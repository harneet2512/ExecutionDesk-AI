"""Deterministic asset resolver for trade planning, preflight, quotes, and execution.

Single source of truth for mapping user-supplied symbols to executable
Coinbase product_ids using executable balances and product tradability.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
import warnings

from backend.core.logging import get_logger
from backend.services.executable_state import ExecutableState

logger = get_logger(__name__)


RESOLUTION_OK = "OK"
RESOLUTION_NOT_HELD = "NOT_HELD"
RESOLUTION_QTY_MISSING = "QTY_MISSING"  # Deprecated backward-compat alias
RESOLUTION_QTY_ZERO = "QTY_ZERO"
RESOLUTION_FUNDS_ON_HOLD = "FUNDS_ON_HOLD"
RESOLUTION_NO_PRODUCT = "NO_PRODUCT"
RESOLUTION_NOT_TRADABLE = "NOT_TRADABLE"
RESOLUTION_LIMIT_ONLY = "LIMIT_ONLY"

USER_MESSAGES = {
    RESOLUTION_NOT_HELD: "{symbol} is not held in your executable balances.",
    RESOLUTION_QTY_MISSING: "Available quantity is 0 for {symbol}.",
    RESOLUTION_QTY_ZERO: "Available quantity is 0 for {symbol}.",
    RESOLUTION_FUNDS_ON_HOLD: "{symbol} funds are on hold and not currently executable.",
    RESOLUTION_NO_PRODUCT: "No tradable product found for {symbol} on the exchange.",
    RESOLUTION_NOT_TRADABLE: "{symbol} is not currently tradable (trading is disabled or market is cancel-only).",
    RESOLUTION_LIMIT_ONLY: "{symbol} is currently limit-only; market orders are unavailable.",
}


@dataclass
class AssetResolution:
    """Resolution result for a single user-supplied symbol."""
    symbol: str
    found_in_snapshot: bool
    snapshot_qty: Optional[float]
    executable_qty: Optional[float]
    hold_qty: Optional[float]
    product_id: Optional[str]
    base_asset: str
    quote_asset: str
    product_flags: Dict[str, bool]
    resolution_status: str
    user_message_if_blocked: str

    @property
    def is_ok(self) -> bool:
        return self.resolution_status == RESOLUTION_OK

    @property
    def is_blocked(self) -> bool:
        return self.resolution_status != RESOLUTION_OK


def _normalize_symbol(raw: str) -> str:
    s = raw.strip().upper()
    if s.endswith("-USD"):
        s = s[:-4]
    elif s.endswith("-USDC"):
        s = s[:-5]
    return s.strip()


def _build_holdings_map(positions: Dict[str, Any]) -> Dict[str, float]:
    """Build a normalized-symbol -> qty map from snapshot positions."""
    holdings: Dict[str, float] = {}
    for key, qty in positions.items():
        norm = _normalize_symbol(key)
        qty_f = float(qty or 0.0)
        holdings[norm] = holdings.get(norm, 0.0) + qty_f
    return holdings


def _default_flags() -> Dict[str, bool]:
    return {
        "is_disabled": False,
        "trading_disabled": False,
        "limit_only": False,
        "cancel_only": False,
    }


def _is_cash_currency(symbol: str) -> bool:
    return symbol in {"USD", "USDC", "USDT", "DAI", "BUSD"}


def _extract_product_flags(product: Dict[str, Any]) -> Dict[str, bool]:
    flags = _default_flags()
    if not isinstance(product, dict):
        return flags
    for k in flags:
        flags[k] = bool(product.get(k, False))
    return flags


def _product_status(flags: Dict[str, bool]) -> Optional[str]:
    if flags.get("is_disabled") or flags.get("trading_disabled") or flags.get("cancel_only"):
        return RESOLUTION_NOT_TRADABLE
    if flags.get("limit_only"):
        return RESOLUTION_LIMIT_ONLY
    return None


def _lookup_product(symbol: str, product_catalog: Dict[str, Dict[str, Any]]) -> Tuple[Optional[str], str, Dict[str, bool]]:
    usd_pid = f"{symbol}-USD"
    usdc_pid = f"{symbol}-USDC"
    if usd_pid in product_catalog:
        p = product_catalog.get(usd_pid) or {}
        return usd_pid, "USD", _extract_product_flags(p)
    if usdc_pid in product_catalog:
        p = product_catalog.get(usdc_pid) or {}
        return usdc_pid, "USDC", _extract_product_flags(p)
    return None, "USD", _default_flags()


def resolve_from_executable_state(
    symbol: str,
    executable_state: ExecutableState,
    product_catalog: Dict[str, Dict[str, Any]],
) -> AssetResolution:
    """Resolve a single symbol from executable balances plus product catalog."""
    norm = _normalize_symbol(symbol)
    bal = (executable_state.balances or {}).get(norm)
    executable_qty = float(getattr(bal, "available_qty", 0.0) or 0.0) if bal else 0.0
    hold_qty = float(getattr(bal, "hold_qty", 0.0) or 0.0) if bal else 0.0
    found_in_state = bal is not None

    product_id, quote_asset, flags = _lookup_product(norm, product_catalog or {})
    if not found_in_state:
        status = RESOLUTION_NOT_HELD
    elif product_id is None:
        status = RESOLUTION_NO_PRODUCT
    else:
        product_block = _product_status(flags)
        if product_block:
            status = product_block
        elif executable_qty <= 0 and hold_qty > 0:
            status = RESOLUTION_FUNDS_ON_HOLD
        elif executable_qty <= 0:
            status = RESOLUTION_QTY_ZERO
        else:
            status = RESOLUTION_OK

    msg = USER_MESSAGES.get(status, "").format(symbol=norm) if status != RESOLUTION_OK else ""
    return AssetResolution(
        symbol=norm,
        found_in_snapshot=found_in_state,
        snapshot_qty=executable_qty if found_in_state else None,
        executable_qty=executable_qty if found_in_state else None,
        hold_qty=hold_qty if found_in_state else None,
        product_id=product_id,
        base_asset=norm,
        quote_asset=quote_asset,
        product_flags=flags,
        resolution_status=status,
        user_message_if_blocked=msg,
    )


def resolve_all_holdings(
    executable_state: ExecutableState,
    product_catalog: Dict[str, Dict[str, Any]],
) -> Tuple[List[AssetResolution], List[AssetResolution]]:
    """Resolve all non-cash currencies and split tradable vs skipped."""
    tradable: List[AssetResolution] = []
    skipped: List[AssetResolution] = []
    for symbol in sorted((executable_state.balances or {}).keys()):
        if _is_cash_currency(symbol):
            continue
        r = resolve_from_executable_state(symbol, executable_state, product_catalog)
        if r.resolution_status == RESOLUTION_OK and (r.executable_qty or 0.0) > 0:
            tradable.append(r)
        else:
            skipped.append(r)
    return tradable, skipped


def resolve_assets(
    user_symbols: List[str],
    positions: Dict[str, Any],
    catalog_check: Optional[Any] = None,
) -> List[AssetResolution]:
    """Deprecated legacy resolver retained for test/backward compatibility.

    Resolve a list of user-supplied symbols to executable product_ids.

    Parameters
    ----------
    user_symbols : list of raw symbol strings (e.g. ["MOODENG", "MORPHO"])
    positions : dict from latest portfolio snapshot (symbol -> qty)
    catalog_check : callable(product_id) -> bool, or ProductCatalogService instance.
                    If None, falls back to import-time catalog lookup.

    Resolution algorithm (legacy compatibility):
      1. Snapshot-first check normalized holdings map
      2. Product resolution with tradeable checker (<SYM>-USD then <SYM>-USDC)
      3. Status determination
    """
    warnings.warn(
        "resolve_assets() is deprecated; use resolve_from_executable_state() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    holdings = _build_holdings_map(positions or {})

    is_tradeable = _get_tradeable_checker(catalog_check)

    results: List[AssetResolution] = []
    for raw in user_symbols:
        norm = _normalize_symbol(raw)
        results.append(_resolve_single(norm, holdings, is_tradeable))
    return results


def _get_tradeable_checker(catalog_check: Any):
    """Return a callable(product_id) -> bool."""
    if callable(catalog_check):
        return catalog_check
    if catalog_check is not None and hasattr(catalog_check, "is_tradeable"):
        return catalog_check.is_tradeable
    def _default_check(product_id: str) -> bool:
        try:
            from backend.services.product_catalog import get_product_catalog
            return get_product_catalog().is_tradeable(product_id)
        except Exception:
            return False
    return _default_check


def _resolve_single(
    symbol: str,
    holdings: Dict[str, float],
    is_tradeable,
) -> AssetResolution:
    found_in_snapshot = symbol in holdings
    snapshot_qty: Optional[float] = holdings.get(symbol)
    if snapshot_qty is not None and snapshot_qty <= 0:
        snapshot_qty = None
        found_in_snapshot = False

    product_id: Optional[str] = None
    quote_asset = "USD"

    usd_pid = f"{symbol}-USD"
    usdc_pid = f"{symbol}-USDC"
    try:
        if is_tradeable(usd_pid):
            product_id = usd_pid
            quote_asset = "USD"
        elif is_tradeable(usdc_pid):
            product_id = usdc_pid
            quote_asset = "USDC"
    except Exception as exc:
        logger.debug("Catalog lookup failed for %s: %s", symbol, str(exc)[:120])

    status = _determine_status(found_in_snapshot, snapshot_qty, product_id)
    msg = USER_MESSAGES.get(status, "").format(symbol=symbol) if status != RESOLUTION_OK else ""

    return AssetResolution(
        symbol=symbol,
        found_in_snapshot=found_in_snapshot,
        snapshot_qty=snapshot_qty,
        executable_qty=snapshot_qty,
        hold_qty=0.0 if snapshot_qty is not None else None,
        product_id=product_id,
        base_asset=symbol,
        quote_asset=quote_asset,
        product_flags=_default_flags(),
        resolution_status=status,
        user_message_if_blocked=msg,
    )


def _determine_status(
    found_in_snapshot: bool,
    snapshot_qty: Optional[float],
    product_id: Optional[str],
) -> str:
    if product_id is None:
        return RESOLUTION_NO_PRODUCT
    if not found_in_snapshot:
        return RESOLUTION_NOT_HELD
    if snapshot_qty is None or snapshot_qty <= 0:
        return RESOLUTION_QTY_ZERO
    return RESOLUTION_OK


resolve_asset = resolve_from_executable_state
