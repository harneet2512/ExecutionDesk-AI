"""Tests for Round 4 DB schema fixes (D1-D7).

Verifies that all repo INSERT/UPDATE statements match actual migration schema.
"""
import pytest
import os
import uuid
from backend.db.connect import init_db, get_conn, _close_connections, validate_schema
from backend.core.config import get_settings
from backend.db.repo.evals_repo import EvalsRepo
from backend.db.repo.portfolio_repo import PortfolioRepo
from backend.db.repo.run_events_repo import RunEventsRepo
from backend.db.repo.order_events_repo import OrderEventsRepo
from backend.db.repo.runs_repo import RunsRepo

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

    # Insert base data needed for FK constraints
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO tenants (tenant_id, name) VALUES (?, ?)",
            ("t_default", "Default Tenant")
        )
        # Insert a run for FK references
        cursor.execute(
            "INSERT OR IGNORE INTO runs (run_id, tenant_id, status, execution_mode) VALUES (?, ?, ?, ?)",
            ("run_schema_test", "t_default", "CREATED", "PAPER")
        )
        # Insert an order for FK references
        cursor.execute(
            "INSERT OR IGNORE INTO orders (order_id, run_id, tenant_id, provider, symbol, side, order_type, qty, notional_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("ord_schema_test", "run_schema_test", "t_default", "PAPER", "BTC-USD", "buy", "market", 0.001, 10.0, "FILLED")
        )
        conn.commit()
    yield
    _close_connections()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass


class TestEvalsRepoSchema:
    """D1+D2: evals_repo INSERT uses correct columns."""

    def test_create_eval_result_succeeds(self, setup_db):
        """INSERT uses eval_id (not id), eval_name (not eval_type), no metadata_json."""
        repo = EvalsRepo()
        eval_id = f"eval_{uuid.uuid4().hex[:8]}"
        result = repo.create_eval_result({
            "eval_id": eval_id,
            "run_id": "run_schema_test",
            "tenant_id": "t_default",
            "eval_name": "test_eval",
            "score": 0.85,
            "reasons_json": '["good performance"]',
        })
        assert result == eval_id

    def test_get_evals_by_run(self, setup_db):
        """SELECT uses ts (not created_at) for ordering."""
        repo = EvalsRepo()
        eval_id = f"eval_{uuid.uuid4().hex[:8]}"
        repo.create_eval_result({
            "eval_id": eval_id,
            "run_id": "run_schema_test",
            "tenant_id": "t_default",
            "eval_name": "test_eval",
            "score": 0.9,
            "reasons_json": '[]',
        })
        results = repo.get_evals_by_run("run_schema_test")
        assert len(results) >= 1
        assert results[-1]["eval_id"] == eval_id


class TestPortfolioRepoSchema:
    """D3: portfolio_repo INSERT uses correct columns."""

    def test_create_snapshot_succeeds(self, setup_db):
        """INSERT uses snapshot_id (not id), includes total_value_usd, no created_at."""
        repo = PortfolioRepo()
        snap_id = f"snap_{uuid.uuid4().hex[:8]}"
        result = repo.create_snapshot({
            "snapshot_id": snap_id,
            "run_id": "run_schema_test",
            "tenant_id": "t_default",
            "balances_json": '{"USD": 100}',
            "positions_json": '[]',
            "total_value_usd": 100.0,
            "ts": "2025-01-01T00:00:00",
        })
        assert result == snap_id

    def test_get_latest_snapshot(self, setup_db):
        """SELECT works with actual schema columns."""
        repo = PortfolioRepo()
        snap_id = f"snap_{uuid.uuid4().hex[:8]}"
        repo.create_snapshot({
            "snapshot_id": snap_id,
            "run_id": "run_schema_test",
            "tenant_id": "t_default",
            "balances_json": '{"USD": 50}',
            "positions_json": '[]',
            "total_value_usd": 50.0,
            "ts": "2025-01-01T00:00:00",
        })
        latest = repo.get_latest_snapshot("t_default")
        assert latest is not None
        assert latest["snapshot_id"] == snap_id
        assert latest["total_value_usd"] == 50.0


