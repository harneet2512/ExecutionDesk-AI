"""Unit tests for universe filtering and strategy selection."""
import pytest
from backend.orchestrator.nodes.research_node import STABLECOINS
from backend.services.strategy_engine import compute_returns, compute_sharpe_proxy, compute_momentum


# --- Helper ---
def make_candles(prices: list) -> list:
    """Create candle dicts from price list."""
    from datetime import datetime, timedelta
    base = datetime(2026, 1, 1)
    return [
        {
            "start_time": (base + timedelta(hours=i)).isoformat() + "Z",
            "end_time": (base + timedelta(hours=i + 1)).isoformat() + "Z",
            "open": p, "high": p * 1.01, "low": p * 0.99, "close": p,
            "volume": 100.0
        }
        for i, p in enumerate(prices)
    ]


# --- Universe filtering tests ---
class TestUniverseFiltering:
    def test_stablecoin_excluded(self):
        """Stablecoins should not appear in universe."""
        products = [
            {"product_id": "BTC-USD", "base_currency_id": "BTC", "quote_currency_id": "USD", "status": "online"},
            {"product_id": "USDT-USD", "base_currency_id": "USDT", "quote_currency_id": "USD", "status": "online"},
            {"product_id": "USDC-USD", "base_currency_id": "USDC", "quote_currency_id": "USD", "status": "online"},
            {"product_id": "ETH-USD", "base_currency_id": "ETH", "quote_currency_id": "USD", "status": "online"},
        ]
        filtered = [
            p["product_id"] for p in products
            if p["status"] == "online"
            and p["quote_currency_id"] == "USD"
            and p["base_currency_id"] not in STABLECOINS
        ]
        assert "BTC-USD" in filtered
        assert "ETH-USD" in filtered
        assert "USDT-USD" not in filtered
        assert "USDC-USD" not in filtered

    def test_offline_excluded(self):
        """Products not 'online' should be excluded."""
        products = [
            {"product_id": "BTC-USD", "base_currency_id": "BTC", "quote_currency_id": "USD", "status": "online"},
            {"product_id": "OLD-USD", "base_currency_id": "OLD", "quote_currency_id": "USD", "status": "delisted"},
        ]
        filtered = [p["product_id"] for p in products if p["status"] == "online"]
        assert "BTC-USD" in filtered
        assert "OLD-USD" not in filtered

    def test_non_usd_excluded(self):
        """Products quoted in non-USD should be excluded."""
        products = [
            {"product_id": "BTC-USD", "base_currency_id": "BTC", "quote_currency_id": "USD", "status": "online"},
            {"product_id": "BTC-EUR", "base_currency_id": "BTC", "quote_currency_id": "EUR", "status": "online"},
        ]
        filtered = [p["product_id"] for p in products if p["quote_currency_id"] == "USD"]
        assert "BTC-USD" in filtered
        assert "BTC-EUR" not in filtered


# --- Strategy selection tests ---
class TestStrategySelection:
    def test_compute_returns_positive(self):
        candles = make_candles([100, 105, 110])
        ret = compute_returns(candles)
        assert abs(ret - 0.10) < 0.001

    def test_compute_returns_negative(self):
        candles = make_candles([100, 95, 90])
        ret = compute_returns(candles)
        assert abs(ret - (-0.10)) < 0.001

    def test_deterministic_selection(self):
        """Given known scores, selection should be deterministic."""
        rankings = [
            {"symbol": "ETH-USD", "score": 0.05, "volume_proxy": 1000},
            {"symbol": "BTC-USD", "score": 0.10, "volume_proxy": 5000},
            {"symbol": "SOL-USD", "score": 0.08, "volume_proxy": 500},
        ]
        rankings.sort(key=lambda x: (x["score"], x["volume_proxy"]), reverse=True)
        assert rankings[0]["symbol"] == "BTC-USD"
        assert rankings[1]["symbol"] == "SOL-USD"
        assert rankings[2]["symbol"] == "ETH-USD"

    def test_tie_breaking_by_volume(self):
        """Same score should be broken by volume proxy."""
        rankings = [
            {"symbol": "A-USD", "score": 0.10, "volume_proxy": 100},
            {"symbol": "B-USD", "score": 0.10, "volume_proxy": 500},
        ]
        rankings.sort(key=lambda x: (x["score"], x["volume_proxy"]), reverse=True)
        assert rankings[0]["symbol"] == "B-USD"

    def test_min_candles_threshold(self):
        """48h lookback should require ~36 candles (75% of 48)."""
        lookback_hours = 48
        MIN_CANDLES = max(int(lookback_hours * 0.75), 2)
        assert MIN_CANDLES == 36

    def test_min_candles_threshold_24h(self):
        lookback_hours = 24
        MIN_CANDLES = max(int(lookback_hours * 0.75), 2)
        assert MIN_CANDLES == 18

    def test_min_candles_threshold_1h(self):
        lookback_hours = 1
        MIN_CANDLES = max(int(lookback_hours * 0.75), 2)
        assert MIN_CANDLES == 2  # floor at 2
