"""Evidence Sufficiency Evaluation - verifies ranking decision has evidence artifacts."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_evidence_sufficiency(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Evidence Sufficiency
    
    Checks:
    - Ranking decision has evidence artifacts (data + filters + top candidates)
    - Rankings table has entries
    - Research node outputs have returns_by_symbol
    - Signals node outputs have top_symbol with evidence
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        checks_passed = 0
        total_checks = 0
        reasons = []
        
        # Check 1: Rankings table has entries
        total_checks += 1
        cursor.execute(
            "SELECT table_json FROM rankings WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,)
        )
        ranking_row = cursor.fetchone()
        if ranking_row:
            rankings_data = json.loads(ranking_row["table_json"])
            if isinstance(rankings_data, list) and len(rankings_data) > 0:
                checks_passed += 1
                reasons.append(f"Rankings table has {len(rankings_data)} candidates")
            else:
                reasons.append("Rankings table empty or invalid format")
        else:
            reasons.append("Rankings table missing")
        
        # Check 2: Research node has returns_by_symbol
        total_checks += 1
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'research'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        research_row = cursor.fetchone()
        if research_row:
            research_output = json.loads(research_row["outputs_json"])
            returns_by_symbol = research_output.get("returns_by_symbol", {})
            if returns_by_symbol and len(returns_by_symbol) > 0:
                checks_passed += 1
                reasons.append(f"Research outputs have returns for {len(returns_by_symbol)} symbols")
            else:
                reasons.append("Research outputs missing returns_by_symbol")
        else:
            reasons.append("Research node outputs missing")
        
        # Check 3: Signals node has top_symbol with evidence
        total_checks += 1
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        signals_row = cursor.fetchone()
        if signals_row:
            signals_output = json.loads(signals_row["outputs_json"])
            top_symbol = signals_output.get("top_symbol")
            top_return = signals_output.get("top_return")
            if top_symbol and top_return is not None:
                checks_passed += 1
                reasons.append(f"Signals output has top_symbol={top_symbol} with return={top_return:.2%}")
            else:
                reasons.append("Signals output missing top_symbol or top_return")
        else:
            reasons.append("Signals node outputs missing")
        
        # Check 4: Universe filters documented (from research outputs)
        total_checks += 1
        if research_row:
            research_output = json.loads(research_row["outputs_json"])
            universe = research_output.get("universe", [])
            if universe and len(universe) > 0:
                checks_passed += 1
                reasons.append(f"Universe filters documented: {len(universe)} products")
            else:
                reasons.append("Universe not documented in research outputs")
        else:
            reasons.append("Cannot check universe (research outputs missing)")
        
        score = checks_passed / total_checks if total_checks > 0 else 0.0
        
        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"min_score": 0.75}
        }
