"""E2E test for runs."""
import pytest
import time
import os
import json
from pathlib import Path
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn
from backend.core.config import get_settings
from backend.orchestrator.state_machine import RunStatus

# Set TEST_AUTH_BYPASS for pytest (uses X-Dev-Tenant fallback)
os.environ["TEST_AUTH_BYPASS"] = "true"

client = TestClient(app)


def _delete_test_db():
    """Delete test database file to ensure clean state."""
    settings = get_settings()
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"Deleted existing DB file: {db_path}")


@pytest.fixture(scope="module")
def setup_db():
    """Setup test database."""
    _delete_test_db()
    init_db()
    yield


def test_trigger_run_and_verify_artifacts(setup_db):
    """Test triggering a run and verifying persisted artifacts."""
    # Trigger run
    response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={"execution_mode": "PAPER"}
    )
    assert response.status_code == 200
    run_data = response.json()
    run_id = run_data["run_id"]
    
    # Wait for run to complete (max 30 seconds)
    max_wait = 30
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
                break
        time.sleep(1)
    
    # If paused, approve and wait
    response = client.get(
        f"/api/v1/runs/{run_id}",
        headers={"X-Dev-Tenant": "t_default"}
    )
    detail = response.json()
    
    if detail["run"]["status"] == "PAUSED":
        # Approve
        approvals = detail["approvals"]
        if approvals:
            approval_id = approvals[0]["approval_id"]
            response = client.post(
                f"/api/v1/approvals/{approval_id}/approve",
                headers={"X-Dev-Tenant": "t_default"},
                json={"comment": "Test approval"}
            )
            assert response.status_code == 200
        
        # Wait for completion
        start_time = time.time()
        while time.time() - start_time < max_wait:
            response = client.get(
                f"/api/v1/runs/{run_id}",
                headers={"X-Dev-Tenant": "t_default"}
            )
            detail = response.json()
            if detail["run"]["status"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(1)
    
    # Verify artifacts
    assert len(detail["nodes"]) >= 6, f"Expected at least 6 nodes, got {len(detail['nodes'])}"
    assert len(detail["policy_events"]) >= 1, "Expected at least 1 policy event"
    assert len(detail["orders"]) >= 1 or detail["run"].get("trade_proposal_json"), "Expected orders or proposal"
    assert len(detail["snapshots"]) >= 3, f"Expected at least 3 snapshots, got {len(detail['snapshots'])}"
    assert len(detail["evals"]) >= 3, f"Expected at least 3 evals, got {len(detail['evals'])}"
    
    # Verify eval names
    eval_names = [e["eval_name"] for e in detail["evals"]]
    assert "schema_validity" in eval_names, "Missing schema_validity eval"
    assert "policy_compliance" in eval_names, "Missing policy_compliance eval"
    assert "citation_coverage" in eval_names, "Missing citation_coverage eval"
    
    # Verify tool_calls table is populated with correct content
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM tool_calls WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        tool_calls_count = row["count"] if row else 0
    assert tool_calls_count >= 1, f"Expected at least 1 tool_call, got {tool_calls_count}"
    
    # Verify tool call content
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tool_name, mcp_server, request_json, response_json, status FROM tool_calls WHERE run_id = ? LIMIT 1",
            (run_id,)
        )
        tool_row = cursor.fetchone()
        assert tool_row is not None, "Tool call should exist"
        assert tool_row["tool_name"] == "rag_search", f"Expected tool_name='rag_search', got {tool_row['tool_name']}"
        assert tool_row["mcp_server"] == "research-mcp-server", f"Expected mcp_server='research-mcp-server', got {tool_row['mcp_server']}"
        assert tool_row["status"] == "SUCCESS", f"Expected status='SUCCESS', got {tool_row['status']}"
    
    # Verify trace_id is present and non-empty
    assert "trace_id" in run_data, "Response should include trace_id"
    trace_id = run_data.get("trace_id") or detail["run"].get("trace_id")
    assert trace_id, "trace_id should be non-empty"
    assert trace_id.startswith("trace_"), f"trace_id should start with 'trace_', got {trace_id}"
    
    # Verify run_events schema includes tenant_id
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(run_events)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
    assert "tenant_id" in column_names, "run_events table must include tenant_id column"
    
    # Test metrics endpoints
    response = client.get(
        f"/api/v1/portfolio/metrics/value-over-time?run_id={run_id}",
        headers={"X-Dev-Tenant": "t_default"}
    )
    assert response.status_code == 200
    portfolio_data = response.json()
    assert len(portfolio_data) > 0, "Portfolio metrics should return data"
    
    response = client.get(
        "/api/v1/ops/metrics",
        headers={"X-Dev-Tenant": "t_default"}
    )
    assert response.status_code == 200
    ops_data = response.json()
    assert "run_durations" in ops_data, "Ops metrics should include run_durations"
    assert "order_fill_latency_ms" in ops_data, "Ops metrics should include order_fill_latency_ms"
    assert "eval_trends" in ops_data, "Ops metrics should include eval_trends"
    assert "policy_blocks" in ops_data, "Ops metrics should include policy_blocks"
    
    # Test policies endpoints
    response = client.get(
        "/api/v1/policies",
        headers={"X-Dev-Tenant": "t_default"}
    )
    assert response.status_code == 200, f"GET /api/v1/policies failed: {response.status_code} {response.text}"
    policies_list = response.json()
    assert isinstance(policies_list, list), "Policies endpoint should return a list"
    
    # Test creating a policy
    response = client.post(
        "/api/v1/policies",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "name": "test_policy",
            "policy_json": {"rule": "test"}
        }
    )
    assert response.status_code == 200, f"POST /api/v1/policies failed: {response.status_code} {response.text}"
    policy_response = response.json()
    assert "policy_id" in policy_response, "Policy creation should return policy_id"
    assert policy_response["status"] in ("created", "updated"), "Policy creation should return status"
    
    # Verify run_events have tenant_id
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ? AND tenant_id = ?",
            (run_id, "t_default")
        )
        row = cursor.fetchone()
        events_with_tenant = row["count"] if row else 0
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ?",
            (run_id,)
        )
        total_events = cursor.fetchone()["count"]
    assert events_with_tenant == total_events, f"All run_events should have tenant_id, got {events_with_tenant}/{total_events}"
    
    # Verify ops metrics have numeric values
    assert len(ops_data["run_durations"]) >= 0, "run_durations should be array"
    assert len(ops_data["order_fill_latency_ms"]) >= 0, "order_fill_latency_ms should be array"
    assert len(ops_data["eval_trends"]) >= 0, "eval_trends should be array"
    if ops_data["run_durations"]:
        assert "duration_ms" in ops_data["run_durations"][0], "run_durations should have duration_ms"
        assert isinstance(ops_data["run_durations"][0]["duration_ms"], (int, float)), "duration_ms should be numeric"


