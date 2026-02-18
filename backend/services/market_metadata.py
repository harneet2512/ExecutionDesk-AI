"""Market Metadata Service with retry logic and stale cache fallback.

Provides robust product metadata fetching from Coinbase with:
- Exponential backoff retry for transient failures
- Fallback to stale cache when API is unavailable
- Structured error reporting
"""
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from enum import Enum

import httpx

from backend.core.logging import get_logger
from backend.db.connect import get_conn
from backend.core.time import now_iso

logger = get_logger(__name__)


# Safe fallback precision values for common crypto pairs.
# These are conservative values (stricter than Coinbase minimums) to ensure
# orders are valid even when the product API is unreachable.
_COMMON_CRYPTO_DEFAULTS = {
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "base_min_size": "0.01",
    "base_max_size": "1000000",
    "quote_min_size": "1.00",
    "quote_max_size": "1000000",
}

SAFE_FALLBACK_PRECISION = {
    "BTC-USD": {
        **_COMMON_CRYPTO_DEFAULTS,
        "base_min_size": "0.00001",
        "base_max_size": "10000",
    },
    "ETH-USD": {
        **_COMMON_CRYPTO_DEFAULTS,
        "base_min_size": "0.0001",
        "base_max_size": "100000",
    },
    "SOL-USD": {**_COMMON_CRYPTO_DEFAULTS},
    "USDC-USD": {
        **_COMMON_CRYPTO_DEFAULTS,
        "quote_increment": "0.0001",
        "base_min_size": "1.00",
        "base_max_size": "10000000",
        "quote_max_size": "10000000",
    },
    # Additional common pairs
    "MATIC-USD": {**_COMMON_CRYPTO_DEFAULTS},
    "AVAX-USD": {**_COMMON_CRYPTO_DEFAULTS},
    "DOGE-USD": {**_COMMON_CRYPTO_DEFAULTS, "base_min_size": "1.00"},
    "ADA-USD": {**_COMMON_CRYPTO_DEFAULTS, "base_min_size": "1.00"},
    "DOT-USD": {**_COMMON_CRYPTO_DEFAULTS},
    "LINK-USD": {**_COMMON_CRYPTO_DEFAULTS},
    "XRP-USD": {**_COMMON_CRYPTO_DEFAULTS, "base_min_size": "1.00"},
    "SHIB-USD": {**_COMMON_CRYPTO_DEFAULTS, "base_min_size": "100000.00"},
    "UNI-USD": {**_COMMON_CRYPTO_DEFAULTS},
    "LTC-USD": {**_COMMON_CRYPTO_DEFAULTS, "base_min_size": "0.001"},
    "ATOM-USD": {**_COMMON_CRYPTO_DEFAULTS},
}


class MetadataErrorCode(str, Enum):
    """Error codes for metadata fetch failures."""
    SUCCESS = "SUCCESS"
    API_TIMEOUT = "API_TIMEOUT"
    API_RATE_LIMITED = "API_RATE_LIMITED"
    API_ERROR = "API_ERROR"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    NO_CACHE_AVAILABLE = "NO_CACHE_AVAILABLE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class MetadataResult:
    """Result of product metadata fetch."""
    success: bool
    data: Optional[Dict[str, Any]]
    error_code: MetadataErrorCode
    error_message: Optional[str]
    used_stale_cache: bool
    cache_age_seconds: Optional[int]


