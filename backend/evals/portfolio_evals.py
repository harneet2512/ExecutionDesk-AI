"""Portfolio analysis evaluations - anti-hallucination checks for portfolio analysis.

Evaluations:
1. portfolio_evidence_coverage: PortfolioBrief evidence_refs must map to tool_calls rows
2. portfolio_numeric_grounding: totals match sum(holdings usd_value) within tolerance
3. portfolio_mode_correctness: LIVE vs PAPER mode properly determined and documented
4. portfolio_refusal_correctness: if creds missing and no paper snapshot, must fail with explicit artifact
"""
import json
from typing import Dict, Any, List
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_portfolio_evidence_coverage(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Eval: PortfolioBrief evidence_refs must map to actual tool_calls rows.
    
    Checks:
    - accounts_call_id exists in tool_calls table
    - All prices_call_ids exist in tool_calls table
    - orders_call_id exists in tool_calls table (if provided)
    
    Returns:
        {"score": 0.0-1.0, "reasons": [...], "thresholds": {...}}
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get portfolio analysis snapshot
        cursor.execute(
            """
            SELECT brief_json FROM portfolio_analysis_snapshots
            WHERE run_id = ? AND tenant_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id, tenant_id)
        )
        row = cursor.fetchone()
        
        if not row or not row["brief_json"]:
            return {
                "score": 0.5,
                "reasons": ["No portfolio analysis snapshot found for this run - may not be a portfolio analysis run"],
                "thresholds": {"min_coverage": 0.8}
            }
        
        try:
            brief = json.loads(row["brief_json"])
        except json.JSONDecodeError:
            return {
                "score": 0.0,
                "reasons": ["Failed to parse portfolio brief JSON"],
                "thresholds": {"min_coverage": 0.8}
            }
        
        evidence_refs = brief.get("evidence_refs", {})
        
        # Collect all evidence IDs
        evidence_ids = []
        if evidence_refs.get("accounts_call_id"):
            evidence_ids.append(("accounts", evidence_refs["accounts_call_id"]))
        for price_id in evidence_refs.get("prices_call_ids", []):
            evidence_ids.append(("prices", price_id))
        if evidence_refs.get("orders_call_id"):
            evidence_ids.append(("orders", evidence_refs["orders_call_id"]))
        
        if not evidence_ids:
            # Check if this was a failure case
            failure = brief.get("failure")
            if failure:
                return {
                    "score": 1.0,
                    "reasons": ["Analysis failed with explicit failure artifact - no evidence expected"],
                    "thresholds": {"min_coverage": 0.8}
                }
            return {
                "score": 0.0,
                "reasons": ["No evidence_refs found in portfolio brief"],
                "thresholds": {"min_coverage": 0.8}
            }
        
        # Verify each evidence ID exists in tool_calls
        verified = []
        missing = []
        
        for source, tool_call_id in evidence_ids:
            cursor.execute(
                "SELECT id FROM tool_calls WHERE id = ? AND run_id = ?",
                (tool_call_id, run_id)
            )
            if cursor.fetchone():
                verified.append(f"{source}:{tool_call_id}")
            else:
                missing.append(f"{source}:{tool_call_id}")
        
        # Calculate coverage score
        total = len(evidence_ids)
        found = len(verified)
        score = found / total if total > 0 else 0.0
        
        reasons = []
        if verified:
            reasons.append(f"Verified {len(verified)}/{total} evidence refs map to tool_calls")
        if missing:
            reasons.append(f"Missing in tool_calls: {missing}")
        
        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"min_coverage": 0.8}
        }


def evaluate_portfolio_numeric_grounding(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Eval: Portfolio totals match sum(holdings usd_value) within tolerance.
    
    Checks:
    - total_value_usd ≈ sum(holdings.usd_value) + cash_usd
    - allocation percentages sum to ~100%
    - No negative values in holdings
    
    Returns:
        {"score": 0.0-1.0, "reasons": [...], "thresholds": {...}}
    """
    tolerance_pct = 1.0  # 1% tolerance for rounding
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT brief_json FROM portfolio_analysis_snapshots
            WHERE run_id = ? AND tenant_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id, tenant_id)
        )
        row = cursor.fetchone()
        
        if not row or not row["brief_json"]:
            return {
                "score": 0.5,
                "reasons": ["No portfolio analysis snapshot found"],
                "thresholds": {"tolerance_pct": tolerance_pct}
            }
        
        try:
            brief = json.loads(row["brief_json"])
        except json.JSONDecodeError:
            return {
                "score": 0.0,
                "reasons": ["Failed to parse portfolio brief JSON"],
                "thresholds": {"tolerance_pct": tolerance_pct}
            }
        
        # Check for failure case
        if brief.get("failure"):
            return {
                "score": 1.0,
                "reasons": ["Analysis failed with explicit failure - numeric grounding N/A"],
                "thresholds": {"tolerance_pct": tolerance_pct}
            }
        
        reasons = []
        score = 1.0
        
        total_value = brief.get("total_value_usd", 0)
        cash_usd = brief.get("cash_usd", 0)
        holdings = brief.get("holdings", [])
        allocation = brief.get("allocation", [])
        
        # Check 1: total_value ≈ sum(holdings) + cash
        holdings_sum = sum(h.get("usd_value", 0) for h in holdings)
        expected_total = holdings_sum + cash_usd
        
        if total_value > 0:
            diff_pct = abs(total_value - expected_total) / total_value * 100
            if diff_pct > tolerance_pct:
                score -= 0.3
                reasons.append(f"Total value mismatch: ${total_value:.2f} vs expected ${expected_total:.2f} (diff: {diff_pct:.2f}%)")
            else:
                reasons.append(f"Total value grounded: ${total_value:.2f} matches sum of holdings + cash")
        
        # Check 2: allocation percentages sum to ~100%
        if allocation:
            alloc_sum = sum(a.get("pct", 0) for a in allocation)
            if abs(alloc_sum - 100) > tolerance_pct:
                score -= 0.2
                reasons.append(f"Allocation percentages sum to {alloc_sum:.1f}%, expected ~100%")
            else:
                reasons.append(f"Allocation percentages sum correctly to {alloc_sum:.1f}%")
        
        # Check 3: No negative values
        negative_holdings = [h for h in holdings if h.get("usd_value", 0) < 0 or h.get("qty", 0) < 0]
        if negative_holdings:
            score -= 0.3
            reasons.append(f"Found {len(negative_holdings)} holdings with negative values")
        
        # Check 4: Holdings USD values match qty * price
        price_mismatches = []
        for h in holdings:
            if h.get("current_price") and h.get("qty"):
                expected_usd = h["qty"] * h["current_price"]
                actual_usd = h.get("usd_value", 0)
                if expected_usd > 0 and abs(actual_usd - expected_usd) / expected_usd > 0.01:
                    price_mismatches.append(h.get("asset_symbol"))
        
        if price_mismatches:
            score -= 0.2
            reasons.append(f"USD value mismatch for: {price_mismatches[:3]}")
        else:
            reasons.append("All holding USD values match qty * price")
        
        return {
            "score": max(0.0, score),
            "reasons": reasons,
            "thresholds": {"tolerance_pct": tolerance_pct}
        }


