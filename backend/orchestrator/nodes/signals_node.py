"""Signals node - computes top movers and momentum."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.ids import new_id
from backend.core.time import now_iso

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute signals node - rank top movers from research results."""
    # Get research node outputs
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes
            WHERE run_id = ? AND name = 'research'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        row = cursor.fetchone()

        if not row or "outputs_json" not in row.keys() or not row["outputs_json"]:
            raise ValueError("Research node outputs not found")

        research_output = json.loads(row["outputs_json"])

    returns_by_symbol = research_output.get("returns_by_symbol", {})
    lookback_hours = research_output.get("lookback_hours", 24)

    # Rank by return (descending)
    rankings = [
        {"symbol": sym, "return_pct": ret}
        for sym, ret in returns_by_symbol.items()
    ]
    rankings.sort(key=lambda x: x["return_pct"], reverse=True)

    if not rankings:
        # Persist signals_failure artifact with reasons
        drop_reasons = research_output.get("drop_reasons", {})
        failure_artifact = {
            "summary": "Signals node: no valid rankings from research node.",
            "universe_size": len(research_output.get("universe", [])),
            "drop_reasons": drop_reasons,
            "lookback_hours": lookback_hours,
            "failed_at": now_iso()
        }
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                   VALUES (?, 'signals', 'signals_failure', ?)""",
                (run_id, json.dumps(failure_artifact))
            )
            conn.commit()
        raise ValueError(
            f"No valid rankings from research node. "
            f"Universe={len(research_output.get('universe', []))}, "
            f"all assets dropped. Check research_debug artifact for details."
        )

    # Check if a specific asset was pre-selected or decision-locked
    pre_selected_symbol = None
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT execution_plan_json, locked_product_id FROM runs WHERE run_id = ?", (run_id,))
        plan_row = cursor.fetchone()

        # DECISION LOCK takes priority over execution_plan
        locked_product_id = plan_row["locked_product_id"] if plan_row and "locked_product_id" in plan_row.keys() else None
        if locked_product_id:
            pre_selected_symbol = locked_product_id  # e.g. "HNT-USD"
            logger.info("SIGNALS_DECISION_LOCK: run=%s using locked_product_id=%s", run_id, locked_product_id)
        elif plan_row and plan_row["execution_plan_json"]:
            try:
                plan = json.loads(plan_row["execution_plan_json"])
                pre_selected_symbol = plan.get("selected_asset")
            except Exception:
                pass

    if pre_selected_symbol:
        # Use the pre-selected asset (user explicitly asked for it)
        matching = [r for r in rankings if r["symbol"] == pre_selected_symbol]
        if matching:
            top_symbol = matching[0]["symbol"]
            top_return = matching[0]["return_pct"]
            logger.info("Using pre-selected asset %s (return: %.4f)", top_symbol, top_return)
        else:
            # Asset was in universe but got dropped by research - use it anyway with 0 return
            top_symbol = pre_selected_symbol
            top_return = 0.0
            rankings.insert(0, {"symbol": top_symbol, "return_pct": top_return})
            logger.warning("Pre-selected asset %s not in rankings, using with 0 return", top_symbol)
    else:
        top_symbol = rankings[0]["symbol"]
        top_return = rankings[0]["return_pct"]

    # Compute momentum and volatility (simplified)
    momentum = "positive" if top_return > 0 else "negative"
    signal_strength = min(1.0, abs(top_return) * 10)  # Normalize to 0-1

    # Get last price from research output if available
    last_prices = research_output.get("last_prices_by_symbol", {})
    last_price = last_prices.get(top_symbol)

    signals_output = {
        "rankings": rankings,
        "top_symbol": top_symbol,
        "top_return": top_return,
        "last_price": last_price,
        "momentum": momentum,
        "signal_strength": signal_strength,
        "universe_size": len(returns_by_symbol),
        "lookback_hours": lookback_hours
    }

    # Store in dag_nodes
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(signals_output), node_id)
        )
        conn.commit()

    # Store ranking evidence in rankings table (for evals and UI)
    with get_conn() as conn:
        cursor = conn.cursor()
        ranking_id = new_id("rank_")
        cursor.execute(
            """
            INSERT OR REPLACE INTO rankings (
                ranking_id, run_id, node_id, window, metric, selected_symbol, selected_score, table_json, ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ranking_id, run_id, node_id, f"{lookback_hours}h", "return_pct", top_symbol, top_return, json.dumps(rankings), now_iso())
        )

        # Create snapshot after decision (Snapshot 2: after research/decision)
        from backend.providers.paper import PaperProvider
        provider = PaperProvider()
        balances, positions, total_value = provider._get_portfolio_state(conn, cursor, tenant_id)

        snapshot_id = new_id("snap_")
        cursor.execute(
            """
            INSERT INTO portfolio_snapshots (
                snapshot_id, run_id, tenant_id, balances_json, positions_json, total_value_usd, ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (snapshot_id, run_id, tenant_id, json.dumps(balances), json.dumps(positions), total_value, now_iso())
        )
        conn.commit()

    return signals_output
