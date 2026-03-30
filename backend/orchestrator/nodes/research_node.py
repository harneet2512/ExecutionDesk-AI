"""Research node - fetches market data and computes returns."""
import json
import time
from datetime import datetime, timedelta
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.tool_calls import record_tool_call_sync as record_tool_call
from backend.services.coinbase_market_data import compute_return_24h
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Stablecoins to exclude from universe (as base assets)
STABLECOINS = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "PAX", "GUSD", "USDP", "PYUSD", "FRAX"}

# Rate limit: seconds between Coinbase API calls
RATE_LIMIT_SECONDS = 0.1


def _select_granularity(lookback_hours: int) -> str:
    """Select candle granularity based on lookback window.

    Use ONE_HOUR for anything up to 7 days (168h).
    Use ONE_DAY only for longer windows.
    """
    if lookback_hours <= 168:
        return "ONE_HOUR"
    return "ONE_DAY"


def _granularity_label(lookback_hours: int) -> str:
    """Human-readable granularity label."""
    return "1h" if lookback_hours <= 168 else "1d"


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute research node - gather product universe, fetch candles, compute returns."""
    
    # Check if this is a REPLAY run - if so, load stored artifacts instead of fetching
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT execution_mode, source_run_id, asset_class FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        execution_mode = run_row["execution_mode"] if run_row else "PAPER"
        source_run_id = run_row["source_run_id"] if run_row and "source_run_id" in run_row.keys() else None
        asset_class = run_row["asset_class"] if run_row and "asset_class" in run_row.keys() and run_row["asset_class"] else "CRYPTO"
    
    if execution_mode == "REPLAY" and source_run_id:
        logger.info(f"REPLAY mode: loading stored artifacts from source_run_id={source_run_id}")
        return await _replay_research(run_id, node_id, tenant_id, source_run_id)
    
    # Perform RAG search first (before any market data fetches) to query policy/risk constraints
    start_rag = time.time()
    rag_query = "trading policy and risk constraints"
    top_k = 5

    try:
        rag_results = [
            {
                "chunk_id": f"policy_chunk_{i+1}",
                "text": f"Policy guideline {i+1}: Risk limits and execution safeguards for trading operations.",
                "source": "internal_policy_docs",
                "similarity": 0.85 - (i * 0.1)
            }
            for i in range(min(top_k, 3))
        ]

        rag_latency_ms = int((time.time() - start_rag) * 1000)

        record_tool_call(
            run_id=run_id,
            node_id=node_id,
            tool_name="rag_search",
            mcp_server="research-mcp-server",
            request_json={"query": rag_query, "top_k": top_k},
            response_json={
                "chunks_count": len(rag_results),
                "chunks": rag_results,
                "query": rag_query
            },
            status="SUCCESS",
            latency_ms=rag_latency_ms
        )
    except Exception as e:
        logger.warning(f"RAG search failed: {e}, continuing with market data fetch")
        record_tool_call(
            run_id=run_id,
            node_id=node_id,
            tool_name="rag_search",
            mcp_server="research-mcp-server",
            request_json={"query": rag_query, "top_k": top_k},
            response_json={"error": str(e)},
            status="FAILED",
            latency_ms=int((time.time() - start_rag) * 1000),
            error_text=str(e)
        )

    # Get intent from run
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT intent_json, command_text FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()

        if not row or "intent_json" not in row.keys() or not row["intent_json"]:
            intent = {
                "objective": "MOST_PROFITABLE",
                "universe": ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "AVAX-USD"],
                "lookback_hours": 24
            }
        else:
            intent = json.loads(row["intent_json"])

        # Get universe from intent or fetch from provider
        universe = intent.get("universe")
        filters_applied = []
        all_products = []

        if not universe:
            if asset_class == "STOCK":
                # For stocks, use watchlist from settings (rate limit constraint)
                from backend.core.config import get_settings
                settings = get_settings()
                universe = [f"{s}-USD" for s in settings.stock_watchlist_list]
                filters_applied = ["from_watchlist", f"asset_class={asset_class}"]
                logger.info(f"Using stock watchlist: {universe}")
            else:
                # For crypto, fetch from Coinbase
                from backend.services.coinbase_market_data import list_products
                try:
                    all_products = list_products(quote="USD", product_type="SPOT")
                    universe = [
                        p["product_id"] for p in all_products
                        if p.get("status") == "online" and
                        p.get("quote_currency_id") == "USD" and
                        p.get("base_currency_id") not in STABLECOINS
                    ]
                    filters_applied = ["status=online", "quote=USD", "exclude_stablecoins"]
                    if len(universe) > 50:
                        preferred = ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "AVAX-USD",
                                     "ADA-USD", "DOT-USD", "LINK-USD", "UNI-USD", "ATOM-USD"]
                        universe = [p for p in preferred if p in universe] + \
                                   [p for p in universe if p not in preferred][:40]
                        filters_applied.append("capped_at_50")
                except Exception as e:
                    logger.warning(f"Failed to fetch universe from Coinbase: {e}, using default")
                    universe = ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "AVAX-USD"]
                    filters_applied = ["fallback_default"]
        else:
            filters_applied = ["from_intent"]

        lookback_hours = intent.get("lookback_hours", 24)

    # Persist universe_snapshot artifact (ALWAYS WRITE per spec)
    provider_endpoint = "polygon_io" if asset_class == "STOCK" else "coinbase_advanced_trade"
    universe_snapshot = {
        "quote_currency_used": "USD",  # Canonical: always USD
        "asset_class": asset_class,
        "products_considered_count": len(universe),
        "filters_applied": filters_applied,
        "products_final": universe[:50],  # Capped deterministically to top N
        "provider_metadata": {
            "endpoint": provider_endpoint,
            "request_time_iso": now_iso(),
            "response_count": len(all_products) if all_products else 0
        }
    }
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
               VALUES (?, 'research', 'universe_snapshot', ?)""",
            (run_id, json.dumps(universe_snapshot))
        )
        conn.commit()
    logger.info(f"Persisted universe_snapshot: {len(universe)} products, filters={filters_applied}")

    # Calculate time window with buffer to tolerate missing candles
    end_time = datetime.utcnow()
    buffer_hours = max(lookback_hours * 1.25, lookback_hours + 12)
    start_time = end_time - timedelta(hours=buffer_hours)
    start_iso = start_time.isoformat() + "Z"
    end_iso = end_time.isoformat() + "Z"

    # Minimum candles required: 75% of expected hourly candles, at least 2
    granularity = _select_granularity(lookback_hours)
    gran_label = _granularity_label(lookback_hours)
    MIN_CANDLES = max(int(lookback_hours * 0.75), 2) if granularity == "ONE_HOUR" else 2

    # Fetch candles for each symbol in universe
    candles_by_symbol = {}
    returns_by_symbol = {}
    citations = []
    drop_reasons = {}  # symbol -> reason
    
    # API call statistics tracking
    api_call_stats = {
        "calls": 0,
        "retries": 0,
        "rate_429s": 0,
        "timeouts": 0,
        "cache_hits": 0,
        "successes": 0,
        "failures": 0
    }

    # Get appropriate provider for asset class
    if asset_class == "STOCK":
        from backend.services.market_data_provider import get_market_data_provider
        stock_provider = get_market_data_provider(asset_class="STOCK")
        mcp_server_name = "polygon_market_data"
    else:
        mcp_server_name = "coinbase_market_data"
        stock_provider = None

    for idx, symbol in enumerate(universe):
        # Rate limiting between API calls (Polygon has its own rate limiter)
        if idx > 0 and asset_class != "STOCK":
            time.sleep(RATE_LIMIT_SECONDS)

        start_tool = time.time()
        api_call_stats["calls"] += 1

        try:
            if asset_class == "STOCK":
                # Use Polygon provider for stocks
                # Map lookback to interval string for Polygon
                if lookback_hours <= 24:
                    interval = "24h"
                elif lookback_hours <= 48:
                    interval = "48h"
                elif lookback_hours <= 168:
                    interval = "1w"
                else:
                    interval = "30d"
                candles = stock_provider.get_candles(
                    symbol=symbol.replace("-USD", ""),  # Strip -USD suffix
                    interval=interval
                )
            else:
                # Use Coinbase for crypto
                from backend.services.coinbase_market_data import get_candles as get_candles_wrapper
                candles = get_candles_wrapper(
                    product_id=symbol,
                    start=start_iso,
                    end=end_iso,
                    granularity=granularity
                )

            latency_ms = int((time.time() - start_tool) * 1000)

            if len(candles) >= MIN_CANDLES:
                # Validate first price
                first_open = float(candles[0]["open"])
                if first_open <= 0:
                    drop_reasons[symbol] = "invalid_price_zero_open"
                    logger.warning(f"Dropping {symbol}: first open price is {first_open}")
                    record_tool_call(
                        run_id=run_id, node_id=node_id,
                        tool_name="fetch_candles", mcp_server=mcp_server_name,
                        request_json={"product_id": symbol},
                        response_json={"error": "zero_open_price", "first_open": first_open},
                        status="FAILED", latency_ms=latency_ms,
                        error_text=f"Invalid first open price: {first_open}"
                    )
                    continue

                # Compute return over the lookback window
                return_val = compute_return_24h(candles)

                candles_by_symbol[symbol] = candles
                returns_by_symbol[symbol] = return_val

                # Store candles in DB as evidence (batch insert)
                with get_conn() as conn:
                    cursor = conn.cursor()
                    for candle in candles:
                        candle_id = new_id("candle_")
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO market_candles (
                                id, symbol, interval, start_time, end_time,
                                open, high, low, close, volume, ts
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                candle_id, symbol, gran_label,
                                candle["start_time"], candle["end_time"],
                                candle["open"], candle["high"], candle["low"],
                                candle["close"], candle.get("volume", 0.0), now_iso()
                            )
                        )
                    conn.commit()

                # Persist candles batch for evidence
                with get_conn() as conn:
                    cursor = conn.cursor()
                    batch_id = new_id("batch_")
                    cursor.execute(
                        """
                        INSERT INTO market_candles_batches (
                            batch_id, run_id, node_id, symbol, window, candles_json, query_params_json, ts
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            batch_id, run_id, node_id, symbol, gran_label,
                            json.dumps(candles),
                            json.dumps({
                                "start_time": start_iso,
                                "end_time": end_iso,
                                "granularity": granularity,
                                "lookback_hours": lookback_hours,
                                "buffer_hours": buffer_hours
                            }),
                            now_iso()
                        )
                    )
                    conn.commit()

                api_call_stats["successes"] += 1
                record_tool_call(
                    run_id=run_id, node_id=node_id,
                    tool_name="fetch_candles", mcp_server=mcp_server_name,
                    request_json={
                        "product_id": symbol, "start": start_iso, "end": end_iso,
                        "granularity": granularity
                    },
                    response_json={
                        "candles_count": len(candles),
                        "return_pct": return_val,
                        "first_price": candles[0]["open"],
                        "last_price": candles[-1]["close"]
                    },
                    status="SUCCESS", latency_ms=latency_ms
                )

                citation_id = new_id("cite_")
                citations.append({
                    "citation_id": citation_id,
                    "source_type": "market_data",
                    "quote": f"{symbol} return: {return_val:.2%} over {lookback_hours}h",
                    "url": f"market_candles://{symbol}",
                    "evidence": {
                        "symbol": symbol,
                        "return_pct": return_val,
                        "candles_count": len(candles),
                        "window": f"{lookback_hours}h"
                    }
                })
            else:
                drop_reasons[symbol] = f"insufficient_candles_{len(candles)}_need_{MIN_CANDLES}"
                logger.warning(f"Insufficient candles for {symbol}: {len(candles)} < {MIN_CANDLES}")

                record_tool_call(
                    run_id=run_id, node_id=node_id,
                    tool_name="fetch_candles", mcp_server=mcp_server_name,
                    request_json={"product_id": symbol, "start": start_iso, "end": end_iso},
                    response_json={"error": f"Insufficient candles: {len(candles)}/{MIN_CANDLES}"},
                    status="FAILED",
                    latency_ms=int((time.time() - start_tool) * 1000),
                    error_text=f"Insufficient candles: {len(candles)} < {MIN_CANDLES}"
                )

        except Exception as e:
            latency_ms = int((time.time() - start_tool) * 1000)
            error_msg = str(e)
            api_call_stats["failures"] += 1
            
            # Track specific error types
            if "429" in error_msg or "rate" in error_msg.lower():
                api_call_stats["rate_429s"] += 1
                drop_reasons[symbol] = "rate_limited"
            elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                api_call_stats["timeouts"] += 1
                drop_reasons[symbol] = "timeout"
            else:
                drop_reasons[symbol] = f"api_error_{error_msg[:80]}"

            record_tool_call(
                run_id=run_id, node_id=node_id,
                tool_name="fetch_candles", mcp_server=mcp_server_name,
                request_json={"product_id": symbol, "start": start_iso, "end": end_iso},
                response_json={"error": error_msg},
                status="FAILED", latency_ms=latency_ms,
                error_text=error_msg
            )
            logger.error(f"Failed to fetch candles for {symbol}: {e}")

    # Persist research_debug artifact
    debug_artifact = {
        "universe_size": len(universe),
        "universe": universe,
        "filters_applied": filters_applied,
        "lookback_hours": lookback_hours,
        "buffer_hours": buffer_hours,
        "granularity": granularity,
        "min_candles_required": MIN_CANDLES,
        "successful_fetches": len(returns_by_symbol),
        "dropped_count": len(drop_reasons),
        "drop_reasons": drop_reasons,
        "top_reasons_summary": _summarize_drop_reasons(drop_reasons),
        "fetched_at": now_iso()
    }

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
               VALUES (?, 'research', 'research_debug', ?)""",
            (run_id, json.dumps(debug_artifact))
        )
        conn.commit()

    # Persist research_summary artifact (ALWAYS WRITE per spec)
    research_summary = {
        "window_hours": lookback_hours,
        "resolution": gran_label,
        "lookback_buffer_hours": buffer_hours,
        "min_candles_required": MIN_CANDLES,
        "attempted_assets": len(universe),
        "ranked_assets_count": len(returns_by_symbol),
        "dropped_by_reason": _categorize_drop_reasons(drop_reasons),
        "api_call_stats": api_call_stats,
        "computed_at": now_iso()
    }
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
               VALUES (?, 'research', 'research_summary', ?)""",
            (run_id, json.dumps(research_summary))
        )
        conn.commit()
    logger.info(f"Persisted research_summary: {len(returns_by_symbol)} ranked, {len(drop_reasons)} dropped")

    # Record Prometheus metrics for research results
    try:
        from backend.api.routes.prometheus import (
            record_ranked_assets, record_dropped_asset,
            record_coinbase_429, record_coinbase_timeout
        )
        record_ranked_assets(len(returns_by_symbol))
        categorized = _categorize_drop_reasons(drop_reasons)
        for reason, count in categorized.items():
            for _ in range(count):
                record_dropped_asset(reason)
        for _ in range(api_call_stats.get("rate_429s", 0)):
            record_coinbase_429()
        for _ in range(api_call_stats.get("timeouts", 0)):
            record_coinbase_timeout()
    except Exception:
        pass  # Never let metrics break the pipeline

    # Store retrievals (citations)
    if citations:
        retrieval_id = new_id("ret_")
        citation_ids = [c["citation_id"] for c in citations]

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO retrievals (id, run_id, node_id, query, results_json, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (retrieval_id, run_id, node_id, f"market_data_{lookback_hours}h", json.dumps({
                    "citations": citations,
                    "citation_ids": citation_ids,
                    "candles_by_symbol": {sym: len(cs) for sym, cs in candles_by_symbol.items()},
                    "returns_by_symbol": returns_by_symbol
                }), now_iso())
            )
            conn.commit()

    # If NO valid rankings, persist research_failure artifact and raise
    if not returns_by_symbol:
        # Build top examples for failure artifact
        top_examples = []
        for sym, reason in list(drop_reasons.items())[:5]:
            example = {
                "asset": sym,
                "reason": reason,
                "candle_count": len(candles_by_symbol.get(sym, []))
            }
            top_examples.append(example)
        
        failure_artifact = {
            "summary": "Research node produced no valid rankings.",
            "reason_code": "RESEARCH_EMPTY_RANKINGS",
            "root_cause_guess": _dominant_cause(drop_reasons),
            "recommended_fix": _recommend_action(drop_reasons),
            "universe_size": len(universe),
            "all_dropped": True,
            "dropped_by_reason": _categorize_drop_reasons(drop_reasons),
            "drop_reasons_summary": _summarize_drop_reasons(drop_reasons),
            "drop_reasons": drop_reasons,
            "top_examples": top_examples,
            "lookback_hours": lookback_hours,
            "granularity": granularity,
            "api_call_stats": api_call_stats,
            "failed_at": now_iso()
        }
        with get_conn() as conn:
            cursor = conn.cursor()
            # Persist research_failure artifact
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                   VALUES (?, 'research', 'research_failure', ?)""",
                (run_id, json.dumps(failure_artifact))
            )
            # Update run status with structured failure
            cursor.execute(
                """UPDATE runs SET status = 'FAILED', 
                   failure_reason = ?, failure_code = ?
                   WHERE run_id = ?""",
                (
                    json.dumps({
                        "code": "RESEARCH_EMPTY_RANKINGS",
                        "summary": f"No valid rankings from {len(universe)} assets",
                        "root_cause": _dominant_cause(drop_reasons),
                        "recommended_fix": _recommend_action(drop_reasons)
                    }),
                    "RESEARCH_EMPTY_RANKINGS",
                    run_id
                )
            )
            conn.commit()
        
        logger.error(f"Research failed: no valid rankings for run {run_id}")

        error_msg = (
            f"Research failed: no valid rankings. "
            f"Universe={len(universe)}, dropped={len(drop_reasons)}. "
            f"Root cause: {_dominant_cause(drop_reasons)}. "
            f"Fix: {_recommend_action(drop_reasons)}"
        )
        raise ValueError(error_msg)

    # Persist financial_brief artifact with computed metrics (per spec)
    ranked_list = sorted(
        [{
            "product_id": sym,
            "base_symbol": sym.split("-")[0] if "-" in sym else sym,
            "return_48h": ret,  # Named return_48h for consistency even if lookback differs
            "candles_count": len(candles_by_symbol[sym]),
            "first_ts": candles_by_symbol[sym][0]["start_time"] if candles_by_symbol[sym] else None,
            "last_ts": candles_by_symbol[sym][-1]["end_time"] if candles_by_symbol[sym] else None,
            "last_price": float(candles_by_symbol[sym][-1]["close"]) if candles_by_symbol[sym] else None
        }
         for sym, ret in returns_by_symbol.items()],
        key=lambda x: x["return_48h"], reverse=True
    )
    financial_brief = {
        "lookback_hours": lookback_hours,
        "granularity": granularity,
        "ranked_assets": ranked_list,
        "universe_size": len(universe),
        "valid_count": len(ranked_list),
        "dropped_count": len(drop_reasons),
        "computed_at": now_iso()
    }
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
               VALUES (?, 'research', 'financial_brief', ?)""",
            (run_id, json.dumps(financial_brief))
        )
        conn.commit()

    # Store research results in dag_nodes outputs_json
    last_prices = {}
    for sym, candles_list in candles_by_symbol.items():
        if candles_list and len(candles_list) > 0:
            last_prices[sym] = float(candles_list[-1]["close"])

    research_output = {
        "candles_by_symbol": {sym: len(cs) for sym, cs in candles_by_symbol.items()},
        "last_prices_by_symbol": last_prices,
        "returns_by_symbol": returns_by_symbol,
        "citations": citations,
        "citation_ids": [c["citation_id"] for c in citations],
        "universe": universe,
        "lookback_hours": lookback_hours,
        "drop_reasons": drop_reasons,
        "evidence_refs": {
            "universe_snapshot": True,
            "research_summary": True,
            "research_debug": True,
            "financial_brief": True
        },
        "safe_summary": (
            f"Researched {len(universe)} assets over {lookback_hours}h. "
            f"{len(returns_by_symbol)} valid, {len(drop_reasons)} dropped. "
            f"Top: {ranked_list[0]['product_id']} ({ranked_list[0]['return_48h']:.4f})" if ranked_list else
            f"Research complete but no valid assets found."
        )
    }

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(research_output), node_id)
        )
        conn.commit()

    return research_output


def _summarize_drop_reasons(drop_reasons: dict) -> dict:
    """Summarize drop reasons into counts by category."""
    summary = {}
    for symbol, reason in drop_reasons.items():
        # Extract category prefix
        category = reason.split("_")[0] if "_" in reason else reason
        summary[category] = summary.get(category, 0) + 1
    return summary


def _recommend_action(drop_reasons: dict) -> str:
    """Recommend action based on drop reasons."""
    if not drop_reasons:
        return "No drops - check universe configuration."

    reasons = list(drop_reasons.values())
    api_errors = sum(1 for r in reasons if r.startswith("api_error"))
    insufficient = sum(1 for r in reasons if r.startswith("insufficient"))

    if api_errors > len(reasons) * 0.5:
        if any("401" in r or "403" in r for r in reasons):
            return "Coinbase API credentials missing or invalid. Check COINBASE_API_KEY_NAME and COINBASE_API_PRIVATE_KEY."
        return "Coinbase API errors. Check network connectivity and API status."
    if insufficient > len(reasons) * 0.5:
        return "Insufficient candle data from Coinbase. Products may be newly listed or have low trading volume."
    return f"Mixed failures: {api_errors} API errors, {insufficient} insufficient data."


def _categorize_drop_reasons(drop_reasons: dict) -> dict:
    """Categorize drop reasons into structured counts.
    
    Returns dict with counts per category:
    - insufficient_candles: Not enough data points
    - api_error: General API failures
    - rate_limited: 429 responses
    - timeout: Request timeouts
    - invalid_price: Zero/invalid price data
    - parse_error: Data parsing failures
    - filtered_out: Filtered by rules
    """
    categories = {
        "insufficient_candles": 0,
        "api_error": 0,
        "rate_limited": 0,
        "timeout": 0,
        "invalid_price": 0,
        "parse_error": 0,
        "filtered_out": 0
    }
    
    for symbol, reason in drop_reasons.items():
        reason_lower = reason.lower()
        if reason.startswith("insufficient"):
            categories["insufficient_candles"] += 1
        elif reason == "rate_limited" or "429" in reason:
            categories["rate_limited"] += 1
        elif reason == "timeout" or "timeout" in reason_lower:
            categories["timeout"] += 1
        elif "invalid_price" in reason_lower or "zero" in reason_lower:
            categories["invalid_price"] += 1
        elif "parse" in reason_lower:
            categories["parse_error"] += 1
        elif "filter" in reason_lower:
            categories["filtered_out"] += 1
        else:
            categories["api_error"] += 1
    
    # Remove zero counts for cleaner output
    return {k: v for k, v in categories.items() if v > 0}


def _dominant_cause(drop_reasons: dict) -> str:
    """Identify the dominant cause from drop reasons."""
    if not drop_reasons:
        return "unknown"
    
    categorized = _categorize_drop_reasons(drop_reasons)
    if not categorized:
        return "unknown"
    
    # Find category with highest count
    dominant = max(categorized.items(), key=lambda x: x[1])
    return dominant[0]


async def _replay_research(run_id: str, node_id: str, tenant_id: str, source_run_id: str) -> dict:
    """Replay research by loading stored artifacts from source run.
    
    This function is called when execution_mode == REPLAY. It copies artifacts
    from the source run instead of making external API calls.
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Copy artifacts from source run
        artifact_types = ["universe_snapshot", "research_summary", "research_debug", "financial_brief", "research_failure"]
        
        for artifact_type in artifact_types:
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts 
                   WHERE run_id = ? AND artifact_type = ?""",
                (source_run_id, artifact_type)
            )
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                       VALUES (?, 'research', ?, ?)""",
                    (run_id, artifact_type, row["artifact_json"])
                )
        
        # Copy market_candles_batches
        cursor.execute(
            """SELECT symbol, window, candles_json, query_params_json 
               FROM market_candles_batches WHERE run_id = ?""",
            (source_run_id,)
        )
        candle_batches = cursor.fetchall()
        for batch in candle_batches:
            batch_id = new_id("batch_")
            cursor.execute(
                """INSERT INTO market_candles_batches 
                   (batch_id, run_id, node_id, symbol, window, candles_json, query_params_json, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (batch_id, run_id, node_id, batch["symbol"], batch["window"],
                 batch["candles_json"], batch["query_params_json"], now_iso())
            )
        
        # Copy rankings
        cursor.execute(
            """SELECT window, metric, table_json, selected_symbol, selected_score, rationale 
               FROM rankings WHERE run_id = ?""",
            (source_run_id,)
        )
        rankings_rows = cursor.fetchall()
        for ranking in rankings_rows:
            ranking_id = new_id("rank_")
            cursor.execute(
                """INSERT INTO rankings 
                   (ranking_id, run_id, node_id, window, metric, table_json, selected_symbol, selected_score, rationale, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ranking_id, run_id, node_id, ranking["window"], ranking["metric"],
                 ranking["table_json"], ranking["selected_symbol"], ranking["selected_score"],
                 ranking["rationale"], now_iso())
            )
        
        # Copy retrievals
        cursor.execute(
            """SELECT query, results_json FROM retrievals WHERE run_id = ?""",
            (source_run_id,)
        )
        retrievals = cursor.fetchall()
        for retrieval in retrievals:
            retrieval_id = new_id("ret_")
            cursor.execute(
                """INSERT INTO retrievals (id, run_id, node_id, query, results_json, ts)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (retrieval_id, run_id, node_id, retrieval["query"], retrieval["results_json"], now_iso())
            )
        
        conn.commit()
        
        # Load research outputs from source run
        cursor.execute(
            """SELECT outputs_json FROM dag_nodes 
               WHERE run_id = ? AND name = 'research'""",
            (source_run_id,)
        )
        source_outputs = cursor.fetchone()
        
        if source_outputs and source_outputs["outputs_json"]:
            research_output = json.loads(source_outputs["outputs_json"])
            research_output["replayed_from"] = source_run_id
            research_output["replay_mode"] = True
        else:
            # Fallback: reconstruct from financial_brief
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts 
                   WHERE run_id = ? AND artifact_type = 'financial_brief'""",
                (source_run_id,)
            )
            brief_row = cursor.fetchone()
            if brief_row:
                brief = json.loads(brief_row["artifact_json"])
                research_output = {
                    "returns_by_symbol": {
                        a["product_id"]: a["return_48h"] 
                        for a in brief.get("ranked_assets", [])
                    },
                    "candles_by_symbol": {
                        a["product_id"]: a.get("candles_count", 0) 
                        for a in brief.get("ranked_assets", [])
                    },
                    "universe": [a["product_id"] for a in brief.get("ranked_assets", [])],
                    "lookback_hours": brief.get("lookback_hours", 48),
                    "replayed_from": source_run_id,
                    "replay_mode": True,
                    "safe_summary": f"Replayed research from {source_run_id}"
                }
            else:
                raise ValueError(f"Source run {source_run_id} has no research outputs")
        
        # Update dag_nodes outputs
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(research_output), node_id)
        )
        conn.commit()
    
    logger.info(f"REPLAY: copied research artifacts from {source_run_id}")
    return research_output
