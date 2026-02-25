"""Persistent product catalog with Coinbase public API refresh.

Provides:
- Startup and periodic refresh of tradeable products from Coinbase Exchange API
- DB-backed lookup for product metadata (precision, min sizes, status)
- Tradability checks without authenticated API calls
- Fallback for when brokerage metadata API returns 401
"""
import time
import threading
import httpx
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from backend.core.logging import get_logger
from backend.core.time import now_iso
from backend.db.connect import get_conn

logger = get_logger(__name__)

# DEPRECATED — unrealistically small; see docs/trading_truth_contracts.md INV-3.
# Retained for backward compatibility. New code uses preflight_engine.
GENERIC_BASE_MIN_SIZE = "0.00000001"

CATALOG_REFRESH_INTERVAL = 6 * 3600  # 6 hours
PUBLIC_API_URL = "https://api.exchange.coinbase.com/products"
REQUEST_TIMEOUT = 15.0


@dataclass
class CatalogProduct:
    """Product info from the persistent catalog."""
    product_id: str
    base_currency: str
    quote_currency: str
    base_min_size: str
    base_max_size: str
    quote_increment: str
    base_increment: str
    min_market_funds: str
    max_market_funds: str
    status: str
    trading_disabled: bool


class ProductCatalogService:
    """Persistent product catalog backed by SQLite."""

    _instance: Optional["ProductCatalogService"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._last_refresh: float = 0.0
        self._refresh_lock = threading.Lock()
        self._metadata_401_count = 0

    # ---- singleton --------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "ProductCatalogService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- public API -------------------------------------------------------
    def refresh_catalog(self) -> int:
        """Fetch full product list from Coinbase public API and store in DB.

        Returns number of products stored.
        """
        with self._refresh_lock:
            try:
                products = self._fetch_public_products()
                if not products:
                    logger.warning("Product catalog refresh returned 0 products")
                    return 0
                stored = self._store_products(products)
                self._last_refresh = time.time()
                logger.info("Product catalog refreshed: %d products stored", stored)
                return stored
            except Exception as e:
                logger.error("Product catalog refresh failed: %s", str(e)[:200])
                return 0

    def get_product(self, product_id: str) -> Optional[CatalogProduct]:
        """Look up a product from the persistent catalog."""
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM product_catalog WHERE product_id = ?",
                    (product_id,),
                )
                row = cursor.fetchone()
                if row:
                    safe_base_min = self._safe_base_min_size(
                        product_id, row["base_min_size"]
                    )
                    return CatalogProduct(
                        product_id=row["product_id"],
                        base_currency=row["base_currency"],
                        quote_currency=row["quote_currency"],
                        base_min_size=safe_base_min,
                        base_max_size=row["base_max_size"] or "1000000",
                        quote_increment=row["quote_increment"] or "0.01",
                        base_increment=row["base_increment"] or "0.00000001",
                        min_market_funds=row["min_market_funds"] or "1.00",
                        max_market_funds=row["max_market_funds"] or "1000000",
                        status=row["status"] or "online",
                        trading_disabled=bool(row["trading_disabled"]),
                    )
                return None
        except Exception as e:
            logger.warning("Catalog lookup failed for %s: %s", product_id, str(e)[:120])
            return None

    @staticmethod
    def _safe_base_min_size(product_id: str, raw_value: Optional[str]) -> str:
        """Return a safe base_min_size, preferring the DB value when it looks
        plausible, then product-specific safe defaults, then the generic crypto
        floor.  Never return a value that equals quote_increment (0.01) for
        high-value assets like BTC/ETH.
        """
        from backend.services.market_metadata import SAFE_FALLBACK_PRECISION

        if raw_value:
            try:
                v = float(raw_value)
                if v > 0:
                    return raw_value
            except (ValueError, TypeError):
                pass

        fb = SAFE_FALLBACK_PRECISION.get(product_id.upper())
        if fb and fb.get("base_min_size"):
            return fb["base_min_size"]

        return GENERIC_BASE_MIN_SIZE

    def is_tradeable(self, product_id: str) -> bool:
        """Check if a product is tradeable based on the catalog."""
        prod = self.get_product(product_id)
        if prod is None:
            return False
        return prod.status == "online" and not prod.trading_disabled

    def get_all_tradeable(self, quote: str = "USD") -> List[str]:
        """Return list of tradeable product_ids for a given quote currency."""
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT product_id FROM product_catalog "
                    "WHERE quote_currency = ? AND status = 'online' "
                    "AND trading_disabled = 0",
                    (quote,),
                )
                return [row["product_id"] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning("get_all_tradeable failed: %s", str(e)[:120])
            return []

    def needs_refresh(self) -> bool:
        """True if catalog is stale or empty."""
        if time.time() - self._last_refresh > CATALOG_REFRESH_INTERVAL:
            return True
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as cnt FROM product_catalog")
                row = cursor.fetchone()
                return (row["cnt"] if row else 0) == 0
        except Exception:
            return True

    def record_metadata_401(self) -> int:
        """Increment the 401 telemetry counter. Returns new count."""
        self._metadata_401_count += 1
        count = self._metadata_401_count
        if count <= 3 or count % 10 == 0:
            logger.warning(
                "coinbase_metadata_401 count=%d — "
                "Coinbase brokerage metadata auth may be misconfigured. "
                "Check API key scopes (requires 'view' permission on Advanced Trade).",
                count,
            )
        return count

    @property
    def metadata_401_count(self) -> int:
        return self._metadata_401_count

    # ---- internals --------------------------------------------------------
    def _fetch_public_products(self) -> List[Dict[str, Any]]:
        """Fetch products from the Coinbase Exchange public API (no auth)."""
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.get(PUBLIC_API_URL)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error("Failed to fetch public products: %s", str(e)[:200])
            return []

    def _store_products(self, products: List[Dict[str, Any]]) -> int:
        """Upsert products into the catalog table."""
        stored = 0
        ts = now_iso()
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                for p in products:
                    pid = p.get("id") or p.get("product_id")
                    if not pid:
                        continue
                    cursor.execute(
                        """INSERT OR REPLACE INTO product_catalog
                           (product_id, base_currency, quote_currency,
                            base_min_size, base_max_size, quote_increment,
                            base_increment, min_market_funds, max_market_funds,
                            status, trading_disabled, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            pid,
                            p.get("base_currency", ""),
                            p.get("quote_currency", ""),
                            p.get("base_min_size", ""),
                            p.get("base_max_size", ""),
                            p.get("quote_increment", ""),
                            p.get("base_increment", ""),
                            p.get("min_market_funds", ""),
                            p.get("max_market_funds", ""),
                            p.get("status", "online"),
                            1 if p.get("trading_disabled", False) else 0,
                            ts,
                        ),
                    )
                    stored += 1
                conn.commit()
        except Exception as e:
            logger.error("Failed to store products: %s", str(e)[:200])
        return stored


def get_product_catalog() -> ProductCatalogService:
    """Get the global ProductCatalogService singleton."""
    return ProductCatalogService.get_instance()
