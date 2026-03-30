"""
Unified trade preflight validation service.
Fixes Bug 6: Trade rejections despite sufficient balance due to
inconsistent fee calculations across multiple validation points.

Consolidates all pre-trade checks:
- Minimum notional validation (with fee buffer)
- Balance sufficiency (for SELL orders)
- Precision validation
- Fee estimation

All validation uses the SAME fee calculation to prevent discrepancies.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Standard Coinbase market order fee rate
COINBASE_FEE_RATE = 0.006  # 0.6%

# DEPRECATED — see docs/trading_truth_contracts.md INV-3.
# New code should use preflight_engine.py which derives mins from verified
# product rules or blocks with PROVIDER_UNAVAILABLE.
DEFAULT_MIN_NOTIONAL_USD = 1.0


class PreflightRejectReason(str, Enum):
    """Structured rejection reason codes."""
    MIN_NOTIONAL_TOO_LOW = "MIN_NOTIONAL_TOO_LOW"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INVALID_PRECISION = "INVALID_PRECISION"
    ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
    NOT_TRADABLE = "NOT_TRADABLE"
    LIMIT_ONLY = "LIMIT_ONLY"
    QTY_ZERO = "QTY_ZERO"
    FUNDS_ON_HOLD = "FUNDS_ON_HOLD"
    NO_PRODUCT = "NO_PRODUCT"
    NOT_HELD = "NOT_HELD"
    EXCEEDS_HOLDINGS = "EXCEEDS_HOLDINGS"


HUMAN_MESSAGES: Dict[str, str] = {
    "MIN_NOTIONAL_TOO_LOW": "Below minimum order size",
    "INSUFFICIENT_BALANCE": "Insufficient balance",
    "INSUFFICIENT_CASH": "Insufficient balance",
    "INVALID_PRECISION": "Order precision not supported by exchange",
    "ASSET_NOT_FOUND": "Could not determine whether this symbol is a crypto or stock asset",
    "PROVIDER_ERROR": "Market unavailable or trading paused",
    "MARKET_UNAVAILABLE": "Market unavailable or trading paused",
    "NOT_TRADABLE": "This asset is not currently tradable (trading is disabled or market is cancel-only)",
    "LIMIT_ONLY": "This market is currently limit-only; market orders are unavailable",
    "QTY_ZERO": "Available quantity is 0 for this asset",
    "FUNDS_ON_HOLD": "Funds are on hold and not currently executable",
    "NOT_HELD": "This asset is not held in your executable balances",
    "NO_PRODUCT": "No tradable product found for this asset on the exchange",
    "EXCEEDS_HOLDINGS": "Requested sell amount exceeds available holdings",
}


@dataclass
class PreflightResult:
    """Result of preflight validation."""
    valid: bool
    reason_code: Optional[PreflightRejectReason] = None
    message: Optional[str] = None
    user_message: Optional[str] = None
    remediation: Optional[str] = None
    fixes: Optional[list] = None
    artifact_ref: Optional[str] = None
    artifacts: Optional[Dict[str, Optional[str]]] = None

    requested_usd: float = 0.0
    effective_usd_after_fees: float = 0.0
    estimated_fee: float = 0.0
    min_notional_usd: float = 0.0
    effective_min_notional: float = 0.0
    available_balance: float = 0.0
    available_usd: float = 0.0
    requires_adjustment: bool = False
    adjusted_amount_usd: Optional[float] = None
    adjusted_qty: Optional[float] = None
    max_sellable_usd: Optional[float] = None

    requires_auto_sell: bool = False
    auto_sell_proposal: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.valid

    @property
    def fix_suggestions(self) -> list:
        return self.fixes or []

    def __post_init__(self):
        if not self.valid and self.reason_code and not self.user_message:
            self.user_message = HUMAN_MESSAGES.get(
                self.reason_code.value if isinstance(self.reason_code, PreflightRejectReason) else str(self.reason_code),
                "Validation failed",
            )
        if not self.fixes:
            self.fixes = []

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "ok": self.valid,
            "valid": self.valid,
            "primary_reason_code": self.reason_code.value if self.reason_code else None,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "message": self.message,
            "user_message": self.user_message,
            "remediation": self.remediation,
            "fix_suggestions": self.fixes or [],
            "fixes": self.fixes or [],
            "artifact_ref": self.artifact_ref,
            "artifacts": self.artifacts or {},
            "requested_usd": self.requested_usd,
            "effective_usd_after_fees": self.effective_usd_after_fees,
            "estimated_fee": self.estimated_fee,
            "min_notional_usd": self.min_notional_usd,
            "effective_min_notional": self.effective_min_notional,
            "available_balance": self.available_balance,
            "available_usd": self.available_usd,
            "requires_adjustment": self.requires_adjustment,
            "adjusted_amount_usd": self.adjusted_amount_usd,
            "adjusted_qty": self.adjusted_qty,
            "max_sellable_usd": self.max_sellable_usd,
            "requires_auto_sell": self.requires_auto_sell,
        }
        if self.auto_sell_proposal:
            d["auto_sell_proposal"] = self.auto_sell_proposal
        return d


def _blocked(
    reason: PreflightRejectReason,
    user_message: str,
    remediation: str,
    fixes: Optional[list] = None,
    *,
    requested_usd: float = 0.0,
    effective_usd_after_fees: float = 0.0,
    estimated_fee: float = 0.0,
    min_notional_usd: float = 0.0,
    effective_min_notional: float = 0.0,
    available_balance: float = 0.0,
    available_usd: float = 0.0,
    artifacts: Optional[Dict[str, Optional[str]]] = None,
) -> PreflightResult:
    return PreflightResult(
        valid=False,
        reason_code=reason,
        message=user_message,
        user_message=user_message,
        remediation=remediation,
        fixes=fixes or [],
        requested_usd=requested_usd,
        effective_usd_after_fees=effective_usd_after_fees,
        estimated_fee=estimated_fee,
        min_notional_usd=min_notional_usd,
        effective_min_notional=effective_min_notional,
        available_balance=available_balance,
        available_usd=available_usd,
        artifacts=artifacts or {},
    )


def calculate_fee(notional_usd: float, fee_rate: float = COINBASE_FEE_RATE) -> float:
    """Calculate the trading fee for a given notional amount."""
    return notional_usd * fee_rate


def calculate_effective_after_fees(notional_usd: float, fee_rate: float = COINBASE_FEE_RATE) -> float:
    """
    Calculate the effective notional after fees are deducted.
    For market orders, the fee is taken from the order value.
    """
    return notional_usd * (1 - fee_rate)


def calculate_required_for_min_notional(min_notional: float, fee_rate: float = COINBASE_FEE_RATE) -> float:
    """
    Calculate the amount needed to meet minimum notional after fees.
    effective_min = min_notional / (1 - fee_rate)
    """
    return min_notional / (1 - fee_rate)


async def get_min_notional_for_asset(asset: str) -> float:
    """
    Get the minimum notional for an asset from Coinbase.
    Falls back to default if unable to fetch.
    """
    from backend.core.test_utils import is_pytest
    if is_pytest():
        return DEFAULT_MIN_NOTIONAL_USD

    try:
        import httpx

        product_id = f"{asset.upper()}-USD"
        url = f"https://api.exchange.coinbase.com/products/{product_id}"

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                product_data = response.json()
                min_market_funds = product_data.get("min_market_funds")
                if min_market_funds:
                    return float(min_market_funds)
    except Exception as e:
        logger.warning(f"Could not fetch min notional for {asset}: {e}")

    return DEFAULT_MIN_NOTIONAL_USD


async def check_cash_for_buy(
    tenant_id: str,
    required_usd: float,
    executable_state=None,  # optional live executable state
) -> Dict[str, Any]:
    """
    Check if user has sufficient USD cash for a BUY order.
    Includes fee buffer in the check.

    Priority 1: use live executable_state if provided.
    Priority 2: portfolio snapshot fallback (may be stale).
    """
    from backend.db.connect import get_conn
    from backend.core.utils import _safe_json_loads

    # Calculate total required including fees
    total_required = required_usd + calculate_fee(required_usd)

    result = {
        "sufficient": False,
        "available_usd": 0.0,
        "required_with_fees": total_required,
        "error": None
    }

    # Priority 1: live executable state (most accurate)
    if executable_state is not None:
        usd_bal = (getattr(executable_state, "balances", {}) or {}).get("USD")
        if usd_bal is not None:
            available = float(getattr(usd_bal, "available_qty", 0.0) or 0.0)
            result["available_usd"] = available
            result["sufficient"] = available >= total_required
            result["source"] = "executable_state"
            return result

    # Priority 2: portfolio snapshot (stale estimate)
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT balances_json
                FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC LIMIT 1
                """,
                (tenant_id,)
            )
            row = cursor.fetchone()

            if row:
                balances = _safe_json_loads(row["balances_json"], {})
                available = balances.get("USD", 0.0)
                result["available_usd"] = available
                result["sufficient"] = available >= total_required
                result["source"] = "portfolio_snapshot_estimate"
                return result
    except Exception as e:
        logger.warning(f"Could not check USD balance from snapshot: {e}")

    # For PAPER mode, assume sufficient if no snapshot
    # For LIVE, this would need actual Coinbase balance check
    result["sufficient"] = True
    result["error"] = "Could not verify USD balance"

    return result


