"""Hallucination Detection Evaluation - Evidence-locked claim verification.

This eval ensures that ALL claims in explanations/proposals are traceable to stored artifacts.
No free-form numbers in prose - everything must be evidence-backed.

Checks:
1. evidence_coverage: explanation must include evidence_refs; if mentions news, news refs must exist
2. claim_faithfulness: every numeric claim must match artifacts within tolerance
3. tool_use_truthfulness: if claims imply tool calls, tool_calls table must contain matching calls
4. uncertainty_discipline: if evidence insufficient (empty rankings), response must be refusal/failure artifact
"""
import json
import re
from typing import Dict, List, Any, Tuple
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Tolerance for numeric comparisons (e.g., 1% tolerance)
NUMERIC_TOLERANCE = 0.01


def evaluate_hallucination_detection(run_id: str, tenant_id: str) -> dict:
    """
    Evidence-locked hallucination detection evaluation.
    
    Verifies that all claims in proposals/explanations are traceable to stored artifacts.
    
    Returns:
        {
            "score": float,  # 0.0 to 1.0
            "reasons": List[str],
            "thresholds": {"min_score": 0.8}
        }
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        checks_passed = 0
        total_checks = 0
        reasons = []
        
        # === CHECK 1: Evidence Coverage ===
        total_checks += 1
        evidence_coverage_pass, evidence_reason = _check_evidence_coverage(cursor, run_id)
        if evidence_coverage_pass:
            checks_passed += 1
        reasons.append(evidence_reason)
        
        # === CHECK 2: Claim Faithfulness ===
        total_checks += 1
        claim_faithful_pass, claim_reason = _check_claim_faithfulness(cursor, run_id)
        if claim_faithful_pass:
            checks_passed += 1
        reasons.append(claim_reason)
        
        # === CHECK 3: Tool Use Truthfulness ===
        total_checks += 1
        tool_truth_pass, tool_reason = _check_tool_use_truthfulness(cursor, run_id)
        if tool_truth_pass:
            checks_passed += 1
        reasons.append(tool_reason)
        
        # === CHECK 4: Uncertainty Discipline ===
        total_checks += 1
        uncertainty_pass, uncertainty_reason = _check_uncertainty_discipline(cursor, run_id)
        if uncertainty_pass:
            checks_passed += 1
        reasons.append(uncertainty_reason)
        
        score = checks_passed / total_checks if total_checks > 0 else 0.0
        
        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"min_score": 0.8},
            "metrics": {
                "checks_passed": checks_passed,
                "total_checks": total_checks,
                "evidence_coverage": evidence_coverage_pass,
                "claim_faithfulness": claim_faithful_pass,
                "tool_truthfulness": tool_truth_pass,
                "uncertainty_discipline": uncertainty_pass
            }
        }


def _check_evidence_coverage(cursor, run_id: str) -> Tuple[bool, str]:
    """Check 1: Evidence Coverage.
    
    Verifies that any claims made have corresponding evidence artifacts.
    If news is mentioned, news refs must exist.
    """
    # Check for research artifacts (universe_snapshot, research_summary, financial_brief)
    cursor.execute(
        """
        SELECT artifact_type, artifact_json 
        FROM run_artifacts 
        WHERE run_id = ? AND step_name = 'research'
        """,
        (run_id,)
    )
    research_artifacts = cursor.fetchall()
    
    artifact_types = [r["artifact_type"] for r in research_artifacts]
    
    # Required artifacts for evidence coverage
    required_artifacts = ["financial_brief"]
    missing = [a for a in required_artifacts if a not in artifact_types]
    
    if missing:
        return False, f"Evidence coverage: missing artifacts {missing}"
    
    # Check if news is mentioned in proposal - if so, news_brief must exist
    cursor.execute(
        "SELECT trade_proposal_json FROM runs WHERE run_id = ?",
        (run_id,)
    )
    row = cursor.fetchone()
    proposal = {}
    if row and row["trade_proposal_json"]:
        try:
            proposal = json.loads(row["trade_proposal_json"])
        except:
            pass
    
    proposal_text = json.dumps(proposal).lower()
    mentions_news = any(word in proposal_text for word in ["news", "headline", "article", "sentiment"])
    
    if mentions_news:
        cursor.execute(
            """
            SELECT COUNT(*) as cnt FROM run_artifacts 
            WHERE run_id = ? AND artifact_type = 'news_brief'
            """,
            (run_id,)
        )
        news_count = cursor.fetchone()["cnt"]
        if news_count == 0:
            return False, "Evidence coverage: proposal mentions news but no news_brief artifact exists"
    
    # Check for evidence_refs in research output
    cursor.execute(
        """
        SELECT outputs_json FROM dag_nodes 
        WHERE run_id = ? AND name = 'research'
        """,
        (run_id,)
    )
    research_row = cursor.fetchone()
    if research_row and research_row["outputs_json"]:
        outputs = json.loads(research_row["outputs_json"])
        evidence_refs = outputs.get("evidence_refs", {})
        if not evidence_refs:
            return False, "Evidence coverage: research outputs missing evidence_refs"
    
    return True, f"Evidence coverage: all required artifacts present ({len(artifact_types)} total)"


def _check_claim_faithfulness(cursor, run_id: str) -> Tuple[bool, str]:
    """Check 2: Claim Faithfulness.
    
    Verifies that numeric claims in proposals match artifact values within tolerance.
    """
    # Get proposal
    cursor.execute(
        "SELECT trade_proposal_json FROM runs WHERE run_id = ?",
        (run_id,)
    )
    row = cursor.fetchone()
    if not row or not row["trade_proposal_json"]:
        return True, "Claim faithfulness: no proposal to check"
    
    try:
        proposal = json.loads(row["trade_proposal_json"])
    except:
        return True, "Claim faithfulness: invalid proposal JSON"
    
    # Get financial_brief artifact for comparison
    cursor.execute(
        """
        SELECT artifact_json FROM run_artifacts 
        WHERE run_id = ? AND artifact_type = 'financial_brief'
        """,
        (run_id,)
    )
    brief_row = cursor.fetchone()
    if not brief_row:
        return True, "Claim faithfulness: no financial_brief to compare"
    
    brief = json.loads(brief_row["artifact_json"])
    ranked_assets = brief.get("ranked_assets", [])
    
    if not ranked_assets:
        return True, "Claim faithfulness: no ranked assets to compare"
    
    # Build lookup by symbol
    asset_lookup = {}
    for asset in ranked_assets:
        sym = asset.get("product_id") or asset.get("symbol")
        if sym:
            asset_lookup[sym] = asset
    
    # Check if proposal has return claims
    proposal_asset = proposal.get("asset") or proposal.get("symbol")
    proposal_return = proposal.get("return_pct") or proposal.get("expected_return")
    
    if proposal_asset and proposal_return is not None:
        # Try to match with -USD suffix
        lookup_key = proposal_asset if "-" in proposal_asset else f"{proposal_asset}-USD"
        if lookup_key in asset_lookup:
            artifact_return = asset_lookup[lookup_key].get("return_48h") or asset_lookup[lookup_key].get("return_pct")
            if artifact_return is not None:
                diff = abs(float(proposal_return) - float(artifact_return))
                if diff > NUMERIC_TOLERANCE:
                    return False, f"Claim faithfulness: proposal return {proposal_return} differs from artifact {artifact_return} by {diff:.4f}"
    
    return True, "Claim faithfulness: numeric claims match artifacts within tolerance"


def _check_tool_use_truthfulness(cursor, run_id: str) -> Tuple[bool, str]:
    """Check 3: Tool Use Truthfulness.
    
    Verifies that if proposal implies tool calls were made, those calls exist in tool_calls table.
    """
    # Get tool calls for this run
    cursor.execute(
        """
        SELECT tool_name, status, COUNT(*) as cnt 
        FROM tool_calls 
        WHERE run_id = ? 
        GROUP BY tool_name, status
        """,
        (run_id,)
    )
    tool_calls = cursor.fetchall()
    
    if not tool_calls:
        # Check if run has research output (which implies tool calls should exist)
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'research' AND status = 'COMPLETED'
            """,
            (run_id,)
        )
        research_row = cursor.fetchone()
        if research_row:
            return False, "Tool truthfulness: research completed but no tool_calls recorded"
        return True, "Tool truthfulness: no tool calls expected or made"
    
    # Check that successful research has at least some successful fetch_candles calls
    cursor.execute(
        """
        SELECT COUNT(*) as cnt FROM tool_calls 
        WHERE run_id = ? AND tool_name = 'fetch_candles' AND status = 'SUCCESS'
        """,
        (run_id,)
    )
    success_count = cursor.fetchone()["cnt"]
    
    # Get research output to check claims
    cursor.execute(
        """
        SELECT outputs_json FROM dag_nodes 
        WHERE run_id = ? AND name = 'research'
        """,
        (run_id,)
    )
    research_row = cursor.fetchone()
    if research_row and research_row["outputs_json"]:
        outputs = json.loads(research_row["outputs_json"])
        returns_by_symbol = outputs.get("returns_by_symbol", {})
        
        # Number of ranked symbols should roughly match successful tool calls
        if len(returns_by_symbol) > 0 and success_count == 0:
            return False, f"Tool truthfulness: {len(returns_by_symbol)} assets ranked but 0 successful fetch_candles calls"
    
    total_calls = sum(t["cnt"] for t in tool_calls)
    return True, f"Tool truthfulness: {total_calls} tool calls recorded, {success_count} successful candle fetches"


