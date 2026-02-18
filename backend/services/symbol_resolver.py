"""Dynamic symbol resolver for the trade parser.

Resolves arbitrary user-provided asset names/symbols to valid product_ids
using a multi-source resolution chain:
1. Hardcoded symbol map (existing CRYPTO_SYMBOLS / STOCK_SYMBOLS)
2. Portfolio holdings (assets the user currently owns)
3. Recent order history (assets recently traded by the platform)
4. Persistent product catalog (all Coinbase-tradeable products)
"""
from typing import Optional
from dataclasses import dataclass

from backend.core.logging import get_logger
from backend.db.connect import get_conn

logger = get_logger(__name__)


@dataclass
class ResolvedSymbol:
    """Result of dynamic symbol resolution."""
    product_id: str          # e.g. "MORPHO-USD"
    base_symbol: str         # e.g. "MORPHO"
    source: str              # "hardcoded", "portfolio", "order_history", "catalog"
    confidence: float        # 0.0-1.0


def canonicalize(raw: str) -> str:
    """Normalise user input into a standard uppercase symbol.

    Handles:  "MORPHO", "morpho-usd", "MORPHO USD", "morpho usd" -> "MORPHO"
    """
    s = raw.strip().upper()
    # Strip trailing -USD / USD
    if s.endswith("-USD"):
        s = s[:-4]
    elif s.endswith(" USD"):
        s = s[:-4]
    elif s.endswith("USD") and len(s) > 3:
        s = s[:-3]
    return s.strip()


def resolve(raw: str, tenant_id: str = "default") -> Optional[ResolvedSymbol]:
    """Resolve a raw user-supplied symbol to a valid product_id.

    Resolution chain (returns on first hit):
      1. Hardcoded symbol dictionaries (CRYPTO_SYMBOLS, STOCK_SYMBOLS)
      2. Portfolio holdings (from latest portfolio_snapshots)
      3. Recent BUY orders (from orders table)
      4. Persistent product catalog (from product_catalog table)
    """
    from backend.agents.trade_parser import CRYPTO_SYMBOLS, STOCK_SYMBOLS

    raw_lower = raw.lower().strip()
    canon = canonicalize(raw)

    # 1. Hardcoded maps
    if raw_lower in CRYPTO_SYMBOLS:
        sym = CRYPTO_SYMBOLS[raw_lower]
        return ResolvedSymbol(f"{sym}-USD", sym, "hardcoded", 1.0)
    if raw_lower in STOCK_SYMBOLS:
        sym = STOCK_SYMBOLS[raw_lower]
        return ResolvedSymbol(sym, sym, "hardcoded", 1.0)
    # Also check the canonical form against keys
    if canon.lower() in CRYPTO_SYMBOLS:
        sym = CRYPTO_SYMBOLS[canon.lower()]
        return ResolvedSymbol(f"{sym}-USD", sym, "hardcoded", 1.0)

    # 2. Portfolio holdings
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT positions_json FROM portfolio_snapshots
                   WHERE tenant_id = ? ORDER BY ts DESC LIMIT 1""",
                (tenant_id,),
            )
            row = cursor.fetchone()
            if row and row["positions_json"]:
                import json
                positions = json.loads(row["positions_json"]) if isinstance(row["positions_json"], str) else row["positions_json"]
                # positions is a dict like {"BTC-USD": 0.0001, "MORPHO-USD": 5.3}
                for pid in positions:
                    base = pid.replace("-USD", "").upper()
                    if base == canon:
                        return ResolvedSymbol(pid, base, "portfolio", 0.9)
    except Exception as e:
        logger.debug("Portfolio resolution failed: %s", str(e)[:120])

    # 3. Recent order history
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT symbol FROM orders
                   WHERE tenant_id = ?
                   ORDER BY created_at DESC LIMIT 50""",
                (tenant_id,),
            )
            for orow in cursor.fetchall():
                sym = (orow["symbol"] or "").upper()
                base = sym.replace("-USD", "")
                if base == canon:
                    return ResolvedSymbol(sym if "-" in sym else f"{sym}-USD", base, "order_history", 0.85)
    except Exception as e:
        logger.debug("Order history resolution failed: %s", str(e)[:120])

    # 4. Product catalog
    try:
        from backend.services.product_catalog import get_product_catalog
        catalog = get_product_catalog()
        product_id = f"{canon}-USD"
        if catalog.is_tradeable(product_id):
            return ResolvedSymbol(product_id, canon, "catalog", 0.8)
        # Also try exact match without -USD (for stocks)
        prod = catalog.get_product(canon)
        if prod:
            return ResolvedSymbol(canon, canon, "catalog", 0.8)
    except Exception as e:
        logger.debug("Catalog resolution failed: %s", str(e)[:120])

    return None


def get_last_purchase(tenant_id: str = "default") -> Optional[ResolvedSymbol]:
    """Find the most recent BUY order placed by the platform for this tenant.

    Used by "sell last purchase" command.
    """
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT symbol, created_at FROM orders
                   WHERE tenant_id = ? AND side = 'BUY'
                   ORDER BY created_at DESC LIMIT 1""",
                (tenant_id,),
            )
            row = cursor.fetchone()
            if row and row["symbol"]:
                sym = row["symbol"].upper()
                base = sym.replace("-USD", "")
                return ResolvedSymbol(sym if "-" in sym else f"{sym}-USD", base, "last_purchase", 1.0)
    except Exception as e:
        logger.warning("get_last_purchase failed: %s", str(e)[:120])
    return None
