"""Tests for natural language configuration and confirmation flow."""
import pytest
import os
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn
from backend.core.config import get_settings
from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo

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
        """Buy without amount should not create a run."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy BTC", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
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
        content_lower = data["content"].lower()
        assert "confirm" in content_lower
        assert "cancel" in content_lower or "abort" in content_lower
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
        """CONFIRM without pending trade should indicate no pending trade."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "CONFIRM", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] is None
        content_lower = data["content"].lower()
        assert "no pending trade" in content_lower or "expired" in content_lower


class TestDefaultMode:
    """Test default execution mode (PAPER in tests, LIVE in runtime)."""
    
    def test_default_mode_is_paper_in_tests(self, setup_db):
        """In pytest, default mode should be PAPER."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy $10 BTC", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        pending = data.get("pending_trade", {})
        assert pending.get("mode") == "PAPER"


class TestNewsToggleAndEvidence:
    """Verify news toggle propagation and news evidence artifact emission."""

    def test_news_toggle_propagates_to_run_and_response(self, setup_db):
        repo = TradeConfirmationsRepo()
        conf_id = repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={
                "side": "BUY",
                "asset": "BTC",
                "amount_usd": 10.0,
                "mode": "PAPER",
                "asset_class": "CRYPTO",
                "news_enabled": True,
                "lookback_hours": 24,
                "is_most_profitable": False,
                "locked_product_id": "BTC-USD",
            },
            mode="PAPER",
            user_id="u_test",
            ttl_seconds=300,
        )
        repo.update_insight(conf_id, {
            "headline": "BTC insight",
            "why_it_matters": "test",
            "key_facts": [],
            "risk_flags": ["news_empty"],
            "confidence": 0.5,
            "sources": {"price_source": "coinbase", "headlines": []},
            "generated_by": "template",
            "news_outcome": {"queries": ["Bitcoin", "BTC", "BTC-USD"], "lookback": "24h", "sources": ["RSS", "GDELT"], "status": "empty", "reason": "No relevant news found"},
        })
        with patch("threading.Thread") as mock_thread:
            response = client.post(
                f"/api/v1/confirmations/{conf_id}/confirm",
                headers={"X-Dev-Tenant": "t_default"},
                json={},
            )
            assert mock_thread.called
        assert response.status_code == 200
        data = response.json()
        assert data.get("news_enabled") is True
        assert data.get("financial_insight") is not None
        run_id = data["run_id"]
        assert run_id is not None

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT news_enabled FROM runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            assert row is not None
            assert int(row["news_enabled"]) == 1

    def test_confirm_emits_news_evidence_artifact(self, setup_db):
        repo = TradeConfirmationsRepo()
        conf_id = repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={
                "side": "BUY",
                "asset": "BTC",
                "amount_usd": 10.0,
                "mode": "PAPER",
                "asset_class": "CRYPTO",
                "news_enabled": True,
                "lookback_hours": 24,
                "is_most_profitable": False,
                "locked_product_id": "BTC-USD",
            },
            mode="PAPER",
            user_id="u_test",
            ttl_seconds=300,
        )
        repo.update_insight(conf_id, {
            "headline": "BTC insight",
            "why_it_matters": "test",
            "key_facts": [],
            "risk_flags": [],
            "confidence": 0.7,
            "sources": {"price_source": "coinbase", "headlines": []},
            "generated_by": "template",
            "news_outcome": {"queries": ["Bitcoin", "BTC", "BTC-USD"], "lookback": "24h", "sources": ["RSS", "GDELT"], "status": "empty", "reason": "No relevant news found"},
        })

        with patch("threading.Thread") as mock_thread:
            confirm_resp = client.post(
                f"/api/v1/confirmations/{conf_id}/confirm",
                headers={"X-Dev-Tenant": "t_default"},
                json={},
            )
            assert mock_thread.called
        assert confirm_resp.status_code == 200
        run_id = confirm_resp.json().get("run_id")
        assert run_id

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'news_evidence' LIMIT 1",
                (run_id,)
            )
            row = cursor.fetchone()
            assert row is not None
            artifact = json.loads(row["artifact_json"])
            assert artifact.get("lookback") == "24h"
            assert artifact.get("sources") == ["RSS", "GDELT"]
            assert artifact.get("status") in ("ok", "empty", "error")
    
    def test_explicit_live_still_paper_in_tests(self, setup_db):
        """Even if user says 'live', tests should force PAPER."""
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={"text": "Buy $10 BTC live", "conversation_id": "conv_test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        pending = data.get("pending_trade", {})
        assert pending.get("mode") == "PAPER"


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
