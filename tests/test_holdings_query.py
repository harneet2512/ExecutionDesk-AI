"""Unit tests for holdings query parsing and response formatting."""
import pytest
from backend.agents.intent_router import (
    classify_intent,
    IntentType,
    is_holdings_query,
    extract_holdings_asset,
)


class TestHoldingsQueryPatterns:
    """Test that holdings queries are correctly identified and parsed."""

    @pytest.mark.parametrize("query,expected_intent", [
        # Direct holdings questions
        ("How much BTC do I own?", IntentType.PORTFOLIO_ANALYSIS),
        ("How much bitcoin do I have?", IntentType.PORTFOLIO_ANALYSIS),
        ("How much ETH do I own", IntentType.PORTFOLIO_ANALYSIS),
        ("how much sol do i have", IntentType.PORTFOLIO_ANALYSIS),
        
        # Balance queries
        ("What is my BTC balance?", IntentType.PORTFOLIO_ANALYSIS),
        ("What is my ethereum balance", IntentType.PORTFOLIO_ANALYSIS),
        ("my btc balance", IntentType.PORTFOLIO_ANALYSIS),
        ("BTC balance", IntentType.PORTFOLIO_ANALYSIS),
        
        # Ownership queries
        ("Do I own any BTC?", IntentType.PORTFOLIO_ANALYSIS),
        ("Do I have any ETH?", IntentType.PORTFOLIO_ANALYSIS),
        ("do i own sol", IntentType.PORTFOLIO_ANALYSIS),
        
        # Show/check queries
        ("Show me my BTC holdings", IntentType.PORTFOLIO_ANALYSIS),
        ("Check my ETH balance", IntentType.PORTFOLIO_ANALYSIS),
        
        # What's queries
        ("What's my BTC?", IntentType.PORTFOLIO_ANALYSIS),
        ("whats my bitcoin balance", IntentType.PORTFOLIO_ANALYSIS),
    ])
    def test_holdings_query_intent_classification(self, query, expected_intent):
        """Test that holdings queries are classified as PORTFOLIO_ANALYSIS."""
        result = classify_intent(query)
        assert result == expected_intent, f"Query '{query}' should be {expected_intent}, got {result}"

    @pytest.mark.parametrize("query,should_match", [
        ("How much BTC do I own?", True),
        ("What is my ETH balance?", True),
        ("Do I own any SOL?", True),
        ("my bitcoin balance", True),
        ("Check my AVAX balance", True),
        
        # Should NOT match (not asset-specific)
        ("How is my portfolio doing?", False),
        ("Analyze my portfolio", False),
        ("What's the price of BTC?", False),  # Price query, not holdings
        ("Buy $10 of BTC", False),  # Trade execution
    ])
    def test_is_holdings_query(self, query, should_match):
        """Test the is_holdings_query helper function."""
        result = is_holdings_query(query)
        assert result == should_match, f"Query '{query}' holdings match should be {should_match}, got {result}"


class TestHoldingsAssetExtraction:
    """Test extraction of specific assets from holdings queries."""

    @pytest.mark.parametrize("query,expected_asset", [
        ("How much BTC do I own?", "BTC"),
        ("How much bitcoin do I have?", "BTC"),
        ("What is my ETH balance?", "ETH"),
        ("What is my ethereum balance", "ETH"),
        ("Do I own any SOL?", "SOL"),
        ("my solana balance", "SOL"),
        ("Check my MATIC balance", "MATIC"),
        ("What's my AVAX?", "AVAX"),
        ("How much ada do I have", "ADA"),
        ("Do I have any DOGE?", "DOGE"),
        ("What is my LTC holding?", "LTC"),
    ])
    def test_extract_holdings_asset(self, query, expected_asset):
        """Test asset extraction from various query formats."""
        result = extract_holdings_asset(query)
        assert result == expected_asset, f"Query '{query}' should extract {expected_asset}, got {result}"

    def test_extract_holdings_asset_unknown(self):
        """Test that unknown assets return None."""
        # Non-crypto terms should not match
        result = extract_holdings_asset("How much cash do I have?")
        assert result is None

    def test_extract_holdings_asset_case_insensitive(self):
        """Test that extraction is case-insensitive."""
        assert extract_holdings_asset("How much btc do I own?") == "BTC"
        assert extract_holdings_asset("How much BTC do I own?") == "BTC"
        assert extract_holdings_asset("How much Btc do I own?") == "BTC"


