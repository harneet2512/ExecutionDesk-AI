"""Orders repository."""
from typing import List, Optional, Dict, Any
from backend.db.connect import get_conn


class OrdersRepo:
    """Repository for orders."""

    def create_order(self, order_data: Dict[str, Any]) -> str:
        """Create an order."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO orders (
                    order_id, run_id, tenant_id, provider, symbol, side,
                    order_type, qty, notional_usd, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    order_data["order_id"],
                    order_data["run_id"],
                    order_data["tenant_id"],
                    order_data["provider"],
                    order_data["symbol"],
                    order_data["side"],
                    order_data["order_type"],
                    order_data.get("qty"),
                    order_data["notional_usd"],
                    order_data["status"],
                )
            )
            conn.commit()
        return order_data["order_id"]

    def update_order_status(self, order_id: str, status: str) -> None:
        """Update order status."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "UPDATE orders SET status = ? WHERE order_id = ?",
                (status, order_id)
            )
            conn.commit()

    def get_orders_by_run(self, run_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """Get all orders for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM orders WHERE run_id = ? AND tenant_id = ? ORDER BY created_at ASC",
                (run_id, tenant_id)
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_order(self, order_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get an order by ID."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM orders WHERE order_id = ? AND tenant_id = ?",
                (order_id, tenant_id)
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def get_orders_by_tenant(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get orders for a tenant."""
        with get_conn() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM orders WHERE tenant_id = ?"
            params: list = [tenant_id]

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
        return [dict(row) for row in rows]
