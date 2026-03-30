"""Plan Completeness Evaluation - verifies required steps exist for command type."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_plan_completeness(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Plan Completeness
    
    Checks:
    - Required steps exist for command type (trading commands need: research, signals, proposal, execution)
    - Execution plan has all expected steps
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get execution plan
        cursor.execute(
            "SELECT execution_plan_json FROM runs WHERE run_id = ?",
            (run_id,)
        )
        plan_row = cursor.fetchone()
        
        if not plan_row or "execution_plan_json" not in plan_row.keys() or not plan_row["execution_plan_json"]:
            return {"score": 0.0, "reasons": ["No execution plan found"]}
        
        plan = json.loads(plan_row["execution_plan_json"])
        steps = plan.get("steps", [])
        
        # Required steps for trading command
        required_steps = ["research", "signals", "proposal", "execution"]
        
        step_names = [s.get("step_name", "") for s in steps]
        
        missing_steps = [req for req in required_steps if req not in step_names]
        present_steps = [req for req in required_steps if req in step_names]
        
        score = len(present_steps) / len(required_steps) if required_steps else 1.0
        
        reasons = []
        if missing_steps:
            reasons.append(f"Missing required steps: {missing_steps}")
        if present_steps:
            reasons.append(f"Present required steps: {present_steps}")
        
        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"min_score": 1.0, "required_steps": required_steps}
        }
