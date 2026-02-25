import pytest

from backend.agents.narrative import build_trade_narrative
from backend.services.asset_resolver import (
    RESOLUTION_FUNDS_ON_HOLD,
    RESOLUTION_OK,
    RESOLUTION_QTY_ZERO,
    resolve_all_holdings,
    resolve_from_executable_state,
)
from backend.services.executable_state import ExecutableBalance, ExecutableState
from backend.services.trade_preflight import PreflightRejectReason, run_preflight


def _state(balances):
    return ExecutableState(
        balances=balances,
        fetched_at="2026-02-20T00:00:00Z",
        source="coinbase_list_accounts",
    )


def _catalog(**kwargs):
    return kwargs


def test_morpho_tradable_resolution_ok():
    state = _state(
        {
            "MORPHO": ExecutableBalance(
                currency="MORPHO",
                available_qty=1.41,
                hold_qty=0.0,
                account_uuid="acc-1",
                updated_at="2026-02-20T00:00:00Z",
            )
        }
    )
    catalog = _catalog(**{"MORPHO-USD": {"is_disabled": False, "trading_disabled": False}})
    res = resolve_from_executable_state("MORPHO", state, catalog)
    assert res.resolution_status == RESOLUTION_OK
    assert res.executable_qty == 1.41
    assert res.product_id == "MORPHO-USD"


def test_qty_zero_and_funds_on_hold_paths():
    state = _state(
        {
            "MORPHO": ExecutableBalance("MORPHO", 0.0, 0.0, "a", "t"),
            "MOODENG": ExecutableBalance("MOODENG", 0.0, 31.46, "b", "t"),
        }
    )
    catalog = _catalog(
        **{
            "MORPHO-USD": {"is_disabled": False, "trading_disabled": False},
            "MOODENG-USD": {"is_disabled": False, "trading_disabled": False},
        }
    )
    r_zero = resolve_from_executable_state("MORPHO", state, catalog)
    r_hold = resolve_from_executable_state("MOODENG", state, catalog)
    assert r_zero.resolution_status == RESOLUTION_QTY_ZERO
    assert r_hold.resolution_status == RESOLUTION_FUNDS_ON_HOLD


def test_sell_all_excludes_usd_and_nontradable():
    state = _state(
        {
            "USD": ExecutableBalance("USD", 200.0, 0.0, "u", "t"),
            "USDC": ExecutableBalance("USDC", 100.0, 0.0, "u2", "t"),
            "MORPHO": ExecutableBalance("MORPHO", 1.41, 0.0, "m", "t"),
            "MOODENG": ExecutableBalance("MOODENG", 0.0, 31.46, "d", "t"),
            "SOL": ExecutableBalance("SOL", 2.0, 0.0, "s", "t"),
        }
    )
    catalog = _catalog(
        **{
            "MORPHO-USD": {"is_disabled": False, "trading_disabled": False},
            "MOODENG-USD": {"is_disabled": False, "trading_disabled": False},
            "SOL-USD": {"is_disabled": False, "trading_disabled": True},
        }
    )
    tradable, skipped = resolve_all_holdings(state, catalog)
    tradable_symbols = [r.symbol for r in tradable]
    skipped_symbols = [r.symbol for r in skipped]
    assert "USD" not in tradable_symbols and "USDC" not in tradable_symbols
    assert tradable_symbols == ["MORPHO"]
    assert "MOODENG" in skipped_symbols and "SOL" in skipped_symbols


@pytest.mark.asyncio
async def test_preflight_uses_executable_qty_and_sets_primary_reason():
    ok = await run_preflight(
        tenant_id="t1",
        side="SELL",
        asset="MORPHO",
        amount_usd=5.0,
        asset_class="CRYPTO",
        mode="LIVE",
        executable_qty=1.0,
        hold_qty=0.0,
        product_flags={"is_disabled": False, "trading_disabled": False, "limit_only": False, "cancel_only": False},
        artifacts={"balances_artifact": "run:x#balances"},
    )
    assert ok.valid is True
    assert ok.to_dict().get("primary_reason_code") is None

    blocked = await run_preflight(
        tenant_id="t1",
        side="SELL",
        asset="MORPHO",
        amount_usd=5.0,
        asset_class="CRYPTO",
        mode="LIVE",
        executable_qty=0.0,
        hold_qty=0.2,
        product_flags={"is_disabled": False, "trading_disabled": False, "limit_only": False, "cancel_only": False},
    )
    assert blocked.valid is False
    assert blocked.reason_code == PreflightRejectReason.FUNDS_ON_HOLD
    assert "hold" in (blocked.user_message or "").lower()


def test_no_unrelated_product_fallback():
    state = _state({"MOODENG": ExecutableBalance("MOODENG", 1.0, 0.0, "a", "t")})
    catalog = _catalog(**{"SOL-USD": {"is_disabled": False, "trading_disabled": False}})
    res = resolve_from_executable_state("MOODENG", state, catalog)
    assert res.product_id is None


def test_narrative_avoids_internal_tokens():
    text = build_trade_narrative(
        interpretation="SELL MORPHO",
        actions=[{"side": "sell", "asset": "MORPHO", "base_size": 1.41, "step_status": "READY"}],
        failures=[],
        is_sequential=False,
        evidence_items=[
            {"label": "Executable balances snapshot", "href": "url:/runs"},
            {"label": "Trade preflight report", "href": "url:/runs"},
        ],
        mode="LIVE",
    )
    assert "trade_preflight" not in text
    assert "portfolio_snapshots" not in text