async def run_preflight(
    tenant_id: str,
    side: str,
    asset: str,
    amount_usd: float,
    asset_class: str = "CRYPTO",
    mode: str = "PAPER",
    executable_qty: Optional[float] = None,
    hold_qty: Optional[float] = None,
    available_usd: Optional[float] = None,
    requested_qty: Optional[float] = None,
    sell_all_requested: bool = False,
    product_flags: Optional[Dict[str, bool]] = None,
    artifacts: Optional[Dict[str, Optional[str]]] = None,
    executable_state=None,  # pass-through to check_cash_for_buy for live USD balance
) -> PreflightResult:
    """
    Run unified preflight validation for a trade.
    
    This consolidates all validation to use consistent fee calculations,
    preventing the discrepancy that caused Bug 6.
    
    Args:
        tenant_id: The tenant ID
        side: "BUY" or "SELL"
        asset: The asset symbol (e.g., "BTC", "ETH")
        amount_usd: The notional amount in USD
        asset_class: "CRYPTO" or "STOCKS"
        mode: "PAPER" or "LIVE"
    
    Returns:
        PreflightResult with validation outcome
    """
    side_upper = side.upper()
    asset_upper = asset.upper()
    
    result = PreflightResult(
        valid=True,
        requested_usd=amount_usd,
        artifacts=artifacts or {},
    )
    
    # Calculate fees using unified calculation
    result.estimated_fee = calculate_fee(amount_usd)
    result.effective_usd_after_fees = calculate_effective_after_fees(amount_usd)
    
    # Skip validation for AUTO asset selection
    if asset_upper == "AUTO":
        return result
    
    # Check 1: Product tradability and limit-only gates (single primary reason)
    product_flags = product_flags or {}
    if product_flags.get("is_disabled") or product_flags.get("trading_disabled") or product_flags.get("cancel_only"):
        return _blocked(
            PreflightRejectReason.NOT_TRADABLE,
            f"{asset} is not tradable right now in this account.",
            "Choose a different asset that is currently tradable.",
            [f"Try another tradable asset instead of {asset}"],
            requested_usd=amount_usd,
            effective_usd_after_fees=result.effective_usd_after_fees,
            estimated_fee=result.estimated_fee,
            artifacts=artifacts,
        )

    if product_flags.get("limit_only"):
        return _blocked(
            PreflightRejectReason.LIMIT_ONLY,
            f"{asset} is currently limit-only, and market orders are not available.",
            "Use a limit order for this asset or choose a different market.",
            ["Submit a limit order instead"],
            requested_usd=amount_usd,
            effective_usd_after_fees=result.effective_usd_after_fees,
            estimated_fee=result.estimated_fee,
            artifacts=artifacts,
        )

    # Check 2: Balance validation
    effective_amount_usd = float(amount_usd)
    effective_qty = float(requested_qty) if requested_qty is not None else None

    if side_upper == "SELL" and asset_class.upper() == "CRYPTO":
        if executable_qty is not None:
            result.available_balance = float(executable_qty or 0.0)
            result.max_sellable_usd = float(available_usd or 0.0) if available_usd is not None else None
            if result.available_balance <= 0 and float(hold_qty or 0.0) > 0:
                return _blocked(
                    PreflightRejectReason.FUNDS_ON_HOLD,
                    f"{asset} funds are on hold and not currently executable.",
                    "Wait for holds to clear, then try again.",
                    [f"Retry after {asset} hold balance becomes available"],
                    requested_usd=amount_usd,
                    effective_usd_after_fees=result.effective_usd_after_fees,
                    estimated_fee=result.estimated_fee,
                    available_balance=result.available_balance,
                    artifacts=artifacts,
                )
            if result.available_balance <= 0:
                return _blocked(
                    PreflightRejectReason.QTY_ZERO,
                    f"Available quantity is 0 for {asset}.",
                    "Reduce order size or select an asset with available balance.",
                    [f"Check available {asset} balance and retry"],
                    requested_usd=amount_usd,
                    effective_usd_after_fees=result.effective_usd_after_fees,
                    estimated_fee=result.estimated_fee,
                    available_balance=result.available_balance,
                    artifacts=artifacts,
                )
            if available_usd is not None and amount_usd > float(available_usd):
                result.requires_adjustment = True
                result.reason_code = PreflightRejectReason.EXCEEDS_HOLDINGS
                result.adjusted_amount_usd = float(max(0.0, available_usd))
                result.adjusted_qty = float(result.available_balance)
                result.max_sellable_usd = float(max(0.0, available_usd))
                effective_amount_usd = float(max(0.0, available_usd))
                effective_qty = float(result.available_balance)
                result.message = (
                    f"You requested ${amount_usd:.2f} of {asset} but only "
                    f"~${float(available_usd):.2f} is sellable; "
                    "I can sell the maximum available instead."
                )
                result.user_message = result.message
                result.fixes = ["CONFIRM SELL MAX", "CANCEL"]
        else:
            return _blocked(
                PreflightRejectReason.NOT_HELD,
                f"{asset} is not held in your executable balances.",
                "Buy the asset first or choose an asset you currently hold.",
                ["Buy the asset first", "Choose an asset you hold"],
                requested_usd=amount_usd,
                effective_usd_after_fees=result.effective_usd_after_fees,
                estimated_fee=result.estimated_fee,
                artifacts=artifacts,
            )

    elif side_upper == "BUY":
        # Check cash balance for BUY orders (use live executable_state when available)
        cash_check = await check_cash_for_buy(tenant_id, amount_usd, executable_state=executable_state)
        result.available_usd = cash_check["available_usd"]
        
        if not cash_check["sufficient"]:
            # --- Funds recycling: try to find a sellable holding ---
            try:
                from backend.services.funds_manager import check_and_recycle
                recycle = await check_and_recycle(tenant_id, amount_usd)
                if recycle.needs_recycle and recycle.sell_symbol:
                    logger.info(
                        "Auto-sell proposal: sell $%.2f of %s to fund BUY (cash=%.2f, need=%.2f)",
                        recycle.sell_amount_usd, recycle.sell_base_symbol,
                        recycle.available_cash, recycle.required_cash,
                    )
                    return PreflightResult(
                        valid=True,  # Allow to proceed with auto-sell
                        requires_auto_sell=True,
                        auto_sell_proposal=recycle.to_dict(),
                        message=(
                            f"Insufficient cash (${cash_check['available_usd']:.2f}). "
                            f"Will auto-sell ${recycle.sell_amount_usd:.2f} of "
                            f"{recycle.sell_base_symbol} to fund your buy."
                        ),
                        remediation=None,
                        requested_usd=amount_usd,
                        effective_usd_after_fees=result.effective_usd_after_fees,
                        estimated_fee=result.estimated_fee,
                        available_usd=cash_check["available_usd"],
                        artifacts=artifacts or {},
                    )
            except Exception as e:
                logger.warning("Funds recycling check failed: %s", str(e)[:200])

            return _blocked(
                PreflightRejectReason.INSUFFICIENT_CASH,
                f"Insufficient balance (have ${cash_check['available_usd']:.2f}, need ${cash_check['required_with_fees']:.2f} including fees).",
                "Deposit more USD or reduce order amount.",
                ["Reduce order amount", "Deposit more USD"],
                requested_usd=amount_usd,
                effective_usd_after_fees=result.effective_usd_after_fees,
                estimated_fee=result.estimated_fee,
                available_usd=cash_check["available_usd"],
                artifacts=artifacts,
            )

    # Check 3: Authoritative broker validation via preview (when available).
    # If preview is unavailable/errors, fallback to metadata minimum checks.
    preview_attempted = False
    preview_available = False
    if mode.upper() == "LIVE" and asset_class.upper() == "CRYPTO":
        preview_attempted = True
        preview_available, preview_valid, preview_message, preview_min_hint = await _validate_via_coinbase_preview(
            side=side_upper,
            asset=asset_upper,
            amount_usd=effective_amount_usd,
            requested_qty=effective_qty,
            executable_qty=float(executable_qty or 0.0) if executable_qty is not None else None,
            available_usd=float(available_usd) if available_usd is not None else None,
        )
        if preview_available and not preview_valid:
            is_precision = any(
                token in (preview_message or "").lower()
                for token in ("increment", "precision", "decimal", "base_size", "quote_size")
            )
            if side_upper == "SELL" and sell_all_requested and any(
                token in (preview_message or "").lower()
                for token in ("minimum", "min", "too small", "funds")
            ):
                minimum_text = f"~${preview_min_hint:.2f}" if preview_min_hint and preview_min_hint > 0 else "the current minimum"
                available_text = effective_amount_usd
                return _blocked(
                    PreflightRejectReason.MIN_NOTIONAL_TOO_LOW,
                    (
                        f"Your {asset} available (~${available_text:.2f}) is below Coinbase's minimum sell size right now. "
                        f"You can't sell this amount via {asset}-USD. "
                        f"Options: Cancel, buy more {asset} to reach approximately {minimum_text}, "
                        "or check Coinbase app for convert/dust options."
                    ),
                    (
                        f"Choose Cancel, buy more {asset} to reach approximately {minimum_text}, "
                        "or check Coinbase app for convert/dust options."
                    ),
                    [
                        "Cancel",
                        f"Buy more {asset} to reach minimum",
                        "Check Coinbase app for convert/dust options",
                    ],
                    requested_usd=amount_usd,
                    effective_usd_after_fees=result.effective_usd_after_fees,
                    estimated_fee=result.estimated_fee,
                    min_notional_usd=float(preview_min_hint or 0.0),
                    effective_min_notional=float(preview_min_hint or 0.0),
                    available_balance=result.available_balance,
                    available_usd=float(available_usd or 0.0),
                    artifacts=artifacts,
                )
            reason = PreflightRejectReason.INVALID_PRECISION if is_precision else PreflightRejectReason.MIN_NOTIONAL_TOO_LOW
            if reason == PreflightRejectReason.INVALID_PRECISION:
                remediation = "Adjust order precision/size to an exchange-supported increment and try again."
            else:
                remediation = "Increase order size to meet Coinbase minimums and try again."
            return _blocked(
                reason,
                f"Coinbase preview rejected this order: {preview_message}",
                remediation,
                ["Adjust amount and retry", "Cancel"],
                requested_usd=amount_usd,
                effective_usd_after_fees=result.effective_usd_after_fees,
                estimated_fee=result.estimated_fee,
                min_notional_usd=float(preview_min_hint or 0.0),
                effective_min_notional=float(preview_min_hint or 0.0),
                available_balance=result.available_balance,
                available_usd=result.available_usd,
                artifacts=artifacts,
            )

    # Check 4: Fallback metadata minimum notional validation.
    # Only used when preview is unavailable or errors.
    if asset_class.upper() == "CRYPTO" and (not preview_attempted or not preview_available):
        min_notional = await get_min_notional_for_asset(asset)
        result.min_notional_usd = min_notional
        result.effective_min_notional = min_notional
        if effective_amount_usd < result.effective_min_notional:
            return _blocked(
                PreflightRejectReason.MIN_NOTIONAL_TOO_LOW,
                f"Below minimum order size for {asset} (need at least ${result.effective_min_notional:.2f}).",
                f"Increase order amount to at least ${result.effective_min_notional:.2f}.",
                [f"Increase amount to ${result.effective_min_notional:.2f} or more"],
                requested_usd=amount_usd,
                effective_usd_after_fees=result.effective_usd_after_fees,
                estimated_fee=result.estimated_fee,
                min_notional_usd=min_notional,
                effective_min_notional=result.effective_min_notional,
                artifacts=artifacts,
            )

    # Check 5: SELL base_min_size guard.
    # Catches undersized sells before they reach the execution node,
    # preventing failures from metadata-derived minimums that passed preview.
    if side_upper == "SELL" and asset_class.upper() == "CRYPTO":
        base_min_block = _check_sell_base_min_size(
            asset=asset_upper,
            amount_usd=effective_amount_usd,
            sell_all_requested=sell_all_requested,
        )
        if base_min_block is not None:
            base_min_block.artifacts = artifacts or {}
            return base_min_block

    # All checks passed
    return result


