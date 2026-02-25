"""Tests for message-only response guardrails."""
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn
import os

client = TestClient(app)
os.environ["TEST_AUTH_BYPASS"] = "true"


@pytest.fixture
def setup_db():
    """Setup clean database for each test."""
    from backend.core.config import get_settings
    settings = get_settings()
    db_path = settings.database_url.replace("sqlite:///", "")
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()
    yield
    if os.path.exists(db_path):
        os.remove(db_path)


def get_run_count():
    """Get current count of runs in database."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM runs")
        row = cursor.fetchone()
        return row["count"] if row else 0


class TestMessageOnlyResponses:
    """Test that message-only responses don't create runs and return proper format."""
    
    def test_greeting_message_only(self, setup_db):
        """Greeting should return message-only response with status COMPLETED."""
        initial_count = get_run_count()
        
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Hi"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify message-only response format
        assert data["run_id"] is None
        assert data["intent"] == "GREETING"
        assert data["status"] == "COMPLETED"
        assert "content" in data
        assert "financial assistant" in data["content"].lower()
        assert "suggestions" in data
        assert len(data["suggestions"]) >= 3
        
        # Verify no run created
        assert get_run_count() == initial_count
    
    def test_out_of_scope_message_only(self, setup_db):
        """Out-of-scope query should return refusal with status COMPLETED."""
        initial_count = get_run_count()
        
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Who is president of USA?"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify message-only response format
        assert data["run_id"] is None
        assert data["intent"] == "OUT_OF_SCOPE"
        assert data["status"] == "COMPLETED"
        assert "can't help with that" in data["content"]
        assert "suggestions" in data
        
        # Verify no run created
        assert get_run_count() == initial_count
    
    def test_capabilities_message_only(self, setup_db):
        """Capabilities query should return help with status COMPLETED."""
        initial_count = get_run_count()
        
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "What can you do?"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify message-only response format
        assert data["run_id"] is None
        assert data["intent"] == "CAPABILITIES_HELP"
        assert data["status"] == "COMPLETED"
        assert "Market Analysis" in data["content"]
        assert "Portfolio" in data["content"]
        
        # Verify no run created
        assert get_run_count() == initial_count
    
    def test_trade_execution_creates_run(self, setup_db):
        """Trade execution should produce a confirmation prompt (not message-only)."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "Buy $10 of BTC in PAPER mode",
                "budget_usd": 10.0,
                "mode": "PAPER"
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["intent"] in ("TRADE_CONFIRMATION_PENDING", "TRADE_EXECUTION")
        assert "confirm" in data["content"].lower() or "blocked" in data["content"].lower()
