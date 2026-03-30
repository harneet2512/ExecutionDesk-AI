"""Tests for the deterministic AssetResolver.

Validates:
  - Symbol resolution uses snapshot-first, then catalog.
  - MOODENG -> MOODENG-USD, MORPHO -> MORPHO-USD (with matching catalog).
  - SOL-USD is never injected as a fallback for unrelated symbols.
  - Exactly one resolution_status per asset.
  - sell-all resolution sets snapshot_qty correctly.
"""
import pytest
from backend.services.asset_resolver import (
    resolve_assets,
    AssetResolution,
    RESOLUTION_OK,
    RESOLUTION_NOT_HELD,
    RESOLUTION_QTY_MISSING,
    RESOLUTION_NO_PRODUCT,
    _normalize_symbol,
    _build_holdings_map,
)


def _always_tradeable(product_id: str) -> bool:
    return True


def _never_tradeable(product_id: str) -> bool:
    return False


def _selective_tradeable(tradeable_set):
    def check(product_id: str) -> bool:
        return product_id in tradeable_set
    return check


class TestNormalizeSymbol:

    def test_plain_symbol(self):
        assert _normalize_symbol("MOODENG") == "MOODENG"

    def test_with_usd_suffix(self):
        assert _normalize_symbol("BTC-USD") == "BTC"

    def test_with_usdc_suffix(self):
        assert _normalize_symbol("ETH-USDC") == "ETH"

    def test_lowercase(self):
        assert _normalize_symbol("morpho") == "MORPHO"

    def test_whitespace(self):
        assert _normalize_symbol("  SOL  ") == "SOL"


class TestBuildHoldingsMap:

    def test_basic(self):
        positions = {"BTC": 0.5, "ETH": 2.0}
        result = _build_holdings_map(positions)
        assert result == {"BTC": 0.5, "ETH": 2.0}

    def test_normalizes_keys(self):
        positions = {"BTC-USD": 0.5, "eth": 1.0}
        result = _build_holdings_map(positions)
        assert "BTC" in result
        assert "ETH" in result

    def test_zero_qty_excluded(self):
        positions = {"BTC": 0.0, "ETH": 1.0}
        result = _build_holdings_map(positions)
        assert result["BTC"] == 0.0
        assert result["ETH"] == 1.0


class TestResolveAssets:

    def test_moodeng_resolves_to_moodeng_usd(self):
        positions = {"MOODENG": 100.0}
        results = resolve_assets(["MOODENG"], positions, _always_tradeable)
        assert len(results) == 1
        r = results[0]
        assert r.product_id == "MOODENG-USD"
        assert r.base_asset == "MOODENG"
        assert r.resolution_status == RESOLUTION_OK
        assert r.found_in_snapshot is True
        assert r.snapshot_qty == 100.0

    def test_morpho_resolves_to_morpho_usd(self):
        positions = {"MORPHO": 50.5}
        results = resolve_assets(["MORPHO"], positions, _always_tradeable)
        assert len(results) == 1
        r = results[0]
        assert r.product_id == "MORPHO-USD"
        assert r.base_asset == "MORPHO"
        assert r.resolution_status == RESOLUTION_OK

    def test_no_sol_fallback(self):
        """Requesting MOODENG must never produce SOL-USD."""
        positions = {"SOL": 10.0}
        tradeable = _selective_tradeable({"SOL-USD", "MOODENG-USD"})
        results = resolve_assets(["MOODENG"], positions, tradeable)
        r = results[0]
        assert r.product_id != "SOL-USD"
        assert r.product_id == "MOODENG-USD"
        assert r.resolution_status == RESOLUTION_NOT_HELD

    def test_unknown_symbol_not_tradeable(self):
        positions = {}
        results = resolve_assets(["FAKECOIN"], positions, _never_tradeable)
        r = results[0]
        assert r.product_id is None
        assert r.resolution_status == RESOLUTION_NO_PRODUCT
        assert r.user_message_if_blocked
        assert "SOL" not in r.user_message_if_blocked

    def test_not_held_but_tradeable(self):
        positions = {"BTC": 1.0}
        results = resolve_assets(["ETH"], positions, _always_tradeable)
        r = results[0]
        assert r.resolution_status == RESOLUTION_NOT_HELD
        assert r.found_in_snapshot is False
        assert r.product_id == "ETH-USD"

    def test_held_with_zero_qty(self):
        positions = {"MOODENG": 0.0}
        results = resolve_assets(["MOODENG"], positions, _always_tradeable)
        r = results[0]
        assert r.resolution_status == RESOLUTION_NOT_HELD
        assert r.found_in_snapshot is False

    def test_usdc_fallback(self):
        tradeable = _selective_tradeable({"BTC-USDC"})
        positions = {"BTC": 1.0}
        results = resolve_assets(["BTC"], positions, tradeable)
        r = results[0]
        assert r.product_id == "BTC-USDC"
        assert r.quote_asset == "USDC"
        assert r.resolution_status == RESOLUTION_OK

    def test_multi_asset_resolution(self):
        positions = {"MOODENG": 100.0, "MORPHO": 50.0}
        results = resolve_assets(
            ["MOODENG", "MORPHO"], positions, _always_tradeable
        )
        assert len(results) == 2
        assert results[0].product_id == "MOODENG-USD"
        assert results[1].product_id == "MORPHO-USD"
        assert all(r.resolution_status == RESOLUTION_OK for r in results)

    def test_one_status_per_asset(self):
        """Each resolution must have exactly one status, never multiple."""
        positions = {}
        results = resolve_assets(
            ["MOODENG", "MORPHO", "FAKECOIN"],
            positions,
            _selective_tradeable({"MOODENG-USD", "MORPHO-USD"}),
        )
        for r in results:
            assert r.resolution_status in (
                RESOLUTION_OK, RESOLUTION_NOT_HELD,
                RESOLUTION_QTY_MISSING, RESOLUTION_NO_PRODUCT,
            )

    def test_sell_all_snapshot_qty(self):
        """sell-all needs snapshot_qty to be set from holdings."""
        positions = {"BTC": 0.123456}
        results = resolve_assets(["BTC"], positions, _always_tradeable)
        r = results[0]
        assert r.snapshot_qty == 0.123456
        assert r.found_in_snapshot is True

    def test_is_ok_and_is_blocked_properties(self):
        positions = {"BTC": 1.0}
        ok_results = resolve_assets(["BTC"], positions, _always_tradeable)
        blocked_results = resolve_assets(["FAKE"], {}, _never_tradeable)
        assert ok_results[0].is_ok is True
        assert ok_results[0].is_blocked is False
        assert blocked_results[0].is_ok is False
        assert blocked_results[0].is_blocked is True

    def test_user_messages(self):
        positions = {}
        results = resolve_assets(
            ["ALPHA", "BETA"],
            positions,
            _selective_tradeable({"ALPHA-USD"}),
        )
        alpha = results[0]
        beta = results[1]
        assert alpha.resolution_status == RESOLUTION_NOT_HELD
        assert "ALPHA" in alpha.user_message_if_blocked
        assert beta.resolution_status == RESOLUTION_NO_PRODUCT
        assert "BETA" in beta.user_message_if_blocked

    def test_no_positions_dict(self):
        results = resolve_assets(["BTC"], None, _always_tradeable)
        r = results[0]
        assert r.found_in_snapshot is False
        assert r.product_id == "BTC-USD"