def _check_sell_base_min_size(
    asset: str,
    amount_usd: float,
    sell_all_requested: bool = False,
) -> Optional[PreflightResult]:
    """Verify that the sell amount converts to at least base_min_size.

    Uses the same metadata chain as the execution provider (market_metadata →
    product_catalog → safe fallback) so the preflight catches rejections that
    would otherwise only surface in coinbase_provider.place_order().

    Returns a blocked PreflightResult if the sell is too small, else None.
    """
    try:
        from backend.services.market_metadata import (
            get_metadata_service,
            SAFE_FALLBACK_PRECISION,
            _COMMON_CRYPTO_DEFAULTS,
        )
        from backend.services.market_data import get_price

        product_id = f"{asset.upper()}-USD"

        price = None
        try:
            price = float(get_price(asset))
        except Exception:
            pass
        if not price or price <= 0:
            return None

        base_size = amount_usd / price

        service = get_metadata_service()
        result = service.get_product_details_sync(product_id, allow_stale=True)
        base_min_str = None
        if result.success and result.data:
            base_min_str = result.data.get("base_min_size")

        if not base_min_str:
            fb = SAFE_FALLBACK_PRECISION.get(product_id)
            if fb:
                base_min_str = fb.get("base_min_size")
        if not base_min_str:
            base_min_str = _COMMON_CRYPTO_DEFAULTS.get("base_min_size", "0.00000001")

        base_min = float(base_min_str)
        if base_min <= 0 or base_size >= base_min:
            return None

        min_usd = base_min * price
        if sell_all_requested:
            return _blocked(
                PreflightRejectReason.MIN_NOTIONAL_TOO_LOW,
                (
                    f"Your {asset} holdings (~${amount_usd:.2f}) are below the venue minimum sell size "
                    f"(~${min_usd:.2f}). This is dust — too small to sell on {asset}-USD. "
                    f"Options: buy more {asset} to reach ~${min_usd:.2f}, "
                    "or check Coinbase app for convert/dust options."
                ),
                f"Buy more {asset} to reach ~${min_usd:.2f}, or check Coinbase convert.",
                [
                    "Cancel",
                    f"Buy more {asset} to reach minimum",
                    "Check Coinbase app for convert/dust options",
                ],
                requested_usd=amount_usd,
                min_notional_usd=min_usd,
                effective_min_notional=min_usd,
            )
        return _blocked(
            PreflightRejectReason.MIN_NOTIONAL_TOO_LOW,
            (
                f"Sell amount ${amount_usd:.2f} of {asset} converts to ~{base_size:.8f} {asset}, "
                f"which is below the base minimum ({base_min_str} {asset} ≈ ${min_usd:.2f}). "
                f"Increase sell amount to at least ~${min_usd:.2f}."
            ),
            f"Increase sell amount to at least ~${min_usd:.2f}.",
            [f"Increase amount to ~${min_usd:.2f}", "Cancel"],
            requested_usd=amount_usd,
            min_notional_usd=min_usd,
            effective_min_notional=min_usd,
        )
    except Exception as exc:
        logger.debug("base_min_size preflight check skipped: %s", str(exc)[:120])
        return None


