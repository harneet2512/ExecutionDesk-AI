"""Integration tests for scope guardrails - ensure out-of-scope queries don't create runs."""
import pytest
import os
from fastapi.testclient import TestClient

os.environ["TEST_AUTH_BYPASS"] = "true"

from backend.api.main import app
from backend.db.connect import get_conn

client = TestClient(app)


@pytest.fixture
def setup_db(test_db):
    """Use conftest's isolated test_db."""
    yield test_db


def get_run_count():
    """Get current count of runs in database."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM runs")
        row = cursor.fetchone()
        return row["count"] if row else 0


class TestGreetingGuardrails:
    """Test that greetings don't create runs."""

    def test_greeting_no_run_created(self, setup_db):
        """Greeting should return message-only response without creating run."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Hi"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert data["intent"] == "GREETING"
        assert "financial assistant" in data["content"].lower()
        assert "suggestions" in data

        assert get_run_count() == 0

    def test_hello_no_run(self, setup_db):
        """Hello should not create run."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Hello there!"},
        )

        assert response.status_code == 200
        assert response.json()["run_id"] is None
        assert get_run_count() == 0


class TestCapabilitiesGuardrails:
    """Test that capabilities queries don't create runs."""

    def test_capabilities_no_run_created(self, setup_db):
        """Capabilities query should return help without creating run."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "What can you do?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert data["intent"] == "CAPABILITIES_HELP"
        assert "Market Analysis" in data["content"]
        assert "Portfolio" in data["content"]
        assert "Trading" in data["content"]

        assert get_run_count() == 0

    def test_help_no_run(self, setup_db):
        """Help query should not create run."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "help"},
        )

        assert response.status_code == 200
        assert response.json()["run_id"] is None
        assert get_run_count() == 0


class TestOutOfScopeGuardrails:
    """Test that out-of-scope queries are blocked."""

    def test_politics_blocked(self, setup_db):
        """Political queries should be blocked."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Who is president of USA?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert data["intent"] == "OUT_OF_SCOPE"
        assert "can't help with that" in data["content"]
        assert "suggestions" in data

        assert get_run_count() == 0

    def test_geography_blocked(self, setup_db):
        """Geography queries should be blocked."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "What is the capital of France?"},
        )

        assert response.status_code == 200
        assert response.json()["run_id"] is None
        assert get_run_count() == 0

    def test_sports_blocked(self, setup_db):
        """Sports queries should be blocked."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Who won the NFL game?"},
        )

        assert response.status_code == 200
        assert response.json()["run_id"] is None
        assert get_run_count() == 0


class TestTradeExecutionAllowed:
    """Test that trade execution queries enter confirmation flow."""

    def test_buy_command_creates_confirmation(self, setup_db):
        """Buy command should enter confirmation flow (not create run directly)."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "Buy $10 of BTC in PAPER mode",
                "budget_usd": 10.0,
                "mode": "PAPER",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "TRADE_CONFIRMATION_PENDING"
        assert data.get("confirmation_id") is not None
        assert data["run_id"] is None
        assert get_run_count() == 0

    def test_most_profitable_creates_confirmation(self, setup_db):
        """Most profitable query should enter confirmation flow."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "Buy the most profitable crypto last 24h for $10",
                "budget_usd": 10.0,
                "mode": "PAPER",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "TRADE_CONFIRMATION_PENDING"
        assert data.get("confirmation_id") is not None
        assert data["run_id"] is None
        assert get_run_count() == 0


class TestFinanceAnalysisAllowed:
    """Test that finance analysis queries are allowed (but may not place orders)."""

    def test_analyze_volatility_allowed(self, setup_db):
        """Analysis query should be allowed."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "Analyze BTC volatility over last 24 hours",
                "mode": "PAPER",
            },
        )

        assert response.status_code == 200
        if response.json().get("run_id"):
            assert get_run_count() == 1


class TestAppDiagnosticsGuardrails:
    """Test that app diagnostics queries don't create runs."""

    def test_telemetry_query_no_run(self, setup_db):
        """Telemetry query should not create run."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Show me telemetry"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert data["intent"] == "APP_DIAGNOSTICS"

        assert get_run_count() == 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_text_blocked(self, setup_db):
        """Empty text should be blocked."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": ""},
        )

        assert response.status_code == 422

    def test_gibberish_blocked(self, setup_db):
        """Gibberish should be treated as out of scope."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "asdfghjkl xyzabc"},
        )

        assert response.status_code == 200
        assert response.json()["run_id"] is None
        assert get_run_count() == 0
