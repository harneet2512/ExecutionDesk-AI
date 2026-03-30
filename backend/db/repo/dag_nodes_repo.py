"""DAG nodes repository.

Schema (from 001_init.sql):
  node_id TEXT PK, run_id TEXT, name TEXT, node_type TEXT, status TEXT,
  started_at TEXT, completed_at TEXT, inputs_json TEXT, outputs_json TEXT, error_json TEXT
"""
from typing import List, Optional, Dict, Any
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


class DAGNodesRepo:
    """Repository for DAG nodes."""

    def create_node(self, node_data: Dict[str, Any]) -> str:
        """Create a DAG node."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO dag_nodes (
                    node_id, run_id, name, node_type, status,
                    inputs_json, outputs_json, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    node_data["node_id"],
                    node_data["run_id"],
                    node_data["name"],
                    node_data["node_type"],
                    node_data["status"],
                    node_data.get("inputs_json"),
                    node_data.get("outputs_json"),
                )
            )
            conn.commit()
            return node_data["node_id"]

    def update_node(
        self,
        node_id: str,
        status: str,
        outputs_json: Optional[str] = None,
        error_json: Optional[str] = None
    ) -> None:
        """Update node status."""
        with get_conn() as conn:
            cursor = conn.cursor()

            if status == "COMPLETED":
                cursor.execute(
                    """
                    UPDATE dag_nodes
                    SET status = ?, outputs_json = ?, completed_at = datetime('now')
                    WHERE node_id = ?
                    """,
                    (status, outputs_json, node_id)
                )
            elif status == "FAILED":
                cursor.execute(
                    """
                    UPDATE dag_nodes
                    SET status = ?, error_json = ?, completed_at = datetime('now')
                    WHERE node_id = ?
                    """,
                    (status, error_json, node_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE dag_nodes
                    SET status = ?
                    WHERE node_id = ?
                    """,
                    (status, node_id)
                )
            conn.commit()

    def get_nodes_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all nodes for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM dag_nodes WHERE run_id = ? ORDER BY started_at ASC",
                (run_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a node by ID."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM dag_nodes WHERE node_id = ?", (node_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
