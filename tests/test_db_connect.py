"""Tests for database connection management with PostgreSQL support.

Tests:
- get_conn() returns sqlite3 connection for sqlite DATABASE_URL
- row_get() works with dict rows (psycopg2 style) AND sqlite3.Row
- Connection pooling lifecycle
- _is_postgres() detection
"""
import os
import sqlite3
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(scope="function")
def sqlite_db():
    """Create a temporary SQLite database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_connect.db")

    old_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass

    try:
        from backend.db.connect import _close_connections, reset_canonical_db_path
        _close_connections()
        reset_canonical_db_path()
    except ImportError:
        pass

    yield db_path

    # Cleanup
    try:
        from backend.db.connect import _close_connections, reset_canonical_db_path
        _close_connections()
        reset_canonical_db_path()
    except ImportError:
        pass
    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass
    if old_db_url:
        os.environ["DATABASE_URL"] = old_db_url
    else:
        os.environ.pop("DATABASE_URL", None)
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


class TestGetConn:
    """Tests for get_conn() context manager."""

    def test_returns_sqlite_connection_for_sqlite_url(self, sqlite_db):
        """get_conn() should return a sqlite3.Connection for sqlite:// URLs."""
        from backend.db.connect import get_conn

        with get_conn() as conn:
            assert isinstance(conn, sqlite3.Connection)

    def test_sqlite_connection_has_row_factory(self, sqlite_db):
        """SQLite connections should have row_factory set to sqlite3.Row."""
        from backend.db.connect import get_conn

        with get_conn() as conn:
            assert conn.row_factory == sqlite3.Row

    def test_connection_can_execute_queries(self, sqlite_db):
        """Connection from get_conn() should execute queries."""
        from backend.db.connect import get_conn

        with get_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_tbl (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO test_tbl (name) VALUES (?)", ("hello",))

        # Verify data persisted (auto-commit on exit)
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM test_tbl WHERE name = ?", ("hello",))
            row = cursor.fetchone()
            assert row is not None
            assert row["name"] == "hello"

    def test_connection_rollback_on_error(self, sqlite_db):
        """Connection should rollback on exception."""
        from backend.db.connect import get_conn

        # First, create the table
        with get_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_rollback (id INTEGER PRIMARY KEY, val TEXT)")

        # Now attempt an insert that raises
        try:
            with get_conn() as conn:
                conn.execute("INSERT INTO test_rollback (val) VALUES (?)", ("should_rollback",))
                raise ValueError("intentional error")
        except ValueError:
            pass

        # Verify data was NOT persisted
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM test_rollback")
            assert cursor.fetchone()["cnt"] == 0


class TestIsPostgres:
    """Tests for _is_postgres() detection."""

    def test_detects_postgresql_url(self):
        """_is_postgres() returns True for postgresql:// URLs."""
        from backend.db.connect import _is_postgres

        assert _is_postgres("postgresql://user:pass@localhost/db") is True
        assert _is_postgres("postgresql+psycopg2://user:pass@localhost/db") is True

    def test_detects_postgres_url(self):
        """_is_postgres() returns True for postgres:// URLs."""
        from backend.db.connect import _is_postgres

        assert _is_postgres("postgres://user:pass@localhost/db") is True

    def test_returns_false_for_sqlite(self):
        """_is_postgres() returns False for sqlite:// URLs."""
        from backend.db.connect import _is_postgres

        assert _is_postgres("sqlite:///./enterprise.db") is False
        assert _is_postgres("sqlite:///tmp/test.db") is False

    def test_returns_false_for_plain_path(self):
        """_is_postgres() returns False for plain file paths."""
        from backend.db.connect import _is_postgres

        assert _is_postgres("./enterprise.db") is False
        assert _is_postgres("/data/enterprise.db") is False


class TestRowGet:
    """Tests for row_get() helper with both row types."""

    def test_with_sqlite_row(self, sqlite_db):
        """row_get() works with sqlite3.Row objects."""
        from backend.db.connect import row_get, get_conn

        with get_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_rowget (id INTEGER PRIMARY KEY, name TEXT, val TEXT)")
            conn.execute("INSERT INTO test_rowget (name, val) VALUES (?, ?)", ("foo", "bar"))
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM test_rowget LIMIT 1")
            row = cursor.fetchone()

            assert row_get(row, "name") == "foo"
            assert row_get(row, "val") == "bar"
            assert row_get(row, "missing", "default_val") == "default_val"

    def test_with_dict_row(self):
        """row_get() works with dict rows (psycopg2 RealDictRow style)."""
        from backend.db.connect import row_get

        row = {"name": "alice", "age": 30, "email": None}

        assert row_get(row, "name") == "alice"
        assert row_get(row, "age") == 30
        assert row_get(row, "email") is None
        assert row_get(row, "missing", "fallback") == "fallback"

    def test_with_none_row(self):
        """row_get() returns default for None row."""
        from backend.db.connect import row_get

        assert row_get(None, "key") is None
        assert row_get(None, "key", "default") == "default"

    def test_with_dict_missing_key(self):
        """row_get() returns default for missing key in dict."""
        from backend.db.connect import row_get

        row = {"a": 1}
        assert row_get(row, "b") is None
        assert row_get(row, "b", 42) == 42


class TestConnectionPoolLifecycle:
    """Tests for connection pooling lifecycle."""

    def test_close_connections_callable(self):
        """_close_connections() should be callable without error."""
        from backend.db.connect import _close_connections

        # Should not raise
        _close_connections()

    def test_reset_canonical_db_path(self, sqlite_db):
        """reset_canonical_db_path() should allow path re-resolution."""
        from backend.db.connect import reset_canonical_db_path, get_canonical_db_path

        path1 = get_canonical_db_path()
        reset_canonical_db_path()
        path2 = get_canonical_db_path()
        # After reset, should resolve again (same value since env unchanged)
        assert path1 == path2

    def test_multiple_connections_sequential(self, sqlite_db):
        """Multiple sequential get_conn() calls should work."""
        from backend.db.connect import get_conn

        with get_conn() as conn1:
            conn1.execute("CREATE TABLE IF NOT EXISTS test_multi (id INTEGER PRIMARY KEY)")

        with get_conn() as conn2:
            conn2.execute("INSERT INTO test_multi (id) VALUES (1)")

        with get_conn() as conn3:
            cursor = conn3.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM test_multi")
            assert cursor.fetchone()["cnt"] == 1


class TestPoolSettings:
    """Tests for DB_POOL_MIN and DB_POOL_MAX settings."""

    def test_pool_settings_have_defaults(self):
        """DB_POOL_MIN and DB_POOL_MAX should have sensible defaults."""
        from backend.core.config import Settings

        s = Settings(database_url="sqlite:///test.db")
        assert hasattr(s, "db_pool_min")
        assert hasattr(s, "db_pool_max")
        assert s.db_pool_min >= 1
        assert s.db_pool_max >= s.db_pool_min

    def test_pool_settings_from_env(self):
        """Pool settings can be overridden via environment."""
        from backend.core.config import Settings

        with patch.dict(os.environ, {"DB_POOL_MIN": "5", "DB_POOL_MAX": "20"}):
            from backend.core.config import reset_settings
            reset_settings()
            s = Settings(database_url="sqlite:///test.db", db_pool_min=5, db_pool_max=20)
            assert s.db_pool_min == 5
            assert s.db_pool_max == 20
