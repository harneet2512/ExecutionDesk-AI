"""Policy events repository."""
from typing import List, Dict, Any
from backend.db.connect import get_conn


class PolicyEventsRepo:
    """Repository for policy events."""

    def create_policy_event(self, event_data: Dict[str, Any]) -> str:
        """Create a policy event."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO policy_events (
                    id, run_id, policy_id, decision, reasons_json, created_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    event_data["id"],
                    event_data["run_id"],
                    event_data.get("policy_id"),
                    event_data["decision"],
                    event_data.get("reasons_json"),
                )
            )
            conn.commit()
            return event_data["id"]

    def get_events_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all policy events for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM policy_events WHERE run_id = ? ORDER BY created_at ASC",
                (run_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
