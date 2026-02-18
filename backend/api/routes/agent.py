"""Agent command API endpoint."""
import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from backend.api.deps import get_current_user
from backend.orchestrator.runner import create_run, execute_run
from backend.agents.command_parser import parse_command
from backend.agents.planner import plan_execution
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


class CommandRequest(BaseModel):
    text: str
    execution_mode: str = "PAPER"  # PAPER, LIVE, REPLAY
    budget_usd: float = 10.0
    window: str = "24h"  # 1h, 24h, 7d
    metric: str = "return"  # return, sharpe_proxy, momentum
    universe: Optional[List[str]] = None
    source_run_id: Optional[str] = None
    dry_run: bool = False


class CommandResponse(BaseModel):
    run_id: str
    parsed_intent: Dict[str, Any]
    selected_asset: Optional[str] = None
    selected_order: Optional[Dict[str, Any]] = None
    decision_trace: List[Dict[str, Any]]


@router.post("/command", response_model=CommandResponse)
async def command(
    request_body: CommandRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    request: Request = None
):
    """
    Execute natural language trading command.
    
    Example: "buy the most profitable crypto for $10"
    """
    tenant_id = user["tenant_id"]
    execution_mode = request_body.execution_mode
    source_run_id = request_body.source_run_id
    
    # Validate LIVE mode requires ENABLE_LIVE_TRADING
    if execution_mode == "LIVE":
        from backend.core.config import get_settings
        settings = get_settings()
        if not settings.enable_live_trading:
            raise HTTPException(
                status_code=403,
                detail="LIVE trading is disabled. Set ENABLE_LIVE_TRADING=true to enable."
            )
    
    # Parse command
    parsed_intent = parse_command(
        text=request_body.text,
        default_budget=request_body.budget_usd,
        default_universe=request_body.universe
    )
    
    # Override with explicit params if provided
    if request_body.budget_usd != 10.0:
        parsed_intent.budget_usd = request_body.budget_usd
    if request_body.window != "24h":
        parsed_intent.window = request_body.window
    if request_body.metric != "return":
        parsed_intent.metric = request_body.metric
    if request_body.universe:
        parsed_intent.universe = request_body.universe
    
    # Create run
    run_id = create_run(
        tenant_id=tenant_id,
        execution_mode=execution_mode,
        source_run_id=source_run_id
    )
    
    # Create execution plan
    execution_plan = plan_execution(parsed_intent, run_id)
    
    # Store command and plan in run
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE runs 
            SET command_text = ?, parsed_intent_json = ?, execution_plan_json = ?
            WHERE run_id = ?
            """,
            (
                request_body.text,
                json.dumps(parsed_intent.dict()),
                json.dumps(execution_plan.dict()),
                run_id
            )
        )
        conn.commit()
    
    # Execute in background (unless dry_run)
    if not request_body.dry_run:
        background_tasks.add_task(execute_run, run_id)
    
    # Get initial response
    result = CommandResponse(
        run_id=run_id,
        parsed_intent=parsed_intent.dict(),
        selected_asset=execution_plan.selected_asset,
        selected_order=execution_plan.selected_order,
        decision_trace=execution_plan.decision_trace
    )
    
    # Add headers
    from fastapi.responses import JSONResponse
    response = JSONResponse(content=result.dict())
    
    # Get trace_id
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT trace_id FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if row and row["trace_id"]:
            response.headers["X-Trace-ID"] = row["trace_id"]
    
    if request and hasattr(request.state, "request_id"):
        response.headers["X-Request-ID"] = request.state.request_id
    
    return response


@router.get("/command/{run_id}")
async def get_command_result(
    run_id: str,
    user: dict = Depends(get_current_user)
):
    """Get command execution result."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
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
        
        parsed_intent = json.loads(row["parsed_intent_json"]) if row["parsed_intent_json"] else None
        execution_plan = json.loads(row["execution_plan_json"]) if row["execution_plan_json"] else None
        
        result = {
            "run_id": run_id,
            "command_text": row["command_text"],
            "parsed_intent": parsed_intent,
            "selected_asset": execution_plan.get("selected_asset") if execution_plan else None,
            "selected_order": execution_plan.get("selected_order") if execution_plan else None,
            "decision_trace": execution_plan.get("decision_trace", []) if execution_plan else [],
            "status": row["status"],
            "trace_id": row["trace_id"] if "trace_id" in row.keys() else None
        }
        
        response = JSONResponse(content=result)
        if "trace_id" in row.keys() and row["trace_id"]:
            response.headers["X-Trace-ID"] = row["trace_id"]
        
        return response
