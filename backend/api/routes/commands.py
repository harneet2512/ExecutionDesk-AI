"""Commands API endpoint (unified command interface)."""
import json
import re
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from backend.api.deps import require_trader
from backend.orchestrator.runner import create_run, execute_run
from backend.agents.command_parser import parse_command
from backend.agents.planner import plan_execution
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.ids import new_id
from backend.core.time import now_iso

logger = get_logger(__name__)

router = APIRouter()


class ExecuteCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=5000, description="Natural language command")
    execution_mode: str = Field("PAPER", pattern="^(PAPER|LIVE|REPLAY)$")
    source_run_id: Optional[str] = Field(None, max_length=100)
    
    model_config = {"extra": "forbid"}
    
    @field_validator('command')
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Validate and sanitize command text."""
        import re
        # Strip control characters (except newlines and tabs)
        v = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', v)
        # Normalize whitespace
        v = re.sub(r'[ \t]+', ' ', v)
        v = re.sub(r'\n{3,}', '\n\n', v)
        v = v.strip()
        return v


class ExecuteCommandResponse(BaseModel):
    run_id: str
    command_type: str  # "trade" | "replay" | "analytics"
    trace_id: Optional[str] = None


@router.post("/execute", response_model=ExecuteCommandResponse)
async def execute_command(
    request_body: ExecuteCommandRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_trader),  # Require trader or admin
    request: Request = None
):
    """
    Execute a natural language command.
    
    Supported commands:
    - "buy the most profitable crypto of last 24hrs for $10" - Trade command
    - "buy $10 of BTC" - Direct trade command
    - "replay run run_xxx" - Replay a previous run
    - "show my performance last 7 days" - Analytics command (returns immediately)
    """
    tenant_id = user["tenant_id"]
    command_lower = request_body.command.lower().strip()
    
    # Handle "replay run <run_id>" command
    if command_lower.startswith("replay run"):
        run_match = re.search(r'replay run\s+([a-zA-Z0-9_-]+)', command_lower)
        if run_match:
            source_run_id = run_match.group(1)
            # Validate source run exists and belongs to tenant
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT run_id FROM runs WHERE run_id = ? AND tenant_id = ?",
                    (source_run_id, tenant_id)
                )
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail=f"Source run {source_run_id} not found")
            
            # Create REPLAY run
            run_id = create_run(
                tenant_id=tenant_id,
                execution_mode="REPLAY",
                source_run_id=source_run_id
            )
            
            # Store command
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE runs SET command_text = ? WHERE run_id = ?",
                    (request_body.command, run_id)
                )
                conn.commit()
            
            background_tasks.add_task(execute_run, run_id)
            
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT trace_id FROM runs WHERE run_id = ?", (run_id,))
                row = cursor.fetchone()
                trace_id = row["trace_id"] if row else None
            
            response = JSONResponse(content={
                "run_id": run_id,
                "command_type": "replay",
                "trace_id": trace_id
            })
            if trace_id:
                response.headers["X-Trace-ID"] = trace_id
            return response
        else:
            raise HTTPException(status_code=400, detail="Replay command must include run_id: 'replay run <run_id>'")
    
    # Handle "show my performance last 7 days" (analytics - return immediately)
    if "show" in command_lower and "performance" in command_lower:
        # This is handled by analytics endpoint, redirect
        # For now, return a placeholder response (analytics endpoint will handle this)
        return JSONResponse(content={
            "run_id": None,
            "command_type": "analytics",
            "message": "Use GET /api/v1/analytics/performance?window=7d for performance data"
        })
    
    # Handle trade commands (default)
    execution_mode = request_body.execution_mode or "PAPER"
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
        text=request_body.command,
        default_budget=10.0,
        default_universe=None
    )
    
    # SAFETY: Enforce hard cap on LIVE orders
    if execution_mode == "LIVE":
        from backend.core.config import get_settings
        settings = get_settings()
        notional_usd = parsed_intent.budget_usd
        if notional_usd > settings.live_max_notional_usd:
            raise HTTPException(
                status_code=400,
                detail=f"LIVE order blocked: notional ${notional_usd:.2f} exceeds LIVE_MAX_NOTIONAL_USD=${settings.live_max_notional_usd:.2f}"
            )

    
    # Create run
    run_id = create_run(
        tenant_id=tenant_id,
        execution_mode=execution_mode,
        source_run_id=source_run_id
    )
    
    # Create execution plan
    execution_plan = plan_execution(parsed_intent, run_id)
    
    # For direct symbol commands (universe has exactly one symbol), set selected_asset immediately
    if len(parsed_intent.universe) == 1:
        selected_symbol = parsed_intent.universe[0]
        execution_plan_dict = execution_plan.dict()
        execution_plan_dict["selected_asset"] = selected_symbol
        execution_plan_dict["selected_order"] = {
            "symbol": selected_symbol,
            "side": parsed_intent.side,
            "notional_usd": parsed_intent.budget_usd
        }
        execution_plan_dict["decision_trace"].append({
            "step": "direct_symbol_selection",
            "selected_symbol": selected_symbol,
            "reason": "Direct symbol command - single symbol in universe",
            "timestamp": now_iso()
        })
    else:
        execution_plan_dict = execution_plan.dict()
    
    # Store command, intent, and plan
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Store intent as evidence
        intent_id = new_id("intent_")
        cursor.execute(
            """
            INSERT INTO intents (intent_id, run_id, command, intent_json, ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (intent_id, run_id, request_body.command, json.dumps(parsed_intent.dict()), now_iso())
        )
        
        cursor.execute(
            """
            UPDATE runs 
            SET command_text = ?, parsed_intent_json = ?, execution_plan_json = ?
            WHERE run_id = ?
            """,
            (
                request_body.command,
                json.dumps(parsed_intent.dict()),
                json.dumps(execution_plan_dict),
                run_id
            )
        )
        conn.commit()
    
    # Execute in background
    background_tasks.add_task(execute_run, run_id)
    
    # Get trace_id
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT trace_id FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        trace_id = row["trace_id"] if row else None
    
    result = ExecuteCommandResponse(
        run_id=run_id,
        command_type="trade",
        trace_id=trace_id
    )
    
    response = JSONResponse(content=result.dict())
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    if request and hasattr(request.state, "request_id"):
        response.headers["X-Request-ID"] = request.state.request_id
    
    return response
