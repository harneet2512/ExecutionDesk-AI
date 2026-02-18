"""Evaluation results repository with enterprise eval support."""
import json
from typing import List, Optional, Dict, Any
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


class EvalsRepo:
    """Repository for evaluation results."""

    def create_eval_result(self, eval_data: Dict[str, Any]) -> str:
        """Create an evaluation result with full enterprise fields."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO eval_results (
                    eval_id, run_id, tenant_id, eval_name,
                    score, reasons_json, ts,
                    conversation_id, eval_category, details_json,
                    step_name, rationale, inputs_json,
                    evaluator_type, thresholds_json
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'),
                          ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval_data["eval_id"],
                    eval_data["run_id"],
                    eval_data["tenant_id"],
                    eval_data["eval_name"],
                    eval_data.get("score"),
                    eval_data.get("reasons_json"),
                    eval_data.get("conversation_id"),
                    eval_data.get("eval_category", "quality"),
                    eval_data.get("details_json"),
                    eval_data.get("step_name"),
                    eval_data.get("rationale"),
                    eval_data.get("inputs_json"),
                    eval_data.get("evaluator_type", "heuristic"),
                    eval_data.get("thresholds_json"),
                )
            )
            conn.commit()
            return eval_data["eval_id"]

    def create_eval_batch(self, evals: List[Dict[str, Any]]) -> List[str]:
        """Create multiple evaluation results in a single transaction."""
        ids = []
        with get_conn() as conn:
            cursor = conn.cursor()
            for eval_data in evals:
                cursor.execute(
                    """
                    INSERT INTO eval_results (
                        eval_id, run_id, tenant_id, eval_name,
                        score, reasons_json, ts,
                        conversation_id, eval_category, details_json,
                        step_name, rationale, inputs_json,
                        evaluator_type, thresholds_json
                    ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'),
                              ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eval_data["eval_id"],
                        eval_data["run_id"],
                        eval_data["tenant_id"],
                        eval_data["eval_name"],
                        eval_data.get("score"),
                        eval_data.get("reasons_json"),
                        eval_data.get("conversation_id"),
                        eval_data.get("eval_category", "quality"),
                        eval_data.get("details_json"),
                        eval_data.get("step_name"),
                        eval_data.get("rationale"),
                        eval_data.get("inputs_json"),
                        eval_data.get("evaluator_type", "heuristic"),
                        eval_data.get("thresholds_json"),
                    )
                )
                ids.append(eval_data["eval_id"])
            conn.commit()
        return ids

    def get_evals_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all evaluations for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM eval_results WHERE run_id = ? ORDER BY ts ASC",
                (run_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_evals_by_conversation(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Get all evaluations for a conversation."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM eval_results WHERE conversation_id = ? ORDER BY ts ASC",
                (conversation_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_evals_by_tenant(
        self,
        tenant_id: str,
        eval_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get evaluations for a tenant."""
        with get_conn() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM eval_results WHERE tenant_id = ?"
            params: list = [tenant_id]

            if eval_type:
                query += " AND eval_name = ?"
                params.append(eval_type)

            query += " ORDER BY ts DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_summary(self, tenant_id: str, window_hours: int = 24) -> Dict[str, Any]:
        """Get eval summary for a time window with enterprise telemetry (min/max/p50/p95/pass_rate)."""
        with get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    COUNT(DISTINCT run_id) as total_runs,
                    COUNT(*) as total_evals,
                    AVG(score) as avg_score,
                    MIN(score) as min_score,
                    MAX(score) as max_score,
                    SUM(CASE WHEN score >= 0.5 THEN 1 ELSE 0 END) as passed_count,
                    SUM(CASE WHEN score < 0.5 THEN 1 ELSE 0 END) as failed_count,
                    AVG(CASE WHEN eval_name = 'groundedness' THEN score END) as avg_groundedness,
                    AVG(CASE WHEN eval_name = 'retrieval_relevance' THEN score END) as avg_retrieval_relevance,
                    AVG(CASE WHEN eval_name = 'faithfulness' THEN score END) as avg_faithfulness,
                    SUM(CASE WHEN eval_name = 'news_coverage' AND score = 0 THEN 1 ELSE 0 END) as missing_headlines_count,
                    SUM(CASE WHEN eval_name IN ('no_candle_data', 'data_freshness') AND score < 0.5 THEN 1 ELSE 0 END) as missing_candles_count
                FROM eval_results
                WHERE tenant_id = ?
                  AND ts >= datetime('now', ? || ' hours')
                """,
                (tenant_id, f"-{window_hours}")
            )
            row = cursor.fetchone()
            if not row or not row["total_evals"]:
                return {
                    "total_runs": 0, "total_evals": 0, "avg_score": 0,
                    "min_score": None, "max_score": None,
                    "p50_score": None, "p95_score": None,
                    "pass_rate": 0, "passed_count": 0, "failed_count": 0,
                    "avg_groundedness": None, "avg_retrieval_relevance": None,
                    "avg_faithfulness": None,
                    "missing_headlines_pct": 0, "missing_candles_pct": 0,
                    "missing_headlines_count": 0, "missing_candles_count": 0,
                }

            total_runs = row["total_runs"] or 0
            total_evals = row["total_evals"] or 0
            passed_count = row["passed_count"] or 0
            failed_count = row["failed_count"] or 0

            # Compute percentiles (p50, p95) using NTILE in SQLite
            p50_score = None
            p95_score = None
            try:
                cursor.execute(
                    """
                    SELECT score FROM eval_results
                    WHERE tenant_id = ? AND ts >= datetime('now', ? || ' hours')
                    ORDER BY score ASC
                    """,
                    (tenant_id, f"-{window_hours}")
                )
                scores = [float(r["score"]) for r in cursor.fetchall() if r["score"] is not None]
                if scores:
                    p50_idx = max(0, int(len(scores) * 0.50) - 1)
                    p95_idx = max(0, int(len(scores) * 0.95) - 1)
                    p50_score = round(scores[p50_idx], 3)
                    p95_score = round(scores[p95_idx], 3)
            except Exception:
                pass

            return {
                "total_runs": total_runs,
                "total_evals": total_evals,
                "avg_score": round(float(row["avg_score"] or 0), 3),
                "min_score": round(float(row["min_score"]), 3) if row["min_score"] is not None else None,
                "max_score": round(float(row["max_score"]), 3) if row["max_score"] is not None else None,
                "p50_score": p50_score,
                "p95_score": p95_score,
                "pass_rate": round(passed_count / max(total_evals, 1), 3),
                "passed_count": passed_count,
                "failed_count": failed_count,
                "avg_groundedness": round(float(row["avg_groundedness"]), 3) if row["avg_groundedness"] else None,
                "avg_retrieval_relevance": round(float(row["avg_retrieval_relevance"]), 3) if row["avg_retrieval_relevance"] else None,
                "avg_faithfulness": round(float(row["avg_faithfulness"]), 3) if row["avg_faithfulness"] else None,
                "missing_headlines_count": row["missing_headlines_count"] or 0,
                "missing_candles_count": row["missing_candles_count"] or 0,
                "missing_headlines_pct": round(
                    (row["missing_headlines_count"] or 0) / max(total_runs, 1) * 100, 1
                ),
                "missing_candles_pct": round(
                    (row["missing_candles_count"] or 0) / max(total_runs, 1) * 100, 1
                ),
            }
