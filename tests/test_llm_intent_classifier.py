"""Tests for the LLM-based intent classifier.

Tests cover:
- Structured output parsing from mocked OpenAI responses
- Typo and alternative phrasing handling
- Fallback to regex when OpenAI is unavailable
- CONFIRM/CANCEL synonym expansion
"""
import json
import pytest
from unittest.mock import patch, MagicMock


def _make_openai_response(content: dict) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response returning JSON content."""
    msg = MagicMock()
    msg.content = json.dumps(content)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestLLMIntentClassifier:
    """Test suite for backend.agents.llm_intent_classifier."""

    # ------------------------------------------------------------------
    # Basic trade intents
    # ------------------------------------------------------------------

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_buy_bitcoin(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.return_value = {
            "action": "BUY",
            "asset": "BTC",
            "amount_usd": 5.0,
            "side": "BUY",
            "strategy": None,
            "timeframe": "24h",
            "outcome": None,
            "market_query": None,
            "confidence": 0.95,
        }
        result = classify_with_llm("buy $5 of bitcoin")
        assert result.action == "BUY"
        assert result.asset == "BTC"
        assert result.amount_usd == 5.0
        assert result.confidence >= 0.9

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_sell_ethereum(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.return_value = {
            "action": "SELL",
            "asset": "ETH",
            "amount_usd": None,
            "side": "SELL",
            "strategy": None,
            "timeframe": None,
            "outcome": None,
            "market_query": None,
            "confidence": 0.92,
        }
        result = classify_with_llm("sell my ethereum")
        assert result.action == "SELL"
        assert result.asset == "ETH"

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_price_query(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.return_value = {
            "action": "QUERY",
            "asset": "BTC",
            "amount_usd": None,
            "side": None,
            "strategy": None,
            "timeframe": None,
            "outcome": None,
            "market_query": "price",
            "confidence": 0.97,
        }
        result = classify_with_llm("what's the price of BTC?")
        assert result.action == "QUERY"
        assert result.asset == "BTC"

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_portfolio_analysis(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.return_value = {
            "action": "PORTFOLIO_ANALYSIS",
            "asset": None,
            "amount_usd": None,
            "side": None,
            "strategy": None,
            "timeframe": None,
            "outcome": None,
            "market_query": None,
            "confidence": 0.98,
        }
        result = classify_with_llm("analyze my portfolio")
        assert result.action == "PORTFOLIO_ANALYSIS"

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_buy_strategy_top_performer(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.return_value = {
            "action": "BUY",
            "asset": None,
            "amount_usd": None,
            "side": "BUY",
            "strategy": "TOP_PERFORMER",
            "timeframe": "24h",
            "outcome": None,
            "market_query": None,
            "confidence": 0.88,
        }
        result = classify_with_llm("buy the best performing crypto")
        assert result.action == "BUY"
        assert result.strategy == "TOP_PERFORMER"

    # ------------------------------------------------------------------
    # Typo handling
    # ------------------------------------------------------------------

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_typo_byu(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.return_value = {
            "action": "BUY",
            "asset": "BTC",
            "amount_usd": 10.0,
            "side": "BUY",
            "strategy": None,
            "timeframe": None,
            "outcome": None,
            "market_query": None,
            "confidence": 0.85,
        }
        result = classify_with_llm("byu $10 of btc")
        assert result.action == "BUY"
        assert result.asset == "BTC"
        assert result.amount_usd == 10.0

    # ------------------------------------------------------------------
    # Alternative phrasings
    # ------------------------------------------------------------------

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_alternative_pick_up_bitcoin(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.return_value = {
            "action": "BUY",
            "asset": "BTC",
            "amount_usd": None,
            "side": "BUY",
            "strategy": None,
            "timeframe": None,
            "outcome": None,
            "market_query": None,
            "confidence": 0.82,
        }
        result = classify_with_llm("pick up some bitcoin")
        assert result.action == "BUY"
        assert result.asset == "BTC"

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_alternative_get_rid_of_eth(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.return_value = {
            "action": "SELL",
            "asset": "ETH",
            "amount_usd": None,
            "side": "SELL",
            "strategy": None,
            "timeframe": None,
            "outcome": None,
            "market_query": None,
            "confidence": 0.84,
        }
        result = classify_with_llm("get rid of my eth")
        assert result.action == "SELL"
        assert result.asset == "ETH"

    # ------------------------------------------------------------------
    # Fallback to regex when OpenAI is unavailable
    # ------------------------------------------------------------------

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_fallback_on_openai_failure(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.side_effect = Exception("OpenAI API unavailable")
        result = classify_with_llm("buy $5 of BTC")
        # Should still return a result via regex fallback
        assert result is not None
        assert result.action == "BUY"
        assert result.asset == "BTC"
        assert result.amount_usd == 5.0
        assert result.confidence < 1.0  # regex confidence is lower

    @patch("backend.agents.llm_intent_classifier._get_openai_key", return_value="sk-test-key")
    @patch("backend.agents.llm_intent_classifier._openai_classify")
    def test_fallback_on_timeout(self, mock_classify, _mock_key):
        from backend.agents.llm_intent_classifier import classify_with_llm

        mock_classify.side_effect = TimeoutError("LLM call timed out")
        result = classify_with_llm("sell my ethereum")
        assert result is not None
        assert result.action == "SELL"
        assert result.asset == "ETH"

    # ------------------------------------------------------------------
    # CONFIRM / CANCEL synonyms
    # ------------------------------------------------------------------

    def test_confirm_synonyms(self):
        from backend.agents.llm_intent_classifier import classify_confirmation

        for word in ["yes", "ok", "proceed", "go ahead", "do it", "confirm", "approved", "go", "execute"]:
            result = classify_confirmation(word)
            assert result == "CONFIRM", f"Expected CONFIRM for '{word}', got {result}"

    def test_cancel_synonyms(self):
        from backend.agents.llm_intent_classifier import classify_confirmation

        for word in ["no", "nevermind", "never mind", "stop", "abort", "cancel", "nope", "skip", "dont", "don't"]:
            result = classify_confirmation(word)
            assert result == "CANCEL", f"Expected CANCEL for '{word}', got {result}"

    def test_non_confirmation_returns_none(self):
        from backend.agents.llm_intent_classifier import classify_confirmation

        result = classify_confirmation("buy $10 of BTC")
        assert result is None

    # ------------------------------------------------------------------
    # ParsedIntent model tests
    # ------------------------------------------------------------------

    def test_parsed_intent_defaults(self):
        from backend.agents.llm_intent_classifier import ParsedIntent

        intent = ParsedIntent(action="BUY", raw_text="test")
        assert intent.action == "BUY"
        assert intent.asset is None
        assert intent.amount_usd is None
        assert intent.confidence == 0.0
        assert intent.raw_text == "test"

    def test_parsed_intent_full(self):
        from backend.agents.llm_intent_classifier import ParsedIntent

        intent = ParsedIntent(
            action="BUY",
            asset="BTC",
            amount_usd=10.0,
            side="BUY",
            strategy="TOP_PERFORMER",
            timeframe="24h",
            confidence=0.95,
            raw_text="buy the best crypto",
        )
        assert intent.action == "BUY"
        assert intent.asset == "BTC"
        assert intent.amount_usd == 10.0
        assert intent.strategy == "TOP_PERFORMER"
        assert intent.timeframe == "24h"
        assert intent.confidence == 0.95

    # ------------------------------------------------------------------
    # Regex fallback classifier directly
    # ------------------------------------------------------------------

    def test_regex_fallback_buy(self):
        from backend.agents.llm_intent_classifier import _regex_fallback_classify

        result = _regex_fallback_classify("buy $20 of ETH")
        assert result.action == "BUY"
        assert result.asset == "ETH"
        assert result.amount_usd == 20.0

    def test_regex_fallback_sell(self):
        from backend.agents.llm_intent_classifier import _regex_fallback_classify

        result = _regex_fallback_classify("sell my BTC")
        assert result.action == "SELL"
        assert result.asset == "BTC"

    def test_regex_fallback_greeting(self):
        from backend.agents.llm_intent_classifier import _regex_fallback_classify

        result = _regex_fallback_classify("hello there")
        assert result.action == "GREETING"

    def test_regex_fallback_portfolio(self):
        from backend.agents.llm_intent_classifier import _regex_fallback_classify

        result = _regex_fallback_classify("analyze my portfolio")
        assert result.action == "PORTFOLIO_ANALYSIS"

    # ------------------------------------------------------------------
    # No OpenAI key configured - pure regex path
    # ------------------------------------------------------------------

    def test_no_api_key_uses_regex(self):
        from backend.agents.llm_intent_classifier import classify_with_llm

        with patch("backend.agents.llm_intent_classifier._get_openai_key", return_value=None):
            result = classify_with_llm("buy $5 of bitcoin")
            assert result.action == "BUY"
            assert result.asset == "BTC"
            assert result.amount_usd == 5.0
