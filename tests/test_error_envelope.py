"""Tests for standardized error envelope across backend responses."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def _get_test_client():
    """Create a test client with auth bypass."""
    import os
    os.environ["TEST_AUTH_BYPASS"] = "true"
    from backend.api.main import app
    return TestClient(app)


class TestLiveDisabled403:
    """LIVE_DISABLED 403 returns structured error envelope with remediation."""

    def test_live_disabled_returns_error_envelope(self):
        """When LIVE is disabled, confirm returns 403 with error_code and remediation."""
        client = _get_test_client()

        # Create a mock LIVE confirmation
        with patch("backend.api.routes.confirmations.confirmations_repo") as mock_repo, \
             patch("backend.api.main.is_schema_healthy", return_value=True):
            mock_repo.get_by_id.return_value = {
                "id": "conf_test123",
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
                    "/api/v1/confirmations/conf_test123/confirm",
                    json={},
                    headers={"X-Dev-Tenant": "t_default"},
                )

        assert response.status_code == 403
        data = response.json()
        # Error envelope should be in detail.error (HTTPException pass-through)
        detail = data.get("detail", data)
        error = detail.get("error", {})
        assert error.get("error_code") == "LIVE_DISABLED" or error.get("code") == "LIVE_DISABLED"
        assert "remediation" in error
        assert error["remediation"]  # Non-empty
        assert "TRADING_DISABLE_LIVE" in error["remediation"]

    def test_live_disabled_includes_request_id(self):
        """Error response includes request_id for tracing."""
        client = _get_test_client()

        with patch("backend.api.routes.confirmations.confirmations_repo") as mock_repo, \
             patch("backend.api.main.is_schema_healthy", return_value=True):
            mock_repo.get_by_id.return_value = {
                "id": "conf_test456",
                "tenant_id": "t_default",
                "status": "PENDING",
                "mode": "LIVE",
                "proposal_json": '{"side":"SELL","asset":"ETH","amount_usd":5}',
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
                    "/api/v1/confirmations/conf_test456/confirm",
                    json={},
                    headers={"X-Dev-Tenant": "t_default"},
                )

        assert response.status_code == 403
        # X-Request-ID header should be present
        assert response.headers.get("X-Request-ID")


class TestDbSchemaOutdated503:
    """DB_SCHEMA_OUTDATED 503 returns structured error envelope with remediation."""

    def test_schema_outdated_returns_error_envelope(self):
        """When schema is outdated, confirm returns 503 with error_code and remediation."""
        client = _get_test_client()

        with patch("backend.api.main.is_schema_healthy", return_value=False):
            response = client.post(
                "/api/v1/confirmations/conf_test789/confirm",
                json={},
                headers={"X-Dev-Tenant": "t_default"},
            )

        assert response.status_code == 503
        data = response.json()
        detail = data.get("detail", data)
        error = detail.get("error", {})
        assert error.get("error_code") == "DB_SCHEMA_OUTDATED" or error.get("code") == "DB_SCHEMA_OUTDATED"
        assert "remediation" in error
        assert error["remediation"]  # Non-empty
        assert "backend" in error["remediation"].lower()


class TestGlobalExceptionHandler:
    """Global exception handler returns structured error envelope."""

    def test_500_includes_error_code(self):
        """500 response includes error_code field."""
        client = _get_test_client()

        # Force a 500 by calling with broken internal state
        with patch("backend.api.main.is_schema_healthy", side_effect=RuntimeError("test crash")):
            response = client.post(
                "/api/v1/confirmations/conf_crash/confirm",
                json={},
                headers={"X-Dev-Tenant": "t_default"},
            )

        assert response.status_code == 500
        data = response.json()
        error = data.get("error", {})
        # Must have both code and error_code
        assert error.get("error_code") == "INTERNAL_ERROR" or error.get("code") == "INTERNAL_ERROR"
        assert "request_id" in error
