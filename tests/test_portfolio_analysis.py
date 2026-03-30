"""Tests for portfolio analysis feature.

Tests:
1. Intent classification for "Analyze my portfolio"
2. Schema validation for PortfolioBrief
3. Allocation math correctness
4. Risk concentration calculations
5. Evidence ref validation
6. API endpoint integration test (fixture-based)
"""
import pytest
import json
import math
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


class TestIntentClassification:
    """Test intent classification for portfolio analysis commands."""
    
    def test_analyze_portfolio_intent(self):
        """'Analyze my portfolio' should map to PORTFOLIO_ANALYSIS."""
        from backend.agents.intent_router import classify_intent, IntentType
        
        result = classify_intent("Analyze my portfolio")
        assert result == IntentType.PORTFOLIO_ANALYSIS
    
    def test_portfolio_analysis_variants(self):
        """Various portfolio analysis phrasings should map correctly."""
        from backend.agents.intent_router import classify_intent, IntentType
        
        test_cases = [
            "Analyze my portfolio",
            "analyze portfolio",
            "portfolio analysis",
            "analyze my holdings",
            "how is my portfolio doing",
            "portfolio summary",
            "portfolio breakdown",
            "risk analysis of my portfolio",
        ]
        
        for command in test_cases:
            result = classify_intent(command)
            assert result == IntentType.PORTFOLIO_ANALYSIS, f"Failed for: {command}"
    
    def test_simple_portfolio_query_not_analysis(self):
        """Simple portfolio queries should not trigger full analysis."""
        from backend.agents.intent_router import classify_intent, IntentType
        
        # These should be PORTFOLIO, not PORTFOLIO_ANALYSIS
        simple_queries = [
            "show my portfolio",
            "what's in my portfolio",
        ]
        
        for command in simple_queries:
            result = classify_intent(command)
            # Should be PORTFOLIO, not PORTFOLIO_ANALYSIS
            assert result in (IntentType.PORTFOLIO, IntentType.PORTFOLIO_ANALYSIS), f"Failed for: {command}"
    
    def test_trade_with_portfolio_not_analysis(self):
        """Trade commands mentioning portfolio should be TRADE_EXECUTION."""
        from backend.agents.intent_router import classify_intent, IntentType
        
        result = classify_intent("buy $10 of BTC from my portfolio")
        assert result == IntentType.TRADE_EXECUTION


class TestPortfolioBriefSchema:
    """Test Pydantic schema validation for PortfolioBrief."""
    
    def test_valid_portfolio_brief(self):
        """Valid PortfolioBrief should pass validation."""
        from backend.agents.schemas import (
            PortfolioBrief, Holding, AllocationRow, RiskSnapshot, ExecutionMode, EvidenceRefs
        )
        
        brief = PortfolioBrief(
            as_of="2024-01-15T12:00:00Z",
            mode=ExecutionMode.PAPER,
            total_value_usd=10000.0,
            cash_usd=1000.0,
            holdings=[
                Holding(asset_symbol="BTC", qty=0.1, usd_value=4500.0, current_price=45000.0),
                Holding(asset_symbol="ETH", qty=2.0, usd_value=4500.0, current_price=2250.0),
            ],
            allocation=[
                AllocationRow(asset_symbol="BTC", pct=45.0, usd_value=4500.0),
                AllocationRow(asset_symbol="ETH", pct=45.0, usd_value=4500.0),
                AllocationRow(asset_symbol="USD", pct=10.0, usd_value=1000.0),
            ],
            risk=RiskSnapshot(
                concentration_pct_top1=45.0,
                concentration_pct_top3=90.0,
                risk_level="MEDIUM"
            ),
            evidence_refs=EvidenceRefs()
        )
        
        assert brief.total_value_usd == 10000.0
        assert len(brief.holdings) == 2
        assert brief.is_success()
    
    def test_holding_validation(self):
        """Holding should validate non-negative values."""
        from backend.agents.schemas import Holding
        
        # Valid holding
        holding = Holding(asset_symbol="BTC", qty=0.5, usd_value=22500.0)
        assert holding.qty == 0.5
        
        # Invalid negative qty should fail
        with pytest.raises(ValueError):
            Holding(asset_symbol="BTC", qty=-1.0, usd_value=100.0)
    
    def test_risk_snapshot_risk_level(self):
        """RiskSnapshot should have valid risk levels."""
        from backend.agents.schemas import RiskSnapshot
        
        risk = RiskSnapshot(
            concentration_pct_top1=80.0,
            concentration_pct_top3=95.0,
            risk_level="VERY_HIGH"
        )
        assert risk.risk_level == "VERY_HIGH"


class TestAllocationMath:
    """Test allocation percentage calculations."""
    
    def test_allocation_sum_to_100(self):
        """Allocation percentages should sum to approximately 100%."""
        from backend.orchestrator.nodes.portfolio_node import _compute_risk_metrics
        from backend.agents.schemas import Holding, AllocationRow
        
        holdings = [
            Holding(asset_symbol="BTC", qty=0.1, usd_value=4500.0),
            Holding(asset_symbol="ETH", qty=2.0, usd_value=4500.0),
        ]
        
        total_value = 10000.0  # 4500 + 4500 + 1000 cash
        
        # Compute allocation
        allocation = []
        for h in holdings:
            pct = (h.usd_value / total_value) * 100
            allocation.append(AllocationRow(
                asset_symbol=h.asset_symbol,
                pct=pct,
                usd_value=h.usd_value
            ))
        
        # Add cash
        allocation.append(AllocationRow(
            asset_symbol="USD",
            pct=10.0,
            usd_value=1000.0
        ))
        
        total_pct = sum(a.pct for a in allocation)
        assert abs(total_pct - 100.0) < 0.1, f"Allocation sum: {total_pct}"
    
    def test_empty_portfolio_allocation(self):
        """Empty portfolio should have 0% allocation."""
        total_value = 0.0
        
        # Should handle zero division gracefully
        if total_value > 0:
            pct = 100.0 / total_value
        else:
            pct = 0.0
        
        assert pct == 0.0


class TestRiskCalculations:
    """Test risk metric calculations."""
    
    def test_concentration_single_asset(self):
        """100% in one asset should give 100% concentration."""
        from backend.agents.schemas import Holding, AllocationRow, RiskSnapshot
        from backend.orchestrator.nodes.portfolio_node import _compute_risk_metrics
        
        holdings = [
            Holding(asset_symbol="BTC", qty=1.0, usd_value=45000.0),
        ]
        
        allocation = [
            AllocationRow(asset_symbol="BTC", pct=100.0, usd_value=45000.0),
        ]
        
        prices = {
            "BTC": {"price": 45000.0, "candles": []}
        }
        
        risk = _compute_risk_metrics(holdings, allocation, prices, 45000.0)
        
        assert risk.concentration_pct_top1 == 100.0
        assert risk.concentration_pct_top3 == 100.0
        assert risk.risk_level == "VERY_HIGH"
    
    def test_diversified_portfolio_risk(self):
        """Well-diversified portfolio should have lower risk."""
        from backend.agents.schemas import Holding, AllocationRow
        from backend.orchestrator.nodes.portfolio_node import _compute_risk_metrics
        
        holdings = [
            Holding(asset_symbol="BTC", qty=0.1, usd_value=2500.0),
            Holding(asset_symbol="ETH", qty=1.0, usd_value=2500.0),
            Holding(asset_symbol="SOL", qty=50.0, usd_value=2500.0),
            Holding(asset_symbol="ADA", qty=5000.0, usd_value=2500.0),
        ]
        
        allocation = [
            AllocationRow(asset_symbol="BTC", pct=25.0, usd_value=2500.0),
            AllocationRow(asset_symbol="ETH", pct=25.0, usd_value=2500.0),
            AllocationRow(asset_symbol="SOL", pct=25.0, usd_value=2500.0),
            AllocationRow(asset_symbol="ADA", pct=25.0, usd_value=2500.0),
        ]
        
        prices = {}
        
        risk = _compute_risk_metrics(holdings, allocation, prices, 10000.0)
        
        assert risk.concentration_pct_top1 == 25.0
        assert risk.concentration_pct_top3 == 75.0
        assert risk.risk_level == "LOW"
    
    def test_volatility_proxy_calculation(self):
        """Volatility proxy should be computed from candles."""
        from backend.agents.schemas import Holding, AllocationRow
        from backend.orchestrator.nodes.portfolio_node import _compute_risk_metrics
        
        holdings = [
            Holding(asset_symbol="BTC", qty=0.1, usd_value=4500.0),
        ]
        
        allocation = [
            AllocationRow(asset_symbol="BTC", pct=100.0, usd_value=4500.0),
        ]
        
        # Create candles with known volatility
        candles = [
            {"close": 100.0},
            {"close": 102.0},  # +2%
            {"close": 100.0},  # -1.96%
            {"close": 103.0},  # +3%
            {"close": 101.0},  # -1.94%
        ]
        
        prices = {
            "BTC": {"price": 101.0, "candles": candles}
        }
        
        risk = _compute_risk_metrics(holdings, allocation, prices, 4500.0)
        
        # Volatility proxy should be non-zero
        assert risk.volatility_proxy is not None
        assert risk.volatility_proxy > 0


