"""Profit Ranking Correctness Evaluation.

Compares the agent's selected asset against the oracle's top asset
computed from frozen candle evidence.
"""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.utils import _safe_json_loads
from backend.evals.oracle_artifacts import compute_oracle_profit_ranking

logger = get_logger(__name__)


def evaluate_profit_ranking_correctness(run_id: str, tenant_id: str) -> dict:
    """Check agent's selected asset vs oracle top asset from frozen candles.

    Returns:
        {"score": float, "reasons": list[str], "thresholds": dict, "details": dict}
    """
    oracle = compute_oracle_profit_ranking(run_id)
    if not oracle:
        return {
            "score": 0.5,
            "reasons": ["No frozen candle data available for oracle comparison"],
            "thresholds": {"pass": 0.5},
            "details": {},
        }

    # Get agent's selected symbol from rankings table
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT selected_symbol FROM rankings WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,),
        )
        ranking_row = cursor.fetchone()

    if not ranking_row:
        return {
            "score": 0.0,
            "reasons": ["No agent ranking found for this run"],
            "thresholds": {"pass": 0.5},
            "details": {"oracle_top": oracle["oracle_top_symbol"]},
        }

    agent_selected = ranking_row["selected_symbol"]
    oracle_top = oracle["oracle_top_symbol"]
    oracle_rankings = oracle["rankings"]

    # Check if agent selected the oracle top
    if agent_selected == oracle_top:
        score = 1.0
        reasons = [f"Agent selected {agent_selected}, matching oracle top asset"]
    else:
        # Check if agent selected a top-3 asset
        top3_symbols = [r["symbol"] for r in oracle_rankings[:3]]
        if agent_selected in top3_symbols:
            rank_pos = top3_symbols.index(agent_selected) + 1
            score = 0.5
            reasons = [
                f"Agent selected {agent_selected} (oracle rank #{rank_pos}), "
                f"oracle top was {oracle_top}"
            ]
        else:
            score = 0.0
            reasons = [
                f"Agent selected {agent_selected}, "
                f"oracle top was {oracle_top} (return: {oracle['oracle_top_return']:.4%})"
            ]

    return {
        "score": score,
        "reasons": reasons,
        "thresholds": {"pass": 0.5},
        "details": {
            "agent_selected": agent_selected,
            "oracle_top": oracle_top,
            "oracle_top_return": oracle["oracle_top_return"],
            "oracle_ranking_count": len(oracle_rankings),
        },
    }