class MarketMetadataService:
    """Service for fetching and caching product metadata from Coinbase."""
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        """Initialize service with optional credentials."""
        self.api_key = api_key
        self.api_secret = api_secret
        self.cache_ttl_hours = 1
        self.max_stale_hours = 24  # Allow stale cache up to 24 hours old
    
    async def get_product_details(
        self,
        product_id: str,
        allow_stale: bool = True,
        headers: Optional[Dict[str, str]] = None
    ) -> MetadataResult:
        """Get product details with retry and fallback logic.
        
        Args:
            product_id: Product identifier (e.g., "BTC-USD")
            allow_stale: If True, fallback to stale cache on API failure
            headers: Optional pre-computed auth headers
            
        Returns:
            MetadataResult with product data or error information
        """
        # Step 1: Check fresh cache (within TTL)
        cached = self._get_from_cache(product_id, max_age_hours=self.cache_ttl_hours)
        if cached:
            logger.info(f"Product details cache hit for {product_id} (fresh)")
            return MetadataResult(
                success=True,
                data=cached,
                error_code=MetadataErrorCode.SUCCESS,
                error_message=None,
                used_stale_cache=False,
                cache_age_seconds=self._get_cache_age_seconds(cached)
            )
        
        # Step 2: Attempt API fetch with retry
        api_result = await self._fetch_from_api_with_retry(product_id, headers=headers)
        
        if api_result.success:
            # Cache the fresh data
            self._save_to_cache(product_id, api_result.data)
            return api_result
        
        # Step 3: Fallback to stale cache if allowed
        if allow_stale:
            stale_cached = self._get_from_cache(product_id, max_age_hours=self.max_stale_hours)
            if stale_cached:
                cache_age = self._get_cache_age_seconds(stale_cached)
                logger.warning(
                    f"Using stale cache for {product_id} (age: {cache_age}s) "
                    f"due to API failure: {api_result.error_message}"
                )
                return MetadataResult(
                    success=True,
                    data=stale_cached,
                    error_code=MetadataErrorCode.SUCCESS,
                    error_message=f"Using stale cache (API failed: {api_result.error_message})",
                    used_stale_cache=True,
                    cache_age_seconds=cache_age
                )
        
        # Step 4a: Try persistent product catalog (populated from public API)
        try:
            from backend.services.product_catalog import get_product_catalog
            cat_product = get_product_catalog().get_product(product_id)
            if cat_product:
                catalog_data = {
                    "product_id": cat_product.product_id,
                    "base_currency_id": cat_product.base_currency,
                    "quote_currency_id": cat_product.quote_currency,
                    "base_min_size": cat_product.base_min_size,
                    "base_max_size": cat_product.base_max_size,
                    "quote_increment": cat_product.quote_increment,
                    "base_increment": cat_product.base_increment,
                    "min_market_funds": cat_product.min_market_funds,
                    "status": cat_product.status,
                }
                logger.info(
                    "Using product catalog data for %s (API failed: %s)",
                    product_id, api_result.error_message,
                )
                return MetadataResult(
                    success=True,
                    data=catalog_data,
                    error_code=MetadataErrorCode.SUCCESS,
                    error_message=f"Using product catalog (API failed: {api_result.error_message})",
                    used_stale_cache=False,
                    cache_age_seconds=None,
                )
        except Exception as e:
            logger.debug("Product catalog lookup failed: %s", str(e)[:100])

        # Step 4b: Try safe fallback precision for common products
        if product_id in SAFE_FALLBACK_PRECISION:
            fallback_data = SAFE_FALLBACK_PRECISION[product_id].copy()
            fallback_data["product_id"] = product_id
            logger.warning(
                f"Using safe fallback precision for {product_id} "
                f"(API failed: {api_result.error_message}, no cache available)"
            )
            return MetadataResult(
                success=True,
                data=fallback_data,
                error_code=MetadataErrorCode.SUCCESS,
                error_message=f"Using safe fallback precision (API failed: {api_result.error_message})",
                used_stale_cache=False,
                cache_age_seconds=None
            )
        
        # Step 5: No cache or fallback available, return API error
        logger.error(f"Failed to get product details for {product_id}: {api_result.error_message}")
        return MetadataResult(
            success=False,
            data=None,
            error_code=api_result.error_code,
            error_message=api_result.error_message,
            used_stale_cache=False,
            cache_age_seconds=None
        )
    
    async def _fetch_from_api_with_retry(
        self,
        product_id: str,
        max_retries: int = 3,
        headers: Optional[Dict[str, str]] = None
    ) -> MetadataResult:
        """Fetch product details from Coinbase API with exponential backoff retry.
        
        Args:
            product_id: Product identifier
            max_retries: Maximum number of retry attempts
            headers: Optional pre-computed auth headers
            
        Returns:
            MetadataResult with API response or error
        """
        path = f"/api/v3/brokerage/products/{product_id}"
        url = f"https://api.coinbase.com{path}"
        
        last_error = None
        last_error_code = MetadataErrorCode.UNKNOWN_ERROR
        
        for attempt in range(max_retries):
            try:
                # Exponential backoff: 1s, 2s, 4s
                if attempt > 0:
                    delay = 2 ** (attempt - 1)
                    logger.info(f"Retrying {product_id} fetch after {delay}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Use provided headers or make unauthenticated request
                    request_headers = headers or {}
                    response = await client.get(url, headers=request_headers)
                    
                    # Handle specific status codes
                    if response.status_code == 404:
                        return MetadataResult(
                            success=False,
                            data=None,
                            error_code=MetadataErrorCode.PRODUCT_NOT_FOUND,
                            error_message=f"Product {product_id} not found",
                            used_stale_cache=False,
                            cache_age_seconds=None
                        )
                    
                    if response.status_code == 429:
                        last_error_code = MetadataErrorCode.API_RATE_LIMITED
                        last_error = f"Rate limited (429) on attempt {attempt + 1}"
                        logger.warning(f"Rate limited fetching {product_id}, will retry")
                        continue
                    
                    if response.status_code >= 500:
                        last_error_code = MetadataErrorCode.API_ERROR
                        last_error = f"Server error ({response.status_code}) on attempt {attempt + 1}"
                        logger.warning(f"Server error {response.status_code} fetching {product_id}, will retry")
                        continue
                    
                    # Explicit 401 detection with actionable logging + telemetry
                    if response.status_code == 401:
                        try:
                            from backend.services.product_catalog import get_product_catalog
                            get_product_catalog().record_metadata_401()
                        except Exception:
                            pass
                        logger.warning(
                            "coinbase_metadata_401 for %s — "
                            "Broker metadata auth misconfigured. "
                            "Check API key scopes (requires 'view' on Advanced Trade). "
                            "Falling back to catalog/safe defaults.",
                            product_id,
                        )
                        return MetadataResult(
                            success=False,
                            data=None,
                            error_code=MetadataErrorCode.API_ERROR,
                            error_message=f"Auth error 401 for {product_id}: check API key scopes",
                            used_stale_cache=False,
                            cache_age_seconds=None,
                        )

                    # Raise for other 4xx errors (don't retry)
                    if 400 <= response.status_code < 500:
                        return MetadataResult(
                            success=False,
                            data=None,
                            error_code=MetadataErrorCode.API_ERROR,
                            error_message=f"Client error {response.status_code}: {response.text[:200]}",
                            used_stale_cache=False,
                            cache_age_seconds=None
                        )
                    
                    response.raise_for_status()
                    
                    # Parse response
                    product_data = response.json().get("product", {})
                    if not product_data:
                        return MetadataResult(
                            success=False,
                            data=None,
                            error_code=MetadataErrorCode.API_ERROR,
                            error_message="Empty product data in API response",
                            used_stale_cache=False,
                            cache_age_seconds=None
                        )
                    
                    logger.info(f"Successfully fetched product details for {product_id}")
                    return MetadataResult(
                        success=True,
                        data=product_data,
                        error_code=MetadataErrorCode.SUCCESS,
                        error_message=None,
                        used_stale_cache=False,
                        cache_age_seconds=0
                    )
            
            except asyncio.TimeoutError:
                last_error_code = MetadataErrorCode.API_TIMEOUT
                last_error = f"Timeout on attempt {attempt + 1}"
                logger.warning(f"Timeout fetching {product_id}, will retry")
                continue
            
            except httpx.RequestError as e:
                last_error_code = MetadataErrorCode.API_ERROR
                last_error = f"Request error on attempt {attempt + 1}: {str(e)[:200]}"
                logger.warning(f"Request error fetching {product_id}: {e}")
                continue
            
            except Exception as e:
                last_error_code = MetadataErrorCode.UNKNOWN_ERROR
                last_error = f"Unexpected error on attempt {attempt + 1}: {str(e)[:200]}"
                logger.error(f"Unexpected error fetching {product_id}: {e}")
                # Don't retry on unexpected errors
                break
        
        # All retries exhausted
        return MetadataResult(
            success=False,
            data=None,
            error_code=last_error_code,
            error_message=f"Failed after {max_retries} attempts: {last_error}",
            used_stale_cache=False,
            cache_age_seconds=None
        )
    
    def get_product_details_sync(
        self,
        product_id: str,
        allow_stale: bool = True,
        headers: Optional[Dict[str, str]] = None
    ) -> "MetadataResult":
        """Synchronous version of get_product_details.

        Safe to call from inside a running event loop (no run_until_complete).
        Uses httpx.Client (sync) instead of AsyncClient.
        """
        # Step 1: Fresh cache
        cached = self._get_from_cache(product_id, max_age_hours=self.cache_ttl_hours)
        if cached:
            return MetadataResult(
                success=True, data=cached,
                error_code=MetadataErrorCode.SUCCESS, error_message=None,
                used_stale_cache=False,
                cache_age_seconds=self._get_cache_age_seconds(cached),
            )

        # Step 2: Sync API fetch with retry
        api_result = self._fetch_from_api_sync(product_id, headers=headers)
        if api_result.success:
            self._save_to_cache(product_id, api_result.data)
            return api_result

        # Step 3: Stale cache fallback
        if allow_stale:
            stale = self._get_from_cache(product_id, max_age_hours=self.max_stale_hours)
            if stale:
                age = self._get_cache_age_seconds(stale)
                logger.warning("Using stale cache for %s (age: %ds)", product_id, age)
                return MetadataResult(
                    success=True, data=stale,
                    error_code=MetadataErrorCode.SUCCESS,
                    error_message=f"Using stale cache (API failed: {api_result.error_message})",
                    used_stale_cache=True, cache_age_seconds=age,
                )

        # Step 4a: Product catalog fallback (sync)
        try:
            from backend.services.product_catalog import get_product_catalog
            cat_product = get_product_catalog().get_product(product_id)
            if cat_product:
                catalog_data = {
                    "product_id": cat_product.product_id,
                    "base_currency_id": cat_product.base_currency,
                    "quote_currency_id": cat_product.quote_currency,
                    "base_min_size": cat_product.base_min_size,
                    "base_max_size": cat_product.base_max_size,
                    "quote_increment": cat_product.quote_increment,
                    "base_increment": cat_product.base_increment,
                    "min_market_funds": cat_product.min_market_funds,
                    "status": cat_product.status,
                }
                logger.info("Using product catalog for %s (sync)", product_id)
                return MetadataResult(
                    success=True, data=catalog_data,
                    error_code=MetadataErrorCode.SUCCESS,
                    error_message=f"Using catalog (API failed: {api_result.error_message})",
                    used_stale_cache=False, cache_age_seconds=None,
                )
        except Exception:
            pass

        # Step 4b: Safe fallback precision
        if product_id in SAFE_FALLBACK_PRECISION:
            fb = SAFE_FALLBACK_PRECISION[product_id].copy()
            fb["product_id"] = product_id
            logger.warning("Using safe fallback precision for %s", product_id)
            return MetadataResult(
                success=True, data=fb,
                error_code=MetadataErrorCode.SUCCESS,
                error_message=f"Using safe fallback (API failed: {api_result.error_message})",
                used_stale_cache=False, cache_age_seconds=None,
            )

        return api_result

    def _fetch_from_api_sync(
        self,
        product_id: str,
        max_retries: int = 3,
        headers: Optional[Dict[str, str]] = None,
    ) -> "MetadataResult":
        """Sync HTTP fetch with exponential backoff."""
        url = f"https://api.coinbase.com/api/v3/brokerage/products/{product_id}"
        last_error = None
        last_code = MetadataErrorCode.UNKNOWN_ERROR

        for attempt in range(max_retries):
            if attempt > 0:
                time.sleep(2 ** (attempt - 1))

            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(url, headers=headers or {})

                    if resp.status_code == 404:
                        return MetadataResult(False, None, MetadataErrorCode.PRODUCT_NOT_FOUND,
                                              f"Product {product_id} not found", False, None)
                    if resp.status_code == 429:
                        last_code = MetadataErrorCode.API_RATE_LIMITED
                        last_error = f"Rate limited (attempt {attempt + 1})"
                        continue
                    if resp.status_code >= 500:
                        last_code = MetadataErrorCode.API_ERROR
                        last_error = f"Server error {resp.status_code} (attempt {attempt + 1})"
                        continue
                    if resp.status_code == 401:
                        try:
                            from backend.services.product_catalog import get_product_catalog
                            get_product_catalog().record_metadata_401()
                        except Exception:
                            pass
                        logger.warning(
                            "coinbase_metadata_401 (sync) for %s — check API key scopes",
                            product_id,
                        )
                        return MetadataResult(False, None, MetadataErrorCode.API_ERROR,
                                              f"Auth error 401 for {product_id}: check API key scopes",
                                              False, None)
                    if 400 <= resp.status_code < 500:
                        return MetadataResult(False, None, MetadataErrorCode.API_ERROR,
                                              f"Client error {resp.status_code}", False, None)

                    resp.raise_for_status()
                    data = resp.json().get("product", {})
                    if not data:
                        return MetadataResult(False, None, MetadataErrorCode.API_ERROR,
                                              "Empty product data", False, None)
                    return MetadataResult(True, data, MetadataErrorCode.SUCCESS, None, False, 0)

            except httpx.TimeoutException:
                last_code = MetadataErrorCode.API_TIMEOUT
                last_error = f"Timeout (attempt {attempt + 1})"
            except httpx.RequestError as e:
                last_code = MetadataErrorCode.API_ERROR
                last_error = f"Request error: {str(e)[:200]}"
            except Exception as e:
                last_code = MetadataErrorCode.UNKNOWN_ERROR
                last_error = f"Unexpected: {str(e)[:200]}"
                break

        return MetadataResult(False, None, last_code,
                              f"Failed after {max_retries} attempts: {last_error}", False, None)

    def _get_from_cache(
        self,
        product_id: str,
        max_age_hours: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Get product details from cache.
        
        Args:
            product_id: Product identifier
            max_age_hours: Maximum age in hours (None = no age limit)
            
        Returns:
            Cached product data or None
        """
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                
                if max_age_hours is not None:
                    # Query with TTL filter
                    cursor.execute(
                        """SELECT * FROM product_details 
                           WHERE product_id = ? 
                           AND updated_at > datetime('now', ?)""",
                        (product_id, f'-{max_age_hours} hours')
                    )
                else:
                    # Query without TTL filter (get any cached data)
                    cursor.execute(
                        "SELECT * FROM product_details WHERE product_id = ?",
                        (product_id,)
                    )
                
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
        
        except Exception as e:
            logger.warning(f"Cache read failed for {product_id}: {e}")
            return None
    
    def _save_to_cache(self, product_id: str, product_data: Dict[str, Any]) -> None:
        """Save product details to cache.
        
        Args:
            product_id: Product identifier
            product_data: Product data from API
        """
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR REPLACE INTO product_details (
                        product_id, base_currency, quote_currency, base_min_size,
                        quote_increment, base_increment, min_market_funds, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        product_id,
                        product_data.get("base_currency_id", ""),
                        product_data.get("quote_currency_id", ""),
                        product_data.get("base_min_size", ""),
                        product_data.get("quote_increment", ""),
                        product_data.get("base_increment", ""),
                        product_data.get("min_market_funds", ""),
                        product_data.get("status", ""),
                        now_iso()
                    )
                )
                conn.commit()
                logger.debug(f"Cached product details for {product_id}")
        
        except Exception as e:
            logger.warning(f"Cache write failed for {product_id}: {e}")
    
    def _get_cache_age_seconds(self, cached_data: Dict[str, Any]) -> int:
        """Calculate age of cached data in seconds.
        
        Args:
            cached_data: Cached product data with updated_at field
            
        Returns:
            Age in seconds
        """
        try:
            updated_at = cached_data.get("updated_at")
            if not updated_at:
                return 0
            
            # Parse ISO timestamp
            cached_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            now = datetime.utcnow()
            age = (now - cached_time).total_seconds()
            return int(age)
        
        except Exception:
            return 0


# Global singleton instance
_service_instance: Optional[MarketMetadataService] = None


def get_metadata_service() -> MarketMetadataService:
    """Get or create the global metadata service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MarketMetadataService()
    return _service_instance
