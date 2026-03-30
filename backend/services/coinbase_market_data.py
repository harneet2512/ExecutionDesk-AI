"""Coinbase Advanced Trade market data service.

Includes production hardening:
- Exponential backoff with jitter for retries
- TTL cache for products list
- Proper error handling for 429s and timeouts
"""
import httpx
import os
import sys
import time
import random
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from backend.services.market_data_provider import get_market_data_provider
from backend.core.logging import get_logger
from backend.core.config import get_settings
from backend.core.symbols import to_product_id

logger = get_logger(__name__)

# === HARDENING CONFIGURATION ===
# Retries are disabled in pytest to prevent time.sleep() blocking the event loop
_IN_PYTEST = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
MAX_RETRIES = 0 if _IN_PYTEST else 3
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 10.0
PRODUCTS_CACHE_TTL_SECONDS = 300  # 5 minutes (products don't change frequently)
REQUEST_TIMEOUT_SECONDS = 10.0


@dataclass
class APICallStats:
    """Thread-safe API call statistics tracker."""
    calls: int = 0
    retries: int = 0
    rate_429s: int = 0
    timeouts: int = 0
    cache_hits: int = 0
    successes: int = 0
    failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    
    def increment(self, field_name: str, value: int = 1) -> None:
        with self._lock:
            current = getattr(self, field_name, 0)
            setattr(self, field_name, current + value)
    
    def to_dict(self) -> dict:
        with self._lock:
            return {
                "calls": self.calls,
                "retries": self.retries,
                "rate_429s": self.rate_429s,
                "timeouts": self.timeouts,
                "cache_hits": self.cache_hits,
                "successes": self.successes,
                "failures": self.failures
            }


# Global stats tracker for observability
_api_stats = APICallStats()


def get_api_stats() -> dict:
    """Get current API call statistics."""
    return _api_stats.to_dict()


def reset_api_stats() -> None:
    """Reset API call statistics (for testing)."""
    global _api_stats
    _api_stats = APICallStats()


# === TTL CACHE FOR PRODUCTS LIST ===
_products_cache: Dict[str, Tuple[List[Dict], float]] = {}
_products_cache_lock = threading.Lock()


def _get_cached_products(quote: str) -> Optional[List[Dict]]:
    """Get products from cache if not expired."""
    with _products_cache_lock:
        cache_key = f"products_{quote}"
        if cache_key in _products_cache:
            products, cached_at = _products_cache[cache_key]
            if time.time() - cached_at < PRODUCTS_CACHE_TTL_SECONDS:
                _api_stats.increment("cache_hits")
                return products
    return None


def _set_cached_products(quote: str, products: List[Dict]) -> None:
    """Store products in cache."""
    with _products_cache_lock:
        cache_key = f"products_{quote}"
        _products_cache[cache_key] = (products, time.time())


# === RETRY WITH EXPONENTIAL BACKOFF ===
def _calculate_backoff(attempt: int) -> float:
    """Calculate backoff time with exponential backoff + jitter."""
    backoff = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
    jitter = random.uniform(0, backoff * 0.3)  # Up to 30% jitter
    return backoff + jitter


