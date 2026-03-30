"""Strategy node - selects top asset based on metric."""
import json
from datetime import datetime, timedelta
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.services.strategy_engine import select_top_asset
from backend.mcp_servers.market_data_server import market_data_server
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute strategy node - selects top asset based on strategy spec."""
    # Get execution plan from run
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT execution_plan_json FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()

        if not row or "execution_plan_json" not in row.keys() or not row["execution_plan_json"]:
            raise ValueError("No execution plan found in run")

        execution_plan = json.loads(row["execution_plan_json"])
        strategy_spec = execution_plan["strategy_spec"]
        trade_intent = execution_plan["trade_intent"]

    # Fetch candles for all symbols in universe
    window = strategy_spec["window"]
    universe = strategy_spec["universe"]
    metric = strategy_spec["metric"]
    lookback_hours = strategy_spec.get("lookback_hours", trade_intent.get("lookback_hours", 24))

    candles_by_symbol = {}
    candle_ids_by_symbol = {}

    # --- Try to consume financial_brief from research node first ---
    # This avoids redundant Coinbase API calls and ensures data consistency.
    rankings = []
    used_financial_brief = False

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'financial_brief'",
            (run_id,)
        )
        brief_row = cursor.fetchone()

    if brief_row:
        try:
            brief = json.loads(brief_row["artifact_json"])
            ranked_assets = brief.get("ranked_assets", [])
            if ranked_assets:
                for asset in ranked_assets:
                    rankings.append({
                        "symbol": asset["product_id"],
                        "score": asset["return_48h"],
                        "volume_proxy": 0,
                        "candles_count": asset.get("candles_count", 0),
                        "first_price": 0.0,
                        "last_price": asset.get("last_price", 0.0)
                    })
                used_financial_brief = True
                logger.info(f"Strategy consuming financial_brief: {len(rankings)} pre-ranked assets")
        except Exception as e:
            logger.warning(f"Failed to parse financial_brief, falling back to fetch: {e}")

    # --- Fallback: fetch candles independently if no financial_brief ---
    if not used_financial_brief:
        # Use lookback_hours with buffer for time window
        end_time = datetime.utcnow()
        buffer_hours = max(lookback_hours * 1.25, lookback_hours + 12)
        start_time = end_time - timedelta(hours=buffer_hours)

        # Select granularity: ONE_HOUR for up to 7 days, ONE_DAY for longer
        granularity_label = "1h" if lookback_hours <= 168 else "24h"

        for symbol in universe:
            # Fetch candles via MCP
            try:
                result = market_data_server.fetch_candles(
                    run_id=run_id,
                    node_id=node_id,
                    symbol=symbol,
                    interval=granularity_label,
                    start_time=start_time.isoformat() + "Z",
                    end_time=end_time.isoformat() + "Z",
                    limit=300
                )

                candles = result["candles"]
                candles_by_symbol[symbol] = candles

                # Store candles in DB
                candle_ids = []
                with get_conn() as conn:
                    cursor = conn.cursor()
                    for candle in candles:
                        candle_id = new_id("candle_")
                        cursor.execute(
                            """
                            INSERT INTO market_candles (
                                id, symbol, interval, start_time, end_time,
                                open, high, low, close, volume, ts
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(symbol, interval, start_time) DO NOTHING
                            """,
                            (
                                candle_id, symbol, granularity_label, candle["start_time"], candle["end_time"],
                                candle["open"], candle["high"], candle["low"], candle["close"],
                                candle.get("volume", 0.0), now_iso()
                            )
                        )
                        candle_ids.append(candle_id)
                    conn.commit()

                candle_ids_by_symbol[symbol] = candle_ids

            except Exception as e:
                logger.warning(f"Failed to fetch candles for {symbol}: {e}")
                candles_by_symbol[symbol] = []

        # Compute rankings (all symbols scored)
        from backend.services.strategy_engine import compute_returns, compute_sharpe_proxy, compute_momentum

        MIN_CANDLES = max(int(lookback_hours * 0.75), 2) if lookback_hours <= 168 else 2

        for symbol in universe:
            candles = candles_by_symbol.get(symbol, [])
            if len(candles) < MIN_CANDLES:
                continue

            # Compute metric
            if metric == "return":
                score = compute_returns(candles)
            elif metric == "sharpe_proxy":
                score = compute_sharpe_proxy(candles)
            elif metric == "momentum":
                score = compute_momentum(candles)
            else:
                score = compute_returns(candles)

            # Compute volume proxy (for tie-breaking)
            volume_proxy = sum(float(c.get("volume", 0)) for c in candles) / len(candles) if candles else 0.0

            rankings.append({
                "symbol": symbol,
                "score": score,
                "volume_proxy": volume_proxy,
                "candles_count": len(candles),
                "first_price": float(candles[0]["close"]) if candles else 0.0,
                "last_price": float(candles[-1]["close"]) if candles else 0.0
            })

        # Sort by score descending, then volume_proxy descending, then alphabetically
        rankings.sort(key=lambda x: (x["score"], x["volume_proxy"], x["symbol"]), reverse=True)

    if not rankings:
        # Persist strategy_failure artifact
        failure_artifact = {
            "summary": "Strategy node: no valid rankings computed.",
            "universe_size": len(universe),
            "metric": metric,
            "lookback_hours": lookback_hours,
            "candles_counts": {sym: len(cs) for sym, cs in candles_by_symbol.items()},
            "min_candles_required": MIN_CANDLES,
            "failed_at": now_iso()
        }
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                   VALUES (?, 'strategy', 'strategy_failure', ?)""",
                (run_id, json.dumps(failure_artifact))
            )
            conn.commit()
        raise ValueError(
            f"No valid rankings computed - insufficient candle data "
            f"(need >= {MIN_CANDLES} candles per asset, lookback={lookback_hours}h)"
        )

    # Select top asset
    top_ranking = rankings[0]
    selected_symbol = top_ranking["symbol"]
    selected_score = top_ranking["score"]

    # Create strategy result
    from backend.agents.schemas import StrategyResult
    strategy_result = StrategyResult(
        selected_symbol=selected_symbol,
        score=selected_score,
        rationale=f"Selected {selected_symbol} based on {metric} metric (score: {selected_score:.4f}). "
                  f"Ranked {len(rankings)} assets over {lookback_hours}h. "
                  f"Top asset moved from ${top_ranking['first_price']:.2f} to ${top_ranking['last_price']:.2f}.",
        features_json={
            "rankings": rankings[:10],
            "metric": metric,
            "window": window,
            "lookback_hours": lookback_hours
        },
        computed_at=now_iso(),
        candles_used=top_ranking["candles_count"]
    )

    # Store evidence artifacts
    with get_conn() as conn:
        cursor = conn.cursor()

        # Store candles batches (evidence)
        for symbol in universe:
            if symbol in candles_by_symbol and candles_by_symbol[symbol]:
                batch_id = new_id("batch_")
                cursor.execute(
                    """
                    INSERT INTO market_candles_batches (
                        batch_id, run_id, node_id, symbol, window, candles_json, query_params_json, ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id, run_id, node_id, symbol, window,
                        json.dumps(candles_by_symbol[symbol]),
                        json.dumps({
                            "start_time": start_time.isoformat() + "Z",
                            "end_time": end_time.isoformat() + "Z",
                            "lookback_hours": lookback_hours,
                            "limit": 300
                        }),
                        now_iso()
                    )
                )

        # Store rankings (evidence)
        ranking_id = new_id("rank_")
        cursor.execute(
            """
            INSERT INTO rankings (
                ranking_id, run_id, node_id, window, metric, table_json, selected_symbol, selected_score, rationale, ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ranking_id, run_id, node_id, window, metric,
                json.dumps(rankings),
                selected_symbol, selected_score,
                strategy_result.rationale,
                now_iso()
            )
        )

        # Store strategy_candles reference (existing)
        if selected_symbol in candle_ids_by_symbol:
            candle_ids = candle_ids_by_symbol[selected_symbol]
            strategy_candle_id = new_id("sc_")
            cursor.execute(
                """
                INSERT INTO strategy_candles (
                    id, run_id, node_id, symbol, interval, candle_ids, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (strategy_candle_id, run_id, node_id, selected_symbol, window, json.dumps(candle_ids), now_iso())
            )

        # Persist strategy_decision artifact (for UI instrumentation)
        decision_artifact = {
            "chosen_asset": selected_symbol,
            "chosen_score": selected_score,
            "metric": metric,
            "lookback_hours": lookback_hours,
            "alternatives": [
                {"symbol": r["symbol"], "score": r["score"]}
                for r in rankings[1:5]
            ],
            "total_candidates": len(rankings),
            "decided_at": now_iso()
        }
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
               VALUES (?, 'strategy', 'strategy_decision', ?)""",
            (run_id, json.dumps(decision_artifact))
        )

        # Persist selection_basis artifact for demo observability
        selection_basis = {
            "method": f"{lookback_hours}h_{metric}_ranking",
            "selected_symbol": selected_symbol,
            "computed_return_7d": top_ranking["score"],
            "candidates_considered_count": len(rankings),
            "candidates": [
                {
                    "symbol": r["symbol"],
                    "return_7d": r["score"],
                    "first_price": r.get("first_price"),
                    "last_price": r.get("last_price"),
                    "candles_count": r.get("candles_count", 0),
                    "skipped_reason": None if r.get("candles_count", 0) >= 2 else "insufficient_candle_data",
                }
                for r in rankings[:10]
            ],
            "fallback_used": None,
            "computed_at": now_iso(),
        }
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
               VALUES (?, 'strategy', 'selection_basis', ?)""",
            (run_id, json.dumps(selection_basis))
        )

        # Update execution plan with selected asset
        execution_plan["selected_asset"] = selected_symbol
        execution_plan["selected_order"] = {
            "symbol": selected_symbol,
            "side": trade_intent["side"],
            "notional_usd": trade_intent["budget_usd"]
        }
        execution_plan["decision_trace"].append({
            "step": "strategy_execution",
            "strategy_result": strategy_result.dict(),
            "evidence_refs": {
                "ranking_id": ranking_id,
                "candle_batch_ids": list(candle_ids_by_symbol.get(selected_symbol, []))[:5]
            },
            "timestamp": now_iso()
        })

        cursor.execute(
            "UPDATE runs SET execution_plan_json = ? WHERE run_id = ?",
            (json.dumps(execution_plan), run_id)
        )

        conn.commit()

    # Emit DECISION event
    from backend.orchestrator.event_emitter import emit_event
    await emit_event(run_id, "DECISION", {
        "decision_type": "asset_selection",
        "selected_symbol": selected_symbol,
        "selected_score": selected_score,
        "metric": metric,
        "lookback_hours": lookback_hours,
        "rankings_count": len(rankings),
        "evidence_refs": {
            "ranking_id": ranking_id,
            "top_3_symbols": [r["symbol"] for r in rankings[:3]]
        }
    }, tenant_id=tenant_id)

    return {
        "strategy_result": strategy_result.dict(),
        "candles_by_symbol": {sym: len(cs) for sym, cs in candles_by_symbol.items()},
        "evidence_refs": {
            "ranking_id": ranking_id,
            "candles_batches": len(universe)
        },
        "safe_summary": f"Selected {selected_symbol} as most profitable asset ({metric}={selected_score:.2%}) from {len(rankings)} candidates over {lookback_hours}h"
    }
