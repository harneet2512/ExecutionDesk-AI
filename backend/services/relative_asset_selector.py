"""Relative asset selection grounded in executable holdings + market data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.core.logging import get_logger
from backend.services.market_data import get_price

logger = get_logger(__name__)


@dataclass
class RelativeSelectionResult:
    symbol: str
    product_id: str
    metric_name: str
    metric_value: float
    timeframe_label: str
    universe_size: int
    rationale: str
    evidence: Dict[str, Any]


def _holding_universe(executable_state: Any) -> List[str]:
    out: List[str] = []
    balances = getattr(executable_state, "balances", {}) or {}
    for sym, bal in balances.items():
        s = str(sym or "").upper().strip()
        if not s or s in {"USD", "USDC", "USDT"}:
            continue
        qty = float(getattr(bal, "available_qty", 0.0) or 0.0)
        if qty > 0:
            out.append(s)
    return sorted(set(out))


def _product_for_symbol(symbol: str, product_catalog: Dict[str, Dict[str, Any]]) -> Optional[str]:
    for pid in (f"{symbol}-USD", f"{symbol}-USDC"):
        prod = (product_catalog or {}).get(pid) or {}
        if not prod:
            continue
        if prod.get("is_disabled") or prod.get("trading_disabled") or prod.get("cancel_only"):
            continue
        return pid
    # permissive fallback when catalog is sparse; resolver/preflight still enforce tradability
    return f"{symbol}-USD"


def _timeframe_label(lookback_hours: float) -> str:
    if lookback_hours <= 1.0:
        return "last 1 hour"
    if lookback_hours <= 24.0:
        return f"last {int(round(lookback_hours))} hours"
    return f"last {int(round(lookback_hours / 24.0))} days"


async def _return_pct(symbol: str, lookback_hours: float) -> Optional[float]:
    product_id = f"{symbol}-USD"
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    granularity = 3600 if lookback_hours >= 1 else 300
    url = f"https://api.exchange.coinbase.com/products/{product_id}/candles"
    params = {
        "granularity": granularity,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, list) or len(data) < 2:
            return None
        rows = sorted(data, key=lambda row: row[0])
        first_open = float(rows[0][3])
        last_close = float(rows[-1][4])
        if first_open <= 0:
            return None
        return ((last_close - first_open) / first_open) * 100.0
    except Exception:
        return None


async def select_relative_asset(
    *,
    command_text: str,
    lookback_hours: float,
    executable_state: Any,
    product_catalog: Dict[str, Dict[str, Any]],
) -> Optional[RelativeSelectionResult]:
    text = (command_text or "").lower()
    symbols = _holding_universe(executable_state)
    if not symbols:
        return None

    # largest holding by executable USD value
    if any(k in text for k in ("largest holding", "largest position", "biggest position", "top holding")):
        scored: List[Tuple[str, float]] = []
        for sym in symbols:
            bal = (getattr(executable_state, "balances", {}) or {}).get(sym)
            qty = float(getattr(bal, "available_qty", 0.0) or 0.0)
            if qty <= 0:
                continue
            try:
                px = float(get_price(sym))
            except Exception:
                continue
            scored.append((sym, qty * px))
        if not scored:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        selected, usd_value = scored[0]
        product_id = _product_for_symbol(selected, product_catalog)
        if not product_id:
            return None
        return RelativeSelectionResult(
            symbol=selected,
            product_id=product_id,
            metric_name="usd_value",
            metric_value=usd_value,
            timeframe_label="current executable balances",
            universe_size=len(symbols),
            rationale=f"Used executable balances and latest quotes across {len(symbols)} holdings; selected {selected} as the largest USD exposure (${usd_value:,.2f}).",
            evidence={"selector": "largest_holding", "universe": symbols},
        )

    # movers/losers across holdings
    wants_loser = any(k in text for k in ("biggest loser", "down the most", "worst performer"))
    wants_mover = any(k in text for k in ("biggest mover", "top mover", "momentum"))
    if not wants_loser and not wants_mover:
        return None

    changes: List[Tuple[str, float]] = []
    for sym in symbols:
        pct = await _return_pct(sym, lookback_hours)
        if pct is None:
            continue
        changes.append((sym, pct))
    if not changes:
        # If candle history is temporarily unavailable, degrade to holdings state
        # so relative commands still resolve to a concrete tradable symbol.
        scored: List[Tuple[str, float]] = []
        for sym in symbols:
            bal = (getattr(executable_state, "balances", {}) or {}).get(sym)
            qty = float(getattr(bal, "available_qty", 0.0) or 0.0)
            if qty <= 0:
                continue
            try:
                px = float(get_price(sym))
            except Exception:
                continue
            scored.append((sym, qty * px))
        if not scored:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        selected, usd_value = scored[0]
        product_id = _product_for_symbol(selected, product_catalog)
        if not product_id:
            return None
        tf = _timeframe_label(lookback_hours or 24.0)
        return RelativeSelectionResult(
            symbol=selected,
            product_id=product_id,
            metric_name="usd_value_fallback",
            metric_value=usd_value,
            timeframe_label=tf,
            universe_size=len(symbols),
            rationale=(
                f"Used executable balances across {len(symbols)} holdings; "
                f"candle history for {tf} was incomplete, so selected {selected} "
                f"by current USD exposure (${usd_value:,.2f})."
            ),
            evidence={"selector": "usd_value_fallback", "universe": symbols, "timeframe": tf},
        )

    if wants_loser:
        selected, metric = min(changes, key=lambda x: x[1])
        metric_name = "worst_return_pct"
    elif "absolute" in text or "biggest mover" in text:
        selected, metric = max(changes, key=lambda x: abs(x[1]))
        metric_name = "abs_return_pct"
    else:
        selected, metric = max(changes, key=lambda x: x[1])
        metric_name = "best_return_pct"

    product_id = _product_for_symbol(selected, product_catalog)
    if not product_id:
        return None
    tf = _timeframe_label(lookback_hours or 24.0)
    return RelativeSelectionResult(
        symbol=selected,
        product_id=product_id,
        metric_name=metric_name,
        metric_value=metric,
        timeframe_label=tf,
        universe_size=len(symbols),
        rationale=f"Used executable balances and evaluated {tf} moves across {len(symbols)} holdings; selected {selected} at {metric:+.2f}%.",
        evidence={"selector": metric_name, "universe": symbols, "timeframe": tf},
    )
