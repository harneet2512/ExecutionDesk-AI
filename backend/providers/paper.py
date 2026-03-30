"""Paper trading provider."""
import json
from typing import Dict, Any
from backend.providers.base import BrokerProvider
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.services.market_data import get_price
from backend.core.logging import get_logger

logger = get_logger(__name__)


class PaperProvider(BrokerProvider):
    """Paper trading provider — mirrors Coinbase single-order constraint."""

    def __init__(self):
        from backend.providers.base import BrokerCapabilities
        self.capabilities = BrokerCapabilities(
            max_orders_per_submit=1,
            supports_batch_submit=False,
            sell_uses_base_size=True,
            buy_uses_quote_size=True,
        )

    def place_order(
        self,
        run_id: str,
        tenant_id: str,
        symbol: str,
        side: str,
        notional_usd: float,
        qty: float = None
    ) -> str:
        """Place an order with realistic lifecycle."""
        order_id = new_id("ord_")
        price = get_price(symbol)
        
        if qty is None:
            qty = notional_usd / price
        
        # Create order (SUBMITTED then FILLED)
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Insert order with fill columns populated
            now = now_iso()
            cursor.execute(
                """
                INSERT INTO orders (
                    order_id, run_id, tenant_id, provider, symbol, side,
                    order_type, qty, notional_usd, status, created_at,
                    filled_qty, avg_fill_price, total_fees, status_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (order_id, run_id, tenant_id, "PAPER", symbol, side.upper(), "MARKET", qty, notional_usd, "FILLED", now,
                 qty, price, 0.0, now)
            )
            
            # Insert order events
            submitted_ts = now_iso()
            event1_id = new_id("evt_")
            cursor.execute(
                """
                INSERT INTO order_events (id, order_id, event_type, payload_json, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event1_id, order_id, "SUBMITTED", json.dumps({"order_id": order_id}), submitted_ts)
            )
            
            filled_ts = now_iso()
            latency_ms = 50  # Simulated latency
            event2_id = new_id("evt_")
            cursor.execute(
                """
                INSERT INTO order_events (id, order_id, event_type, payload_json, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event2_id, order_id, "FILLED", json.dumps({
                    "order_id": order_id,
                    "price": price,
                    "qty": qty,
                    "latency_ms": latency_ms
                }), filled_ts)
            )
            
            # Get current portfolio state
            balances, positions, _ = self._get_portfolio_state(conn, cursor, tenant_id)
            
            # Update portfolio state
            if side.upper() == "BUY":
                balances["USD"] = balances.get("USD", 100.0) - notional_usd
                positions[symbol] = positions.get(symbol, 0.0) + qty
            elif side.upper() == "SELL":
                balances["USD"] = balances.get("USD", 100.0) + notional_usd
                positions[symbol] = positions.get(symbol, 0.0) - qty
                if positions.get(symbol, 0) <= 0:
                    if symbol in positions:
                        del positions[symbol]
            
            # Calculate total value
            total_value = balances.get("USD", 0.0)
            for pos_symbol, pos_qty in positions.items():
                try:
                    pos_price = get_price(pos_symbol)
                    total_value += pos_qty * pos_price
                except Exception:
                    pass
            
            # Create portfolio snapshot
            snapshot_id = new_id("snap_")
            cursor.execute(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_id, run_id, tenant_id, balances_json, positions_json, total_value_usd, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, run_id, tenant_id, json.dumps(balances), json.dumps(positions), total_value, now_iso())
            )
            
            conn.commit()
        
        return order_id
    
    def _get_portfolio_state(self, conn, cursor, tenant_id: str):
        """Get current portfolio state from latest snapshot or default."""
        # Note: conn is already in context manager, don't use it here
        cursor.execute(
            """
            SELECT balances_json, positions_json, total_value_usd
            FROM portfolio_snapshots
            WHERE tenant_id = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (tenant_id,)
        )
        row = cursor.fetchone()
        
        if row:
            balances = json.loads(row["balances_json"])
            positions = json.loads(row["positions_json"])
            total_value = row["total_value_usd"]
        else:
            # Initialize with default
            balances = {"USD": 100.0}
            positions = {}
            total_value = 100.0
        
        return balances, positions, total_value
    
    def get_positions(self, tenant_id: str) -> Dict[str, Any]:
        """Get current positions."""
        with get_conn() as conn:
            cursor = conn.cursor()
            balances, positions, total_value = self._get_portfolio_state(conn, cursor, tenant_id)
            return {
                "positions": positions,
                "total_value": total_value
            }
    
    def get_balances(self, tenant_id: str) -> Dict[str, Any]:
        """Get account balances."""
        with get_conn() as conn:
            cursor = conn.cursor()
            balances, _, _ = self._get_portfolio_state(conn, cursor, tenant_id)
            return {"balances": balances}
