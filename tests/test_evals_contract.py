"""Tests for eval API contract: definitions attached, reasons normalized, scores valid."""
import json
import pytest
from fastapi.testclient import TestClient
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso


@pytest.fixture
def client(test_db):
    from backend.api.main import app
    return TestClient(app)


def _seed_run_with_evals(run_id="run_test123", tenant_id="t_default"):
    """Insert a run and a few eval results."""
    with get_conn() as conn:
        # Ensure tenant exists
        existing = conn.execute(
            "SELECT tenant_id FROM tenants WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO tenants (tenant_id, name) VALUES (?, ?)",
                (tenant_id, "Test Tenant"),
            )
            conn.commit()
        conn.execute(
            """INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at)
               VALUES (?, ?, 'COMPLETED', 'PAPER', ?)""",
            (run_id, tenant_id, now_iso()),
        )
        # Insert evals with various reasons formats
        evals = [
            (new_id("eval_"), run_id, tenant_id, "schema_validity", 1.0,
             json.dumps(["Proposal has required keys"]), "heuristic"),
            (new_id("eval_"), run_id, tenant_id, "policy_compliance", 0.0,
             json.dumps(["Policy decision: BLOCKED"]), "heuristic"),
            (new_id("eval_"), run_id, tenant_id, "faithfulness", 0.85,
             json.dumps(["Evidence coverage: good", "Some minor gaps"]), "ragas"),
        ]
        for e in evals:
            conn.execute(
                """INSERT INTO eval_results
                   (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (*e, now_iso()),
            )
        conn.commit()
    return run_id


def test_scorecard_has_definitions(client, test_db):
    run_id = _seed_run_with_evals()
    resp = client.get(
        f"/api/v1/evals/run/{run_id}",
        headers={"X-Dev-Tenant": "t_default"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "evals" in data

    for ev in data["evals"]:
        # definition must be present
        assert "definition" in ev, f"{ev['eval_name']} missing definition"
        defn = ev["definition"]
        assert isinstance(defn, dict)
        assert "title" in defn
        assert "rubric" in defn
        assert "threshold" in defn


def test_reasons_always_list_of_strings(client, test_db):
    run_id = _seed_run_with_evals()
    resp = client.get(
        f"/api/v1/evals/run/{run_id}",
        headers={"X-Dev-Tenant": "t_default"},
    )
    data = resp.json()

    for ev in data["evals"]:
        reasons = ev["reasons"]
        assert isinstance(reasons, list), f"{ev['eval_name']} reasons not list"
        for r in reasons:
            assert isinstance(r, str), f"{ev['eval_name']} reason not string: {r!r}"


def test_score_is_numeric(client, test_db):
    run_id = _seed_run_with_evals()
    resp = client.get(
        f"/api/v1/evals/run/{run_id}",
        headers={"X-Dev-Tenant": "t_default"},
    )
    data = resp.json()

    for ev in data["evals"]:
        assert isinstance(ev["score"], (int, float)), f"{ev['eval_name']} score not numeric"
        assert 0.0 <= ev["score"] <= 1.0, f"{ev['eval_name']} score {ev['score']} out of [0,1]"


def test_pass_respects_definition_threshold(client, test_db):
    run_id = _seed_run_with_evals()
    resp = client.get(
        f"/api/v1/evals/run/{run_id}",
        headers={"X-Dev-Tenant": "t_default"},
    )
    data = resp.json()

    for ev in data["evals"]:
        threshold = ev["definition"]["threshold"]
        expected_pass = ev["score"] >= threshold
        assert ev["pass"] == expected_pass, (
            f"{ev['eval_name']}: pass={ev['pass']} but score={ev['score']} "
            f"threshold={threshold}"
        )


def test_details_endpoint_has_definitions(client, test_db):
    run_id = _seed_run_with_evals()
    resp = client.get(
        f"/api/v1/evals/run/{run_id}/details",
        headers={"X-Dev-Tenant": "t_default"},
    )
    assert resp.status_code == 200
    data = resp.json()

    for cat, cat_data in data["categories"].items():
        for ev in cat_data["evals"]:
            assert "definition" in ev


def test_definitions_endpoint(client, test_db):
    resp = client.get(
        "/api/v1/evals/definitions",
        headers={"X-Dev-Tenant": "t_default"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "definitions" in data
    assert len(data["definitions"]) >= 30


def test_single_definition_endpoint(client, test_db):
    resp = client.get(
        "/api/v1/evals/definition/schema_validity",
        headers={"X-Dev-Tenant": "t_default"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["eval_name"] == "schema_validity"
    assert data["definition"]["title"] == "Schema Validity"
