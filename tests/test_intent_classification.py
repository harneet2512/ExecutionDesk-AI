"""Unit tests for intent classification router."""
import pytest
from backend.agents.intent_router import (
    classify_intent,
    IntentType,
    normalize_text,
    is_greeting,
    is_capabilities_help,
    is_out_of_scope,
    has_finance_keywords,
    has_trade_execution_keywords
)


class TestNormalization:
    """Test text normalization."""
    
    def test_normalize_lowercase(self):
        assert normalize_text("HELLO WORLD") == "hello world"
    
    def test_normalize_whitespace(self):
        assert normalize_text("hello    world") == "hello world"
        assert normalize_text("  hello  ") == "hello"
    
    def test_normalize_mixed(self):
        assert normalize_text("  HELLO   WORLD  ") == "hello world"


class TestGreetingIntent:
    """Test GREETING intent classification."""
    
    def test_simple_greetings(self):
        assert classify_intent("Hi") == IntentType.GREETING
        assert classify_intent("Hello") == IntentType.GREETING
        assert classify_intent("Hey") == IntentType.GREETING
        assert classify_intent("Yo") == IntentType.GREETING
    
    def test_greeting_with_punctuation(self):
        assert classify_intent("Hi!") == IntentType.GREETING
        assert classify_intent("Hello there!") == IntentType.GREETING
    
    def test_time_based_greetings(self):
        assert classify_intent("Good morning") == IntentType.GREETING
        assert classify_intent("Good afternoon") == IntentType.GREETING
        assert classify_intent("Good evening") == IntentType.GREETING
    
    def test_how_are_you(self):
        assert classify_intent("How are you?") == IntentType.GREETING


class TestCapabilitiesIntent:
    """Test CAPABILITIES_HELP intent classification."""
    
    def test_capabilities_keywords(self):
        assert classify_intent("What can you do?") == IntentType.CAPABILITIES_HELP
        assert classify_intent("What are your capabilities?") == IntentType.CAPABILITIES_HELP
        assert classify_intent("help") == IntentType.CAPABILITIES_HELP
        assert classify_intent("Help me") == IntentType.CAPABILITIES_HELP
    
    def test_examples_request(self):
        # "examples" alone triggers capabilities
        assert classify_intent("Show me some examples") == IntentType.CAPABILITIES_HELP
        # But "example queries" might have finance context, so could be different
        result = classify_intent("What are some example queries?")
        # Accept either CAPABILITIES_HELP or FINANCE_ANALYSIS
        assert result in (IntentType.CAPABILITIES_HELP, IntentType.FINANCE_ANALYSIS)
    
    def test_how_to_use(self):
        assert classify_intent("How do I use this?") == IntentType.CAPABILITIES_HELP
        assert classify_intent("How to use you") == IntentType.CAPABILITIES_HELP


class TestOutOfScopeIntent:
    """Test OUT_OF_SCOPE intent classification."""
    
    def test_politics(self):
        assert classify_intent("Who is president of USA?") == IntentType.OUT_OF_SCOPE
        assert classify_intent("Who is the prime minister?") == IntentType.OUT_OF_SCOPE
        assert classify_intent("Tell me about the election") == IntentType.OUT_OF_SCOPE
    
    def test_geography(self):
        assert classify_intent("What is the capital of France?") == IntentType.OUT_OF_SCOPE
        assert classify_intent("Where is Paris located?") == IntentType.OUT_OF_SCOPE
    
    def test_history(self):
        assert classify_intent("When was Bitcoin invented?") == IntentType.OUT_OF_SCOPE
        assert classify_intent("History of cryptocurrency") == IntentType.OUT_OF_SCOPE
    
    def test_sports(self):
        assert classify_intent("Who won the game?") == IntentType.OUT_OF_SCOPE
        assert classify_intent("What's the NFL score?") == IntentType.OUT_OF_SCOPE
    
    def test_celebrity(self):
        assert classify_intent("Who starred in that movie?") == IntentType.OUT_OF_SCOPE
        assert classify_intent("Tell me about celebrity news") == IntentType.OUT_OF_SCOPE
    
    def test_contextual_finance_exception(self):
        # This should NOT be out of scope because it has strong finance context
        result = classify_intent("How could an election affect BTC volatility and market returns?")
        assert result != IntentType.OUT_OF_SCOPE  # Should be FINANCE_ANALYSIS


