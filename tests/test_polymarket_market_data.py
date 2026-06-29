"""Tests for PolymarketMarketDataProvider.

Tests cover:
- Market search returns ranked results
- get_current_price returns YES price as 0-1 probability
- Timeseries-to-OHLCV conversion
"""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Market search
# ---------------------------------------------------------------------------

class TestMarketSearch:
    """Tests for market search functionality."""

    @patch("backend.providers.polymarket_market_data.httpx.Client")
    def test_search_returns_ranked_results(self, mock_client_cls):
        from backend.providers.polymarket_market_data import PolymarketMarketDataProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "conditionId": "cond_1",
                "question": "Will Trump win the 2024 election?",
                "slug": "will-trump-win-2024",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '[0.62, 0.38]',
                "volume": "5000000",
                "liquidity": "1000000",
                "active": True,
            },
            {
                "conditionId": "cond_2",
                "question": "Will Trump be the Republican nominee?",
                "slug": "trump-republican-nominee",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '[0.90, 0.10]',
                "volume": "2000000",
                "liquidity": "500000",
                "active": True,
            },
        ]
        mock_response.raise_for_status = MagicMock()

        instance = MagicMock()
        instance.get.return_value = mock_response
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        provider = PolymarketMarketDataProvider()
        results = provider.search_markets("Trump win")

        assert isinstance(results, list)
        assert len(results) == 2
        # Results should have required fields
        for r in results:
            assert "question" in r
            assert "slug" in r
            assert "yes_price" in r
            assert "volume" in r
        # Should be ranked by volume (descending)
        assert float(results[0]["volume"]) >= float(results[1]["volume"])


# ---------------------------------------------------------------------------
# get_current_price
# ---------------------------------------------------------------------------

class TestGetCurrentPrice:
    """Tests for get_current_price returning YES price as probability."""

    @patch("backend.providers.polymarket_market_data.httpx.Client")
    def test_price_returns_probability(self, mock_client_cls):
        from backend.providers.polymarket_market_data import PolymarketMarketDataProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "condition_id": "cond_1",
            "question": "Will X happen?",
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["0.65", "0.35"],
            "tokens": [
                {"token_id": "tok_yes", "outcome": "Yes", "price": "0.65"},
                {"token_id": "tok_no", "outcome": "No", "price": "0.35"},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        instance = MagicMock()
        instance.get.return_value = mock_response
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        provider = PolymarketMarketDataProvider()
        price = provider.get_current_price("cond_1")

        assert isinstance(price, float)
        assert 0.0 <= price <= 1.0
        assert abs(price - 0.65) < 0.001

    @patch("backend.providers.polymarket_market_data.httpx.Client")
    def test_price_returns_none_on_api_error(self, mock_client_cls):
        from backend.providers.polymarket_market_data import PolymarketMarketDataProvider

        instance = MagicMock()
        instance.get.side_effect = Exception("API down")
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        provider = PolymarketMarketDataProvider()
        price = provider.get_current_price("bad_cond")

        assert price is None


# ---------------------------------------------------------------------------
# Timeseries to OHLCV
# ---------------------------------------------------------------------------

class TestTimeseriesConversion:
    """Tests for timeseries-to-OHLCV conversion."""

    def test_converts_timeseries_to_ohlcv(self):
        from backend.providers.polymarket_market_data import PolymarketMarketDataProvider

        provider = PolymarketMarketDataProvider()

        timeseries = [
            {"t": 1700000000, "p": 0.50},
            {"t": 1700000060, "p": 0.52},
            {"t": 1700000120, "p": 0.48},
            {"t": 1700000180, "p": 0.55},
            {"t": 1700003600, "p": 0.60},
            {"t": 1700003660, "p": 0.58},
        ]

        ohlcv = provider.timeseries_to_ohlcv(timeseries, interval_seconds=3600)

        assert isinstance(ohlcv, list)
        assert len(ohlcv) >= 1

        first_bar = ohlcv[0]
        assert "open" in first_bar
        assert "high" in first_bar
        assert "low" in first_bar
        assert "close" in first_bar
        assert "start_time" in first_bar

        # First bar: open=0.50, high=0.55, low=0.48, close=0.55
        assert abs(first_bar["open"] - 0.50) < 0.001
        assert abs(first_bar["high"] - 0.55) < 0.001
        assert abs(first_bar["low"] - 0.48) < 0.001

    def test_empty_timeseries_returns_empty(self):
        from backend.providers.polymarket_market_data import PolymarketMarketDataProvider

        provider = PolymarketMarketDataProvider()
        result = provider.timeseries_to_ohlcv([], interval_seconds=3600)
        assert result == []
