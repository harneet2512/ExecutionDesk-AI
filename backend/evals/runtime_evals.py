"""Runtime evaluation emitter — runs lightweight evals during trade execution.

Emits eval_results entries for:
- retrieval_relevance + context_precision/recall after retrieval
- groundedness / faithfulness after insight generation
- news_coverage when news ON but headlines empty
"""
import json
import uuid
from typing import Optional, Dict, Any, List

from backend.db.repo.evals_repo import EvalsRepo
from backend.core.logging import get_logger

logger = get_logger(__name__)

_repo = EvalsRepo()


def _make_eval(
    run_id: str,
    tenant_id: str,
    eval_name: str,
    score: float,
    reasons: List[str],
    step_name: str,
    category: str = "rag",
    rationale: str = "",
    conversation_id: Optional[str] = None,
    inputs_json: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "eval_id": f"ev_{uuid.uuid4().hex[:16]}",
        "run_id": run_id,
        "tenant_id": tenant_id,
        "eval_name": eval_name,
        "score": max(0.0, min(1.0, score)),
        "reasons_json": json.dumps(reasons),
        "step_name": step_name,
        "eval_category": category,
        "rationale": rationale,
        "conversation_id": conversation_id,
        "inputs_json": inputs_json,
        "evaluator_type": "heuristic",
    }


def emit_retrieval_evals(
    run_id: str,
    tenant_id: str,
    query: str,
    returned_chunks: int,
    avg_similarity: float,
    conversation_id: Optional[str] = None,
) -> List[str]:
    """Emit retrieval_relevance + context_precision/recall after retrieval step."""
    evals = []

    # Retrieval relevance based on similarity score
    rel_score = min(avg_similarity, 1.0) if avg_similarity > 0 else 0.0
    reasons = []
    if returned_chunks == 0:
        rel_score = 0.0
        reasons.append("No chunks returned from retrieval")
    elif avg_similarity < 0.3:
        reasons.append(f"Low avg similarity ({avg_similarity:.3f}) — chunks may not be relevant")
    elif avg_similarity >= 0.7:
        reasons.append(f"Good avg similarity ({avg_similarity:.3f})")
    else:
        reasons.append(f"Moderate avg similarity ({avg_similarity:.3f})")

    evals.append(_make_eval(
        run_id=run_id, tenant_id=tenant_id,
        eval_name="retrieval_relevance",
        score=rel_score,
        reasons=reasons,
        step_name="retrieval",
        category="rag",
        rationale=f"Based on {returned_chunks} chunks with avg_similarity={avg_similarity:.3f}",
        conversation_id=conversation_id,
    ))

    # Context precision (heuristic: chunks > 0 and similarity > threshold)
    precision_score = min(1.0, avg_similarity * 1.2) if returned_chunks > 0 else 0.0
    evals.append(_make_eval(
        run_id=run_id, tenant_id=tenant_id,
        eval_name="context_precision",
        score=precision_score,
        reasons=[f"{returned_chunks} chunks returned, precision heuristic based on similarity"],
        step_name="retrieval",
        category="rag",
        conversation_id=conversation_id,
    ))

    # Context recall (heuristic: enough chunks returned)
    recall_score = min(1.0, returned_chunks / 5.0) if returned_chunks > 0 else 0.0
    evals.append(_make_eval(
        run_id=run_id, tenant_id=tenant_id,
        eval_name="context_recall",
        score=recall_score,
        reasons=[f"{returned_chunks} chunks of expected 5 returned"],
        step_name="retrieval",
        category="rag",
        conversation_id=conversation_id,
    ))

    try:
        return _repo.create_eval_batch(evals)
    except Exception as e:
        logger.warning("Failed to emit retrieval evals: %s", e)
        return []