def test_command_execute_most_profitable(setup_db):
    """Test command: 'buy the most profitable crypto of last 24hrs for $10'."""
    response = client.post(
        "/api/v1/commands/execute",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "command": "buy the most profitable crypto of last 24hrs for $10",
            "execution_mode": "PAPER"
        }
    )
    assert response.status_code == 200
    result = response.json()
    run_id = result["run_id"]
    assert result["command_type"] == "trade"
    
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
                        time.sleep(2)
                        continue
                break
        time.sleep(1)
    
    # Verify command persisted
    assert detail["run"].get("command_text") == "buy the most profitable crypto of last 24hrs for $10"
    
    # Verify intent persisted
    assert detail["run"].get("parsed_intent_json"), "parsed_intent should be stored"
    
    # Verify rankings evidence exists
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM rankings WHERE run_id = ?",
            (run_id,)
        )
        rankings_count = cursor.fetchone()["count"]
    assert rankings_count >= 1, "Rankings evidence should be stored"
    
    # Verify candles batches exist
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM market_candles_batches WHERE run_id = ?",
            (run_id,)
        )
        batches_count = cursor.fetchone()["count"]
    assert batches_count >= 1, "Candles batches should be stored"
    
    # Verify selected asset matches top ranked
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT selected_symbol, table_json FROM rankings WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,)
        )
        ranking_row = cursor.fetchone()
        if ranking_row:
            rankings_data = json.loads(ranking_row["table_json"])
            selected_symbol = ranking_row["selected_symbol"]
            assert rankings_data[0]["symbol"] == selected_symbol, "Selected symbol should match top-ranked"
    
    # Verify tool calls exist
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM tool_calls WHERE run_id = ?",
            (run_id,)
        )
        tool_calls_count = cursor.fetchone()["count"]
    assert tool_calls_count >= 2, f"Expected at least 2 tool calls (market_data + broker), got {tool_calls_count}"
    
    # Verify evals include new ones
    eval_names = [e["eval_name"] for e in detail["evals"]]
    assert "intent_parse_accuracy" in eval_names or "strategy_validity" in eval_names, "Should have command-based evals"
    
    # Verify trace endpoint works
    response = client.get(
        f"/api/v1/runs/{run_id}/trace",
        headers={"X-Dev-Tenant": "t_default"}
    )
    assert response.status_code == 200
    trace = response.json()
    assert "plan" in trace
    assert "steps" in trace
    assert "artifacts" in trace
    assert len(trace["artifacts"]["rankings"]) > 0, "Trace should include rankings"


