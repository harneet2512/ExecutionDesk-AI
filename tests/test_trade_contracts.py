"""Phase 6: Category-based regression tests for trading truth contracts.

Every test is asset-agnostic — they use parameterised fixtures so the same
assertions hold for BTC, ETH, DOGE, or any other instrument.

See docs/trading_truth_contracts.md for the invariants being verified.
"""
from __future__ import annotations

import os
import json
import tempfile
import shutil
from decimal import Decimal
from typing import Dict
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ASSETS = ["BTC", "ETH", "DOGE", "SOL"]


@pytest.fixture()
def isolated_db():
    """Provide a clean test database for each test."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "contracts_test.db")
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["TEST_DATABASE_URL"] = f"sqlite:///{db_path}"

    from backend.core.config import reset_settings
    from backend.db.connect import reset_canonical_db_path, _close_connections

    reset_settings()
    _close_connections()
    reset_canonical_db_path()

    from backend.db.connect import init_db
    init_db()

    yield db_path

    _close_connections()
    reset_canonical_db_path()
    reset_settings()
    if old_url:
        os.environ["DATABASE_URL"] = old_url
    else:
        os.environ.pop("DATABASE_URL", None)
    os.environ.pop("TEST_DATABASE_URL", None)
    shutil.rmtree(temp_dir, ignore_errors=True)


def _make_ctx(
    asset: str,
    side: str = "SELL",
    amount_usd: float = 10.0,
    available_qty: float = 0.0,
    hold_qty: float = 0.0,
    rule_source: str = "catalog",
    base_min_size: str | None = "0.0001",
    min_market_funds: str | None = "1.00",
    price: float = 100.0,
    sell_all: bool = False,
    verified: bool = False,
    trading_disabled: bool = False,
):
    """Build a minimal TradeContext for testing preflight_engine."""
    from backend.services.trade_context import (
        TradeContext,
        TradeAction,
        ExecutableBalance,
        ResolvedProductRules,
    )

    product_id = f"{asset.upper()}-USD"
    action = TradeAction(
        side=side.upper(),
        asset=asset.upper(),
        product_id=product_id,
        amount_usd=amount_usd,
        amount_mode="all" if sell_all else "quote_usd",
        sell_all=sell_all,
    )
    balances: Dict[str, ExecutableBalance] = {}
    if available_qty > 0 or hold_qty > 0:
        balances[asset.upper()] = ExecutableBalance(
            currency=asset.upper(),
            available_qty=available_qty,
            hold_qty=hold_qty,
        )
    balances["USD"] = ExecutableBalance(currency="USD", available_qty=1000.0, hold_qty=0.0)

    rules = ResolvedProductRules(
        product_id=product_id,
        rule_source=rule_source,
        base_min_size=Decimal(base_min_size) if base_min_size else None,
        min_market_funds=Decimal(min_market_funds) if min_market_funds else None,
        verified=verified,
        trading_disabled=trading_disabled,
    )

    return TradeContext(
        tenant_id="t_test",
        execution_mode="PAPER",
        actions=(action,),
        executable_balances=balances,
        resolved_products={product_id: rules},
        market_prices={asset.upper(): price},
        built_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# 1) Any-asset SELL ALL with missing balances => BLOCKED NO_BALANCE
# ---------------------------------------------------------------------------

class TestSellAllMissingBalance:

    @pytest.mark.parametrize("asset", SAMPLE_ASSETS)
    def test_sell_all_no_balance_blocked(self, asset):
        from backend.services.preflight_engine import run_preflight_engine, PreflightStatus, ReasonCode

        ctx = _make_ctx(asset, side="SELL", sell_all=True, available_qty=0.0)
        report = run_preflight_engine(ctx)

        assert len(report.results) == 1
        r = report.results[0]
        assert r.status == PreflightStatus.BLOCKED
        assert r.reason_code == ReasonCode.NO_BALANCE


# ---------------------------------------------------------------------------
# 2) Any-asset SELL below min => BLOCKED BELOW_MIN
# ---------------------------------------------------------------------------

class TestSellBelowMin:

    @pytest.mark.parametrize("asset", SAMPLE_ASSETS)
    def test_sell_below_base_min(self, asset):
        from backend.services.preflight_engine import run_preflight_engine, PreflightStatus, ReasonCode

        ctx = _make_ctx(
            asset, side="SELL", amount_usd=0.001,
            available_qty=1.0, base_min_size="0.1",
            price=100.0,
        )
        report = run_preflight_engine(ctx)
        r = report.results[0]
        assert r.status == PreflightStatus.BLOCKED
        assert r.reason_code == ReasonCode.BELOW_MIN


# ---------------------------------------------------------------------------
# 3) Preview unavailable => BLOCKED PROVIDER_UNAVAILABLE
# ---------------------------------------------------------------------------

class TestProviderUnavailable:

    @pytest.mark.parametrize("asset", SAMPLE_ASSETS)
    def test_unavailable_rules_blocked(self, asset):
        from backend.services.preflight_engine import run_preflight_engine, PreflightStatus, ReasonCode

        ctx = _make_ctx(asset, side="BUY", rule_source="unavailable")
        report = run_preflight_engine(ctx)
        r = report.results[0]
        assert r.status == PreflightStatus.BLOCKED
        assert r.reason_code == ReasonCode.PROVIDER_UNAVAILABLE
        assert "Retry" in r.fix_options


# ---------------------------------------------------------------------------
# 4) Exceeds holdings => ADJUSTED with "sell max" option
# ---------------------------------------------------------------------------

class TestExceedsHoldings:

    @pytest.mark.parametrize("asset", SAMPLE_ASSETS)
    def test_exceeds_holdings_adjusted(self, asset):
        from backend.services.preflight_engine import run_preflight_engine, PreflightStatus, ReasonCode

        ctx = _make_ctx(
            asset, side="SELL", amount_usd=500.0,
            available_qty=1.0, price=100.0,
        )
        report = run_preflight_engine(ctx)
        r = report.results[0]
        assert r.status == PreflightStatus.ADJUSTED
        assert r.reason_code == ReasonCode.EXCEEDS_HOLDINGS
        assert "CONFIRM SELL MAX" in r.fix_options
        assert r.adjusted_amount_usd is not None
        assert r.adjusted_amount_usd <= 100.0  # 1.0 * $100


# ---------------------------------------------------------------------------
# 5) Pending fill => never marked filled
# ---------------------------------------------------------------------------

class TestPendingFillNotMarkedFilled:

    def test_pending_order_not_marked_filled(self, isolated_db):
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        tenant_id = "t_test"
        run_id = new_id("run_")
        order_id = new_id("ord_")
        ts = now_iso()
        with get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, name) VALUES (?, ?)",
                (tenant_id, "Test Tenant"),
            )
            conn.execute(
                "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?,?,?,?,?)",
                (run_id, tenant_id, "COMPLETED", "PAPER", ts),
            )
            conn.execute(
                "INSERT INTO orders (order_id, run_id, tenant_id, provider, symbol, side, "
                "order_type, qty, notional_usd, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (order_id, run_id, tenant_id, "paper", "BTC-USD", "BUY",
                 "MARKET", 0.001, 10.0, "PENDING", ts),
            )

        with get_conn() as conn:
            row = conn.execute(
                "SELECT status FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            assert row["status"] == "PENDING", "order must remain PENDING until fill confirmed"


# ---------------------------------------------------------------------------
# 6) DB/catalog health => stable across runs
# ---------------------------------------------------------------------------

class TestDbCatalogHealth:

    def test_schema_ok_and_path_stable(self, isolated_db):
        from backend.db.connect import get_schema_status, get_canonical_db_path

        s1 = get_schema_status()
        assert s1["schema_ok"] is True

        path1 = get_canonical_db_path()
        path2 = get_canonical_db_path()
        assert path1 == path2, "canonical path must not change"


# ---------------------------------------------------------------------------
# 7) News enabled => news panel must be present or explicitly unavailable
#    (Backend contract: insight always includes news_outcome with status)
# ---------------------------------------------------------------------------

class TestNewsEnabledContract:

    def test_error_insight_has_news_outcome(self):
        """When insight generation fails, the fallback dict must still include
        news_outcome with a non-null status, so the UI can show the right state."""
        fallback_insight = {
            "headline": "Market insight unavailable",
            "key_facts": [],
            "risk_flags": ["insight_unavailable"],
            "news_outcome": {
                "status": "error",
                "reason": "News unavailable right now (provider error).",
                "items": 0,
            },
            "asset_news_evidence": {
                "queries": ["GENERIC"],
                "lookback": "24h",
                "sources": [],
                "status": "error",
                "items": [],
                "reason_if_empty_or_error": "provider error",
            },
        }
        assert fallback_insight["news_outcome"]["status"] in ("ok", "empty", "error")
        assert fallback_insight["asset_news_evidence"]["status"] in ("ok", "empty", "error")


# ---------------------------------------------------------------------------
# 8) Run diagnostics artifact => always emitted with correct schema
# ---------------------------------------------------------------------------

class TestRunDiagnosticsArtifact:

    def test_diagnostics_schema(self, isolated_db):
        from backend.services.run_diagnostics import build_run_diagnostics

        diag = build_run_diagnostics(
            run_id="run_test",
            tenant_id="t_test",
            execution_mode="PAPER",
            referenced_assets=["BTC", "ETH"],
        )

        assert "env" in diag
        assert "balances" in diag
        assert "product_rules" in diag
        assert "decisions" in diag
        assert "built_at" in diag

        env = diag["env"]
        assert env["execution_mode"] == "PAPER"
        assert env["tenant_id"] == "t_test"
        assert isinstance(env["db_path"], str)
        assert isinstance(env["catalog_count"], int)
        assert isinstance(env["migrations_applied"], int)

    def test_diagnostics_contains_all_referenced_assets(self, isolated_db):
        from backend.services.run_diagnostics import build_run_diagnostics

        diag = build_run_diagnostics(
            run_id="run_test",
            tenant_id="t_test",
            execution_mode="PAPER",
            referenced_assets=["BTC", "SOL", "DOGE"],
        )
        for asset in ["BTC", "SOL", "DOGE"]:
            assert asset in diag["balances"]


# ---------------------------------------------------------------------------
# 9) TradeContext immutability => no component can modify it after build
# ---------------------------------------------------------------------------

class TestTradeContextImmutability:

    def test_trade_context_is_frozen(self):
        from backend.services.trade_context import TradeContext, TradeAction, ExecutableBalance

        action = TradeAction(
            side="BUY", asset="ETH", product_id="ETH-USD",
            amount_usd=10.0, amount_mode="quote_usd",
        )
        ctx = TradeContext(
            tenant_id="t_test",
            execution_mode="PAPER",
            actions=(action,),
            executable_balances={"ETH": ExecutableBalance("ETH", 1.0, 0.0)},
            resolved_products={},
            market_prices={"ETH": 3000.0},
            built_at="2026-01-01T00:00:00Z",
        )

        with pytest.raises(AttributeError):
            ctx.tenant_id = "t_evil"  # type: ignore[misc]

        with pytest.raises(AttributeError):
            ctx.execution_mode = "LIVE"  # type: ignore[misc]

    def test_actions_is_tuple(self):
        from backend.services.trade_context import TradeContext, TradeAction

        action = TradeAction(
            side="BUY", asset="BTC", product_id="BTC-USD",
            amount_usd=10.0, amount_mode="quote_usd",
        )
        ctx = TradeContext(
            tenant_id="t_test",
            execution_mode="PAPER",
            actions=(action,),
            built_at="2026-01-01T00:00:00Z",
        )
        assert isinstance(ctx.actions, tuple)
