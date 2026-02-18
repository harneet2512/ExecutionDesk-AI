"""Run events repository."""
from typing import List, Dict, Any
from backend.db.connect import get_conn


class RunEventsRepo:
    """Repository for run events (SSE streaming)."""

    def create_event(self, event_data: Dict[str, Any]) -> str:
        """Create a run event."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO run_events (
                    id, run_id, tenant_id, event_type, payload_json, ts
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_data["id"],
                    event_data["run_id"],
                    event_data["tenant_id"],
                    event_data["event_type"],
                    event_data["payload_json"],
                    event_data["ts"],
                )
            )
            conn.commit()
            return event_data["id"]

    def get_events_by_run(self, run_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """Get all events for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? AND tenant_id = ?
                ORDER BY ts ASC
                """,
                (run_id, tenant_id)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
