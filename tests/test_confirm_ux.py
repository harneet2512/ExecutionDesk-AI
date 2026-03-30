"""Tests for confirmation UX fixes.

Covers F9 (already-confirmed returns run_id) and cancel idempotency.
"""
import pytest
import os
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


class TestAlreadyConfirmedReturnsRunId:
    """F9: Double-confirm must return the existing run_id so frontend can track it."""

    def test_double_confirm_returns_run_id(self, setup_db):
        """Second confirm returns existing run_id, not just status text."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )

        # First confirm: creates a run
        r1 = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        assert r1.status_code == 200
        first_run_id = r1.json().get("run_id")
        assert first_run_id, "First confirm must return run_id"

        # Second confirm: should be idempotent and return existing run_id
        r2 = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["status"] == "CONFIRMED"
        assert data2.get("run_id") == first_run_id, \
            f"Double-confirm must return existing run_id={first_run_id}, got {data2.get('run_id')}"

    def test_double_confirm_has_confirmation_id(self, setup_db):
        """Double-confirm response includes the confirmation_id."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "sell", "asset": "ETH", "amount_usd": 5},
            mode="PAPER"
        )

        client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )

        r2 = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        assert r2.status_code == 200
        assert r2.json()["confirmation_id"] == conf_id


class TestCancelIdempotency:
    """Cancel should be idempotent and return meaningful status."""

    def test_double_cancel_returns_cancelled(self, setup_db):
        """Cancelling an already-cancelled confirmation returns CANCELLED status."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )

        # First cancel
        r1 = client.post(
            f"/api/v1/confirmations/{conf_id}/cancel",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        assert r1.status_code == 200
        assert r1.json()["status"] == "CANCELLED"

        # Second cancel: idempotent
        r2 = client.post(
            f"/api/v1/confirmations/{conf_id}/cancel",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["status"] == "CANCELLED"
        assert "already" in data2.get("message", "").lower()

    def test_cancel_after_confirm_returns_confirmed(self, setup_db):
        """Cancelling an already-confirmed trade returns CONFIRMED status, not error."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )

        # Confirm first
        r1 = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        assert r1.status_code == 200
        run_id = r1.json().get("run_id")

        # Try to cancel: should return already CONFIRMED with run_id
        r2 = client.post(
            f"/api/v1/confirmations/{conf_id}/cancel",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["status"] == "CONFIRMED"
        assert data2.get("run_id") == run_id, \
            "Cancel of confirmed trade should return the existing run_id"