def emit_insight_evals(
    run_id: str,
    tenant_id: str,
    insight: Dict[str, Any],
    fact_pack: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
) -> List[str]:
    """Emit groundedness/faithfulness evals after insight generation."""
    evals = []
    generated_by = insight.get("generated_by", "template")
    confidence = insight.get("confidence", 0)
    key_facts = insight.get("key_facts", [])
    risk_flags = insight.get("risk_flags", [])
    headline = insight.get("headline", "")

    # Groundedness: is the insight grounded in data?
    groundedness_score = confidence  # Use confidence as proxy
    groundedness_reasons = []
    if "price_unavailable" in risk_flags:
        groundedness_score *= 0.5
        groundedness_reasons.append("Price data unavailable — reduced groundedness")
    if "no_candle_data" in risk_flags:
        groundedness_score *= 0.7
        groundedness_reasons.append("No candle/trend data — partially ungrounded")
    if len(key_facts) >= 3:
        groundedness_reasons.append(f"Insight has {len(key_facts)} supporting facts")
    else:
        groundedness_score *= 0.8
        groundedness_reasons.append(f"Only {len(key_facts)} facts — thin evidence")
    if generated_by == "llm" or generated_by == "hybrid":
        groundedness_reasons.append("LLM-enhanced — check for hallucinations")

    evals.append(_make_eval(
        run_id=run_id, tenant_id=tenant_id,
        eval_name="groundedness",
        score=min(1.0, groundedness_score),
        reasons=groundedness_reasons,
        step_name="insight",
        category="rag",
        rationale=f"Heuristic: confidence={confidence:.2f}, facts={len(key_facts)}, generator={generated_by}",
        conversation_id=conversation_id,
    ))

    # Faithfulness: does the insight faithfully represent the data?
    faithfulness_score = min(1.0, confidence * 1.1)  # Slightly generous
    faithfulness_reasons = []
    if headline and ("unavailable" in headline.lower() or "unknown" in headline.lower()):
        faithfulness_score = 0.3
        faithfulness_reasons.append("Headline indicates data unavailability")
    else:
        faithfulness_reasons.append("Headline appears to represent market data faithfully")
    if generated_by == "template":
        faithfulness_score = min(faithfulness_score + 0.1, 1.0)
        faithfulness_reasons.append("Template-based: high faithfulness (deterministic)")

    evals.append(_make_eval(
        run_id=run_id, tenant_id=tenant_id,
        eval_name="faithfulness",
        score=faithfulness_score,
        reasons=faithfulness_reasons,
        step_name="insight",
        category="rag",
        conversation_id=conversation_id,
    ))

    # Answer relevance
    relevance_score = 0.8 if len(key_facts) >= 2 else 0.5
    evals.append(_make_eval(
        run_id=run_id, tenant_id=tenant_id,
        eval_name="answer_relevance",
        score=relevance_score,
        reasons=[f"Insight provides {len(key_facts)} facts for trade context"],
        step_name="insight",
        category="rag",
        conversation_id=conversation_id,
    ))

    try:
        return _repo.create_eval_batch(evals)
    except Exception as e:
        logger.warning("Failed to emit insight evals: %s", e)
        return []


def emit_news_coverage_eval(
    run_id: str,
    tenant_id: str,
    news_enabled: bool,
    headlines_count: int,
    conversation_id: Optional[str] = None,
    reason: str = "",
) -> Optional[str]:
    """Emit news_coverage eval — score=0 when news ON but no headlines."""
    if not news_enabled:
        return None  # Don't penalize when news is explicitly disabled

    score = min(1.0, headlines_count / 3.0) if headlines_count > 0 else 0.0
    reasons = []
    if headlines_count == 0:
        reasons.append("News toggle ON but 0 headlines found")
        if reason:
            reasons.append(reason)
        else:
            reasons.append("Check RSS/GDELT feed configuration")
    else:
        reasons.append(f"{headlines_count} headlines found")

    ev = _make_eval(
        run_id=run_id, tenant_id=tenant_id,
        eval_name="news_coverage",
        score=score,
        reasons=reasons,
        step_name="news",
        category="data",
        rationale=f"headlines_count={headlines_count}, news_enabled={news_enabled}",
        conversation_id=conversation_id,
    )

    try:
        return _repo.create_eval_result(ev)
    except Exception as e:
        logger.warning("Failed to emit news_coverage eval: %s", e)
        return None


def emit_runtime_metric(
    metric_name: str,
    details: Dict[str, Any],
    run_id: str = "none",
    tenant_id: str = "system",
) -> Optional[str]:
    """Emit a runtime telemetry metric to eval_results (best-effort)."""
    ev = _make_eval(
        run_id=run_id,
        tenant_id=tenant_id,
        eval_name=f"metric_{metric_name}",
        score=0.0,
        reasons=[json.dumps(details, default=str)],
        step_name="telemetry",
        category="telemetry",
        rationale=f"Runtime metric: {metric_name}",
    )
    try:
        return _repo.create_eval_result(ev)
    except Exception as e:
        logger.warning("Failed to emit runtime metric %s: %s", metric_name, e)
        return None


