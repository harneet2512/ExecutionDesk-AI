"""Execution trace API endpoint."""
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from backend.api.deps import require_viewer
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _safe_json_loads(s, default=None):
    """Parse JSON safely, returning default on failure."""
    if not s:
        return default if default is not None else {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


@router.get("/{run_id}/trace")
async def get_trace(run_id: str, user: dict = Depends(require_viewer)):
    """
    Get execution trace: plan + current step statuses + latest key artifacts.
    
    Returns:
    {
        "plan": {...},
        "steps": [{step_id, step_name, status, ...}],
        "artifacts": {
            "rankings": [...],
            "candles_batches": [...],
            "tool_calls": [...]
        },
        "current_step": {...},
        "status": "RUNNING" | "COMPLETED" | "PAUSED" | "FAILED"
    }
    """
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get run
        cursor.execute(
            """
            SELECT command_text, parsed_intent_json, execution_plan_json, trace_id, status
            FROM runs WHERE run_id = ? AND tenant_id = ?
            """,
            (run_id, tenant_id)
        )
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        
        execution_plan = json.loads(row["execution_plan_json"]) if row and "execution_plan_json" in row.keys() and row["execution_plan_json"] else None
        parsed_intent = json.loads(row["parsed_intent_json"]) if row and "parsed_intent_json" in row.keys() and row["parsed_intent_json"] else None
        
        # Get steps (dag_nodes)
        cursor.execute(
            """
            SELECT node_id, name, status, started_at, completed_at, outputs_json, error_json
            FROM dag_nodes WHERE run_id = ? ORDER BY started_at ASC
            """,
            (run_id,)
        )
        nodes = cursor.fetchall()
        
        # Get recent events (last 50 for trace)
        cursor.execute(
            """
            SELECT event_type, payload_json, ts
            FROM run_events WHERE run_id = ? ORDER BY ts DESC LIMIT 50
            """,
            (run_id,)
        )
        events = cursor.fetchall()
        
        # Get artifacts
        cursor.execute(
            "SELECT ranking_id, table_json, selected_symbol, selected_score FROM rankings WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,)
        )
        ranking_row = cursor.fetchone()
        rankings = _safe_json_loads(ranking_row["table_json"], []) if ranking_row else []
        
        cursor.execute(
            "SELECT batch_id, symbol, candles_json FROM market_candles_batches WHERE run_id = ? ORDER BY ts DESC LIMIT 5",
            (run_id,)
        )
        candles_batches = []
        for batch_row in cursor.fetchall():
            candles_batches.append({
                "batch_id": batch_row["batch_id"],
                "symbol": batch_row["symbol"],
                "candles_count": len(_safe_json_loads(batch_row["candles_json"], []))
            })
        
        cursor.execute(
            "SELECT id, tool_name, mcp_server, status FROM tool_calls WHERE run_id = ? ORDER BY ts DESC LIMIT 20",
            (run_id,)
        )
        tool_calls = [dict(tc) for tc in cursor.fetchall()]
        
        # Build steps list
        steps = []
        for node in nodes:
            node_dict = dict(node)
            steps.append({
                "step_id": node_dict["node_id"],
                "step_name": node_dict["name"],
                "status": node_dict["status"],
                "started_at": node_dict.get("started_at"),
                "completed_at": node_dict.get("completed_at"),
                "has_output": bool(node_dict.get("outputs_json")),
                "has_error": bool(node_dict.get("error_json"))
            })
        
        # Find current step (first incomplete)
        current_step = None
        for step in steps:
            if step["status"] in ("RUNNING", "PENDING"):
                current_step = step
                break
        if not current_step and steps:
            current_step = steps[-1]  # Last completed step
        
        # Build trace response
        trace = {
            "plan": execution_plan,
            "parsed_intent": parsed_intent,
            "steps": steps,
            "artifacts": {
                "rankings": rankings[:10],  # Top 10
                "candles_batches": candles_batches,
                "tool_calls": tool_calls
            },
            "current_step": current_step,
            "status": row["status"],
            "trace_id": row["trace_id"] if row and "trace_id" in row.keys() else None,
            "recent_events": [{"event_type": e["event_type"], "payload": _safe_json_loads(e["payload_json"], {}), "ts": e["ts"]} for e in events[:10]]
        }
        
        # Fetch portfolio_brief artifact if available (for PortfolioCard component)
        try:
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts
                   WHERE run_id = ? AND artifact_type = 'portfolio_brief'
                   ORDER BY created_at DESC LIMIT 1""",
                (run_id,)
            )
            pf_row = cursor.fetchone()
            if pf_row:
                trace["portfolio_brief"] = _safe_json_loads(pf_row["artifact_json"])
        except Exception:
            pass  # Table may not exist or no artifact

        response = JSONResponse(content=trace)
        if row and "trace_id" in row.keys() and row["trace_id"]:
            response.headers["X-Trace-ID"] = row["trace_id"]

        return response
