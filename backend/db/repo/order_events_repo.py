"""Order events repository."""
from typing import List, Dict, Any
from backend.db.connect import get_conn


class OrderEventsRepo:
    """Repository for order events."""

    def create_order_event(self, event_data: Dict[str, Any]) -> str:
        """Create an order event."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO order_events (
                    id, order_id, event_type, payload_json, ts
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_data["id"],
                    event_data["order_id"],
                    event_data["event_type"],
                    event_data["payload_json"],
                    event_data["ts"],
                )
            )
            conn.commit()
            return event_data["id"]

    def get_events_by_order(self, order_id: str) -> List[Dict[str, Any]]:
        """Get all events for an order."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM order_events WHERE order_id = ? ORDER BY ts ASC",
                (order_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_events_by_run(self, run_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """Get all order events for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT oe.* FROM order_events oe
                JOIN orders o ON oe.order_id = o.order_id
                WHERE o.run_id = ? AND o.tenant_id = ?
                ORDER BY oe.ts ASC
                """,
                (run_id, tenant_id)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
