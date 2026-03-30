"""Runs API routes."""
import asyncio
import sqlite3
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, Response, JSONResponse
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
import json
from backend.api.deps import get_current_user, require_viewer, require_trader
from backend.orchestrator.runner import create_run, execute_run
from backend.orchestrator.event_pubsub import event_pubsub
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def _structured_run_error(status_code: int, code: str, message: str, request_id: str):
    """Return structured JSON error with X-Request-ID header."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={"X-Request-ID": request_id},
    )

router = APIRouter()


class RunTrigger(BaseModel):
    execution_mode: str = Field("PAPER", pattern="^(PAPER|LIVE|REPLAY)$")
    source_run_id: Optional[str] = Field(None, max_length=100)
    
    model_config = {"extra": "forbid"}


class RunResponse(BaseModel):
    run_id: str
    tenant_id: str
    status: str
    execution_mode: str
    created_at: str
    trace_id: Optional[str] = None


@router.post("/trigger")
async def trigger_run(
    trigger: RunTrigger,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_trader),
    request: Request = None
):
    """Trigger a new run."""
    request_id = getattr(request.state, 'request_id', None) if request else str(uuid.uuid4())[:8]
    tenant_id = user["tenant_id"]

    try:
        return await _trigger_run_impl(trigger, tenant_id, request_id, background_tasks, request)
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        err_lower = str(e).lower()
        if "database is locked" in err_lower:
            return _structured_run_error(503, "DB_BUSY", "Database busy, please retry", request_id)
        return _structured_run_error(503, "DB_ERROR", str(e)[:200], request_id)
    except Exception as e:
        try:
            logger.error("trigger_run_error: %s | req=%s", str(e)[:200], request_id)
        except Exception:
            pass
        return _structured_run_error(500, "INTERNAL_ERROR", "Failed to trigger run", request_id)


async def _trigger_run_impl(trigger, tenant_id, request_id, background_tasks, request):
    """Internal implementation of trigger_run."""
    execution_mode = trigger.execution_mode
    source_run_id = trigger.source_run_id

    if execution_mode == "REPLAY" and not source_run_id:
        raise HTTPException(
            status_code=400,
            detail="source_run_id is required when execution_mode is REPLAY"
        )

    if source_run_id:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT run_id FROM runs WHERE run_id = ? AND tenant_id = ?",
                (source_run_id, tenant_id)
            )
            if not cursor.fetchone():
                raise HTTPException(
                    status_code=404,
                    detail=f"Source run {source_run_id} not found"
                )

    run_id = create_run(tenant_id, execution_mode, source_run_id=source_run_id)
    background_tasks.add_task(execute_run, run_id)

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT run_id, tenant_id, status, execution_mode, created_at, trace_id, source_run_id FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()

    result_dict = dict(row) if row else {}
    trace_id = result_dict.get("trace_id") if result_dict else None

    response = JSONResponse(content=result_dict)
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    if request_id:
        response.headers["X-Request-ID"] = request_id

    return response


@router.get("", response_model=List[RunResponse])
async def list_runs(user: dict = Depends(require_viewer)):  # Any authenticated user
    """List runs."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT run_id, tenant_id, status, execution_mode, created_at, trace_id
            FROM runs
            WHERE tenant_id = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (tenant_id,)
        )
        rows = cursor.fetchall()
    
    return [RunResponse(**dict(row)) for row in rows]


class RunStatusResponse(BaseModel):
    """Minimal status response for frequent polling."""
    run_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    current_step: Optional[str] = None
    last_error: Optional[str] = None
    updated_at: Optional[str] = None


