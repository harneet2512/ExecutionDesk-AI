"""Evaluations API endpoints with enterprise dashboard support."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from backend.api.deps import require_viewer
from backend.db.connect import get_conn, row_get
from backend.core.logging import get_logger
from backend.core.utils import _safe_json_loads
from backend.evals.eval_definitions import get_definition, get_all_definitions
from backend.evals.explain import explain_eval_async, explain_run_async

logger = get_logger(__name__)


def _normalize_reasons(reasons_json) -> list:
    """Ensure reasons is always a list of strings for safe React rendering."""
    raw = _safe_json_loads(reasons_json, default=[])
    if not isinstance(raw, list):
        raw = [raw] if raw is not None else []
    return [
        x if isinstance(x, str) else json.dumps(x, default=str)
        for x in raw
    ]

router = APIRouter()

# Category mapping for evals that were inserted before eval_category column existed
EVAL_CATEGORY_MAP = {
    # RAG
    "faithfulness": "rag", "answer_relevance": "rag", "retrieval_relevance": "rag",
    "hallucination_detection": "rag", "news_evidence_integrity": "rag",
    "evidence_sufficiency": "rag", "citation_coverage": "rag",
    "numeric_claims_grounded": "rag", "portfolio_grounding": "rag",
    # Safety
    "prompt_injection_resistance": "safety", "policy_invariants": "safety",
    "risk_gate_compliance": "safety",
    # Quality
    "agent_quality": "quality", "ux_completeness": "quality",
    "execution_quality": "quality", "ranking_correctness": "quality",
    "intent_parse_correctness": "quality", "plan_completeness": "quality",
    "ranking_correctness_offline": "quality", "intent_parse_accuracy": "quality",
    "strategy_validity": "quality",
    # Compliance
    "budget_compliance": "compliance", "policy_compliance": "compliance",
    "policy_decision_present": "compliance",
    # Performance
    "latency_slo": "performance", "end_to_end_latency": "performance",
    "rate_limit_resilience": "performance", "tool_error_rate": "performance",
    "tool_call_coverage": "performance", "tool_reliability": "performance",
    # Data
    "market_evidence_integrity": "data", "data_freshness": "data",
    "news_freshness": "data", "cluster_dedup_score": "data",
    "schema_validity": "data", "execution_correctness": "data",
    "determinism_replay": "data", "numeric_grounding": "data",
    "action_grounding": "data", "coinbase_data_integrity": "data",
    # Oracle
    "profit_ranking_correctness": "quality", "time_window_correctness": "performance",
    # Compliance (new)
    "live_trade_truthfulness": "compliance", "confirm_trade_idempotency": "compliance",
    "trade_amount_intent_correctness": "compliance", "insufficient_balance_truthfulness": "compliance",
    # RAG (new)
    "groundedness": "rag", "context_precision": "rag", "context_recall": "rag",
}


def _compute_grade(avg_score: float) -> str:
    if avg_score >= 0.9:
        return "A"
    elif avg_score >= 0.8:
        return "B"
    elif avg_score >= 0.7:
        return "C"
    elif avg_score >= 0.6:
        return "D"
    return "F"


def _get_category(row) -> str:
    """Get eval category from row or fallback to mapping."""
    if "eval_category" in row.keys() and row["eval_category"]:
        return row["eval_category"]
    return EVAL_CATEGORY_MAP.get(row["eval_name"], "quality")


@router.get("/run/{run_id}")
async def get_run_eval_scorecard(run_id: str, user: dict = Depends(require_viewer)):
    """Get evaluation scorecard for a run."""
    tenant_id = user["tenant_id"]

    with get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT run_id FROM runs WHERE run_id = ? AND tenant_id = ?",
            (run_id, tenant_id)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Run not found")

        cursor.execute(
            """
            SELECT eval_id, eval_name, score, reasons_json, evaluator_type, thresholds_json,
                   eval_category, details_json, explanation, explanation_source
            FROM eval_results
            WHERE run_id = ?
            ORDER BY ts ASC
            """,
            (run_id,)
        )
        eval_rows = cursor.fetchall()

    evals = []
    for row in eval_rows:
        defn = get_definition(row["eval_name"])
        thresh = defn.get("threshold", 0.5)
        eval_data = {
            "eval_id": row_get(row, "eval_id"),
            "eval_name": row["eval_name"],
            "score": float(row["score"]),
            "reasons": _normalize_reasons(row["reasons_json"]),
            "evaluator_type": (row["evaluator_type"] if "evaluator_type" in row.keys() else None) or "default",
            "thresholds": _safe_json_loads(row_get(row, "thresholds_json"), default={}),
            "category": _get_category(row),
            "details": _safe_json_loads(row_get(row, "details_json"), default=None),
            "definition": defn,
            "pass": float(row["score"]) >= thresh,
            "explanation": row_get(row, "explanation"),
            "explanation_source": row_get(row, "explanation_source"),
        }
        evals.append(eval_data)

    total_evals = len(evals)
    passed_evals = sum(1 for e in evals if e["pass"])
    failed_evals = total_evals - passed_evals
    avg_score = sum(e["score"] for e in evals) / total_evals if total_evals > 0 else 0.0

    # Category breakdown
    categories = {}
    for e in evals:
        cat = e["category"]
        if cat not in categories:
            categories[cat] = {"scores": [], "passed": 0, "failed": 0}
        categories[cat]["scores"].append(e["score"])
        if e["pass"]:
            categories[cat]["passed"] += 1
        else:
            categories[cat]["failed"] += 1
    category_summary = {}
    for cat, data in categories.items():
        cat_avg = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        category_summary[cat] = {
            "avg_score": round(cat_avg, 3),
            "total": len(data["scores"]),
            "passed": data["passed"],
            "failed": data["failed"],
            "grade": _compute_grade(cat_avg),
        }

    failures = [e for e in evals if not e["pass"]]

    return {
        "evals": evals,
        "summary": {
            "total_evals": total_evals,
            "passed_evals": passed_evals,
            "failed_evals": failed_evals,
            "avg_score": round(avg_score, 3),
            "grade": _compute_grade(avg_score),
        },
        "categories": category_summary,
        "failures": failures,
    }


@router.get("/dashboard")
async def get_eval_dashboard(user: dict = Depends(require_viewer)):
    """Aggregate eval dashboard: overall stats, category scores, recent runs."""
    tenant_id = user["tenant_id"]

    with get_conn() as conn:
        cursor = conn.cursor()

        # Total evaluated runs
        cursor.execute(
            "SELECT COUNT(DISTINCT run_id) as cnt FROM eval_results WHERE tenant_id = ?",
            (tenant_id,)
        )
        total_runs = cursor.fetchone()["cnt"]

        # Overall avg score
        cursor.execute(
            "SELECT AVG(score) as avg_score FROM eval_results WHERE tenant_id = ?",
            (tenant_id,)
        )
        row = cursor.fetchone()
        overall_avg = round(float(row["avg_score"]), 3) if row and row["avg_score"] else 0.0

        # Category averages with min/max/pass_rate (use eval_category column or fallback)
        cursor.execute(
            """SELECT eval_name, eval_category, AVG(score) as avg_score,
                      MIN(score) as min_score, MAX(score) as max_score,
                      COUNT(*) as cnt,
                      SUM(CASE WHEN score >= 0.5 THEN 1 ELSE 0 END) as passed
               FROM eval_results WHERE tenant_id = ? GROUP BY eval_name""",
            (tenant_id,)
        )
        eval_name_rows = cursor.fetchall()

        category_totals = {}
        for r in eval_name_rows:
            cat = r["eval_category"] if "eval_category" in r.keys() and r["eval_category"] else EVAL_CATEGORY_MAP.get(r["eval_name"], "quality")
            if cat not in category_totals:
                category_totals[cat] = {"sum": 0.0, "count": 0, "min": 1.0, "max": 0.0, "passed": 0}
            cnt = int(r["cnt"])
            category_totals[cat]["sum"] += float(r["avg_score"]) * cnt
            category_totals[cat]["count"] += cnt
            if r["min_score"] is not None:
                category_totals[cat]["min"] = min(category_totals[cat]["min"], float(r["min_score"]))
            if r["max_score"] is not None:
                category_totals[cat]["max"] = max(category_totals[cat]["max"], float(r["max_score"]))
            category_totals[cat]["passed"] += int(r["passed"] or 0)

        category_scores = {}
        for cat, data in category_totals.items():
            avg = data["sum"] / data["count"] if data["count"] > 0 else 0
            category_scores[cat] = {
                "avg_score": round(avg, 3),
                "min_score": round(data["min"], 3) if data["count"] > 0 else None,
                "max_score": round(data["max"], 3) if data["count"] > 0 else None,
                "eval_count": data["count"],
                "pass_rate": round(data["passed"] / max(data["count"], 1), 3),
                "grade": _compute_grade(avg),
            }

        # Recent runs with eval summaries (last 20)
        cursor.execute(
            """
            SELECT r.run_id, r.status, r.execution_mode, r.created_at, r.command_text,
                   COUNT(er.eval_id) as eval_count,
                   AVG(er.score) as avg_score,
                   SUM(CASE WHEN er.score >= 0.5 THEN 1 ELSE 0 END) as passed,
                   SUM(CASE WHEN er.score < 0.5 THEN 1 ELSE 0 END) as failed
            FROM runs r
            JOIN eval_results er ON r.run_id = er.run_id
            WHERE r.tenant_id = ?
            GROUP BY r.run_id
            ORDER BY r.created_at DESC
            LIMIT 20
            """,
            (tenant_id,)
        )
        recent_runs = []
        for row in cursor.fetchall():
            avg = float(row["avg_score"]) if row["avg_score"] else 0
            recent_runs.append({
                "run_id": row["run_id"],
                "status": row["status"],
                "mode": row["execution_mode"],
                "created_at": row["created_at"],
                "command": row["command_text"][:80] if row["command_text"] else None,
                "eval_count": row["eval_count"],
                "avg_score": round(avg, 3),
                "grade": _compute_grade(avg),
                "passed": row["passed"],
                "failed": row["failed"],
            })

        # Grade distribution
        grade_dist = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        for r in recent_runs:
            grade_dist[r["grade"]] = grade_dist.get(r["grade"], 0) + 1

    return {
        "total_runs_evaluated": total_runs,
        "overall_avg_score": overall_avg,
        "overall_grade": _compute_grade(overall_avg),
        "category_scores": category_scores,
        "grade_distribution": grade_dist,
        "recent_runs": recent_runs,
    }


@router.get("/runs")
async def list_eval_runs(
    user: dict = Depends(require_viewer),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Paginated list of runs with eval summaries."""
    tenant_id = user["tenant_id"]

    with get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT r.run_id, r.status, r.execution_mode, r.created_at, r.command_text,
                   COUNT(er.eval_id) as eval_count,
                   AVG(er.score) as avg_score,
                   SUM(CASE WHEN er.score >= 0.5 THEN 1 ELSE 0 END) as passed,
                   SUM(CASE WHEN er.score < 0.5 THEN 1 ELSE 0 END) as failed
            FROM runs r
            JOIN eval_results er ON r.run_id = er.run_id
            WHERE r.tenant_id = ?
            GROUP BY r.run_id
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (tenant_id, limit, offset)
        )
        rows = cursor.fetchall()

    runs = []
    for row in rows:
        avg = float(row["avg_score"]) if row["avg_score"] else 0
        runs.append({
            "run_id": row["run_id"],
            "status": row["status"],
            "mode": row["execution_mode"],
            "created_at": row["created_at"],
            "command": row["command_text"][:80] if row["command_text"] else None,
            "eval_count": row["eval_count"],
            "avg_score": round(avg, 3),
            "grade": _compute_grade(avg),
            "passed": row["passed"],
            "failed": row["failed"],
        })

    return {"runs": runs, "limit": limit, "offset": offset}


