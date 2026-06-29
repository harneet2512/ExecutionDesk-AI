"""Tests for analytics client endpoints.

Tests each analytical endpoint returns expected response shape.
Uses the existing test_db fixture from tests/conftest.py.
"""
import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_db):
    """Create a FastAPI test client with a fresh test database."""
    # Must import AFTER test_db fixture sets up the database
    from backend.api.main import app

    return TestClient(app)


@pytest.fixture
def seeded_db(test_db):
    """Seed the test database with sample data for analytics queries."""
    from backend.db.connect import get_conn
    from backend.core.time import now_iso

    with get_conn() as conn:
        cursor = conn.cursor()

        # Insert tenants first (runs.tenant_id FK -> tenants.tenant_id)
        tenants = ["t_active", "t_churning", "t_default"]
        for tid in tenants:
            cursor.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, name) VALUES (?, ?)",
                (tid, f"Tenant {tid}"),
            )

        # Insert runs (multiple tenants for churn/feature-adoption)
        for i, tid in enumerate(tenants):
            for j in range(3):
                run_id = f"run_{tid}_{j}"
                status = "COMPLETED" if j < 2 else "FAILED"
                cursor.execute(
                    """
                    INSERT INTO runs (run_id, tenant_id, status, execution_mode,
                                      command_text, created_at, completed_at)
                    VALUES (?, ?, ?, 'PAPER', ?, ?, ?)
                    """,
                    (run_id, tid, status, f"buy BTC {j}",
                     now_iso(), now_iso() if status == "COMPLETED" else None),
                )

                # Insert DAG nodes for each run
                for node_name in ["research", "signals", "strategy"]:
                    node_status = "COMPLETED" if status == "COMPLETED" else "FAILED"
                    cursor.execute(
                        """
                        INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, completed_at)
                        VALUES (?, ?, ?, 'EXECUTE', ?, ?)
                        """,
                        (f"n_{run_id}_{node_name}", run_id, node_name,
                         node_status, now_iso() if node_status == "COMPLETED" else None),
                    )

                # Insert orders for completed runs
                # orders requires: provider (NOT NULL), order_type (NOT NULL)
                if status == "COMPLETED":
                    cursor.execute(
                        """
                        INSERT INTO orders (order_id, run_id, tenant_id, provider,
                                            symbol, side, order_type,
                                            notional_usd, filled_qty, avg_fill_price,
                                            total_fees, status, status_reason, created_at)
                        VALUES (?, ?, ?, 'paper', 'BTC-USD', 'BUY', 'MARKET',
                                100.0, 0.002, 50000.0,
                                0.50, 'FILLED', NULL, ?)
                        """,
                        (f"ord_{run_id}", run_id, tid, now_iso()),
                    )

                # Insert tool calls (requires mcp_server and request_json NOT NULL,
                # and node_id FK referencing dag_nodes)
                first_node_id = f"n_{run_id}_research"
                cursor.execute(
                    """
                    INSERT INTO tool_calls (id, run_id, node_id, tool_name, mcp_server,
                                            request_json, status, ts)
                    VALUES (?, ?, ?, 'market_data', 'market', '{}', ?, ?)
                    """,
                    (f"tc_{run_id}_{j}", run_id, first_node_id,
                     "ok" if status == "COMPLETED" else "error",
                     now_iso()),
                )

        # Insert eval results
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
            VALUES (?, ?, ?, 'execution_quality', 0.85, '["good"]', ?)
            """,
            ("eval_1", "run_t_active_0", "t_active", now_iso()),
        )

        conn.commit()

    return test_db


@pytest.fixture
def seeded_client(seeded_db):
    """Create a FastAPI test client with a seeded test database."""
    from backend.api.main import app

    return TestClient(app)


class TestClientChurnRisk:
    """Tests for GET /api/v1/analytics/client-churn-risk."""

    def test_returns_expected_shape(self, seeded_client):
        """Endpoint returns list with tenant churn-risk entries."""
        resp = seeded_client.get(
            "/api/v1/analytics/client-churn-risk",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "clients" in data
        assert isinstance(data["clients"], list)

    def test_churn_entry_fields(self, seeded_client):
        """Each churn-risk entry has expected fields."""
        resp = seeded_client.get(
            "/api/v1/analytics/client-churn-risk",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = resp.json()
        if data["clients"]:
            entry = data["clients"][0]
            assert "tenant_id" in entry
            assert "total_runs" in entry
            assert "risk_level" in entry

    def test_unauthenticated_returns_401(self, seeded_client):
        """Unauthenticated request should return 401."""
        import os
        old_bypass = os.environ.get("TEST_AUTH_BYPASS")
        os.environ["TEST_AUTH_BYPASS"] = "false"
        os.environ["ENABLE_DEV_AUTH"] = "true"
        try:
            from backend.core.config import reset_settings
            reset_settings()
            resp = seeded_client.get("/api/v1/analytics/client-churn-risk")
            assert resp.status_code == 401
        finally:
            if old_bypass:
                os.environ["TEST_AUTH_BYPASS"] = old_bypass
            else:
                os.environ["TEST_AUTH_BYPASS"] = "true"
            os.environ.pop("ENABLE_DEV_AUTH", None)
            from backend.core.config import reset_settings
            reset_settings()


class TestExecutionQuality:
    """Tests for GET /api/v1/analytics/execution-quality."""

    def test_returns_expected_shape(self, seeded_client):
        """Endpoint returns execution quality summary."""
        resp = seeded_client.get(
            "/api/v1/analytics/execution-quality",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "total_runs" in data["summary"]
        assert "success_rate" in data["summary"]

    def test_summary_has_numeric_values(self, seeded_client):
        """Summary values should be numeric."""
        resp = seeded_client.get(
            "/api/v1/analytics/execution-quality",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = resp.json()
        summary = data["summary"]
        assert isinstance(summary["total_runs"], (int, float))
        assert isinstance(summary["success_rate"], (int, float))


class TestErrorBreakdown:
    """Tests for GET /api/v1/analytics/error-breakdown."""

    def test_returns_expected_shape(self, seeded_client):
        """Endpoint returns error breakdown list."""
        resp = seeded_client.get(
            "/api/v1/analytics/error-breakdown",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" in data
        assert isinstance(data["errors"], list)
        assert "total_errors" in data

    def test_error_entry_fields(self, seeded_client):
        """Error entries have code and count fields."""
        resp = seeded_client.get(
            "/api/v1/analytics/error-breakdown",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = resp.json()
        if data["errors"]:
            entry = data["errors"][0]
            assert "error_code" in entry or "failure_code" in entry
            assert "count" in entry


class TestFeatureAdoption:
    """Tests for GET /api/v1/analytics/feature-adoption."""

    def test_returns_expected_shape(self, seeded_client):
        """Endpoint returns feature adoption data."""
        resp = seeded_client.get(
            "/api/v1/analytics/feature-adoption",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "features" in data
        assert isinstance(data["features"], list)

    def test_feature_entry_fields(self, seeded_client):
        """Feature entries have name and usage count."""
        resp = seeded_client.get(
            "/api/v1/analytics/feature-adoption",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = resp.json()
        if data["features"]:
            entry = data["features"][0]
            assert "feature" in entry
            assert "usage_count" in entry


class TestRevenueByTier:
    """Tests for GET /api/v1/analytics/revenue-by-tier."""

    def test_returns_expected_shape(self, seeded_client):
        """Endpoint returns revenue-by-tier data."""
        resp = seeded_client.get(
            "/api/v1/analytics/revenue-by-tier",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tiers" in data
        assert isinstance(data["tiers"], list)

    def test_tier_entry_fields(self, seeded_client):
        """Tier entries have tier name and revenue."""
        resp = seeded_client.get(
            "/api/v1/analytics/revenue-by-tier",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = resp.json()
        if data["tiers"]:
            entry = data["tiers"][0]
            assert "tier" in entry
            assert "total_notional_usd" in entry
            assert "run_count" in entry

    def test_empty_db_returns_empty_tiers(self, client):
        """With no data, returns empty tiers list."""
        resp = client.get(
            "/api/v1/analytics/revenue-by-tier",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tiers"] == []
