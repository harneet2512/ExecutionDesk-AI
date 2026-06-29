"""Tests for PolymarketProvider (CLOB broker integration).

Tests cover:
- place_order returns order_id and maps CLOB statuses
- Limit order price validation (0.01-0.99)
- get_positions returns correct shape with unrealized_pnl
- get_order_book returns bids/asks/spread/depth
- Retry on 429 with exponential backoff
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from decimal import Decimal


# ---------------------------------------------------------------------------
# CLOB status mapping
# ---------------------------------------------------------------------------

class TestStatusMapping:
    """Polymarket CLOB status -> internal status mapping."""

    def test_live_maps_to_submitted(self):
        from backend.providers.polymarket_clob import PolymarketProvider
        assert PolymarketProvider.STATUS_MAP["LIVE"] == "SUBMITTED"

    def test_matched_maps_to_filled(self):
        from backend.providers.polymarket_clob import PolymarketProvider
        assert PolymarketProvider.STATUS_MAP["MATCHED"] == "FILLED"

    def test_canceled_maps_to_cancelled(self):
        from backend.providers.polymarket_clob import PolymarketProvider
        assert PolymarketProvider.STATUS_MAP["CANCELED"] == "CANCELLED"


# ---------------------------------------------------------------------------
# place_order
# ---------------------------------------------------------------------------

class TestPlaceOrder:
    """Tests for PolymarketProvider.place_order()."""

    @patch("backend.providers.polymarket_clob.httpx.Client")
    def test_place_order_returns_order_id(self, mock_client_cls, test_db):
        from backend.providers.polymarket_clob import PolymarketProvider
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        # Create a run first to satisfy FK constraint
        run_id = new_id("run_")
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, 'CREATED', 'PAPER', ?)",
                (run_id, "t_default", now_iso())
            )
            conn.commit()

        # Mock CLOB POST /order response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "orderID": "clob_order_abc123",
            "status": "LIVE",
        }
        mock_response.raise_for_status = MagicMock()

        instance = MagicMock()
        instance.request.return_value = mock_response
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        provider = PolymarketProvider(api_key="test_key", api_secret="test_secret")
        order_id = provider.place_order(
            run_id=run_id,
            tenant_id="t_default",
            symbol="will-trump-win-2024",
            side="BUY",
            notional_usd=10.0,
            outcome="YES",
            limit_price=0.55,
        )

        assert order_id is not None
        assert isinstance(order_id, str)
        assert len(order_id) > 0

    @patch("backend.providers.polymarket_clob.httpx.Client")
    def test_place_order_stores_in_db(self, mock_client_cls, test_db):
        from backend.providers.polymarket_clob import PolymarketProvider
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        # Create a run first to satisfy FK constraint
        run_id = new_id("run_")
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, 'CREATED', 'PAPER', ?)",
                (run_id, "t_default", now_iso())
            )
            conn.commit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "orderID": "clob_order_xyz",
            "status": "LIVE",
        }
        mock_response.raise_for_status = MagicMock()

        instance = MagicMock()
        instance.request.return_value = mock_response
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        provider = PolymarketProvider(api_key="test_key", api_secret="test_secret")
        order_id = provider.place_order(
            run_id=run_id,
            tenant_id="t_default",
            symbol="some-market",
            side="BUY",
            notional_usd=5.0,
            outcome="YES",
            limit_price=0.60,
        )

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["provider"] == "POLYMARKET"
            assert row["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Price validation
# ---------------------------------------------------------------------------

class TestPriceValidation:
    """Limit order price must be 0.01-0.99."""

    def test_price_below_minimum_raises(self):
        from backend.providers.polymarket_clob import PolymarketProvider

        provider = PolymarketProvider(api_key="k", api_secret="s")
        with pytest.raises(ValueError, match="between 0.01 and 0.99"):
            provider._validate_limit_price(0.00)

    def test_price_above_maximum_raises(self):
        from backend.providers.polymarket_clob import PolymarketProvider

        provider = PolymarketProvider(api_key="k", api_secret="s")
        with pytest.raises(ValueError, match="between 0.01 and 0.99"):
            provider._validate_limit_price(1.00)

    def test_price_at_boundary_ok(self):
        from backend.providers.polymarket_clob import PolymarketProvider

        provider = PolymarketProvider(api_key="k", api_secret="s")
        # These should not raise
        provider._validate_limit_price(0.01)
        provider._validate_limit_price(0.99)
        provider._validate_limit_price(0.50)

    def test_negative_price_raises(self):
        from backend.providers.polymarket_clob import PolymarketProvider

        provider = PolymarketProvider(api_key="k", api_secret="s")
        with pytest.raises(ValueError, match="between 0.01 and 0.99"):
            provider._validate_limit_price(-0.5)


# ---------------------------------------------------------------------------
# get_positions
# ---------------------------------------------------------------------------

class TestGetPositions:
    """Tests for PolymarketProvider.get_positions()."""

    @patch("backend.providers.polymarket_clob.httpx.Client")
    def test_get_positions_returns_correct_shape(self, mock_client_cls):
        from backend.providers.polymarket_clob import PolymarketProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "market": "will-trump-win-2024",
                "outcome": "YES",
                "size": 100,
                "avgPrice": 0.55,
                "currentPrice": 0.62,
            }
        ]
        mock_response.raise_for_status = MagicMock()

        instance = MagicMock()
        instance.request.return_value = mock_response
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        provider = PolymarketProvider(api_key="k", api_secret="s")
        result = provider.get_positions(tenant_id="t_test")

        assert "positions" in result
        positions = result["positions"]
        assert isinstance(positions, list)
        assert len(positions) == 1

        pos = positions[0]
        assert "market" in pos
        assert "outcome" in pos
        assert "size" in pos
        assert "unrealized_pnl" in pos
        # PnL = (current - avg) * size = (0.62 - 0.55) * 100 = 7.0
        assert abs(pos["unrealized_pnl"] - 7.0) < 0.01


# ---------------------------------------------------------------------------
# get_order_book
# ---------------------------------------------------------------------------

class TestGetOrderBook:
    """Tests for PolymarketProvider.get_order_book()."""

    @patch("backend.providers.polymarket_clob.httpx.Client")
    def test_order_book_returns_bids_asks_spread(self, mock_client_cls):
        from backend.providers.polymarket_clob import PolymarketProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bids": [
                {"price": "0.55", "size": "100"},
                {"price": "0.54", "size": "200"},
            ],
            "asks": [
                {"price": "0.57", "size": "150"},
                {"price": "0.58", "size": "250"},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        instance = MagicMock()
        instance.request.return_value = mock_response
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        provider = PolymarketProvider(api_key="k", api_secret="s")
        book = provider.get_order_book(token_id="token_abc")

        assert "bids" in book
        assert "asks" in book
        assert "spread" in book
        assert "depth" in book

        assert len(book["bids"]) == 2
        assert len(book["asks"]) == 2

        # Spread = best_ask - best_bid = 0.57 - 0.55 = 0.02
        assert abs(book["spread"] - 0.02) < 0.001

        # Depth = sum of all sizes
        assert book["depth"]["bid_depth"] == 300
        assert book["depth"]["ask_depth"] == 400


# ---------------------------------------------------------------------------
# Retry on 429
# ---------------------------------------------------------------------------

class TestRetryBehavior:
    """Tests for 429 retry with exponential backoff."""

    @patch("backend.providers.polymarket_clob.time.sleep")
    @patch("backend.providers.polymarket_clob.httpx.Client")
    def test_retries_on_429(self, mock_client_cls, mock_sleep):
        from backend.providers.polymarket_clob import PolymarketProvider

        # First call returns 429, second returns success
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.raise_for_status.side_effect = Exception("Rate limited")

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {
            "orderID": "clob_order_retry",
            "status": "LIVE",
        }
        mock_ok.raise_for_status = MagicMock()

        instance = MagicMock()
        instance.request.side_effect = [mock_429, mock_ok]
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *a: None
        mock_client_cls.return_value = instance

        provider = PolymarketProvider(api_key="k", api_secret="s")
        # Use _clob_request to test retry directly
        result = provider._clob_request("POST", "/order", json_body={"test": True})

        assert result["orderID"] == "clob_order_retry"
        assert mock_sleep.called
