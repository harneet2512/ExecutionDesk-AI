"""Market evidence integrity evals.

These evals verify that all numeric claims in agent outputs are properly grounded
in evidence from market data providers.
"""
import json
from typing import Optional
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.time import now_iso

logger = get_logger(__name__)


def market_evidence_integrity(run_id: str, tenant_id: str) -> dict:
    """Verify that every numeric claim references evidence IDs.
    
    Checks:
    1. All decision_table entries have corresponding candle data
    2. All price claims cite market_candles or candle batch IDs
    3. No fabricated returns or prices without evidence
    
    Returns:
        dict with pass/fail, score 0-1, and list of issues
    """
    issues = []
    score = 1.0
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get decision_table artifact
        cursor.execute(
            """SELECT artifact_json FROM run_artifacts 
               WHERE run_id = ? AND artifact_type = 'decision_table'""",
            (run_id,)
        )
        decision_row = cursor.fetchone()
        
        if not decision_row:
            issues.append({
                "type": "missing_artifact",
                "detail": "decision_table artifact not found",
                "severity": "critical"
            })
            score = 0.0
            return _build_result("FAIL", score, issues)
        
        decision_table = json.loads(decision_row["artifact_json"])
        ranked_candidates = decision_table.get("ranked_candidates", [])
        
        # Get market candle batches for this run
        cursor.execute(
            """SELECT symbol, window, candles_json FROM market_candles_batches
               WHERE run_id = ?""",
            (run_id,)
        )
        candle_batches = cursor.fetchall()
        evidenced_symbols = {row["symbol"] for row in candle_batches}
        
        # Check each ranked candidate has evidence
        for candidate in ranked_candidates:
            symbol = candidate.get("symbol")
            if symbol and symbol not in evidenced_symbols:
                issues.append({
                    "type": "missing_candle_evidence",
                    "detail": f"No candle data found for ranked symbol: {symbol}",
                    "severity": "high",
                    "symbol": symbol
                })
                score -= 0.1
        
        # Check for any price claims without evidence
        cursor.execute(
            """SELECT outputs_json FROM dag_nodes
               WHERE run_id = ? AND name = 'research'""",
            (run_id,)
        )
        research_row = cursor.fetchone()
        
        if research_row and research_row["outputs_json"]:
            research_output = json.loads(research_row["outputs_json"])
            returns_by_symbol = research_output.get("returns_by_symbol", {})
            
            for symbol, ret_value in returns_by_symbol.items():
                if symbol not in evidenced_symbols:
                    issues.append({
                        "type": "ungrounded_return",
                        "detail": f"Return {ret_value:.4f} for {symbol} has no candle evidence",
                        "severity": "critical",
                        "symbol": symbol,
                        "return": ret_value
                    })
                    score -= 0.2
    
    score = max(0.0, score)
    passed = score >= 0.8 and not any(i["severity"] == "critical" for i in issues)
    
    return _build_result("PASS" if passed else "FAIL", score, issues)


