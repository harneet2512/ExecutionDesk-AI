"""Tests for prediction market intent parsing.

Tests cover:
- "buy yes on Trump" -> action=BUY, outcome=YES
- "what's the probability" -> action=QUERY
- Implicit outcome: "I think Trump wins" -> YES
- PREDICTION_MARKET asset class detection
"""
import pytest


class TestPredictionIntentParsing:
    """Tests for prediction market intent detection in intent_parser."""

    def test_buy_yes_explicit(self):
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("buy yes on Trump winning")
        assert intent.action == "BUY"
        assert intent.asset_class == "PREDICTION_MARKET"
        assert intent.constraints.get("outcome") == "YES"

    def test_buy_no_explicit(self):
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("buy no on Trump winning the election")
        assert intent.action == "BUY"
        assert intent.asset_class == "PREDICTION_MARKET"
        assert intent.constraints.get("outcome") == "NO"

    def test_sell_yes(self):
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("sell yes on will Biden run again")
        assert intent.action == "SELL"
        assert intent.asset_class == "PREDICTION_MARKET"
        assert intent.constraints.get("outcome") == "YES"

    def test_query_probability(self):
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("what's the probability of Trump winning?")
        assert intent.action == "QUERY"
        assert intent.asset_class == "PREDICTION_MARKET"

    def test_query_odds(self):
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("what are the odds of a recession?")
        assert intent.action == "QUERY"
        assert intent.asset_class == "PREDICTION_MARKET"

    def test_implicit_yes_think(self):
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("I think Trump wins the election")
        assert intent.asset_class == "PREDICTION_MARKET"
        assert intent.constraints.get("outcome") == "YES"

    def test_implicit_yes_bet(self):
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("bet on Trump winning")
        assert intent.asset_class == "PREDICTION_MARKET"
        assert intent.constraints.get("outcome") == "YES"

    def test_budget_extraction(self):
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("buy $50 yes on Trump winning")
        assert intent.budget_usd == 50.0
        assert intent.asset_class == "PREDICTION_MARKET"

    def test_non_prediction_not_affected(self):
        """Crypto intents should remain as CRYPTO."""
        from backend.agents.intent_parser import parse_intent

        intent = parse_intent("buy $10 of BTC")
        assert intent.asset_class == "CRYPTO"


class TestPredictionCommandParser:
    """Tests for prediction market command parsing."""

    def test_buy_yes_prediction_command(self):
        from backend.agents.command_parser import parse_command

        intent = parse_command("buy yes on Trump winning for $10")
        assert intent.side == "BUY"
        assert intent.constraints.get("outcome") == "YES"
        assert intent.constraints.get("asset_class") == "PREDICTION_MARKET"
        assert intent.budget_usd == 10.0

    def test_query_prediction_command(self):
        from backend.agents.command_parser import parse_command

        intent = parse_command("what's the probability of a recession?")
        assert intent.constraints.get("asset_class") == "PREDICTION_MARKET"
        assert intent.constraints.get("action") == "QUERY"
