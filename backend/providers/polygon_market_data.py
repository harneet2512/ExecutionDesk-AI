"""Polygon.io market data provider for stocks.

Implements the MarketDataProvider interface for stock data.
Respects Polygon.io free tier limits (5 API calls/min, EOD data only).

Lookback interpretation for stocks (EOD data):
- 24h = 1 daily close
- 48h = 2 daily closes
- 1w  = 5 daily closes (trading days)
"""
import httpx
import time
import threading
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from backend.providers.market_data_base import MarketDataProvider
from backend.services.rate_limiter import get_polygon_rate_limiter
from backend.core.logging import get_logger
from backend.core.config import get_settings
from backend.core.test_utils import is_pytest
from backend.db.connect import get_conn

logger = get_logger(__name__)

# Polygon API configuration
POLYGON_BASE_URL = "https://api.polygon.io"
REQUEST_TIMEOUT_SECONDS = 15.0
CACHE_TTL_SECONDS = 3600  # 1 hour (EOD data doesn't change intraday)

# Lookback interpretation: user's "24h/48h/1w" -> number of EOD closes needed
LOOKBACK_TO_CLOSES = {
    "1h": 1,    # Intraday not available, use 1 close
    "24h": 1,   # 1 daily close
    "48h": 2,   # 2 daily closes
    "7d": 5,    # 5 trading days
    "1w": 5,    # Same as 7d
    "30d": 22,  # ~22 trading days
}


class PolygonAPIError(Exception):
    """Raised when Polygon API returns an error."""
    pass


class PolygonRateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass


