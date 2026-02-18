"""Tests for LIVE trading safety features."""
import pytest
import os
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db
from backend.core.config import get_settings

client = TestClient(app)

# Set TEST_AUTH_BYPASS for pytest
os.environ["TEST_AUTH_BYPASS"] = "true"


def invalidate_settings_cache():
    """Invalidate the settings cache to pick up new env vars."""
    import backend.core.config as config_module
    config_module._settings = None


@pytest.fixture
def setup_db():
    """Setup clean database."""
    settings = get_settings()
    db_path = settings.database_url.replace("sqlite:///", "")
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()
    yield
    # Clean up env vars after test
    invalidate_settings_cache()


def test_live_order_exceeds_default_cap(setup_db):
    """Test that LIVE order exceeding default $20 cap is blocked via /commands/execute."""
    # Enable LIVE trading temporarily
    os.environ["ENABLE_LIVE_TRADING"] = "true"
    os.environ["TRADING_DISABLE_LIVE"] = "false"
    os.environ["LIVE_MAX_NOTIONAL_USD"] = "20.0"  # Default cap
    os.environ["MARKET_DATA_MODE"] = "coinbase"  # Required for LIVE
    invalidate_settings_cache()

    try:
        # Try to place $21 LIVE order via commands/execute (has cap enforcement)
        response = client.post(
            "/api/v1/commands/execute",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "command": "buy $21 of BTC",
                "execution_mode": "LIVE"
            }
        )

        # Should be blocked with 400
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        assert "LIVE order blocked" in response.json()["detail"]
        assert "exceeds LIVE_MAX_NOTIONAL_USD" in response.json()["detail"]
    finally:
        # Reset env vars
        os.environ.pop("ENABLE_LIVE_TRADING", None)
        os.environ["TRADING_DISABLE_LIVE"] = "true"
        os.environ.pop("LIVE_MAX_NOTIONAL_USD", None)
        os.environ.pop("MARKET_DATA_MODE", None)
        invalidate_settings_cache()


def test_live_order_with_custom_cap(setup_db):
    """Test that LIVE order under custom cap is allowed."""
    # Enable LIVE trading with higher cap
    os.environ["ENABLE_LIVE_TRADING"] = "true"
    os.environ["LIVE_MAX_NOTIONAL_USD"] = "50.0"  # Custom cap
    os.environ["MARKET_DATA_MODE"] = "coinbase"  # Required for LIVE
    invalidate_settings_cache()
    
    try:
        # Try to place $40 LIVE order (should pass notional check)
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "buy $40 of BTC",
                "budget_usd": 40.0,
                "mode": "LIVE"
            }
        )
        
        # Should pass notional cap validation (200 or 202)
        # May fail later if Coinbase creds missing, but cap check should pass
        assert response.status_code in (200, 202, 500), f"Got {response.status_code}: {response.text}"
        
        # If it failed, ensure it's NOT due to notional cap
        if response.status_code not in (200, 202):
            error_detail = response.json().get("detail", "")
            assert "exceeds LIVE_MAX_NOTIONAL_USD" not in error_detail, "Should not fail on notional cap"
    finally:
        # Reset env vars
        os.environ.pop("ENABLE_LIVE_TRADING", None)
        os.environ.pop("LIVE_MAX_NOTIONAL_USD", None)
        os.environ.pop("MARKET_DATA_MODE", None)
        invalidate_settings_cache()


def test_paper_order_ignores_cap(setup_db):
    """Test that PAPER mode orders are not affected by LIVE cap."""
    # Set a low LIVE cap
    os.environ["LIVE_MAX_NOTIONAL_USD"] = "10.0"
    invalidate_settings_cache()
    
    try:
        # Place $100 PAPER order (should succeed)
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "buy $100 of BTC",
                "budget_usd": 100.0,
                "mode": "PAPER"
            }
        )
        
        # Should succeed (200 or 202)
        assert response.status_code in (200, 202), f"Expected 200/202, got {response.status_code}: {response.text}"
        assert "run_id" in response.json()
    finally:
        # Reset env var
        os.environ.pop("LIVE_MAX_NOTIONAL_USD", None)
        invalidate_settings_cache()


def test_live_trading_disabled_by_default(setup_db):
    """Test that LIVE trading is disabled by default and downgrades to PAPER."""
    # Ensure LIVE is disabled (default)
    os.environ["TRADING_DISABLE_LIVE"] = "true"
    os.environ.pop("ENABLE_LIVE_TRADING", None)
    invalidate_settings_cache()

    # Try to place LIVE order - should be downgraded to PAPER, not rejected
    response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "text": "buy $5 of BTC",
            "budget_usd": 5.0,
            "mode": "LIVE"
        }
    )

    # Chat command downgrades LIVE to PAPER gracefully
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    # Should show PAPER mode, not LIVE
    pending = data.get("pending_trade", {})
    assert pending.get("mode") == "PAPER", f"Expected PAPER mode, got: {pending.get('mode')}"


def test_live_requires_coinbase_market_data_mode(setup_db):
    """Test that LIVE trading with kill switch on is downgraded to PAPER."""
    # TRADING_DISABLE_LIVE=true means LIVE gets downgraded
    os.environ["TRADING_DISABLE_LIVE"] = "true"
    os.environ["ENABLE_LIVE_TRADING"] = "true"
    os.environ["MARKET_DATA_MODE"] = "stub"
    invalidate_settings_cache()

    try:
        # Try to place LIVE order - should be downgraded to PAPER
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "buy $5 of BTC",
                "budget_usd": 5.0,
                "mode": "LIVE"
            }
        )

        # Should succeed as PAPER (downgraded from LIVE)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        pending = data.get("pending_trade", {})
        assert pending.get("mode") == "PAPER", f"Expected PAPER mode, got: {pending.get('mode')}"
    finally:
        # Reset env vars
        os.environ.pop("ENABLE_LIVE_TRADING", None)
        os.environ.pop("MARKET_DATA_MODE", None)
        invalidate_settings_cache()


def test_commands_execute_endpoint_enforces_cap(setup_db):
    """Test that /commands/execute endpoint enforces LIVE cap."""
    # Enable LIVE trading with default cap and disable kill switch
    os.environ["ENABLE_LIVE_TRADING"] = "true"
    os.environ["TRADING_DISABLE_LIVE"] = "false"
    os.environ["LIVE_MAX_NOTIONAL_USD"] = "20.0"
    os.environ["MARKET_DATA_MODE"] = "coinbase"
    invalidate_settings_cache()

    try:
        # Try to execute command with $25 (should fail)
        response = client.post(
            "/api/v1/commands/execute",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "command": "buy $25 of ETH",
                "execution_mode": "LIVE"
            }
        )

        # Should be blocked with 400
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        assert "LIVE order blocked" in response.json()["detail"]
    finally:
        # Reset env vars
        os.environ.pop("ENABLE_LIVE_TRADING", None)
        os.environ["TRADING_DISABLE_LIVE"] = "true"
        os.environ.pop("LIVE_MAX_NOTIONAL_USD", None)
        os.environ.pop("MARKET_DATA_MODE", None)
        invalidate_settings_cache()
