"""Stock window honesty evaluation.

Evaluates that stock commands honestly report:
- Window requested (24h, 48h, 1w)
- Window actually used (EOD closes) 
- Data granularity (EOD, not intraday)
- Tickers universe used

Fails if:
- Response claims intraday granularity for stocks
- Window interpretation not disclosed
- Universe not shown when relevant
"""
import json
from typing import Dict, Any, List
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def stock_window_honesty(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Evaluate stock window honesty.
    
    Checks that stock-related runs honestly disclose:
    - EOD data limitations
    - Actual window used (trading days)
    - Granularity info
    
    Args:
        run_id: Run ID to evaluate
        tenant_id: Tenant ID
        
    Returns:
        Dict with score (0-1), issues list, and details
    """
    issues = []
    details = []
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get run info
        cursor.execute(
            "SELECT asset_class, intent_json FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            return {"score": 1.0, "issues": [], "details": ["Run not found"]}
        
        asset_class = row["asset_class"]
        if asset_class != "STOCK":
            return {"score": 1.0, "issues": [], "details": ["Not a stock run, skipping"]}
        
        # Get artifacts
        cursor.execute(
            """SELECT artifact_type, artifact_json FROM run_artifacts 
               WHERE run_id = ? AND artifact_type IN 
               ('universe_snapshot', 'research_summary', 'decision_table', 'trade_proposal')""",
            (run_id,)
        )
        artifacts = {row["artifact_type"]: json.loads(row["artifact_json"]) for row in cursor.fetchall()}
        
        # Check 1: Universe snapshot should exist and show granularity
        if "universe_snapshot" in artifacts:
            snapshot = artifacts["universe_snapshot"]
            
            if snapshot.get("granularity") != "EOD":
                issues.append("universe_snapshot.granularity should be 'EOD' for stocks")
            
            if not snapshot.get("symbols"):
                issues.append("universe_snapshot.symbols is empty or missing")
            
            if snapshot.get("data_source") != "polygon":
                issues.append("universe_snapshot.data_source should be 'polygon' for stocks")
            
            details.append(f"Universe symbols: {snapshot.get('symbols', [])}")
            details.append(f"Granularity: {snapshot.get('granularity', 'UNKNOWN')}")
        else:
            issues.append("universe_snapshot artifact missing for stock run")
        
        # Check 2: Decision table should include window interpretation
        if "decision_table" in artifacts:
            dt = artifacts["decision_table"]
            
            # Check for staleness_note or window info
            if not dt.get("staleness_note") and not dt.get("window_actual"):
                issues.append("decision_table missing window interpretation or staleness note")
            
            # Check candidates have granularity
            candidates = dt.get("ranked_candidates", [])
            for c in candidates:
                if c.get("granularity") not in ("EOD", "ONE_DAY"):
                    issues.append(f"Candidate {c.get('symbol')} claims non-EOD granularity: {c.get('granularity')}")
        
        # Check 3: Research summary should not claim intraday for stocks
        if "research_summary" in artifacts:
            rs = artifacts["research_summary"]
            summary_text = json.dumps(rs).lower()
            
            intraday_terms = ["minute", "hourly", "5m", "15m", "1h", "intraday"]
            for term in intraday_terms:
                if term in summary_text:
                    # Allow if explicitly saying "not intraday" or similar
                    if "no intraday" in summary_text or "not intraday" in summary_text:
                        continue
                    if "eod" in summary_text or "daily" in summary_text:
                        continue
                    issues.append(f"research_summary may claim intraday data (found '{term}')")
                    break
    
    # Calculate score
    if not issues:
        score = 1.0
    elif len(issues) == 1:
        score = 0.7
    elif len(issues) == 2:
        score = 0.5
    else:
        score = 0.3
    
    return {
        "score": score,
        "issues": issues,
        "details": details,
        "checks_performed": [
            "universe_snapshot granularity check",
            "decision_table window interpretation check",
            "research_summary intraday claim check"
        ]
    }


def evaluate_stock_window_honesty(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """Wrapper for eval node integration."""
    return stock_window_honesty(run_id, tenant_id)