@router.get("/status/{run_id}")
async def get_run_status(run_id: str, user: dict = Depends(require_viewer)):
    """Get minimal run status for frequent polling."""
    tenant_id = user["tenant_id"]
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT run_id, status, execution_mode, started_at, completed_at
                   FROM runs WHERE run_id = ? AND tenant_id = ?""",
                (run_id, tenant_id)
            )
            run = cursor.fetchone()
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")

            # Get current step from latest node (column is `name` not `node_name`)
            cursor.execute(
                """SELECT name, status FROM dag_nodes
                   WHERE run_id = ? ORDER BY started_at DESC LIMIT 1""",
                (run_id,)
            )
            node = cursor.fetchone()
            current_step = node["name"] if node else None

            # Get step counts for progress tracking
            cursor.execute(
                "SELECT COUNT(*) as total FROM dag_nodes WHERE run_id = ?",
                (run_id,)
            )
            total_row = cursor.fetchone()
            total_steps = total_row["total"] if total_row else 0

            cursor.execute(
                "SELECT COUNT(*) as done FROM dag_nodes WHERE run_id = ? AND status = 'COMPLETED'",
                (run_id,)
            )
            done_row = cursor.fetchone()
            completed_steps = done_row["done"] if done_row else 0

            # Get last_error from failed node
            last_error = None
            cursor.execute(
                "SELECT error_json FROM dag_nodes WHERE run_id = ? AND status = 'FAILED' ORDER BY completed_at DESC LIMIT 1",
                (run_id,)
            )
            err_row = cursor.fetchone()
            if err_row and err_row["error_json"]:
                try:
                    last_error = json.loads(err_row["error_json"]).get("error")
                except Exception:
                    pass

            # Get last event time as updated_at
            cursor.execute(
                "SELECT MAX(ts) as last_ts FROM run_events WHERE run_id = ?",
                (run_id,)
            )
            event_row = cursor.fetchone()
            updated_at = event_row["last_ts"] if event_row else None

            # Flag stale SUBMITTED orders (>60s old) so frontend can reconcile
            stale_order_ids = []
            if run["status"] in ("RUNNING", "COMPLETED", "FAILED") and total_steps > 0:
                cursor.execute(
                    """SELECT order_id FROM orders
                       WHERE run_id = ? AND status = 'SUBMITTED'
                       AND created_at < datetime('now', '-60 seconds')""",
                    (run_id,),
                )
                stale_order_ids = [r["order_id"] for r in cursor.fetchall()]

        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "execution_mode": run["execution_mode"],
            "started_at": run["started_at"],
            "completed_at": run["completed_at"],
            "current_step": current_step,
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "last_error": last_error,
            "updated_at": updated_at,
            "stale_order_ids": stale_order_ids,
        }
    except HTTPException:
        raise  # Let 404 etc. propagate normally
    except Exception as e:
        logger.warning("Status endpoint error for run %s: %s", run_id, str(e)[:200])
        return {"run_id": run_id, "status": "UNKNOWN", "error": "Temporary error fetching status"}


@router.get("/{run_id}")
async def get_run_detail(run_id: str, user: dict = Depends(require_viewer), request: Request = None):
    """Get run detail."""
    request_id = getattr(request.state, 'request_id', None) if request else str(uuid.uuid4())[:8]
    tenant_id = user["tenant_id"]

    try:
        return await _get_run_detail_impl(run_id, tenant_id, request_id, request)
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        err_lower = str(e).lower()
        if "database is locked" in err_lower:
            return _structured_run_error(503, "DB_BUSY", "Database busy, please retry", request_id)
        return _structured_run_error(503, "DB_ERROR", str(e)[:200], request_id)
    except Exception as e:
        try:
            logger.error("get_run_detail_error: %s | req=%s | run=%s", str(e)[:200], request_id, run_id)
        except Exception:
            pass
        return _structured_run_error(500, "INTERNAL_ERROR", "Failed to fetch run detail", request_id)


async def _get_run_detail_impl(run_id: str, tenant_id: str, request_id: str, request):
    """Internal implementation of get_run_detail."""
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get run (include trace_id and source_run_id)
        cursor.execute(
            "SELECT * FROM runs WHERE run_id = ? AND tenant_id = ?",
            (run_id, tenant_id)
        )
        run = cursor.fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        
        # Get nodes
        cursor.execute(
            "SELECT * FROM dag_nodes WHERE run_id = ? ORDER BY started_at ASC",
            (run_id,)
        )
        nodes = cursor.fetchall()
        
        # Get policy events
        cursor.execute(
            "SELECT * FROM policy_events WHERE run_id = ?",
            (run_id,)
        )
        policy_events = cursor.fetchall()
        
        # Get approvals
        cursor.execute(
            "SELECT * FROM approvals WHERE run_id = ?",
            (run_id,)
        )
        approvals = cursor.fetchall()
        
        # Get orders
        cursor.execute(
            "SELECT * FROM orders WHERE run_id = ?",
            (run_id,)
        )
        orders = cursor.fetchall()
        
        # Get snapshots
        cursor.execute(
            "SELECT * FROM portfolio_snapshots WHERE run_id = ? ORDER BY ts ASC",
            (run_id,)
        )
        snapshots = cursor.fetchall()
        
        # Get evals
        cursor.execute(
            "SELECT * FROM eval_results WHERE run_id = ?",
            (run_id,)
        )
        evals = cursor.fetchall()
        
        # Get fills for orders in this run
        order_ids = [o["order_id"] for o in orders]
        fills = []
        if order_ids:
            try:
                placeholders = ",".join(["?"] * len(order_ids))
                cursor.execute(
                    f"""
                    SELECT * FROM fills
                    WHERE order_id IN ({placeholders})
                    ORDER BY filled_at ASC
                    """,
                    order_ids
                )
                fills = cursor.fetchall()
            except Exception:
                fills = []  # Table may not exist yet

        # Get last_event_at from run_events
        cursor.execute(
            "SELECT MAX(ts) as last_event_at FROM run_events WHERE run_id = ?",
            (run_id,)
        )
        last_event_row = cursor.fetchone()
        last_event_at = last_event_row["last_event_at"] if last_event_row else None

        # Get artifacts count
        try:
            cursor.execute(
                "SELECT COUNT(*) as count FROM run_artifacts WHERE run_id = ?",
                (run_id,)
            )
            artifacts_row = cursor.fetchone()
            artifacts_count = artifacts_row["count"] if artifacts_row else 0
        except Exception:
            artifacts_count = 0  # Table may not exist yet

    run_dict = dict(run)

    # Generate summary_text from metadata or node outputs
    summary_text = None
    metadata_json = run_dict.get("metadata_json")
    if metadata_json:
        import json as json_module
        try:
            metadata = json_module.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
            intent = metadata.get("intent", "")
            if intent == "PORTFOLIO_ANALYSIS":
                summary_text = "Portfolio analysis completed"
            elif intent == "TRADE_EXECUTION":
                side = metadata.get("side", "")
                asset = metadata.get("asset", "")
                amount = metadata.get("amount_usd", "")
                summary_text = f"{side.capitalize()} ${amount} of {asset}"
        except Exception:
            pass

    # Add computed fields to run
    run_dict["summary_text"] = summary_text
    run_dict["last_event_at"] = last_event_at
    run_dict["artifacts_count"] = artifacts_count

    result = {
        "run": run_dict,
        "nodes": [dict(n) for n in nodes],
        "policy_events": [dict(p) for p in policy_events],
        "approvals": [dict(a) for a in approvals],
        "orders": [dict(o) for o in orders],
        "snapshots": [dict(s) for s in snapshots],
        "evals": [dict(e) for e in evals],
        "fills": [dict(f) for f in fills],
    }
    
    # Add trace_id and request_id headers if available
    from fastapi.responses import JSONResponse
    response = JSONResponse(content=result)
    trace_id = run_dict.get("trace_id") if run_dict else None
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    if request and hasattr(request.state, "request_id"):
        response.headers["X-Request-ID"] = request.state.request_id
    
    return response


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, user: dict = Depends(require_viewer), request: Request = None):
    """Stream run events via SSE."""
    tenant_id = user["tenant_id"]
    user_id = user["user_id"]
    
    # SSE connection tracking and limits
    from backend.api.middleware.sse_tracker import track_sse_connection, untrack_sse_connection, get_sse_connection_count
    from backend.core.ids import new_id
    
    connection_id = new_id("sse_")
    user_key = f"{tenant_id}:{user_id}"
    
    # Check SSE connection limit
    if get_sse_connection_count(user_key) >= 3:
        raise HTTPException(
            status_code=429,
            detail="Maximum concurrent SSE connections (3) exceeded. Close existing connections and try again."
        )
    
    if not track_sse_connection(user_key, connection_id, run_id):
        raise HTTPException(
            status_code=429,
            detail="SSE connection limit exceeded"
        )
    
    # Verify run exists and belongs to tenant
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT run_id FROM runs WHERE run_id = ? AND tenant_id = ?",
            (run_id, tenant_id)
        )
        if not cursor.fetchone():
            untrack_sse_connection(user_key, connection_id)
            raise HTTPException(status_code=404, detail="Run not found")
    
    async def event_generator():
        # Replay historical events
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT event_type, payload_json, ts FROM run_events WHERE run_id = ? ORDER BY ts ASC",
                (run_id,)
            )
            historical = cursor.fetchall()
        
        for event in historical:
            payload = json.loads(event["payload_json"])
            yield f"data: {json.dumps({'event_type': event['event_type'], 'payload': payload, 'ts': event['ts']})}\n\n"
        
        # Subscribe to live events
        queue = await event_pubsub.subscribe(run_id)
        
        try:
            while True:
                # Check if run is complete
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
                    row = cursor.fetchone()
                    if row and row["status"] in ("COMPLETED", "FAILED"):
                        yield f"data: {json.dumps({'event_type': 'RUN_COMPLETE', 'status': row['status']})}\n\n"
                        break
                
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            # Clean up SSE connection tracking and pubsub subscription
            untrack_sse_connection(user_key, connection_id)
            await event_pubsub.unsubscribe(run_id, queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )
