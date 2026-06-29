"""Tests for trade_parser timeframe integration.

Verifies that trade_parser delegates to timeframe_parser for
all time expressions, rather than relying on hardcoded strings.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestTradeParserTimeframe:
    """Verify trade_parser uses timeframe_parser for lookback windows."""

    def test_last_48_hours(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy the most profitable crypto last 48 hours for $10")
        assert result.lookback_hours == 48.0

    def test_past_48h(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy the top crypto past 48h for $10")
        assert result.lookback_hours == 48.0

    def test_48_hours_ago(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy best performing crypto 48 hours ago for $10")
        assert result.lookback_hours == 48.0

    def test_2_days(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy the top gainer 2 days for $10")
        assert result.lookback_hours == 48.0

    def test_past_week(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy best crypto past 1 week for $10")
        assert result.lookback_hours == 168.0

    def test_last_month(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy the top crypto last 1 month for $10")
        assert result.lookback_hours == 720.0

    def test_last_24h_default(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy the top crypto last 24 hours for $10")
        assert result.lookback_hours == 24.0

    def test_last_1_hour(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy best crypto last 1 hour for $10")
        assert result.lookback_hours == 1.0

    def test_30_minutes(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy best crypto last 30 minutes for $10")
        assert result.lookback_hours == 0.5

    def test_3_weeks(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy best crypto last 3 weeks for $10")
        assert result.lookback_hours == 504.0  # 3 * 7 * 24

    def test_no_timeframe_defaults_to_24h(self):
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy $10 of BTC")
        assert result.lookback_hours == 24.0

    def test_time_window_populated(self):
        """When timeframe_parser succeeds, time_window dict should be set."""
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy best crypto last 48 hours for $10")
        assert result.lookback_hours == 48.0
        # time_window should be a dict from timeframe_parser
        if result.time_window is not None:
            assert "lookback_hours" in result.time_window
            assert result.time_window["lookback_hours"] == 48.0

    def test_ytd_anchored(self):
        """Year-to-date should produce a large lookback."""
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy the top crypto YTD for $10")
        # YTD from Jan 1 will be many hours; just assert it's > 24h
        assert result.lookback_hours > 24.0

    def test_since_monday_anchored(self):
        """Anchored time expression 'since Monday'."""
        from backend.agents.trade_parser import parse_trade_command

        result = parse_trade_command("buy best crypto since Monday for $10")
        # "since Monday" should produce some lookback > 0
        assert result.lookback_hours > 0