@router.get("/conversations/{conversation_id}")
async def get_conversation_evals(conversation_id: str, user: dict = Depends(require_viewer)):
    """Get all evaluations for a conversation."""
    tenant_id = user["tenant_id"]

    with get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT er.*, r.command_text, r.execution_mode, r.status as run_status
            FROM eval_results er
            JOIN runs r ON er.run_id = r.run_id
            WHERE er.conversation_id = ? AND er.tenant_id = ?
            ORDER BY er.ts ASC
            """,
            (conversation_id, tenant_id)
        )
        rows = cursor.fetchall()

    evals = []
    for row in rows:
        eval_data = {
            "eval_name": row["eval_name"],
            "score": float(row["score"]) if row["score"] is not None else 0,
            "reasons": _normalize_reasons(row["reasons_json"]),
            "step_name": row["step_name"] if "step_name" in row.keys() else None,
            "category": _get_category(row),
            "run_id": row["run_id"],
            "run_status": row["run_status"],
            "pass": float(row["score"] or 0) >= 0.5,
        }
        evals.append(eval_data)

    return {"evals": evals, "conversation_id": conversation_id}


@router.get("/summary")
async def get_eval_summary(
    user: dict = Depends(require_viewer),
    window: str = Query(default="24h"),
):
    """Get eval summary for a time window (24h, 7d)."""
    tenant_id = user["tenant_id"]

    # Parse window
    if window == "7d":
        window_hours = 168
    elif window == "48h":
        window_hours = 48
    else:
        window_hours = 24

    from backend.db.repo.evals_repo import EvalsRepo
    repo = EvalsRepo()
    summary = repo.get_summary(tenant_id, window_hours)

    return {
        "window": window,
        "window_hours": window_hours,
        **summary,
    }


@router.get("/run/{run_id}/details")
async def get_run_eval_details(run_id: str, user: dict = Depends(require_viewer)):
    """Detailed eval breakdown for a run, grouped by category."""
    tenant_id = user["tenant_id"]

    with get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT run_id, command_text, execution_mode, status, created_at FROM runs WHERE run_id = ? AND tenant_id = ?",
            (run_id, tenant_id)
        )
        run_row = cursor.fetchone()
        if not run_row:
            raise HTTPException(status_code=404, detail="Run not found")

        cursor.execute(
            """
            SELECT eval_id, eval_name, score, reasons_json, evaluator_type, thresholds_json,
                   eval_category, details_json, ts, explanation, explanation_source
            FROM eval_results
            WHERE run_id = ?
            ORDER BY ts ASC
            """,
            (run_id,)
        )
        eval_rows = cursor.fetchall()

    # Group by category
    by_category = {}
    all_evals = []
    for row in eval_rows:
        cat = _get_category(row)
        defn = get_definition(row["eval_name"])
        thresh = defn.get("threshold", 0.5)
        eval_data = {
            "eval_id": row_get(row, "eval_id"),
            "eval_name": row["eval_name"],
            "score": float(row["score"]),
            "reasons": _normalize_reasons(row["reasons_json"]),
            "evaluator_type": (row["evaluator_type"] if "evaluator_type" in row.keys() else None) or "default",
            "thresholds": _safe_json_loads(row_get(row, "thresholds_json"), default={}),
            "details": _safe_json_loads(row_get(row, "details_json"), default=None),
            "definition": defn,
            "category": cat,
            "pass": float(row["score"]) >= thresh,
            "ts": row["ts"],
            "explanation": row_get(row, "explanation"),
            "explanation_source": row_get(row, "explanation_source"),
        }
        all_evals.append(eval_data)
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(eval_data)

    # Category summaries
    category_summaries = {}
    for cat, cat_evals in by_category.items():
        scores = [e["score"] for e in cat_evals]
        avg = sum(scores) / len(scores) if scores else 0
        category_summaries[cat] = {
            "avg_score": round(avg, 3),
            "grade": _compute_grade(avg),
            "total": len(scores),
            "passed": sum(1 for s in scores if s >= 0.5),
            "failed": sum(1 for s in scores if s < 0.5),
            "evals": cat_evals,
        }

    total = len(all_evals)
    avg_all = sum(e["score"] for e in all_evals) / total if total > 0 else 0

    return {
        "run": {
            "run_id": run_row["run_id"],
            "command": run_row["command_text"],
            "mode": run_row["execution_mode"],
            "status": run_row["status"],
            "created_at": run_row["created_at"],
        },
        "summary": {
            "total_evals": total,
            "avg_score": round(avg_all, 3),
            "grade": _compute_grade(avg_all),
            "passed": sum(1 for e in all_evals if e["pass"]),
            "failed": sum(1 for e in all_evals if not e["pass"]),
        },
        "categories": category_summaries,
    }


@router.post("/run/{run_id}/explain")
async def post_run_explain(run_id: str, user: dict = Depends(require_viewer)):
    """Generate and store LLM/rule-based explanations for all evals in the run, then run-level summary.
    Scoring stays rule-based; this only fills explanation text. Idempotent: skips evals that already have explanation.
    """
    tenant_id = user["tenant_id"]

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT run_id, command_text, status, created_at FROM runs WHERE run_id = ? AND tenant_id = ?",
            (run_id, tenant_id),
        )
        run_row = cursor.fetchone()
        if not run_row:
            raise HTTPException(status_code=404, detail="Run not found")

        cursor.execute(
            """
            SELECT eval_id, eval_name, score, reasons_json, evaluator_type, thresholds_json,
                   eval_category, details_json, explanation, explanation_source
            FROM eval_results
            WHERE run_id = ?
            ORDER BY ts ASC
            """,
            (run_id,),
        )
        eval_rows = cursor.fetchall()

    if not eval_rows:
        return {"run_id": run_id, "evals_updated": 0, "run_explanation": None, "message": "No evals for this run."}

    evals_updated = 0
    all_evals = []
    by_category = {}
    updates_to_apply = []

    for row in eval_rows:
        eval_id = row_get(row, "eval_id")
        existing_explanation = row_get(row, "explanation")
        if existing_explanation and str(existing_explanation).strip():
            # Already has explanation; build payload for run explainer only
            cat = _get_category(row)
            defn = get_definition(row["eval_name"])
            thresh = defn.get("threshold", 0.5)
            all_evals.append({
                "eval_name": row["eval_name"],
                "score": float(row["score"]),
                "reasons": _normalize_reasons(row["reasons_json"]),
                "category": cat,
                "pass": float(row["score"]) >= thresh,
            })
            if cat not in by_category:
                by_category[cat] = {"scores": [], "total": 0, "passed": 0, "failed": 0, "avg_score": 0, "grade": "F"}
            by_category[cat]["scores"].append(float(row["score"]))
            by_category[cat]["total"] += 1
            if float(row["score"]) >= thresh:
                by_category[cat]["passed"] += 1
            else:
                by_category[cat]["failed"] += 1
            continue

        cat = _get_category(row)
        defn = get_definition(row["eval_name"])
        thresh = defn.get("threshold", 0.5)
        reasons = _normalize_reasons(row["reasons_json"])
        details = _safe_json_loads(row_get(row, "details_json"), default=None)
        passed = float(row["score"]) >= thresh

        result = await explain_eval_async(
            eval_name=row["eval_name"],
            category=cat,
            score=float(row["score"]),
            threshold=thresh,
            passed=passed,
            reasons=reasons,
            details=details,
            definition=defn,
            use_llm=True,
        )
        explanation_text = result.get("explanation") or ""
        source = result.get("explanation_source") or "rules"
        updates_to_apply.append((explanation_text, source, eval_id))
        evals_updated += 1

        all_evals.append({
            "eval_name": row["eval_name"],
            "score": float(row["score"]),
            "reasons": reasons,
            "category": cat,
            "pass": passed,
        })
        if cat not in by_category:
            by_category[cat] = {"scores": [], "total": 0, "passed": 0, "failed": 0, "avg_score": 0, "grade": "F"}
        by_category[cat]["scores"].append(float(row["score"]))
        by_category[cat]["total"] += 1
        if passed:
            by_category[cat]["passed"] += 1
        else:
            by_category[cat]["failed"] += 1

    if updates_to_apply:
        with get_conn() as conn:
            cursor = conn.cursor()
            for explanation_text, source, eval_id in updates_to_apply:
                cursor.execute(
                    "UPDATE eval_results SET explanation = ?, explanation_source = ? WHERE eval_id = ?",
                    (explanation_text, source, eval_id),
                )

    # Category summaries for run explainer
    category_breakdown = {}
    for c, data in by_category.items():
        scores = data["scores"]
        avg = sum(scores) / len(scores) if scores else 0
        category_breakdown[c] = {
            "avg_score": round(avg, 3),
            "grade": _compute_grade(avg),
            "total": data["total"],
            "passed": data["passed"],
            "failed": data["failed"],
        }

    failures = [e for e in all_evals if not e["pass"]]
    total = len(all_evals)
    avg_all = sum(e["score"] for e in all_evals) / total if total else 0
    run_explanation = await explain_run_async(
        run_id=run_id,
        overall_score=avg_all,
        grade=_compute_grade(avg_all),
        category_breakdown=category_breakdown,
        top_failures=failures[:5],
        total_evals=total,
        passed_count=sum(1 for e in all_evals if e["pass"]),
        failed_count=sum(1 for e in all_evals if not e["pass"]),
    )

    return {
        "run_id": run_id,
        "evals_updated": evals_updated,
        "run_explanation": run_explanation,
    }


@router.get("/definitions")
async def list_eval_definitions(user: dict = Depends(require_viewer)):
    """Return all eval definitions."""
    return {"definitions": get_all_definitions()}


@router.get("/definition/{eval_name}")
async def get_eval_definition(eval_name: str, user: dict = Depends(require_viewer)):
    """Return definition for a single eval_name."""
    defn = get_definition(eval_name)
    return {"eval_name": eval_name, "definition": defn}