class TestRunEventsRepoSchema:
    """D4: run_events_repo INSERT uses correct columns (no created_at)."""

    def test_create_event_succeeds(self, setup_db):
        """INSERT into run_events without created_at column."""
        repo = RunEventsRepo()
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        result = repo.create_event({
            "id": event_id,
            "run_id": "run_schema_test",
            "tenant_id": "t_default",
            "event_type": "STEP_STARTED",
            "payload_json": '{"step": "research"}',
            "ts": "2025-01-01T00:00:00",
        })
        assert result == event_id

    def test_get_events_by_run(self, setup_db):
        """SELECT works with ts ordering."""
        repo = RunEventsRepo()
        repo.create_event({
            "id": f"evt_{uuid.uuid4().hex[:8]}",
            "run_id": "run_schema_test",
            "tenant_id": "t_default",
            "event_type": "STEP_STARTED",
            "payload_json": '{}',
            "ts": "2025-01-01T00:00:00",
        })
        events = repo.get_events_by_run("run_schema_test", "t_default")
        assert len(events) >= 1


class TestOrderEventsRepoSchema:
    """D5: order_events_repo INSERT uses correct columns (no created_at)."""

    def test_create_order_event_succeeds(self, setup_db):
        """INSERT into order_events without created_at column."""
        repo = OrderEventsRepo()
        event_id = f"oevt_{uuid.uuid4().hex[:8]}"
        result = repo.create_order_event({
            "id": event_id,
            "order_id": "ord_schema_test",
            "event_type": "FILLED",
            "payload_json": '{"qty": 0.001}',
            "ts": "2025-01-01T00:00:00",
        })
        assert result == event_id


class TestRunsRepoSchema:
    """D6+D7: runs_repo create/update uses correct columns."""

    def test_create_run_succeeds(self, setup_db):
        """CREATE uses actual schema columns (no strategy_id, created_by, etc.)."""
        repo = RunsRepo()
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        result = repo.create_run({
            "run_id": run_id,
            "tenant_id": "t_default",
            "status": "CREATED",
            "execution_mode": "PAPER",
        })
        assert result == run_id

    def test_create_run_with_optional_columns(self, setup_db):
        """CREATE with optional columns (source_run_id, metadata_json, intent_json)."""
        repo = RunsRepo()
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        result = repo.create_run({
            "run_id": run_id,
            "tenant_id": "t_default",
            "status": "CREATED",
            "execution_mode": "PAPER",
            "source_run_id": "run_schema_test",
            "metadata_json": '{"test": true}',
            "intent_json": '{"intent": "TRADE"}',
        })
        assert result == run_id

    def test_update_run_status_completed(self, setup_db):
        """UPDATE COMPLETED uses completed_at (not updated_at)."""
        repo = RunsRepo()
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        repo.create_run({
            "run_id": run_id,
            "tenant_id": "t_default",
            "status": "CREATED",
            "execution_mode": "PAPER",
        })
        # Should not raise
        repo.update_run_status(run_id, "COMPLETED")
        run = repo.get_run(run_id, "t_default")
        assert run["status"] == "COMPLETED"
        assert run["completed_at"] is not None

    def test_update_run_status_failed(self, setup_db):
        """UPDATE FAILED uses failure_reason/failure_code (not error_message/failed_at)."""
        repo = RunsRepo()
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        repo.create_run({
            "run_id": run_id,
            "tenant_id": "t_default",
            "status": "CREATED",
            "execution_mode": "PAPER",
        })
        repo.update_run_status(run_id, "FAILED", failure_reason="test error", failure_code="TEST_FAILURE")
        run = repo.get_run(run_id, "t_default")
        assert run["status"] == "FAILED"
        assert run["completed_at"] is not None
        assert run["failure_reason"] == "test error"
        assert run["failure_code"] == "TEST_FAILURE"

    def test_update_run_status_running(self, setup_db):
        """UPDATE RUNNING sets started_at."""
        repo = RunsRepo()
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        repo.create_run({
            "run_id": run_id,
            "tenant_id": "t_default",
            "status": "CREATED",
            "execution_mode": "PAPER",
        })
        repo.update_run_status(run_id, "RUNNING")
        run = repo.get_run(run_id, "t_default")
        assert run["status"] == "RUNNING"
        assert run["started_at"] is not None


class TestValidateSchemaExtended:
    """validate_schema covers new tables (eval_results, portfolio_snapshots, etc.)."""

    def test_validate_schema_no_crash(self, setup_db):
        """validate_schema completes without error."""
        # Should not raise
        validate_schema()