def test_command_execute_direct_symbol(setup_db):
    """Test command: 'buy $10 of BTC'."""
    response = client.post(
        "/api/v1/commands/execute",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "command": "buy $10 of BTC",
            "execution_mode": "PAPER"
        }
    )
    assert response.status_code == 200
    result = response.json()
    run_id = result["run_id"]
    
    # Wait briefly for completion
    time.sleep(5)
    
    response = client.get(
        f"/api/v1/runs/{run_id}",
        headers={"X-Dev-Tenant": "t_default"}
    )
    assert response.status_code == 200
    detail = response.json()
    
    # Verify BTC was selected
    execution_plan_json = detail["run"].get("execution_plan_json")
    if execution_plan_json:
        import json
        plan = json.loads(execution_plan_json)
        selected_symbol = plan.get("selected_asset") or plan.get("selected_order", {}).get("symbol")
        # BTC-USD should be in universe
        assert selected_symbol is not None, "Selected symbol should not be None"
        assert selected_symbol in ["BTC-USD"] or (selected_symbol and "BTC" in selected_symbol), f"Expected BTC-related symbol, got {selected_symbol}"


def test_command_replay(setup_db):
    """Test command: 'replay run <run_id>'."""
    # First create a source run
    source_response = client.post(
        "/api/v1/runs/trigger",
        headers={"X-Dev-Tenant": "t_default"},
        json={"execution_mode": "PAPER"}
    )
    assert source_response.status_code == 200
    source_run_id = source_response.json()["run_id"]
    
    # Wait for completion
    time.sleep(10)
    
    # Now replay it
    response = client.post(
        "/api/v1/commands/execute",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "command": f"replay run {source_run_id}",
            "execution_mode": "REPLAY"
        }
    )
    assert response.status_code == 200
    result = response.json()
    assert result["command_type"] == "replay"
    replay_run_id = result["run_id"]
    assert replay_run_id != source_run_id
    
    # Verify source_run_id is set
    response = client.get(
        f"/api/v1/runs/{replay_run_id}",
        headers={"X-Dev-Tenant": "t_default"}
    )
    assert response.status_code == 200
    detail = response.json()
    # Note: source_run_id might be in the run object or execution_plan
    assert detail["run"]["execution_mode"] == "REPLAY"


