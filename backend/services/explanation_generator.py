"""Evidence-Locked Explanation Generator.

Generates explanations in strict JSON format where every claim is traceable to artifacts.
No free-form numbers in prose - all claims must have evidence_refs.

Output Format:
{
    "claims": [
        {
            "type": "numeric",
            "key": "return_48h",
            "asset": "BTC",
            "value": 0.0831,
            "source_artifact": "financial_brief",
            "evidence_refs": ["market_candles_batch:batch_123"]
        },
        {
            "type": "event",
            "tag": "hack",
            "asset": "SOL",
            "polarity": "neg",
            "severity": "high",
            "source_artifact": "news_brief",
            "evidence_refs": ["news_item:item_456"]
        }
    ],
    "evidence_refs": {
        "market": ["batch_123", "batch_456"],
        "news": ["item_789"],
        "policy": [],
        "risk": []
    }
}
"""
import json
from typing import Dict, List, Any, Optional
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def generate_explanation(run_id: str) -> dict:
    """Generate an evidence-locked explanation for a run.
    
    All claims are extracted from artifacts and linked to evidence.
    No LLM-generated prose - only artifact-backed claims.
    
    Args:
        run_id: The run to generate explanation for
        
    Returns:
        Evidence-locked explanation in strict JSON format
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        claims = []
        evidence_refs = {
            "market": [],
            "news": [],
            "policy": [],
            "risk": []
        }
        
        # === Extract claims from financial_brief artifact ===
        cursor.execute(
            """
            SELECT artifact_json FROM run_artifacts 
            WHERE run_id = ? AND artifact_type = 'financial_brief'
            """,
            (run_id,)
        )
        brief_row = cursor.fetchone()
        
        if brief_row:
            brief = json.loads(brief_row["artifact_json"])
            ranked_assets = brief.get("ranked_assets", [])
            
            for asset in ranked_assets[:5]:  # Top 5 only
                product_id = asset.get("product_id") or asset.get("symbol")
                base_symbol = product_id.split("-")[0] if product_id and "-" in product_id else product_id
                
                # Return claim
                return_value = asset.get("return_48h") or asset.get("return_pct")
                if return_value is not None:
                    # Get evidence ref from market_candles_batches
                    cursor.execute(
                        """
                        SELECT batch_id FROM market_candles_batches 
                        WHERE run_id = ? AND symbol = ?
                        LIMIT 1
                        """,
                        (run_id, product_id)
                    )
                    batch_row = cursor.fetchone()
                    batch_ref = f"market_candles_batch:{batch_row['batch_id']}" if batch_row else None
                    
                    claims.append({
                        "type": "numeric",
                        "key": "return_48h",
                        "asset": base_symbol,
                        "value": round(return_value, 6),
                        "source_artifact": "financial_brief",
                        "evidence_refs": [batch_ref] if batch_ref else []
                    })
                    
                    if batch_row:
                        evidence_refs["market"].append(batch_row["batch_id"])
                
                # Price claim
                last_price = asset.get("last_price")
                if last_price is not None:
                    claims.append({
                        "type": "numeric",
                        "key": "last_price",
                        "asset": base_symbol,
                        "value": float(last_price),
                        "source_artifact": "financial_brief",
                        "evidence_refs": []
                    })
        
        # === Extract claims from news_brief artifact ===
        cursor.execute(
            """
            SELECT artifact_json FROM run_artifacts 
            WHERE run_id = ? AND artifact_type = 'news_brief'
            """,
            (run_id,)
        )
        news_row = cursor.fetchone()
        
        if news_row:
            news_brief = json.loads(news_row["artifact_json"])
            
            # Extract blocker events
            blockers = news_brief.get("blockers", [])
            for blocker in blockers:
                asset = blocker.get("asset") or blocker.get("symbol")
                keyword = blocker.get("keyword") or blocker.get("type")
                news_id = blocker.get("news_id") or blocker.get("item_id")
                
                claims.append({
                    "type": "event",
                    "tag": keyword,
                    "asset": asset,
                    "polarity": "neg",
                    "severity": "high",
                    "source_artifact": "news_brief",
                    "evidence_refs": [f"news_item:{news_id}"] if news_id else []
                })
                
                if news_id:
                    evidence_refs["news"].append(news_id)
            
            # Extract sentiment claims
            sentiment_by_asset = news_brief.get("sentiment_by_asset", {})
            for asset, sentiment in sentiment_by_asset.items():
                if isinstance(sentiment, dict):
                    score = sentiment.get("score")
                    if score is not None:
                        claims.append({
                            "type": "numeric",
                            "key": "news_sentiment",
                            "asset": asset,
                            "value": score,
                            "source_artifact": "news_brief",
                            "evidence_refs": []
                        })
        
        # === Extract claims from strategy_decision artifact ===
        cursor.execute(
            """
            SELECT artifact_json FROM run_artifacts 
            WHERE run_id = ? AND artifact_type = 'strategy_decision'
            """,
            (run_id,)
        )
        strategy_row = cursor.fetchone()
        
        if strategy_row:
            strategy = json.loads(strategy_row["artifact_json"])
            
            chosen_asset = strategy.get("chosen_asset")
            chosen_score = strategy.get("score")
            
            if chosen_asset and chosen_score is not None:
                claims.append({
                    "type": "selection",
                    "key": "chosen_asset",
                    "asset": chosen_asset,
                    "value": chosen_score,
                    "source_artifact": "strategy_decision",
                    "evidence_refs": []
                })
        
        # === Extract claims from policy_events ===
        cursor.execute(
            """
            SELECT decision, reasons_json FROM policy_events 
            WHERE run_id = ? 
            ORDER BY ts DESC LIMIT 1
            """,
            (run_id,)
        )
        policy_row = cursor.fetchone()
        
        if policy_row:
            claims.append({
                "type": "policy",
                "key": "policy_decision",
                "asset": None,
                "value": policy_row["decision"],
                "source_artifact": "policy_events",
                "evidence_refs": []
            })
            evidence_refs["policy"].append(policy_row["decision"])
        
        # === Extract claims from risk assessment ===
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'risk'
            """,
            (run_id,)
        )
        risk_row = cursor.fetchone()
        
        if risk_row and risk_row["outputs_json"]:
            risk_output = json.loads(risk_row["outputs_json"])
            risk_score = risk_output.get("risk_score")
            
            if risk_score is not None:
                claims.append({
                    "type": "numeric",
                    "key": "risk_score",
                    "asset": None,
                    "value": risk_score,
                    "source_artifact": "risk_node_output",
                    "evidence_refs": []
                })
                evidence_refs["risk"].append(f"risk_score:{risk_score}")
        
        # Remove duplicate evidence refs
        for category in evidence_refs:
            evidence_refs[category] = list(set(evidence_refs[category]))
        
        return {
            "claims": claims,
            "evidence_refs": evidence_refs,
            "metadata": {
                "run_id": run_id,
                "claims_count": len(claims),
                "has_market_evidence": len(evidence_refs["market"]) > 0,
                "has_news_evidence": len(evidence_refs["news"]) > 0
            }
        }


