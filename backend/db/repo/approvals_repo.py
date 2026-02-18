"""Approvals repository."""
from typing import List, Optional, Dict, Any
from backend.db.connect import get_conn


class ApprovalsRepo:
    """Repository for approvals."""

    def create_approval(self, approval_data: Dict[str, Any]) -> str:
        """Create an approval request."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO approvals (
                    approval_id, run_id, tenant_id, status, created_at
                ) VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (
                    approval_data["approval_id"],
                    approval_data["run_id"],
                    approval_data["tenant_id"],
                    approval_data["status"],
                )
            )
            conn.commit()
        return approval_data["approval_id"]

    def get_pending_approvals(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Get pending approvals for a tenant."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM approvals
                WHERE tenant_id = ? AND status = 'PENDING'
                ORDER BY created_at DESC
                """,
                (tenant_id,)
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_approval(self, approval_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get an approval by ID."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM approvals WHERE approval_id = ? AND tenant_id = ?",
                (approval_id, tenant_id)
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def update_approval(
        self,
        approval_id: str,
        status: str,
        decided_by: str,
        comment: Optional[str] = None
    ) -> None:
        """Update approval decision."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE approvals
                SET status = ?, decided_by = ?, decided_at = datetime('now'), comment = ?
                WHERE approval_id = ?
                """,
                (status, decided_by, comment, approval_id)
            )
            conn.commit()