class TestTradeExecutionIntent:
    """Test TRADE_EXECUTION intent classification."""
    
    def test_buy_commands(self):
        assert classify_intent("Buy $10 of BTC") == IntentType.TRADE_EXECUTION
        assert classify_intent("Purchase 0.5 ETH") == IntentType.TRADE_EXECUTION
        assert classify_intent("Buy me the most profitable crypto") == IntentType.TRADE_EXECUTION
    
    def test_sell_commands(self):
        assert classify_intent("Sell $50 of ETH") == IntentType.TRADE_EXECUTION
        assert classify_intent("Sell my BTC position") == IntentType.TRADE_EXECUTION
    
    def test_order_commands(self):
        assert classify_intent("Execute an order for BTC") == IntentType.TRADE_EXECUTION
        assert classify_intent("Place a trade for $100") == IntentType.TRADE_EXECUTION


class TestFinanceAnalysisIntent:
    """Test FINANCE_ANALYSIS intent classification."""
    
    def test_analysis_queries(self):
        assert classify_intent("Analyze BTC volatility") == IntentType.FINANCE_ANALYSIS
        assert classify_intent("Compare ETH vs BTC returns") == IntentType.FINANCE_ANALYSIS
        assert classify_intent("What's the price of Bitcoin?") == IntentType.FINANCE_ANALYSIS
    
    def test_market_data_queries(self):
        assert classify_intent("Show me BTC candles") == IntentType.FINANCE_ANALYSIS
        assert classify_intent("What are the top gainers?") == IntentType.FINANCE_ANALYSIS
        # "Most profitable" without buy/sell is analysis
        assert classify_intent("What's the most profitable crypto today?") == IntentType.FINANCE_ANALYSIS


class TestPortfolioIntent:
    """Test PORTFOLIO intent classification."""
    
    def test_portfolio_queries(self):
        assert classify_intent("Show my portfolio") == IntentType.PORTFOLIO
        assert classify_intent("What's my PNL?") == IntentType.PORTFOLIO
        assert classify_intent("Portfolio allocation") == IntentType.PORTFOLIO
        assert classify_intent("My holdings") == IntentType.PORTFOLIO


class TestAppDiagnosticsIntent:
    """Test APP_DIAGNOSTICS intent classification."""
    
    def test_telemetry_queries(self):
        assert classify_intent("Show telemetry") == IntentType.APP_DIAGNOSTICS
        assert classify_intent("View my runs") == IntentType.APP_DIAGNOSTICS
        assert classify_intent("What are evals?") == IntentType.APP_DIAGNOSTICS
    
    def test_steps_panel_queries(self):
        assert classify_intent("Explain the steps panel") == IntentType.APP_DIAGNOSTICS
        assert classify_intent("What happened in my last run?") == IntentType.APP_DIAGNOSTICS


class TestEdgeCases:
    """Test edge cases and ambiguous queries."""
    
    def test_empty_string(self):
        assert classify_intent("") == IntentType.OUT_OF_SCOPE
        assert classify_intent("   ") == IntentType.OUT_OF_SCOPE
    
    def test_gibberish(self):
        assert classify_intent("asdfghjkl") == IntentType.OUT_OF_SCOPE
        assert classify_intent("xyzabc123") == IntentType.OUT_OF_SCOPE
    
    def test_mixed_intent(self):
        # Should prioritize trade execution if buy/sell present
        assert classify_intent("Buy BTC and analyze volatility") == IntentType.TRADE_EXECUTION