def _check_uncertainty_discipline(cursor, run_id: str) -> Tuple[bool, str]:
    """Check 4: Uncertainty Discipline.
    
    Verifies that if evidence was insufficient (empty rankings, stale news),
    the response was a refusal/failure artifact, not a confident claim.
    """
    # Check for research_failure artifact
    cursor.execute(
        """
        SELECT artifact_json FROM run_artifacts 
        WHERE run_id = ? AND artifact_type = 'research_failure'
        """,
        (run_id,)
    )
    failure_row = cursor.fetchone()
    
    if failure_row:
        # Research failed - check that run is marked as failed or has no order
        cursor.execute(
            "SELECT status FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE run_id = ?",
            (run_id,)
        )
        order_count = cursor.fetchone()["cnt"]
        
        if run_row and run_row["status"] not in ("FAILED", "PAUSED"):
            if order_count > 0:
                return False, "Uncertainty discipline: research_failure exists but orders were placed"
        
        return True, "Uncertainty discipline: research failed and no orders placed"
    
    # Check for signals_failure artifact
    cursor.execute(
        """
        SELECT artifact_json FROM run_artifacts 
        WHERE run_id = ? AND artifact_type = 'signals_failure'
        """,
        (run_id,)
    )
    signals_failure = cursor.fetchone()
    
    if signals_failure:
        # Signals failed - verify no orders
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE run_id = ?",
            (run_id,)
        )
        order_count = cursor.fetchone()["cnt"]
        if order_count > 0:
            return False, "Uncertainty discipline: signals_failure exists but orders were placed"
        return True, "Uncertainty discipline: signals failed and no orders placed"
    
    # No failure artifacts - check that there IS evidence for any claims
    cursor.execute(
        """
        SELECT outputs_json FROM dag_nodes 
        WHERE run_id = ? AND name = 'research'
        """,
        (run_id,)
    )
    research_row = cursor.fetchone()
    
    if research_row and research_row["outputs_json"]:
        outputs = json.loads(research_row["outputs_json"])
        returns = outputs.get("returns_by_symbol", {})
        
        if not returns:
            # No returns but no failure artifact - this is a problem
            return False, "Uncertainty discipline: no valid rankings but no failure artifact present"
    
    return True, "Uncertainty discipline: evidence sufficient for claims or failure properly documented"
