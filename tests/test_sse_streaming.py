"""Test SSE live streaming."""
import pytest
import time
import os
import json
from fastapi.testclient import TestClient

os.environ["TEST_AUTH_BYPASS"] = "true"

from backend.api.main import app

client = TestClient(app)


@pytest.fixture
def setup_db(test_db):
    """Use conftest's isolated test_db."""
    yield test_db


def test_sse_historical_events(setup_db):
    """Test SSE endpoint replays historical events."""
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={"execution_mode": "PAPER"},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    max_wait = 60
    start_time = time.time()
    while time.time() - start_time < max_wait:
        response = client.get(
            f"/api/v1/runs/{run_id}", headers={"X-Dev-Tenant": "t_default"}
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
                            json={"comment": "Test"},
                        )
                        time.sleep(1)
                        continue
                break
        time.sleep(1)

    response = client.get(
        f"/api/v1/runs/{run_id}/events",
        headers={"X-Dev-Tenant": "t_default", "Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/event-stream" in content_type or "text/event" in content_type.lower(), (
        f"Expected text/event-stream, got {content_type}"
    )

    events_received = []
    lines_read = 0
    for line in response.iter_lines():
        if line:
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                events_received.append(event_data)
                lines_read += 1
                if lines_read >= 20:
                    break

    assert len(events_received) > 0, "Should receive at least one historical event"

    event_types = [e.get("event_type") for e in events_received]
    assert "RUN_CREATED" in event_types or "RUN_STATUS" in event_types, (
        "Should have RUN_CREATED or RUN_STATUS events"
    )
    assert any("NODE_STARTED" in str(e) or "NODE_FINISHED" in str(e) for e in event_types), (
        "Should have node events"
    )


def test_sse_response_format(setup_db):
    """Test SSE response format is valid."""
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={"execution_mode": "PAPER"},
    )
    run_id = response.json()["run_id"]

    time.sleep(2)

    response = client.get(
        f"/api/v1/runs/{run_id}/events",
        headers={"X-Dev-Tenant": "t_default", "Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/event-stream" in content_type or "text/event" in content_type.lower(), (
        f"Expected text/event-stream, got {content_type}"
    )

    lines = []
    for line in response.iter_lines():
        if line and line.strip():
            lines.append(line)
        if len(lines) >= 5:
            break

    assert len(lines) > 0, "Should receive SSE lines"
    for line in lines:
        assert line.startswith("data: ") or line.startswith(": "), f"Invalid SSE format: {line}"
