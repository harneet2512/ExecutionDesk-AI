"""Approvals API routes."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from backend.api.deps import require_trader
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.time import now_iso
from backend.orchestrator.runner import execute_run
from backend.orchestrator.event_emitter import emit_event as _emit_event
from backend.orchestrator.state_machine import RunStatus

logger = get_logger(__name__)
router = APIRouter()

class ApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(APPROVED|REJECTED)$")

@router.post("/{approval_id}/decision")
async def decision_approval(
    approval_id: str,
    decision_body: ApprovalDecision,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_trader)
):
    """Submit an approval decision (APPROVED or REJECTED)."""
    tenant_id = user["tenant_id"]
    decision = decision_body.decision
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get approval record
        cursor.execute(
            "SELECT run_id, status FROM approvals WHERE approval_id = ? AND tenant_id = ?",
            (approval_id, tenant_id)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        run_id = row["run_id"]
        current_status = row["status"]
        
        if current_status != "PENDING":
            raise HTTPException(status_code=400, detail=f"Approval is already {current_status}")
            
        # Update approval
        cursor.execute(
            """
            UPDATE approvals 
            SET status = 'COMPLETED', decision = ?, updated_at = ?
            WHERE approval_id = ?
            """,
            (decision, now_iso(), approval_id)
        )
        conn.commit()
    
    logger.info(f"Approval {approval_id} for run {run_id} decided: {decision}")
    
    if decision == "APPROVED":
        # Resume run
        # update run status back to RUNNING (is usually PAUSED)
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE runs SET status = ? WHERE run_id = ?",
                (RunStatus.RUNNING.value, run_id)
            )
            conn.commit()
            
        await _emit_event(run_id, "RUN_STATUS", {"status": RunStatus.RUNNING.value}, tenant_id=tenant_id)
        await _emit_event(run_id, "APPROVAL_DECISION", {"decision": "APPROVED", "approval_id": approval_id}, tenant_id=tenant_id)
        
        # Trigger execution again (runner will skip completed nodes)
        background_tasks.add_task(execute_run, run_id)
        
    else:
        # REJECTED - Fail the run
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE runs SET status = ? WHERE run_id = ?",
                (RunStatus.FAILED.value, run_id)
            )
            conn.commit()
            
        await _emit_event(run_id, "RUN_STATUS", {"status": RunStatus.FAILED.value}, tenant_id=tenant_id)
        await _emit_event(run_id, "APPROVAL_DECISION", {"decision": "REJECTED", "approval_id": approval_id}, tenant_id=tenant_id)
        await _emit_event(run_id, "RUN_FAILED", {"error": "User rejected trade proposal", "code": "USER_REJECTED"}, tenant_id=tenant_id)

    return {"status": "success", "decision": decision}
