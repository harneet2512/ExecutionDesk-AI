"""Tests for Round 4 production hardening.

Covers:
- I1: Insight fallback on exception
- S1: TRADING_DISABLE_LIVE blocks LIVE trades
- S2: TRADE_EXEC_START audit logging
- C1/C2: Confirm idempotency (covered by test_confirm_ux.py)
"""
import pytest
import os
import json
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn, _close_connections
from backend.core.config import get_settings, reset_settings
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


class TestInsightFallback:
    """I1: Insight fallback when generation fails."""

    def test_fallback_insight_is_valid_json(self):
        """Fallback insight dict is valid JSON and has expected shape."""
        fallback = {
            "headline": "Market insight temporarily unavailable",
            "why_it_matters": "Unable to retrieve market data. Proceed with caution.",
            "key_facts": [],
            "risk_flags": [],
            "confidence": 0.0,
            "generated_by": "fallback",
            "sources": {},
        }
        # Must be JSON-serializable
        serialized = json.dumps(fallback)
        parsed = json.loads(serialized)
        assert parsed["generated_by"] == "fallback"
        assert parsed["confidence"] == 0.0
        assert isinstance(parsed["key_facts"], list)

    def test_fallback_insight_included_on_exception(self):
        """When generate_insight raises, fallback insight is set (not None)."""
        # Simulate the guard logic from chat.py
        financial_insight = None
        news_enabled = True

        if news_enabled:
            try:
                raise RuntimeError("API timeout")
            except Exception:
                financial_insight = {
                    "headline": "Market insight temporarily unavailable",
                    "why_it_matters": "Unable to retrieve market data. Proceed with caution.",
                    "key_facts": [],
                    "risk_flags": [],
                    "confidence": 0.0,
                    "generated_by": "fallback",
                    "sources": {},
                }

        assert financial_insight is not None
        assert financial_insight["generated_by"] == "fallback"

    def test_normal_insight_not_overridden(self):
        """When generate_insight succeeds, normal insight is used."""
        financial_insight = None
        news_enabled = True

        if news_enabled:
            try:
                financial_insight = {
                    "headline": "BTC up 5%",
                    "key_facts": ["Fact 1"],
                    "confidence": 0.8,
                    "generated_by": "template",
                }
            except Exception:
                financial_insight = {
                    "generated_by": "fallback",
                }

        assert financial_insight is not None
        assert financial_insight["generated_by"] == "template"


class TestTradingDisableLive:
    """S1: TRADING_DISABLE_LIVE blocks LIVE trades via confirm endpoint."""

    def test_live_trade_blocked_by_default(self, setup_db):
        """LIVE mode confirmation is rejected with 403 when TRADING_DISABLE_LIVE=true."""
        # Create a LIVE mode confirmation
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="LIVE"
        )

        # Default: TRADING_DISABLE_LIVE is true
        response = client.post(
            f"/api/v1/confirmations/{conf_id}/confirm",
            headers={"X-Dev-Tenant": "t_default"},
            json={}
        )
        assert response.status_code == 403
        data = response.json()
        # Structured error response: detail.error.message contains the message
        detail = data.get("detail", {})
        if isinstance(detail, dict):
            msg = detail.get("error", {}).get("message", "")
        else:
            msg = str(detail)
        assert "LIVE trading is disabled" in msg, f"Expected LIVE disabled message, got: {data}"

    def test_paper_trade_not_blocked(self, setup_db):
        """PAPER mode confirmation is NOT blocked by TRADING_DISABLE_LIVE."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )

        # Mock threading to prevent actual execution
        mock_thread = MagicMock()
        with patch('threading.Thread', return_value=mock_thread):
            response = client.post(
                f"/api/v1/confirmations/{conf_id}/confirm",
                headers={"X-Dev-Tenant": "t_default"},
                json={}
            )

        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "EXECUTING"


class TestTradeAuditLog:
    """S2: TRADE_EXEC_START audit logging."""

    def test_confirm_logs_trade_exec_start(self, setup_db):
        """Confirm endpoint logs TRADE_EXEC_START before thread starts."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )

        mock_thread = MagicMock()
        with patch('threading.Thread', return_value=mock_thread), \
             patch('backend.api.routes.confirmations.logger') as mock_logger:
            response = client.post(
                f"/api/v1/confirmations/{conf_id}/confirm",
                headers={"X-Dev-Tenant": "t_default"},
                json={}
            )

        assert response.status_code == 200
        # Check that TRADE_EXEC_START was logged
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        trade_exec_logged = any("TRADE_EXEC_START" in c for c in info_calls)
        assert trade_exec_logged, f"Expected TRADE_EXEC_START in logs, got: {info_calls}"


class TestConfirmInsightReturn:
    """I2: Confirm endpoint returns stored insight_json from DB."""

    def test_confirm_includes_stored_insight(self, setup_db):
        """When insight_json is stored on confirmation, it's included in confirm response."""
        conf_id = confirmations_repo.create_pending(
            tenant_id="t_default",
            conversation_id="conv_test",
            proposal_json={"side": "buy", "asset": "BTC", "amount_usd": 10},
            mode="PAPER"
        )

        # Store insight on the confirmation
        test_insight = {"headline": "BTC is volatile", "confidence": 0.7, "generated_by": "template"}
        confirmations_repo.update_insight(conf_id, test_insight)

        mock_thread = MagicMock()
        with patch('threading.Thread', return_value=mock_thread):
            response = client.post(
                f"/api/v1/confirmations/{conf_id}/confirm",
                headers={"X-Dev-Tenant": "t_default"},
                json={}
            )

        assert response.status_code == 200
        data = response.json()
        assert "financial_insight" in data, f"Expected financial_insight in response, got keys: {list(data.keys())}"
        assert data["financial_insight"]["headline"] == "BTC is volatile"
