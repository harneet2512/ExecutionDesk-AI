"""WebSocket endpoint for real-time market data streaming.

Endpoint: ws://localhost:8000/api/v1/ws/market-data
Auth:     ?tenant=<id>  (dev mode) | ?token=<JWT> | ?api_key=edai_...
Channels: prices:BTC-USD, book:BTC-USD, trades:BTC-USD, prices:pm_market_123

Client messages:
  {"action": "subscribe",   "channel": "prices:BTC-USD"}
  {"action": "unsubscribe", "channel": "prices:BTC-USD"}
  {"action": "ping"}

Server messages:
  {"type": "connected",    "connection_id": "..."}
  {"type": "subscribed",   "channel": "prices:BTC-USD"}
  {"type": "unsubscribed", "channel": "prices:BTC-USD"}
  {"type": "pong"}
  {"type": "price",        "symbol": "BTC-USD", "price": 67500.0, ...}
  {"type": "heartbeat",    "ts": ...}
  {"type": "error",        "message": "..."}
"""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.core.logging import get_logger
from backend.services.ws_manager import get_ws_manager, _validate_channel

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# HTTP helper: broadcast to channel (used by backend services and tests)
# ---------------------------------------------------------------------------

class BroadcastRequest(BaseModel):
    channel: str
    message: dict


@router.post("/ws/broadcast")
async def post_broadcast(req: BroadcastRequest):
    """Broadcast a message to all WebSocket subscribers of a channel.

    Intended for internal use by backend services (e.g., after a fill) and
    for integration tests that need to trigger broadcasts.
    """
    mgr = get_ws_manager()
    await mgr.broadcast(req.channel, req.message)
    return {"ok": True, "channel": req.channel}


@router.get("/ws/stats")
async def get_ws_stats():
    """Return WebSocket manager statistics (connections, channels)."""
    mgr = get_ws_manager()
    return mgr.stats()


def _resolve_tenant(
    token: Optional[str] = None,
    api_key: Optional[str] = None,
    tenant: Optional[str] = None,
) -> Optional[str]:
    """Resolve tenant_id from query params.

    Priority: JWT token > api_key > tenant query param (dev mode).
    Returns tenant_id or None if auth fails.
    """
    # JWT token auth
    if token:
        try:
            from backend.core.security import decode_access_token
            payload = decode_access_token(token)
            if payload and payload.get("tenant_id"):
                return payload["tenant_id"]
        except Exception:
            pass

    # API key auth (future)
    if api_key and api_key.startswith("edai_"):
        # Placeholder for API key resolution
        pass

    # Dev mode: ?tenant=... (mirrors SSE / X-Dev-Tenant pattern)
    from backend.core.config import get_settings
    settings = get_settings()
    if settings.test_auth_bypass:
        return tenant or "t_default"
    if not settings.enable_dev_auth and settings.api_secret_key == "dev-secret-key-change-in-production":
        return tenant or "t_default"

    return None


@router.websocket("/ws/market-data")
async def ws_market_data(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None),
    tenant: Optional[str] = Query(None),
):
    """WebSocket endpoint for streaming market data."""
    # Resolve tenant
    tenant_id = _resolve_tenant(token=token, api_key=api_key, tenant=tenant)
    if not tenant_id:
        await websocket.close(code=4001, reason="Authentication required")
        return

    mgr = get_ws_manager()

    # Enforce connection limit
    if not mgr.can_connect(tenant_id):
        await websocket.close(
            code=4002,
            reason=f"Connection limit reached (max {mgr.MAX_CONNECTIONS_PER_TENANT if hasattr(mgr, 'MAX_CONNECTIONS_PER_TENANT') else 5})",
        )
        return

    await websocket.accept()

    # Register
    info = mgr.register(websocket, tenant_id)

    try:
        # Send welcome
        await websocket.send_json({
            "type": "connected",
            "connection_id": info.connection_id,
            "tenant_id": tenant_id,
        })

        # Message loop
        while True:
            raw = await websocket.receive_text()

            # Parse JSON
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                })
                continue

            action = msg.get("action")

            if action == "subscribe":
                channel = msg.get("channel", "")
                err = _validate_channel(channel)
                if err:
                    await websocket.send_json({"type": "error", "message": err})
                    continue
                mgr.subscribe(info, channel)
                await websocket.send_json({
                    "type": "subscribed",
                    "channel": channel,
                })

            elif action == "unsubscribe":
                channel = msg.get("channel", "")
                mgr.unsubscribe(info, channel)
                await websocket.send_json({
                    "type": "unsubscribed",
                    "channel": channel,
                })

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS error for conn=%s: %s", info.connection_id[:8], str(exc)[:200])
    finally:
        mgr.disconnect(info)
