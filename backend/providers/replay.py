"""Replay provider - copies orders from source run."""
import json
from typing import Dict, Any
from backend.providers.base import BrokerProvider
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso


class ReplayProvider(BrokerProvider):
    """Replay provider - copies orders from source run."""
    
    def __init__(self, source_run_id: str):
        self.source_run_id = source_run_id
    
    def place_order(
        self,
        run_id: str,
        tenant_id: str,
        symbol: str,
        side: str,
        notional_usd: float,
        qty: float = None
    ) -> str:
        """Replay: copy orders from source run."""
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Find matching order in source run
            cursor.execute(
                """
                SELECT order_id, symbol, side, notional_usd, qty
                FROM orders
                WHERE run_id = ? AND symbol = ? AND side = ?
                LIMIT 1
                """,
                (self.source_run_id, symbol, side.upper())
            )
            source_order = cursor.fetchone()
            
            if not source_order:
                raise ValueError(f"No matching order found in source run {self.source_run_id}")
            
            # Create new order with same data
            new_order_id = new_id("ord_")
            cursor.execute(
                """
                INSERT INTO orders (
                    order_id, run_id, tenant_id, provider, symbol, side,
                    order_type, qty, notional_usd, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_order_id, run_id, tenant_id, "REPLAY", symbol, side.upper(), "MARKET",
                 source_order["qty"], source_order["notional_usd"], "FILLED", now_iso())
            )
            
            # Copy order events
            cursor.execute(
                "SELECT event_type, payload_json, ts FROM order_events WHERE order_id = ?",
                (source_order["order_id"],)
            )
            source_events = cursor.fetchall()
            
            for event in source_events:
                event_id = new_id("evt_")
                cursor.execute(
                    """
                    INSERT INTO order_events (id, order_id, event_type, payload_json, ts)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_id, new_order_id, event["event_type"], event["payload_json"], event["ts"])
                )
            
            conn.commit()
        
        return new_order_id
    
    def get_positions(self, tenant_id: str) -> Dict[str, Any]:
        """Get positions (not applicable for replay)."""
        return {"positions": {}, "total_value": 0.0}
    
    def get_balances(self, tenant_id: str) -> Dict[str, Any]:
        """Get balances (not applicable for replay)."""
        return {"balances": {"USD": 0.0}}
