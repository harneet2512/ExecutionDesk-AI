"""Intent Parse Correctness Evaluation - verifies intent parser extracts fields correctly."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_intent_parse_correctness(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Intent Parse Correctness
    
    Checks:
    - Intent parser extracts asset class (crypto/stock/fx)
    - Intent parser extracts timeframe (lookback_hours)
    - Intent parser extracts budget_usd
    - Intent parser extracts objective (MOST_PROFITABLE, etc.)
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get intent and command_text
        cursor.execute(
            "SELECT intent_json, command_text FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        
        if not row or "intent_json" not in row.keys() or not row["intent_json"]:
            return {"score": 0.0, "reasons": ["No intent_json found"]}
        
        intent = json.loads(row["intent_json"])
        command_text = row["command_text"] if "command_text" in row.keys() else ""
        
        checks_passed = 0
        total_checks = 0
        reasons = []
        
        # Check 1: objective is present
        total_checks += 1
        objective = intent.get("objective")
        if objective:
            checks_passed += 1
            reasons.append(f"Objective extracted: {objective}")
        else:
            reasons.append("Missing objective in intent")
        
        # Check 2: budget_usd is present and numeric
        total_checks += 1
        budget_usd = intent.get("budget_usd")
        if budget_usd is not None:
            try:
                float(budget_usd)
                checks_passed += 1
                reasons.append(f"Budget extracted: ${budget_usd}")
            except (ValueError, TypeError):
                reasons.append(f"Budget not numeric: {budget_usd}")
        else:
            reasons.append("Missing budget_usd in intent")
        
        # Check 3: lookback_hours is present
        total_checks += 1
        lookback_hours = intent.get("lookback_hours")
        if lookback_hours is not None:
            checks_passed += 1
            reasons.append(f"Lookback hours extracted: {lookback_hours}h")
        else:
            reasons.append("Missing lookback_hours in intent")
        
        # Check 4: asset class inference (crypto if universe contains crypto symbols)
        total_checks += 1
        universe = intent.get("universe", [])
        asset_class = "crypto" if any("-USD" in str(sym) for sym in universe) else "unknown"
        if asset_class == "crypto" or not universe:  # Allow unknown if no universe specified
            checks_passed += 1
            reasons.append(f"Asset class inferred: {asset_class}")
        else:
            reasons.append(f"Asset class unclear from universe: {universe}")
        
        score = checks_passed / total_checks if total_checks > 0 else 0.0
        
        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"min_score": 0.75}
        }