def validate_explanation(explanation: dict) -> dict:
    """Validate an explanation for completeness.
    
    Args:
        explanation: The explanation to validate
        
    Returns:
        Validation result with pass/fail and reasons
    """
    issues = []
    
    claims = explanation.get("claims", [])
    evidence_refs = explanation.get("evidence_refs", {})
    
    # Check that all numeric claims have evidence refs
    for claim in claims:
        if claim["type"] == "numeric":
            if not claim.get("evidence_refs"):
                issues.append(f"Numeric claim '{claim['key']}' for {claim.get('asset')} has no evidence_refs")
    
    # Check that evidence_refs are not empty if claims exist
    if claims:
        total_refs = sum(len(refs) for refs in evidence_refs.values())
        if total_refs == 0:
            issues.append("Claims exist but no evidence references provided")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "claims_count": len(claims),
        "evidence_refs_count": sum(len(refs) for refs in evidence_refs.values())
    }


def generate_templated_prose(explanation: dict) -> str:
    """Generate templated prose from an explanation.
    
    Creates human-readable text from structured claims.
    All numbers come from claims, not free-form generation.
    
    Args:
        explanation: The evidence-locked explanation
        
    Returns:
        Templated prose string
    """
    claims = explanation.get("claims", [])
    
    if not claims:
        return "No analysis available - insufficient evidence."
    
    lines = []
    
    # Group claims by type
    return_claims = [c for c in claims if c["key"] == "return_48h"]
    price_claims = [c for c in claims if c["key"] == "last_price"]
    selection_claims = [c for c in claims if c["type"] == "selection"]
    event_claims = [c for c in claims if c["type"] == "event"]
    
    # Return summary
    if return_claims:
        top_returns = sorted(return_claims, key=lambda x: x["value"], reverse=True)[:3]
        lines.append("Top performers (48h return):")
        for claim in top_returns:
            lines.append(f"  - {claim['asset']}: {claim['value']:.2%}")
    
    # Selection
    if selection_claims:
        for claim in selection_claims:
            lines.append(f"Selected: {claim['asset']} (score: {claim['value']:.4f})")
    
    # Events/blockers
    if event_claims:
        lines.append("Risk events detected:")
        for claim in event_claims:
            lines.append(f"  - {claim['asset']}: {claim['tag']} ({claim['severity']} severity)")
    
    return "\n".join(lines)
