"""RAGAS-style evaluation metrics for agentic trade pipeline.

Implements three enterprise-grade RAG evaluation metrics:
1. Faithfulness - are claims grounded in evidence?
2. Answer Relevance - does the response match the user's intent?
3. Retrieval Relevance - is retrieved evidence related to the query?

Each evaluator returns: {"score": float, "reasons": list[str], "thresholds": dict, "details": dict}
"""
import json
import os
import re
from typing import Dict, List, Any, Optional

from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def _safe_json_loads(s, default=None):
    if not s:
        return default if default is not None else {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def _extract_numeric_claims(text: str) -> List[str]:
    """Extract sentences containing numbers from text (likely factual claims)."""
    if not text:
        return []
    sentences = re.split(r'[.!?\n]', text)
    claims = []
    for s in sentences:
        s = s.strip()
        if s and re.search(r'\d+\.?\d*', s):
            claims.append(s)
    return claims[:10]  # Cap at 10 claims


def _text_overlap_score(claim: str, evidence_text: str) -> float:
    """Simple keyword overlap between claim and evidence."""
    if not claim or not evidence_text:
        return 0.0
    claim_tokens = set(re.findall(r'\w+', claim.lower()))
    evidence_tokens = set(re.findall(r'\w+', evidence_text.lower()))
    if not claim_tokens:
        return 0.0
    overlap = claim_tokens & evidence_tokens
    # Remove common stop words from overlap
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "for", "and", "or", "at"}
    meaningful_overlap = overlap - stop_words
    meaningful_claim = claim_tokens - stop_words
    if not meaningful_claim:
        return 1.0  # All stop words = trivially grounded
    return len(meaningful_overlap) / len(meaningful_claim)


