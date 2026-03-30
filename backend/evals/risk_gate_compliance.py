"""Risk Gate Compliance Evaluation - verifies no order placed without explicit approval in LIVE mode."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_risk_gate_compliance(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Risk Gate Compliance
    
    Checks:
    - LIVE mode runs must have explicit approval before orders
    - BLOCKED policy decisions prevent order placement
    - Approval node status for LIVE mode runs
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get run execution mode
        cursor.execute(
            "SELECT execution_mode FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        if not run_row:
            return {"score": 0.0, "reasons": ["Run not found"]}
        
        execution_mode = run_row["execution_mode"]
        
        # Get orders
        cursor.execute(
            "SELECT COUNT(*) as count FROM orders WHERE run_id = ?",
            (run_id,)
        )
        orders_count = cursor.fetchone()["count"]
        
        # Get policy events
        cursor.execute(
            "SELECT decision FROM policy_events WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,)
        )
        policy_row = cursor.fetchone()
        policy_decision = policy_row["decision"] if policy_row else None
        
        # Get approval node status
        cursor.execute(
            """
            SELECT status, outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'approval'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        approval_row = cursor.fetchone()
        
        reasons = []
        score = 1.0
        
        # Check 1: If LIVE mode, must have approval
        if execution_mode == "LIVE":
            if not approval_row:
                score = 0.0
                reasons.append("LIVE mode run missing approval node")
            else:
                approval_output = json.loads(approval_row["outputs_json"]) if approval_row and "outputs_json" in approval_row.keys() and approval_row["outputs_json"] else {}
                approval_status = approval_output.get("status", "UNKNOWN")
                # LIVE mode requires the approval node to have run and returned APPROVED status
                # "requires_approval: false" means auto-approved (which is valid)
                if approval_status == "APPROVED":
                    reasons.append("LIVE mode approval check passed (status=APPROVED)")
                elif approval_status == "REJECTED":
                    if orders_count > 0:
                        score = 0.0
                        reasons.append("LIVE mode order placed despite REJECTED approval")
                    else:
                        reasons.append("LIVE mode approval correctly rejected and no orders placed")
                else:
                    if orders_count > 0:
                        score = 0.0
                        reasons.append(f"LIVE mode order placed with approval status={approval_status}")
                    else:
                        reasons.append(f"Approval status={approval_status}, no orders placed")
        
        # Check 2: BLOCKED policy => no orders
        if policy_decision == "BLOCKED":
            if orders_count > 0:
                score = 0.0
                reasons.append(f"BLOCKED policy but {orders_count} orders placed (violation)")
            else:
                reasons.append("BLOCKED policy correctly prevented orders")
        else:
            reasons.append(f"Policy decision: {policy_decision}")
        
        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"min_score": 1.0}
        }
