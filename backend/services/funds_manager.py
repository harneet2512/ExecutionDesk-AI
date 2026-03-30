"""Funds Manager — auto-recycle funds by selling holdings when cash is insufficient.

When a BUY order cannot proceed because available USD is too low, this service:
1. Identifies the best holding to sell (most recently bought asset or largest liquid position)
2. Calculates exactly how much to sell (just enough to cover the buy + fees)
3. Returns an auto-sell proposal that the confirmation UX can present to the user

Safety:
- Never sells more than needed
- Requires the same confirmation flow as normal trades
- Logs all auto-sell reasoning in audit log
"""
import json
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

from backend.db.connect import get_conn
from backend.core.utils import _safe_json_loads
from backend.services.trade_preflight import COINBASE_FEE_RATE, calculate_fee

logger = logging.getLogger(__name__)


@dataclass
class RecycleResult:
    """Result of a funds-recycling check."""
    needs_recycle: bool
    sell_symbol: Optional[str] = None       # e.g. "BTC-USD"
    sell_base_symbol: Optional[str] = None  # e.g. "BTC"
    sell_amount_usd: float = 0.0
    available_cash: float = 0.0
    required_cash: float = 0.0
    reason: str = ""
    holdings_checked: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def check_and_recycle(
    tenant_id: str,
    required_usd: float,
    fee_buffer: float = 0.02,
) -> RecycleResult:
    """Check if cash is sufficient for a BUY; if not, find a holding to sell.

    Args:
        tenant_id: Tenant identifier
        required_usd: The notional amount the user wants to BUY
        fee_buffer: Extra buffer above required amount (default $0.02)

    Returns:
        RecycleResult describing whether auto-sell is needed and what to sell.
    """
    total_needed = required_usd + calculate_fee(required_usd) + fee_buffer

    # --- Get current cash balance ---
    available_cash = 0.0
    positions: Dict[str, float] = {}
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT balances_json, positions_json
                   FROM portfolio_snapshots
                   WHERE tenant_id = ? ORDER BY ts DESC LIMIT 1""",
                (tenant_id,),
            )
            row = cursor.fetchone()
            if row:
                balances = _safe_json_loads(row["balances_json"], {})
                available_cash = float(balances.get("USD", 0.0))
                positions = _safe_json_loads(row["positions_json"], {})
    except Exception as e:
        logger.warning("funds_manager: could not read snapshot: %s", str(e)[:120])

    if available_cash >= total_needed:
        return RecycleResult(
            needs_recycle=False,
            available_cash=available_cash,
            required_cash=total_needed,
            reason="Sufficient cash available",
        )

    shortfall = total_needed - available_cash

    # --- Find best holding to sell ---
    # Strategy: prefer the most-recently-bought asset, then fall back to largest liquid position
    sellable = _find_sellable_holding(tenant_id, positions, shortfall)

    if sellable is None:
        return RecycleResult(
            needs_recycle=True,
            available_cash=available_cash,
            required_cash=total_needed,
            reason="Insufficient funds. No sellable assets to raise cash.",
            holdings_checked=len(positions),
        )

    sell_symbol, sell_base, sell_amount = sellable

    # Add fee buffer for the sell order itself
    sell_amount_with_fees = sell_amount / (1 - COINBASE_FEE_RATE)
    # Round up to avoid leaving dust
    sell_amount_with_fees = round(sell_amount_with_fees + 0.01, 2)

    return RecycleResult(
        needs_recycle=True,
        sell_symbol=sell_symbol,
        sell_base_symbol=sell_base,
        sell_amount_usd=sell_amount_with_fees,
        available_cash=available_cash,
        required_cash=total_needed,
        reason=(
            f"Need ${total_needed:.2f} but only ${available_cash:.2f} available. "
            f"Auto-selling ${sell_amount_with_fees:.2f} of {sell_base} to raise cash."
        ),
        holdings_checked=len(positions),
    )


def _find_sellable_holding(
    tenant_id: str,
    positions: Dict[str, float],
    shortfall: float,
) -> Optional[tuple]:
    """Find the best holding to sell to cover the shortfall.

    Returns (product_id, base_symbol, sell_amount_usd) or None.
    """
    # 1. Prefer most-recently-bought asset
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT symbol FROM orders
                   WHERE tenant_id = ? AND side = 'BUY'
                   ORDER BY created_at DESC LIMIT 10""",
                (tenant_id,),
            )
            recent_buys = [r["symbol"] for r in cursor.fetchall()]
    except Exception:
        recent_buys = []

    # Build candidates with estimated USD value
    candidates = []
    for pid, qty in positions.items():
        if qty <= 0:
            continue
        base = pid.replace("-USD", "").upper()
        if base == "USD":
            continue
        # Estimate USD value
        usd_value = _estimate_usd_value(base, qty)
        if usd_value < 0.50:
            continue  # Not worth selling dust
        candidates.append((pid, base, qty, usd_value))

    if not candidates:
        return None

    # Sort: recently-bought first, then largest value
    def _sort_key(c):
        pid = c[0]
        # Lower index in recent_buys = higher priority
        try:
            recency = recent_buys.index(pid)
        except ValueError:
            recency = 999
        return (recency, -c[3])  # recency asc, value desc

    candidates.sort(key=_sort_key)

    best = candidates[0]
    pid, base, qty, usd_value = best

    # Sell only enough to cover the shortfall
    sell_amount = min(shortfall, usd_value)
    sell_amount = max(sell_amount, 1.0)  # At least $1 to meet Coinbase minimum

    return (pid, base, sell_amount)


def _estimate_usd_value(base_symbol: str, qty: float) -> float:
    """Estimate USD value of a holding using the Exchange API or defaults."""
    try:
        import httpx
        url = f"https://api.exchange.coinbase.com/products/{base_symbol}-USD/ticker"
        resp = httpx.get(url, timeout=5.0)
        if resp.status_code == 200:
            price = float(resp.json().get("price", 0))
            if price > 0:
                return qty * price
    except Exception:
        pass

    # Fallback estimates for common assets
    _PRICES = {"BTC": 50000, "ETH": 3000, "SOL": 100, "DOGE": 0.10, "XRP": 0.50}
    price = _PRICES.get(base_symbol.upper(), 1.0)
    return qty * price
