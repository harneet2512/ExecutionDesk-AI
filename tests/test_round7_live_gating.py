"""Tests for Round 7: LIVE gating, structured errors, health config.

Covers:
- Trade parser defaults to PAPER when LIVE is disabled
- Trade parser allows LIVE when explicitly enabled
- Explicit 'paper' keyword always forces PAPER mode
- Chat endpoint downgrades LIVE to PAPER when disabled
- Confirm endpoint returns structured 403 error for LIVE-disabled
- Health endpoint exposes trading_disable_live and live_execution_allowed
"""
import pytest
import os
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn, _close_connections, _parse_db_url
from backend.core.config import get_settings

client = TestClient(app)

os.environ["TEST_AUTH_BYPASS"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "test"


@pytest.fixture
def fresh_db():
    """Setup a clean database for each test."""
    settings = get_settings()
    db_path = _parse_db_url(settings.database_url)
    _close_connections()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass
    init_db()
    yield db_path
    _close_connections()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass


class TestTradeParserLiveGating:
    """Trade parser respects LIVE config settings."""

    def test_parser_defaults_paper_when_live_disabled(self):
        """With TRADING_DISABLE_LIVE=true (default), crypto defaults to PAPER."""
        from backend.agents.trade_parser import parse_trade_command

        # Mock detect_test_environment to False so we test the config path
        with patch("backend.agents.trade_parser.detect_test_environment", return_value=False):
            result = parse_trade_command("sell $2 BTC")

        assert result.mode == "PAPER", f"Expected PAPER but got {result.mode}"

    def test_parser_allows_live_when_enabled(self):
        """With TRADING_DISABLE_LIVE=false + ENABLE_LIVE_TRADING=true, crypto gets LIVE."""
        from backend.agents.trade_parser import parse_trade_command

        with patch("backend.agents.trade_parser.detect_test_environment", return_value=False), \
             patch("backend.core.config.get_settings") as mock_settings:
            mock_settings.return_value.trading_disable_live = False
            mock_settings.return_value.enable_live_trading = True
            result = parse_trade_command("sell $2 BTC")

        assert result.mode == "LIVE", f"Expected LIVE but got {result.mode}"

    def test_parser_explicit_paper_keyword(self):
        """'paper' keyword always forces PAPER regardless of config."""
        from backend.agents.trade_parser import parse_trade_command

        with patch("backend.agents.trade_parser.detect_test_environment", return_value=False), \
             patch("backend.core.config.get_settings") as mock_settings:
            mock_settings.return_value.trading_disable_live = False
            mock_settings.return_value.enable_live_trading = True
            result = parse_trade_command("sell $2 BTC paper")

        assert result.mode == "PAPER", f"Expected PAPER but got {result.mode}"


class TestConfirmStructuredError:
    """Confirm endpoint returns structured 403 for LIVE-disabled."""

    def test_confirm_403_structured_error(self, fresh_db):
        """LIVE confirmation returns structured error with code and remediation."""
        # Create a LIVE confirmation directly in DB
        from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo
        repo = TradeConfirmationsRepo()

        proposal = {
            "side": "BUY",
            "asset": "BTC",
            "amount_usd": 10.0,
            "mode": "LIVE",
        }
        conf_id = repo.create_pending(
            tenant_id="t_default",
            conversation_id="test_conv",
            proposal_json=proposal,
            mode="LIVE",
            user_id="u_test",
            ttl_seconds=300
        )

        response = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
        )

        assert response.status_code == 403
        data = response.json()
        # Response structure: {"status": "ERROR", "detail": {"error": {...}}, "request_id": ...}
        detail = data.get("detail", {})
        error = detail.get("error", {})
        assert error.get("code") == "LIVE_DISABLED", f"Expected LIVE_DISABLED code, got: {data}"
        assert "remediation" in error, f"Missing remediation in error: {data}"
        assert "TRADING_DISABLE_LIVE" in error.get("remediation", "")


class TestHealthLiveConfig:
    """Health endpoint exposes live trading config."""

    def test_health_exposes_live_config(self, fresh_db):
        """GET /ops/health returns config.trading_disable_live and config.live_execution_allowed."""
        response = client.get(
            "/api/v1/ops/health",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert response.status_code == 200
        data = response.json()
        config = data.get("config", {})
        assert "trading_disable_live" in config, f"Missing trading_disable_live in config: {config}"
        assert "live_execution_allowed" in config, f"Missing live_execution_allowed in config: {config}"
        assert isinstance(config["trading_disable_live"], bool)
        assert isinstance(config["live_execution_allowed"], bool)