class TestIntentPriority:
    """Test that intent classification priority is correct."""

    def test_holdings_query_not_trade_execution(self):
        """Holdings queries should not be misclassified as trades."""
        # These contain crypto symbols but are NOT trade commands
        query = "How much BTC do I own?"
        result = classify_intent(query)
        assert result != IntentType.TRADE_EXECUTION
        assert result == IntentType.PORTFOLIO_ANALYSIS

    def test_trade_command_not_holdings(self):
        """Trade commands should still be classified correctly."""
        query = "Buy $10 of BTC"
        result = classify_intent(query)
        assert result == IntentType.TRADE_EXECUTION

    def test_explicit_analysis_takes_precedence(self):
        """Explicit portfolio analysis should work as before."""
        query = "Analyze my portfolio"
        result = classify_intent(query)
        assert result == IntentType.PORTFOLIO_ANALYSIS

    def test_general_portfolio_query(self):
        """General portfolio queries without specific assets."""
        # Without a specific asset and analysis keyword, goes to PORTFOLIO
        query = "Show my portfolio"
        result = classify_intent(query)
        # This should be either PORTFOLIO or PORTFOLIO_ANALYSIS depending on patterns
        assert result in (IntentType.PORTFOLIO, IntentType.PORTFOLIO_ANALYSIS)


class TestMarkdownFormatting:
    """Test markdown output formatting for portfolio responses."""

    def test_markdown_table_separator(self):
        """Ensure markdown tables use correct separator syntax."""
        from backend.api.routes.chat import _format_portfolio_analysis
        
        brief = {
            "mode": "LIVE",
            "as_of": "2026-02-02T12:00:00Z",
            "total_value_usd": 10000.0,
            "cash_usd": 500.0,
            "holdings": [
                {"asset_symbol": "BTC", "qty": 0.1, "usd_value": 9500.0, "current_price": 95000.0}
            ],
            "allocation": [
                {"asset_symbol": "BTC", "pct": 95.0, "usd_value": 9500.0}
            ],
            "risk": {"risk_level": "HIGH", "concentration_pct_top1": 95.0, "concentration_pct_top3": 95.0},
            "recommendations": [],
            "warnings": [],
            "evidence_refs": {}
        }
        
        content = _format_portfolio_analysis(brief)
        
        # Check that table separator uses dashes, not underscores
        assert "|-------|" in content or "|---|" in content
        assert "|_______|" not in content
        
        # Check table structure
        assert "| Asset |" in content
        assert "| BTC |" in content

    def test_asset_holdings_response_format(self):
        """Test focused asset response formatting."""
        from backend.api.routes.chat import _format_asset_holdings_response
        
        brief = {
            "mode": "LIVE",
            "as_of": "2026-02-02T12:00:00Z",
            "total_value_usd": 10000.0,
            "cash_usd": 500.0,
            "holdings": [
                {"asset_symbol": "BTC", "qty": 0.12345678, "usd_value": 9500.0, "current_price": 77000.0},
                {"asset_symbol": "ETH", "qty": 1.5, "usd_value": 4500.0, "current_price": 3000.0}
            ],
            "evidence_refs": {"accounts_call_id": "call_123", "prices_call_ids": ["call_456"]}
        }
        
        # Query for BTC
        content = _format_asset_holdings_response("BTC", brief)
        
        # Should have focused BTC answer
        assert "BTC" in content
        assert "0.12345678" in content
        assert "9500" in content or "9,500" in content
        assert "77,000" in content or "77000" in content
        
        # Should mention LIVE mode
        assert "LIVE" in content
        
        # Should have evidence refs
        assert "Evidence" in content or "API calls" in content

    def test_asset_holdings_response_zero_balance(self):
        """Test response when queried asset has zero balance."""
        from backend.api.routes.chat import _format_asset_holdings_response
        
        brief = {
            "mode": "LIVE",
            "as_of": "2026-02-02T12:00:00Z",
            "total_value_usd": 500.0,
            "cash_usd": 500.0,
            "holdings": [],  # No crypto holdings
            "evidence_refs": {"accounts_call_id": "call_123"}
        }
        
        # Query for BTC which is not in holdings
        content = _format_asset_holdings_response("BTC", brief)
        
        # Should explicitly state 0 balance
        assert "0" in content
        assert "BTC" in content
        assert "do not" in content.lower() or "don't" in content.lower() or "no" in content.lower()


class TestNotificationPolicy:
    """Test notification triggering policy."""

    def test_notification_recorded_on_skip(self):
        """Test that skipped notifications are recorded."""
        from backend.services.notifications.pushover import record_skipped_notification
        from backend.db.connect import get_conn, init_db
        from backend.core.config import get_settings
        import os
        
        # Initialize database to ensure notification_events table exists
        init_db()
        
        # Generate unique run_id for this test
        import uuid
        test_run_id = f"test_run_{uuid.uuid4().hex[:8]}"
        
        # Record a skipped notification
        record_skipped_notification(
            action="test_action",
            reason="Test reason",
            run_id=test_run_id
        )
        
        # Verify it was recorded
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM notification_events WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
                (test_run_id,)
            )
            row = cursor.fetchone()
            
            assert row is not None
            assert row["status"] == "skipped"
            assert row["action"] == "test_action"
            assert "Test reason" in row["payload_redacted"]
