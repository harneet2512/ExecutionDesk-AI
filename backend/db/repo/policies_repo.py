"""Policies repository."""
from typing import List, Optional, Dict, Any
from backend.db.connect import get_conn


class PoliciesRepo:
    """Repository for policies."""

    def create_policy(self, policy_data: Dict[str, Any]) -> str:
        """Create a policy."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO policies (
                    policy_id, tenant_id, name, version, policy_json, created_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    policy_data["policy_id"],
                    policy_data["tenant_id"],
                    policy_data["name"],
                    policy_data.get("version", 1),
                    policy_data["policy_json"],
                )
            )
            conn.commit()
        return policy_data["policy_id"]

    def get_active_policies(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Get active policies for a tenant."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM policies
                WHERE tenant_id = ?
                ORDER BY name, version DESC
                """,
                (tenant_id,)
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_policy(self, policy_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a policy by ID."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM policies WHERE policy_id = ? AND tenant_id = ?",
                (policy_id, tenant_id)
            )
            row = cursor.fetchone()
        return dict(row) if row else None
