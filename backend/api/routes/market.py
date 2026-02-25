"""Market data API routes (candles + price)."""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from backend.api.deps import require_viewer
from backend.core.logging import get_logger
from backend.db.connect import get_conn
from backend.services.market_data import get_price, MarketDataError

logger = get_logger(__name__)

router = APIRouter()

RANGE_CONFIG = {
    "1H":  {"interval": "ONE_MINUTE",    "delta": timedelta(hours=1)},
    "24H": {"interval": "FIVE_MINUTE",   "delta": timedelta(hours=24)},
    "7D":  {"interval": "ONE_HOUR",      "delta": timedelta(days=7)},
    "30D": {"interval": "ONE_DAY",       "delta": timedelta(days=30)},
}


@router.get("/price")
async def get_market_price(symbol: str = Query(...)):
    """Get market price."""
    try:
        price = get_price(symbol)
        return {"symbol": symbol, "price": price}
    except MarketDataError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/candles")
async def get_candles(
    symbol: str = Query(..., description="Product ID, e.g. BTC-USD"),
    time_range: str = Query("24H", alias="range", description="1H, 24H, 7D, or 30D"),
    run_id: Optional[str] = Query(None),
):
    """Return candles for a symbol within a time range, plus trade markers if run_id supplied."""
    cfg = RANGE_CONFIG.get(time_range.upper())
    if not cfg:
        raise HTTPException(status_code=400, detail=f"Invalid range '{time_range}'. Use 1H, 24H, 7D, or 30D.")

    now = datetime.now(timezone.utc)
    range_start = now - cfg["delta"]
    range_start_iso = range_start.isoformat()
    range_end_iso = now.isoformat()
    interval = cfg["interval"]

    candles = []
    source = "market_candles_table"

    with get_conn() as conn:
        cursor = conn.cursor()

        # Normalize symbol for DB lookup (may be stored as BTC-USD or BTC)
        sym_variants = [symbol]
        base = symbol.split("-")[0] if "-" in symbol else symbol
        if "-" not in symbol:
            sym_variants.append(f"{symbol}-USD")
        sym_variants.append(base)

        placeholders = ",".join(["?"] * len(sym_variants))
        cursor.execute(
            f"""SELECT id, symbol, interval, start_time, end_time, open, high, low, close, volume
                FROM market_candles
                WHERE symbol IN ({placeholders})
                  AND start_time >= ?
                ORDER BY start_time ASC
                LIMIT 500""",
            (*sym_variants, range_start_iso),
        )
        rows = cursor.fetchall()
        for r in rows:
            candles.append({
                "ts": r["start_time"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"] or 0),
            })

    if len(candles) < 5:
        try:
            from backend.providers.coinbase_market_data import CoinbaseMarketDataProvider
            provider = CoinbaseMarketDataProvider()
            live_candles = provider.get_candles(
                symbol=symbol,
                interval=interval.lower() if interval.lower() in ("1h", "24h", "7d") else interval,
                start_time=range_start_iso,
                end_time=range_end_iso,
            )
            candles = [
                {
                    "ts": c.get("start_time") or c.get("time") or c.get("t", ""),
                    "open": float(c.get("open", c.get("o", 0))),
                    "high": float(c.get("high", c.get("h", 0))),
                    "low": float(c.get("low", c.get("l", 0))),
                    "close": float(c.get("close", c.get("c", 0))),
                    "volume": float(c.get("volume", c.get("v", 0))),
                }
                for c in live_candles
            ]
            source = "coinbase_public"
        except Exception as e:
            logger.warning("Coinbase candle fallback failed for %s: %s", symbol, str(e)[:200])

    trade_markers = []
    if run_id:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT side, notional_usd, symbol, created_at FROM orders WHERE run_id = ?",
                (run_id,),
            )
            for row in cursor.fetchall():
                trade_markers.append({
                    "ts": row["created_at"],
                    "side": row["side"],
                    "notional_usd": float(row["notional_usd"] or 0),
                    "symbol": row["symbol"],
                })

    last_updated = candles[-1]["ts"] if candles else None
    return {
        "candles": candles,
        "trade_markers": trade_markers,
        "meta": {
            "points": len(candles),
            "range_start": range_start_iso,
            "range_end": range_end_iso,
            "source": source,
            "last_updated_at": last_updated,
        },
    }
