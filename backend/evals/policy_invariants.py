"""Policy Invariants Evaluation - verifies BLOCKED decisions prevent orders."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_policy_invariants(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Policy Invariants
    
    Checks:
    - If policy decision is BLOCKED, no orders should be inserted
    - Policy events match actual execution
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get policy decision
        cursor.execute(
            """
            SELECT decision, reasons_json FROM policy_events
            WHERE run_id = ?
            ORDER BY ts DESC LIMIT 1
            """,
            (run_id,)
        )
        policy_row = cursor.fetchone()
        
        if not policy_row:
            return {"score": 1.0, "reasons": ["No policy events (evaluation skipped)"]}
        
        policy_decision = policy_row["decision"]
        
        # Get orders
        cursor.execute(
            "SELECT COUNT(*) as count FROM orders WHERE run_id = ?",
            (run_id,)
        )
        orders_count = cursor.fetchone()["count"]
        
        # Check invariant: BLOCKED => no orders
        if policy_decision == "BLOCKED":
            if orders_count == 0:
                score = 1.0
                reasons = ["Policy BLOCKED correctly prevented orders"]
            else:
                score = 0.0
                reasons = [f"Policy invariant violated: BLOCKED but {orders_count} orders inserted"]
        else:
            # For ALLOWED or REQUIRES_APPROVAL, orders may exist
            score = 1.0
            reasons = [f"Policy {policy_decision} - {orders_count} orders (expected)"]
    
    return {"score": score, "reasons": reasons}
