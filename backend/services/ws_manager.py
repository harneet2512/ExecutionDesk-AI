"""WebSocket connection manager for real-time market data streaming.

Manages:
- Connection registry (channel -> subscribers, tenant -> connections)
- Subscribe / unsubscribe / broadcast / disconnect
- Max 5 connections per tenant
- Heartbeat ping every 30s
- Background price fetcher polling active symbols
"""
import asyncio
import json
import time
import uuid
from collections import defaultdict
from typing import Dict, Set, Any, Optional

from starlette.websockets import WebSocket, WebSocketState

from backend.core.logging import get_logger

logger = get_logger(__name__)

# Valid channel prefixes
VALID_CHANNEL_PREFIXES = {"prices", "book", "trades"}

# Limits
MAX_CONNECTIONS_PER_TENANT = 5
HEARTBEAT_INTERVAL_S = 30

# Poll intervals by channel type
POLL_INTERVAL_CRYPTO_S = 2
POLL_INTERVAL_PM_S = 5


def _validate_channel(channel: str) -> Optional[str]:
    """Validate channel format.  Returns error message or None if valid."""
    if ":" not in channel:
        return "Invalid channel format. Expected <type>:<symbol>, e.g. prices:BTC-USD"
    prefix, symbol = channel.split(":", 1)
    if prefix not in VALID_CHANNEL_PREFIXES:
        return f"Unknown channel type '{prefix}'. Supported: {', '.join(sorted(VALID_CHANNEL_PREFIXES))}"
    if not symbol:
        return "Channel symbol cannot be empty"
    return None


class _ConnectionInfo:
    """Metadata for a single WebSocket connection."""

    __slots__ = ("ws", "connection_id", "tenant_id", "channels", "connected_at")

    def __init__(self, ws: WebSocket, connection_id: str, tenant_id: str):
        self.ws = ws
        self.connection_id = connection_id
        self.tenant_id = tenant_id
        self.channels: Set[str] = set()
        self.connected_at = time.time()


