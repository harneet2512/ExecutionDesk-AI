"""Tests for the Runbook/Playbook system.

Covers:
- Runbook CRUD (create, read by slug, update, delete)
- GET /runbooks/suggest?error_code=INSUFFICIENT_BALANCE returns matching runbook
- Usage tracking increments times_used counter
- Search across title, symptoms, error_codes
- Seed runbooks apply correctly (8 runbooks created)
"""
import os
import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_db):
    """Create a FastAPI test client with an isolated database."""
    os.environ["TEST_AUTH_BYPASS"] = "true"
    from backend.core.config import reset_settings
    reset_settings()
    from backend.api.main import app
    return TestClient(app, headers={"X-Dev-Tenant": "t_default"})


# ── CRUD Tests ──────────────────────────────────────────────────────────


def test_create_runbook(client):
    """POST /api/v1/runbooks creates a runbook and returns it."""
    payload = {
        "title": "Test Runbook",
        "slug": "test-runbook",
        "category": "testing",
        "error_codes": ["TEST_ERROR"],
        "symptoms": "Something broke during testing",
        "diagnosis_steps": "1. Check logs\n2. Reproduce",
        "resolution": "Fix the bug",
        "prevention": "Write more tests",
        "severity": "low",
    }
    resp = client.post("/api/v1/runbooks", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["slug"] == "test-runbook"
    assert data["title"] == "Test Runbook"
    assert data["category"] == "testing"
    assert data["error_codes"] == ["TEST_ERROR"]
    assert data["times_used"] == 0
    assert data["severity"] == "low"


def test_create_runbook_duplicate_slug(client):
    """Creating a runbook with an existing slug returns 409."""
    payload = {
        "title": "First",
        "slug": "dup-slug",
        "category": "testing",
        "error_codes": [],
        "symptoms": "n/a",
        "diagnosis_steps": "n/a",
        "resolution": "n/a",
        "prevention": "n/a",
        "severity": "low",
    }
    resp1 = client.post("/api/v1/runbooks", json=payload)
    assert resp1.status_code == 201

    payload["title"] = "Second"
    resp2 = client.post("/api/v1/runbooks", json=payload)
    assert resp2.status_code == 409


def test_get_runbook_by_slug(client):
    """GET /api/v1/runbooks/{slug} returns the runbook detail."""
    payload = {
        "title": "Slug Lookup",
        "slug": "slug-lookup",
        "category": "testing",
        "error_codes": ["LOOKUP_ERR"],
        "symptoms": "Cannot find things",
        "diagnosis_steps": "Search harder",
        "resolution": "Found it",
        "prevention": "Label things",
        "severity": "medium",
    }
    client.post("/api/v1/runbooks", json=payload)

    resp = client.get("/api/v1/runbooks/slug-lookup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Slug Lookup"
    assert data["severity"] == "medium"


def test_get_runbook_not_found(client):
    """GET for a nonexistent slug returns 404."""
    resp = client.get("/api/v1/runbooks/does-not-exist")
    assert resp.status_code == 404


def test_update_runbook(client):
    """PATCH /api/v1/runbooks/{slug} updates fields."""
    payload = {
        "title": "Updatable",
        "slug": "updatable",
        "category": "testing",
        "error_codes": ["OLD_CODE"],
        "symptoms": "Old symptoms",
        "diagnosis_steps": "Old steps",
        "resolution": "Old fix",
        "prevention": "Old prevention",
        "severity": "low",
    }
    client.post("/api/v1/runbooks", json=payload)

    patch_resp = client.patch(
        "/api/v1/runbooks/updatable",
        json={"title": "Updated Title", "severity": "critical", "error_codes": ["NEW_CODE"]},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["title"] == "Updated Title"
    assert data["severity"] == "critical"
    assert data["error_codes"] == ["NEW_CODE"]
    # Unchanged fields should persist
    assert data["symptoms"] == "Old symptoms"


def test_update_runbook_not_found(client):
    """PATCH for a nonexistent slug returns 404."""
    resp = client.patch("/api/v1/runbooks/ghost", json={"title": "Nope"})
    assert resp.status_code == 404


def test_delete_runbook(client):
    """DELETE /api/v1/runbooks/{slug} removes the runbook."""
    payload = {
        "title": "Deletable",
        "slug": "deletable",
        "category": "testing",
        "error_codes": [],
        "symptoms": "n/a",
        "diagnosis_steps": "n/a",
        "resolution": "n/a",
        "prevention": "n/a",
        "severity": "low",
    }
    client.post("/api/v1/runbooks", json=payload)

    del_resp = client.delete("/api/v1/runbooks/deletable")
    assert del_resp.status_code == 200

    # Verify it's gone
    get_resp = client.get("/api/v1/runbooks/deletable")
    assert get_resp.status_code == 404


def test_delete_runbook_not_found(client):
    """DELETE for a nonexistent slug returns 404."""
    resp = client.delete("/api/v1/runbooks/ghost")
    assert resp.status_code == 404


# ── List & Filter Tests ─────────────────────────────────────────────────


def test_list_runbooks(client):
    """GET /api/v1/runbooks returns all runbooks."""
    for i in range(3):
        client.post("/api/v1/runbooks", json={
            "title": f"Runbook {i}",
            "slug": f"runbook-{i}",
            "category": "testing",
            "error_codes": [],
            "symptoms": "n/a",
            "diagnosis_steps": "n/a",
            "resolution": "n/a",
            "prevention": "n/a",
            "severity": "low",
        })

    resp = client.get("/api/v1/runbooks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["runbooks"]) >= 3


def test_list_runbooks_filter_by_category(client):
    """GET /api/v1/runbooks?category=X filters by category."""
    client.post("/api/v1/runbooks", json={
        "title": "Cat A",
        "slug": "cat-a",
        "category": "order-errors",
        "error_codes": [],
        "symptoms": "n/a",
        "diagnosis_steps": "n/a",
        "resolution": "n/a",
        "prevention": "n/a",
        "severity": "low",
    })
    client.post("/api/v1/runbooks", json={
        "title": "Cat B",
        "slug": "cat-b",
        "category": "system",
        "error_codes": [],
        "symptoms": "n/a",
        "diagnosis_steps": "n/a",
        "resolution": "n/a",
        "prevention": "n/a",
        "severity": "low",
    })

    resp = client.get("/api/v1/runbooks?category=order-errors")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["category"] == "order-errors" for r in data["runbooks"])


def test_list_runbooks_filter_by_error_code(client):
    """GET /api/v1/runbooks?error_code=X filters by error code in JSON array."""
    client.post("/api/v1/runbooks", json={
        "title": "Balance Error",
        "slug": "balance-error",
        "category": "order-errors",
        "error_codes": ["INSUFFICIENT_BALANCE", "BELOW_MINIMUM_SIZE"],
        "symptoms": "Insufficient funds",
        "diagnosis_steps": "Check balance",
        "resolution": "Add funds",
        "prevention": "Monitor balance",
        "severity": "medium",
    })

    resp = client.get("/api/v1/runbooks?error_code=INSUFFICIENT_BALANCE")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["runbooks"]) >= 1
    assert any("INSUFFICIENT_BALANCE" in r["error_codes"] for r in data["runbooks"])


# ── Suggest Tests ────────────────────────────────────────────────────────


def test_suggest_by_error_code(client):
    """GET /api/v1/runbooks/suggest?error_code=INSUFFICIENT_BALANCE returns matching runbook."""
    client.post("/api/v1/runbooks", json={
        "title": "Order Rejected - Insufficient Balance",
        "slug": "order-rejected-insufficient-balance",
        "category": "order-errors",
        "error_codes": ["INSUFFICIENT_BALANCE", "BELOW_MINIMUM_SIZE"],
        "symptoms": "Order is rejected with insufficient balance",
        "diagnosis_steps": "1. Check wallet\n2. Check order size",
        "resolution": "Add funds or reduce order size",
        "prevention": "Pre-check balances before order",
        "severity": "medium",
    })

    resp = client.get("/api/v1/runbooks/suggest?error_code=INSUFFICIENT_BALANCE")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["suggestions"]) >= 1
    assert data["suggestions"][0]["slug"] == "order-rejected-insufficient-balance"


def test_suggest_no_match(client):
    """Suggest with unknown error code returns empty list."""
    resp = client.get("/api/v1/runbooks/suggest?error_code=TOTALLY_UNKNOWN_ERROR")
    assert resp.status_code == 200
    data = resp.json()
    assert data["suggestions"] == []


# ── Usage Tracking Tests ────────────────────────────────────────────────


def test_usage_tracking_increments_times_used(client):
    """POST /api/v1/runbooks/{slug}/use increments times_used counter."""
    client.post("/api/v1/runbooks", json={
        "title": "Usage Track",
        "slug": "usage-track",
        "category": "testing",
        "error_codes": [],
        "symptoms": "n/a",
        "diagnosis_steps": "n/a",
        "resolution": "n/a",
        "prevention": "n/a",
        "severity": "low",
    })

    # Verify initial count is 0
    resp = client.get("/api/v1/runbooks/usage-track")
    assert resp.json()["times_used"] == 0

    # Log usage twice
    use1 = client.post("/api/v1/runbooks/usage-track/use", json={
        "outcome": "resolved",
        "notes": "Worked great",
    })
    assert use1.status_code == 200

    use2 = client.post("/api/v1/runbooks/usage-track/use", json={
        "outcome": "partial",
    })
    assert use2.status_code == 200

    # Verify count incremented to 2
    resp = client.get("/api/v1/runbooks/usage-track")
    assert resp.json()["times_used"] == 2


def test_usage_tracking_not_found(client):
    """Logging usage for a nonexistent runbook returns 404."""
    resp = client.post("/api/v1/runbooks/ghost/use", json={"outcome": "n/a"})
    assert resp.status_code == 404


# ── Search Tests ─────────────────────────────────────────────────────────


def test_search_across_title_symptoms_error_codes(client):
    """GET /api/v1/runbooks?q=timeout searches title, symptoms, error_codes."""
    client.post("/api/v1/runbooks", json={
        "title": "Order Timeout",
        "slug": "order-timeout",
        "category": "order-errors",
        "error_codes": ["ORDER_TIMEOUT", "EXECUTION_TIMEOUT"],
        "symptoms": "Orders hang and eventually timeout",
        "diagnosis_steps": "Check network",
        "resolution": "Retry",
        "prevention": "Better network",
        "severity": "high",
    })
    client.post("/api/v1/runbooks", json={
        "title": "Unrelated Runbook",
        "slug": "unrelated",
        "category": "system",
        "error_codes": ["SOMETHING_ELSE"],
        "symptoms": "Nothing about time limits",
        "diagnosis_steps": "n/a",
        "resolution": "n/a",
        "prevention": "n/a",
        "severity": "low",
    })

    resp = client.get("/api/v1/runbooks?q=timeout")
    assert resp.status_code == 200
    data = resp.json()
    slugs = [r["slug"] for r in data["runbooks"]]
    assert "order-timeout" in slugs
    assert "unrelated" not in slugs


# ── Seed Runbooks Test ───────────────────────────────────────────────────


def test_seed_runbooks_creates_8(test_db):
    """seed_runbooks() creates exactly 8 pre-populated runbooks."""
    from backend.db.seed_runbooks import seed_runbooks
    from backend.db.connect import get_conn

    count = seed_runbooks()
    assert count == 8

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM runbooks")
        assert cursor.fetchone()["cnt"] == 8

    # Verify specific slugs exist
    expected_slugs = [
        "order-rejected-insufficient-balance",
        "order-timeout",
        "policy-block-symbol-not-allowed",
        "api-rate-limited",
        "stale-market-data",
        "live-trading-disabled",
        "approval-stuck-pending",
        "prediction-market-not-found",
    ]
    with get_conn() as conn:
        cursor = conn.cursor()
        for slug in expected_slugs:
            cursor.execute("SELECT slug FROM runbooks WHERE slug = ?", (slug,))
            row = cursor.fetchone()
            assert row is not None, f"Seed runbook '{slug}' not found"


def test_seed_runbooks_idempotent(test_db):
    """Running seed_runbooks() twice does not duplicate entries."""
    from backend.db.seed_runbooks import seed_runbooks

    seed_runbooks()
    count2 = seed_runbooks()
    assert count2 == 0  # all already exist

    from backend.db.connect import get_conn
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM runbooks")
        assert cursor.fetchone()["cnt"] == 8