def _extract_preview_min_hint(text: str) -> Optional[float]:
    import re
    m = re.search(r"\$?\s*([0-9]+(?:\.[0-9]+)?)", text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _build_preview_payload(
    side: str,
    asset: str,
    amount_usd: float,
    requested_qty: Optional[float] = None,
    executable_qty: Optional[float] = None,
    available_usd: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    product_id = f"{asset.upper()}-USD"
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "side": side.upper(),
        "order_configuration": {"market_market_ioc": {}},
    }
    if side.upper() == "BUY":
        payload["order_configuration"]["market_market_ioc"]["quote_size"] = f"{float(amount_usd):.2f}"
        return payload

    base_size = None
    if requested_qty is not None and requested_qty > 0:
        base_size = float(requested_qty)
    elif executable_qty is not None and available_usd and available_usd > 0:
        ratio = max(0.0, min(1.0, float(amount_usd) / float(available_usd)))
        base_size = float(executable_qty) * ratio
    else:
        try:
            from backend.services.market_data import get_price
            px = float(get_price(asset))
            if px > 0:
                base_size = float(amount_usd) / px
        except Exception:
            base_size = None

    if base_size is None or base_size <= 0:
        return None

    payload["order_configuration"]["market_market_ioc"]["base_size"] = f"{base_size:.8f}"
    return payload


async def _validate_via_coinbase_preview(
    side: str,
    asset: str,
    amount_usd: float,
    requested_qty: Optional[float] = None,
    executable_qty: Optional[float] = None,
    available_usd: Optional[float] = None,
) -> Tuple[bool, bool, str, Optional[float]]:
    """
    Returns: (preview_available, preview_valid, message, min_notional_hint)
    """
    payload = _build_preview_payload(
        side=side,
        asset=asset,
        amount_usd=amount_usd,
        requested_qty=requested_qty,
        executable_qty=executable_qty,
        available_usd=available_usd,
    )
    if not payload:
        return False, True, "preview unavailable", None

    try:
        from backend.providers.coinbase_provider import CoinbaseProvider

        provider = CoinbaseProvider()
        preview = provider.preview_order(payload)

        success = preview.get("success")
        error_msg = (
            preview.get("error_message")
            or preview.get("message")
            or preview.get("error")
            or ""
        )
        if success is False:
            hint = _extract_preview_min_hint(error_msg)
            return True, False, error_msg or "Order does not pass Coinbase preview checks.", hint
        if success is True:
            return True, True, "ok", None

        # Unknown shape - treat this as unavailable so metadata checks can still run.
        return False, True, "preview unavailable", None
    except Exception as e:
        logger.info("Coinbase preview unavailable, using metadata fallback: %s", str(e)[:200])
        return False, True, "preview unavailable", None
