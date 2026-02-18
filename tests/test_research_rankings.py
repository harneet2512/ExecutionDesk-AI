"""Unit tests for research node return computation and ranking logic."""
import pytest
from datetime import datetime, timedelta

from backend.services.coinbase_market_data import compute_return_24h
from backend.orchestrator.nodes.research_node import (
    _select_granularity,
    _granularity_label,
    _summarize_drop_reasons,
    _recommend_action,
    STABLECOINS,
)


# --- Helper to create candle dicts ---
def make_candles(prices: list, start_hour_offset: int = 0) -> list:
    """Create a list of candle dicts from a price sequence."""
    base = datetime(2026, 1, 1, 0, 0)
    candles = []
    for i, price in enumerate(prices):
        t = base + timedelta(hours=start_hour_offset + i)
        candles.append({
            "start_time": t.isoformat() + "Z",
            "end_time": (t + timedelta(hours=1)).isoformat() + "Z",
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 100.0,
        })
    return candles


# --- Tests for compute_return_24h ---
class TestComputeReturn:
    def test_positive_return(self):
        candles = make_candles([100.0, 105.0, 110.0])
        ret = compute_return_24h(candles)
        # (110 - 100) / 100 = 0.10
        assert abs(ret - 0.10) < 0.001

    def test_negative_return(self):
        candles = make_candles([100.0, 95.0, 90.0])
        ret = compute_return_24h(candles)
        # (90 - 100) / 100 = -0.10
        assert abs(ret - (-0.10)) < 0.001

    def test_flat_return(self):
        candles = make_candles([100.0, 100.0, 100.0])
        ret = compute_return_24h(candles)
        assert abs(ret) < 0.001

    def test_two_candles_minimum(self):
        candles = make_candles([50.0, 55.0])
        ret = compute_return_24h(candles)
        # (55 - 50) / 50 = 0.10
        assert abs(ret - 0.10) < 0.001

    def test_48h_worth_of_candles(self):
        """48 hourly candles: price goes from 100 to 120."""
        prices = [100.0 + (20.0 * i / 47) for i in range(48)]
        candles = make_candles(prices)
        ret = compute_return_24h(candles)
        # (last - first) / first ≈ (120 - 100) / 100 = 0.20
        assert abs(ret - 0.20) < 0.01

    def test_single_candle_returns_zero(self):
        candles = make_candles([100.0])
        ret = compute_return_24h(candles)
        assert ret == 0.0

    def test_empty_candles_returns_zero(self):
        ret = compute_return_24h([])
        assert ret == 0.0


# --- Tests for granularity selection ---
class TestGranularity:
    def test_24h_uses_one_hour(self):
        assert _select_granularity(24) == "ONE_HOUR"

    def test_48h_uses_one_hour(self):
        """Critical: 48h must use ONE_HOUR, not ONE_DAY."""
        assert _select_granularity(48) == "ONE_HOUR"

    def test_168h_uses_one_hour(self):
        assert _select_granularity(168) == "ONE_HOUR"

    def test_169h_uses_one_day(self):
        assert _select_granularity(169) == "ONE_DAY"

    def test_1h_uses_one_hour(self):
        assert _select_granularity(1) == "ONE_HOUR"

    def test_label_48h(self):
        assert _granularity_label(48) == "1h"

    def test_label_169h(self):
        assert _granularity_label(169) == "1d"


# --- Tests for drop reason helpers ---
class TestDropReasons:
    def test_summarize_empty(self):
        assert _summarize_drop_reasons({}) == {}

    def test_summarize_single_category(self):
        reasons = {
            "BTC-USD": "api_error_timeout",
            "ETH-USD": "api_error_500",
        }
        summary = _summarize_drop_reasons(reasons)
        assert summary.get("api") == 2

    def test_summarize_mixed(self):
        reasons = {
            "BTC-USD": "api_error_timeout",
            "ETH-USD": "insufficient_candles_5_need_36",
            "SOL-USD": "invalid_price_zero_open",
        }
        summary = _summarize_drop_reasons(reasons)
        assert summary.get("api") == 1
        assert summary.get("insufficient") == 1
        assert summary.get("invalid") == 1

    def test_recommend_action_auth_error(self):
        reasons = {
            "BTC-USD": "api_error_401_unauthorized",
            "ETH-USD": "api_error_403_forbidden",
        }
        result = _recommend_action(reasons)
        assert "credentials" in result.lower()

    def test_recommend_action_insufficient(self):
        reasons = {
            "BTC-USD": "insufficient_candles_5_need_36",
            "ETH-USD": "insufficient_candles_3_need_36",
        }
        result = _recommend_action(reasons)
        assert "insufficient" in result.lower() or "candle" in result.lower()


# --- Tests for stablecoin exclusion ---
class TestStablecoinExclusion:
    def test_stablecoins_set(self):
        assert "USDT" in STABLECOINS
        assert "USDC" in STABLECOINS
        assert "DAI" in STABLECOINS
        assert "BUSD" in STABLECOINS
        assert "PYUSD" in STABLECOINS

    def test_non_stablecoins(self):
        assert "BTC" not in STABLECOINS
        assert "ETH" not in STABLECOINS
        assert "SOL" not in STABLECOINS
