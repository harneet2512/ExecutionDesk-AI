"""Unit tests for sell sizing and minimum-size field mapping."""

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from backend.providers.coinbase_provider import CoinbaseProvider
from backend.services.market_metadata import _COMMON_CRYPTO_DEFAULTS, SAFE_FALLBACK_PRECISION
from backend.services.product_catalog import ProductCatalogService, GENERIC_BASE_MIN_SIZE


# ---------------------------------------------------------------------------
# 1. Mapping: quote_increment must never equal base_min_size
# ---------------------------------------------------------------------------

def test_common_crypto_defaults_do_not_map_quote_increment_as_base_min():
    assert _COMMON_CRYPTO_DEFAULTS["quote_increment"] == "0.01"
    assert _COMMON_CRYPTO_DEFAULTS["base_min_size"] != _COMMON_CRYPTO_DEFAULTS["quote_increment"]


def test_safe_fallback_btc_base_min_is_not_quote_increment():
    btc = SAFE_FALLBACK_PRECISION["BTC-USD"]
    assert float(btc["base_min_size"]) < 0.001, (
        "BTC base_min_size should be tiny (crypto units), not 0.01"
    )
    assert btc["base_min_size"] != btc["quote_increment"]


# ---------------------------------------------------------------------------
# 2. ProductCatalogService._safe_base_min_size never returns "0.01" for BTC
# ---------------------------------------------------------------------------

def test_catalog_safe_base_min_size_empty_returns_safe_fallback():
    """When DB column is NULL/empty, _safe_base_min_size must use SAFE_FALLBACK or generic."""
    result = ProductCatalogService._safe_base_min_size("BTC-USD", "")
    assert result == SAFE_FALLBACK_PRECISION["BTC-USD"]["base_min_size"]
    assert result != "0.01"


def test_catalog_safe_base_min_size_none_returns_safe_fallback():
    result = ProductCatalogService._safe_base_min_size("BTC-USD", None)
    assert result == SAFE_FALLBACK_PRECISION["BTC-USD"]["base_min_size"]


def test_catalog_safe_base_min_size_valid_value_preserved():
    result = ProductCatalogService._safe_base_min_size("BTC-USD", "0.00000001")
    assert result == "0.00000001"


def test_catalog_safe_base_min_size_unknown_product_uses_generic():
    result = ProductCatalogService._safe_base_min_size("UNKNOWN-USD", "")
    assert result == GENERIC_BASE_MIN_SIZE


def test_catalog_safe_base_min_size_zero_treated_as_missing():
    """A stored '0' or '0.0' should trigger fallback, not be returned as-is."""
    result = ProductCatalogService._safe_base_min_size("BTC-USD", "0")
    assert result == SAFE_FALLBACK_PRECISION["BTC-USD"]["base_min_size"]


# ---------------------------------------------------------------------------
# 3. CoinbaseProvider fallback constraints
# ---------------------------------------------------------------------------

def test_generic_coinbase_fallback_uses_fine_base_precision(monkeypatch):
    class _FailedResult:
        success = False
        data = None
        error_code = None
        error_message = "metadata unavailable"
        used_stale_cache = False
        cache_age_seconds = None

    class _Service:
        def get_product_details_sync(self, *args, **kwargs):
            return _FailedResult()

    monkeypatch.setattr(
        "backend.services.market_metadata.get_metadata_service",
        lambda: _Service(),
    )
    monkeypatch.setattr(
        "backend.services.asset_selection_engine.get_tradeable_product_ids",
        lambda: {"MOCK-USD"},
    )

    provider = CoinbaseProvider.__new__(CoinbaseProvider)
    provider._get_headers = lambda method, path: {}

    data = provider._validate_product_constraints("MOCK-USD", 10.0)
    assert data["base_min_size"] == "0.00000001"
    assert data["base_increment"] == "0.00000001"
    assert data["quote_increment"] == "0.01"


