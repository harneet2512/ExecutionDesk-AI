"""Tests for prediction market DAG nodes.

Tests cover:
- prediction_research node outputs correct artifact shape
- prediction_risk node enforces max exposure
- DAG node sequence for PREDICTION asset class
"""
import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock


class TestPredictionResearchNode:
    """Tests for the prediction_research DAG node."""

    @pytest.mark.asyncio
    @patch("backend.orchestrator.nodes.prediction_research.httpx.Client")
    async def test_outputs_correct_artifact_shape(self, mock_client_cls, test_db):
        from backend.orchestrator.nodes.prediction_research import execute
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        # Create a run with prediction intent
        run_id = new_id("run_")
        node_id = new_id("node_")
        tenant_id = "t_default"

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO runs (run_id, tenant_id, status, execution_mode, asset_class, intent_json, created_at)
                   VALUES (?, ?, 'RUNNING', 'PAPER', 'PREDICTION_MARKET', ?, ?)""",
                (run_id, tenant_id, json.dumps({
                    "action": "BUY",
                    "market_query": "Trump winning",
                    "outcome": "YES",
                    "budget_usd": 10.0,
                }), now_iso())
            )
            cursor.execute(
                """INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at)
                   VALUES (?, ?, 'prediction_research', 'prediction_research', 'RUNNING', ?)""",
                (node_id, run_id, now_iso())
            )
            conn.commit()

        # Mock CLOB market search response -- Gamma API returns events with nested markets
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "evt_1",
                "slug": "will-trump-win-2024",
                "title": "Will Trump win the 2024 election?",
                "markets": [
                    {
                        "conditionId": "cond_123",
                        "question": "Will Trump win the 2024 election?",
                        "slug": "will-trump-win-2024",
                        "outcomes": '["Yes", "No"]',
                        "outcomePrices": '[0.62, 0.38]',
                        "clobTokenIds": '["tok_yes", "tok_no"]',
                        "volume": "5000000",
                        "liquidity": "1000000",
                        "active": True,
                        "endDate": "2024-11-05",
                    }
                ],
            }
        ]
        mock_response.raise_for_status = MagicMock()

        instance = MagicMock()
        instance.get.return_value = mock_response
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        result = await execute(run_id, node_id, tenant_id)

        # Verify output shape
        assert "market" in result
        assert "yes_price" in result
        assert "no_price" in result
        assert "volume" in result
        assert "question" in result
        assert "token_id" in result

        assert isinstance(result["yes_price"], float)
        assert 0.0 <= result["yes_price"] <= 1.0


class TestPredictionRiskNode:
    """Tests for the prediction_risk DAG node."""

    @pytest.mark.asyncio
    async def test_enforces_max_exposure(self, test_db):
        from backend.orchestrator.nodes.prediction_risk import execute
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        run_id = new_id("run_")
        node_id = new_id("node_")
        research_node_id = new_id("node_")
        tenant_id = "t_default"

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO runs (run_id, tenant_id, status, execution_mode, asset_class, intent_json, created_at)
                   VALUES (?, ?, 'RUNNING', 'PAPER', 'PREDICTION_MARKET', ?, ?)""",
                (run_id, tenant_id, json.dumps({
                    "budget_usd": 500.0,
                    "outcome": "YES",
                }), now_iso())
            )
            # Create research node output
            cursor.execute(
                """INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at, outputs_json)
                   VALUES (?, ?, 'prediction_research', 'prediction_research', 'COMPLETED', ?, ?)""",
                (research_node_id, run_id, now_iso(), json.dumps({
                    "market": {"condition_id": "cond_1", "question": "Test?"},
                    "yes_price": 0.60,
                    "no_price": 0.40,
                    "token_id": "tok_yes",
                    "volume": "1000000",
                    "question": "Test market?",
                }))
            )
            cursor.execute(
                """INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at)
                   VALUES (?, ?, 'prediction_risk', 'prediction_risk', 'RUNNING', ?)""",
                (node_id, run_id, now_iso())
            )
            conn.commit()

        result = await execute(run_id, node_id, tenant_id)

        assert "max_notional" in result
        assert "budget_usd" in result
        assert "risk_summary" in result
        # Max exposure should cap budget to configured limit
        assert result["max_notional"] <= result["budget_usd"]