def evaluate_portfolio_mode_correctness(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Eval: If LIVE analysis returned, ensure creds validated and LIVE endpoints used;
    otherwise marked PAPER with explanation.
    
    Checks:
    - Mode in brief matches execution context
    - If LIVE mode, accounts_call_id references coinbase_provider
    - If PAPER mode, warnings explain why
    
    Returns:
        {"score": 0.0-1.0, "reasons": [...], "thresholds": {...}}
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get run execution mode
        cursor.execute(
            "SELECT execution_mode FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        run_mode = run_row["execution_mode"] if run_row else "PAPER"
        
        # Get portfolio analysis snapshot
        cursor.execute(
            """
            SELECT brief_json, mode FROM portfolio_analysis_snapshots
            WHERE run_id = ? AND tenant_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id, tenant_id)
        )
        row = cursor.fetchone()
        
        if not row:
            return {
                "score": 0.5,
                "reasons": ["No portfolio analysis snapshot found"],
                "thresholds": {}
            }
        
        try:
            brief = json.loads(row["brief_json"])
        except json.JSONDecodeError:
            return {
                "score": 0.0,
                "reasons": ["Failed to parse portfolio brief JSON"],
                "thresholds": {}
            }
        
        reasons = []
        score = 1.0
        
        brief_mode = brief.get("mode", "UNKNOWN")
        warnings = brief.get("warnings", [])
        evidence_refs = brief.get("evidence_refs", {})
        
        # Check mode consistency
        if brief_mode == "LIVE":
            # Verify LIVE mode is legitimate
            accounts_call_id = evidence_refs.get("accounts_call_id")
            if accounts_call_id:
                cursor.execute(
                    "SELECT mcp_server, tool_name FROM tool_calls WHERE id = ?",
                    (accounts_call_id,)
                )
                call_row = cursor.fetchone()
                if call_row and "coinbase" in call_row["mcp_server"].lower():
                    reasons.append("LIVE mode correctly uses Coinbase provider")
                else:
                    score -= 0.5
                    reasons.append(f"LIVE mode but accounts fetched from: {call_row['mcp_server'] if call_row else 'unknown'}")
            else:
                score -= 0.3
                reasons.append("LIVE mode but no accounts_call_id in evidence")
                
        elif brief_mode == "PAPER":
            # Check for appropriate explanation
            has_fallback_warning = any(
                "paper" in w.lower() or "snapshot" in w.lower() or "credential" in w.lower()
                for w in warnings
            )
            if run_mode == "LIVE" and not has_fallback_warning:
                score -= 0.3
                reasons.append("PAPER mode used but no explanation for LIVE -> PAPER fallback")
            else:
                reasons.append("PAPER mode correctly documented")
        
        # Check for failure with proper mode documentation
        failure = brief.get("failure")
        if failure:
            if failure.get("error_code") in ("CREDS_MISSING", "API_ERROR"):
                reasons.append(f"Failure properly documented: {failure.get('error_code')}")
            else:
                reasons.append(f"Failure mode: {failure.get('error_code')}")
        
        return {
            "score": max(0.0, score),
            "reasons": reasons,
            "thresholds": {}
        }


def evaluate_portfolio_refusal_correctness(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Eval: If creds missing and no paper snapshot, must fail with explicit failure artifact.
    
    Checks:
    - If no data available, failure artifact is present
    - Failure artifact has error_code and error_message
    - Suggested_action provides actionable guidance
    - No hallucinated holdings when data is unavailable
    
    Returns:
        {"score": 0.0-1.0, "reasons": [...], "thresholds": {...}}
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT brief_json FROM portfolio_analysis_snapshots
            WHERE run_id = ? AND tenant_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id, tenant_id)
        )
        row = cursor.fetchone()
        
        if not row:
            return {
                "score": 0.5,
                "reasons": ["No portfolio analysis snapshot found"],
                "thresholds": {}
            }
        
        try:
            brief = json.loads(row["brief_json"])
        except json.JSONDecodeError:
            return {
                "score": 0.0,
                "reasons": ["Failed to parse portfolio brief JSON"],
                "thresholds": {}
            }
        
        reasons = []
        score = 1.0
        
        failure = brief.get("failure")
        holdings = brief.get("holdings", [])
        total_value = brief.get("total_value_usd", 0)
        
        # Check for proper failure handling
        if failure:
            # Verify failure artifact is complete
            if not failure.get("error_code"):
                score -= 0.3
                reasons.append("Failure artifact missing error_code")
            else:
                reasons.append(f"Failure has error_code: {failure['error_code']}")
            
            if not failure.get("error_message"):
                score -= 0.2
                reasons.append("Failure artifact missing error_message")
            else:
                reasons.append("Failure has error_message")
            
            if not failure.get("suggested_action"):
                score -= 0.1
                reasons.append("Failure artifact missing suggested_action")
            else:
                reasons.append("Failure has suggested_action")
            
            # Verify no hallucinated data on failure
            if holdings and any(h.get("usd_value", 0) > 0 for h in holdings):
                score -= 0.5
                reasons.append("CRITICAL: Holdings present despite failure - possible hallucination")
        else:
            # Success case - verify we have actual data
            if not holdings and total_value == 0:
                # This might be an empty portfolio, which is valid
                reasons.append("Empty portfolio (no holdings, $0 value) - valid state")
            elif holdings:
                reasons.append(f"Success with {len(holdings)} holdings - refusal check N/A")
            else:
                reasons.append("Non-failure state with data - refusal check N/A")
        
        return {
            "score": max(0.0, score),
            "reasons": reasons,
            "thresholds": {}
        }


def run_portfolio_evals(run_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """Run all portfolio evaluations and return results."""
    results = []
    
    evals = [
        ("portfolio_evidence_coverage", evaluate_portfolio_evidence_coverage),
        ("portfolio_numeric_grounding", evaluate_portfolio_numeric_grounding),
        ("portfolio_mode_correctness", evaluate_portfolio_mode_correctness),
        ("portfolio_refusal_correctness", evaluate_portfolio_refusal_correctness),
    ]
    
    for eval_name, eval_func in evals:
        try:
            result = eval_func(run_id, tenant_id)
            result["eval_name"] = eval_name
            results.append(result)
        except Exception as e:
            logger.error(f"Portfolio eval {eval_name} failed: {e}")
            results.append({
                "eval_name": eval_name,
                "score": 0.0,
                "reasons": [f"Eval failed with error: {str(e)}"],
                "thresholds": {}
            })
    
    return results
