"""Prediction market discovery API routes."""
import time
from typing import Optional, Any, Dict, List

from fastapi import APIRouter, Query, Path, HTTPException

from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

_popular_cache: Dict[str, Any] = {"data": None, "ts": 0}
_detail_cache: Dict[str, Any] = {}
_CACHE_TTL = 60
_DETAIL_CACHE_TTL = 30


def _get_provider():
    from backend.providers.polymarket_market_data import PolymarketMarketDataProvider
    return PolymarketMarketDataProvider()


@router.get("/search")
async def search_markets(
    q: str = Query("", description="Search query for prediction markets"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of results"),
):
    """Search Polymarket prediction markets by keyword."""
    try:
        provider = _get_provider()
        markets = provider.search_markets(q, limit=limit)
        return {"markets": markets, "query": q, "count": len(markets)}
    except Exception as e:
        logger.error("Prediction market search failed for q='%s': %s", q, str(e)[:200])
        raise HTTPException(status_code=502, detail=f"Failed to fetch prediction markets: {str(e)[:200]}")


@router.get("/popular")
async def popular_markets(
    limit: int = Query(20, ge=1, le=50, description="Maximum number of results"),
):
    """Get popular/high-volume active prediction markets (cached 60s)."""
    now = time.monotonic()
    cache_key = f"popular_{limit}"
    if _popular_cache.get("key") == cache_key and _popular_cache["data"] is not None and now - _popular_cache["ts"] < _CACHE_TTL:
        return _popular_cache["data"]

    try:
        provider = _get_provider()
        markets = provider.search_markets("", limit=limit)
        result = {"markets": markets, "count": len(markets)}
        _popular_cache["data"] = result
        _popular_cache["ts"] = now
        _popular_cache["key"] = cache_key
        return result
    except Exception as e:
        if _popular_cache["data"] is not None:
            logger.warning("Popular markets fetch failed, returning stale cache: %s", str(e)[:200])
            return _popular_cache["data"]
        logger.error("Popular prediction markets fetch failed: %s", str(e)[:200])
        raise HTTPException(status_code=502, detail=f"Failed to fetch popular markets: {str(e)[:200]}")


@router.get("/{condition_id}")
async def market_detail(
    condition_id: str = Path(..., description="Market condition ID"),
):
    """Get detailed information about a specific prediction market."""
    now = time.monotonic()
    cached = _detail_cache.get(condition_id)
    if cached and now - cached["ts"] < _DETAIL_CACHE_TTL:
        return cached["data"]

    try:
        provider = _get_provider()
        detail = provider.get_market_detail(condition_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Market not found")
        _detail_cache[condition_id] = {"data": detail, "ts": now}
        return detail
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Market detail failed for %s: %s", condition_id, str(e)[:200])
        raise HTTPException(status_code=502, detail=f"Failed to fetch market detail: {str(e)[:200]}")


@router.get("/{condition_id}/order-book")
async def market_order_book(
    condition_id: str = Path(..., description="Market condition ID"),
    outcome: str = Query("YES", description="Outcome to get order book for (YES or NO)"),
):
    """Get order book depth for a market outcome."""
    try:
        provider = _get_provider()
        detail = provider.get_market_detail(condition_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Market not found")

        tokens = detail.get("tokens", [])
        target_token = None
        for t in tokens:
            if t.get("outcome", "").upper() == outcome.upper():
                target_token = t
                break
        if not target_token and tokens:
            target_token = tokens[0]

        if not target_token or not target_token.get("token_id"):
            raise HTTPException(status_code=404, detail="Token not found for outcome")

        book = provider.get_order_book(target_token["token_id"])
        if book is None:
            return {"bids": [], "asks": [], "spread": 0, "depth": {"bid_depth": 0, "ask_depth": 0, "total_depth": 0}}
        return book
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Order book failed for %s: %s", condition_id, str(e)[:200])
        raise HTTPException(status_code=502, detail=f"Failed to fetch order book: {str(e)[:200]}")


@router.get("/{condition_id}/price-history")
async def market_price_history(
    condition_id: str = Path(..., description="Market condition ID"),
    interval: str = Query("1w", description="Time range: 1h, 6h, 1d, 1w, 1m, all"),
    fidelity: int = Query(60, description="Granularity in minutes: 1, 5, 15, 60, 360, 1440"),
):
    """Get price history timeseries for charting probability over time."""
    try:
        provider = _get_provider()
        detail = provider.get_market_detail(condition_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Market not found")

        tokens = detail.get("tokens", [])
        if not tokens:
            return {"history": [], "outcomes": []}

        outcomes = []
        for token in tokens:
            token_id = token.get("token_id")
            outcome_name = token.get("outcome", "Unknown")
            if not token_id:
                continue
            points = provider.get_price_history(token_id, fidelity=fidelity, interval=interval)
            outcomes.append({
                "outcome": outcome_name,
                "current_price": token.get("price", 0),
                "points": [{"t": p["t"], "p": round(p["p"], 4)} for p in points],
            })

        return {"history": outcomes, "condition_id": condition_id, "interval": interval}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Price history failed for %s: %s", condition_id, str(e)[:200])
        raise HTTPException(status_code=502, detail=f"Failed to fetch price history: {str(e)[:200]}")


@router.get("/{condition_id}/trades")
async def market_trades(
    condition_id: str = Path(..., description="Market condition ID"),
    limit: int = Query(50, ge=1, le=200),
):
    """Get recent trades for a market."""
    try:
        provider = _get_provider()
        trades = provider.get_market_trades(condition_id, limit=limit)
        return {"trades": trades, "count": len(trades)}
    except Exception as e:
        logger.error("Market trades failed for %s: %s", condition_id, str(e)[:200])
        raise HTTPException(status_code=502, detail=f"Failed to fetch trades: {str(e)[:200]}")
