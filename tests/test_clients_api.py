"""Tests for Client Operations Dashboard API endpoints."""
import pytest
import json
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso


def _days_ago_iso(days):
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat().replace('+00:00', 'Z')


def _ensure_tenant(tenant_id):
    """Ensure tenant exists in the tenants table (FK requirement)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tenants (tenant_id, name) VALUES (?, ?)",
            (tenant_id, tenant_id),
        )
        conn.commit()


def _seed_tenant(tenant_id, num_runs=5, num_failed=0):
    """Seed a tenant with runs for testing."""
    _ensure_tenant(tenant_id)
    for i in range(num_runs):
        run_id = new_id("run_")
        status = "FAILED" if i < num_failed else "COMPLETED"
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, ?, 'PAPER', ?)",
                (run_id, tenant_id, status, _days_ago_iso(i + 1)),
            )
            conn.commit()


@pytest.fixture
def client(test_db):
    """Create a FastAPI test client."""
    from backend.api.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestListClients:
    """Test GET /api/v1/clients."""

    def test_list_clients_empty(self, client, test_db):
        """Returns empty list when no profiles exist."""
        res = client.get("/api/v1/clients", headers={"X-Dev-Tenant": "t_default"})
        assert res.status_code == 200
        data = res.json()
        assert "clients" in data
        assert isinstance(data["clients"], list)

    def test_list_clients_after_refresh(self, client, test_db):
        """Returns client profiles after health refresh."""
        _seed_tenant("t_listed", num_runs=3)

        # Refresh to populate profiles
        res = client.post("/api/v1/clients/refresh", headers={"X-Dev-Tenant": "t_default"})
        assert res.status_code == 200

        # List should now have the tenant
        res = client.get("/api/v1/clients", headers={"X-Dev-Tenant": "t_default"})
        assert res.status_code == 200
        data = res.json()
        tenants = [c["tenant_id"] for c in data["clients"]]
        assert "t_listed" in tenants


class TestGetClientProfile:
    """Test GET /api/v1/clients/{tenant_id}."""

    def test_get_client_profile(self, client, test_db):
        """Returns profile with health breakdown."""
        _seed_tenant("t_profile", num_runs=5)

        res = client.get("/api/v1/clients/t_profile", headers={"X-Dev-Tenant": "t_default"})
        assert res.status_code == 200
        data = res.json()
        assert data["tenant_id"] == "t_profile"
        assert "health" in data
        assert "score" in data["health"]
        assert "classification" in data["health"]
        assert "components" in data["health"]
        assert "alerts" in data
        assert "issues" in data

    def test_get_nonexistent_client(self, client, test_db):
        """Returns inactive profile for unknown tenant."""
        res = client.get("/api/v1/clients/t_nobody", headers={"X-Dev-Tenant": "t_default"})
        assert res.status_code == 200
        data = res.json()
        assert data["health"]["classification"] == "inactive"
        assert data["health"]["score"] == 0


class TestIssueEndpoints:
    """Test issue CRUD endpoints."""

    def test_create_issue(self, client, test_db):
        """POST creates an issue and returns it."""
        res = client.post(
            "/api/v1/clients/t_issues_api/issues",
            json={"title": "Test Issue", "description": "Something broke", "priority": "high"},
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "Test Issue"
        assert data["status"] == "open"
        assert "issue_id" in data

    def test_list_issues(self, client, test_db):
        """GET returns issues for a tenant."""
        # Create two issues
        for title in ["Issue A", "Issue B"]:
            client.post(
                "/api/v1/clients/t_list_issues/issues",
                json={"title": title},
                headers={"X-Dev-Tenant": "t_default"},
            )

        res = client.get(
            "/api/v1/clients/t_list_issues/issues",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2

    def test_update_issue_status(self, client, test_db):
        """PATCH updates issue status."""
        # Create
        res = client.post(
            "/api/v1/clients/t_update_issue/issues",
            json={"title": "Will Resolve"},
            headers={"X-Dev-Tenant": "t_default"},
        )
        issue_id = res.json()["issue_id"]

        # Update to resolved
        res = client.patch(
            f"/api/v1/clients/t_update_issue/issues/{issue_id}",
            json={"status": "resolved", "comment": "Fixed it"},
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "resolved"
        assert data["resolved_at"] is not None
        assert len(data["comments"]) == 1
        assert data["comments"][0]["content"] == "Fixed it"

    def test_update_nonexistent_issue(self, client, test_db):
        """PATCH on missing issue returns 404."""
        res = client.patch(
            "/api/v1/clients/t_nobody/issues/issue_fake123",
            json={"status": "resolved"},
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert res.status_code == 404
