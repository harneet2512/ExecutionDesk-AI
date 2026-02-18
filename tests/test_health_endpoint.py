"""Tests for the /health and /ops/capabilities endpoints.

Verifies that:
- /health returns structured health status
- /ops/capabilities returns correct feature flags
- Schema health, migration status, and LIVE trading flag are accurate
"""
import pytest
import os
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


@pytest.fixture(scope="function")
def setup_db():
    """Create an isolated test database."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_health.db")

    old_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["TEST_DATABASE_URL"] = f"sqlite:///{db_path}"

    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass

    try:
        from backend.db.connect import init_db, _close_connections
        _close_connections()
        init_db()
        yield db_path
    finally:
        from backend.db.connect import _close_connections
        _close_connections()
        if old_db_url:
            os.environ["DATABASE_URL"] = old_db_url
        else:
            os.environ.pop("DATABASE_URL", None)
        os.environ.pop("TEST_DATABASE_URL", None)
        try:
            from backend.core.config import reset_settings
            reset_settings()
        except ImportError:
            pass
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


class TestRootHealth:
    """Tests for GET /health."""

    def test_health_returns_structured_response(self, setup_db):
        """Root /health must return structured health fields."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()

        # Required fields
        assert "ok" in data
        assert "db_ready" in data
        assert "schema_ok" in data
        assert "migrations_needed" in data
        assert "status" in data

    def test_health_ok_when_db_healthy(self, setup_db):
        """When all migrations applied, health must return ok=True."""
        response = client.get("/health")
        data = response.json()

        assert data["ok"] is True
        assert data["db_ready"] is True
        assert data["schema_ok"] is True
        assert data["status"] == "ok"

    def test_health_includes_live_trading_flag(self, setup_db):
        """Health must report live_trading_enabled status."""
        response = client.get("/health")
        data = response.json()
        assert "live_trading_enabled" in data
        assert isinstance(data["live_trading_enabled"], bool)


class TestOpsHealth:
    """Tests for GET /api/v1/ops/health."""

    def test_ops_health_returns_deep_check(self, setup_db):
        """Ops health must include migration details and provider config."""
        response = client.get(
            "/api/v1/ops/health",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert response.status_code == 200
        data = response.json()

        assert "ok" in data
        assert "db_ok" in data
        assert "schema_ok" in data
        assert "migrations" in data

    def test_ops_health_ok_after_init(self, setup_db):
        """After init_db, ops health must report ok=True."""
        response = client.get(
            "/api/v1/ops/health",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = response.json()
        assert data["ok"] is True


class TestCapabilities:
    """Tests for GET /api/v1/ops/capabilities."""

    def test_capabilities_returns_feature_flags(self, setup_db):
        """Capabilities must return all expected feature flags."""
        response = client.get(
            "/api/v1/ops/capabilities",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert response.status_code == 200
        data = response.json()

        assert "live_trading_enabled" in data
        assert "paper_trading_enabled" in data
        assert "news_enabled" in data
        assert "db_ready" in data
        assert "version" in data

    def test_capabilities_db_ready_after_init(self, setup_db):
        """After init_db, capabilities must report db_ready=True."""
        response = client.get(
            "/api/v1/ops/capabilities",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = response.json()
        assert data["db_ready"] is True

    def test_capabilities_includes_provider_status(self, setup_db):
        """Capabilities must include news_provider_status and market_data_provider."""
        response = client.get(
            "/api/v1/ops/capabilities",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = response.json()
        assert "news_provider_status" in data
        assert "market_data_provider" in data

    def test_capabilities_live_disabled_by_default(self, setup_db):
        """Default config should have LIVE trading disabled."""
        response = client.get(
            "/api/v1/ops/capabilities",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = response.json()
        # Default config has trading_disable_live=True
        assert data["live_trading_enabled"] is False
