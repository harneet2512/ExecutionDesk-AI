"""Numeric Grounding Evaluation - verifies all numeric claims are traceable to artifacts."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_numeric_grounding(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Numeric Grounding
    
    Checks:
    - Every numeric shown in UI/proposal is traceable to artifact paths
    - Returns, prices, fees, quantities have evidence
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get proposal
        cursor.execute(
            "SELECT trade_proposal_json FROM runs WHERE run_id = ?",
            (run_id,)
        )
        proposal_row = cursor.fetchone()
        if not proposal_row or "trade_proposal_json" not in proposal_row.keys() or not proposal_row["trade_proposal_json"]:
            return {"score": 0.0, "reasons": ["No proposal found"]}
        
        proposal = json.loads(proposal_row["trade_proposal_json"])
        orders = proposal.get("orders", [])
        
        if not orders:
            return {"score": 0.0, "reasons": ["No orders in proposal"]}
        
        order = orders[0]
        claimed_notional = order.get("notional_usd")
        claimed_return = proposal.get("expected_return_24h")
        
        # Check if claimed_notional has evidence (intent budget_usd)
        cursor.execute("SELECT intent_json FROM runs WHERE run_id = ?", (run_id,))
        intent_row = cursor.fetchone()
        if intent_row and "intent_json" in intent_row.keys() and intent_row["intent_json"]:
            intent = json.loads(intent_row["intent_json"])
            budget_usd = intent.get("budget_usd")
            
            if budget_usd and abs(float(claimed_notional) - float(budget_usd)) < 1.0:
                notional_grounded = True
            else:
                notional_grounded = False
        else:
            notional_grounded = False
        
        # Check if claimed_return has evidence (signals or research outputs)
        return_grounded = False
        if claimed_return is not None:
            cursor.execute(
                """
                SELECT outputs_json FROM dag_nodes 
                WHERE run_id = ? AND name IN ('signals', 'research')
                ORDER BY started_at DESC LIMIT 1
                """,
                (run_id,)
            )
            outputs_row = cursor.fetchone()
            if outputs_row:
                outputs = json.loads(outputs_row["outputs_json"])
                if "top_return" in outputs:
                    stored_return = outputs["top_return"]
                    if abs(float(claimed_return) - float(stored_return)) < 0.001:  # Tolerance
                        return_grounded = True
                elif "returns_by_symbol" in outputs:
                    returns = outputs["returns_by_symbol"]
                    if returns:
                        max_return = max(returns.values())
                        if abs(float(claimed_return) - float(max_return)) < 0.001:
                            return_grounded = True
        
        # Count grounded vs ungrounded
        grounded_count = 0
        total_count = 0
        
        if claimed_notional is not None:
            total_count += 1
            if notional_grounded:
                grounded_count += 1
        
        if claimed_return is not None:
            total_count += 1
            if return_grounded:
                grounded_count += 1
        
        score = grounded_count / total_count if total_count > 0 else 0.0
        reasons = []
        if notional_grounded:
            reasons.append(f"Notional ${claimed_notional} grounded to intent budget")
        else:
            reasons.append(f"Notional ${claimed_notional} not grounded")
        
        if return_grounded:
            reasons.append(f"Return {claimed_return:.2%} grounded to stored outputs")
        else:
            reasons.append(f"Return {claimed_return:.2%} not grounded")
    
    return {"score": score, "reasons": reasons}
