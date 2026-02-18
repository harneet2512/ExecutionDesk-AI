"""Retrievals repository."""
from typing import List, Dict, Any
from backend.db.connect import get_conn


class RetrievalsRepo:
    """Repository for retrievals."""

    def create_retrieval(self, retrieval_data: Dict[str, Any]) -> str:
        """Create a retrieval record."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO retrievals (
                    retrieval_id, run_id, query, source_type,
                    doc_ids_json, chunk_ids_json, scores_json,
                    as_of_datetime, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    retrieval_data["retrieval_id"],
                    retrieval_data["run_id"],
                    retrieval_data["query"],
                    retrieval_data.get("source_type"),
                    retrieval_data.get("doc_ids_json"),
                    retrieval_data.get("chunk_ids_json"),
                    retrieval_data.get("scores_json"),
                    retrieval_data["as_of_datetime"],
                )
            )
            conn.commit()
            return retrieval_data["retrieval_id"]

    def get_retrievals_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all retrievals for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM retrievals WHERE run_id = ? ORDER BY created_at ASC",
                (run_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