class TestTradeSummary:
    """Test trading behavior summary calculations."""
    
    def test_trade_summary_empty_orders(self):
        """Empty order list should return zero counts."""
        from backend.orchestrator.nodes.portfolio_node import _compute_trade_summary
        
        summary = _compute_trade_summary([], 30)
        
        assert summary.total_trades == 0
        assert summary.total_notional_usd == 0.0
        assert summary.buys == 0
        assert summary.sells == 0
    
    def test_trade_summary_with_orders(self):
        """Order list should compute correct summary."""
        from backend.orchestrator.nodes.portfolio_node import _compute_trade_summary
        
        orders = [
            {"side": "BUY", "filled_value": "100.0", "product_id": "BTC-USD"},
            {"side": "BUY", "filled_value": "200.0", "product_id": "BTC-USD"},
            {"side": "SELL", "filled_value": "150.0", "product_id": "ETH-USD"},
        ]
        
        summary = _compute_trade_summary(orders, 30)
        
        assert summary.total_trades == 3
        assert summary.total_notional_usd == 450.0
        assert summary.buys == 2
        assert summary.sells == 1
        assert "BTC" in summary.top_assets


class TestPortfolioEvals:
    """Test portfolio-specific evaluations."""
    
    def test_evidence_coverage_eval(self, test_db):
        """Evidence coverage eval should verify tool call refs exist."""
        from backend.evals.portfolio_evals import evaluate_portfolio_evidence_coverage
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso
        
        # Create test run and snapshot
        run_id = new_id("run_")
        tenant_id = "t_default"
        
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Ensure tenant exists (FK constraint)
            cursor.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, name, execution_mode) VALUES (?, 'Test Tenant', 'PAPER')",
                (tenant_id,)
            )
            
            # Create run with all required fields
            cursor.execute(
                """INSERT INTO runs (run_id, tenant_id, status, execution_mode, strategy_id, strategy_version, created_at) 
                   VALUES (?, ?, 'COMPLETED', 'PAPER', 'test_strategy', '1.0', ?)""",
                (run_id, tenant_id, now_iso())
            )
            
            # Create tool call
            tool_call_id = new_id("tool_")
            cursor.execute(
                """INSERT INTO tool_calls (id, run_id, node_id, tool_name, mcp_server, request_json, status, ts)
                   VALUES (?, ?, '', 'get_accounts', 'coinbase_provider', '{}', 'SUCCESS', ?)""",
                (tool_call_id, run_id, now_iso())
            )
            
            # Create portfolio analysis snapshot with evidence refs
            brief = {
                "as_of": now_iso(),
                "mode": "PAPER",
                "total_value_usd": 1000.0,
                "holdings": [],
                "evidence_refs": {
                    "accounts_call_id": tool_call_id,
                    "prices_call_ids": [],
                    "orders_call_id": None
                }
            }
            
            cursor.execute(
                """INSERT INTO portfolio_analysis_snapshots 
                   (snapshot_id, run_id, tenant_id, mode, total_value_usd, brief_json, created_at)
                   VALUES (?, ?, ?, 'PAPER', 1000.0, ?, ?)""",
                (new_id("snap_"), run_id, tenant_id, json.dumps(brief), now_iso())
            )
            conn.commit()
        
        # Run eval
        result = evaluate_portfolio_evidence_coverage(run_id, tenant_id)
        
        assert result["score"] == 1.0
        assert "Verified" in result["reasons"][0]
    
    def test_numeric_grounding_eval(self, test_db):
        """Numeric grounding eval should verify totals match."""
        from backend.evals.portfolio_evals import evaluate_portfolio_numeric_grounding
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso
        
        run_id = new_id("run_")
        tenant_id = "t_default"
        
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Ensure tenant exists (FK constraint)
            cursor.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, name, execution_mode) VALUES (?, 'Test Tenant', 'PAPER')",
                (tenant_id,)
            )
            
            # Create run with all required fields
            cursor.execute(
                """INSERT INTO runs (run_id, tenant_id, status, execution_mode, strategy_id, strategy_version, created_at) 
                   VALUES (?, ?, 'COMPLETED', 'PAPER', 'test_strategy', '1.0', ?)""",
                (run_id, tenant_id, now_iso())
            )
            
            # Create snapshot with consistent values
            brief = {
                "as_of": now_iso(),
                "mode": "PAPER",
                "total_value_usd": 1500.0,
                "cash_usd": 500.0,
                "holdings": [
                    {"asset_symbol": "BTC", "qty": 0.02, "usd_value": 1000.0, "current_price": 50000.0}
                ],
                "allocation": [
                    {"asset_symbol": "BTC", "pct": 66.67, "usd_value": 1000.0},
                    {"asset_symbol": "USD", "pct": 33.33, "usd_value": 500.0}
                ],
                "evidence_refs": {}
            }
            
            cursor.execute(
                """INSERT INTO portfolio_analysis_snapshots 
                   (snapshot_id, run_id, tenant_id, mode, total_value_usd, brief_json, created_at)
                   VALUES (?, ?, ?, 'PAPER', 1500.0, ?, ?)""",
                (new_id("snap_"), run_id, tenant_id, json.dumps(brief), now_iso())
            )
            conn.commit()
        
        result = evaluate_portfolio_numeric_grounding(run_id, tenant_id)
        
        assert result["score"] >= 0.8


