"""Smoke regression tests for critical trading platform flows.

These tests verify the fixes documented in FAULT_INVENTORY.md.
Run with: python -m pytest tests/test_smoke_regression.py -v
"""
import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock


def run_async(coro):
    """Helper to run async functions in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestF1InsightQuality:
    """F1: Insight must not contain UNKNOWN strings."""

    def test_fact_pack_no_unknown_worst_case(self):
        """With no price, no change, no headlines: no UNKNOWN in output."""
        from backend.services.pre_confirm_insight import build_fact_pack

        facts = build_fact_pack(
            "BTC", "BUY", 5.0, "CRYPTO",
            {"price": None, "change_24h_pct": None, "price_source": "none"},
            [], news_enabled=True, headlines_fetch_failed=True,
        )

        # Check key_facts for UNKNOWN
        for fact in facts["key_facts"]:
            assert "UNKNOWN" not in fact.upper(), f"UNKNOWN found in key_fact: {fact}"

        # Volatility should be None, not "UNKNOWN"
        assert facts["volatility"] is None or facts["volatility"] in ("HIGH", "MODERATE", "LOW")

    def test_template_insight_no_unknown(self):
        """Template insight never says Volatility UNKNOWN."""
        from backend.services.pre_confirm_insight import _build_template_insight

        facts = {
            "asset": "BTC", "side": "BUY", "notional_usd": 10.0,
            "change_24h_pct": None, "volatility": None, "price": None,
            "headlines": [], "risk_flags": [],
            "confidence": 0.0, "key_facts": [],
            "price_source": "none", "news_enabled": True,
            "live_allowed": True, "mode": "PAPER",
            "data_quality": {
                "missing_price": True,
                "missing_price_reason": "No data",
                "missing_change": True,
                "missing_change_reason": "No candles",
                "missing_headlines": True,
                "missing_headlines_reason": "No results",
                "stale_data": True,
                "headlines_fetch_failed": False,
            },
            "estimated_fees_usd": 0.06, "fee_impact_pct": 0.6,
        }
        result = _build_template_insight(facts, "req_smoke")
        combined = result["headline"] + " " + result["why_it_matters"]
        assert "UNKNOWN" not in combined


class TestF2LiveDisabledSafety:
    """F2: LIVE disabled returns structured 403 with remediation."""

    def test_live_disabled_error_has_remediation(self):
        """When LIVE is disabled, 403 error includes remediation field."""
        import os
        os.environ["TEST_AUTH_BYPASS"] = "true"
        from fastapi.testclient import TestClient
        from backend.api.main import app
        client = TestClient(app)

        with patch("backend.api.routes.confirmations.confirmations_repo") as mock_repo, \
             patch("backend.api.main.is_schema_healthy", return_value=True):
            mock_repo.get_by_id.return_value = {
                "id": "conf_smoke",
                "tenant_id": "t_default",
                "status": "PENDING",
                "mode": "LIVE",
                "proposal_json": '{"side":"BUY","asset":"BTC","amount_usd":10}',
                "expires_at": "2099-12-31T23:59:59",
                "run_id": None,
                "insight_json": None,
            }
            mock_repo.get_by_id_debug.return_value = None

            with patch("backend.core.config.get_settings") as mock_settings:
                settings = MagicMock()
                settings.trading_disable_live = True
                mock_settings.return_value = settings

                response = client.post(
                    "/api/v1/confirmations/conf_smoke/confirm",
                    json={},
                    headers={"X-Dev-Tenant": "t_default"},
                )

        assert response.status_code == 403
        data = response.json()
        detail = data.get("detail", data)
        error = detail.get("error", {})
        assert error.get("remediation"), "Missing remediation in LIVE_DISABLED error"


class TestF6DbSchemaOutdated:
    """F6: DB schema outdated returns structured 503."""

    def test_schema_outdated_has_error_code(self):
        """503 for schema issues includes error_code=DB_SCHEMA_OUTDATED."""
        import os
        os.environ["TEST_AUTH_BYPASS"] = "true"
        from fastapi.testclient import TestClient
        from backend.api.main import app
        client = TestClient(app)

        with patch("backend.api.main.is_schema_healthy", return_value=False):
            response = client.post(
                "/api/v1/confirmations/conf_schema/confirm",
                json={},
                headers={"X-Dev-Tenant": "t_default"},
            )

        assert response.status_code == 503
        data = response.json()
        detail = data.get("detail", data)
        error = detail.get("error", {})
        code = error.get("error_code") or error.get("code")
        assert code == "DB_SCHEMA_OUTDATED", f"Expected DB_SCHEMA_OUTDATED, got {code}"


class TestF7HeadlinesMissingTables:
    """F7: Headlines fetch gracefully handles missing news tables."""

    def test_missing_tables_returns_empty_headlines(self):
        """When news tables don't exist, _fetch_headlines returns ([], True)."""
        from backend.services.pre_confirm_insight import _fetch_headlines

        # Mock get_conn to raise "no such table"
        with patch("backend.services.pre_confirm_insight.get_conn") as mock_conn:
            mock_cursor = MagicMock()
            mock_cursor.execute.side_effect = Exception("no such table: news_items")
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.cursor.return_value = mock_cursor
            mock_conn.return_value = mock_ctx

            headlines, fetch_failed, _diag = _fetch_headlines("BTC")

        assert headlines == []
        assert fetch_failed is True


class TestCapabilitiesSmoke:
    """Capabilities endpoint returns valid structure."""

    def test_capabilities_all_fields(self):
        """GET /capabilities returns all required fields with correct types."""
        from backend.api.routes.ops import get_capabilities

        with patch("backend.api.routes.ops.get_settings") as mock_settings, \
             patch("backend.db.connect.get_schema_status") as mock_schema:
            settings = MagicMock()
            settings.is_live_execution_allowed.return_value = False
            mock_settings.return_value = settings
            mock_schema.return_value = {
                "schema_ok": True,
                "applied_migrations": [],
                "pending_migrations": [],
            }

            result = run_async(get_capabilities())

        assert isinstance(result["live_trading_enabled"], bool)
        assert isinstance(result["paper_trading_enabled"], bool)
        assert isinstance(result["db_ready"], bool)
        assert isinstance(result["version"], str)


class TestConfirmationInvalidId:
    """Invalid confirmation ID returns 400 with error envelope."""

    def test_bad_format_returns_400(self):
        """Confirmation ID not starting with conf_ returns 400."""
        import os
        os.environ["TEST_AUTH_BYPASS"] = "true"
        from fastapi.testclient import TestClient
        from backend.api.main import app
        client = TestClient(app)

        with patch("backend.api.main.is_schema_healthy", return_value=True):
            response = client.post(
                "/api/v1/confirmations/bad_id_123/confirm",
                json={},
                headers={"X-Dev-Tenant": "t_default"},
            )

        assert response.status_code == 400
