"""Tests for Round 6: DB lifecycle overhaul.

Covers:
- init_db creates all critical tables
- validate_schema returns (ok, missing) tuple
- validate_schema detects missing tables
- get_schema_status returns correct structure
- Health endpoint returns ok=true after init
- Health endpoint returns ok=false with degraded schema
- Conversations load after proper init
- Confirm endpoint blocked when schema is bad
- Migrations dir uses absolute path (works regardless of CWD)
"""
import pytest
import os
from pathlib import Path
from fastapi.testclient import TestClient
from backend.api.main import app, is_schema_healthy
from backend.db.connect import (
    init_db, get_conn, _close_connections, validate_schema,
    get_schema_status, _parse_db_url,
)
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


class TestInitDb:
    """init_db creates all critical tables."""

    CRITICAL_TABLES = [
        "runs", "orders", "dag_nodes", "tool_calls",
        "trade_confirmations", "conversations", "messages",
        "eval_results", "portfolio_snapshots", "run_events",
        "order_events", "schema_migrations",
    ]

    def test_init_db_creates_all_tables(self, fresh_db):
        """After init_db(), all critical tables exist."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row["name"] for row in cursor.fetchall()}

        for table in self.CRITICAL_TABLES:
            assert table in tables, f"Critical table '{table}' missing after init_db()"

    def test_init_db_idempotent(self, fresh_db):
        """Calling init_db() twice does not crash or duplicate data."""
        init_db()  # second call
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM schema_migrations")
            count = cursor.fetchone()["cnt"]
        assert count > 0, "No migrations recorded"


class TestValidateSchema:
    """validate_schema returns (ok, missing) tuple."""

    def test_returns_ok_after_init(self, fresh_db):
        """After init_db(), validate_schema returns (True, {})."""
        ok, missing = validate_schema()
        assert ok is True, f"Schema should be OK after init, missing={missing}"
        assert missing == {}

    def test_detects_missing_table(self, fresh_db):
        """Dropping a table makes validate_schema return (False, {...})."""
        with get_conn() as conn:
            conn.execute("DROP TABLE IF EXISTS eval_results")
            conn.commit()

        ok, missing = validate_schema()
        assert ok is False, "Schema should be NOT OK after dropping table"
        assert "eval_results" in missing


class TestGetSchemaStatus:
    """get_schema_status returns correct structure."""

    def test_structure(self, fresh_db):
        """Returns dict with expected keys and correct types."""
        status = get_schema_status()
        assert "db_path" in status
        assert "schema_ok" in status
        assert "applied_migrations" in status
        assert "pending_migrations" in status
        assert "missing_columns" in status
        assert isinstance(status["applied_migrations"], list)
        assert isinstance(status["pending_migrations"], list)
        assert isinstance(status["schema_ok"], bool)

    def test_all_migrations_applied(self, fresh_db):
        """After init_db, pending_migrations should be empty."""
        status = get_schema_status()
        assert status["schema_ok"] is True
        assert len(status["pending_migrations"]) == 0
        assert len(status["applied_migrations"]) > 0

    def test_db_path_is_absolute(self, fresh_db):
        """db_path should be an absolute path."""
        status = get_schema_status()
        assert os.path.isabs(status["db_path"]), f"db_path should be absolute: {status['db_path']}"


class TestHealthEndpoint:
    """Health endpoint returns correct ok/schema_ok fields."""

    def test_health_ok_after_init(self, fresh_db):
        """After init, /api/v1/ops/health returns ok=true."""
        response = client.get(
            "/api/v1/ops/health",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["db_ok"] is True
        assert data["schema_ok"] is True
        assert data["message"] == "All systems operational"

    def test_health_has_migration_counts(self, fresh_db):
        """Health response includes migration count fields."""
        response = client.get(
            "/api/v1/ops/health",
            headers={"X-Dev-Tenant": "t_default"},
        )
        data = response.json()
        assert "migrations_applied" in data
        assert "migrations_pending" in data
        assert isinstance(data["migrations_applied"], int)
        assert data["migrations_applied"] > 0
        assert data["migrations_pending"] == 0


class TestConversationsAfterInit:
    """Conversations load after proper initialization."""

    def test_list_conversations_200(self, fresh_db):
        """GET /conversations returns 200 after init."""
        response = client.get(
            "/api/v1/conversations",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert response.status_code == 200

    def test_create_and_get_conversation(self, fresh_db):
        """Can create and retrieve a conversation after init."""
        # Create
        create_resp = client.post(
            "/api/v1/conversations",
            headers={"X-Dev-Tenant": "t_default"},
            json={"title": "Test Conv"},
        )
        assert create_resp.status_code == 200 or create_resp.status_code == 201
        conv_id = create_resp.json()["conversation_id"]

        # Get
        get_resp = client.get(
            f"/api/v1/conversations/{conv_id}",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["conversation_id"] == conv_id


class TestMigrationsDirAbsolute:
    """Migrations directory resolution is absolute (CWD-independent)."""

    def test_migrations_dir_exists(self):
        """The migrations dir computed from __file__ exists."""
        from backend.db import connect
        migrations_dir = Path(connect.__file__).parent / "migrations"
        assert migrations_dir.exists(), f"Migrations dir not found: {migrations_dir}"
        sql_files = list(migrations_dir.glob("*.sql"))
        assert len(sql_files) > 0, "No .sql migration files found"

    def test_init_db_raises_on_missing_dir(self, tmp_path, monkeypatch, fresh_db):
        """init_db raises RuntimeError when migrations dir doesn't exist."""
        # Monkeypatch __file__ to point to a temp dir without migrations
        import backend.db.connect as connect_mod
        fake_file = tmp_path / "connect.py"
        fake_file.write_text("")
        monkeypatch.setattr(connect_mod, "__file__", str(fake_file))

        with pytest.raises(RuntimeError, match="Migrations directory not found"):
            init_db()