def evaluate_faithfulness(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """RAGAS Faithfulness Proxy: are factual claims grounded in evidence?

    Extracts numeric/factual claims from trade proposal and insight,
    then checks each against evidence artifacts (candles, rankings, tool calls).
    """
    reasons = []
    details = {"claims_checked": 0, "claims_grounded": 0, "claim_scores": []}

    try:
        with get_conn() as conn:
            cursor = conn.cursor()

            # Get trade proposal and insight text
            cursor.execute(
                "SELECT trade_proposal_json, parsed_intent_json FROM runs WHERE run_id = ?",
                (run_id,)
            )
            run_row = cursor.fetchone()
            proposal = _safe_json_loads(run_row["trade_proposal_json"]) if run_row else {}
            intent = _safe_json_loads(
                run_row["parsed_intent_json"] if run_row and "parsed_intent_json" in run_row.keys() else None
            )

            # Get insight from trade_confirmations if available
            cursor.execute(
                "SELECT insight_json FROM trade_confirmations WHERE run_id = ? LIMIT 1",
                (run_id,)
            )
            conf_row = cursor.fetchone()
            insight = _safe_json_loads(conf_row["insight_json"]) if conf_row else {}

            # Collect all text to check for claims
            claim_sources = []
            if proposal.get("citations"):
                for c in proposal["citations"]:
                    claim_sources.append(str(c))
            if insight.get("why_it_matters"):
                claim_sources.append(insight["why_it_matters"])
            if insight.get("headline"):
                claim_sources.append(insight["headline"])
            for fact in insight.get("key_facts", []):
                claim_sources.append(str(fact))

            all_text = " ".join(claim_sources)
            claims = _extract_numeric_claims(all_text)

            if not claims:
                reasons.append("No numeric/factual claims found in response")
                return {"score": 1.0, "reasons": reasons, "thresholds": {"min_score": 0.7}, "details": details}

            # Gather evidence text
            evidence_parts = []

            # Evidence from rankings
            cursor.execute(
                "SELECT table_json FROM rankings WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
                (run_id,)
            )
            ranking_row = cursor.fetchone()
            if ranking_row:
                evidence_parts.append(str(ranking_row["table_json"])[:2000])

            # Evidence from run_artifacts (candles, financial_brief, news_brief)
            cursor.execute(
                "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type IN ('financial_brief', 'news_brief', 'candle_batch')",
                (run_id,)
            )
            for art_row in cursor.fetchall():
                evidence_parts.append(str(art_row["artifact_json"])[:1000])

            # Evidence from tool_calls
            cursor.execute(
                "SELECT response_json FROM tool_calls WHERE run_id = ? AND status = 'SUCCESS' LIMIT 5",
                (run_id,)
            )
            for tc_row in cursor.fetchall():
                evidence_parts.append(str(tc_row["response_json"])[:1000])

            evidence_text = " ".join(evidence_parts)

            # Score each claim
            grounded = 0
            for claim in claims:
                score = _text_overlap_score(claim, evidence_text)
                details["claim_scores"].append({"claim": claim[:100], "score": round(score, 2)})
                if score >= 0.3:  # Threshold: 30% keyword overlap = grounded
                    grounded += 1

            details["claims_checked"] = len(claims)
            details["claims_grounded"] = grounded

            if len(claims) > 0:
                faithfulness_score = grounded / len(claims)
            else:
                faithfulness_score = 1.0

            if faithfulness_score >= 0.8:
                reasons.append(f"{grounded}/{len(claims)} claims grounded in evidence (strong)")
            elif faithfulness_score >= 0.5:
                reasons.append(f"{grounded}/{len(claims)} claims grounded in evidence (moderate)")
            else:
                reasons.append(f"{grounded}/{len(claims)} claims grounded in evidence (weak)")

            return {
                "score": round(faithfulness_score, 3),
                "reasons": reasons,
                "thresholds": {"min_score": 0.7},
                "details": details,
            }

    except Exception as e:
        logger.warning("Faithfulness eval failed for %s: %s", run_id, str(e)[:200])
        return {"score": 0.5, "reasons": [f"Eval error: {str(e)[:100]}"], "thresholds": {"min_score": 0.7}, "details": details}


def evaluate_answer_relevance(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """RAGAS Answer Relevance Proxy: does the response match the user intent?

    Checks alignment between user command/intent and the system's trade proposal,
    measuring intent match (side/asset/amount), response specificity, and completeness.
    """
    reasons = []
    details = {"intent_match": 0.0, "specificity": 0.0, "completeness": 0.0}

    try:
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT command_text, parsed_intent_json, trade_proposal_json, execution_plan_json FROM runs WHERE run_id = ?",
                (run_id,)
            )
            run_row = cursor.fetchone()
            if not run_row:
                return {"score": 0.0, "reasons": ["Run not found"], "thresholds": {"min_score": 0.6}, "details": details}

            command = run_row["command_text"] or ""
            intent = _safe_json_loads(run_row["parsed_intent_json"])
            proposal = _safe_json_loads(run_row["trade_proposal_json"])
            plan = _safe_json_loads(run_row["execution_plan_json"])

            # 1. Intent Match (0.4 weight): side, asset, amount alignment
            intent_score = 0.0
            intent_side = intent.get("side", "").upper()
            intent_budget = intent.get("budget_usd", 0)
            intent_universe = intent.get("universe", [])

            # Check if proposal matches intent
            proposal_orders = proposal.get("orders", [])
            if proposal_orders:
                order = proposal_orders[0]
                order_side = order.get("side", "").upper()
                order_notional = order.get("notional_usd", 0)
                order_symbol = order.get("symbol", "")

                if order_side == intent_side:
                    intent_score += 0.4
                if intent_budget > 0 and abs(order_notional - intent_budget) / max(intent_budget, 0.01) < 0.1:
                    intent_score += 0.3
                if order_symbol in intent_universe or any(order_symbol.startswith(u.replace("-USD", "")) for u in intent_universe):
                    intent_score += 0.3
            elif plan.get("selected_asset"):
                # No proposal yet but plan has selected asset
                intent_score += 0.3
                if plan["selected_asset"] in intent_universe:
                    intent_score += 0.3
            else:
                # No proposal or plan
                intent_score = 0.0

            details["intent_match"] = round(intent_score, 2)

            # 2. Specificity (0.3 weight): does response mention specific data?
            specificity_score = 0.0

            # Check insight
            cursor.execute(
                "SELECT insight_json FROM trade_confirmations WHERE run_id = ? LIMIT 1",
                (run_id,)
            )
            conf_row = cursor.fetchone()
            insight = _safe_json_loads(conf_row["insight_json"]) if conf_row else {}

            insight_text = insight.get("why_it_matters", "") + " " + insight.get("headline", "")
            # Check for specific numbers in insight
            if re.search(r'\$\d+', insight_text):
                specificity_score += 0.3
            if re.search(r'\d+\.?\d*%', insight_text):
                specificity_score += 0.4
            # Check for asset name
            for u in intent_universe:
                asset_name = u.replace("-USD", "")
                if asset_name in insight_text:
                    specificity_score += 0.3
                    break

            details["specificity"] = round(min(1.0, specificity_score), 2)

            # 3. Completeness (0.3 weight): has insight, evidence, risk flags
            completeness_score = 0.0
            if insight.get("headline"):
                completeness_score += 0.25
            if insight.get("why_it_matters"):
                completeness_score += 0.25
            if insight.get("key_facts") and len(insight["key_facts"]) > 0:
                completeness_score += 0.25
            if insight.get("risk_flags") is not None:
                completeness_score += 0.25

            details["completeness"] = round(completeness_score, 2)

            # Weighted total
            total = (details["intent_match"] * 0.4 +
                     details["specificity"] * 0.3 +
                     details["completeness"] * 0.3)

            if total >= 0.7:
                reasons.append("Response strongly matches user intent")
            elif total >= 0.4:
                reasons.append("Response partially matches user intent")
            else:
                reasons.append("Response weakly matches user intent")

            reasons.append(f"Intent match: {details['intent_match']:.0%}, Specificity: {details['specificity']:.0%}, Completeness: {details['completeness']:.0%}")

            return {
                "score": round(total, 3),
                "reasons": reasons,
                "thresholds": {"min_score": 0.6},
                "details": details,
            }

    except Exception as e:
        logger.warning("Answer relevance eval failed for %s: %s", run_id, str(e)[:200])
        return {"score": 0.5, "reasons": [f"Eval error: {str(e)[:100]}"], "thresholds": {"min_score": 0.6}, "details": details}


def evaluate_retrieval_relevance(run_id: str, tenant_id: str) -> Dict[str, Any]:
    """RAGAS Retrieval Relevance: is retrieved evidence related to the traded asset?

    Examines evidence items (candles, news, rankings) and checks:
    - Symbol match with traded asset
    - Evidence freshness (penalizes stale data)
    - News relevance (headline-to-asset alignment)
    """
    reasons = []
    details = {"total_evidence": 0, "relevant_evidence": 0, "freshness_penalty": 0.0, "items": []}

    try:
        with get_conn() as conn:
            cursor = conn.cursor()

            # Get traded asset from intent
            cursor.execute(
                "SELECT parsed_intent_json FROM runs WHERE run_id = ?",
                (run_id,)
            )
            run_row = cursor.fetchone()
            intent = _safe_json_loads(run_row["parsed_intent_json"]) if run_row else {}
            universe = intent.get("universe", [])
            asset_symbols = [u.replace("-USD", "").upper() for u in universe]

            if not asset_symbols:
                return {"score": 0.5, "reasons": ["No target asset to check relevance against"], "thresholds": {"min_score": 0.6}, "details": details}

            total_items = 0
            relevant_items = 0

            # Check run_artifacts
            cursor.execute(
                "SELECT artifact_type, artifact_json FROM run_artifacts WHERE run_id = ?",
                (run_id,)
            )
            for art_row in cursor.fetchall():
                total_items += 1
                art_text = str(art_row["artifact_json"])[:2000].upper()
                is_relevant = any(sym in art_text for sym in asset_symbols)
                details["items"].append({
                    "type": art_row["artifact_type"],
                    "relevant": is_relevant,
                })
                if is_relevant:
                    relevant_items += 1

            # Check tool_calls
            cursor.execute(
                "SELECT tool_name, request_json, response_json FROM tool_calls WHERE run_id = ? LIMIT 10",
                (run_id,)
            )
            for tc_row in cursor.fetchall():
                total_items += 1
                req_text = str(tc_row["request_json"])[:500].upper()
                resp_text = str(tc_row["response_json"])[:1000].upper() if tc_row["response_json"] else ""
                is_relevant = any(sym in req_text or sym in resp_text for sym in asset_symbols)
                details["items"].append({
                    "type": f"tool:{tc_row['tool_name']}",
                    "relevant": is_relevant,
                })
                if is_relevant:
                    relevant_items += 1

            # Check news evidence
            cursor.execute(
                "SELECT item_id FROM run_news_evidence WHERE run_id = ?",
                (run_id,)
            )
            news_evidence_rows = cursor.fetchall()
            for ne_row in news_evidence_rows:
                total_items += 1
                cursor.execute(
                    "SELECT title FROM news_items WHERE id = ?",
                    (ne_row["item_id"],)
                )
                ni_row = cursor.fetchone()
                if ni_row:
                    title_upper = ni_row["title"].upper()
                    is_relevant = any(sym in title_upper for sym in asset_symbols)
                    # Also check common names
                    name_map = {"BTC": "BITCOIN", "ETH": "ETHEREUM", "SOL": "SOLANA"}
                    if not is_relevant:
                        is_relevant = any(name_map.get(sym, "") in title_upper for sym in asset_symbols)
                    details["items"].append({"type": "news", "relevant": is_relevant, "title": ni_row["title"][:60]})
                    if is_relevant:
                        relevant_items += 1

            details["total_evidence"] = total_items
            details["relevant_evidence"] = relevant_items

            if total_items == 0:
                reasons.append("No evidence items found for this run")
                return {"score": 0.5, "reasons": reasons, "thresholds": {"min_score": 0.6}, "details": details}

            relevance_score = relevant_items / total_items

            # Freshness penalty: check if candle data is stale
            cursor.execute(
                "SELECT MAX(ts) as latest_ts FROM market_candles WHERE symbol IN (%s)" % ",".join("?" * len(asset_symbols)),
                asset_symbols
            )
            candle_ts_row = cursor.fetchone()
            if candle_ts_row and candle_ts_row["latest_ts"]:
                from datetime import datetime, timedelta
                try:
                    latest = datetime.fromisoformat(candle_ts_row["latest_ts"].replace("Z", "+00:00"))
                    age_hours = (datetime.now(latest.tzinfo) - latest).total_seconds() / 3600
                    if age_hours > 48:
                        penalty = min(0.2, (age_hours - 48) / 240)  # Max 0.2 penalty
                        details["freshness_penalty"] = round(penalty, 3)
                        relevance_score = max(0.0, relevance_score - penalty)
                        reasons.append(f"Stale data penalty: candles are {age_hours:.0f}h old")
                except Exception:
                    pass

            if relevance_score >= 0.7:
                reasons.append(f"{relevant_items}/{total_items} evidence items relevant to {', '.join(asset_symbols)}")
            else:
                reasons.append(f"Low relevance: {relevant_items}/{total_items} items match {', '.join(asset_symbols)}")

            return {
                "score": round(min(1.0, relevance_score), 3),
                "reasons": reasons,
                "thresholds": {"min_score": 0.6},
                "details": details,
            }

    except Exception as e:
        logger.warning("Retrieval relevance eval failed for %s: %s", run_id, str(e)[:200])
        return {"score": 0.5, "reasons": [f"Eval error: {str(e)[:100]}"], "thresholds": {"min_score": 0.6}, "details": details}