def emit_execution_eval(
    run_id: str,
    tenant_id: str,
    success: bool,
    mode: str = "PAPER",
    error: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Optional[str]:
    """Emit execution quality eval after trade completes."""
    score = 1.0 if success else 0.0
    reasons = []
    if success:
        reasons.append(f"Trade executed successfully in {mode} mode")
    else:
        reasons.append(f"Trade failed in {mode} mode")
        if error:
            reasons.append(f"Error: {error[:200]}")

    ev = _make_eval(
        run_id=run_id, tenant_id=tenant_id,
        eval_name="execution_quality",
        score=score,
        reasons=reasons,
        step_name="execute",
        category="quality",
        conversation_id=conversation_id,
    )

    try:
        return _repo.create_eval_result(ev)
    except Exception as e:
        logger.warning("Failed to emit execution eval: %s", e)
        return None


# ---------------------------------------------------------------------------
# Enterprise eval metrics
# ---------------------------------------------------------------------------

def emit_tool_success_rate(
    run_id: str,
    tenant_id: str,
    conversation_id: Optional[str] = None,
) -> Optional[str]:
    """Emit tool_success_rate eval — ratio of successful tool calls for this run."""
    from backend.db.connect import get_conn

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as succeeded,
                          SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed
                   FROM tool_calls WHERE run_id = ?""",
                (run_id,),
            )
            row = cursor.fetchone()
            total = row["total"] if row else 0
            succeeded = row["succeeded"] if row else 0

        score = (succeeded / total) if total > 0 else 1.0
        reasons = [f"{succeeded}/{total} tool calls succeeded"]
        if total == 0:
            reasons.append("No tool calls recorded for this run")

        ev = _make_eval(
            run_id=run_id, tenant_id=tenant_id,
            eval_name="tool_success_rate",
            score=min(1.0, score),
            reasons=reasons,
            step_name="tools",
            category="reliability",
            rationale=f"succeeded={succeeded}, total={total}",
            conversation_id=conversation_id,
        )
        return _repo.create_eval_result(ev)
    except Exception as e:
        logger.warning("Failed to emit tool_success_rate eval: %s", e)
        return None


def emit_news_sentiment_grounded_rate(
    run_id: str,
    tenant_id: str,
    conversation_id: Optional[str] = None,
) -> Optional[str]:
    """Emit news_sentiment_grounded_rate — checks if sentiment rationales quote headline text."""
    from backend.db.connect import get_conn

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            # Fetch the insight from run artifacts
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts
                   WHERE run_id = ? AND artifact_type = 'financial_brief'
                   ORDER BY created_at DESC LIMIT 1""",
                (run_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None  # No insight artifact — skip

        import json as _json
        artifact = _json.loads(row["artifact_json"])
        headlines = (artifact.get("sources") or {}).get("headlines") or []

        grounded = 0
        total = 0
        for h in headlines:
            total += 1
            rationale = (h.get("rationale") or "").lower()
            title = (h.get("title") or "").lower()
            # Grounded if rationale references at least one significant word from the title
            title_words = [w for w in title.split() if len(w) > 4]
            if any(w in rationale for w in title_words) or h.get("driver", "none") != "none":
                grounded += 1

        score = (grounded / total) if total > 0 else 1.0
        reasons = [f"{grounded}/{total} headline sentiments grounded in rationale"]

        ev = _make_eval(
            run_id=run_id, tenant_id=tenant_id,
            eval_name="news_sentiment_grounded_rate",
            score=min(1.0, score),
            reasons=reasons,
            step_name="news",
            category="grounding",
            rationale=f"grounded={grounded}, total={total}",
            conversation_id=conversation_id,
        )
        return _repo.create_eval_result(ev)
    except Exception as e:
        logger.warning("Failed to emit news_sentiment_grounded_rate eval: %s", e)
        return None


def emit_response_format_score(
    run_id: str,
    tenant_id: str,
    conversation_id: Optional[str] = None,
) -> Optional[str]:
    """Emit response_format_score — checks that insights are structured (not raw JSON dumps)."""
    from backend.db.connect import get_conn

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts
                   WHERE run_id = ? AND artifact_type = 'financial_brief'
                   ORDER BY created_at DESC LIMIT 1""",
                (run_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        import json as _json
        artifact = _json.loads(row["artifact_json"])

        score = 0.0
        reasons = []

        # Check required structured fields for financial_brief artifact
        # Actual format: {ranked_assets, lookback_hours, granularity, universe_size, ...}
        has_ranked = isinstance(artifact.get("ranked_assets"), list) and len(artifact.get("ranked_assets", [])) > 0
        has_lookback = artifact.get("lookback_hours") is not None
        has_granularity = bool(artifact.get("granularity"))
        has_computed = bool(artifact.get("computed_at"))

        checks_passed = sum([has_ranked, has_lookback, has_granularity, has_computed])
        score = checks_passed / 4.0

        if has_ranked:
            reasons.append(f"Has {len(artifact.get('ranked_assets', []))} ranked assets")
        else:
            reasons.append("Missing ranked_assets")
        if has_lookback:
            reasons.append(f"Has lookback_hours: {artifact.get('lookback_hours')}")
        else:
            reasons.append("Missing lookback_hours")
        if has_granularity:
            reasons.append(f"Has granularity: {artifact.get('granularity')}")
        else:
            reasons.append("Missing granularity")
        if has_computed:
            reasons.append("Has computed_at timestamp")
        else:
            reasons.append("Missing computed_at")

        ev = _make_eval(
            run_id=run_id, tenant_id=tenant_id,
            eval_name="response_format_score",
            score=min(1.0, score),
            reasons=reasons,
            step_name="insight",
            category="quality",
            rationale=f"{checks_passed}/4 format checks passed",
            conversation_id=conversation_id,
        )
        return _repo.create_eval_result(ev)
    except Exception as e:
        logger.warning("Failed to emit response_format_score eval: %s", e)
        return None


def emit_run_state_consistency(
    run_id: str,
    tenant_id: str,
    conversation_id: Optional[str] = None,
) -> Optional[str]:
    """Emit run_state_consistency — validates no contradictory states in run_events."""
    from backend.db.connect import get_conn

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            # Get the run's final status
            cursor.execute(
                "SELECT status FROM runs WHERE run_id = ?",
                (run_id,),
            )
            run_row = cursor.fetchone()
            final_status = run_row["status"] if run_row else "UNKNOWN"

            # Get all run events in order
            cursor.execute(
                "SELECT event_type, payload_json FROM run_events WHERE run_id = ? ORDER BY ts ASC",
                (run_id,),
            )
            events = cursor.fetchall()

        score = 1.0
        reasons = []
        event_types = [e["event_type"] for e in events]

        # Check: no RUNNING event after COMPLETED or FAILED
        terminal_seen = False
        for et in event_types:
            if et in ("RUN_COMPLETED", "RUN_FAILED"):
                terminal_seen = True
            elif terminal_seen and et in ("RUN_STARTED", "NODE_STARTED"):
                score = 0.0
                reasons.append(f"Event {et} occurred after terminal state")

        # Check: final status matches event trail
        if final_status == "COMPLETED" and "RUN_COMPLETED" not in event_types:
            score *= 0.5
            reasons.append("Run marked COMPLETED but no RUN_COMPLETED event found")
        if final_status == "FAILED" and "RUN_FAILED" not in event_types:
            score *= 0.5
            reasons.append("Run marked FAILED but no RUN_FAILED event found")

        if not reasons:
            reasons.append(f"State consistent: {len(events)} events, final status {final_status}")

        ev = _make_eval(
            run_id=run_id, tenant_id=tenant_id,
            eval_name="run_state_consistency",
            score=max(0.0, min(1.0, score)),
            reasons=reasons,
            step_name="orchestration",
            category="reliability",
            rationale=f"events={len(events)}, final_status={final_status}",
            conversation_id=conversation_id,
        )
        return _repo.create_eval_result(ev)
    except Exception as e:
        logger.warning("Failed to emit run_state_consistency eval: %s", e)
        return None
