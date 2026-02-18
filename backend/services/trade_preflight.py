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
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Standard Coinbase market order fee rate
COINBASE_FEE_RATE = 0.006  # 0.6%

# Default minimum notional for crypto orders
DEFAULT_MIN_NOTIONAL_USD = 1.0


class PreflightRejectReason(str, Enum):
    """Structured rejection reason codes."""
    MIN_NOTIONAL_TOO_LOW = "MIN_NOTIONAL_TOO_LOW"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INVALID_PRECISION = "INVALID_PRECISION"
    ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass
class PreflightResult:
    """Result of preflight validation."""
    valid: bool
    reason_code: Optional[PreflightRejectReason] = None
    message: Optional[str] = None
    remediation: Optional[str] = None
    
    # Calculated values for UI display
    requested_usd: float = 0.0
    effective_usd_after_fees: float = 0.0
    estimated_fee: float = 0.0
    min_notional_usd: float = 0.0
    effective_min_notional: float = 0.0
    available_balance: float = 0.0
    available_usd: float = 0.0

    # Auto-sell / funds recycling
    requires_auto_sell: bool = False
    auto_sell_proposal: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "valid": self.valid,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "message": self.message,
            "remediation": self.remediation,
            "requested_usd": self.requested_usd,
            "effective_usd_after_fees": self.effective_usd_after_fees,
            "estimated_fee": self.estimated_fee,
            "min_notional_usd": self.min_notional_usd,
            "effective_min_notional": self.effective_min_notional,
            "available_balance": self.available_balance,
            "available_usd": self.available_usd,
            "requires_auto_sell": self.requires_auto_sell,
        }
        if self.auto_sell_proposal:
            d["auto_sell_proposal"] = self.auto_sell_proposal
        return d


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