def test_sell_validation_requires_base_size_not_quote_size():
    provider = CoinbaseProvider.__new__(CoinbaseProvider)

    errors = provider._validate_order_locally(
        side="SELL",
        product_id="BTC-USD",
        order_configuration={"market_market_ioc": {"quote_size": "10.00"}},
        product_details={"base_min_size": "0.00000001"},
        notional_usd=10.0,
    )

    assert any("SELL market order must use base_size" in e for e in errors)


# ---------------------------------------------------------------------------
# 4. USD → base_size conversion magnitude
# ---------------------------------------------------------------------------

def test_usd_to_base_conversion_magnitude():
    """$2 at ~$65,000/BTC should yield ~0.00003 BTC, not 0.01."""
    usd = 2.0
    price = 65000.0
    base_size = usd / price
    assert 0.00001 < base_size < 0.001, (
        f"$2/65000 = {base_size}, should be ~0.00003"
    )
    assert base_size < 0.01, "base_size must be well below the old wrong 0.01 default"


def test_usd_to_base_conversion_various_prices():
    """Sanity: conversion for typical crypto prices."""
    for usd, price, asset in [
        (2.0, 65000.0, "BTC"),
        (2.0, 3500.0, "ETH"),
        (2.0, 150.0, "SOL"),
    ]:
        base = usd / price
        assert base > 0, f"{asset}: base must be positive"
        assert base < 1.0, f"{asset}: $2 should be < 1 unit of {asset}"


# ---------------------------------------------------------------------------
# 5. Preview rejection blocks pre-confirm (preflight)
# ---------------------------------------------------------------------------

def _setup_preflight_mocks(monkeypatch, base_min_size="0.00001", price=65000.0):
    """Shared setup for preflight base_min_size tests."""
    monkeypatch.setattr(
        "backend.services.market_data.get_price",
        lambda asset: price,
    )

    class _FakeResult:
        success = True
        data = {"base_min_size": base_min_size}
        error_code = None
        error_message = None
        used_stale_cache = False
        cache_age_seconds = 0

    class _FakeService:
        def get_product_details_sync(self, *a, **kw):
            return _FakeResult()

    monkeypatch.setattr(
        "backend.services.market_metadata.get_metadata_service",
        lambda: _FakeService(),
    )


def test_preflight_blocks_sell_below_base_min(monkeypatch):
    """Preflight should block a SELL whose USD converts to below base_min_size."""
    from backend.services.trade_preflight import _check_sell_base_min_size

    _setup_preflight_mocks(monkeypatch)

    block = _check_sell_base_min_size(
        asset="BTC",
        amount_usd=0.10,
        sell_all_requested=False,
    )
    assert block is not None, "Should block a $0.10 BTC sell"
    assert not block.valid
    assert "minimum" in block.message.lower() or "below" in block.message.lower()


def test_preflight_allows_sell_above_base_min(monkeypatch):
    """Preflight should pass a SELL that comfortably exceeds base_min_size."""
    from backend.services.trade_preflight import _check_sell_base_min_size

    _setup_preflight_mocks(monkeypatch)

    block = _check_sell_base_min_size(
        asset="BTC",
        amount_usd=10.0,
        sell_all_requested=False,
    )
    assert block is None, "Should allow a $10 BTC sell"


# ---------------------------------------------------------------------------
# 6. Dust handling: sell-all with tiny holdings
# ---------------------------------------------------------------------------

def test_preflight_dust_message_for_sell_all(monkeypatch):
    """Sell-all with dust should get a clear dust message with options."""
    from backend.services.trade_preflight import _check_sell_base_min_size

    _setup_preflight_mocks(monkeypatch)

    block = _check_sell_base_min_size(
        asset="BTC",
        amount_usd=0.05,
        sell_all_requested=True,
    )
    assert block is not None
    assert not block.valid
    assert "dust" in block.message.lower()
    assert any("convert" in f.lower() or "dust" in f.lower() for f in (block.fixes or []))
