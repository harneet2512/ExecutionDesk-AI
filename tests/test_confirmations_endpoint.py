"""Tests for the confirmation endpoint with proper error handling."""
import pytest
import os
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn
from backend.core.config import get_settings
from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo

client = TestClient(app)
confirmations_repo = TradeConfirmationsRepo()

# Force test environment
os.environ["TEST_AUTH_BYPASS"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "test"


@pytest.fixture
def setup_db():
    """Setup clean database for each test."""
    from backend.db.connect import _close_connections
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
            "INSERT INTO conversations (conversation_id, tenant_id, title) VALUES (?, ?, ?)",
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


class TestConfirmationsEndpoint:
    """Test confirmation endpoint error handling."""
    
    def test_invalid_confirmation_id_format(self, setup_db):
        """Invalid confirmation ID format should return 400."""
        response = client.post(
            "/api/v1/confirmations/invalid_id/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        
        assert response.status_code == 400
        assert "invalid_confirmation_id_format" in response.text
    
    def test_confirmation_not_found(self, setup_db):
        """Non-existent confirmation should return 404."""
        response = client.post(
            "/api/v1/confirmations/conf_nonexistent123/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        
        assert response.status_code == 404
        assert "confirmation_not_found" in response.text
    
    def test_wrong_tenant(self, setup_db):
        """Confirmation with wrong tenant should return 404."""
        # Create confirmation for one tenant
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_other",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )
        
        # Try to confirm with different tenant
        response = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        
        assert response.status_code == 404
        assert "confirmation_not_found" in response.text
    
    def test_happy_path_confirm(self, setup_db):
        """Valid confirmation should return 200."""
        # Create a pending confirmation
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )
        
        # Confirm it
        response = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("run_id") is not None
        assert data.get("status") == "EXECUTING"
        assert data.get("confirmation_id") == conf_id
    
    def test_idempotent_confirm(self, setup_db):
        """Confirming an already confirmed trade should return 200 with status."""
        # Create and confirm
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )
        
        # First confirm
        client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        
        # Second confirm should be idempotent
        response = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "CONFIRMED"
        assert "already" in data.get("message", "").lower()


class TestConfirmationCancel:
    """Test cancel endpoint."""
    
    def test_cancel_pending(self, setup_db):
        """Cancelling a pending confirmation should work."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )
        
        response = client.post(
            f"/api/v1/confirmations/{conf_id}/cancel",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "CANCELLED"
    
    def test_cancel_not_found(self, setup_db):
        """Cancelling non-existent confirmation should return 404."""
        response = client.post(
            "/api/v1/confirmations/conf_nonexistent123/cancel",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        
        assert response.status_code == 404
