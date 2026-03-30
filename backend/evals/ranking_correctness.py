"""Ranking Correctness Evaluation - verifies chosen asset matches top return."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_ranking_correctness(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Ranking Correctness
    
    Checks:
    - Chosen asset equals top return from stored candles/rankings
    - Ranking computation matches stored evidence
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get signals node output (top_symbol)
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        signals_row = cursor.fetchone()
        if not signals_row:
            return {"score": 0.0, "reasons": ["Signals node output not found"]}
        
        signals_output = json.loads(signals_row["outputs_json"])
        chosen_symbol = signals_output.get("top_symbol")
        chosen_return = signals_output.get("top_return")
        
        if not chosen_symbol:
            return {"score": 0.0, "reasons": ["No chosen symbol in signals output"]}
        
        # Get rankings from rankings table (if exists)
        cursor.execute(
            "SELECT selected_symbol, table_json FROM rankings WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,)
        )
        ranking_row = cursor.fetchone()
        
        if ranking_row:
            rankings_data = json.loads(ranking_row["table_json"])
            if isinstance(rankings_data, list) and len(rankings_data) > 0:
                top_ranked = rankings_data[0]
                top_symbol = top_ranked.get("symbol") or top_ranked.get("product_id")
                
                if top_symbol == chosen_symbol:
                    score = 1.0
                    reasons = [f"Chosen {chosen_symbol} matches top-ranked from rankings table"]
                else:
                    score = 0.0
                    reasons = [f"Mismatch: chosen {chosen_symbol} vs top-ranked {top_symbol}"]
            else:
                # Fallback: check research node outputs
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
                    
                    if returns_by_symbol:
                        # Sort by return descending
                        sorted_symbols = sorted(returns_by_symbol.items(), key=lambda x: x[1], reverse=True)
                        if sorted_symbols and sorted_symbols[0][0] == chosen_symbol:
                            score = 1.0
                            reasons = [f"Chosen {chosen_symbol} matches top return from research outputs"]
                        else:
                            score = 0.0
                            reasons = [f"Mismatch: chosen {chosen_symbol} vs top return {sorted_symbols[0][0] if sorted_symbols else 'N/A'}"]
                    else:
                        score = 0.5
                        reasons = ["Rankings table missing, research outputs incomplete"]
                else:
                    score = 0.5
                    reasons = ["Rankings table missing, research node output missing"]
        else:
            # No rankings table, use research node
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
                
                if returns_by_symbol:
                    sorted_symbols = sorted(returns_by_symbol.items(), key=lambda x: x[1], reverse=True)
                    if sorted_symbols and sorted_symbols[0][0] == chosen_symbol:
                        score = 1.0
                        reasons = [f"Chosen {chosen_symbol} matches top return from research"]
                    else:
                        score = 0.0
                        reasons = [f"Mismatch: chosen {chosen_symbol} vs top {sorted_symbols[0][0] if sorted_symbols else 'N/A'}"]
                else:
                    score = 0.0
                    reasons = ["No returns computed in research node"]
            else:
                score = 0.0
                reasons = ["Research node output not found"]
    
    return {"score": score, "reasons": reasons}
