"""Proposal node - builds trade proposal with chosen asset and rationale."""
import json
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute proposal node - build trade proposal with rationale and citations."""
    with get_conn() as conn:
        cursor = conn.cursor()

        # Get intent, asset_class, and locked_product_id
        cursor.execute("SELECT intent_json, asset_class, execution_mode, locked_product_id FROM runs WHERE run_id = ?", (run_id,))
        intent_row = cursor.fetchone()
        intent = json.loads(intent_row["intent_json"]) if intent_row and "intent_json" in intent_row.keys() and intent_row["intent_json"] else {}
        action = intent.get("action") or intent.get("side", "BUY")
        action = action.upper()
        asset_class = intent_row["asset_class"] if intent_row and "asset_class" in intent_row.keys() and intent_row["asset_class"] else "CRYPTO"
        run_execution_mode = intent_row["execution_mode"] if intent_row and "execution_mode" in intent_row.keys() else "PAPER"
        locked_product_id = intent_row["locked_product_id"] if intent_row and "locked_product_id" in intent_row.keys() else None
        
        # Get signals (top symbol and return)
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
            raise ValueError("Signals node outputs not found")
        
        signals_output = json.loads(signals_row["outputs_json"])
        top_symbol = signals_output.get("top_symbol")
        top_return = signals_output.get("top_return", 0.0)

        # ── DECISION LOCK: Override top_symbol with locked_product_id if set ──
        if locked_product_id:
            locked_symbol = locked_product_id.replace("-USD", "")
            if locked_symbol != top_symbol:
                logger.warning(
                    "PROPOSAL_LOCK_OVERRIDE: run=%s signals_symbol=%s locked=%s, using locked",
                    run_id, top_symbol, locked_symbol
                )
            top_symbol = locked_symbol
        
        # Get risk sizing
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'risk'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        risk_row = cursor.fetchone()
        if not risk_row:
            raise ValueError("Risk node outputs not found")
        
        risk_output = json.loads(risk_row["outputs_json"])
        final_notional = risk_output.get("final_notional", 10.0)
        
        # Get news (optional)
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'news'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        news_row = cursor.fetchone()
        sentiment_gate = {}
        news_blockers = []  # Backwards-compat: critical blockers only
        
        if news_row:
            news_output = json.loads(news_row["outputs_json"])
            brief = news_output.get("brief", {})
            sentiment_gate = brief.get("sentiment_gate", {})
            # Only critical blockers are treated as hard blocks
            news_blockers = [b for b in sentiment_gate.get("critical_blockers", []) if b.get("asset") == top_symbol]
        
        # Get citations from research
        cursor.execute(
            "SELECT results_json FROM retrievals WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,)
        )
        retrieval_row = cursor.fetchone()
        citations = []
        if retrieval_row:
            retrieval_results = json.loads(retrieval_row["results_json"])
            citations = retrieval_results.get("citations", [])
        
        # Decision Logic
        # Sentiment gate + critical blockers only prevent BUY orders, not SELL orders.
        # Bearish news actually supports sell decisions.
        is_buy = action in ("BUY", "MARKET_BUY")
        is_sentiment_gated = sentiment_gate.get("gated", False) and is_buy
        is_critical_blocked = len(news_blockers) > 0 and is_buy
        is_blocked = is_critical_blocked  # Only critical blockers fully block
        rationale = ""
        orders = []
        
        if is_blocked:
            blocker_reasons = "; ".join([f"{b.get('keyword', 'unknown')} ({b.get('title', 'news item')})" for b in news_blockers])
            rationale = f"BLOCKED: {top_symbol} has critical security alerts: {blocker_reasons}"
        else:
            # Add asset_class and execution mode context to rationale
            if asset_class == "STOCK":
                rationale = f"Selected {top_symbol} based on {top_return:.2%} EOD return. " \
                            f"Budget: ${final_notional:.2f}. ASSISTED_LIVE mode: order ticket will be generated."
            else:
                rationale = f"Selected {top_symbol} based on {top_return:.2%} return over lookback window. " \
                            f"Budget: ${final_notional:.2f} (with fee buffer)."

            # Indicate news / sentiment status in rationale
            if not news_row:
                rationale += " News analysis disabled."
            elif is_sentiment_gated:
                gate_explanation = sentiment_gate.get("explanation", "Bearish sentiment detected")
                rationale += f" WARNING: {gate_explanation}. Proceeding with risk override allowed."
            elif sentiment_gate.get("bearish_count", 0) > 0 and not is_buy:
                rationale += " Bearish news detected (supports SELL decision)."
            elif sentiment_gate.get("net_sentiment", 0) > 0:
                rationale += f" News sentiment: positive ({sentiment_gate.get('net_sentiment', 0):.2f})."

            # Set execution_mode for stocks
            order_mode = "ASSISTED_LIVE" if (asset_class == "STOCK" or run_execution_mode == "ASSISTED_LIVE") else None
            order = {
                "symbol": top_symbol,
                "side": action,
                "notional_usd": final_notional,
                "order_type": "MARKET"
            }
            if order_mode:
                order["execution_mode"] = order_mode
            orders = [order]

        # Build proposal
        proposal = {
            "orders": orders,
            "citations": citations,
            "rationale": rationale,
            "expected_return_24h": top_return,
            "confidence": 0.0 if is_blocked else min(0.95, 0.5 + abs(top_return) * 2),
            "chosen_product_id": top_symbol
        }
        
        # Create DecisionRecord Artifact
        decision_record = {
            "selected_asset": None if is_blocked else top_symbol,
            "action": action,
            "orders": orders,
            "rationale": rationale,
            "blockers": news_blockers,
            "sentiment_gate": sentiment_gate,
            "sentiment_gated": is_sentiment_gated,
            "risk_override_allowed": sentiment_gate.get("risk_override_allowed", False),
            "constraints_triggered": [
                {
                    "type": "news",
                    "name": "critical_news_blocker",
                    "severity": "CRITICAL",
                    "details": b.get("keyword", "unknown block")
                } for b in news_blockers
            ]
        }
        cursor.execute(
            """
            INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
            VALUES (?, 'proposal', 'decision_record', ?)
            """,
            (run_id, json.dumps(decision_record))
        )

        # Create decision_table artifact (ALWAYS per spec)
        # Get rankings and drop reasons from research node
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes
            WHERE run_id = ? AND name = 'research'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        research_row = cursor.fetchone()
        ranked_candidates = []
        dropped_symbols = {}
        granularity = "1h"
        staleness_note = None

        if research_row:
            research_output = json.loads(research_row["outputs_json"])
            returns_by_symbol = research_output.get("returns_by_symbol", {})
            dropped_symbols = research_output.get("drop_reasons", {})
            granularity = research_output.get("granularity", "1h")

            # Build ranked candidates list
            for symbol, return_val in sorted(returns_by_symbol.items(), key=lambda x: x[1], reverse=True):
                ranked_candidates.append({
                    "symbol": symbol,
                    "return_pct": return_val * 100,
                    "selected": symbol == top_symbol,
                    "status": "selected" if symbol == top_symbol else "candidate"
                })

            # For stocks (EOD data), add staleness note
            if asset_class == "STOCK" or granularity in ("1d", "EOD"):
                staleness_note = "EOD data: prices may be up to 1 business day old"

        decision_table = {
            "asset_class": asset_class,
            "granularity": granularity,
            "staleness_note": staleness_note,
            "ranked_candidates": ranked_candidates,
            "dropped_symbols": dropped_symbols,
            "final_selection": {
                "symbol": top_symbol if not is_blocked else None,
                "return_pct": top_return * 100,
                "blocked": is_blocked,
                "sentiment_gated": is_sentiment_gated,
                "block_reason": news_blockers[0].get("keyword") if news_blockers else None,
                "net_sentiment": sentiment_gate.get("net_sentiment"),
            },
            "created_at": now_iso()
        }
        cursor.execute(
            """
            INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
            VALUES (?, 'proposal', 'decision_table', ?)
            """,
            (run_id, json.dumps(decision_table))
        )
        conn.commit()

    # Store proposal in run
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE runs SET trade_proposal_json = ? WHERE run_id = ?",
            (json.dumps(proposal), run_id)
        )
        conn.commit()
    
    # Store in dag_nodes
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(proposal), node_id)
        )
        conn.commit()
    
    return proposal