class TestPredictionSignalsNode:
    """Tests for the prediction_signals DAG node."""

    @pytest.mark.asyncio
    async def test_outputs_signal_data(self, test_db):
        from backend.orchestrator.nodes.prediction_signals import execute
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        run_id = new_id("run_")
        node_id = new_id("node_")
        research_node_id = new_id("node_")
        tenant_id = "t_default"

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO runs (run_id, tenant_id, status, execution_mode, asset_class, intent_json, created_at)
                   VALUES (?, ?, 'RUNNING', 'PAPER', 'PREDICTION_MARKET', ?, ?)""",
                (run_id, tenant_id, json.dumps({
                    "action": "BUY",
                    "outcome": "YES",
                    "budget_usd": 10.0,
                }), now_iso())
            )
            cursor.execute(
                """INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at, outputs_json)
                   VALUES (?, ?, 'prediction_research', 'prediction_research', 'COMPLETED', ?, ?)""",
                (research_node_id, run_id, now_iso(), json.dumps({
                    "market": {"condition_id": "cond_1", "question": "Test?"},
                    "yes_price": 0.55,
                    "no_price": 0.45,
                    "token_id": "tok_yes",
                    "volume": "2000000",
                    "liquidity": "500000",
                    "question": "Test market?",
                }))
            )
            cursor.execute(
                """INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at)
                   VALUES (?, ?, 'prediction_signals', 'prediction_signals', 'RUNNING', ?)""",
                (node_id, run_id, now_iso())
            )
            conn.commit()

        result = await execute(run_id, node_id, tenant_id)

        assert "market_sentiment" in result
        assert "yes_price" in result
        assert "liquidity_score" in result


class TestPredictionMarketExecution:
    """Tests for prediction market order execution in the execution node."""

    @pytest.mark.asyncio
    async def test_paper_prediction_execution_creates_filled_order(self, test_db):
        """PAPER mode prediction market execution simulates a filled limit order."""
        from backend.orchestrator.nodes.execution_node import execute
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        run_id = new_id("run_")
        node_id = new_id("node_")
        tenant_id = "t_default"

        proposal = {
            "orders": [{
                "symbol": "cond_trump_2028",
                "side": "BUY",
                "notional_usd": 10.0,
                "outcome": "YES",
                "limit_price": 0.55,
            }]
        }

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO runs (run_id, tenant_id, status, execution_mode,
                   asset_class, trade_proposal_json, created_at)
                   VALUES (?, ?, 'RUNNING', 'PAPER', 'PREDICTION_MARKET', ?, ?)""",
                (run_id, tenant_id, json.dumps(proposal), now_iso()),
            )
            cursor.execute(
                """INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at)
                   VALUES (?, ?, 'execution', 'execution', 'RUNNING', ?)""",
                (node_id, run_id, now_iso()),
            )
            conn.commit()

        result = await execute(run_id, node_id, tenant_id)

        assert result["fill_confirmed"] is True
        assert len(result["order_ids"]) == 1
        assert "prediction market" in result["safe_summary"].lower()

        # Verify order persisted as FILLED
        order_id = result["order_ids"][0]
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["provider"] == "PAPER_POLYMARKET"
            assert row["status"] == "FILLED"
            assert float(row["avg_fill_price"]) == 0.55

    @pytest.mark.asyncio
    async def test_paper_prediction_execution_computes_qty(self, test_db):
        """Verify qty = notional / limit_price for paper prediction fills."""
        from backend.orchestrator.nodes.execution_node import execute
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        run_id = new_id("run_")
        node_id = new_id("node_")
        tenant_id = "t_default"

        proposal = {
            "orders": [{
                "symbol": "cond_election",
                "side": "BUY",
                "notional_usd": 20.0,
                "outcome": "NO",
                "limit_price": 0.40,
            }]
        }

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO runs (run_id, tenant_id, status, execution_mode,
                   asset_class, trade_proposal_json, created_at)
                   VALUES (?, ?, 'RUNNING', 'PAPER', 'PREDICTION_MARKET', ?, ?)""",
                (run_id, tenant_id, json.dumps(proposal), now_iso()),
            )
            cursor.execute(
                """INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at)
                   VALUES (?, ?, 'execution', 'execution', 'RUNNING', ?)""",
                (node_id, run_id, now_iso()),
            )
            conn.commit()

        result = await execute(run_id, node_id, tenant_id)

        order_id = result["order_ids"][0]
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT qty FROM orders WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()
            # qty = 20.0 / 0.40 = 50.0
            assert abs(float(row["qty"]) - 50.0) < 0.01
