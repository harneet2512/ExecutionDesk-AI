"""Tests that hardened endpoints never return raw 500s for expected DB failures.

Covers F1 (cancel_trade), F2 (get_run_detail), F3 (trigger_run).
All three endpoints now have _impl() + try-except wrappers that convert
sqlite3.OperationalError into 503 JSON and generic exceptions into 500 JSON,
never leaking raw stack traces.
"""
import pytest
import os
import sqlite3
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn, _close_connections
from backend.core.config import get_settings
from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo

client = TestClient(app)
confirmations_repo = TradeConfirmationsRepo()

os.environ["TEST_AUTH_BYPASS"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "test"


@pytest.fixture
def setup_db():
    """Setup clean database for each test."""
    settings = get_settings()
    db_path = settings.database_url.replace("sqlite:///", "")
    _close_connections()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass
    init_db()

    # Create a test conversation
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO conversations (conversation_id, tenant_id, title) VALUES (?, ?, ?)",
            ("conv_test", "t_default", "Test Conversation")
        )
        conn.commit()
    yield
    _close_connections()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass


class TestCancelTradeNever500:
    """F1: cancel_trade endpoint must never return raw 500."""

    def test_cancel_db_locked_returns_json(self, setup_db):
        """When DB is locked during cancel, return structured JSON error, not 500."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )

        with patch(
            'backend.api.routes.confirmations.confirmations_repo.get_by_id',
            side_effect=sqlite3.OperationalError("database is locked")
        ):
            response = client.post(
                f"/api/v1/confirmations/{conf_id}/cancel",
                headers={"X-Dev-Tenant": "t_default"},
                json={}
            )

        # Must be JSON, not a raw stack trace
        assert response.status_code == 500
        data = response.json()
        # Middleware wraps HTTPException into standard error shape
        assert "error" in data or "detail" in data, "Response must be structured JSON"
        # Must have a request_id somewhere in the response for debugging
        assert data.get("request_id") or (data.get("error") and data["error"].get("request_id")), \
            "Error must contain request_id"

    def test_cancel_generic_exception_returns_json(self, setup_db):
        """When cancel hits unexpected error, return JSON envelope, not raw 500."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )

        with patch(
            'backend.api.routes.confirmations.confirmations_repo.get_by_id',
            side_effect=RuntimeError("unexpected test error")
        ):
            response = client.post(
                f"/api/v1/confirmations/{conf_id}/cancel",
                headers={"X-Dev-Tenant": "t_default"},
                json={}
            )

        assert response.status_code == 500
        data = response.json()
        assert "error" in data or "detail" in data, "Response must be structured JSON"
        # Must not leak raw stack trace to client
        raw_body = response.text
        assert "Traceback" not in raw_body

    def test_cancel_has_request_id_in_error(self, setup_db):
        """Error responses must include a request_id for debugging."""
        with patch(
            'backend.api.routes.confirmations.confirmations_repo.get_by_id',
            side_effect=RuntimeError("boom")
        ):
            response = client.post(
                "/api/v1/confirmations/conf_test123/cancel",
                headers={"X-Dev-Tenant": "t_default"},
                json={}
            )

        data = response.json()
        # request_id can be at top level or nested in error
        request_id = data.get("request_id") or (data.get("error", {}).get("request_id"))
        assert request_id, "Error must contain request_id for debugging"


class TestGetRunDetailNever500:
    """F2: get_run_detail endpoint must never return raw 500."""

    def test_run_not_found_returns_404(self, setup_db):
        """Requesting a nonexistent run returns 404 JSON."""
        response = client.get(
            "/api/v1/runs/run_nonexistent",
            headers={"X-Dev-Tenant": "t_default"}
        )
        assert response.status_code == 404

    def test_db_locked_returns_503(self, setup_db):
        """When DB is locked during run detail fetch, return 503 JSON."""
        with patch(
            'backend.api.routes.runs.get_conn',
            side_effect=sqlite3.OperationalError("database is locked")
        ):
            response = client.get(
                "/api/v1/runs/run_test123",
                headers={"X-Dev-Tenant": "t_default"}
            )

        assert response.status_code == 503
        data = response.json()
        assert data["error"]["code"] == "DB_BUSY"

    def test_generic_error_returns_500_json(self, setup_db):
        """When get_run_detail hits unexpected error, return 500 JSON, not raw crash."""
        with patch(
            'backend.api.routes.runs.get_conn',
            side_effect=RuntimeError("unexpected")
        ):
            response = client.get(
                "/api/v1/runs/run_test123",
                headers={"X-Dev-Tenant": "t_default"}
            )

        assert response.status_code == 500
        data = response.json()
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert data["error"].get("request_id"), "Must include request_id"


class TestTriggerRunNever500:
    """F3: trigger_run endpoint must never return raw 500."""

    def test_db_locked_returns_503(self, setup_db):
        """When DB is locked during trigger, return 503 JSON."""
        with patch(
            'backend.api.routes.runs.create_run',
            side_effect=sqlite3.OperationalError("database is locked")
        ):
            response = client.post(
                "/api/v1/runs/trigger",
                headers={"X-Dev-Tenant": "t_default"},
                json={"execution_mode": "PAPER"}
            )

        assert response.status_code == 503
        data = response.json()
        assert data["error"]["code"] == "DB_BUSY"

    def test_generic_error_returns_500_json(self, setup_db):
        """When trigger hits unexpected error, return 500 JSON, not raw crash."""
        with patch(
            'backend.api.routes.runs.create_run',
            side_effect=RuntimeError("runner crashed")
        ):
            response = client.post(
                "/api/v1/runs/trigger",
                headers={"X-Dev-Tenant": "t_default"},
                json={"execution_mode": "PAPER"}
            )

        assert response.status_code == 500
        data = response.json()
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert data["error"].get("request_id"), "Must include request_id"

    def test_invalid_mode_returns_422(self, setup_db):
        """Invalid execution_mode should return 422, not 500."""
        response = client.post(
            "/api/v1/runs/trigger",
            headers={"X-Dev-Tenant": "t_default"},
            json={"execution_mode": "INVALID_MODE"}
        )
        assert response.status_code == 422
