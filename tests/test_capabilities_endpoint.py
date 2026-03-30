"""Tests for GET /api/v1/ops/capabilities endpoint."""
import pytest
from unittest.mock import patch, MagicMock


class TestCapabilitiesEndpoint:
    """Capabilities endpoint returns correct feature flags."""

    def test_returns_all_required_fields(self):
        """Capabilities response includes all required keys."""
        from backend.api.routes.ops import get_capabilities
        import asyncio

        with patch("backend.api.routes.ops.get_settings") as mock_settings, \
             patch("backend.db.connect.get_schema_status") as mock_schema:
            settings = MagicMock()
            settings.is_live_execution_allowed.return_value = False
            mock_settings.return_value = settings
            mock_schema.return_value = {
                "schema_ok": True,
                "applied_migrations": ["001_init"],
                "pending_migrations": [],
            }

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(get_capabilities())
            finally:
                loop.close()

        required_keys = [
            "live_trading_enabled",
            "paper_trading_enabled",
            "insights_enabled",
            "news_enabled",
            "db_ready",
            "remediation",
            "version",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_db_ready_true_when_schema_ok(self):
        """db_ready=true when all migrations applied."""
        from backend.api.routes.ops import get_capabilities
        import asyncio

        with patch("backend.api.routes.ops.get_settings") as mock_settings, \
             patch("backend.db.connect.get_schema_status") as mock_schema:
            settings = MagicMock()
            settings.is_live_execution_allowed.return_value = True
            mock_settings.return_value = settings
            mock_schema.return_value = {
                "schema_ok": True,
                "applied_migrations": ["001_init"],
                "pending_migrations": [],
            }

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(get_capabilities())
            finally:
                loop.close()

        assert result["db_ready"] is True
        assert result["remediation"] is None

    def test_db_ready_false_with_pending_migrations(self):
        """db_ready=false when pending migrations exist."""
        from backend.api.routes.ops import get_capabilities
        import asyncio

        with patch("backend.api.routes.ops.get_settings") as mock_settings, \
             patch("backend.db.connect.get_schema_status") as mock_schema:
            settings = MagicMock()
            settings.is_live_execution_allowed.return_value = False
            mock_settings.return_value = settings
            mock_schema.return_value = {
                "schema_ok": False,
                "applied_migrations": ["001_init"],
                "pending_migrations": ["025_add_insight_json"],
            }

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(get_capabilities())
            finally:
                loop.close()

        assert result["db_ready"] is False
        assert result["remediation"] is not None
        assert "pending" in result["remediation"].lower()

    def test_live_trading_matches_config(self):
        """live_trading_enabled reflects settings.is_live_execution_allowed()."""
        from backend.api.routes.ops import get_capabilities
        import asyncio

        with patch("backend.api.routes.ops.get_settings") as mock_settings, \
             patch("backend.db.connect.get_schema_status") as mock_schema:
            settings = MagicMock()
            settings.is_live_execution_allowed.return_value = True
            mock_settings.return_value = settings
            mock_schema.return_value = {
                "schema_ok": True,
                "applied_migrations": [],
                "pending_migrations": [],
            }

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(get_capabilities())
            finally:
                loop.close()

        assert result["live_trading_enabled"] is True

    def test_paper_always_enabled(self):
        """paper_trading_enabled is always true."""
        from backend.api.routes.ops import get_capabilities
        import asyncio

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

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(get_capabilities())
            finally:
                loop.close()

        assert result["paper_trading_enabled"] is True

    def test_version_present(self):
        """version field is a non-empty string."""
        from backend.api.routes.ops import get_capabilities
        import asyncio

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

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(get_capabilities())
            finally:
                loop.close()

        assert isinstance(result["version"], str)
        assert len(result["version"]) > 0
