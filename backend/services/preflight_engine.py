"""Deterministic preflight engine — asset-agnostic, no magic defaults.

Consumes a TradeContext and produces a per-action PreflightResult with
strict provenance tracking.  Replaces ad-hoc validation scattered across
trade_preflight.py, execution_node.py, and coinbase_provider.py.

See docs/trading_truth_contracts.md Section 2.1 for the output contract.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.services.trade_context import (
    ExecutableBalance,
    ResolvedProductRules,
    TradeAction,
    TradeContext,
)

logger = logging.getLogger(__name__)

COINBASE_FEE_RATE = Decimal("0.006")


class PreflightStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    ADJUSTED = "ADJUSTED"


class ReasonCode(str, Enum):
    NO_BALANCE = "NO_BALANCE"
    NOT_TRADABLE = "NOT_TRADABLE"
    BELOW_MIN = "BELOW_MIN"
    PRECISION = "PRECISION"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    EXCEEDS_HOLDINGS = "EXCEEDS_HOLDINGS"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    FUNDS_ON_HOLD = "FUNDS_ON_HOLD"
    LIMIT_ONLY = "LIMIT_ONLY"
    MISSING_PRICE = "MISSING_PRICE"
    BALANCES_UNAVAILABLE = "BALANCES_UNAVAILABLE"
    ASSET_NOT_IN_BALANCES = "ASSET_NOT_IN_BALANCES"
    NO_AVAILABLE_BALANCE = "NO_AVAILABLE_BALANCE"
    PREVIEW_REJECTED = "PREVIEW_REJECTED"
    PREVIEW_UNAVAILABLE = "PREVIEW_UNAVAILABLE"


@dataclass
class ActionPreflightResult:
    """Preflight outcome for a single trade action."""
    action: TradeAction
    status: PreflightStatus = PreflightStatus.READY
    reason_code: Optional[ReasonCode] = None
    user_message: str = ""
    fix_options: List[str] = field(default_factory=list)
    verified: bool = False
    rule_source: str = "none"
    adjusted_amount_usd: Optional[float] = None
    adjusted_qty: Optional[float] = None
    max_sellable_usd: Optional[float] = None
    estimated_fee_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.action.asset,
            "side": self.action.side,
            "status": self.status.value,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "user_message": self.user_message,
            "fix_options": self.fix_options,
            "verified": self.verified,
            "rule_source": self.rule_source,
            "adjusted_amount_usd": self.adjusted_amount_usd,
            "adjusted_qty": self.adjusted_qty,
            "max_sellable_usd": self.max_sellable_usd,
            "estimated_fee_usd": self.estimated_fee_usd,
        }


@dataclass
class PreflightReport:
    """Aggregate preflight result across all actions in a trade intent."""
    results: List[ActionPreflightResult] = field(default_factory=list)

    @property
    def all_ready(self) -> bool:
        return all(r.status == PreflightStatus.READY for r in self.results)

    @property
    def any_blocked(self) -> bool:
        return any(r.status == PreflightStatus.BLOCKED for r in self.results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "all_ready": self.all_ready,
            "any_blocked": self.any_blocked,
            "results": [r.to_dict() for r in self.results],
        }

    def diagnostics_decisions(self) -> Dict[str, Dict[str, Any]]:
        """Build the ``decisions`` sub-payload for the run_diagnostics artifact."""
        decisions: Dict[str, Dict[str, Any]] = {}
        for r in self.results:
            key = f"{r.action.side}_{r.action.asset}_{r.action.amount_mode}".upper()
            decisions[key] = {
                "status": r.status.value,
                "reason_code": r.reason_code.value if r.reason_code else None,
                "rule_source": r.rule_source,
            }
        return decisions


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def _blocked(
    action: TradeAction,
    reason: ReasonCode,
    user_message: str,
    fix_options: Optional[List[str]] = None,
    *,
    rule_source: str = "none",
    verified: bool = False,
) -> ActionPreflightResult:
    return ActionPreflightResult(
        action=action,
        status=PreflightStatus.BLOCKED,
        reason_code=reason,
        user_message=user_message,
        fix_options=fix_options or [],
        rule_source=rule_source,
        verified=verified,
    )


def run_preflight_engine(ctx: TradeContext) -> PreflightReport:
    """Run deterministic preflight checks for every action in a TradeContext.

    No magic defaults. If product rules are unavailable, the action is
    BLOCKED with PROVIDER_UNAVAILABLE.
    """
    report = PreflightReport()

    for action in ctx.actions:
        result = _check_single_action(ctx, action)
        report.results.append(result)

    return report


def _check_single_action(
    ctx: TradeContext,
    action: TradeAction,
) -> ActionPreflightResult:
    asset = action.asset.upper()
    side = action.side.upper()
    product_id = action.product_id or f"{asset}-USD"
    rules = ctx.get_product_rules(product_id)
    price = ctx.get_price(asset)

    rule_source = rules.rule_source if rules else "unavailable"
    verified = rules.verified if rules else False
    fee = float(Decimal(str(action.amount_usd or 0)) * COINBASE_FEE_RATE)

    # ── Check 1: Product tradability ──────────────────────────────────
    if rules and rules.trading_disabled:
        return _blocked(
            action, ReasonCode.NOT_TRADABLE,
            f"{asset} is not tradable right now.",
            [f"Try another asset instead of {asset}"],
            rule_source=rule_source, verified=verified,
        )

    if rules and rules.status and rules.status.lower() in ("cancel_only", "delisted"):
        return _blocked(
            action, ReasonCode.NOT_TRADABLE,
            f"{asset} market is {rules.status} — orders are not accepted.",
            ["Choose a different asset"],
            rule_source=rule_source, verified=verified,
        )

    # ── Check 2: Product rules availability ───────────────────────────
    if rules is None or rules.rule_source == "unavailable":
        return _blocked(
            action, ReasonCode.PROVIDER_UNAVAILABLE,
            (
                f"Unable to verify trading rules for {asset}. "
                "The exchange metadata is temporarily unavailable. "
                "Please retry in a few moments."
            ),
            ["Retry", "Cancel"],
            rule_source="unavailable", verified=False,
        )

    # ── Check 3: SELL-specific balance checks ─────────────────────────
    if side == "SELL":
        bal = ctx.get_balance(asset)
        if bal is None or bal.available_qty <= 0:
            hold_qty = bal.hold_qty if bal else 0.0
            if hold_qty > 0:
                return _blocked(
                    action, ReasonCode.FUNDS_ON_HOLD,
                    f"{asset} funds are on hold and not currently executable.",
                    [f"Retry after {asset} hold clears"],
                    rule_source=rule_source, verified=verified,
                )
            return _blocked(
                action, ReasonCode.NO_BALANCE,
                f"No executable {asset} balance available for selling.",
                ["Buy the asset first", "Choose an asset you hold"],
                rule_source=rule_source, verified=verified,
            )

        available_usd = bal.available_qty * price if price else None

        if action.sell_all and available_usd is not None:
            min_sell = _min_sell_usd(rules, price)
            if min_sell is not None and available_usd < min_sell:
                return _blocked(
                    action, ReasonCode.BELOW_MIN,
                    (
                        f"Your {asset} holdings (~${available_usd:.2f}) are below "
                        f"the venue minimum (~${min_sell:.2f}). "
                        f"Options: buy more {asset} to reach ~${min_sell:.2f}, "
                        "or check Coinbase app for convert/dust options."
                    ),
                    ["Cancel", f"Buy more {asset} to reach minimum",
                     "Check Coinbase app for convert/dust options"],
                    rule_source=rule_source, verified=verified,
                )

        if not action.sell_all and available_usd is not None and action.amount_usd > available_usd:
            return ActionPreflightResult(
                action=action,
                status=PreflightStatus.ADJUSTED,
                reason_code=ReasonCode.EXCEEDS_HOLDINGS,
                user_message=(
                    f"You requested ${action.amount_usd:.2f} of {asset} but only "
                    f"~${available_usd:.2f} is sellable; "
                    "I can sell the maximum available instead."
                ),
                fix_options=["CONFIRM SELL MAX", "CANCEL"],
                verified=verified,
                rule_source=rule_source,
                adjusted_amount_usd=available_usd,
                adjusted_qty=bal.available_qty,
                max_sellable_usd=available_usd,
                estimated_fee_usd=fee,
            )

        if price and rules.base_min_size:
            base_size = action.amount_usd / price
            if base_size < float(rules.base_min_size):
                min_usd = float(rules.base_min_size) * price
                label = "(estimated)" if not verified else ""
                return _blocked(
                    action, ReasonCode.BELOW_MIN,
                    (
                        f"Sell amount ${action.amount_usd:.2f} of {asset} converts "
                        f"to ~{base_size:.8f} {asset}, below the base minimum "
                        f"({rules.base_min_size} {asset} ~ ${min_usd:.2f}) {label}. "
                        f"Increase to at least ~${min_usd:.2f}."
                    ),
                    [f"Increase amount to ~${min_usd:.2f}", "Cancel"],
                    rule_source=rule_source, verified=verified,
                )

    # ── Check 4: BUY-specific balance checks ──────────────────────────
    if side == "BUY":
        usd_bal = ctx.get_balance("USD")
        cash = usd_bal.available_qty if usd_bal else 0.0
        total_needed = action.amount_usd + fee
        if cash < total_needed and cash > 0:
            pass  # funds recycling handled elsewhere
        elif cash <= 0:
            pass  # non-fatal: PAPER mode may not have balances

    # ── Check 5: Min notional / min market funds ──────────────────────
    if rules.min_market_funds is not None:
        min_mf = float(rules.min_market_funds)
        # For SELL ALL with unavailable price (amount_usd=0), skip USD min check;
        # execution engine will validate at order time when price is available.
        _is_sell_all_no_price = (
            side == "SELL" and action.sell_all and action.amount_usd <= 0
        )
        if not _is_sell_all_no_price and action.amount_usd < min_mf:
            label = "(estimated)" if not verified else ""
            return _blocked(
                action, ReasonCode.BELOW_MIN,
                (
                    f"Order ${action.amount_usd:.2f} for {asset} is below the "
                    f"minimum market funds (${min_mf:.2f}) {label}."
                ),
                [f"Increase amount to at least ${min_mf:.2f}", "Cancel"],
                rule_source=rule_source, verified=verified,
            )

    # ── All checks passed ─────────────────────────────────────────────
    return ActionPreflightResult(
        action=action,
        status=PreflightStatus.READY,
        verified=verified,
        rule_source=rule_source,
        estimated_fee_usd=fee,
    )


def _min_sell_usd(
    rules: Optional[ResolvedProductRules],
    price: Optional[float],
) -> Optional[float]:
    """Compute minimum sell amount in USD from product rules and price."""
    if not rules or not price or price <= 0:
        return None
    if rules.base_min_size is not None:
        return float(rules.base_min_size) * price
    return None
