"""Tests for client health scoring and classification."""
import pytest
import json
from datetime import datetime, timezone, timedelta
from backend.db.connect import get_conn, row_get
from backend.core.ids import new_id
from backend.core.time import now_iso


def _ensure_tenant(tenant_id):
    """Ensure tenant exists in the tenants table (FK requirement)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tenants (tenant_id, name) VALUES (?, ?)",
            (tenant_id, tenant_id),
        )
        conn.commit()


def _insert_run(tenant_id, status="COMPLETED", created_at=None):
    """Helper: insert a run for testing."""
    _ensure_tenant(tenant_id)
    run_id = new_id("run_")
    ts = created_at or now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, ?, 'PAPER', ?)",
            (run_id, tenant_id, status, ts),
        )
        conn.commit()
    return run_id


def _insert_order(tenant_id, run_id, filled_qty=1.0, avg_fill_price=100.0, created_at=None):
    """Helper: insert an order for testing."""
    order_id = new_id("order_")
    ts = created_at or now_iso()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO orders (order_id, run_id, tenant_id, symbol, side, qty, filled_qty, avg_fill_price, status, created_at)
               VALUES (?, ?, ?, 'BTC-USD', 'BUY', 1.0, ?, ?, 'FILLED', ?)""",
            (order_id, run_id, tenant_id, filled_qty, avg_fill_price, ts),
        )
        conn.commit()
    return order_id


def _days_ago_iso(days):
    """Return ISO timestamp for N days ago."""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat().replace('+00:00', 'Z')


class TestHealthScoreCalculation:
    """Test health score computation logic."""

    def test_high_score_active_successful(self, test_db):
        """100% activity + 100% success = high score."""
        from backend.services.client_health import compute_health_score

        tid = "t_health_high"
        # Insert 10 recent successful runs
        for i in range(10):
            _insert_run(tid, "COMPLETED", _days_ago_iso(i + 1))
        # Insert some prior-period runs
        for i in range(5):
            _insert_run(tid, "COMPLETED", _days_ago_iso(35 + i))

        result = compute_health_score(tid)
        assert result["score"] >= 70, f"Expected high score, got {result['score']}"
        assert result["classification"] in ("healthy", "good")
        assert result["components"]["success_rate"] == 100.0

    def test_zero_trades_inactive(self, test_db):
        """Zero trades = score 0, classification inactive."""
        from backend.services.client_health import compute_health_score

        result = compute_health_score("t_ghost")
        assert result["score"] == 0
        assert result["classification"] == "inactive"
        assert result["stats"]["total_runs"] == 0

    def test_all_failed_low_score(self, test_db):
        """All failed runs = low success_rate component."""
        from backend.services.client_health import compute_health_score

        tid = "t_all_fail"
        for i in range(5):
            _insert_run(tid, "FAILED", _days_ago_iso(i + 1))

        result = compute_health_score(tid)
        assert result["components"]["success_rate"] == 0.0
        assert result["score"] < 70  # Can't be healthy with 0% success

    def test_inactive_30_plus_days(self, test_db):
        """No recent activity but old activity = low activity score."""
        from backend.services.client_health import compute_health_score

        tid = "t_inactive_30"
        # Only old runs (40+ days ago)
        for i in range(5):
            _insert_run(tid, "COMPLETED", _days_ago_iso(40 + i))

        result = compute_health_score(tid)
        assert result["components"]["activity"] == 0.0  # No recent runs


class TestClassificationBoundaries:
    """Test health classification thresholds."""

    def test_classify_healthy(self, test_db):
        """Score 90 = healthy."""
        from backend.services.client_health import classify_health
        assert classify_health(90) == "healthy"
        assert classify_health(100) == "healthy"
        assert classify_health(95.5) == "healthy"

    def test_classify_good(self, test_db):
        """Score 70-89 = good."""
        from backend.services.client_health import classify_health
        assert classify_health(89) == "good"
        assert classify_health(70) == "good"
        assert classify_health(89.9) == "good"

    def test_classify_at_risk(self, test_db):
        """Score 40-69 = at_risk."""
        from backend.services.client_health import classify_health
        assert classify_health(40) == "at_risk"
        assert classify_health(69) == "at_risk"

    def test_classify_churning(self, test_db):
        """Score 1-39 = churning."""
        from backend.services.client_health import classify_health
        assert classify_health(1) == "churning"
        assert classify_health(39) == "churning"

    def test_classify_inactive(self, test_db):
        """Score 0 = inactive."""
        from backend.services.client_health import classify_health
        assert classify_health(0) == "inactive"


