"""Tool calls repository.

Schema (from 001_init.sql):
  id TEXT PK, run_id TEXT, node_id TEXT, tool_name TEXT, mcp_server TEXT,
  request_json TEXT, response_json TEXT, status TEXT, ts TEXT, error_text TEXT
"""
from typing import List, Optional, Dict, Any
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


class ToolCallsRepo:
    """Repository for tool calls."""

    def create_tool_call(self, tool_call_data: Dict[str, Any]) -> str:
        """Create a tool call record."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO tool_calls (
                    id, run_id, node_id,
                    tool_name, mcp_server, request_json, response_json,
                    status, error_text, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    tool_call_data["id"],
                    tool_call_data["run_id"],
                    tool_call_data.get("node_id"),
                    tool_call_data["tool_name"],
                    tool_call_data["mcp_server"],
                    tool_call_data["request_json"],
                    tool_call_data.get("response_json"),
                    tool_call_data["status"],
                    tool_call_data.get("error_text"),
                )
            )
            conn.commit()
            return tool_call_data["id"]

    def update_tool_call(
        self,
        tool_call_id: str,
        response_json: Optional[str] = None,
        status: Optional[str] = None,
        error_text: Optional[str] = None
    ) -> None:
        """Update tool call result."""
        with get_conn() as conn:
            cursor = conn.cursor()

            updates = []
            params = []

            if response_json is not None:
                updates.append("response_json = ?")
                params.append(response_json)
            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if error_text is not None:
                updates.append("error_text = ?")
                params.append(error_text)

            if updates:
                params.append(tool_call_id)
                cursor.execute(
                    f"UPDATE tool_calls SET {', '.join(updates)} WHERE id = ?",
                    params
                )
                conn.commit()

    def get_tool_calls_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all tool calls for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY ts ASC",
                (run_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_tool_calls_by_node(self, node_id: str) -> List[Dict[str, Any]]:
        """Get all tool calls for a node."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM tool_calls WHERE node_id = ? ORDER BY ts ASC",
                (node_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