def freshness_eval(run_id: str, tenant_id: str, max_stale_hours: int = 48) -> dict:
    """Verify that EOD data is not stale beyond configured threshold.
    
    For stocks using EOD data, this checks that the latest candle
    is not older than max_stale_hours (accounting for weekends/holidays).
    
    Returns:
        dict with pass/fail, score 0-1, and staleness details
    """
    issues = []
    score = 1.0
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get asset_class from run
        cursor.execute(
            "SELECT asset_class FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        asset_class = run_row["asset_class"] if run_row and "asset_class" in run_row.keys() else "CRYPTO"
        
        # Only apply freshness eval to stocks (EOD data)
        if asset_class != "STOCK":
            return _build_result("PASS", 1.0, [{"type": "skipped", "detail": "Not STOCK asset class"}])
        
        # Get universe_snapshot
        cursor.execute(
            """SELECT artifact_json FROM run_artifacts
               WHERE run_id = ? AND artifact_type = 'universe_snapshot'""",
            (run_id,)
        )
        snapshot_row = cursor.fetchone()
        
        if not snapshot_row:
            issues.append({
                "type": "missing_snapshot",
                "detail": "universe_snapshot artifact not found",
                "severity": "medium"
            })
            return _build_result("FAIL", 0.5, issues)
        
        snapshot = json.loads(snapshot_row["artifact_json"])
        provider_metadata = snapshot.get("provider_metadata", {})
        request_time = provider_metadata.get("request_time_iso")
        
        # Get latest candle timestamps
        cursor.execute(
            """SELECT symbol, candles_json FROM market_candles_batches
               WHERE run_id = ?""",
            (run_id,)
        )
        batches = cursor.fetchall()
        
        from datetime import datetime, timedelta
        stale_symbols = []
        
        for batch in batches:
            candles = json.loads(batch["candles_json"])
            if not candles:
                continue
            
            # Get the latest candle end time
            latest_candle = candles[-1]
            latest_end = latest_candle.get("end_time")
            
            if latest_end:
                try:
                    candle_dt = datetime.fromisoformat(latest_end.replace("Z", "+00:00"))
                    now_dt = datetime.utcnow().replace(tzinfo=candle_dt.tzinfo)
                    age_hours = (now_dt - candle_dt).total_seconds() / 3600
                    
                    # For stocks, allow up to 72 hours for weekend handling
                    effective_max = max_stale_hours
                    weekday = candle_dt.weekday()
                    if weekday >= 4:  # Friday or later
                        effective_max += 48  # Allow extra time for weekend
                    
                    if age_hours > effective_max:
                        stale_symbols.append({
                            "symbol": batch["symbol"],
                            "age_hours": round(age_hours, 1),
                            "latest_candle": latest_end
                        })
                except Exception as e:
                    logger.warning(f"Failed to parse candle timestamp: {e}")
        
        if stale_symbols:
            score = max(0.0, 1.0 - (len(stale_symbols) * 0.2))
            for sym in stale_symbols:
                issues.append({
                    "type": "stale_data",
                    "detail": f"{sym['symbol']} data is {sym['age_hours']}h old",
                    "severity": "medium",
                    "symbol": sym["symbol"],
                    "age_hours": sym["age_hours"]
                })
    
    passed = score >= 0.6 and len(stale_symbols) == 0
    return _build_result("PASS" if passed else "WARN", score, issues)


def rate_limit_resilience(run_id: str, tenant_id: str) -> dict:
    """Verify that partial data yields partial ranking + explicit drop reasons.
    
    Checks:
    1. research_summary artifact exists with drop reasons
    2. If symbols were dropped, drop_reasons are explicit (not generic)
    3. Rankings still produced despite drops (graceful degradation)
    
    Returns:
        dict with pass/fail, score 0-1, and resilience assessment
    """
    issues = []
    score = 1.0
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get research_summary artifact
        cursor.execute(
            """SELECT artifact_json FROM run_artifacts
               WHERE run_id = ? AND artifact_type = 'research_summary'""",
            (run_id,)
        )
        summary_row = cursor.fetchone()
        
        if not summary_row:
            issues.append({
                "type": "missing_artifact",
                "detail": "research_summary artifact not found",
                "severity": "high"
            })
            return _build_result("FAIL", 0.3, issues)
        
        summary = json.loads(summary_row["artifact_json"])
        dropped_by_reason = summary.get("dropped_by_reason", {})
        api_call_stats = summary.get("api_call_stats", {})
        ranked_assets_count = summary.get("ranked_assets_count", 0)
        attempted_assets = summary.get("attempted_assets", 0)
        
        # Check if there were rate limits
        rate_429s = api_call_stats.get("rate_429s", 0)
        timeouts = api_call_stats.get("timeouts", 0)
        
        if rate_429s > 0 or timeouts > 0:
            # Verify explicit drop reasons exist
            if dropped_by_reason.get("rate_limited", 0) != rate_429s:
                issues.append({
                    "type": "missing_drop_reason",
                    "detail": f"Got {rate_429s} 429s but drop_reasons shows {dropped_by_reason.get('rate_limited', 0)}",
                    "severity": "medium"
                })
                score -= 0.1
            
            if dropped_by_reason.get("timeout", 0) != timeouts:
                issues.append({
                    "type": "missing_drop_reason", 
                    "detail": f"Got {timeouts} timeouts but drop_reasons shows {dropped_by_reason.get('timeout', 0)}",
                    "severity": "medium"
                })
                score -= 0.1
        
        # Check for graceful degradation
        if attempted_assets > 0 and ranked_assets_count == 0:
            # Complete failure to rank - check if research_failure artifact exists
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts
                   WHERE run_id = ? AND artifact_type = 'research_failure'""",
                (run_id,)
            )
            failure_row = cursor.fetchone()
            
            if failure_row:
                failure = json.loads(failure_row["artifact_json"])
                if failure.get("root_cause_guess") and failure.get("recommended_fix"):
                    # Failure is properly documented
                    score = 0.7
                    issues.append({
                        "type": "documented_failure",
                        "detail": "Complete ranking failure but properly documented",
                        "severity": "info"
                    })
                else:
                    score = 0.3
                    issues.append({
                        "type": "undocumented_failure",
                        "detail": "Complete failure without root cause analysis",
                        "severity": "high"
                    })
            else:
                score = 0.0
                issues.append({
                    "type": "silent_failure",
                    "detail": "Complete ranking failure with no failure artifact",
                    "severity": "critical"
                })
        elif ranked_assets_count > 0 and ranked_assets_count < attempted_assets:
            # Partial success - this is acceptable
            degradation_pct = (1 - ranked_assets_count / attempted_assets) * 100
            if degradation_pct > 50:
                score -= 0.2
                issues.append({
                    "type": "high_degradation",
                    "detail": f"{degradation_pct:.0f}% of assets dropped",
                    "severity": "medium"
                })
    
    score = max(0.0, min(1.0, score))
    passed = score >= 0.7
    return _build_result("PASS" if passed else "WARN", score, issues)


def _build_result(status: str, score: float, issues: list) -> dict:
    """Build standardized eval result."""
    return {
        "status": status,
        "score": round(score, 3),
        "issues": issues,
        "issue_count": len([i for i in issues if i.get("severity") != "info"]),
        "evaluated_at": now_iso()
    }
