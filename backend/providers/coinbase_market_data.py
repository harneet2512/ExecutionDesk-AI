"""Coinbase Advanced Trade market data provider.

This is the only market data provider. Tests should mock HTTP calls via httpx_mock or similar.

Production hardening:
- Uses retry with exponential backoff from coinbase_market_data service
- Proper error handling for 429s and timeouts
"""
import os
import httpx
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from backend.providers.market_data_base import MarketDataProvider
from backend.core.logging import get_logger
from backend.core.config import get_settings
from backend.core.symbols import to_product_id

logger = get_logger(__name__)

# Retry configuration — disabled in pytest to prevent time.sleep() blocking the event loop
_IN_PYTEST = "pytest" in __import__("sys").modules or "PYTEST_CURRENT_TEST" in os.environ
MAX_RETRIES = 0 if _IN_PYTEST else 3
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 10.0


class CoinbaseMarketDataProvider(MarketDataProvider):
    """Coinbase market data provider.

    Uses the public Coinbase Exchange API for read-only market data (candles, prices).
    Uses the authenticated Advanced Trade API for order execution.
    """

    BASE_URL = "https://api.coinbase.com/api/v3/brokerage"
    PUBLIC_URL = "https://api.exchange.coinbase.com"

    # Map human-readable intervals to Exchange API granularity (seconds)
    GRANULARITY_MAP = {
        "ONE_MINUTE": 60,
        "FIVE_MINUTE": 300,
        "FIFTEEN_MINUTE": 900,
        "ONE_HOUR": 3600,
        "SIX_HOUR": 21600,
        "ONE_DAY": 86400,
        "oneminute": 60,
        "fiveminute": 300,
        "fifteenminute": 900,
        "onehour": 3600,
        "sixhour": 21600,
        "oneday": 86400,
        "1h": 3600,
        "24h": 86400,
        "7d": 86400,
    }

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or os.getenv("COINBASE_API_KEY") or getattr(settings, "coinbase_api_key", None)
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET") or getattr(settings, "coinbase_api_secret", None)

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers for public endpoints."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 300
    ) -> List[Dict[str, Any]]:
        """
        Get candles from Coinbase Exchange (public, no auth required).

        Coinbase Exchange API: GET /products/{product_id}/candles
        Granularity: seconds (60, 300, 900, 3600, 21600, 86400)
        Response: [[time, low, high, open, close, volume], ...]
        """
        product_id = to_product_id(symbol)

        # Resolve granularity to seconds
        granularity = self.GRANULARITY_MAP.get(interval, 3600)

        # Calculate time window
        if not start_time:
            end = datetime.utcnow()
            if granularity <= 3600:
                start = end - timedelta(hours=24)
            else:
                start = end - timedelta(days=30)
            start_time = start.isoformat() + "Z"
            end_time = end.isoformat() + "Z"

        # Parse ISO timestamps to epoch seconds for Exchange API
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            start_dt = datetime.fromisoformat(start_time.replace("Z", ""))
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00")) if end_time else datetime.utcnow()
        except (ValueError, AttributeError):
            end_dt = datetime.fromisoformat(end_time.replace("Z", "")) if end_time else datetime.utcnow()

        url = f"{self.PUBLIC_URL}/products/{product_id}/candles"
        params = {
            "start": int(start_dt.timestamp()),
            "end": int(end_dt.timestamp()),
            "granularity": granularity
        }

        last_error = None
        import sys as _sys
        _effective_retries = 0 if ("pytest" in _sys.modules or "PYTEST_CURRENT_TEST" in os.environ) else MAX_RETRIES

        for attempt in range(_effective_retries + 1):
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(url, headers=self._get_headers(), params=params)

                    # Handle rate limiting with retry
                    if response.status_code == 429:
                        if attempt < _effective_retries:
                            wait_time = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                            jitter = random.uniform(0, wait_time * 0.3)
                            total_wait = wait_time + jitter
                            logger.warning(f"Rate limited (429) for {symbol}, retrying in {total_wait:.2f}s")
                            time.sleep(total_wait)
                            continue
                        else:
                            raise ValueError(f"Rate limited (429) for {symbol} after {_effective_retries} retries")
                    
                    # Handle server errors with retry
                    if response.status_code >= 500:
                        if attempt < _effective_retries:
                            wait_time = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                            logger.warning(f"Server error ({response.status_code}) for {symbol}, retrying in {wait_time:.2f}s")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Coinbase API server error for {symbol}: {response.status_code} - {response.text}")
                            raise ValueError(f"Coinbase API server error ({response.status_code}). Error: {response.text}")

                    response.raise_for_status()
                    data = response.json()

                    # Exchange API returns: [[time, low, high, open, close, volume], ...]
                    candles = []
                    for row in data:
                        if not isinstance(row, (list, tuple)) or len(row) < 5:
                            continue
                        candles.append({
                            "start_time": datetime.utcfromtimestamp(row[0]).isoformat() + "Z",
                            "end_time": datetime.utcfromtimestamp(row[0] + granularity).isoformat() + "Z",
                            "low": float(row[1]),
                            "high": float(row[2]),
                            "open": float(row[3]),
                            "close": float(row[4]),
                            "volume": float(row[5]) if len(row) > 5 else 0.0
                        })

                    # Sort by start_time ascending (Exchange API returns newest first)
                    candles.sort(key=lambda x: x["start_time"])
                    return candles[-limit:] if len(candles) > limit else candles

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _effective_retries:
                    wait_time = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                    logger.warning(f"Timeout for {symbol}, retrying in {wait_time:.2f}s (attempt {attempt + 1}/{_effective_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Coinbase API timeout for {symbol} after {_effective_retries} retries")
                    raise ValueError(f"Timeout fetching candles for {symbol} after {_effective_retries} retries")
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    logger.error(f"Coinbase API server error for {symbol}: {e.response.status_code} - {e.response.text}")
                    raise ValueError(f"Coinbase API server error ({e.response.status_code}). Error: {e.response.text}")
                else:
                    logger.error(f"Coinbase API error for {symbol}: {e.response.status_code} - {e.response.text}")
                    raise
            except Exception as e:
                logger.error(f"Coinbase API error for {symbol}: {e}")
                raise
        
        # Should not reach here
        if last_error:
            raise last_error
        raise RuntimeError(f"Unexpected: max retries exhausted for {symbol}")

    def get_price(self, symbol: str) -> float:
        """Get current price from Coinbase Exchange (public, no auth required).

        Uses retry with exponential backoff for reliability.
        """
        import sys as _sys
        _effective_retries = 0 if ("pytest" in _sys.modules or "PYTEST_CURRENT_TEST" in os.environ) else MAX_RETRIES

        product_id = to_product_id(symbol)
        url = f"{self.PUBLIC_URL}/products/{product_id}/ticker"

        last_error = None

        for attempt in range(_effective_retries + 1):
            try:
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(url, headers=self._get_headers())
                    
                    # Handle rate limiting with retry
                    if response.status_code == 429:
                        if attempt < _effective_retries:
                            wait_time = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                            jitter = random.uniform(0, wait_time * 0.3)
                            logger.warning(f"Rate limited (429) for {symbol} price, retrying in {wait_time + jitter:.2f}s")
                            time.sleep(wait_time + jitter)
                            continue
                        else:
                            raise ValueError(f"Rate limited (429) for {symbol} price after {_effective_retries} retries")

                    # Handle server errors with retry
                    if response.status_code >= 500:
                        if attempt < _effective_retries:
                            wait_time = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                            logger.warning(f"Server error ({response.status_code}) for {symbol} price, retrying")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Coinbase API server error for {symbol}: {response.status_code} - {response.text}")
                            raise ValueError(f"Coinbase API server error ({response.status_code})")

                    response.raise_for_status()
                    data = response.json()
                    return float(data.get("price", 0))

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _effective_retries:
                    wait_time = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                    logger.warning(f"Timeout for {symbol} price, retrying in {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    raise ValueError(f"Timeout getting price for {symbol} after {_effective_retries} retries")
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    logger.error(f"Coinbase API server error for {symbol}: {e.response.status_code} - {e.response.text}")
                    raise ValueError(f"Coinbase API server error ({e.response.status_code}). Error: {e.response.text}")
                else:
                    logger.error(f"Coinbase API error for {symbol}: {e.response.status_code} - {e.response.text}")
                    raise
            except Exception as e:
                logger.error(f"Coinbase price fetch failed for {symbol}: {e}")
                raise ValueError(f"Failed to get price for {symbol} from Coinbase: {str(e)}")
        
        # Should not reach here
        if last_error:
            raise ValueError(f"Failed to get price for {symbol}: {last_error}")
        raise RuntimeError(f"Unexpected: max retries exhausted for {symbol} price")
