"""Frontend smoke test using HTTP requests."""
import pytest
import requests
import time
import subprocess
import os
import signal
from pathlib import Path

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


@pytest.fixture(scope="module")
def backend_server():
    """Start backend server in subprocess."""
    # Check if backend is already running
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=2)
        if response.status_code == 200:
            yield None
            return
    except:
        pass
    
    # Start backend if not running
    import sys
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api.main:app", "--port", "8000"],
        cwd=Path(__file__).parent.parent,
        env={**os.environ, "DATABASE_URL": "sqlite:///./test_frontend.db"}
    )
    
    # Wait for backend to be ready
    for _ in range(30):
        try:
            response = requests.get(f"{BACKEND_URL}/health", timeout=1)
            if response.status_code == 200:
                break
        except:
            time.sleep(1)
    else:
        proc.terminate()
        pytest.skip("Backend server failed to start")
    
    yield proc
    
    # Cleanup
    proc.terminate()
    proc.wait(timeout=5)


def test_backend_endpoints_smoke(backend_server):
    """Test backend endpoints used by frontend return valid data."""
    headers = {"X-Dev-Tenant": "t_default"}
    
    # Test health
    response = requests.get(f"{BACKEND_URL}/health", timeout=5)
    assert response.status_code == 200
    
    # Test list runs
    response = requests.get(f"{BACKEND_URL}/api/v1/runs", headers=headers, timeout=5)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    
    # Trigger a run
    response = requests.post(
        f"{BACKEND_URL}/api/v1/runs/trigger",
        headers=headers,
        json={"execution_mode": "PAPER"},
        timeout=5
    )
    assert response.status_code == 200
    run_data = response.json()
    assert "run_id" in run_data
    run_id = run_data["run_id"]
    
    # Wait for completion
    for _ in range(60):
        response = requests.get(f"{BACKEND_URL}/api/v1/runs/{run_id}", headers=headers, timeout=5)
        if response.status_code == 200:
            detail = response.json()
            if detail["run"]["status"] in ("COMPLETED", "FAILED", "PAUSED"):
                if detail["run"]["status"] == "PAUSED":
                    # Approve
                    approvals = detail.get("approvals", [])
                    if approvals:
                        requests.post(
                            f"{BACKEND_URL}/api/v1/approvals/{approvals[0]['approval_id']}/approve",
                            headers=headers,
                            json={"comment": "Test"},
                            timeout=5
                        )
                        time.sleep(2)
                        continue
                break
        time.sleep(1)
    
    # Test portfolio metrics (used by frontend chart)
    response = requests.get(
        f"{BACKEND_URL}/api/v1/portfolio/metrics/value-over-time?run_id={run_id}",
        headers=headers,
        timeout=5
    )
    assert response.status_code == 200
    portfolio_data = response.json()
    assert isinstance(portfolio_data, list)
    if portfolio_data:
        assert "ts" in portfolio_data[0]
        assert "total_value_usd" in portfolio_data[0]
        assert isinstance(portfolio_data[0]["total_value_usd"], (int, float))
    
    # Test ops metrics (used by frontend charts)
    response = requests.get(f"{BACKEND_URL}/api/v1/ops/metrics", headers=headers, timeout=5)
    assert response.status_code == 200
    ops_data = response.json()
    assert "run_durations" in ops_data
    assert "order_fill_latency_ms" in ops_data
    assert "eval_trends" in ops_data
    assert "policy_blocks" in ops_data
    assert isinstance(ops_data["run_durations"], list)
    assert isinstance(ops_data["order_fill_latency_ms"], list)
    assert isinstance(ops_data["eval_trends"], list)
    assert isinstance(ops_data["policy_blocks"], list)
    
    # Verify numeric values in arrays
    if ops_data["run_durations"]:
        assert "duration_ms" in ops_data["run_durations"][0]
        assert isinstance(ops_data["run_durations"][0]["duration_ms"], (int, float))
    if ops_data["eval_trends"]:
        assert "score" in ops_data["eval_trends"][0]
        assert isinstance(ops_data["eval_trends"][0]["score"], (int, float))
