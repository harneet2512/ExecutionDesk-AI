"""Tests for the eval dashboard API endpoints and RAGAS eval imports.

Verifies:
- /api/v1/evals/dashboard returns correct structure
- /api/v1/evals/runs returns paginated list
- /api/v1/evals/run/{run_id} returns scorecard
- /api/v1/evals/run/{run_id}/details returns category breakdown
- RAGAS eval functions are importable and callable
- Eval category mapping covers all known eval names
"""
import pytest
import os
import json
import tempfile
import shutil
from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)

HEADERS = {"X-Dev-Tenant": "t_default"}


@pytest.fixture(scope="function")
def setup_db():
    """Create an isolated test database."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_evals.db")

    old_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["TEST_DATABASE_URL"] = f"sqlite:///{db_path}"

    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass

    try:
        from backend.db.connect import init_db, _close_connections
        _close_connections()
        init_db()
        yield db_path
    finally:
        from backend.db.connect import _close_connections
        _close_connections()
        if old_db_url:
            os.environ["DATABASE_URL"] = old_db_url
        else:
            os.environ.pop("DATABASE_URL", None)
        os.environ.pop("TEST_DATABASE_URL", None)
        try:
            from backend.core.config import reset_settings
            reset_settings()
        except ImportError:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)


def _seed_eval_data(run_id: str, tenant_id: str = "t_default"):
    """Insert a run and eval results for testing."""
    from backend.db.connect import get_conn
    from backend.core.time import now_iso

    ts = now_iso()
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO runs (run_id, tenant_id, status, execution_mode, command_text, created_at) VALUES (?, ?, 'COMPLETED', 'PAPER', 'buy $2 of BTC', ?)",
            (run_id, tenant_id, ts),
        )
        evals = [
            ("faithfulness", 0.85, "rag", ["Claims grounded in evidence"]),
            ("answer_relevance", 0.92, "rag", ["Response matches intent"]),
            ("retrieval_relevance", 0.78, "rag", ["Evidence mostly relevant"]),
            ("prompt_injection_resistance", 1.0, "safety", ["No injection detected"]),
            ("agent_quality", 0.88, "quality", ["Good execution flow"]),
            ("budget_compliance", 0.95, "compliance", ["Within budget"]),
            ("latency_slo", 0.7, "performance", ["Slightly slow"]),
            ("data_freshness", 0.6, "data", ["Data 12h old"]),
        ]
        for eval_name, score, category, reasons in evals:
            cursor.execute(
                """INSERT INTO eval_results
                   (eval_id, run_id, tenant_id, eval_name, score, reasons_json,
                    evaluator_type, thresholds_json, eval_category, ts)
                   VALUES (?, ?, ?, ?, ?, ?, 'heuristic', '{}', ?, ?)""",
                (
                    f"ev_{eval_name}_{run_id[:8]}",
                    run_id,
                    tenant_id,
                    eval_name,
                    score,
                    json.dumps(reasons),
                    category,
                    ts,
                ),
            )
        conn.commit()


class TestEvalDashboardEndpoint:
    """Tests for GET /api/v1/evals/dashboard."""

    def test_dashboard_empty(self, setup_db):
        """Dashboard with no eval data returns zero counts."""
        response = client.get("/api/v1/evals/dashboard", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["total_runs_evaluated"] == 0
        assert data["overall_avg_score"] == 0.0
        assert "category_scores" in data
        assert "grade_distribution" in data
        assert "recent_runs" in data

    def test_dashboard_with_data(self, setup_db):
        """Dashboard with seeded eval data returns correct aggregates."""
        _seed_eval_data("run_eval_test_001")
        response = client.get("/api/v1/evals/dashboard", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()

        assert data["total_runs_evaluated"] == 1
        assert data["overall_avg_score"] > 0
        assert data["overall_grade"] in ("A", "B", "C", "D", "F")
        assert len(data["category_scores"]) > 0
        assert len(data["recent_runs"]) == 1

        run = data["recent_runs"][0]
        assert run["run_id"] == "run_eval_test_001"
        assert run["eval_count"] == 8
        assert run["grade"] in ("A", "B", "C", "D", "F")

    def test_dashboard_category_scores(self, setup_db):
        """Dashboard category scores include expected categories."""
        _seed_eval_data("run_eval_test_002")
        response = client.get("/api/v1/evals/dashboard", headers=HEADERS)
        data = response.json()

        cats = data["category_scores"]
        assert "rag" in cats
        assert "safety" in cats
        assert cats["safety"]["avg_score"] == 1.0
        assert cats["safety"]["grade"] == "A"


class TestEvalRunsEndpoint:
    """Tests for GET /api/v1/evals/runs."""

    def test_runs_empty(self, setup_db):
        """Empty DB returns empty runs list."""
        response = client.get("/api/v1/evals/runs", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["runs"] == []
        assert data["limit"] == 50
        assert data["offset"] == 0

    def test_runs_with_data(self, setup_db):
        """Seeded data returns runs with eval summaries."""
        _seed_eval_data("run_eval_test_003")
        response = client.get("/api/v1/evals/runs?limit=10&offset=0", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()

        assert len(data["runs"]) == 1
        run = data["runs"][0]
        assert run["run_id"] == "run_eval_test_003"
        assert run["eval_count"] == 8
        assert isinstance(run["avg_score"], float)
        assert run["passed"] >= 0
        assert run["failed"] >= 0


class TestRunScorecardEndpoint:
    """Tests for GET /api/v1/evals/run/{run_id}."""

    def test_scorecard_not_found(self, setup_db):
        """Non-existent run returns 404."""
        response = client.get("/api/v1/evals/run/nonexistent_run", headers=HEADERS)
        assert response.status_code == 404

    def test_scorecard_with_data(self, setup_db):
        """Scorecard returns eval details and summary."""
        _seed_eval_data("run_eval_test_004")
        response = client.get("/api/v1/evals/run/run_eval_test_004", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()

        assert "evals" in data
        assert "summary" in data
        assert "categories" in data
        assert "failures" in data

        assert data["summary"]["total_evals"] == 8
        assert data["summary"]["avg_score"] > 0
        assert data["summary"]["grade"] in ("A", "B", "C", "D", "F")

        # Check eval details
        eval_names = [e["eval_name"] for e in data["evals"]]
        assert "faithfulness" in eval_names
        assert "answer_relevance" in eval_names


class TestRunDetailEndpoint:
    """Tests for GET /api/v1/evals/run/{run_id}/details."""

    def test_details_not_found(self, setup_db):
        """Non-existent run returns 404."""
        response = client.get("/api/v1/evals/run/nonexistent/details", headers=HEADERS)
        assert response.status_code == 404

    def test_details_with_data(self, setup_db):
        """Details endpoint returns category-grouped evals."""
        _seed_eval_data("run_eval_test_005")
        response = client.get("/api/v1/evals/run/run_eval_test_005/details", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()

        assert "run" in data
        assert data["run"]["run_id"] == "run_eval_test_005"
        assert "summary" in data
        assert "categories" in data

        # Categories should include rag, safety, quality, etc.
        cats = data["categories"]
        assert "rag" in cats
        assert cats["rag"]["total"] == 3  # faithfulness, answer_relevance, retrieval_relevance
        assert cats["rag"]["grade"] in ("A", "B", "C", "D", "F")

        # Each category should have evals list
        for cat_data in cats.values():
            assert "evals" in cat_data
            assert len(cat_data["evals"]) > 0


class TestRAGSEvalsImport:
    """Tests for RAGAS-style eval functions."""

    def test_rag_evals_importable(self):
        """RAGAS eval functions should be importable."""
        from backend.evals.rag_evals import (
            evaluate_faithfulness,
            evaluate_answer_relevance,
            evaluate_retrieval_relevance,
        )
        assert callable(evaluate_faithfulness)
        assert callable(evaluate_answer_relevance)
        assert callable(evaluate_retrieval_relevance)

    def test_eval_category_map_coverage(self):
        """EVAL_CATEGORY_MAP should cover all known eval names."""
        from backend.api.routes.evals import EVAL_CATEGORY_MAP

        # Check key eval names are mapped
        assert EVAL_CATEGORY_MAP["faithfulness"] == "rag"
        assert EVAL_CATEGORY_MAP["answer_relevance"] == "rag"
        assert EVAL_CATEGORY_MAP["retrieval_relevance"] == "rag"
        assert EVAL_CATEGORY_MAP["prompt_injection_resistance"] == "safety"
        assert EVAL_CATEGORY_MAP["agent_quality"] == "quality"
        assert EVAL_CATEGORY_MAP["budget_compliance"] == "compliance"
        assert EVAL_CATEGORY_MAP["latency_slo"] == "performance"
        assert EVAL_CATEGORY_MAP["data_freshness"] == "data"

    def test_compute_grade(self):
        """Grade computation should follow A/B/C/D/F scale."""
        from backend.api.routes.evals import _compute_grade

        assert _compute_grade(0.95) == "A"
        assert _compute_grade(0.85) == "B"
        assert _compute_grade(0.75) == "C"
        assert _compute_grade(0.65) == "D"
        assert _compute_grade(0.45) == "F"
