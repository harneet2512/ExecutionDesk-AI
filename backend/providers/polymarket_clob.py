"""Polymarket CLOB broker provider.

Connects to the Polymarket Central Limit Order Book (CLOB) API
for placing limit orders on prediction market outcomes.
"""
import json
import time
from typing import Dict, Any, Optional, List

import httpx

from backend.providers.base import BrokerProvider, BrokerCapabilities
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger
from backend.core.config import get_settings

logger = get_logger(__name__)


class PolymarketProvider(BrokerProvider):
    """Polymarket CLOB provider for prediction market trading."""

    BASE_URL = "https://clob.polymarket.com"

    # Map CLOB order statuses to internal status values
    STATUS_MAP: Dict[str, str] = {
        "LIVE": "SUBMITTED",
        "MATCHED": "FILLED",
        "CANCELED": "CANCELLED",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        settings = get_settings()
        self.api_key = api_key or getattr(settings, "polymarket_api_key", None) or ""
        self.api_secret = api_secret or getattr(settings, "polymarket_api_secret", None) or ""

        # Polymarket CLOB only supports limit orders
        self.capabilities = BrokerCapabilities(
            max_orders_per_submit=1,
            supports_batch_submit=False,
            sell_uses_base_size=True,
            buy_uses_quote_size=False,
        )

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_limit_price(price: float) -> None:
        """Validate that *price* is a legal Polymarket limit price.

        Polymarket outcome shares trade between $0.01 and $0.99 inclusive.
        Raises ``ValueError`` if the price is outside that range.
        """
        if price < 0.01 or price > 0.99:
            raise ValueError(
                f"Limit price {price} out of range. "
                "Polymarket prices must be between 0.01 and 0.99 inclusive."
            )

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _clob_request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send an HTTP request to the Polymarket CLOB API.

        Retries up to 3 times on HTTP 429 (rate-limit) responses using
        exponential backoff starting at 1 second.
        """
        url = f"{self.BASE_URL}{path}"
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["POLY_API_KEY"] = self.api_key
        if self.api_secret:
            headers["POLY_API_SECRET"] = self.api_secret

        max_attempts = 3
        backoff_seconds = 1

        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.request(
                        method=method.upper(),
                        url=url,
                        headers=headers,
                        json=json_body if json_body else None,
                    )

                    if response.status_code == 429:
                        if attempt < max_attempts:
                            wait_time = backoff_seconds * (2 ** (attempt - 1))
                            logger.warning(
                                "Polymarket rate limited (429), retrying after %ss "
                                "(attempt %s/%s)",
                                wait_time, attempt, max_attempts,
                            )
                            time.sleep(wait_time)
                            continue

                    response.raise_for_status()
                    return response.json()

            except httpx.HTTPStatusError:
                if attempt >= max_attempts:
                    raise
                wait_time = backoff_seconds * (2 ** (attempt - 1))
                time.sleep(wait_time)
            except Exception:
                if attempt >= max_attempts:
                    raise
                wait_time = backoff_seconds * (2 ** (attempt - 1))
                time.sleep(wait_time)

        return {}

    # ------------------------------------------------------------------
    # BrokerProvider interface
    # ------------------------------------------------------------------

    def place_order(
        self,
        run_id: str,
        tenant_id: str,
        symbol: str,
        side: str,
        notional_usd: float,
        qty: float = None,
        outcome: str = "YES",
        limit_price: float = None,
    ) -> str:
        """Place a limit order on the Polymarket CLOB.

        Parameters
        ----------
        run_id : str
            Current execution run identifier.
        tenant_id : str
            Tenant placing the order.
        symbol : str
            Polymarket condition/token ID.
        side : str
            ``"BUY"`` or ``"SELL"``.
        notional_usd : float
            Dollar value of the order.
        qty : float, optional
            Explicit share quantity. When *None*, calculated from
            ``notional_usd / limit_price``.
        outcome : str
            ``"YES"`` or ``"NO"`` outcome token (default ``"YES"``).
        limit_price : float
            Required limit price between 0.01 and 0.99.

        Returns
        -------
        str
            Internal order ID.
        """
        if limit_price is None:
            raise ValueError("limit_price is required for Polymarket CLOB orders")

        self._validate_limit_price(limit_price)

        side_upper = side.upper()

        # Compute quantity from notional if not provided
        if qty is None or qty <= 0:
            qty = notional_usd / limit_price

        order_id = new_id("ord_")
        client_order_id = new_id("pm_")
        start_time = time.time()

        payload = {
            "tokenID": symbol,
            "side": side_upper,
            "price": str(limit_price),
            "size": str(qty),
            "outcome": outcome.upper(),
            "type": "GTC",  # Good-Til-Cancelled
        }

        try:
            result = self._clob_request("POST", "/order", json_body=payload)
            latency_ms = int((time.time() - start_time) * 1000)

            # Extract CLOB-assigned order ID if present
            clob_order_id = result.get("orderID") or result.get("id") or ""
            clob_status = result.get("status", "LIVE")
            internal_status = self.STATUS_MAP.get(clob_status, "SUBMITTED")

            logger.info(
                "Polymarket order placed: %s side=%s price=%s qty=%s symbol=%s "
                "clob_id=%s status=%s latency=%sms",
                order_id, side_upper, limit_price, qty, symbol,
                clob_order_id, internal_status, latency_ms,
            )

            # Persist order to DB
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO orders (
                        order_id, run_id, tenant_id, provider, symbol, side,
                        order_type, qty, notional_usd, status, created_at,
                        client_order_id, avg_fill_price
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id, run_id, tenant_id, "POLYMARKET", symbol,
                        side_upper, "LIMIT", qty, notional_usd, internal_status,
                        now_iso(), client_order_id, limit_price,
                    ),
                )

                # Store order event
                event_id = new_id("evt_")
                cursor.execute(
                    """
                    INSERT INTO order_events (id, order_id, event_type, payload_json, ts)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event_id, order_id, internal_status,
                        json.dumps({
                            "clob_order_id": clob_order_id,
                            "outcome": outcome.upper(),
                            "limit_price": limit_price,
                            "size": qty,
                            "clob_status": clob_status,
                        }, default=str),
                        now_iso(),
                    ),
                )
                conn.commit()

            return order_id

        except Exception as exc:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Polymarket place_order failed: %s (latency=%sms)", exc, latency_ms,
            )

            # Persist failed order for auditability
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO orders (
                        order_id, run_id, tenant_id, provider, symbol, side,
                        order_type, qty, notional_usd, status, created_at,
                        client_order_id, status_reason, status_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id, run_id, tenant_id, "POLYMARKET", symbol,
                        side_upper, "LIMIT", qty, notional_usd, "FAILED",
                        now_iso(), client_order_id, str(exc), now_iso(),
                    ),
                )
                conn.commit()
            raise

    def get_positions(self, tenant_id: str) -> Dict[str, Any]:
        """Get current Polymarket positions for *tenant_id*."""
        try:
            data = self._clob_request("GET", "/positions")

            positions: List[Dict[str, Any]] = []
            for pos in data if isinstance(data, list) else data.get("positions", []):
                size = float(pos.get("size", 0))
                avg_price = float(pos.get("avgPrice", pos.get("avg_price", 0)))
                current_price = float(pos.get("currentPrice", pos.get("current_price", 0)))
                unrealized_pnl = (current_price - avg_price) * size if size else 0.0

                positions.append({
                    "market": pos.get("market") or pos.get("conditionId", ""),
                    "outcome": pos.get("outcome", ""),
                    "size": size,
                    "avg_price": avg_price,
                    "current_price": current_price,
                    "unrealized_pnl": round(unrealized_pnl, 4),
                })

            return {"positions": positions}

        except Exception as exc:
            logger.error("Polymarket get_positions failed: %s", exc)
            return {"positions": []}

    def get_balances(
        self,
        tenant_id: str,
        run_id: str = None,
        node_id: str = None,
    ) -> Dict[str, Any]:
        """Get USDC balance on Polymarket for *tenant_id*."""
        try:
            data = self._clob_request("GET", "/balance")

            usdc_balance = float(
                data.get("balance", data.get("usdc", data.get("available", 0)))
            )

            return {
                "balances": {
                    "USDC": usdc_balance,
                },
            }

        except Exception as exc:
            logger.error("Polymarket get_balances failed: %s", exc)
            return {"balances": {"USDC": 0.0}}

    def get_fills(
        self,
        order_id: str,
        run_id: str = None,
        node_id: str = None,
    ) -> List[Dict[str, Any]]:
        """Get fills for a Polymarket order.

        Queries the CLOB ``/trades`` endpoint filtered by *order_id*, then
        falls back to locally stored fills in the ``fills`` table.
        """
        # Try CLOB API first
        try:
            data = self._clob_request("GET", f"/trades?order_id={order_id}")
            trades = data if isinstance(data, list) else data.get("trades", [])
            if trades:
                return [
                    {
                        "trade_id": t.get("id", ""),
                        "price": float(t.get("price", 0)),
                        "size": float(t.get("size", 0)),
                        "side": t.get("side", ""),
                        "fee": float(t.get("fee", 0)),
                        "timestamp": t.get("timestamp", ""),
                    }
                    for t in trades
                ]
        except Exception as exc:
            logger.warning("Polymarket CLOB get_fills failed, falling back to DB: %s", exc)

        # Fallback: local fills table
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM fills WHERE order_id = ? ORDER BY filled_at",
                    (order_id,),
                )
                rows = cursor.fetchall()
                return [
                    {
                        "trade_id": row["trade_id"] if row["trade_id"] else "",
                        "price": float(row["price"]),
                        "size": float(row["size"]),
                        "fee": float(row["fee"]),
                        "timestamp": row["filled_at"],
                    }
                    for row in rows
                ]
        except Exception as exc:
            logger.error("Polymarket get_fills DB fallback failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Polymarket-specific methods
    # ------------------------------------------------------------------

    def get_order_book(self, token_id: str) -> Dict[str, Any]:
        """Get the order book for a Polymarket token.

        Parameters
        ----------
        token_id : str
            The token (outcome) identifier on Polymarket.

        Returns
        -------
        dict
            ``{"bids": [...], "asks": [...], "spread": float,
            "depth": {"bid_depth": int, "ask_depth": int}}``
        """
        try:
            data = self._clob_request("GET", f"/book?token_id={token_id}")

            bids = data.get("bids", [])
            asks = data.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else 0.0
            best_ask = float(asks[0]["price"]) if asks else 0.0
            spread = round(best_ask - best_bid, 4) if (best_bid and best_ask) else 0.0

            bid_depth = sum(int(float(b.get("size", 0))) for b in bids)
            ask_depth = sum(int(float(a.get("size", 0))) for a in asks)

            return {
                "bids": bids,
                "asks": asks,
                "spread": spread,
                "depth": {
                    "bid_depth": bid_depth,
                    "ask_depth": ask_depth,
                },
            }

        except Exception as exc:
            logger.error("Polymarket get_order_book failed for %s: %s", token_id, exc)
            return {
                "bids": [],
                "asks": [],
                "spread": 0.0,
                "depth": {"bid_depth": 0, "ask_depth": 0},
            }
