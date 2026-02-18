"""Budget Compliance Evaluation."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_budget_compliance(run_id: str, tenant_id: str) -> dict:
    """
    Eval 2: Budget Compliance
    
    Checks:
    - Executed notional <= budget_usd (including fees buffer)
    - All orders comply with budget limit
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get intent (budget)
        cursor.execute(
            "SELECT intent_json FROM runs WHERE run_id = ?",
            (run_id,)
        )
        intent_row = cursor.fetchone()
        if not intent_row or "intent_json" not in intent_row.keys() or not intent_row["intent_json"]:
            return {"score": 0.0, "reasons": ["No intent found"]}
        
        intent = json.loads(intent_row["intent_json"])
        budget_usd = intent.get("budget_usd", 10.0)
        
        # Get executed orders
        cursor.execute(
            "SELECT notional_usd, status FROM orders WHERE run_id = ?",
            (run_id,)
        )
        orders = cursor.fetchall()
        
        if not orders:
            return {"score": 0.0, "reasons": ["No orders executed"]}
        
        total_notional = sum(float(o["notional_usd"]) for o in orders)
        
        # Check compliance (with 1% tolerance for rounding)
        if total_notional <= budget_usd * 1.01:
            score = 1.0
            reasons = [f"Total notional ${total_notional:.2f} <= budget ${budget_usd:.2f}"]
        else:
            score = 0.0
            reasons = [f"Budget exceeded: ${total_notional:.2f} > ${budget_usd:.2f}"]
        
        return {"score": score, "reasons": reasons}
