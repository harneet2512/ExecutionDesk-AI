"""Tests for prediction market DAG routing in the orchestrator runner.

Tests cover:
- PREDICTION_MARKET asset_class routes to prediction-specific nodes
- CRYPTO asset_class still uses default crypto nodes (regression)
- PREDICTION asset_class also routes to prediction nodes
"""
import pytest
import json
from unittest.mock import patch, AsyncMock

from backend.orchestrator.runner import _execute_run_body
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso


def _create_test_run(tenant_id: str, asset_class: str, command_text: str = "buy yes on Trump winning for $10") -> str:
    """Helper to create a test run with the given asset_class."""
    run_id = new_id("run_")
    intent = {
        "action": "BUY",
        "market_query": "Trump winning",
        "outcome": "YES",
        "budget_usd": 10.0,
    }
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO runs (
                run_id, tenant_id, status, execution_mode, asset_class,
                command_text, parsed_intent_json, intent_json, created_at
            ) VALUES (?, ?, 'CREATED', 'PAPER', ?, ?, ?, ?, ?)""",
            (
                run_id, tenant_id, asset_class,
                command_text, json.dumps(intent), json.dumps(intent), now_iso(),
            ),
        )
        conn.commit()
    return run_id


class TestPredictionDAGRouting:
    """Tests for prediction market DAG node selection."""

    @pytest.mark.asyncio
    async def test_prediction_market_uses_prediction_nodes(self, test_db):
        """When asset_class is PREDICTION_MARKET, the DAG should use prediction-specific nodes."""
        tenant_id = "t_default"
        run_id = _create_test_run(tenant_id, "PREDICTION_MARKET")

        # We will track which node functions are called
        called_nodes = []

        async def mock_node(run_id, node_id, tenant_id):
            # Extract the node name from the DB
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM dag_nodes WHERE node_id = ?", (node_id,))
                row = cursor.fetchone()
                if row:
                    called_nodes.append(row["name"])
            return {"status": "ok"}

        # Patch all node execute functions to track calls
        with patch("backend.orchestrator.runner.prediction_research_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.prediction_signals_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.prediction_risk_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.strategy_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.proposal_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.policy_check_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.approval_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.execution_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.post_trade_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.eval_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner._emit_event", new_callable=AsyncMock):

            await _execute_run_body(run_id, None)

        # Verify prediction-specific nodes are used (first three)
        assert "prediction_research" in called_nodes, f"prediction_research not in {called_nodes}"
        assert "prediction_signals" in called_nodes, f"prediction_signals not in {called_nodes}"
        assert "prediction_risk" in called_nodes, f"prediction_risk not in {called_nodes}"

        # Verify standard crypto nodes are NOT used
        assert "research" not in called_nodes, "Standard research node should not be used for prediction runs"
        assert "signals" not in called_nodes, "Standard signals node should not be used for prediction runs"
        assert "risk" not in called_nodes, "Standard risk node should not be used for prediction runs"

    @pytest.mark.asyncio
    async def test_crypto_uses_standard_nodes(self, test_db):
        """Regression: CRYPTO asset_class should still use standard nodes."""
        tenant_id = "t_default"
        run_id = _create_test_run(tenant_id, "CRYPTO", command_text="buy $10 of BTC")

        called_nodes = []

        async def mock_node(run_id, node_id, tenant_id):
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM dag_nodes WHERE node_id = ?", (node_id,))
                row = cursor.fetchone()
                if row:
                    called_nodes.append(row["name"])
            return {"status": "ok"}

        with patch("backend.orchestrator.runner.research_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.news_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.signals_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.risk_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.strategy_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.proposal_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.policy_check_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.approval_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.execution_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.post_trade_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.eval_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner._emit_event", new_callable=AsyncMock):

            await _execute_run_body(run_id, None)

        # Verify standard nodes are used
        assert "research" in called_nodes, f"Standard research node should be used for crypto runs, got {called_nodes}"

        # Verify prediction nodes are NOT used
        assert "prediction_research" not in called_nodes
        assert "prediction_signals" not in called_nodes
        assert "prediction_risk" not in called_nodes

    @pytest.mark.asyncio
    async def test_prediction_alias_routes_correctly(self, test_db):
        """PREDICTION (without _MARKET suffix) should also route to prediction nodes."""
        tenant_id = "t_default"
        run_id = _create_test_run(tenant_id, "PREDICTION")

        called_nodes = []

        async def mock_node(run_id, node_id, tenant_id):
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM dag_nodes WHERE node_id = ?", (node_id,))
                row = cursor.fetchone()
                if row:
                    called_nodes.append(row["name"])
            return {"status": "ok"}

        with patch("backend.orchestrator.runner.prediction_research_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.prediction_signals_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.prediction_risk_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.strategy_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.proposal_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.policy_check_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.approval_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.execution_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.post_trade_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner.eval_execute", side_effect=mock_node), \
             patch("backend.orchestrator.runner._emit_event", new_callable=AsyncMock):

            await _execute_run_body(run_id, None)

        assert "prediction_research" in called_nodes
        assert "prediction_signals" in called_nodes
        assert "prediction_risk" in called_nodes