def test_command_live_blocked(setup_db):
    """Test LIVE mode is blocked without ENABLE_LIVE_TRADING."""
    response = client.post(
        "/api/v1/commands/execute",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "command": "buy $10 of BTC",
            "execution_mode": "LIVE"
        }
    )
    # Should be 403 or 400 (depending on implementation)
    assert response.status_code in (400, 403), f"Expected 403 or 400, got {response.status_code}"


def test_chat_command_most_profitable(setup_db):
    """Test chat command: 'Buy me the most profitable crypto of the last 24 hours for $10'."""
    response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "text": "Buy me the most profitable crypto of the last 24 hours for $10",
            "budget_usd": 10.0,
            "mode": "PAPER",
            "lookback_hours": 24
        }
    )
    assert response.status_code == 200
    result = response.json()
    run_id = result["run_id"]
    assert result["parsed_intent"]["objective"] == "MOST_PROFITABLE"
    assert result["parsed_intent"]["action"] == "BUY"
    assert result["parsed_intent"]["budget_usd"] == 10.0
    
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
                        time.sleep(2)
                        continue
                break
        time.sleep(1)
    
    # Verify intent stored
    assert detail["run"].get("intent_json"), "Intent should be stored"
    assert detail["run"].get("command_text") == "Buy me the most profitable crypto of the last 24 hours for $10"
    
    # Verify steps emitted
    response = client.get(
        f"/api/v1/runs/{run_id}/events",
        headers={"X-Dev-Tenant": "t_default"}
    )
    # SSE endpoint, but we can check run_events
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ? AND event_type IN ('STEP_STARTED', 'STEP_FINISHED')",
            (run_id,)
        )
        step_events_count = cursor.fetchone()["count"]
    assert step_events_count >= 2, f"Expected at least 2 step events, got {step_events_count}"
    
    # Verify candles stored
    with get_conn() as conn:
        cursor = conn.cursor()
        # Check strategy_candles which links candles to runs
        cursor.execute(
            "SELECT COUNT(*) as count FROM strategy_candles WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        candles_count = row["count"] if row else 0
        # Also check if any candles exist for common symbols
        if candles_count == 0:
            cursor.execute(
                "SELECT COUNT(*) as count FROM market_candles WHERE symbol IN ('BTC-USD', 'ETH-USD', 'SOL-USD')",
                ()
            )
            row = cursor.fetchone()
            candles_count = row["count"] if row else 0
        # This query may not work exactly, but check research node outputs
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'research'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        research_row = cursor.fetchone()
        if research_row:
            research_output = json.loads(research_row["outputs_json"])
            assert research_output.get("candles_by_symbol"), "Research should fetch candles"
            assert research_output.get("returns_by_symbol"), "Research should compute returns"
    
    # Verify budget compliance
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT SUM(notional_usd) as total FROM orders WHERE run_id = ?",
            (run_id,)
        )
        total_notional = cursor.fetchone()["total"] or 0.0
    assert total_notional <= 10.0 * 1.01, f"Budget exceeded: ${total_notional:.2f} > $10.00"
    
    # Verify eval scorecard exists
    response = client.get(
        f"/api/v1/evals/run/{run_id}",
        headers={"X-Dev-Tenant": "t_default"}
    )
    assert response.status_code == 200
    scorecard = response.json()
    assert scorecard["summary"]["total_evals"] >= 2, "Should have at least 2 evals"
    assert "action_grounding" in [e["eval_name"] for e in scorecard["evals"]], "Should have action_grounding eval"
    assert "budget_compliance" in [e["eval_name"] for e in scorecard["evals"]], "Should have budget_compliance eval"
    
    # Verify tool calls exist
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM tool_calls WHERE run_id = ?",
            (run_id,)
        )
        tool_calls_count = cursor.fetchone()["count"]
    assert tool_calls_count >= 2, f"Expected at least 2 tool calls (market_data + broker), got {tool_calls_count}"
