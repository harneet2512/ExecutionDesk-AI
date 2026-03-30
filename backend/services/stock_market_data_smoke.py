"""Polygon stock market data smoke check.

This module provides a minimal smoke test to verify Polygon API connectivity
and caching behavior. NOT required at runtime.
"""
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


def smoke_polygon_one_ticker(
    ticker: str = "AAPL",
    lookback_days: int = 10
) -> Dict[str, Any]:
    """
    Smoke test Polygon API with a single ticker.
    
    Makes ONE real API call (unless cached), verifies response structure,
    and returns detailed stats.
    
    Args:
        ticker: Stock symbol to test (default: AAPL)
        lookback_days: Number of trading days to look back (default: 10)
        
    Returns:
        Dict with:
        - success: bool
        - ticker: str
        - candles_count: int
        - date_range: str
        - cache_hit: bool
        - api_call_made: bool
        - response_time_ms: float
        - error: Optional[str]
        - provider_stats: dict
    """
    from backend.core.config import get_settings
    from backend.core.logging import get_logger
    import time
    
    logger = get_logger(__name__)
    settings = get_settings()
    
    result = {
        "success": False,
        "ticker": ticker,
        "candles_count": 0,
        "date_range": "",
        "cache_hit": False,
        "api_call_made": False,
        "response_time_ms": 0,
        "error": None,
        "provider_stats": {}
    }
    
    # Check API key
    if not settings.polygon_api_key:
        result["error"] = "POLYGON_API_KEY not configured"
        logger.error("[REDACTED] Polygon API key missing")
        return result
    
    try:
        from backend.providers.polygon_market_data import PolygonMarketDataProvider
        
        provider = PolygonMarketDataProvider()
        
        # Get stats before call
        stats_before = provider.get_stats()
        
        # Convert lookback_days to interval string
        if lookback_days <= 1:
            interval = "24h"
        elif lookback_days <= 2:
            interval = "48h"
        elif lookback_days <= 7:
            interval = "1w"
        else:
            interval = "30d"
        
        start_time = time.time()
        
        # Make the API call using interval (not start/end dates)
        candles = provider.get_candles(
            symbol=ticker,
            interval=interval
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Get stats after call
        stats_after = provider.get_stats()
        
        result["response_time_ms"] = round(elapsed_ms, 2)
        result["candles_count"] = len(candles) if candles else 0
        result["provider_stats"] = stats_after
        
        # Check if it was a cache hit
        if stats_after.get("cache_hits", 0) > stats_before.get("cache_hits", 0):
            result["cache_hit"] = True
            result["api_call_made"] = False
        else:
            result["cache_hit"] = False
            result["api_call_made"] = True
        
        if candles and len(candles) > 0:
            result["success"] = True
            first_date = candles[0].get("start_time", "N/A")
            last_date = candles[-1].get("start_time", "N/A")
            result["date_range"] = f"{first_date} to {last_date}"
            logger.info(
                "Polygon smoke test PASSED: %s returned %d candles",
                ticker, len(candles)
            )
        else:
            result["error"] = "No candles returned"
            logger.warning(f"Polygon smoke test: No candles for {ticker}")
            
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Polygon smoke test FAILED: {e}")
    
    return result


def smoke_polygon_all_watchlist() -> Dict[str, Any]:
    """
    Smoke test Polygon API for all watchlist symbols.
    
    Uses rate limiting to respect free tier (5 calls/min).
    
    Returns:
        Dict with:
        - success: bool
        - symbols_tested: int
        - symbols_passed: int
        - symbols_failed: list
        - total_candles: int
        - total_time_ms: float
        - provider_stats: dict
    """
    from backend.core.config import get_settings
    import time
    
    settings = get_settings()
    watchlist = settings.stock_watchlist_list
    
    result = {
        "success": False,
        "symbols_tested": 0,
        "symbols_passed": 0,
        "symbols_failed": [],
        "total_candles": 0,
        "total_time_ms": 0,
        "provider_stats": {}
    }
    
    start_time = time.time()
    
    for symbol in watchlist:
        ticker_result = smoke_polygon_one_ticker(symbol, lookback_days=5)
        result["symbols_tested"] += 1
        
        if ticker_result["success"]:
            result["symbols_passed"] += 1
            result["total_candles"] += ticker_result["candles_count"]
        else:
            result["symbols_failed"].append({
                "symbol": symbol,
                "error": ticker_result.get("error")
            })
        
        result["provider_stats"] = ticker_result.get("provider_stats", {})
        
        # Rate limiting: if we made an API call, sleep to avoid rate limit
        if ticker_result.get("api_call_made"):
            time.sleep(12)  # 5 calls/min = 1 call every 12 seconds
    
    result["total_time_ms"] = round((time.time() - start_time) * 1000, 2)
    result["success"] = result["symbols_passed"] == result["symbols_tested"]
    
    return result


if __name__ == "__main__":
    """CLI smoke test."""
    import json
    
    print("=" * 60)
    print("Polygon Stock Market Data Smoke Test")
    print("=" * 60)
    
    # Single ticker test
    print("\n[1] Single Ticker Test (AAPL)")
    result = smoke_polygon_one_ticker("AAPL", lookback_days=10)
    
    print(f"  Success: {result['success']}")
    print(f"  Candles: {result['candles_count']}")
    print(f"  Date Range: {result['date_range']}")
    print(f"  Cache Hit: {result['cache_hit']}")
    print(f"  Response Time: {result['response_time_ms']}ms")
    if result['error']:
        print(f"  Error: {result['error']}")
    print(f"  Provider Stats: {json.dumps(result['provider_stats'], indent=2)}")
    
    if result['success']:
        print("\n✅ Polygon smoke test PASSED")
    else:
        print("\n❌ Polygon smoke test FAILED")
