"""Test SSE live streaming."""
import pytest
import time
import os
import subprocess
import threading
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


def test_sse_historical_events(setup_db):
    """Test SSE endpoint replays historical events."""
    # Create a completed run first
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={"execution_mode": "PAPER"}
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    
    # Wait for completion
    max_wait = 60
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
                    approvals = detail.get("approvals", [])
                    if approvals:
                        client.post(
                            f"/api/v1/approvals/{approvals[0]['approval_id']}/approve",
                            headers={"X-Dev-Tenant": "t_default"},
                            json={"comment": "Test"}
                        )
                        time.sleep(1)
                        continue
                break
        time.sleep(1)
    
    # Get SSE stream (TestClient.get() supports streaming responses)
    response = client.get(
        f"/api/v1/runs/{run_id}/events",
        headers={"X-Dev-Tenant": "t_default", "Accept": "text/event-stream"}
    )
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/event-stream" in content_type or "text/event" in content_type.lower(), f"Expected text/event-stream, got {content_type}"
    
    # Read SSE lines
    events_received = []
    lines_read = 0
    for line in response.iter_lines():
        if line:
            # iter_lines() returns strings, not bytes
            if line.startswith("data: "):
                import json
                event_data = json.loads(line[6:])  # Remove "data: " prefix
                events_received.append(event_data)
                lines_read += 1
                if lines_read >= 20:  # Read first 20 events
                    break
    
    # Verify we received historical events
    assert len(events_received) > 0, "Should receive at least one historical event"
    
    # Check for expected event types
    event_types = [e.get("event_type") for e in events_received]
    assert "RUN_CREATED" in event_types or "RUN_STATUS" in event_types, "Should have RUN_CREATED or RUN_STATUS events"
    assert any("NODE_STARTED" in str(e) or "NODE_FINISHED" in str(e) for e in event_types), "Should have node events"


def test_sse_response_format(setup_db):
    """Test SSE response format is valid."""
    # Trigger a run
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={"execution_mode": "PAPER"}
    )
    run_id = response.json()["run_id"]
    
    # Wait a bit for some events
    time.sleep(2)
    
    # Get SSE stream (TestClient.get() supports streaming responses)
    response = client.get(
        f"/api/v1/runs/{run_id}/events",
        headers={"X-Dev-Tenant": "t_default", "Accept": "text/event-stream"}
    )
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/event-stream" in content_type or "text/event" in content_type.lower(), f"Expected text/event-stream, got {content_type}"
    
    # Read a few lines (skip empty lines)
    lines = []
    for line in response.iter_lines():
        if line and line.strip():  # Only non-empty lines
            lines.append(line)
        if len(lines) >= 5:
            break
    
    # Verify SSE format (data: {...}\n\n or : heartbeat\n\n)
    assert len(lines) > 0, "Should receive SSE lines"
    for line in lines:
        assert line.startswith("data: ") or line.startswith(": "), f"Invalid SSE format: {line}"
