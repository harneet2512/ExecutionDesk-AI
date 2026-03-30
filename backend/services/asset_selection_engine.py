"""Asset Selection Engine for natural-language asset screening.

Selects the best asset based on user criteria like:
- "highest performing crypto in the last 10 minutes"
- "best return in the last 24h"
- "top gainer this week"

Integrates with Coinbase market data for live price feeds.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from backend.core.logging import get_logger
from backend.services.coinbase_market_data import list_products

logger = get_logger(__name__)


class NoMarketDataError(Exception):
    """Raised when no candle data is available to compute top performer."""
    pass


class NoTradeableAssetError(Exception):
    """Raised when no tradable asset can be found for the given criteria."""
    pass


def get_tradeable_product_ids() -> set:
    """Return the set of product_ids that are tradeable on Coinbase (status=online, quote=USD).

    This is the authoritative tradability gate. Any asset selected for a LIVE trade
    MUST appear in this set.
    """
    try:
        products = list_products(quote="USD")
        return {p["product_id"] for p in products if p.get("product_id")}
    except Exception as e:
        logger.warning("Failed to fetch tradeable products: %s", str(e)[:200])
        return set()


def verify_product_tradeable(product_id: str) -> bool:
    """Check whether a specific product_id is tradeable on Coinbase.

    Uses the Exchange API product listing (status=online) as the source of truth.
    Also attempts a broker metadata probe, but treats it as non-blocking when the API
    returns auth errors (401) — these don't indicate the product is untradeable, just
    that the metadata service has authentication issues.
    """
    # Level 1: Exchange listing (authoritative)
    tradeable = get_tradeable_product_ids()
    if product_id not in tradeable:
        logger.info("TRADABILITY_FAIL: %s not in exchange product list", product_id)
        return False

    # Level 2: Broker metadata probe (best-effort, non-blocking on auth errors)
    try:
        from backend.services.market_metadata import get_metadata_service
        svc = get_metadata_service()
        result = svc.get_product_details_sync(product_id, allow_stale=True)
        if result.success:
            logger.info("TRADABILITY_PASS: %s verified via broker metadata", product_id)
            return True
        elif result.error_message and "401" in str(result.error_message):
            # Auth error — the product IS listed on the exchange, but we can't fetch
            # metadata due to API key issues. This doesn't mean it's untradeable.
            # Allow it through but log a warning.
            logger.info(
                "TRADABILITY_PASS_EXCHANGE_ONLY: %s listed on exchange (broker metadata 401, allowing)",
                product_id
            )
            return True
        else:
            logger.warning(
                "TRADABILITY_FAIL_L2: %s broker metadata error: %s",
                product_id, result.error_message
            )
            return False
    except Exception as e:
        # If we can't check broker metadata, trust the exchange listing
        logger.warning(
            "TRADABILITY_PASS_EXCHANGE_ONLY: %s broker check exception (allowing): %s",
            product_id, str(e)[:200]
        )
        return True

# Major crypto assets (top by market cap)
MAJOR_CRYPTOS = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", 
    "DOT", "LINK", "MATIC", "ATOM", "LTC", "UNI", "BCH"
}

# Stablecoins to exclude from selection
STABLECOINS = {
    "USDC", "USDT", "DAI", "BUSD", "TUSD", "USDP", "GUSD", "FRAX", "USDD"
}


@dataclass
class SelectionResult:
    """Result of asset selection."""
    selected_symbol: str
    selected_return_pct: float
    top_candidates: List[Dict[str, Any]]  # Top 3 with metrics
    universe_description: str
    window_description: str
    why_explanation: str
    fallback_used: bool = False
    lookback_hours: float = 24.0
    universe_size: int = 0
    evaluated_count: int = 0
    # Enterprise fields
    data_coverage_pct: float = 0.0  # % of candidates with valid data
    ranking_confidence: float = 0.0  # Confidence in selection (gap between 1st and 2nd)
    exclusions_count: int = 0
    exclusion_reasons: List[str] = field(default_factory=list)
    time_window: Optional[Dict[str, Any]] = None  # Structured TimeWindow


@dataclass 
class CandidateMetrics:
    """Metrics for a candidate asset."""
    symbol: str
    product_id: str
    return_pct: float
    first_price: float
    last_price: float
    candle_count: int
    volume_24h: Optional[float] = None
    

def _humanize_window(hours: float) -> str:
    """Convert hours to human-readable window description."""
    if hours < 1:
        minutes = int(hours * 60)
        return f"last {minutes} minute{'s' if minutes != 1 else ''}"
    elif hours == 1:
        return "last hour"
    elif hours < 24:
        h = int(hours)
        return f"last {h} hour{'s' if h != 1 else ''}"
    elif hours == 24:
        return "last 24 hours"
    elif hours < 168:
        days = int(hours / 24)
        return f"last {days} day{'s' if days != 1 else ''}"
    elif hours == 168:
        return "last week"
    else:
        weeks = int(hours / 168)
        return f"last {weeks} week{'s' if weeks != 1 else ''}"


def _get_granularity(lookback_hours: float) -> str:
    """Determine optimal granularity based on lookback window."""
    if lookback_hours <= 1:
        return "ONE_MINUTE"
    elif lookback_hours <= 6:
        return "FIVE_MINUTE" 
    elif lookback_hours <= 24:
        return "FIFTEEN_MINUTE"
    elif lookback_hours <= 168:  # 1 week
        return "ONE_HOUR"
    else:
        return "SIX_HOUR"


async def _fetch_candles_async(
    product_id: str, 
    lookback_hours: float,
    granularity: str = "ONE_HOUR"
) -> List[Dict[str, Any]]:
    """Fetch candles for a product asynchronously."""
    try:
        import httpx
        from backend.providers.coinbase_market_data import CoinbaseMarketDataProvider
        
        public_url = CoinbaseMarketDataProvider.PUBLIC_URL
        
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=lookback_hours)
        
        # Map granularity to Coinbase API format (seconds)
        granularity_map = {
            "ONE_MINUTE": 60,
            "FIVE_MINUTE": 300,
            "FIFTEEN_MINUTE": 900,
            "ONE_HOUR": 3600,
            "SIX_HOUR": 21600,
            "ONE_DAY": 86400
        }
        gran_seconds = granularity_map.get(granularity, 3600)
        
        url = f"{public_url}/products/{product_id}/candles"
        params = {
            "granularity": gran_seconds,
            "start": start_time.isoformat(),
            "end": end_time.isoformat()
        }
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        
        # Coinbase returns: [timestamp, low, high, open, close, volume]
        candles = []
        for candle in data:
            if len(candle) >= 5:
                candles.append({
                    "timestamp": int(candle[0]),
                    "open": float(candle[3]),
                    "high": float(candle[2]),
                    "low": float(candle[1]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]) if len(candle) >= 6 else 0.0,
                })
        
        # Sort by timestamp ascending (oldest first)
        candles.sort(key=lambda x: x["timestamp"])
        return candles
        
    except Exception as e:
        logger.debug(f"Failed to fetch candles for {product_id}: {e}")
        return []


def _compute_return(candles: List[Dict[str, Any]]) -> float:
    """Compute percent return from candles."""
    if len(candles) < 2:
        return 0.0
    
    first_open = candles[0]["open"]
    last_close = candles[-1]["close"]
    
    if first_open <= 0:
        return 0.0
    
    return ((last_close - first_open) / first_open) * 100


async def select_asset(
    criteria: str,
    lookback_hours: float = 24.0,
    notional_usd: float = 10.0,
    universe_constraint: str = "top_25_volume",
    threshold_pct: Optional[float] = None,
    asset_class: str = "CRYPTO"
) -> SelectionResult:
    """
    Select the best asset based on selection criteria.
    
    Args:
        criteria: Selection criteria (e.g., "highest performing", "best return")
        lookback_hours: Lookback window in hours (supports fractional for minutes)
        notional_usd: Order size in USD
        universe_constraint: One of "top_25_volume", "majors_only", "all"
        threshold_pct: Optional threshold filter (e.g., "up 20%" -> 20.0)
        asset_class: "CRYPTO" or "STOCK"
    
    Returns:
        SelectionResult with selected asset and metrics
    """
    try:
        # 1. Get tradeable products
        products = list_products(quote="USD")
        
        if not products:
            logger.warning("No products returned from list_products")
            return _fallback_selection(lookback_hours, universe_constraint)
        
        # 2. Filter by constraint
        if universe_constraint == "majors_only":
            products = [
                p for p in products 
                if p.get("base_currency_id", "").upper() in MAJOR_CRYPTOS
            ]
            universe_desc = "major cryptocurrencies"
        elif universe_constraint == "exclude_stablecoins":
            products = [
                p for p in products 
                if p.get("base_currency_id", "").upper() not in STABLECOINS
            ]
            universe_desc = "cryptocurrencies (excluding stablecoins)"
        else:
            # Filter stablecoins and tokens with empty base_currency_id
            filtered = [
                p for p in products
                if p.get("base_currency_id", "").upper() not in STABLECOINS
                and p.get("base_currency_id", "")
            ]
            # Sort by 24h volume descending if the field is available; else keep API order.
            # This surfaces liquid major assets (BTC, ETH, SOL) and pushes obscure
            # low-liquidity tokens (leveraged tokens, test tokens) to the bottom.
            filtered.sort(
                key=lambda p: float(
                    p.get("volume_24h", 0) or p.get("quote_volume_24h", 0) or 0
                ),
                reverse=True,
            )
            products = filtered[:25]
            universe_desc = "top 25 cryptocurrencies by 24h volume"
        
        if not products:
            logger.warning("No products after filtering")
            return _fallback_selection(lookback_hours, universe_constraint)
        
        universe_size = len(products)
        
        # 3. Determine granularity based on lookback
        granularity = _get_granularity(lookback_hours)
        
        # 4. Fetch candles and compute metrics for all products in parallel
        async def get_metrics(product: Dict) -> Optional[CandidateMetrics]:
            product_id = product.get("product_id", "")
            if not product_id:
                return None
                
            candles = await _fetch_candles_async(product_id, lookback_hours, granularity)

            if len(candles) < 2:
                return None

            # Require minimum average volume to exclude synthetic/illiquid tokens
            avg_volume = sum(c.get("volume", 0) for c in candles) / len(candles)
            if avg_volume <= 0:
                return None  # skip tokens with no trading volume

            return_pct = _compute_return(candles)
            
            # Apply threshold filter if specified
            if threshold_pct is not None:
                if criteria in ("highest performing", "best return", "momentum", "rising"):
                    if return_pct < threshold_pct:
                        return None
                elif criteria in ("lowest performing", "worst return", "falling"):
                    if return_pct > -threshold_pct:
                        return None
            
            return CandidateMetrics(
                symbol=product.get("base_currency_id", ""),
                product_id=product_id,
                return_pct=return_pct,
                first_price=candles[0]["open"],
                last_price=candles[-1]["close"],
                candle_count=len(candles)
            )
        
        # Run parallel fetches with semaphore to limit concurrency
        semaphore = asyncio.Semaphore(10)
        
        async def limited_get_metrics(product: Dict) -> Optional[CandidateMetrics]:
            async with semaphore:
                return await get_metrics(product)
        
        tasks = [limited_get_metrics(p) for p in products]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter valid results and track exclusions
        rankings: List[CandidateMetrics] = []
        exclusions_count = 0
        exclusion_reasons: List[str] = []
        
        for r in results:
            if isinstance(r, CandidateMetrics):
                rankings.append(r)
            elif isinstance(r, Exception):
                exclusions_count += 1
                exclusion_reasons.append(f"fetch_error: {str(r)[:50]}")
            elif r is None:
                exclusions_count += 1
                exclusion_reasons.append("insufficient_candles")
        
        # Calculate data coverage
        data_coverage_pct = (len(rankings) / universe_size * 100) if universe_size > 0 else 0.0
        
        if not rankings:
            logger.warning("No valid rankings after fetching candles for %d products", universe_size)
            raise NoMarketDataError(
                f"Unable to compute top performer for {_humanize_window(lookback_hours)} "
                f"(no candle data available for {universe_size} candidates). "
                f"Exclusions: {exclusions_count}."
            )
        
        # 5. Sort and select
        # Default: highest return first (for "highest performing", "best return", etc.)
        if criteria in ("lowest performing", "worst return", "falling"):
            rankings.sort(key=lambda x: x.return_pct)
        else:
            rankings.sort(key=lambda x: x.return_pct, reverse=True)
        
        # ── TRADABILITY GATE ──
        # Verify the top-ranked asset is actually tradeable on Coinbase.
        # Uses two-level check: (1) exchange listing AND (2) broker metadata.
        # If it fails, walk down the rankings until we find one that passes both.
        selected = None
        skipped_non_tradeable = []
        for candidate in rankings:
            if verify_product_tradeable(candidate.product_id):
                selected = candidate
                break
            else:
                skipped_non_tradeable.append(candidate.symbol)
                logger.warning(
                    "TRADABILITY_SKIP: %s (%s) failed tradability check, trying next",
                    candidate.symbol, candidate.product_id
                )

        if not selected:
            raise NoTradeableAssetError(
                f"None of the top {len(rankings)} performers are tradeable on Coinbase. "
                f"Skipped: {', '.join(skipped_non_tradeable[:5])}. "
                f"Try a different timeframe or universe."
            )

        if skipped_non_tradeable:
            logger.info(
                "TRADABILITY_FALLBACK: Skipped %d non-tradeable assets, selected %s instead",
                len(skipped_non_tradeable), selected.symbol
            )
        
        # Calculate ranking confidence (gap between 1st and 2nd place)
        ranking_confidence = 1.0
        # Confidence: gap between selected and next candidate (any, not just tradeable)
        selected_idx = rankings.index(selected) if selected in rankings else 0
        other_candidates = [r for r in rankings if r != selected]
        if other_candidates:
            gap = abs(selected.return_pct - other_candidates[0].return_pct)
            # Higher gap = higher confidence (normalize to 0-1 scale)
            ranking_confidence = min(1.0, gap / 10.0)  # 10% gap = max confidence
        
        # 6. Build top candidates list (top 3)
        top_candidates = []
        for r in rankings[:3]:
            top_candidates.append({
                "symbol": r.symbol,
                "product_id": r.product_id,
                "return_pct": round(r.return_pct, 2),
                "first_price": r.first_price,
                "last_price": r.last_price,
            })
        
        # 7. Generate explanation
        window_desc = _humanize_window(lookback_hours)
        direction = "up" if selected.return_pct >= 0 else "down"
        
        why_explanation = (
            f"{selected.symbol} was selected as the top performer from {len(rankings)} assets "
            f"in the {window_desc}. It returned {abs(selected.return_pct):.2f}% ({direction}), "
            f"moving from ${selected.first_price:,.4f} to ${selected.last_price:,.4f}."
        )
        
        if len(rankings) >= 2:
            runner_up = rankings[1]
            why_explanation += (
                f" Runner-up: {runner_up.symbol} at {runner_up.return_pct:+.2f}%."
            )
        
        result = SelectionResult(
            selected_symbol=selected.symbol,
            selected_return_pct=round(selected.return_pct, 2),
            top_candidates=top_candidates,
            universe_description=universe_desc,
            window_description=window_desc,
            why_explanation=why_explanation,
            fallback_used=False,
            lookback_hours=lookback_hours,
            universe_size=universe_size,
            evaluated_count=len(rankings),
            data_coverage_pct=round(data_coverage_pct, 1),
            ranking_confidence=round(ranking_confidence, 2),
            exclusions_count=exclusions_count,
            exclusion_reasons=exclusion_reasons[:5],
        )
        
        # Emit eval metrics
        _emit_selection_eval(result, universe_size)
        
        return result
        
    except (NoMarketDataError, NoTradeableAssetError):
        # Let these propagate — they are deterministic refusals, not transient errors
        raise
    except Exception as e:
        logger.error(f"Asset selection failed: {e}")
        return _fallback_selection(lookback_hours, universe_constraint)


def _fallback_selection(lookback_hours: float, universe_constraint: str) -> SelectionResult:
    """Return fallback selection when actual selection fails."""
    window_desc = _humanize_window(lookback_hours)
    
    return SelectionResult(
        selected_symbol="BTC",
        selected_return_pct=0.0,
        top_candidates=[{
            "symbol": "BTC",
            "product_id": "BTC-USD",
            "return_pct": 0.0,
            "first_price": 0.0,
            "last_price": 0.0,
        }],
        universe_description="fallback (market data unavailable)",
        window_description=window_desc,
        why_explanation=(
            f"Unable to fetch live market data for the {window_desc}. "
            f"Defaulting to BTC as a fallback. Please verify market conditions."
        ),
        fallback_used=True,
        lookback_hours=lookback_hours,
        universe_size=0,
        evaluated_count=0
    )


def _emit_selection_eval(result: SelectionResult, universe_size: int) -> None:
    """Emit eval metrics for asset selection."""
    try:
        from backend.evals.runtime_evals import emit_runtime_metric
        
        emit_runtime_metric("asset_selection", {
            "selected_symbol": result.selected_symbol,
            "selected_return_pct": result.selected_return_pct,
            "universe_size": universe_size,
            "evaluated_count": result.evaluated_count,
            "data_coverage_pct": result.data_coverage_pct,
            "ranking_confidence": result.ranking_confidence,
            "fallback_used": result.fallback_used,
            "exclusions_count": result.exclusions_count,
            "lookback_hours": result.lookback_hours,
        })
        
        if result.fallback_used:
            emit_runtime_metric("asset_selection_fallback", {
                "reason": "no_valid_candidates",
                "universe_size": universe_size,
                "exclusion_reasons": result.exclusion_reasons,
            })
            
    except Exception as e:
        logger.debug(f"Failed to emit selection eval: {e}")


def selection_result_to_dict(result: SelectionResult) -> Dict[str, Any]:
    """Convert SelectionResult to serializable dict."""
    return {
        "selected_symbol": result.selected_symbol,
        "selected_return_pct": result.selected_return_pct,
        "top_candidates": result.top_candidates,
        "universe_description": result.universe_description,
        "window_description": result.window_description,
        "why_explanation": result.why_explanation,
        "fallback_used": result.fallback_used,
        "lookback_hours": result.lookback_hours,
        "universe_size": result.universe_size,
        "evaluated_count": result.evaluated_count,
        "data_coverage_pct": result.data_coverage_pct,
        "ranking_confidence": result.ranking_confidence,
        "exclusions_count": result.exclusions_count,
        "exclusion_reasons": result.exclusion_reasons,
        "time_window": result.time_window,
    }