async def check_balance_for_sell(
    tenant_id: str,
    asset: str,
    required_usd: float
) -> Dict[str, Any]:
    """
    Check if user has sufficient balance for a SELL order.
    Returns available balance in both asset units and USD equivalent.
    """
    from backend.db.connect import get_conn
    from backend.core.utils import _safe_json_loads
    from backend.core.config import settings
    
    result = {
        "sufficient": False,
        "available": 0.0,
        "available_usd": 0.0,
        "error": None
    }
    
    # Handle AUTO selection - cannot validate
    if asset.upper() == "AUTO":
        result["sufficient"] = True
        result["error"] = "Cannot validate balance for AUTO selection"
        return result
    
    asset_upper = asset.upper()
    
    # Check PAPER mode first (use portfolio snapshots)
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT positions_json, balances_json
                FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC LIMIT 1
                """,
                (tenant_id,)
            )
            row = cursor.fetchone()
            
            if row:
                positions = _safe_json_loads(row["positions_json"], {})
                balances = _safe_json_loads(row["balances_json"], {})
                available = positions.get(asset_upper, balances.get(asset_upper, 0.0))
                
                if available > 0:
                    # Get real market price from Exchange API ticker
                    usd_per_unit = None
                    try:
                        import httpx
                        ticker_url = f"https://api.exchange.coinbase.com/products/{asset_upper}-USD/ticker"
                        _resp = httpx.get(ticker_url, timeout=5.0)
                        if _resp.status_code == 200:
                            _data = _resp.json()
                            _price = float(_data.get("price", 0))
                            if _price > 0:
                                usd_per_unit = _price
                    except Exception as _e:
                        logger.debug("Ticker fetch failed for %s: %s", asset_upper, str(_e)[:100])
                    if not usd_per_unit or usd_per_unit <= 0:
                        # Fallback to conservative estimates
                        usd_per_unit = 50000 if asset_upper == "BTC" else 3000 if asset_upper == "ETH" else 100
                    result["available"] = available
                    result["available_usd"] = available * usd_per_unit
                    result["sufficient"] = result["available_usd"] >= required_usd
                    return result
    except Exception as e:
        logger.warning(f"Could not check portfolio snapshot: {e}")
    
    # Check LIVE credentials if available
    if settings.coinbase_api_key_name and settings.coinbase_api_private_key:
        try:
            from backend.providers.coinbase_provider import CoinbaseProvider
            from backend.services.coinbase_market_data import get_candles
            
            provider = CoinbaseProvider()
            balances_result = provider.get_balances(tenant_id)
            balances = balances_result.get("balances", {})
            available = float(balances.get(asset_upper, 0.0))
            
            result["available"] = available
            
            if available > 0:
                # Get current price for USD conversion
                try:
                    candles = get_candles(f"{asset_upper}-USD", granularity="ONE_HOUR", limit=1)
                    if candles and len(candles) > 0:
                        current_price = candles[0].get("close", 0)
                        result["available_usd"] = available * current_price
                        result["sufficient"] = result["available_usd"] >= required_usd
                except Exception:
                    # Fallback to mock price
                    usd_per_unit = 50000 if asset_upper == "BTC" else 3000 if asset_upper == "ETH" else 100
                    result["available_usd"] = available * usd_per_unit
                    result["sufficient"] = result["available_usd"] >= required_usd
            
            return result
        except Exception as e:
            logger.warning(f"Could not check Coinbase balance: {e}")
            result["error"] = str(e)
    
    return result


async def check_cash_for_buy(
    tenant_id: str,
    required_usd: float
) -> Dict[str, Any]:
    """
    Check if user has sufficient USD cash for a BUY order.
    Includes fee buffer in the check.
    """
    from backend.db.connect import get_conn
    from backend.core.utils import _safe_json_loads
    from backend.core.config import settings
    
    # Calculate total required including fees
    total_required = required_usd + calculate_fee(required_usd)
    
    result = {
        "sufficient": False,
        "available_usd": 0.0,
        "required_with_fees": total_required,
        "error": None
    }
    
    # Check portfolio snapshot
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
    mode: str = "PAPER"
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
        requested_usd=amount_usd
    )
    
    # Calculate fees using unified calculation
    result.estimated_fee = calculate_fee(amount_usd)
    result.effective_usd_after_fees = calculate_effective_after_fees(amount_usd)
    
    # Skip validation for AUTO asset selection
    if asset_upper == "AUTO":
        return result
    
    # Check 1: Minimum notional validation
    if asset_class.upper() == "CRYPTO":
        min_notional = await get_min_notional_for_asset(asset)
        result.min_notional_usd = min_notional
        result.effective_min_notional = calculate_required_for_min_notional(min_notional)
        
        if amount_usd < result.effective_min_notional:
            return PreflightResult(
                valid=False,
                reason_code=PreflightRejectReason.MIN_NOTIONAL_TOO_LOW,
                message=f"Order amount ${amount_usd:.2f} is below minimum. After the 0.6% fee, orders must be at least ${result.effective_min_notional:.2f} to meet the ${min_notional:.2f} minimum for {asset}.",
                remediation=f"Increase order amount to at least ${result.effective_min_notional:.2f}.",
                requested_usd=amount_usd,
                effective_usd_after_fees=result.effective_usd_after_fees,
                estimated_fee=result.estimated_fee,
                min_notional_usd=min_notional,
                effective_min_notional=result.effective_min_notional,
            )
    
    # Check 2: Balance validation
    if side_upper == "SELL" and asset_class.upper() == "CRYPTO":
        balance_check = await check_balance_for_sell(tenant_id, asset, amount_usd)
        result.available_balance = balance_check["available"]
        result.available_usd = balance_check["available_usd"]
        
        if not balance_check["sufficient"]:
            available_msg = f"{balance_check['available']:.8f} {asset}" if balance_check['available'] > 0 else f"0 {asset}"
            available_usd_msg = f"${balance_check['available_usd']:.2f}" if balance_check['available_usd'] > 0 else "$0.00"
            
            return PreflightResult(
                valid=False,
                reason_code=PreflightRejectReason.INSUFFICIENT_BALANCE,
                message=f"Insufficient {asset} balance to sell ${amount_usd:.2f}. Available: {available_msg} ({available_usd_msg}).",
                remediation=f"Reduce sell amount or acquire more {asset} first.",
                requested_usd=amount_usd,
                effective_usd_after_fees=result.effective_usd_after_fees,
                estimated_fee=result.estimated_fee,
                available_balance=balance_check["available"],
                available_usd=balance_check["available_usd"],
            )
    
    elif side_upper == "BUY":
        # Check cash balance for BUY orders
        cash_check = await check_cash_for_buy(tenant_id, amount_usd)
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
                    )
            except Exception as e:
                logger.warning("Funds recycling check failed: %s", str(e)[:200])

            return PreflightResult(
                valid=False,
                reason_code=PreflightRejectReason.INSUFFICIENT_CASH,
                message=f"Insufficient USD balance. Need ${cash_check['required_with_fees']:.2f} (including fees), have ${cash_check['available_usd']:.2f}.",
                remediation="Deposit more USD or reduce order amount.",
                requested_usd=amount_usd,
                effective_usd_after_fees=result.effective_usd_after_fees,
                estimated_fee=result.estimated_fee,
                available_usd=cash_check["available_usd"],
            )
    
    # All checks passed
    return result
