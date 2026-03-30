"""Runs repository."""
from typing import List, Optional, Dict, Any
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


class RunsRepo:
    """Repository for runs."""

    def list_runs(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List runs for a tenant."""
        with get_conn() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM runs WHERE tenant_id = ?"
            params = [tenant_id]

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

    def get_run(self, run_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a run by ID."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM runs WHERE run_id = ? AND tenant_id = ?",
                (run_id, tenant_id)
            )
            row = cursor.fetchone()

            return dict(row) if row else None

    def create_run(self, run_data: Dict[str, Any]) -> str:
        """Create a new run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO runs (
                    run_id, tenant_id, status, execution_mode,
                    trace_id, source_run_id, metadata_json, intent_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    run_data["run_id"],
                    run_data["tenant_id"],
                    run_data["status"],
                    run_data.get("execution_mode", "PAPER"),
                    run_data.get("trace_id"),
                    run_data.get("source_run_id"),
                    run_data.get("metadata_json"),
                    run_data.get("intent_json"),
                )
            )
            conn.commit()

            return run_data["run_id"]

    def update_run_status(
        self,
        run_id: str,
        status: str,
        failure_reason: Optional[str] = None,
        failure_code: Optional[str] = None
    ) -> None:
        """Update run status."""
        with get_conn() as conn:
            cursor = conn.cursor()

            if status in ("COMPLETED", "FAILED"):
                cursor.execute(
                    "UPDATE runs SET status = ?, completed_at = datetime('now'), failure_reason = ?, failure_code = ? WHERE run_id = ?",
                    (status, failure_reason, failure_code, run_id)
                )
            elif status == "RUNNING":
                cursor.execute(
                    "UPDATE runs SET status = ?, started_at = datetime('now') WHERE run_id = ?",
                    (status, run_id)
                )
            else:
                cursor.execute(
                    "UPDATE runs SET status = ? WHERE run_id = ?",
                    (status, run_id)
                )

            conn.commit()