class TestAlertTriggers:
    """Test alert detection logic."""

    def test_no_activity_7d_alert(self, test_db):
        """No activity in 7 days fires ALERT_NO_ACTIVITY_7D."""
        from backend.services.client_health import compute_health_score, detect_alerts

        tid = "t_stale"
        # Only old runs (10+ days ago)
        for i in range(3):
            _insert_run(tid, "COMPLETED", _days_ago_iso(10 + i))

        health = compute_health_score(tid)
        alerts = detect_alerts(tid, health)
        alert_types = [a["alert_type"] for a in alerts]
        assert "ALERT_NO_ACTIVITY_7D" in alert_types

    def test_no_alert_if_recent_activity(self, test_db):
        """Recent activity should not trigger ALERT_NO_ACTIVITY_7D."""
        from backend.services.client_health import compute_health_score, detect_alerts

        tid = "t_active_ok"
        _insert_run(tid, "COMPLETED", _days_ago_iso(1))

        health = compute_health_score(tid)
        alerts = detect_alerts(tid, health)
        alert_types = [a["alert_type"] for a in alerts]
        assert "ALERT_NO_ACTIVITY_7D" not in alert_types

    def test_no_alert_for_brand_new_tenant(self, test_db):
        """Brand new tenant with no runs should not get no-activity alert."""
        from backend.services.client_health import compute_health_score, detect_alerts

        health = compute_health_score("t_brand_new")
        alerts = detect_alerts("t_brand_new", health)
        alert_types = [a["alert_type"] for a in alerts]
        assert "ALERT_NO_ACTIVITY_7D" not in alert_types


class TestIssueCRUD:
    """Test issue create, read, update, comment via service layer."""

    def test_create_and_read_issue(self, test_db):
        """Create an issue and verify it can be read back."""
        issue_id = new_id("issue_")
        now = now_iso()
        tenant_id = "t_issues"

        with get_conn() as conn:
            conn.execute(
                """INSERT INTO client_issues
                   (issue_id, tenant_id, title, description, status, priority, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'open', 'medium', 'test-user', ?, ?)""",
                (issue_id, tenant_id, "Test Issue", "A test issue", now, now),
            )
            conn.commit()

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM client_issues WHERE issue_id = ?", (issue_id,))
            row = cursor.fetchone()

        assert row is not None
        assert row_get(row, "title") == "Test Issue"
        assert row_get(row, "status") == "open"
        assert row_get(row, "tenant_id") == tenant_id

    def test_update_issue_status(self, test_db):
        """Update issue status from open to resolved."""
        issue_id = new_id("issue_")
        now = now_iso()
        tenant_id = "t_issues2"

        with get_conn() as conn:
            conn.execute(
                """INSERT INTO client_issues
                   (issue_id, tenant_id, title, status, priority, created_by, created_at, updated_at)
                   VALUES (?, ?, 'Issue 2', 'open', 'high', 'test-user', ?, ?)""",
                (issue_id, tenant_id, now, now),
            )
            conn.commit()

        with get_conn() as conn:
            conn.execute(
                "UPDATE client_issues SET status = ?, resolved_at = ?, updated_at = ? WHERE issue_id = ?",
                ("resolved", now_iso(), now_iso(), issue_id),
            )
            conn.commit()

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM client_issues WHERE issue_id = ?", (issue_id,))
            row = cursor.fetchone()

        assert row_get(row, "status") == "resolved"
        assert row_get(row, "resolved_at") is not None

    def test_add_comment_to_issue(self, test_db):
        """Add a comment to an issue and read it back."""
        issue_id = new_id("issue_")
        comment_id = new_id("cmt_")
        now = now_iso()
        tenant_id = "t_comment"

        with get_conn() as conn:
            conn.execute(
                """INSERT INTO client_issues
                   (issue_id, tenant_id, title, status, priority, created_by, created_at, updated_at)
                   VALUES (?, ?, 'Commented Issue', 'open', 'low', 'test-user', ?, ?)""",
                (issue_id, tenant_id, now, now),
            )
            conn.execute(
                """INSERT INTO client_issue_comments (comment_id, issue_id, author, content, created_at)
                   VALUES (?, ?, 'test-user', 'This is a comment', ?)""",
                (comment_id, issue_id, now),
            )
            conn.commit()

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM client_issue_comments WHERE issue_id = ? ORDER BY created_at ASC",
                (issue_id,)
            )
            comments = cursor.fetchall()

        assert len(comments) == 1
        assert row_get(comments[0], "content") == "This is a comment"
        assert row_get(comments[0], "author") == "test-user"
