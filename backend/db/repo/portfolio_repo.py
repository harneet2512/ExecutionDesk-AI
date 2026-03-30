"""Portfolio snapshots repository."""
from typing import List, Optional, Dict, Any
from backend.db.connect import get_conn


class PortfolioRepo:
    """Repository for portfolio snapshots."""

    def create_snapshot(self, snapshot_data: Dict[str, Any]) -> str:
        """Create a portfolio snapshot."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_id, run_id, tenant_id, balances_json,
                    positions_json, total_value_usd, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_data["snapshot_id"],
                    snapshot_data.get("run_id"),
                    snapshot_data["tenant_id"],
                    snapshot_data["balances_json"],
                    snapshot_data["positions_json"],
                    snapshot_data.get("total_value_usd", 0.0),
                    snapshot_data["ts"],
                )
            )
            conn.commit()
            return snapshot_data["snapshot_id"]

    def get_snapshots_by_run(self, run_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """Get all snapshots for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM portfolio_snapshots WHERE run_id = ? AND tenant_id = ? ORDER BY ts ASC",
                (run_id, tenant_id)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_latest_snapshot(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get latest snapshot for a tenant."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (tenant_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_snapshots_by_tenant(
        self,
        tenant_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get snapshots for a tenant."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (tenant_id, limit)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
