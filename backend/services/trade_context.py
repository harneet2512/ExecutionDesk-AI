"""Unified TradeContext — single source of truth for trade planning and execution.

All planning, preflight, and execution code must consume a TradeContext
rather than querying balances, catalogs, or prices ad-hoc.  The context
is built once per trade intent and is immutable after construction.

See docs/trading_truth_contracts.md Section 4 for the contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from backend.core.logging import get_logger
from backend.core.time import now_iso

logger = get_logger(__name__)

RuleSource = Literal["preview", "catalog", "fallback", "unavailable"]


@dataclass(frozen=True)
class ResolvedProductRules:
    """Product trading rules with provenance tracking."""
    product_id: str
    rule_source: RuleSource
    base_min_size: Optional[Decimal] = None
    base_increment: Optional[Decimal] = None
    min_market_funds: Optional[Decimal] = None
    status: Optional[str] = None
    trading_disabled: bool = False
    verified: bool = False


@dataclass
class TradeAction:
    """A single requested trade action."""
    side: str        # BUY | SELL
    asset: str       # e.g. "BTC", "ETH"
    product_id: str  # e.g. "BTC-USD"
    amount_usd: float
    amount_mode: str  # quote_usd | base_qty | all
    sell_all: bool = False
    requested_qty: Optional[float] = None


@dataclass(frozen=True)
class ExecutableBalance:
    """Per-currency balance from the authoritative state source."""
    currency: str
    available_qty: float
    hold_qty: float


@dataclass(frozen=True)
class TradeContext:
    """Immutable context snapshot for a single trade intent.

    No component should query balances, product rules, or prices
    independently once a TradeContext has been built.
    """
    tenant_id: str
    execution_mode: str
    actions: tuple  # tuple[TradeAction, ...] — frozen for immutability
    executable_balances: Dict[str, ExecutableBalance] = field(default_factory=dict)
    resolved_products: Dict[str, ResolvedProductRules] = field(default_factory=dict)
    market_prices: Dict[str, float] = field(default_factory=dict)
    built_at: str = ""

    def get_balance(self, currency: str) -> Optional[ExecutableBalance]:
        return self.executable_balances.get(currency.upper())

    def get_product_rules(self, product_id: str) -> Optional[ResolvedProductRules]:
        return self.resolved_products.get(product_id)

    def get_price(self, asset: str) -> Optional[float]:
        return self.market_prices.get(asset.upper())


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _resolve_product_rules(product_id: str) -> ResolvedProductRules:
    """Resolve product trading rules through the precedence chain.

    1. Market metadata service (brokerage API / cache)
    2. Product catalog (public Exchange API, DB-backed)
    3. Mark as 'unavailable' — no silent hardcoded fallback
    """
    # Tier 1: metadata service (brokerage API + cache)
    try:
        from backend.services.market_metadata import get_metadata_service
        svc = get_metadata_service()
        result = svc.get_product_details_sync(product_id, allow_stale=True)
        if result.success and result.data:
            return ResolvedProductRules(
                product_id=product_id,
                rule_source="catalog" if result.used_stale_cache else "preview",
                base_min_size=_to_decimal(result.data.get("base_min_size")),
                base_increment=_to_decimal(result.data.get("base_increment")),
                min_market_funds=_to_decimal(result.data.get("min_market_funds")),
                status=result.data.get("status"),
                trading_disabled=bool(result.data.get("trading_disabled")),
                verified=not result.used_stale_cache,
            )
    except Exception as exc:
        logger.debug("metadata service lookup failed for %s: %s", product_id, str(exc)[:120])

    # Tier 2: product catalog (public API, persistent DB)
    try:
        from backend.services.product_catalog import get_product_catalog
        prod = get_product_catalog().get_product(product_id)
        if prod:
            return ResolvedProductRules(
                product_id=product_id,
                rule_source="catalog",
                base_min_size=_to_decimal(prod.base_min_size),
                base_increment=_to_decimal(prod.base_increment),
                min_market_funds=_to_decimal(prod.min_market_funds),
                status=prod.status,
                trading_disabled=prod.trading_disabled,
                verified=False,
            )
    except Exception as exc:
        logger.debug("catalog lookup failed for %s: %s", product_id, str(exc)[:120])

    # Tier 3: unavailable — no hardcoded fallback
    return ResolvedProductRules(
        product_id=product_id,
        rule_source="unavailable",
        verified=False,
    )


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def build_trade_context(
    tenant_id: str,
    execution_mode: str,
    actions: List[TradeAction],
) -> TradeContext:
    """Build an immutable TradeContext for a set of trade actions.

    1. Fetches ExecutableState once (authoritative for balances).
    2. Resolves product rules for every referenced product.
    3. Fetches current market prices (display only).
    """
    # ---- 1. Executable balances (single fetch) ----
    balances: Dict[str, ExecutableBalance] = {}
    try:
        from backend.services.executable_state import fetch_executable_state
        state = fetch_executable_state(tenant_id)
        for currency, bal in (state.balances or {}).items():
            balances[currency.upper()] = ExecutableBalance(
                currency=currency.upper(),
                available_qty=bal.available_qty,
                hold_qty=bal.hold_qty,
            )
    except Exception as exc:
        logger.warning("build_trade_context: balance fetch failed: %s", str(exc)[:200])

    # ---- 2. Collect all referenced product IDs ----
    product_ids: List[str] = []
    for a in actions:
        pid = a.product_id or f"{a.asset.upper()}-USD"
        if pid not in product_ids:
            product_ids.append(pid)

    # ---- 3. Resolve product rules (no hardcoded fallback) ----
    resolved: Dict[str, ResolvedProductRules] = {}
    for pid in product_ids:
        resolved[pid] = _resolve_product_rules(pid)

    # ---- 4. Market prices (best-effort, display only) ----
    prices: Dict[str, float] = {}
    for a in actions:
        asset = a.asset.upper()
        if asset in prices or asset == "USD":
            continue
        try:
            from backend.services.market_data import get_price
            px = float(get_price(asset))
            if px > 0:
                prices[asset] = px
        except Exception:
            pass

    return TradeContext(
        tenant_id=tenant_id,
        execution_mode=execution_mode,
        actions=tuple(actions),
        executable_balances=balances,
        resolved_products=resolved,
        market_prices=prices,
        built_at=now_iso(),
    )