class WebSocketManager:
    """Central registry for WebSocket connections and channel subscriptions."""

    def __init__(self):
        # channel -> set of _ConnectionInfo
        self._channels: Dict[str, Set[_ConnectionInfo]] = defaultdict(set)
        # tenant_id -> set of _ConnectionInfo
        self._tenant_connections: Dict[str, Set[_ConnectionInfo]] = defaultdict(set)
        # connection_id -> _ConnectionInfo (for fast lookup)
        self._connections: Dict[str, _ConnectionInfo] = {}
        # Background task handle
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._price_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def can_connect(self, tenant_id: str) -> bool:
        """Check whether the tenant has room for another connection."""
        return len(self._tenant_connections[tenant_id]) < MAX_CONNECTIONS_PER_TENANT

    def register(self, ws: WebSocket, tenant_id: str) -> _ConnectionInfo:
        """Register a new WebSocket connection. Caller must verify can_connect first."""
        conn_id = str(uuid.uuid4())
        info = _ConnectionInfo(ws, conn_id, tenant_id)
        self._connections[conn_id] = info
        self._tenant_connections[tenant_id].add(info)
        logger.info(
            "WS connected: conn=%s tenant=%s (total=%d)",
            conn_id[:8], tenant_id, len(self._connections),
        )
        return info

    def disconnect(self, info: _ConnectionInfo) -> None:
        """Remove a connection from all registries."""
        # Remove from channels
        for ch in list(info.channels):
            self._channels[ch].discard(info)
            if not self._channels[ch]:
                del self._channels[ch]
        info.channels.clear()

        # Remove from tenant map
        self._tenant_connections[info.tenant_id].discard(info)
        if not self._tenant_connections[info.tenant_id]:
            del self._tenant_connections[info.tenant_id]

        # Remove from global map
        self._connections.pop(info.connection_id, None)

        logger.info(
            "WS disconnected: conn=%s tenant=%s (remaining=%d)",
            info.connection_id[:8], info.tenant_id, len(self._connections),
        )

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe
    # ------------------------------------------------------------------

    def subscribe(self, info: _ConnectionInfo, channel: str) -> None:
        """Subscribe a connection to a channel (idempotent)."""
        info.channels.add(channel)
        self._channels[channel].add(info)

    def unsubscribe(self, info: _ConnectionInfo, channel: str) -> None:
        """Unsubscribe a connection from a channel (idempotent)."""
        info.channels.discard(channel)
        self._channels[channel].discard(info)
        if not self._channels[channel]:
            del self._channels[channel]

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(self, channel: str, message: dict) -> None:
        """Send a message to all subscribers of a channel."""
        subscribers = list(self._channels.get(channel, set()))
        if not subscribers:
            return
        text = json.dumps(message)
        dead: list[_ConnectionInfo] = []
        for info in subscribers:
            try:
                if info.ws.client_state == WebSocketState.CONNECTED:
                    await info.ws.send_text(text)
            except Exception:
                dead.append(info)
        # Clean up dead connections
        for info in dead:
            self.disconnect(info)

    # ------------------------------------------------------------------
    # Active symbols
    # ------------------------------------------------------------------

    def active_symbols(self) -> Dict[str, Set[str]]:
        """Return mapping of channel_type -> set of symbols being watched."""
        result: Dict[str, Set[str]] = defaultdict(set)
        for channel in self._channels:
            if ":" in channel:
                prefix, symbol = channel.split(":", 1)
                result[prefix].add(symbol)
        return dict(result)

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    async def start_background_tasks(self) -> None:
        """Start heartbeat and price-fetcher tasks (called on app startup)."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self._price_task is None or self._price_task.done():
            self._price_task = asyncio.create_task(self._price_fetch_loop())

    async def stop_background_tasks(self) -> None:
        """Cancel background tasks (called on app shutdown)."""
        for task in (self._heartbeat_task, self._price_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _heartbeat_loop(self) -> None:
        """Send ping frames to all connected clients every HEARTBEAT_INTERVAL_S."""
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                dead: list[_ConnectionInfo] = []
                for info in list(self._connections.values()):
                    try:
                        if info.ws.client_state == WebSocketState.CONNECTED:
                            await info.ws.send_json({"type": "heartbeat", "ts": time.time()})
                    except Exception:
                        dead.append(info)
                for info in dead:
                    self.disconnect(info)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Heartbeat loop error: %s", str(exc)[:200])
                await asyncio.sleep(5)

    async def _price_fetch_loop(self) -> None:
        """Poll market data for actively-subscribed symbols and broadcast."""
        while True:
            try:
                symbols = self.active_symbols()
                price_symbols = symbols.get("prices", set())

                if price_symbols:
                    for symbol in list(price_symbols):
                        try:
                            is_pm = symbol.startswith("pm_")
                            price_data = await self._fetch_price(symbol)
                            if price_data:
                                await self.broadcast(f"prices:{symbol}", {
                                    "type": "price",
                                    "symbol": symbol,
                                    "price": price_data.get("price"),
                                    "change_pct": price_data.get("change_pct"),
                                    "volume_24h": price_data.get("volume_24h"),
                                    "ts": time.time(),
                                })
                        except Exception as exc:
                            logger.debug("Price fetch failed for %s: %s", symbol, str(exc)[:120])

                # Crypto polls every 2s, PM every 5s -- use the shorter interval
                # and let the per-symbol fetch handle timing internally.
                await asyncio.sleep(POLL_INTERVAL_CRYPTO_S)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Price fetch loop error: %s", str(exc)[:200])
                await asyncio.sleep(5)

    async def _fetch_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch current price for a symbol.  Returns dict or None."""
        try:
            from backend.services.market_data import get_price
            price = get_price(symbol)
            if price is not None:
                return {"price": float(price), "change_pct": None, "volume_24h": None}
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return manager statistics."""
        return {
            "total_connections": len(self._connections),
            "total_channels": len(self._channels),
            "tenants": len(self._tenant_connections),
            "channels": {ch: len(subs) for ch, subs in self._channels.items()},
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_manager: Optional[WebSocketManager] = None


def get_ws_manager() -> WebSocketManager:
    """Return the global WebSocket manager singleton."""
    global _manager
    if _manager is None:
        _manager = WebSocketManager()
    return _manager
