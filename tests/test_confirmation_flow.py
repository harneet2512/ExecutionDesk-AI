"""Tests for natural language configuration and confirmation flow."""
import pytest
import os
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn
from backend.core.config import get_settings

client = TestClient(app)

# Force test environment
os.environ["TEST_AUTH_BYPASS"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "test"


@pytest.fixture
def setup_db():
    """Setup clean database for each test."""
    settings = get_settings()
    db_path = settings.database_url.replace("sqlite:///", "")
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()
    
    # Create a test conversation
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversations (conversation_id, tenant_id, title) VALUES (?, ?, ?)",
            ("conv_test", "t_default", "Test Conversation")
        )
        conn.commit()
    
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


class TestNaturalLanguageParsing:
    """Test natural language parsing and missing parameter detection."""
    
    def test_buy_without_amount(self, setup_db):
        """Buy without amount should ask for amount."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy BTC", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert "How much" in data["content"]
        assert data["intent"] == "TRADE_EXECUTION_INCOMPLETE"
        assert get_run_count() == 0
    
    def test_buy_with_amount_requires_confirmation(self, setup_db):
        """Buy with amount should require confirmation."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy $10 BTC", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert "CONFIRMATION" in data["content"]
        assert "CONFIRM" in data["content"]
        assert "CANCEL" in data["content"]
        assert data["intent"] == "TRADE_CONFIRMATION_PENDING"
        assert get_run_count() == 0


class TestConfirmationFlow:
    """Test CONFIRM/CANCEL flow."""
    
    def test_confirm_executes_trade(self, setup_db):
        """CONFIRM should execute pending trade."""
        # First, request trade
        client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy $10 BTC", "conversation_id": "conv_test"}
        )
        
        # Then confirm
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "CONFIRM", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is not None
        assert "confirmed" in data["content"].lower()
        assert get_run_count() == 1
    
    def test_cancel_aborts_trade(self, setup_db):
        """CANCEL should abort pending trade."""
        # First, request trade
        client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy $10 BTC", "conversation_id": "conv_test"}
        )
        
        # Then cancel
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "CANCEL", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert "cancelled" in data["content"].lower()
        assert get_run_count() == 0
    
    def test_confirm_without_pending_trade(self, setup_db):
        """CONFIRM without pending trade should return expired message."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "CONFIRM", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert "expired" in data["content"].lower()


class TestDefaultMode:
    """Test default execution mode (PAPER in tests, LIVE in runtime)."""
    
    def test_default_mode_is_paper_in_tests(self, setup_db):
        """In pytest, default mode should be PAPER."""
        # Request trade
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy $10 BTC", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        # Check confirmation message mentions PAPER
        assert "PAPER" in data["content"]
    
    def test_explicit_live_still_paper_in_tests(self, setup_db):
        """Even if user says 'live', tests should force PAPER."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy $10 BTC live", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        # Should still be PAPER in tests
        assert "PAPER" in data["content"]


class TestMessageOnlyIntents:
    """Test that message-only intents still work."""
    
    def test_greeting_no_run(self, setup_db):
        """Greeting should not create run."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Hi", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert data["intent"] == "GREETING"
        assert get_run_count() == 0
    
    def test_out_of_scope_no_run(self, setup_db):
        """Out-of-scope should not create run."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Who is president?", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        assert data["intent"] == "OUT_OF_SCOPE"
        assert get_run_count() == 0
