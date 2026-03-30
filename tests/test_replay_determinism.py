"""Test REPLAY mode determinism."""
import pytest
import time
import os
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn
from backend.core.config import get_settings

client = TestClient(app)


def _delete_test_db():
    """Delete test database file."""
    settings = get_settings()
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.fixture(scope="module")
def setup_db():
    """Setup test database."""
    _delete_test_db()
    init_db()
    yield


def _wait_for_completion(run_id: str, max_wait: int = 60):
    """Wait for run to complete."""
    start_time = time.time()
    while time.time() - start_time < max_wait:
        response = client.get(
            f"/api/v1/runs/{run_id}",
            headers={"X-Dev-Tenant": "t_default"}
        )
        if response.status_code == 200:
            detail = response.json()
            status = detail["run"]["status"]
            if status in ("COMPLETED", "FAILED", "PAUSED"):
                if status == "PAUSED":
                    # Approve and continue
                    approvals = detail.get("approvals", [])
                    if approvals:
                        approval_id = approvals[0]["approval_id"]
                        client.post(
                            f"/api/v1/approvals/{approval_id}/approve",
                            headers={"X-Dev-Tenant": "t_default"},
                            json={"comment": "Test approval"}
                        )
                        time.sleep(1)
                        continue
                return detail
        time.sleep(1)
    raise TimeoutError(f"Run {run_id} did not complete in {max_wait}s")


def test_replay_determinism(setup_db):
    """Test REPLAY mode produces deterministic results from source run."""
    # Step 1: Run PAPER mode to create source
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={"execution_mode": "PAPER"}
    )
    assert response.status_code == 200
    source_run_id = response.json()["run_id"]
    
    # Wait for source run to complete
    source_detail = _wait_for_completion(source_run_id)
    assert source_detail["run"]["status"] == "COMPLETED", "Source run should complete"
    
    # Capture source orders
    source_orders = source_detail["orders"]
    assert len(source_orders) >= 1, "Source run should have orders"
    
    # Extract key fields from source orders
    source_order_fields = [
        {
            "symbol": o["symbol"],
            "side": o["side"],
            "notional_usd": o["notional_usd"],
            "qty": o["qty"]
        }
        for o in source_orders
    ]
    
    # Step 2: Run REPLAY mode with source_run_id
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "execution_mode": "REPLAY",
            "source_run_id": source_run_id
        }
    )
    assert response.status_code == 200
    replay_run_id = response.json()["run_id"]
    assert response.json().get("trace_id"), "Response should include trace_id"
    
    # Wait for replay run to complete
    replay_detail = _wait_for_completion(replay_run_id)
    assert replay_detail["run"]["status"] == "COMPLETED", "Replay run should complete"
    assert replay_detail["run"]["source_run_id"] == source_run_id, "Replay run should reference source"
    
    # Step 3: Compare orders deterministically
    replay_orders = replay_detail["orders"]
    assert len(replay_orders) == len(source_orders), f"Replay should have same order count: {len(replay_orders)} vs {len(source_orders)}"
    
    for i, (source_order, replay_order) in enumerate(zip(source_order_fields, replay_orders)):
        assert replay_order["symbol"] == source_order["symbol"], f"Order {i} symbol mismatch"
        assert replay_order["side"] == source_order["side"], f"Order {i} side mismatch"
        assert abs(replay_order["notional_usd"] - source_order["notional_usd"]) < 0.01, f"Order {i} notional mismatch"
        if source_order["qty"]:
            assert abs(replay_order["qty"] - source_order["qty"]) < 0.001, f"Order {i} qty mismatch"
    
    # Step 4: Verify order events were copied
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM order_events WHERE order_id IN (SELECT order_id FROM orders WHERE run_id = ?)",
            (replay_run_id,)
        )
        replay_events_count = cursor.fetchone()["count"]
        
        cursor.execute(
            "SELECT COUNT(*) as count FROM order_events WHERE order_id IN (SELECT order_id FROM orders WHERE run_id = ?)",
            (source_run_id,)
        )
        source_events_count = cursor.fetchone()["count"]
    
    assert replay_events_count >= source_events_count, f"Replay should have at least as many order events: {replay_events_count} vs {source_events_count}"


def test_replay_requires_source_run_id(setup_db):
    """Test REPLAY mode fails without source_run_id."""
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={"execution_mode": "REPLAY"}
    )
    assert response.status_code == 400
    assert "source_run_id" in response.json()["detail"].lower()


def test_replay_source_not_found(setup_db):
    """Test REPLAY mode fails with non-existent source_run_id."""
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "execution_mode": "REPLAY",
            "source_run_id": "run_nonexistent"
        }
    )
    assert response.status_code == 404
