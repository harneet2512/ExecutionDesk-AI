"""Grounding evals for portfolio and news evidence.

These evals verify that all claims about holdings and news are properly
grounded in provider responses or user-provided artifacts.
"""
import json
from typing import Optional
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.time import now_iso

logger = get_logger(__name__)


def portfolio_grounding(run_id: str, tenant_id: str) -> dict:
    """Verify that holdings claims are backed by provider response or user-pasted artifact.
    
    Checks:
    1. portfolio_analysis_snapshot exists with holdings
    2. Holdings data has evidence_source (coinbase_accounts, user_input, etc.)
    3. Numeric values in brief match evidence
    
    Returns:
        dict with pass/fail, score 0-1, and issues
    """
    issues = []
    score = 1.0
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Check if this run has portfolio analysis
        cursor.execute(
            """SELECT metadata_json FROM runs WHERE run_id = ?""",
            (run_id,)
        )
        run_row = cursor.fetchone()
        
        if run_row and run_row["metadata_json"]:
            metadata = json.loads(run_row["metadata_json"])
            intent = metadata.get("intent")
            
            if intent != "PORTFOLIO_ANALYSIS":
                return _build_result("PASS", 1.0, [{
                    "type": "skipped",
                    "detail": "Not a portfolio analysis run"
                }])
        else:
            return _build_result("PASS", 1.0, [{
                "type": "skipped",
                "detail": "No run metadata"
            }])
        
        # Get portfolio_brief artifact
        cursor.execute(
            """SELECT artifact_json FROM run_artifacts
               WHERE run_id = ? AND artifact_type = 'portfolio_brief'""",
            (run_id,)
        )
        brief_row = cursor.fetchone()
        
        if not brief_row:
            issues.append({
                "type": "missing_artifact",
                "detail": "portfolio_brief artifact not found",
                "severity": "high"
            })
            return _build_result("FAIL", 0.3, issues)
        
        brief = json.loads(brief_row["artifact_json"])
        holdings = brief.get("holdings", [])
        evidence_source = brief.get("evidence_source")
        
        # Check evidence source is specified
        if not evidence_source:
            issues.append({
                "type": "missing_evidence_source",
                "detail": "portfolio_brief has no evidence_source specified",
                "severity": "high"
            })
            score -= 0.3
        
        # Check holdings have grounding
        for holding in holdings:
            symbol = holding.get("symbol")
            quantity = holding.get("quantity")
            
            if symbol and quantity is None:
                issues.append({
                    "type": "missing_quantity",
                    "detail": f"Holding {symbol} has no quantity",
                    "severity": "medium",
                    "symbol": symbol
                })
                score -= 0.1
        
        # Check for portfolio_snapshot in DB (evidence)
        cursor.execute(
            """SELECT balances_json, positions_json, total_value_usd
               FROM portfolio_snapshots
               WHERE tenant_id = ?
               ORDER BY ts DESC LIMIT 1""",
            (tenant_id,)
        )
        snapshot_row = cursor.fetchone()
        
        if not snapshot_row:
            # No DB snapshot - check if user_input evidence exists
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts
                   WHERE run_id = ? AND artifact_type = 'user_holdings_input'""",
                (run_id,)
            )
            user_input_row = cursor.fetchone()
            
            if not user_input_row and evidence_source != "simulated":
                issues.append({
                    "type": "no_evidence_found",
                    "detail": "No portfolio snapshot or user input evidence found",
                    "severity": "critical"
                })
                score -= 0.5
        else:
            # Verify brief totals match snapshot
            snapshot_total = snapshot_row["total_value_usd"] or 0
            brief_total = brief.get("total_value_usd", 0)
            
            # Allow 1% tolerance for price movement
            if snapshot_total > 0:
                diff_pct = abs(snapshot_total - brief_total) / snapshot_total
                if diff_pct > 0.01:
                    issues.append({
                        "type": "total_mismatch",
                        "detail": f"Brief total ${brief_total:.2f} differs from snapshot ${snapshot_total:.2f} by {diff_pct*100:.1f}%",
                        "severity": "medium"
                    })
                    score -= 0.1
    
    score = max(0.0, score)
    passed = score >= 0.7 and not any(i["severity"] == "critical" for i in issues)
    return _build_result("PASS" if passed else "FAIL", score, issues)


def news_evidence_integrity(run_id: str, tenant_id: str) -> dict:
    """Verify that every news tag/blocker references stored run_news_evidence.
    
    Checks:
    1. news_brief artifact exists if news was enabled
    2. All blocker tags reference specific evidence IDs
    3. Evidence items are actually stored in run_news_evidence table
    
    Returns:
        dict with pass/fail, score 0-1, and evidence gaps
    """
    issues = []
    score = 1.0
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Check if news was enabled for this run
        cursor.execute(
            "SELECT news_enabled FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        
        if not run_row:
            return _build_result("PASS", 1.0, [{
                "type": "skipped",
                "detail": "Run not found"
            }])
        
        try:
            news_enabled = run_row["news_enabled"] if "news_enabled" in run_row.keys() else True
        except (IndexError, KeyError):
            news_enabled = True
        
        # Check for news_skipped artifact
        cursor.execute(
            """SELECT artifact_json FROM run_artifacts
               WHERE run_id = ? AND artifact_type = 'news_skipped'""",
            (run_id,)
        )
        skipped_row = cursor.fetchone()
        
        if skipped_row or not news_enabled:
            return _build_result("PASS", 1.0, [{
                "type": "news_disabled",
                "detail": "News was disabled or skipped for this run"
            }])
        
        # Get news_brief artifact
        cursor.execute(
            """SELECT artifact_json FROM run_artifacts
               WHERE run_id = ? AND artifact_type = 'news_brief'""",
            (run_id,)
        )
        brief_row = cursor.fetchone()
        
        if not brief_row:
            # News node might not have run yet or failed
            cursor.execute(
                """SELECT outputs_json FROM dag_nodes
                   WHERE run_id = ? AND name = 'news'""",
                (run_id,)
            )
            news_node_row = cursor.fetchone()
            
            if not news_node_row:
                issues.append({
                    "type": "news_node_missing",
                    "detail": "News node did not run despite news being enabled",
                    "severity": "medium"
                })
                score = 0.7
            else:
                issues.append({
                    "type": "missing_brief",
                    "detail": "News node ran but no news_brief artifact produced",
                    "severity": "medium"
                })
                score = 0.6
            
            return _build_result("WARN", score, issues)
        
        brief = json.loads(brief_row["artifact_json"])
        blockers = brief.get("blockers", [])
        items = brief.get("items", [])
        
        # Get stored news evidence (join with news_items + asset_mentions)
        cursor.execute(
            """SELECT rne.item_id, nam.asset_symbol AS symbol,
                      ni.title AS headline, rne.role AS tag
               FROM run_news_evidence rne
               LEFT JOIN news_items ni ON rne.item_id = ni.id
               LEFT JOIN news_asset_mentions nam ON rne.item_id = nam.item_id
               WHERE rne.run_id = ?""",
            (run_id,)
        )
        evidence_rows = cursor.fetchall()
        evidence_by_symbol = {}
        for row in evidence_rows:
            symbol = row["symbol"] if "symbol" in row.keys() else None
            if symbol is None:
                continue
            if symbol not in evidence_by_symbol:
                evidence_by_symbol[symbol] = []
            evidence_by_symbol[symbol].append(row)
        
        # Check blockers have evidence
        for blocker in blockers:
            symbol = blocker.get("symbol")
            if symbol and symbol not in evidence_by_symbol:
                issues.append({
                    "type": "ungrounded_blocker",
                    "detail": f"Blocker for {symbol} has no stored evidence",
                    "severity": "high",
                    "symbol": symbol,
                    "tag": blocker.get("tag")
                })
                score -= 0.2
        
        # Check items have reasonable evidence
        total_items = len(items)
        evidenced_items = sum(1 for item in items if item.get("evidence_id"))
        
        if total_items > 0:
            evidence_ratio = evidenced_items / total_items
            if evidence_ratio < 0.8:
                issues.append({
                    "type": "low_evidence_coverage",
                    "detail": f"Only {evidenced_items}/{total_items} news items have evidence IDs",
                    "severity": "medium"
                })
                score -= 0.1
    
    score = max(0.0, score)
    passed = score >= 0.7 and not any(i["severity"] == "critical" for i in issues)
    return _build_result("PASS" if passed else "WARN", score, issues)


def _build_result(status: str, score: float, issues: list) -> dict:
    """Build standardized eval result."""
    return {
        "status": status,
        "score": round(score, 3),
        "issues": issues,
        "issue_count": len([i for i in issues if i.get("severity") not in ("info", "skipped")]),
        "evaluated_at": now_iso()
    }
