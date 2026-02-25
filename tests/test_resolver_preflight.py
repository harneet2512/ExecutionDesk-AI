"""Unit tests for asset resolver and trade preflight integration.

Covers 20 scenarios per spec: resolver resolution rules, resolve_all_holdings
cash exclusion, preflight SELL paths, single-reason enforcement, and
forbidden-string checks.
"""
import pytest
from backend.services.asset_resolver import (
    resolve_from_executable_state as resolve_asset,
    resolve_all_holdings,
    RESOLUTION_OK,
)
from backend.services.executable_state import ExecutableBalance, ExecutableState
from backend.services.trade_preflight import (
    run_preflight,
    PreflightRejectReason,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(holdings: dict) -> ExecutableState:
    """Build an ExecutableState from {symbol: (available_qty, hold_qty)}."""
    balances = {}
    for sym, (avail, hold) in holdings.items():
        balances[sym] = ExecutableBalance(
            currency=sym,
            available_qty=avail,
            hold_qty=hold,
            account_uuid=None,
            updated_at=None,
        )
    return ExecutableState(balances=balances, fetched_at="2025-01-01T00:00:00Z", source="test")


def _online_catalog(*symbols):
    """Product catalog where every symbol is online and tradable."""
    cat = {}
    for sym in symbols:
        cat[f"{sym}-USD"] = {
            "is_disabled": False,
            "trading_disabled": False,
            "limit_only": False,
            "cancel_only": False,
        }
    return cat


def _disabled_catalog(*symbols):
    cat = {}
    for sym in symbols:
        cat[f"{sym}-USD"] = {
            "is_disabled": True,
            "trading_disabled": True,
            "limit_only": False,
            "cancel_only": False,
        }
    return cat


def _limit_only_catalog(*symbols):
    cat = {}
    for sym in symbols:
        cat[f"{sym}-USD"] = {
            "is_disabled": False,
            "trading_disabled": False,
            "limit_only": True,
            "cancel_only": False,
        }
    return cat


_TRADABLE_FLAGS = {
    "is_disabled": False,
    "trading_disabled": False,
    "limit_only": False,
    "cancel_only": False,
}
_DISABLED_FLAGS = {
    "is_disabled": True,
    "trading_disabled": True,
    "limit_only": False,
    "cancel_only": False,
}
_LIMIT_ONLY_FLAGS = {
    "is_disabled": False,
    "trading_disabled": False,
    "limit_only": True,
    "cancel_only": False,
}


# ---------------------------------------------------------------------------
# Resolver tests (1-12)
# ---------------------------------------------------------------------------

class TestResolveAsset:
    def test_ok(self):
        """1. MORPHO available 1.41 with online catalog -> OK"""
        state = _make_state({"MORPHO": (1.41, 0.0)})
        r = resolve_asset("MORPHO", state, _online_catalog("MORPHO"))
        assert r.resolution_status == "OK"
        assert r.executable_qty == pytest.approx(1.41)

    def test_funds_on_hold(self):
        """2. MORPHO available=0, hold=1.41 -> FUNDS_ON_HOLD"""
        state = _make_state({"MORPHO": (0.0, 1.41)})
        r = resolve_asset("MORPHO", state, _online_catalog("MORPHO"))
        assert r.resolution_status == "FUNDS_ON_HOLD"

    def test_qty_zero(self):
        """3. MORPHO available=0, hold=0 -> QTY_ZERO"""
        state = _make_state({"MORPHO": (0.0, 0.0)})
        r = resolve_asset("MORPHO", state, _online_catalog("MORPHO"))
        assert r.resolution_status == "QTY_ZERO"

    def test_not_held(self):
        """4. MORPHO not in state -> NOT_HELD"""
        state = _make_state({})
        r = resolve_asset("MORPHO", state, _online_catalog("MORPHO"))
        assert r.resolution_status == "NOT_HELD"

    def test_no_product_empty_catalog(self):
        """5. MORPHO in state, empty catalog -> NO_PRODUCT"""
        state = _make_state({"MORPHO": (1.41, 0.0)})
        r = resolve_asset("MORPHO", state, {})
        assert r.resolution_status == "NO_PRODUCT"

    def test_no_product_wrong_catalog(self):
        """6. MORPHO in state, SOL-only catalog -> NO_PRODUCT (no fallback to SOL-USD)"""
        state = _make_state({"MORPHO": (1.41, 0.0)})
        r = resolve_asset("MORPHO", state, _online_catalog("SOL"))
        assert r.resolution_status == "NO_PRODUCT"

    def test_not_tradable(self):
        """7. MORPHO available, disabled catalog -> NOT_TRADABLE"""
        state = _make_state({"MORPHO": (1.41, 0.0)})
        r = resolve_asset("MORPHO", state, _disabled_catalog("MORPHO"))
        assert r.resolution_status == "NOT_TRADABLE"

    def test_not_tradable_beats_qty(self):
        """8. MORPHO 5.0 available but disabled -> NOT_TRADABLE (not QTY_ZERO)"""
        state = _make_state({"MORPHO": (5.0, 0.0)})
        r = resolve_asset("MORPHO", state, _disabled_catalog("MORPHO"))
        assert r.resolution_status == "NOT_TRADABLE"

    def test_limit_only(self):
        """9. MORPHO available, limit-only catalog -> LIMIT_ONLY"""
        state = _make_state({"MORPHO": (1.41, 0.0)})
        r = resolve_asset("MORPHO", state, _limit_only_catalog("MORPHO"))
        assert r.resolution_status == "LIMIT_ONLY"


class TestResolveAllHoldings:
    def test_usd_excluded_crypto_tradable(self):
        """10. USD silently excluded, MORPHO+MOODENG tradable"""
        state = _make_state({
            "USD": (0.76, 0.0),
            "MORPHO": (1.41, 0.0),
            "MOODENG": (31.46, 0.0),
        })
        cat = _online_catalog("MORPHO", "MOODENG")
        tradable, skipped = resolve_all_holdings(state, cat)
        tradable_syms = {r.symbol for r in tradable}
        assert "USD" not in tradable_syms
        assert "MORPHO" in tradable_syms
        assert "MOODENG" in tradable_syms
        assert len(skipped) == 0

    def test_hold_and_zero_in_skipped(self):
        """11. FOO=FUNDS_ON_HOLD, BAR=QTY_ZERO both in skipped"""
        state = _make_state({
            "FOO": (0.0, 1.0),
            "BAR": (0.0, 0.0),
        })
        cat = _online_catalog("FOO", "BAR")
        tradable, skipped = resolve_all_holdings(state, cat)
        assert len(tradable) == 0
        statuses = {r.symbol: r.resolution_status for r in skipped}
        assert statuses["FOO"] == "FUNDS_ON_HOLD"
        assert statuses["BAR"] == "QTY_ZERO"

    def test_no_contradictions(self):
        """12. Each asset appears in exactly one of tradable or skipped"""
        state = _make_state({
            "MORPHO": (1.41, 0.0),
            "FOO": (0.0, 1.0),
            "BAR": (0.0, 0.0),
            "USD": (100.0, 0.0),
        })
        cat = _online_catalog("MORPHO", "FOO", "BAR")
        tradable, skipped = resolve_all_holdings(state, cat)
        tradable_syms = {r.symbol for r in tradable}
        skipped_syms = {r.symbol for r in skipped}
        assert not tradable_syms & skipped_syms, "Asset must not appear in both lists"
        assert "USD" not in (tradable_syms | skipped_syms), "Cash must be silently excluded"


# ---------------------------------------------------------------------------
# Preflight tests (13-20)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_min_notional(monkeypatch):
    """Stub HTTP call so run_preflight never hits the network."""
    async def _mock(_asset: str) -> float:
        return 1.0
    monkeypatch.setattr(
        "backend.services.trade_preflight.get_min_notional_for_asset", _mock
    )


class TestRunPreflight:
    @pytest.mark.asyncio
    async def test_sell_valid(self):
        """13. SELL with positive executable_qty -> valid"""
        result = await run_preflight(
            tenant_id="t_test", side="SELL", asset="MORPHO",
            amount_usd=100.0, executable_qty=1.41,
            product_flags=_TRADABLE_FLAGS,
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_sell_exceeds_holdings_returns_adjustment(self):
        """SELL notional above holdings should adjust to max sellable."""
        result = await run_preflight(
            tenant_id="t_test",
            side="SELL",
            asset="MORPHO",
            amount_usd=10.0,
            executable_qty=1.0,
            available_usd=2.28,
            product_flags=_TRADABLE_FLAGS,
        )
        assert result.valid is True
        assert result.requires_adjustment is True
        assert result.reason_code == PreflightRejectReason.EXCEEDS_HOLDINGS
        assert result.adjusted_amount_usd == pytest.approx(2.28)
        assert result.adjusted_qty == pytest.approx(1.0)
        assert "maximum available" in (result.user_message or "").lower()

    @pytest.mark.asyncio
    async def test_sell_below_minimum_is_blocked(self):
        """SELL below venue minimum should be blocked before confirm."""
        result = await run_preflight(
            tenant_id="t_test",
            side="SELL",
            asset="MORPHO",
            amount_usd=0.5,
            executable_qty=5.0,
            available_usd=0.5,
            product_flags=_TRADABLE_FLAGS,
        )
        assert result.valid is False
        assert result.reason_code == PreflightRejectReason.MIN_NOTIONAL_TOO_LOW

    @pytest.mark.asyncio
    async def test_preview_rejects_tiny_sell_blocks_even_if_metadata_would_allow(self, monkeypatch):
        async def _preview_reject(**_kwargs):
            return True, False, "minimum sell size is $1.00", 1.0

        async def _lenient_metadata(_asset: str) -> float:
            return 0.01

        monkeypatch.setattr("backend.services.trade_preflight._validate_via_coinbase_preview", _preview_reject)
        monkeypatch.setattr("backend.services.trade_preflight.get_min_notional_for_asset", _lenient_metadata)

        result = await run_preflight(
            tenant_id="t_test",
            side="SELL",
            asset="MORPHO",
            amount_usd=0.50,
            executable_qty=5.0,
            available_usd=0.50,
            mode="LIVE",
            product_flags=_TRADABLE_FLAGS,
        )
        assert result.valid is False
        assert result.reason_code == PreflightRejectReason.MIN_NOTIONAL_TOO_LOW
        assert "preview rejected" in (result.user_message or "").lower()

    @pytest.mark.asyncio
    async def test_preview_accepts_small_sell_even_if_metadata_default_would_block(self, monkeypatch):
        async def _preview_ok(**_kwargs):
            return True, True, "ok", None

        async def _strict_metadata(_asset: str) -> float:
            return 1.0

        monkeypatch.setattr("backend.services.trade_preflight._validate_via_coinbase_preview", _preview_ok)
        monkeypatch.setattr("backend.services.trade_preflight.get_min_notional_for_asset", _strict_metadata)

        result = await run_preflight(
            tenant_id="t_test",
            side="SELL",
            asset="MORPHO",
            amount_usd=0.50,
            executable_qty=5.0,
            available_usd=0.50,
            mode="LIVE",
            product_flags=_TRADABLE_FLAGS,
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_sell_all_dust_preview_block_has_enterprise_guidance(self, monkeypatch):
        async def _preview_reject(**_kwargs):
            return True, False, "minimum sell size is $1.00", 1.0

        monkeypatch.setattr("backend.services.trade_preflight._validate_via_coinbase_preview", _preview_reject)

        result = await run_preflight(
            tenant_id="t_test",
            side="SELL",
            asset="BTC",
            amount_usd=0.40,
            executable_qty=0.00001,
            requested_qty=0.00001,
            available_usd=0.40,
            mode="LIVE",
            sell_all_requested=True,
            product_flags=_TRADABLE_FLAGS,
        )
        assert result.valid is False
        assert result.reason_code == PreflightRejectReason.MIN_NOTIONAL_TOO_LOW
        msg = result.user_message or ""
        assert "below coinbase's minimum sell size" in msg.lower()
        fixes = result.fixes or []
        assert "Cancel" in fixes
        assert any("Buy more BTC" in f for f in fixes)

    @pytest.mark.asyncio
    async def test_sell_funds_on_hold(self):
        """14. SELL qty=0, hold=1.41 -> FUNDS_ON_HOLD"""
        result = await run_preflight(
            tenant_id="t_test", side="SELL", asset="MORPHO",
            amount_usd=100.0, executable_qty=0.0, hold_qty=1.41,
            product_flags=_TRADABLE_FLAGS,
        )
        assert not result.valid
        assert result.reason_code == PreflightRejectReason.FUNDS_ON_HOLD

    @pytest.mark.asyncio
    async def test_sell_qty_zero(self):
        """15. SELL qty=0, hold=0 -> QTY_ZERO"""
        result = await run_preflight(
            tenant_id="t_test", side="SELL", asset="MORPHO",
            amount_usd=100.0, executable_qty=0.0, hold_qty=0.0,
            product_flags=_TRADABLE_FLAGS,
        )
        assert not result.valid
        assert result.reason_code == PreflightRejectReason.QTY_ZERO

    @pytest.mark.asyncio
    async def test_sell_not_held(self):
        """16. SELL qty=None -> NOT_HELD"""
        result = await run_preflight(
            tenant_id="t_test", side="SELL", asset="MORPHO",
            amount_usd=100.0, executable_qty=None,
            product_flags=_TRADABLE_FLAGS,
        )
        assert not result.valid
        assert result.reason_code == PreflightRejectReason.NOT_HELD

    @pytest.mark.asyncio
    async def test_sell_not_tradable(self):
        """17. SELL with disabled product -> NOT_TRADABLE"""
        result = await run_preflight(
            tenant_id="t_test", side="SELL", asset="MORPHO",
            amount_usd=100.0, executable_qty=1.41,
            product_flags=_DISABLED_FLAGS,
        )
        assert not result.valid
        assert result.reason_code == PreflightRejectReason.NOT_TRADABLE

    @pytest.mark.asyncio
    async def test_sell_limit_only(self):
        """18. SELL with limit_only product -> LIMIT_ONLY"""
        result = await run_preflight(
            tenant_id="t_test", side="SELL", asset="MORPHO",
            amount_usd=100.0, executable_qty=1.41,
            product_flags=_LIMIT_ONLY_FLAGS,
        )
        assert not result.valid
        assert result.reason_code == PreflightRejectReason.LIMIT_ONLY

    @pytest.mark.asyncio
    async def test_single_reason_code(self):
        """19. Blocked result has exactly one reason_code (not two)"""
        result = await run_preflight(
            tenant_id="t_test", side="SELL", asset="MORPHO",
            amount_usd=100.0, executable_qty=0.0, hold_qty=1.41,
            product_flags=_TRADABLE_FLAGS,
        )
        assert not result.valid
        assert result.reason_code is not None
        d = result.to_dict()
        assert d["reason_code"] == d["primary_reason_code"]

    @pytest.mark.asyncio
    async def test_no_forbidden_strings(self):
        """20. 'quantity unavailable' and 'position not found' never in user_message"""
        scenarios = [
            {"executable_qty": None, "product_flags": _TRADABLE_FLAGS},
            {"executable_qty": 0.0, "hold_qty": 0.0, "product_flags": _TRADABLE_FLAGS},
            {"executable_qty": 0.0, "hold_qty": 1.0, "product_flags": _TRADABLE_FLAGS},
            {"executable_qty": 1.0, "product_flags": _DISABLED_FLAGS},
            {"executable_qty": 1.0, "product_flags": _LIMIT_ONLY_FLAGS},
        ]
        for kwargs in scenarios:
            result = await run_preflight(
                tenant_id="t_test", side="SELL", asset="MORPHO",
                amount_usd=100.0, **kwargs,
            )
            msg = (result.user_message or "").lower()
            assert "quantity unavailable" not in msg, f"Found forbidden string in: {result.user_message}"
            assert "position not found" not in msg, f"Found forbidden string in: {result.user_message}"


class TestTradeReasoning:

    @pytest.fixture(autouse=True)
    def check_key(self):
        import os
        import pytest as _pytest
        if not os.getenv("OPENAI_API_KEY"):
            _pytest.skip("OPENAI_API_KEY not set")

    def _state(self, balances: dict):
        from unittest.mock import MagicMock
        s = MagicMock()
        s.balances = {
            sym: MagicMock(available_qty=qty, hold_qty=0.0)
            for sym, qty in balances.items()
        }
        return s

    def test_returns_plan_summary(self):
        from backend.agents.trade_reasoner import reason_about_plan
        actions = [{"side": "sell", "asset": "MOODENG", "base_size": 31.46, "amount_usd": 1.88}]
        r = reason_about_plan("sell my moodeng", actions, [], self._state({"MOODENG": 31.46}), 5.14)
        assert r.plan_summary and len(r.plan_summary) > 10

    def test_step_summaries_match_action_count(self):
        from backend.agents.trade_reasoner import reason_about_plan
        actions = [
            {"side": "sell", "asset": "MOODENG", "base_size": 31.46, "amount_usd": 1.88},
            {"side": "sell", "asset": "MORPHO", "base_size": 1.41, "amount_usd": 2.22},
        ]
        r = reason_about_plan("sell everything", actions, [], self._state({"MOODENG": 31.46, "MORPHO": 1.41}), 5.14)
        assert len(r.step_summaries) == 2

    def test_risk_flag_for_large_liquidation(self):
        from backend.agents.trade_reasoner import reason_about_plan
        actions = [
            {"side": "sell", "asset": "MOODENG", "base_size": 31.46, "amount_usd": 1.88},
            {"side": "sell", "asset": "MORPHO", "base_size": 1.41, "amount_usd": 2.22},
            {"side": "sell", "asset": "BTC", "base_size": 0.000005, "amount_usd": 0.31},
        ]
        r = reason_about_plan("sell everything", actions, [], self._state({"MOODENG": 31.46, "MORPHO": 1.41, "BTC": 0.000005}), 5.14)
        all_text = " ".join(r.risk_flags + r.warnings + [r.plan_summary]).lower()
        assert any(w in all_text for w in ["portfolio", "liquidat", "cash", "91", "85", "percent", "%"])

    def test_alternatives_when_blocked(self):
        from backend.agents.trade_reasoner import reason_about_plan
        actions = [{"side": "sell", "asset": "MORPHO", "base_size": 1.41, "amount_usd": 2.22}]
        failures = ["MOODENG funds are on hold and not currently executable"]
        r = reason_about_plan("sell all my holdings", actions, failures, self._state({"MORPHO": 1.41}), 5.14)
        assert r.confidence in ("medium", "high")

    def test_graceful_degradation(self):
        from unittest.mock import MagicMock, patch
        from backend.agents.trade_reasoner import reason_about_plan
        actions = [{"side": "sell", "asset": "BTC", "base_size": 0.000005, "amount_usd": 0.31}]
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API down")
        with patch("openai.OpenAI", return_value=mock_client):
            r = reason_about_plan("sell btc", actions, [], self._state({"BTC": 0.000005}), 5.14)
        assert r is not None
        assert r.confidence in ("high", "medium", "low")
        assert len(r.step_summaries) == 1

    def test_narrative_validates_with_reasoning(self):
        """build_trade_narrative must pass _validate() when reasoning is injected."""
        from backend.agents.trade_reasoner import TradeReasoning
        from backend.agents.narrative import build_trade_narrative
        reasoning = TradeReasoning(
            plan_summary="Selling MOODENG and MORPHO for ~$4.10 combined.",
            step_summaries=[
                "Step 1 (ready): SELL 31.460000 MOODENG @ market — est. $1.88",
                "Step 2 (queued): SELL 1.410000 MORPHO @ market — est. $2.22",
            ],
            risk_flags=["This removes all crypto exposure from your account"],
            portfolio_impact="Sells ~$4.10 of $5.14 total portfolio (79.8%)",
            confidence="high",
        )
        actions = [
            {"side": "sell", "asset": "MOODENG", "base_size": 31.46, "amount_usd": 1.88, "step_status": "READY"},
            {"side": "sell", "asset": "MORPHO", "base_size": 1.41, "amount_usd": 2.22, "step_status": "QUEUED"},
        ]
        result = build_trade_narrative(
            interpretation="SELL full positions",
            actions=actions,
            failures=[],
            is_sequential=True,
            evidence_items=[
                {"label": "Executable balances snapshot", "href": "url:/runs"},
                {"label": "Trade preflight report", "href": "url:/runs"},
            ],
            mode="LIVE",
            reasoning=reasoning,
        )
        assert "MOODENG" in result or "Selling" in result
        assert "CONFIRM" in result