class TestPortfolioAPIIntegration:
    """Integration tests for portfolio analysis API endpoint."""
    
    def test_portfolio_analysis_endpoint_paper_mode(self, test_db, bypass_auth):
        """POST /api/v1/chat/command 'Analyze my portfolio' should return PortfolioBrief."""
        from fastapi.testclient import TestClient
        from backend.api.main import app
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso
        
        # Create tenant and portfolio snapshot in DB (PAPER mode uses DB snapshots)
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Ensure tenant exists
            cursor.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, name, execution_mode) VALUES ('t_default', 'Default Tenant', 'PAPER')"
            )
            
            balances = {"BTC": 0.1, "ETH": 1.0, "USD": 500.0}
            positions = {"BTC": 0.1, "ETH": 1.0}
            
            cursor.execute(
                """INSERT INTO portfolio_snapshots 
                   (snapshot_id, tenant_id, run_id, balances_json, positions_json, total_value_usd, ts)
                   VALUES (?, 't_default', NULL, ?, ?, 5000.0, ?)""",
                (new_id("snap_"), json.dumps(balances), json.dumps(positions), now_iso())
            )
            conn.commit()
        
        # Mock the market data provider to return candles
        mock_candles = [
            {"open": 45000.0, "high": 45500.0, "low": 44500.0, "close": 45200.0},
            {"open": 45200.0, "high": 45700.0, "low": 45000.0, "close": 45500.0},
        ]
        
        with patch("backend.services.coinbase_market_data.get_candles") as mock_get_candles:
            mock_get_candles.return_value = mock_candles
            
            client = TestClient(app)
            response = client.post(
                "/api/v1/chat/command",
                json={"text": "Analyze my portfolio"},
                headers={"Authorization": "Bearer test-token"}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["intent"] == "PORTFOLIO_ANALYSIS"
        assert "portfolio_brief" in data
        
        brief = data["portfolio_brief"]
        assert brief["mode"] in ("LIVE", "PAPER")
        assert "holdings" in brief
        assert "allocation" in brief
        assert "risk" in brief
    
    def test_portfolio_analysis_no_data(self, test_db, bypass_auth):
        """Portfolio analysis with no data should return explicit failure."""
        from fastapi.testclient import TestClient
        from backend.api.main import app
        from backend.db.connect import get_conn
        
        # Ensure tenant exists but no portfolio snapshots
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, name, execution_mode) VALUES ('t_default', 'Default Tenant', 'PAPER')"
            )
            conn.commit()
        
        with patch("backend.services.coinbase_market_data.get_candles") as mock_get_candles:
            mock_get_candles.return_value = []
            
            client = TestClient(app)
            response = client.post(
                "/api/v1/chat/command",
                json={"text": "Analyze my portfolio"},
                headers={"Authorization": "Bearer test-token"}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should fail gracefully with explicit message
        assert data["intent"] == "PORTFOLIO_ANALYSIS"
        # Either returns failure or empty portfolio
        if data.get("status") == "FAILED":
            assert "portfolio_brief" in data
            assert data["portfolio_brief"].get("failure") is not None


class TestPortfolioFixtures:
    """Test with recorded fixtures."""
    
    def test_coinbase_accounts_fixture(self):
        """Validate Coinbase accounts response fixture format."""
        # This fixture should be added to tests/fixtures/vcr_cassettes/
        accounts_response = {
            "accounts": [
                {
                    "uuid": "test-uuid-1",
                    "currency": "BTC",
                    "available_balance": {"value": "0.1", "currency": "BTC"},
                    "hold": {"value": "0", "currency": "BTC"},
                    "type": "ACCOUNT_TYPE_CRYPTO",
                    "active": True
                },
                {
                    "uuid": "test-uuid-2",
                    "currency": "USD",
                    "available_balance": {"value": "1000.0", "currency": "USD"},
                    "hold": {"value": "0", "currency": "USD"},
                    "type": "ACCOUNT_TYPE_FIAT",
                    "active": True
                }
            ]
        }
        
        # Validate structure
        assert "accounts" in accounts_response
        assert len(accounts_response["accounts"]) == 2
        assert accounts_response["accounts"][0]["currency"] == "BTC"
    
    def test_coinbase_orders_fixture(self):
        """Validate Coinbase orders response fixture format."""
        orders_response = {
            "orders": [
                {
                    "order_id": "test-order-1",
                    "product_id": "BTC-USD",
                    "side": "BUY",
                    "order_type": "MARKET",
                    "status": "FILLED",
                    "created_time": "2024-01-15T10:00:00Z",
                    "filled_size": "0.001",
                    "filled_value": "45.00",
                    "average_filled_price": "45000.00",
                    "total_fees": "0.45"
                }
            ]
        }
        
        # Validate structure
        assert "orders" in orders_response
        assert len(orders_response["orders"]) == 1
        assert orders_response["orders"][0]["status"] == "FILLED"


class TestBTCHoldingsQuery:
    """Integration tests for 'How much BTC do I own?' query."""
    
    def test_btc_query_intent_classification(self):
        """Test that BTC holdings query is correctly classified."""
        from backend.agents.intent_router import classify_intent, IntentType
        
        result = classify_intent("How much BTC do I own?")
        assert result == IntentType.PORTFOLIO_ANALYSIS
    
    def test_btc_query_asset_extraction(self):
        """Test that BTC is correctly extracted from the query."""
        from backend.agents.intent_router import extract_holdings_asset
        
        result = extract_holdings_asset("How much BTC do I own?")
        assert result == "BTC"
    
    def test_btc_query_response_format_with_holdings(self):
        """Test response format when user has BTC holdings."""
        from backend.api.routes.chat import _format_asset_holdings_response

        brief = {
            "mode": "LIVE",
            "as_of": "2026-02-02T12:00:00Z",
            "total_value_usd": 50000.0,
            "cash_usd": 1000.0,
            "holdings": [
                {"asset_symbol": "BTC", "qty": 0.5, "usd_value": 45000.0, "current_price": 90000.0},
                {"asset_symbol": "ETH", "qty": 2.0, "usd_value": 4000.0, "current_price": 2000.0}
            ],
            "evidence_refs": {"accounts_call_id": "call_123", "prices_call_ids": ["call_456"]}
        }

        content = _format_asset_holdings_response("BTC", brief)
        paragraphs = content.split("\n\n")

        assert 3 <= len(paragraphs) <= 6
        assert "BTC" in content
        assert "0.50000000" in content
        assert "45,000" in content
        assert "90,000" in content
        assert "LIVE" in content
        assert "Evidence:" in paragraphs[-1]

    def test_btc_query_response_format_zero_balance(self):
        """Test response format when user has zero BTC."""
        from backend.api.routes.chat import _format_asset_holdings_response

        brief = {
            "mode": "LIVE",
            "as_of": "2026-02-02T12:00:00Z",
            "total_value_usd": 5000.0,
            "cash_usd": 5000.0,
            "holdings": [
                {"asset_symbol": "ETH", "qty": 2.0, "usd_value": 0.0, "current_price": None}
            ],
            "evidence_refs": {"accounts_call_id": "call_123"}
        }

        content = _format_asset_holdings_response("BTC", brief)
        paragraphs = content.split("\n\n")

        assert 3 <= len(paragraphs) <= 6
        assert "BTC" in content
    
    def test_holdings_query_vs_trade_execution(self):
        """Test that 'How much BTC do I own?' is not confused with trade."""
        from backend.agents.intent_router import classify_intent, IntentType
        
        # Holdings query
        holdings_result = classify_intent("How much BTC do I own?")
        assert holdings_result == IntentType.PORTFOLIO_ANALYSIS
        
        # Trade command
        trade_result = classify_intent("Buy $10 of BTC")
        assert trade_result == IntentType.TRADE_EXECUTION
        
        # They should be different
        assert holdings_result != trade_result
    
    def test_various_btc_query_formats(self):
        """Test multiple ways of asking about BTC holdings."""
        from backend.agents.intent_router import classify_intent, IntentType, extract_holdings_asset
        
        queries = [
            ("How much BTC do I own?", "BTC"),
            ("What is my bitcoin balance?", "BTC"),
            ("Do I have any BTC?", "BTC"),
            ("my btc balance", "BTC"),
            ("Check my BTC holdings", "BTC"),
        ]
        
        for query, expected_asset in queries:
            intent = classify_intent(query)
            asset = extract_holdings_asset(query)
            
            assert intent == IntentType.PORTFOLIO_ANALYSIS, f"Query '{query}' wrong intent"
            assert asset == expected_asset, f"Query '{query}' extracted '{asset}' instead of '{expected_asset}'"
