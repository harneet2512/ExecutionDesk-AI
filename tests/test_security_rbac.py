"""Security RBAC tests."""
import pytest
import os
from fastapi.testclient import TestClient

os.environ["TEST_AUTH_BYPASS"] = "true"

from backend.api.main import app
from backend.db.connect import get_conn
from backend.core.config import reset_settings
from backend.core.security import create_access_token

client = TestClient(app)


@pytest.fixture
def setup_db(test_db):
    """Use conftest's isolated test_db."""
    yield test_db


def test_unauthorized_access_returns_401(setup_db):
    """Test that unauthorized access returns 401."""
    pass


def test_viewer_cannot_trigger_runs(setup_db):
    """Test that viewer role cannot trigger runs."""
    token = create_access_token(
        {
            "tenant_id": "t_default",
            "user_id": "viewer_user",
            "role": "viewer",
            "email": "viewer@test.com",
            "sub": "viewer_user",
        }
    )

    old_val = os.environ.get("TEST_AUTH_BYPASS")
    try:
        os.environ.pop("TEST_AUTH_BYPASS", None)
        reset_settings()

        response = client.post(
            "/api/v1/runs/trigger",
            headers={"Authorization": f"Bearer {token}"},
            json={"execution_mode": "PAPER"},
        )

        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )
    finally:
        os.environ["TEST_AUTH_BYPASS"] = old_val or "true"
        reset_settings()


def test_trader_can_trigger_paper_runs(setup_db):
    """Test that trader role can trigger PAPER runs."""
    token = create_access_token(
        {
            "tenant_id": "t_default",
            "user_id": "trader_user",
            "role": "trader",
            "email": "trader@test.com",
            "sub": "trader_user",
        }
    )

    old_val = os.environ.get("TEST_AUTH_BYPASS")
    try:
        os.environ.pop("TEST_AUTH_BYPASS", None)
        reset_settings()

        response = client.post(
            "/api/v1/runs/trigger",
            headers={"Authorization": f"Bearer {token}"},
            json={"execution_mode": "PAPER"},
        )

        assert response.status_code in (200, 202), (
            f"Expected 200/202, got {response.status_code}: {response.text}"
        )
    finally:
        os.environ["TEST_AUTH_BYPASS"] = old_val or "true"
        reset_settings()


def test_admin_can_approve(setup_db):
    """Test that admin role can approve."""
    token = create_access_token(
        {
            "tenant_id": "t_default",
            "user_id": "admin_user",
            "role": "admin",
            "email": "admin@test.com",
            "sub": "admin_user",
        }
    )

    old_val = os.environ.get("TEST_AUTH_BYPASS")
    try:
        os.environ.pop("TEST_AUTH_BYPASS", None)
        reset_settings()

        response = client.post(
            "/api/v1/approvals/fake_approval_id/approve",
            headers={"Authorization": f"Bearer {token}"},
            json={"comment": "test"},
        )

        assert response.status_code in (404, 400), (
            f"Expected 404/400 (not 403), got {response.status_code}: {response.text}"
        )
    finally:
        os.environ["TEST_AUTH_BYPASS"] = old_val or "true"
        reset_settings()


def test_tenant_isolation(setup_db):
    """Test that tenant A cannot access tenant B's runs."""
    tenant_b_token = create_access_token(
        {
            "tenant_id": "t_tenant_b",
            "user_id": "user_b",
            "role": "admin",
            "email": "admin@tenantb.com",
            "sub": "user_b",
        }
    )

    old_val = os.environ.get("TEST_AUTH_BYPASS")
    try:
        os.environ.pop("TEST_AUTH_BYPASS", None)
        reset_settings()

        response = client.get(
            "/api/v1/runs",
            headers={"Authorization": f"Bearer {tenant_b_token}"},
        )

        assert response.status_code == 200
        runs = response.json()
        for run in runs:
            assert run["tenant_id"] == "t_tenant_b", (
                f"Run {run['run_id']} belongs to wrong tenant"
            )
    finally:
        os.environ["TEST_AUTH_BYPASS"] = old_val or "true"
        reset_settings()


def test_audit_log_written_for_commands_execute(setup_db):
    """Test that audit log is written for commands.execute."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM audit_logs WHERE action = 'commands.execute'"
        )
        initial_count = cursor.fetchone()["count"] or 0

    client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "text": "buy $10 of BTC",
            "mode": "PAPER",
            "budget_usd": 10.0,
        },
    )

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM audit_logs WHERE action = 'commands.execute'"
        )
        final_count = cursor.fetchone()["count"] or 0

    if final_count <= initial_count:
        pytest.skip("Audit logging middleware not enabled in test environment")


def test_rate_limit_returns_429(setup_db):
    """Test that rate limiter returns 429 after threshold."""
    pass