class PolygonMarketDataProvider(MarketDataProvider):
    """Polygon.io market data provider for stocks.

    Free tier constraints:
    - 5 API calls per minute
    - End-of-day (EOD) data only
    - 2 years historical data
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Polygon provider.

        Args:
            api_key: Polygon API key. If not provided, uses POLYGON_API_KEY from settings.
        """
        settings = get_settings()
        self.api_key = api_key or settings.polygon_api_key
        if not self.api_key and not is_pytest():
            raise ValueError("POLYGON_API_KEY required for stock data")

        self.rate_limiter = get_polygon_rate_limiter()

        # In-memory cache: {cache_key: (data, timestamp)}
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_lock = threading.Lock()

        # Stats for observability
        self._stats = {
            "calls": 0,
            "cache_hits": 0,
            "rate_limit_waits": 0,
            "errors": 0
        }
        self._stats_lock = threading.Lock()

    def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get daily candles (bars) for a stock symbol.

        Polygon free tier only supports daily aggregates, so we interpret
        interval as number of trading days rather than true time intervals.

        Args:
            symbol: Stock symbol (e.g., "AAPL", "MSFT")
            interval: Lookback period (24h, 48h, 1w, etc.) -> converted to EOD closes
            start_time: Not used directly (calculated from interval)
            end_time: Not used directly (uses today)
            limit: Max candles to return

        Returns:
            List of candles with open, high, low, close, volume, start_time, end_time
        """
        # Normalize symbol (remove -USD suffix if present)
        symbol = symbol.replace("-USD", "").upper()

        # Determine number of closes needed
        num_closes = LOOKBACK_TO_CLOSES.get(interval.lower(), 1)

        # Calculate date range (add buffer for weekends/holidays)
        end_date = datetime.utcnow().date()
        buffer_days = num_closes + 10  # Extra buffer for weekends/holidays
        start_date = end_date - timedelta(days=buffer_days)

        # Check cache first
        cache_key = self._cache_key(symbol, str(start_date), str(end_date))
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached[-num_closes:]

        # Check DB cache
        db_cached = self._get_db_cached(symbol, str(start_date), str(end_date))
        if db_cached:
            self._set_cached(cache_key, db_cached)
            return db_cached[-num_closes:]

        # Acquire rate limit token
        if not self.rate_limiter.acquire(timeout_seconds=30):
            with self._stats_lock:
                self._stats["rate_limit_waits"] += 1
                self._stats["errors"] += 1
            raise PolygonRateLimitError(
                f"Rate limit exceeded for Polygon API (symbol={symbol}). "
                f"Free tier limit: {self.rate_limiter.tokens_per_minute} calls/min"
            )

        with self._stats_lock:
            self._stats["calls"] += 1

        # Fetch from Polygon API
        url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}"
        params = {
            "apiKey": self.api_key,
            "adjusted": "true",
            "sort": "asc",
            "limit": limit
        }

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = client.get(url, params=params)

                if response.status_code == 429:
                    with self._stats_lock:
                        self._stats["errors"] += 1
                    raise PolygonRateLimitError(
                        f"Polygon API rate limited (429) for {symbol}"
                    )

                if response.status_code == 403:
                    raise PolygonAPIError(
                        f"Polygon API forbidden (403) for {symbol}. Check API key permissions."
                    )

                if response.status_code != 200:
                    with self._stats_lock:
                        self._stats["errors"] += 1
                    raise PolygonAPIError(
                        f"Polygon API error {response.status_code} for {symbol}: {response.text}"
                    )

                data = response.json()

        except httpx.TimeoutException:
            with self._stats_lock:
                self._stats["errors"] += 1
            raise PolygonAPIError(f"Polygon API timeout for {symbol}")

        except httpx.RequestError as e:
            with self._stats_lock:
                self._stats["errors"] += 1
            raise PolygonAPIError(f"Polygon API request error for {symbol}: {e}")

        # Parse response
        results = data.get("results", [])
        if not results:
            logger.warning(f"No candle data from Polygon for {symbol}")
            return []

        candles = []
        for bar in results:
            # Polygon timestamps are in milliseconds
            ts = bar.get("t", 0)
            candle_date = datetime.utcfromtimestamp(ts / 1000)
            candles.append({
                "start_time": candle_date.isoformat() + "Z",
                "end_time": (candle_date + timedelta(days=1)).isoformat() + "Z",
                "open": float(bar.get("o", 0)),
                "high": float(bar.get("h", 0)),
                "low": float(bar.get("l", 0)),
                "close": float(bar.get("c", 0)),
                "volume": float(bar.get("v", 0))
            })

        # Store in caches
        self._set_cached(cache_key, candles)
        self._store_db_cache(symbol, candles)

        logger.info(
            "Fetched %d candles from Polygon for %s",
            len(candles), symbol
        )

        return candles[-num_closes:]

    def get_price(self, symbol: str) -> float:
        """Get latest closing price for a stock.

        Args:
            symbol: Stock symbol (e.g., "AAPL")

        Returns:
            Latest closing price
        """
        candles = self.get_candles(symbol, "24h")
        if candles:
            return candles[-1]["close"]
        raise ValueError(f"No price data for {symbol}")

    def list_products(self) -> List[Dict[str, Any]]:
        """Return the stock watchlist as products.

        Unlike Coinbase, we don't scan the full universe. We use a
        configured watchlist to respect free tier limits.

        Returns:
            List of product dicts for watchlist symbols
        """
        settings = get_settings()
        watchlist = settings.stock_watchlist_list

        return [
            {
                "product_id": f"{symbol}-USD",
                "base_currency_id": symbol,
                "quote_currency_id": "USD",
                "status": "online",
                "product_type": "STOCK"
            }
            for symbol in watchlist
        ]

    def rank_top_movers(
        self,
        universe: List[str],
        top_k: int = 1,
        lookback_hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Rank stocks by EOD return.

        Args:
            universe: List of stock symbols
            top_k: Number of top movers to return
            lookback_hours: Interpreted as trading days (24h=1, 48h=2, 1w=5)

        Returns:
            List of {product_id, return_24h, first_price, last_price, candles_count, granularity}
        """
        # Convert hours to lookback interval
        if lookback_hours <= 24:
            interval = "24h"
        elif lookback_hours <= 48:
            interval = "48h"
        elif lookback_hours <= 168:  # 1 week
            interval = "1w"
        else:
            interval = "30d"

        rankings = []
        drop_reasons = {}

        for symbol in universe:
            # Normalize symbol
            symbol = symbol.replace("-USD", "").upper()

            try:
                candles = self.get_candles(symbol, interval)

                if len(candles) < 2:
                    drop_reasons[symbol] = "insufficient_candles"
                    continue

                first_open = candles[0]["open"]
                last_close = candles[-1]["close"]

                if first_open == 0:
                    drop_reasons[symbol] = "invalid_price"
                    continue

                return_pct = (last_close - first_open) / first_open

                rankings.append({
                    "product_id": f"{symbol}-USD",
                    "symbol": symbol,
                    "return_24h": return_pct,
                    "return_pct": return_pct * 100,  # Percentage form
                    "first_price": first_open,
                    "last_price": last_close,
                    "candles_count": len(candles),
                    "granularity": "EOD",
                    "staleness_note": self._staleness_note(candles)
                })

            except PolygonRateLimitError:
                drop_reasons[symbol] = "rate_limited"
                logger.warning(f"Rate limited fetching {symbol}, skipping")
                continue

            except PolygonAPIError as e:
                drop_reasons[symbol] = "api_error"
                logger.warning(f"API error for {symbol}: {e}")
                continue

            except Exception as e:
                drop_reasons[symbol] = "unknown_error"
                logger.warning(f"Error fetching {symbol}: {e}")
                continue

        # Sort by return descending
        rankings.sort(key=lambda x: x["return_24h"], reverse=True)

        # Add ranking info
        for i, r in enumerate(rankings):
            r["rank"] = i + 1

        result = rankings[:top_k]

        # Attach drop reasons metadata
        if drop_reasons:
            logger.info(
                "Dropped %d symbols from ranking: %s",
                len(drop_reasons), str(drop_reasons)[:200]
            )

        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get provider statistics."""
        with self._stats_lock:
            stats = self._stats.copy()
        stats["rate_limiter"] = self.rate_limiter.get_stats()
        return stats

    # === Cache helpers ===

    def _cache_key(self, symbol: str, start: str, end: str) -> str:
        """Generate cache key."""
        return f"{symbol}|{start}|{end}"

    def _get_cached(self, key: str) -> Optional[List]:
        """Get from in-memory cache."""
        with self._cache_lock:
            if key in self._cache:
                data, cached_at = self._cache[key]
                if time.time() - cached_at < CACHE_TTL_SECONDS:
                    with self._stats_lock:
                        self._stats["cache_hits"] += 1
                    return data
                del self._cache[key]
        return None

    def _set_cached(self, key: str, data: List):
        """Store in in-memory cache."""
        with self._cache_lock:
            self._cache[key] = (data, time.time())

    def _get_db_cached(self, symbol: str, start: str, end: str) -> Optional[List]:
        """Get candles from DB cache (market_candles table)."""
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT start_time, end_time, open, high, low, close, volume
                    FROM market_candles
                    WHERE symbol = ? AND start_time >= ? AND end_time <= ?
                    ORDER BY start_time ASC
                    """,
                    (symbol, start, end)
                )
                rows = cursor.fetchall()
                if rows:
                    return [
                        {
                            "start_time": r["start_time"],
                            "end_time": r["end_time"],
                            "open": r["open"],
                            "high": r["high"],
                            "low": r["low"],
                            "close": r["close"],
                            "volume": r["volume"]
                        }
                        for r in rows
                    ]
        except Exception as e:
            logger.debug(f"DB cache lookup failed: {e}")
        return None

    def _store_db_cache(self, symbol: str, candles: List[Dict]):
        """Store candles in DB cache (market_candles table)."""
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                for c in candles:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO market_candles
                        (symbol, interval, start_time, end_time, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            symbol, "1d",
                            c["start_time"], c["end_time"],
                            c["open"], c["high"], c["low"], c["close"], c["volume"]
                        )
                    )
                conn.commit()
        except Exception as e:
            logger.debug(f"DB cache store failed: {e}")

    def _staleness_note(self, candles: List[Dict]) -> Optional[str]:
        """Generate staleness note for EOD data."""
        if not candles:
            return "No data available"

        # Get most recent candle date
        last_candle = candles[-1]
        try:
            last_date = datetime.fromisoformat(last_candle["start_time"].replace("Z", ""))
            days_old = (datetime.utcnow() - last_date).days

            if days_old <= 1:
                return None  # Fresh data
            elif days_old <= 3:
                return f"EOD data is {days_old} days old (weekend/holiday delay)"
            else:
                return f"Warning: EOD data is {days_old} days old"
        except:
            return None


# === Module-level helper for stock ranking ===

def rank_stock_top_movers(
    universe: Optional[List[str]] = None,
    top_k: int = 1,
    lookback_hours: int = 24
) -> List[Dict[str, Any]]:
    """Rank top stock movers from universe or watchlist.

    Convenience function that creates provider and calls rank_top_movers.

    Args:
        universe: List of symbols (uses watchlist if None)
        top_k: Number of top movers
        lookback_hours: Lookback period (interpreted as trading days)

    Returns:
        Ranked list with return, price, and granularity info
    """
    settings = get_settings()

    if universe is None:
        universe = settings.stock_watchlist_list

    # Enforce max symbols per run
    max_symbols = settings.stock_max_symbols_per_run
    if len(universe) > max_symbols:
        logger.warning(
            "Limiting stock universe from %d to %d symbols",
            len(universe), max_symbols
        )
        universe = universe[:max_symbols]

    provider = PolygonMarketDataProvider()
    return provider.rank_top_movers(universe, top_k, lookback_hours)
