"""Determinism Replay Evaluation - verifies replay produces same results."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_determinism_replay(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Determinism Replay
    
    Checks:
    - If this is a REPLAY run, verify it produced same ranking/proposal as source run
    - Same chosen asset, same order symbol/side/notional
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Check if this is a REPLAY run
        cursor.execute(
            "SELECT execution_mode, source_run_id FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        if not run_row:
            return {"score": 1.0, "reasons": ["Run not found (evaluation skipped)"]}
        
        execution_mode = run_row["execution_mode"]
        source_run_id = run_row["source_run_id"] if run_row and "source_run_id" in run_row.keys() else None
        
        if execution_mode != "REPLAY" or not source_run_id:
            return {"score": 1.0, "reasons": ["Not a REPLAY run (evaluation skipped)"]}
        
        # Get signals outputs from both runs
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        replay_signals_row = cursor.fetchone()
        
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (source_run_id,)
        )
        source_signals_row = cursor.fetchone()
        
        if not replay_signals_row or not source_signals_row:
            return {"score": 0.0, "reasons": ["Signals outputs missing for replay or source run"]}
        
        replay_signals = json.loads(replay_signals_row["outputs_json"])
        source_signals = json.loads(source_signals_row["outputs_json"])
        
        replay_symbol = replay_signals.get("top_symbol")
        source_symbol = source_signals.get("top_symbol")
        
        # Compare chosen symbols
        if replay_symbol != source_symbol:
            return {
                "score": 0.0,
                "reasons": [f"Determinism violation: replay chose {replay_symbol} vs source {source_symbol}"]
            }
        
        # Compare proposals
        cursor.execute(
            "SELECT trade_proposal_json FROM runs WHERE run_id = ?",
            (run_id,)
        )
        replay_proposal_row = cursor.fetchone()
        
        cursor.execute(
            "SELECT trade_proposal_json FROM runs WHERE run_id = ?",
            (source_run_id,)
        )
        source_proposal_row = cursor.fetchone()
        
        if replay_proposal_row and source_proposal_row:
            replay_proposal = json.loads(replay_proposal_row["trade_proposal_json"])
            source_proposal = json.loads(source_proposal_row["trade_proposal_json"])
            
            replay_orders = replay_proposal.get("orders", [])
            source_orders = source_proposal.get("orders", [])
            
            if len(replay_orders) != len(source_orders):
                return {
                    "score": 0.0,
                    "reasons": [f"Order count mismatch: replay {len(replay_orders)} vs source {len(source_orders)}"]
                }
            
            # Compare first order
            if replay_orders and source_orders:
                replay_order = replay_orders[0]
                source_order = source_orders[0]
                
                if (replay_order.get("symbol") != source_order.get("symbol") or
                    replay_order.get("side") != source_order.get("side") or
                    abs(float(replay_order.get("notional_usd", 0)) - float(source_order.get("notional_usd", 0))) > 0.01):
                    return {
                        "score": 0.0,
                        "reasons": [
                            f"Order mismatch: replay {replay_order} vs source {source_order}"
                        ]
                    }
        
        return {
            "score": 1.0,
            "reasons": [
                f"Replay matches source: chosen symbol {replay_symbol}",
                "Order proposal matches source"
            ]
        }