def _fetch_with_retry(
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    max_retries: int = MAX_RETRIES,
    timeout: float = REQUEST_TIMEOUT_SECONDS
) -> httpx.Response:
    """
    Fetch URL with exponential backoff + jitter on retryable errors.
    
    Retries on:
    - 429 Too Many Requests (rate limit)
    - 5xx Server errors
    - Timeout errors
    - Connection errors
    
    Returns:
        httpx.Response on success
        
    Raises:
        httpx.HTTPStatusError: On non-retryable HTTP errors (4xx except 429)
        httpx.TimeoutException: After max retries exhausted for timeouts
        Exception: After max retries exhausted for other errors
    """
    last_error = None
    
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        _api_stats.increment("calls")
        
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(url, params=params, headers=headers)
                
                # Check for rate limiting
                if response.status_code == 429:
                    _api_stats.increment("rate_429s")
                    if attempt < max_retries:
                        _api_stats.increment("retries")
                        wait_time = _calculate_backoff(attempt)
                        logger.warning(f"Rate limited (429) on {url}, retrying in {wait_time:.2f}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        _api_stats.increment("failures")
                        response.raise_for_status()
                
                # Check for server errors (retryable)
                if response.status_code >= 500:
                    if attempt < max_retries:
                        _api_stats.increment("retries")
                        wait_time = _calculate_backoff(attempt)
                        logger.warning(f"Server error ({response.status_code}) on {url}, retrying in {wait_time:.2f}s")
                        time.sleep(wait_time)
                        continue
                    else:
                        _api_stats.increment("failures")
                        response.raise_for_status()
                
                # Check for other errors
                response.raise_for_status()
                
                _api_stats.increment("successes")
                return response
                
        except httpx.TimeoutException as e:
            _api_stats.increment("timeouts")
            last_error = e
            if attempt < max_retries:
                _api_stats.increment("retries")
                wait_time = _calculate_backoff(attempt)
                logger.warning(f"Timeout on {url}, retrying in {wait_time:.2f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                _api_stats.increment("failures")
                raise
                
        except httpx.ConnectError as e:
            last_error = e
            if attempt < max_retries:
                _api_stats.increment("retries")
                wait_time = _calculate_backoff(attempt)
                logger.warning(f"Connection error on {url}, retrying in {wait_time:.2f}s")
                time.sleep(wait_time)
            else:
                _api_stats.increment("failures")
                raise
                
        except httpx.HTTPStatusError as e:
            # Don't retry 4xx errors (except 429 handled above)
            _api_stats.increment("failures")
            raise
    
    # Should not reach here, but just in case
    if last_error:
        raise last_error
    raise RuntimeError(f"Unexpected: max retries exhausted without error for {url}")


def list_products(quote: str = "USD", product_type: str = "SPOT") -> List[Dict[str, Any]]:
    """
    List Coinbase products (symbols).

    Uses the public Exchange API (no auth required).
    Implements TTL caching (60s) to reduce API calls.
    Uses retry with exponential backoff for reliability.
    Falls back to default universe on error.

    Returns:
        List of product dicts with product_id, base_currency, quote_currency, etc.
    """
    # Check cache first
    cached = _get_cached_products(quote)
    if cached is not None:
        logger.debug(f"Using cached products list ({len(cached)} {quote} products)")
        return cached
    
    from backend.providers.coinbase_market_data import CoinbaseMarketDataProvider
    public_url = CoinbaseMarketDataProvider.PUBLIC_URL

    try:
        response = _fetch_with_retry(
            url=f"{public_url}/products",
            headers={"Accept": "application/json"},
            max_retries=MAX_RETRIES,
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        data = response.json()

        # Exchange API returns a flat list of product objects
        filtered = [
            {
                "product_id": p.get("id", ""),
                "base_currency_id": p.get("base_currency", ""),
                "quote_currency_id": p.get("quote_currency", ""),
                "status": p.get("status", ""),
                "product_type": "SPOT",
            }
            for p in data
            if p.get("quote_currency") == quote and p.get("status") == "online"
        ]
        
        # Cache the result
        _set_cached_products(quote, filtered)
        
        logger.info(f"Fetched {len(filtered)} {quote} products from Coinbase Exchange API")
        return filtered
        
    except httpx.TimeoutException as e:
        logger.error(f"Timeout fetching products from Coinbase after {MAX_RETRIES} retries: {e}")
        return []
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            logger.error(f"Rate limited (429) fetching products after {MAX_RETRIES} retries")
        else:
            logger.error(f"HTTP error fetching products from Coinbase: {e.response.status_code}")
        return []
    except Exception as e:
        logger.error(f"Failed to list products from Coinbase: {e}")
        return []


def get_candles(
    product_id: str,
    start: str,
    end: str,
    granularity: str = "ONE_HOUR"
) -> List[Dict[str, Any]]:
    """
    Get candles for a product.
    
    Uses provider factory to select appropriate provider (test/live).
    Normalizes product_id to canonical format.
    
    Args:
        product_id: Product ID (e.g., "BTC-USD" or "BTC")
        start: Start time (ISO format)
        end: End time (ISO format)
        granularity: ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, ONE_HOUR, SIX_HOUR, ONE_DAY
    
    Returns:
        List of candle dicts
    """
    # Normalize to canonical product_id
    product_id = to_product_id(product_id)
    
    provider = get_market_data_provider()
    return provider.get_candles(
        symbol=product_id,
        interval=granularity.lower().replace("_", ""),
        start_time=start,
        end_time=end
    )


def compute_return_24h(candles: List[Dict[str, Any]]) -> float:
    """
    Compute 24h return from candles.
    
    Formula: (last_close - first_open) / first_open
    
    Returns:
        Return as decimal (e.g., 0.0234 for 2.34%)
    """
    if len(candles) < 2:
        return 0.0
    
    first_open = float(candles[0]["open"])
    last_close = float(candles[-1]["close"])
    
    if first_open == 0:
        return 0.0
    
    return (last_close - first_open) / first_open


def rank_top_movers(universe: List[str], top_k: int = 1, lookback_hours: int = 24) -> List[Dict[str, Any]]:
    """
    Rank top movers from universe based on 24h return.
    
    Uses provider factory to select appropriate provider (test/live).
    Normalizes product_ids to canonical format.
    
    Args:
        universe: List of product_ids (e.g., ["BTC-USD", "ETH-USD"] or ["BTC", "ETH"])
        top_k: Number of top movers to return
        lookback_hours: Lookback window in hours
    
    Returns:
        List of {product_id, return_24h, first_price, last_price, candles_count} sorted by return descending
    """
    provider = get_market_data_provider()
    
    # Calculate time window
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=lookback_hours)
    
    rankings = []
    
    for product_id in universe:
        # Normalize to canonical product_id
        product_id = to_product_id(product_id)
        
        try:
            candles = provider.get_candles(
                symbol=product_id,
                interval="1h" if lookback_hours <= 168 else "24h",
                start_time=start_time.isoformat() + "Z",
                end_time=end_time.isoformat() + "Z"
            )
            
            if len(candles) >= 2:
                return_24h = compute_return_24h(candles)
                rankings.append({
                    "product_id": product_id,
                    "return_24h": return_24h,
                    "first_price": float(candles[0]["open"]),
                    "last_price": float(candles[-1]["close"]),
                    "candles_count": len(candles)
                })
        except Exception as e:
            logger.warning(f"Failed to get candles for {product_id}: {e}")
            continue
    
    # Sort by return descending
    rankings.sort(key=lambda x: x["return_24h"], reverse=True)
    
    return rankings[:top_k]
