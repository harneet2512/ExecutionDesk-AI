"""Approval node."""
import json
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute approval node.
    
    For PAPER mode: auto-approve (user already confirmed via UI dialog).
    For LIVE mode: check if policy requires approval, pause if needed.
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Determine execution mode and whether user already confirmed via chat
        cursor.execute("SELECT execution_mode, metadata_json FROM runs WHERE run_id = ?", (run_id,))
        run_row = cursor.fetchone()
        execution_mode = run_row["execution_mode"] if run_row else "PAPER"
        
        # If the run was created via the confirmation flow (user typed "CONFIRM"),
        # treat it as pre-approved regardless of execution mode
        user_pre_confirmed = False
        if run_row and run_row["metadata_json"]:
            try:
                import json as _json
                meta = _json.loads(run_row["metadata_json"])
                user_pre_confirmed = meta.get("confirmed", False)
            except Exception:
                pass

        # 1. Check if we already have an approval record for this run
        cursor.execute(
            "SELECT approval_id, status, decision FROM approvals WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,)
        )
        row = cursor.fetchone()
        
        if row:
            # Existing approval found
            status = row["status"]
            decision = row["decision"]  # 'APPROVED', 'REJECTED', or None
            
            if status == "COMPLETED" and decision == "APPROVED":
                return {
                    "requires_approval": False,
                    "approval_id": row["approval_id"],
                    "status": "APPROVED",
                    "safe_summary": "User approved execution"
                }
            elif status == "COMPLETED" and decision == "REJECTED":
                from backend.core.error_codes import TradeErrorException, TradeErrorCode
                raise TradeErrorException(
                    error_code=TradeErrorCode.USER_REJECTED,
                    message="User rejected the trade proposal.",
                    remediation="Review the proposal and modify if necessary."
                )
            else:
                # Still PENDING - auto-approve if PAPER mode or user pre-confirmed
                if execution_mode == "PAPER" or user_pre_confirmed:
                    cursor.execute(
                        "UPDATE approvals SET status = 'COMPLETED', decision = 'APPROVED', updated_at = ? WHERE approval_id = ?",
                        (now_iso(), row["approval_id"])
                    )
                    conn.commit()
                    reason = "PAPER mode" if execution_mode == "PAPER" else "user pre-confirmed"
                    logger.info("Auto-approved %s run %s (approval %s)", reason, run_id, row["approval_id"])
                    return {
                        "requires_approval": False,
                        "approval_id": row["approval_id"],
                        "status": "APPROVED",
                        "safe_summary": f"Auto-approved ({reason})"
                    }
                return {
                    "requires_approval": True,
                    "approval_id": row["approval_id"],
                    "status": "PENDING",
                    "safe_summary": "Waiting for user approval"
                }

        # 2. No existing approval record
        # Check policy_check output to see if approval is required
        cursor.execute(
            "SELECT outputs_json FROM dag_nodes WHERE run_id = ? AND name = 'policy_check' LIMIT 1",
            (run_id,)
        )
        policy_row = cursor.fetchone()
        policy_decision = "ALLOWED"
        if policy_row and policy_row["outputs_json"]:
            try:
                policy_out = json.loads(policy_row["outputs_json"])
                policy_decision = policy_out.get("decision", "ALLOWED")
            except Exception:
                pass

        # Auto-approve if: PAPER mode, user pre-confirmed via chat, or policy says ALLOWED
        if execution_mode == "PAPER" or user_pre_confirmed or (execution_mode != "LIVE" and policy_decision == "ALLOWED"):
            approval_id = new_id("apr_")
            cursor.execute(
                """
                INSERT INTO approvals (approval_id, run_id, tenant_id, status, decision, created_at, updated_at)
                VALUES (?, ?, ?, 'COMPLETED', 'APPROVED', ?, ?)
                """,
                (approval_id, run_id, tenant_id, now_iso(), now_iso())
            )
            conn.commit()
            logger.info("Auto-approved %s mode run %s", execution_mode, run_id)
            return {
                "requires_approval": False,
                "approval_id": approval_id,
                "status": "APPROVED",
                "safe_summary": f"Auto-approved ({execution_mode} mode)"
            }
        
        # LIVE mode with REQUIRES_APPROVAL: create pending approval
        approval_id = new_id("apr_")
        cursor.execute(
            """
            INSERT INTO approvals (approval_id, run_id, tenant_id, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (approval_id, run_id, tenant_id, "PENDING", now_iso())
        )
        conn.commit()
        
        logger.info("Approval required for LIVE run %s (approval %s)", run_id, approval_id)
        return {
            "requires_approval": True,
            "approval_id": approval_id,
            "status": "PENDING", 
            "safe_summary": "LIVE trade requires approval"
        }
