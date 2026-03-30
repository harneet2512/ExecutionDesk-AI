"""Phase 2 tests: DB path invariant and startup health checks.

These tests verify INV-5 (canonical DB path stability) and the fail-fast
startup health checks introduced in the environment stabilization phase.
"""
import os
import tempfile
import shutil

import pytest


@pytest.fixture()
def isolated_db():
    """Create a temp DB, point settings at it, yield, then clean up."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "inv5_test.db")
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    from backend.core.config import reset_settings
    from backend.db.connect import reset_canonical_db_path, _close_connections

    reset_settings()
    _close_connections()
    reset_canonical_db_path()

    from backend.db.connect import init_db
    init_db()

    yield db_path

    _close_connections()
    reset_canonical_db_path()
    reset_settings()
    if old_url:
        os.environ["DATABASE_URL"] = old_url
    else:
        os.environ.pop("DATABASE_URL", None)
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestDbPathInvariant:
    """INV-5: same canonical DB path across all connections in a process."""

    def test_get_conn_returns_same_path(self, isolated_db):
        from backend.db.connect import get_canonical_db_path, get_conn

        path1 = get_canonical_db_path()
        assert os.path.isabs(path1), "canonical path must be absolute"

        with get_conn() as conn:
            conn.execute("SELECT 1")

        path2 = get_canonical_db_path()
        assert path1 == path2, "canonical path must not change between connections"

    def test_canonical_path_matches_actual_file(self, isolated_db):
        from backend.db.connect import get_canonical_db_path

        canonical = get_canonical_db_path()
        assert os.path.normcase(canonical) == os.path.normcase(
            os.path.abspath(isolated_db)
        )


class TestStartupHealthChecks:
    """Verify fail-fast behaviour when schema or catalog is broken."""

    def test_schema_status_ok_after_init(self, isolated_db):
        from backend.db.connect import get_schema_status

        status = get_schema_status()
        assert status["schema_ok"] is True
        assert len(status["applied_migrations"]) > 0
        assert len(status["pending_migrations"]) == 0

    def test_schema_reports_missing_table(self, isolated_db):
        """If a required table is dropped, schema_ok must be False."""
        from backend.db.connect import get_conn, validate_schema

        with get_conn() as conn:
            conn.execute("DROP TABLE IF EXISTS eval_results")

        ok, missing = validate_schema()
        assert not ok
        assert "eval_results" in missing

    def test_catalog_table_exists(self, isolated_db):
        from backend.db.connect import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM product_catalog"
            ).fetchone()
        assert row["cnt"] is not None  # table exists (count may be 0 in test)

    def test_migrations_count_stable(self, isolated_db):
        """Two consecutive schema_status calls must report the same migration list."""
        from backend.db.connect import get_schema_status

        s1 = get_schema_status()
        s2 = get_schema_status()
        assert s1["applied_migrations"] == s2["applied_migrations"]
