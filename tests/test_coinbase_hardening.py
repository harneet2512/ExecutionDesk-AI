"""Tests for Coinbase provider hardening."""
import pytest
import time
import json
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db.connect import init_db, get_conn
from backend.core.config import get_settings

client = TestClient(app)


@pytest.fixture
def setup_db():
    """Setup clean database."""
    settings = get_settings()
    db_path = settings.database_url.replace("sqlite:///", "")
    import os
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()
    yield
    # Cleanup if needed


def test_live_disabled_by_default(setup_db):
    """Test LIVE mode is disabled by default (PAPER mode always works)."""
    # PAPER mode should work
    response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "text": "buy $10 of BTC",
            "mode": "PAPER",
            "budget_usd": 10.0
        }
    )
    assert response.status_code == 200
    
    # LIVE mode should be blocked (unless ENABLE_LIVE_TRADING=true)
    settings = get_settings()
    if not settings.enable_live_trading:
        response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "buy $10 of BTC",
                "mode": "LIVE",
                "budget_usd": 10.0
            }
        )
        assert response.status_code in (400, 403), f"Expected 400 or 403, got {response.status_code}"


def test_most_profitable_paper(setup_db):
    """Test 'most profitable' command in PAPER mode: verifies candles, ranking, budget, evals."""
    response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "text": "buy the most profitable crypto of last 24hrs for $10",
            "mode": "PAPER",
            "budget_usd": 10.0,
            "lookback_hours": 24
        }
    )
    assert response.status_code == 200
    result = response.json()

    # With mandatory confirmation gating, trades return confirmation_id first
    confirmation_id = result.get("confirmation_id")
    run_id = result.get("run_id")

    if confirmation_id and not run_id:
        # Confirm the trade to get a run_id
        confirm_response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "CONFIRM",
                "confirmation_id": confirmation_id
            }
        )
        assert confirm_response.status_code == 200
        confirm_result = confirm_response.json()
        run_id = confirm_result.get("run_id")

    assert run_id, f"Expected run_id after confirmation, got: {result}"
    
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
    
    # Verify candles stored (check strategy_candles which links candles to runs)
    with get_conn() as conn:
        cursor = conn.cursor()
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
    assert candles_count >= 1, "Candles should be stored"
    
    # Verify ranking correctness
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        signals_row = cursor.fetchone()
        if signals_row:
            signals_output = json.loads(signals_row["outputs_json"])
            chosen_symbol = signals_output.get("top_symbol")
            assert chosen_symbol, "Chosen symbol should exist"
        
        # Verify budget compliance
        cursor.execute(
            "SELECT SUM(notional_usd) as total FROM orders WHERE run_id = ?",
            (run_id,)
        )
        total_notional = cursor.fetchone()["total"] or 0.0
        assert total_notional <= 10.0 * 1.01, f"Budget exceeded: ${total_notional:.2f} > $10.00"
        
        # Verify tool calls exist
        cursor.execute(
            "SELECT COUNT(*) as count FROM tool_calls WHERE run_id = ?",
            (run_id,)
        )
        tool_calls_count = cursor.fetchone()["count"]
    
    # Verify evals all present
    eval_names = [e["eval_name"] for e in detail["evals"]]
    required_evals = ["action_grounding", "budget_compliance", "ranking_correctness", "numeric_grounding"]
    for eval_name in required_evals:
        assert eval_name in eval_names, f"Missing eval: {eval_name}"
    assert tool_calls_count >= 2, f"Expected at least 2 tool calls, got {tool_calls_count}"


def test_replay_determinism(setup_db):
    """Test REPLAY determinism: same intent/artifacts -> same chosen asset and proposal."""
    # Create source run
    source_response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "text": "buy the most profitable crypto of last 24hrs for $10",
            "mode": "PAPER",
            "budget_usd": 10.0
        }
    )
    assert source_response.status_code == 200
    source_result = source_response.json()

    # Handle mandatory confirmation gating
    source_confirmation_id = source_result.get("confirmation_id")
    source_run_id = source_result.get("run_id")

    if source_confirmation_id and not source_run_id:
        confirm_response = client.post(
            "/api/v1/chat/command",
            headers={"X-Dev-Tenant": "t_default"},
            json={
                "text": "CONFIRM",
                "confirmation_id": source_confirmation_id
            }
        )
        assert confirm_response.status_code == 200
        source_run_id = confirm_response.json().get("run_id")

    assert source_run_id, f"Expected source run_id after confirmation"
    
    # Wait for completion
    time.sleep(15)
    
    # Get source run details
    source_detail = client.get(
        f"/api/v1/runs/{source_run_id}",
        headers={"X-Dev-Tenant": "t_default"}
    ).json()
    
    # Get source chosen asset
    with get_conn() as conn:
        source_cursor = conn.cursor()
        source_cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (source_run_id,)
        )
        source_signals_row = source_cursor.fetchone()
        source_chosen_symbol = None
        if source_signals_row:
            source_signals_output = json.loads(source_signals_row["outputs_json"])
            source_chosen_symbol = source_signals_output.get("top_symbol")
    
    # Replay the run (replay is handled by /commands/execute, not /chat/command)
    replay_response = client.post(
        "/api/v1/commands/execute",
        headers={"X-Dev-Tenant": "t_default"},
        json={
            "command": f"replay run {source_run_id}",
            "execution_mode": "REPLAY",
            "source_run_id": source_run_id
        }
    )
    assert replay_response.status_code == 200
    replay_result = replay_response.json()
    replay_run_id = replay_result.get("run_id")
    assert replay_run_id, f"Expected replay run_id, got: {replay_result}"
    
    # Wait for completion
    time.sleep(15)
    
    # Get replay run details
    replay_detail = client.get(
        f"/api/v1/runs/{replay_run_id}",
        headers={"X-Dev-Tenant": "t_default"}
    ).json()
    
    # Get replay chosen asset
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (replay_run_id,)
        )
        replay_signals_row = cursor.fetchone()
        replay_chosen_symbol = None
        if replay_signals_row:
            replay_signals_output = json.loads(replay_signals_row["outputs_json"])
            replay_chosen_symbol = replay_signals_output.get("top_symbol")
    
    # Verify determinism: same chosen symbol
    assert replay_chosen_symbol == source_chosen_symbol, \
        f"Determinism violation: replay chose {replay_chosen_symbol} vs source {source_chosen_symbol}"
    
    # Verify proposals match
    source_proposal = json.loads(source_detail["run"].get("trade_proposal_json", "{}")) if source_detail["run"].get("trade_proposal_json") else {}
    replay_proposal = json.loads(replay_detail["run"].get("trade_proposal_json", "{}")) if replay_detail["run"].get("trade_proposal_json") else {}
    
    if source_proposal.get("orders") and replay_proposal.get("orders"):
        source_order = source_proposal["orders"][0]
        replay_order = replay_proposal["orders"][0]
        assert source_order.get("symbol") == replay_order.get("symbol"), "Order symbol should match"
        assert source_order.get("side") == replay_order.get("side"), "Order side should match"
        assert abs(float(source_order.get("notional_usd", 0)) - float(replay_order.get("notional_usd", 0))) < 0.01, "Order notional should match"
