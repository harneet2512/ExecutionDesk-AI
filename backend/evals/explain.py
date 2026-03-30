"""Eval explainability: rule-based and optional LLM-generated explanations.

Scoring remains rule-based; this module only generates explanation text from
computed score + evidence. Simple evals use rule templates; semantic evals
(rag, grounding, hallucination) can use LLM with strict context.
"""

import json
import asyncio
from typing import Any, Optional

from backend.core.utils import _safe_json_loads
from backend.evals.eval_definitions import get_definition


# Eval types that get rule-only explanation (no LLM)
RULE_ONLY_EVALUATOR_TYPES = {"heuristic", "default", "unknown"}

# Categories where LLM explanation is most useful (semantic interpretation)
SEMANTIC_CATEGORIES = {"rag"}


def _truncate_evidence(details: Any, max_keys: int = 10, max_value_len: int = 200) -> dict:
    """Produce a small evidence subset for LLM context (no PII, bounded size)."""
    if not details or not isinstance(details, dict):
        return {}
    out = {}
    for i, (k, v) in enumerate(list(details.items())[:max_keys]):
        if v is None:
            out[k] = None
        elif isinstance(v, (str, int, float, bool)):
            s = str(v)
            out[k] = s[:max_value_len] + ("..." if len(s) > max_value_len else "")
        elif isinstance(v, list):
            out[k] = [str(x)[:max_value_len] for x in (v[:5] if len(v) > 5 else v)]
        else:
            out[k] = json.dumps(v, default=str)[:max_value_len] + "..."
    return out


def build_rule_explanation(
    eval_name: str,
    score: float,
    passed: bool,
    reasons: list,
    definition: dict,
) -> dict:
    """Build explanation from rules only: summary, explanation, recommended_fix, evidence_used, confidence."""
    title = definition.get("title") or eval_name.replace("_", " ").title()
    threshold = definition.get("threshold", 0.5)
    how_to_improve = definition.get("how_to_improve") or []

    reasons_str = "; ".join(str(r) for r in (reasons or [])[:5])
    if not reasons_str:
        reasons_str = "No specific reasons recorded."

    if passed:
        summary = f"{title} passed (score {score:.2f} >= threshold {threshold:.2f})."
        explanation = (
            f"This eval checks: {definition.get('description', 'N/A')}. "
            f"The score is {score:.2f} (threshold {threshold:.2f}). {reasons_str}"
        )
        recommended_fix = []
    else:
        summary = f"{title} failed (score {score:.2f} below threshold {threshold:.2f})."
        explanation = (
            f"This eval checks: {definition.get('description', 'N/A')}. "
            f"The score is {score:.2f} (threshold {threshold:.2f}). Reasons: {reasons_str}"
        )
        recommended_fix = how_to_improve[:3]

    return {
        "summary": summary,
        "explanation": explanation,
        "explanation_source": "rules",
        "evidence_used": list(reasons)[:5] if reasons else [],
        "recommended_fix": recommended_fix,
        "confidence": 1.0,
    }


async def _call_llm_for_eval(
    eval_name: str,
    category: str,
    score: float,
    threshold: float,
    passed: bool,
    rubric_snippet: str,
    reasons: list,
    evidence_subset: dict,
    how_to_improve: list,
) -> Optional[dict]:
    """Call LLM to generate summary, explanation, evidence_used, recommended_fix. Returns None if unavailable or error."""
    try:
        from openai import AsyncOpenAI
        from backend.core.config import get_settings
        if not get_settings().openai_api_key:
            return None
    except Exception:
        return None

    try:
        client = AsyncOpenAI()
        reasons_text = "; ".join(str(r) for r in (reasons or [])[:5]) or "No reasons provided."
        evidence_text = json.dumps(evidence_subset, default=str)[:1500] if evidence_subset else "No evidence provided."

        prompt = f"""You are an evaluation explainability assistant. Generate a short, grounded explanation for this eval result.
Do NOT invent facts. Only reference the evidence and reasons below. If evidence is missing, say "Insufficient evidence" and suggest what to log.

Eval: {eval_name}
Category: {category}
Score: {score:.3f} (threshold: {threshold:.3f}) — {"PASS" if passed else "FAIL"}
Rubric: {rubric_snippet[:400]}
Reasons: {reasons_text}
Evidence (subset): {evidence_text}
How to improve (from rubric): {json.dumps(how_to_improve[:3])}

Respond in JSON only:
{{
  "summary": "One sentence summary of why this score.",
  "explanation": "2-4 sentences explaining the score, quoting evidence or reasons where relevant.",
  "evidence_used": ["list", "of", "evidence keys or reason snippets you referenced"],
  "recommended_fix": ["bullet 1", "bullet 2"] (only if FAIL; else empty array),
  "confidence": 0.0 to 1.0
}}"""

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=get_settings().openai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=500,
            ),
            timeout=15.0,
        )
        content = response.choices[0].message.content
        if not content:
            return None
        # Strip markdown code block if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        result = json.loads(content)
        if not isinstance(result, dict):
            return None
        result["explanation_source"] = "llm"
        if "confidence" not in result or not isinstance(result["confidence"], (int, float)):
            result["confidence"] = 0.8
        return result
    except Exception:
        return None


def explain_eval_sync(
    eval_name: str,
    category: str,
    score: float,
    threshold: float,
    passed: bool,
    reasons: list,
    details: Any,
    definition: dict,
    use_llm: bool = False,
) -> dict:
    """Synchronous wrapper: produce explanation (rules only, or rules+LLM if use_llm and semantic)."""
    reasons_list = list(reasons) if reasons else []
    rule_result = build_rule_explanation(eval_name, score, passed, reasons_list, definition)
    if not use_llm:
        return rule_result

    evaluator_type = (definition.get("evaluator_type") or "default").lower()
    if evaluator_type in RULE_ONLY_EVALUATOR_TYPES and category not in SEMANTIC_CATEGORIES:
        return rule_result

    evidence_subset = _truncate_evidence(details)
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # If we're already in async context, we cannot block on async call; return rule-only
        return rule_result
    try:
        llm_result = loop.run_until_complete(
            _call_llm_for_eval(
                eval_name=eval_name,
                category=category,
                score=score,
                threshold=threshold,
                passed=passed,
                rubric_snippet=definition.get("rubric", "") or definition.get("description", ""),
                reasons=reasons_list,
                evidence_subset=evidence_subset,
                how_to_improve=definition.get("how_to_improve") or [],
            )
        )
    except Exception:
        llm_result = None
    if llm_result and isinstance(llm_result.get("explanation"), str):
        return llm_result
    return rule_result


async def explain_eval_async(
    eval_name: str,
    category: str,
    score: float,
    threshold: float,
    passed: bool,
    reasons: list,
    details: Any,
    definition: dict,
    use_llm: bool = True,
) -> dict:
    """Produce explanation for one eval. Uses LLM for semantic evals when use_llm=True and API available."""
    reasons_list = list(reasons) if reasons else []
    rule_result = build_rule_explanation(eval_name, score, passed, reasons_list, definition)
    if not use_llm:
        return rule_result

    evaluator_type = (definition.get("evaluator_type") or "default").lower()
    if evaluator_type in RULE_ONLY_EVALUATOR_TYPES and category not in SEMANTIC_CATEGORIES:
        return rule_result

    evidence_subset = _truncate_evidence(details)
    llm_result = await _call_llm_for_eval(
        eval_name=eval_name,
        category=category,
        score=score,
        threshold=threshold,
        passed=passed,
        rubric_snippet=definition.get("rubric", "") or definition.get("description", ""),
        reasons=reasons_list,
        evidence_subset=evidence_subset,
        how_to_improve=definition.get("how_to_improve") or [],
    )
    if llm_result and isinstance(llm_result.get("explanation"), str):
        return llm_result
    return rule_result


async def explain_run_async(
    run_id: str,
    overall_score: float,
    grade: str,
    category_breakdown: dict,
    top_failures: list,
    total_evals: int,
    passed_count: int,
    failed_count: int,
) -> Optional[dict]:
    """Run-level explainer: main drivers, strongest areas, what to fix. Grounded only in computed evals."""
    try:
        from openai import AsyncOpenAI
        from backend.core.config import get_settings
        if not get_settings().openai_api_key:
            return None
    except Exception:
        return None

    try:
        client = AsyncOpenAI()
        failures_text = "\n".join(
            f"- {e.get('eval_name', '?')}: score {e.get('score', 0):.2f}; reasons: {str(e.get('reasons', [])[:2])}"
            for e in (top_failures or [])[:5]
        )
        categories_text = json.dumps({
            k: {"avg_score": v.get("avg_score"), "grade": v.get("grade"), "total": v.get("total")}
            for k, v in (category_breakdown or {}).items()
        }, default=str)[:800]

        prompt = f"""You are an evaluation summary assistant. Based ONLY on the following run metrics, produce a short run-level explanation.
Do NOT invent metrics. Use only the numbers and eval names below.

Run ID: {run_id}
Overall score: {overall_score:.3f} — Grade: {grade}
Total evals: {total_evals} (passed: {passed_count}, failed: {failed_count})
Category breakdown: {categories_text}
Top failures:
{failures_text or "None"}

Respond in JSON only:
{{
  "main_drivers": ["2-4 bullets: what drove the score up or down"],
  "strongest_areas": ["1-2 bullets: categories or evals that did well"],
  "what_to_fix": ["2-4 bullets: concrete fixes based on the failures above"]
}}"""

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=get_settings().openai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=400,
            ),
            timeout=15.0,
        )
        content = response.choices[0].message.content
        if not content:
            return None
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        result = json.loads(content)
        if isinstance(result, dict) and ("main_drivers" in result or "what_to_fix" in result):
            return result
        return None
    except Exception:
        return None
