"""Hybrid pre-confirm financial insight service.

Generates a deterministic fact pack + template insight, optionally
enhanced by LLM for the 'why_it_matters' field with a 2s timeout.

Result is always a valid InsightSchema - template fallback guarantees
the confirm action is never blocked by insight failure.
"""
import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from typing import Literal

from backend.core.logging import get_logger
from backend.db.connect import get_conn

logger = get_logger(__name__)

# LLM availability check (lazy, cached)
_llm_available: Optional[bool] = None

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class InsightSchema(BaseModel):
    headline: str
    why_it_matters: str
    key_facts: List[str]
    risk_flags: List[str]
    confidence: float = Field(ge=0.0, le=1.0)
    sources: dict
    generated_by: Literal["template", "llm", "hybrid"]
    request_id: str


# ---------------------------------------------------------------------------
# In-memory TTL cache (60s)
# ---------------------------------------------------------------------------

_insight_cache: Dict[str, Tuple[dict, float]] = {}
CACHE_TTL = 60


def _cache_key(symbol: str, side: str, notional_usd: float, mode: str, news_enabled: bool) -> str:
    notional_bucket = round(notional_usd, -1) if notional_usd >= 10 else round(notional_usd, 0)
    return f"{symbol}:{side}:{notional_bucket}:{mode}:{news_enabled}"


def _cache_get(key: str) -> Optional[dict]:
    if key in _insight_cache:
        data, ts = _insight_cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
        del _insight_cache[key]
    return None


def _cache_set(key: str, data: dict) -> None:
    _insight_cache[key] = (data, time.time())
    # Evict old entries to prevent memory leak
    now = time.time()
    stale = [k for k, (_, t) in _insight_cache.items() if now - t > CACHE_TTL * 3]
    for k in stale:
        _insight_cache.pop(k, None)


# ---------------------------------------------------------------------------
# Candles fallback (Coinbase public API)
# ---------------------------------------------------------------------------

async def _fetch_candles_fallback(symbol: str) -> List[dict]:
    """Fetch candles from Coinbase public API as fallback when DB is empty.
    
    Returns list of candle dicts with keys: close, high, low, start_time.
    """
    try:
        from backend.core.symbols import to_product_id
        import httpx
        
        product_id = to_product_id(symbol)
        
        # Fetch 7 days of hourly candles (168 candles)
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=7)
        
        url = f"https://api.exchange.coinbase.com/products/{product_id}/candles"
        params = {
            "granularity": 3600,  # 1 hour
            "start": start_time.isoformat(),
            "end": end_time.isoformat()
        }
        
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        
        # Coinbase returns: [timestamp, low, high, open, close, volume]
        candles = []
        for candle in data:
            if len(candle) >= 5:
                ts_val = int(candle[0])
                candles.append({
                    "close": float(candle[4]),
                    "open": float(candle[3]),
                    "high": float(candle[2]),
                    "low": float(candle[1]),
                    "volume": float(candle[5]) if len(candle) >= 6 else 0.0,
                    "start_time": datetime.utcfromtimestamp(ts_val).isoformat() + "Z",
                    "end_time": datetime.utcfromtimestamp(ts_val + 3600).isoformat() + "Z",
                })

        # Sort by timestamp descending (most recent first)
        candles.sort(key=lambda x: x["start_time"], reverse=True)

        # Cache to DB for future use (match actual market_candles schema)
        if candles:
            try:
                from backend.core.time import now_iso
                with get_conn() as conn:
                    cursor = conn.cursor()
                    for i, candle in enumerate(candles):
                        candle_id = f"cb_{symbol}_{i}_{int(datetime.utcnow().timestamp())}"
                        cursor.execute(
                            """INSERT OR IGNORE INTO market_candles
                               (id, symbol, interval, start_time, end_time,
                                open, high, low, close, volume, ts)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                candle_id,
                                symbol,
                                "ONE_HOUR",
                                candle["start_time"],
                                candle["end_time"],
                                candle["open"],
                                candle["high"],
                                candle["low"],
                                candle["close"],
                                candle["volume"],
                                now_iso(),
                            )
                        )
                    conn.commit()
                    logger.info("Cached %d candles from Coinbase API for %s", len(candles), symbol)
            except Exception as cache_err:
                logger.debug("Failed to cache candles for %s: %s", symbol, str(cache_err)[:100])
        
        return candles
        
    except Exception as e:
        logger.debug(f"Coinbase candles API fallback failed for {symbol}: {e}")
        return []


# ---------------------------------------------------------------------------
# Price fetching (Coinbase public API, 1.5s timeout)
# ---------------------------------------------------------------------------

async def _fetch_price_data(symbol: str) -> dict:
    """Fetch price + 24h change + 7d range from market data provider.

    Returns dict with keys: price, change_24h_pct, change_7d_pct, range_7d_high, 
    range_7d_low, price_pct_of_range, volatility_7d_atr, price_source.
    On failure, returns price=None.
    """
    try:
        from backend.services.market_data import get_price
        price = get_price(symbol)
        
        # Fetch candle data for 24h change and 7d range
        change_24h_pct = None
        change_7d_pct = None
        range_7d_high = None
        range_7d_low = None
        price_pct_of_range = None
        volatility_7d_atr = None
        
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                
                # Get recent candles (up to 7 days worth, assuming 1h candles = 168 candles)
                cursor.execute(
                    """SELECT close, high, low, start_time FROM market_candles
                       WHERE symbol = ? ORDER BY ts DESC LIMIT 200""",
                    (symbol,)
                )
                rows = cursor.fetchall()
                
                # If DB has no candles, try Coinbase API fallback
                if len(rows) == 0:
                    logger.debug(f"No candles in DB for {symbol}, trying Coinbase API fallback")
                    candles_fallback = await _fetch_candles_fallback(symbol)
                    if candles_fallback:
                        rows = candles_fallback
                        logger.info(f"Using {len(rows)} candles from Coinbase API fallback for {symbol}")
                
                if len(rows) >= 2:
                    # 24h change (last 2 candles)
                    current = float(rows[0]["close"])
                    prev = float(rows[1]["close"])
                    if prev > 0:
                        change_24h_pct = ((current - prev) / prev) * 100
                    
                    # 7d range and change
                    if len(rows) >= 24:  # At least 24 hours of data
                        candles_7d = rows[:min(168, len(rows))]  # Up to 7 days
                        highs = [float(r["high"]) for r in candles_7d if r["high"]]
                        lows = [float(r["low"]) for r in candles_7d if r["low"]]
                        closes = [float(r["close"]) for r in candles_7d if r["close"]]
                        
                        if highs and lows and closes:
                            range_7d_high = max(highs)
                            range_7d_low = min(lows)
                            
                            # Calculate where current price sits in range (0-100%)
                            if range_7d_high > range_7d_low:
                                price_pct_of_range = ((price - range_7d_low) / (range_7d_high - range_7d_low)) * 100
                            
                            # 7d change
                            oldest_close = closes[-1]
                            if oldest_close > 0:
                                change_7d_pct = ((current - oldest_close) / oldest_close) * 100
                            
                            # Calculate 7d ATR (Average True Range) as volatility proxy
                            if len(candles_7d) >= 2:
                                true_ranges = []
                                for i in range(len(candles_7d) - 1):
                                    high = float(candles_7d[i]["high"])
                                    low = float(candles_7d[i]["low"])
                                    prev_close = float(candles_7d[i + 1]["close"])
                                    
                                    tr = max(
                                        high - low,
                                        abs(high - prev_close),
                                        abs(low - prev_close)
                                    )
                                    true_ranges.append(tr)
                                
                                if true_ranges and price > 0:
                                    avg_tr = sum(true_ranges) / len(true_ranges)
                                    volatility_7d_atr = (avg_tr / price) * 100  # As percentage
        
        except Exception as e:
            logger.debug(f"Candle data fetch failed for {symbol}: {e}")

        return {
            "price": price,
            "change_24h_pct": change_24h_pct,
            "change_7d_pct": change_7d_pct,
            "range_7d_high": range_7d_high,
            "range_7d_low": range_7d_low,
            "price_pct_of_range": price_pct_of_range,
            "volatility_7d_atr": volatility_7d_atr,
            "price_source": "market_data_provider"
        }
    except Exception as e:
        logger.warning("Price fetch failed for %s: %s", symbol, str(e)[:100])
        return {
            "price": None,
            "change_24h_pct": None,
            "change_7d_pct": None,
            "range_7d_high": None,
            "range_7d_low": None,
            "price_pct_of_range": None,
            "volatility_7d_atr": None,
            "price_source": "none"
        }


# ---------------------------------------------------------------------------
# Sentiment analysis (lightweight keyword-based)
# ---------------------------------------------------------------------------

def _analyze_headline_sentiment(headline: str) -> dict:
    """Analyze headline sentiment using keyword matching.

    Returns dict with:
      - sentiment: "bullish" | "bearish" | "neutral"
      - confidence: 0.0-1.0 (keyword match density)
      - driver: dominant keyword that drove the classification
      - rationale: 3-10 word quote from the headline grounding the sentiment
    """
    headline_lower = headline.lower()
    words = headline.split()

    # Driver label categories
    driver_categories = {
        "Macro": ["market", "economy", "gdp", "inflation", "fed", "rate", "treasury", "dollar"],
        "Regulation": ["regulation", "crackdown", "ban", "sec", "law", "compliance", "legal"],
        "ETF": ["etf", "fund", "grayscale", "blackrock", "fidelity", "ishares"],
        "Exchange": ["exchange", "coinbase", "binance", "kraken", "ftx"],
        "Security": ["hack", "exploit", "scam", "fraud", "vulnerability", "breach"],
        "Adoption": ["adoption", "partnership", "launch", "integration", "accept", "payment"],
        "On-chain": ["whale", "mining", "halving", "hash", "staking", "defi", "nft"],
    }

    # Bullish keywords
    bullish_keywords = [
        "surge", "rally", "gain", "rise", "soar", "jump", "climb", "breakout",
        "bullish", "bull", "up", "high", "record", "all-time", "ath", "moon",
        "pump", "green", "profit", "win", "success", "adoption", "breakthrough",
        "positive", "optimistic", "upgrade", "partnership", "launch"
    ]

    # Bearish keywords
    bearish_keywords = [
        "crash", "plunge", "drop", "fall", "decline", "sink", "tumble", "slump",
        "bearish", "bear", "down", "low", "loss", "losses", "red", "sell-off",
        "dump", "fear", "panic", "concern", "warning", "risk", "threat", "hack",
        "exploit", "scam", "fraud", "ban", "regulation", "crackdown", "negative"
    ]

    bullish_hits = [kw for kw in bullish_keywords if kw in headline_lower]
    bearish_hits = [kw for kw in bearish_keywords if kw in headline_lower]
    bullish_count = len(bullish_hits)
    bearish_count = len(bearish_hits)
    total_hits = bullish_count + bearish_count

    if bullish_count > bearish_count:
        sentiment = "bullish"
        primary_kw = bullish_hits[0] if bullish_hits else "general"
    elif bearish_count > bullish_count:
        sentiment = "bearish"
        primary_kw = bearish_hits[0] if bearish_hits else "general"
    else:
        sentiment = "neutral"
        primary_kw = "mixed" if total_hits > 0 else "none"

    # Determine driver category label
    driver = primary_kw
    for cat_label, cat_keywords in driver_categories.items():
        if any(ck in headline_lower for ck in cat_keywords):
            driver = cat_label
            break

    # Confidence: ratio of dominant signal strength to total possible keywords
    dominant_count = max(bullish_count, bearish_count)
    confidence = min(dominant_count / 3.0, 1.0) if dominant_count > 0 else 0.0

    # Extract grounded rationale: quote 3-10 words from headline around the
    # first matched keyword to anchor the sentiment in the source text.
    rationale = ""
    if primary_kw and primary_kw not in ("general", "mixed", "none"):
        try:
            kw_lower = primary_kw.lower()
            for idx, w in enumerate(words):
                if kw_lower in w.lower():
                    start = max(0, idx - 2)
                    end = min(len(words), idx + 8)
                    snippet = words[start:end]
                    if len(snippet) < 3 and len(words) >= 3:
                        snippet = words[:min(10, len(words))]
                    rationale = " ".join(snippet)
                    break
        except Exception:
            pass
    if not rationale and len(words) >= 3:
        rationale = " ".join(words[:min(10, len(words))])

    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 2),
        "driver": driver,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# News headlines (DB query, 1.5s budget)
# ---------------------------------------------------------------------------

def _fetch_headlines(symbol: str, limit: int = 5) -> Tuple[List[dict], bool, str]:
    """Fetch recent headlines mentioning this asset from news_items table.

    Returns (headlines_list, fetch_failed, diagnostic_reason) tuple.
    Each headline includes sentiment analysis.
    ``diagnostic_reason`` is a human-readable string explaining why no
    headlines were returned (empty string on success).
    
    Tries multiple symbol variants (BTC, BTC-USD, Bitcoin) to maximize matches.
    """
    try:
        # Generate symbol variants to try
        from backend.core.symbols import to_product_id
        symbol_variants = [symbol]
        
        # Add product_id variant (e.g., "BTC" -> "BTC-USD")
        try:
            product_id = to_product_id(symbol)
            if product_id != symbol and product_id not in symbol_variants:
                symbol_variants.append(product_id)
        except Exception:
            pass
        
        # Add common name variants for major cryptos
        symbol_upper = symbol.upper().replace("-USD", "")
        name_mapping = {
            "BTC": ["Bitcoin", "BTC-USD", "bitcoin"],
            "ETH": ["Ethereum", "ETH-USD", "ethereum", "Ether"],
            "SOL": ["Solana", "SOL-USD", "solana"],
            "USDC": ["USD Coin", "USDC-USD"],
            "DOGE": ["Dogecoin", "DOGE-USD", "dogecoin"],
            "MATIC": ["Polygon", "MATIC-USD", "polygon"],
            "AVAX": ["Avalanche", "AVAX-USD", "avalanche"],
            "ADA": ["Cardano", "ADA-USD", "cardano"],
            "DOT": ["Polkadot", "DOT-USD", "polkadot"],
            "LINK": ["Chainlink", "LINK-USD", "chainlink"],
            "XRP": ["Ripple", "XRP-USD", "ripple"],
            "UNI": ["Uniswap", "UNI-USD", "uniswap"],
            "LTC": ["Litecoin", "LTC-USD", "litecoin"],
            "ATOM": ["Cosmos", "ATOM-USD", "cosmos"],
            "SHIB": ["Shiba Inu", "SHIB-USD"],
        }
        if symbol_upper in name_mapping:
            for variant in name_mapping[symbol_upper]:
                if variant not in symbol_variants:
                    symbol_variants.append(variant)
        
        # Try 48h window first, then expand to 72h if no results
        time_windows = [48, 72]
        
        for hours in time_windows:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            
            with get_conn() as conn:
                cursor = conn.cursor()
                
                # Build query with multiple symbol variants
                placeholders = ",".join("?" * len(symbol_variants))
                query = f"""
                    SELECT DISTINCT ni.title, ni.url, ni.published_at, ns.name as source_name
                    FROM news_items ni
                    JOIN news_asset_mentions nam ON ni.id = nam.item_id
                    LEFT JOIN news_sources ns ON ni.source_id = ns.id
                    WHERE nam.asset_symbol IN ({placeholders})
                      AND ni.published_at >= ?
                    ORDER BY ni.published_at DESC
                    LIMIT ?
                """
                
                params = symbol_variants + [cutoff, limit]
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                if rows:
                    headlines = []
                    for row in rows:
                        title = row["title"]
                        sa = _analyze_headline_sentiment(title)
                        headlines.append({
                            "title": title,
                            "url": row["url"] if "url" in row.keys() else None,
                            "published_at": row["published_at"],
                            "source": row["source_name"] if "source_name" in row.keys() else "Unknown",
                            "sentiment": sa["sentiment"],
                            "confidence": sa["confidence"],
                            "driver": sa["driver"],
                            "rationale": sa["rationale"],
                        })
                    
                    if headlines:
                        logger.debug(
                            f"Found {len(headlines)} headlines for {symbol} "
                            f"(tried variants: {symbol_variants}, window: {hours}h)"
                        )
                        return headlines, False, ""
        
        # No headlines found after trying all variants and time windows.
        # Check if news_sources are enabled to provide a diagnostic reason.
        diagnostic_reason = "no matching headlines in 72h window"
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as cnt FROM news_sources WHERE is_enabled = 1")
                row = cursor.fetchone()
                enabled = row["cnt"] if row else 0
                cursor.execute("SELECT COUNT(*) as cnt FROM news_items")
                items_row = cursor.fetchone()
                total_items = items_row["cnt"] if items_row else 0
                if enabled == 0:
                    diagnostic_reason = "no news sources enabled -- run POST /api/v1/news/ingest"
                elif total_items == 0:
                    diagnostic_reason = "news sources enabled but 0 articles ingested -- trigger ingestion"
                else:
                    diagnostic_reason = (
                        f"0 of {total_items} articles match {symbol_variants} in 72h; "
                        f"try ingesting more sources"
                    )
        except Exception:
            pass  # best-effort diagnostic

        logger.info(
            "No headlines for %s (%s). Variants tried: %s",
            symbol, diagnostic_reason, symbol_variants,
        )
        # Telemetry: emit news_fetch_zero_results metric
        try:
            from backend.evals.runtime_evals import emit_runtime_metric
            emit_runtime_metric("news_fetch_zero_results", {
                "symbol": symbol,
                "variants_tried": symbol_variants,
                "diagnostic": diagnostic_reason,
            })
        except Exception:
            pass  # best-effort telemetry

        # Simulated fallback: provide deterministic dev-mode headlines so the
        # insight card is never empty during development / demo.
        use_simulated = os.environ.get("NEWS_USE_SIMULATED_FALLBACK", "true").lower() in ("1", "true", "yes")
        if use_simulated:
            symbol_display = symbol_upper or symbol
            simulated_headlines = [
                {
                    "title": f"[Simulated] {symbol_display} market shows mixed signals amid steady volume",
                    "url": None,
                    "published_at": datetime.utcnow().isoformat(),
                    "source": "Simulated",
                    "sentiment": "neutral",
                    "confidence": 0.3,
                    "driver": "mixed",
                    "rationale": "simulated headline for development — no live feeds matched",
                },
                {
                    "title": f"[Simulated] Analysts watching {symbol_display} price action closely this week",
                    "url": None,
                    "published_at": (datetime.utcnow() - timedelta(hours=6)).isoformat(),
                    "source": "Simulated",
                    "sentiment": "neutral",
                    "confidence": 0.25,
                    "driver": "mixed",
                    "rationale": "simulated headline for development — no live feeds matched",
                },
                {
                    "title": f"[Simulated] Crypto markets flat as {symbol_display} consolidates near key level",
                    "url": None,
                    "published_at": (datetime.utcnow() - timedelta(hours=12)).isoformat(),
                    "source": "Simulated",
                    "sentiment": "neutral",
                    "confidence": 0.25,
                    "driver": "mixed",
                    "rationale": "simulated headline for development — no live feeds matched",
                },
            ]
            logger.info(
                "Using %d simulated fallback headlines for %s (NEWS_USE_SIMULATED_FALLBACK=true)",
                len(simulated_headlines), symbol,
            )
            return simulated_headlines, False, f"simulated fallback ({diagnostic_reason})"

        return [], False, diagnostic_reason
        
    except Exception as e:
        err_str = str(e).lower()
        if "no such table" in err_str or "no such column" in err_str:
            logger.info(
                "Headlines tables not configured for %s (run news migrations): %s",
                symbol, str(e)[:100]
            )
            return [], True, "news tables not available -- apply migration 016"
        else:
            logger.warning("Headlines fetch failed for %s: %s", symbol, str(e)[:100])
        return [], True, f"fetch error: {str(e)[:80]}"


# ---------------------------------------------------------------------------
# Deterministic fact pack
# ---------------------------------------------------------------------------

def build_fact_pack(
    asset: str,
    side: str,
    notional_usd: float,
    asset_class: str,
    price_data: dict,
    headlines: List[dict],
    mode: str = "PAPER",
    news_enabled: bool = True,
    headlines_fetch_failed: bool = False,
    headlines_diagnostic: str = "",
) -> dict:
    """Build deterministic fact pack from price data and headlines."""
    price = price_data.get("price")
    change_pct = price_data.get("change_24h_pct")
    change_7d_pct = price_data.get("change_7d_pct")
    range_7d_high = price_data.get("range_7d_high")
    range_7d_low = price_data.get("range_7d_low")
    price_pct_of_range = price_data.get("price_pct_of_range")
    volatility_7d_atr = price_data.get("volatility_7d_atr")
    price_source = price_data.get("price_source", "none")

    # Volatility proxy (use 7d ATR if available, fallback to 24h change)
    volatility: Optional[str] = None
    if volatility_7d_atr is not None:
        # Use 7d ATR as primary volatility measure
        if volatility_7d_atr > 5:
            volatility = "HIGH"
        elif volatility_7d_atr > 2:
            volatility = "MODERATE"
        else:
            volatility = "LOW"
    elif change_pct is not None:
        # Fallback to 24h change
        abs_change = abs(change_pct)
        if abs_change > 5:
            volatility = "HIGH"
        elif abs_change > 2:
            volatility = "MODERATE"
        else:
            volatility = "LOW"
    
    # Range position context
    range_position: Optional[str] = None
    if price_pct_of_range is not None:
        if price_pct_of_range >= 80:
            range_position = "near_high"
        elif price_pct_of_range <= 20:
            range_position = "near_low"
        else:
            range_position = "mid_range"

    # Fee estimates (Coinbase taker fee)
    estimated_fees_pct = 0.6
    estimated_fees_usd = notional_usd * 0.006
    fee_impact_pct = (estimated_fees_usd / notional_usd * 100) if notional_usd > 0 else 0.0

    # Mode / LIVE config
    from backend.core.config import get_settings
    settings = get_settings()
    live_allowed = settings.is_live_execution_allowed()
    live_disabled_downgrade = (mode == "PAPER" and settings.trading_disable_live)

    # Data quality flags (boolean + descriptive reasons)
    data_quality = {
        "missing_price": price is None,
        "missing_price_reason": (
            f"Market data provider returned no data for {asset}"
            if price is None else None
        ),
        "missing_change": change_pct is None,
        "missing_change_reason": (
            f"No candle data in market_candles table for {asset}"
            if change_pct is None else None
        ),
        "missing_headlines": len(headlines) == 0 and news_enabled,
        "missing_headlines_reason": (
            headlines_diagnostic
            if headlines_diagnostic
            else f"News fetch failed for {asset} (tables may not be configured)"
            if headlines_fetch_failed
            else f"News feed returned 0 results for {asset} in 48h window"
            if (len(headlines) == 0 and news_enabled)
            else None
        ),
        "stale_data": price_source == "none",
        "headlines_fetch_failed": headlines_fetch_failed,
    }

    # Risk flags
    risk_flags: List[str] = []
    if change_pct is not None and abs(change_pct) > 5:
        risk_flags.append("high_volatility")
    if notional_usd < 10:
        risk_flags.append("thin_notional")
    if len(headlines) == 0 and news_enabled:
        risk_flags.append("news_empty")
    if price is None:
        risk_flags.append("price_unavailable")
    if not live_allowed and mode == "PAPER" and settings.trading_disable_live:
        risk_flags.append("live_disabled")
    if fee_impact_pct > 1.0 and notional_usd < 50:
        risk_flags.append("high_fee_impact")
    if change_pct is None:
        risk_flags.append("no_candle_data")
    if headlines_fetch_failed:
        risk_flags.append("headlines_fetch_failed")

    # Confidence scoring
    confidence = 0.35
    if price is not None and change_pct is not None:
        confidence += 0.15
    if volatility is not None:
        confidence += 0.10
    if len(headlines) >= 2:
        confidence += 0.10
    if len(headlines) == 0 and news_enabled:
        confidence -= 0.20
    if price is None:
        confidence -= 0.20
    confidence = max(0.0, min(1.0, confidence))

    # Top headlines for template use
    top_headlines = [h["title"] for h in headlines[:3]]
    headline_sources = list({h.get("source", "Unknown") for h in headlines})
    
    # Sentiment distribution
    sentiment_counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for h in headlines:
        sentiment = h.get("sentiment", "neutral")
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
    
    headline_sentiment_summary = None
    if len(headlines) > 0:
        parts = []
        if sentiment_counts["bullish"] > 0:
            parts.append(f"{sentiment_counts['bullish']} bullish")
        if sentiment_counts["bearish"] > 0:
            parts.append(f"{sentiment_counts['bearish']} bearish")
        if sentiment_counts["neutral"] > 0:
            parts.append(f"{sentiment_counts['neutral']} neutral")
        headline_sentiment_summary = ", ".join(parts) if parts else "no sentiment"

    # Key facts (never say "UNKNOWN")
    key_facts: List[str] = []
    if price is not None:
        key_facts.append(f"{asset} is trading at ${price:,.2f}")
    
    # 24h and 7d trends
    if change_pct is not None:
        direction = "up" if change_pct >= 0 else "down"
        key_facts.append(f"{asset} is {direction} {abs(change_pct):.1f}% in the last 24h")
    elif price is not None:
        key_facts.append(f"24h price trend data not available for {asset}")
    
    if change_7d_pct is not None:
        direction_7d = "up" if change_7d_pct >= 0 else "down"
        key_facts.append(f"7-day trend: {direction_7d} {abs(change_7d_pct):.1f}%")
    
    # Range context
    if range_7d_high is not None and range_7d_low is not None and price is not None:
        key_facts.append(f"7-day range: ${range_7d_low:,.2f} - ${range_7d_high:,.2f}")
        if price_pct_of_range is not None:
            if range_position == "near_high":
                key_facts.append(f"Price is near 7d high ({price_pct_of_range:.0f}% of range)")
            elif range_position == "near_low":
                key_facts.append(f"Price is near 7d low ({price_pct_of_range:.0f}% of range)")
            else:
                key_facts.append(f"Price is mid-range ({price_pct_of_range:.0f}% of range)")

    if volatility is not None:
        key_facts.append(f"Volatility: {volatility}")

    key_facts.append(f"Order size: ${notional_usd:.2f} ({side.upper()})")
    key_facts.append(f"Estimated taker fee: ${estimated_fees_usd:.2f} (0.6% of ${notional_usd:.2f})")

    if notional_usd < 50:
        key_facts.append(f"Fee represents {fee_impact_pct:.1f}% of order value")

    if headlines:
        key_facts.append(f"{len(headlines)} headline(s) in last 48h")
    elif news_enabled and not headlines_fetch_failed:
        key_facts.append("No headlines available (feed returned none)")
    elif headlines_fetch_failed:
        key_facts.append("No headlines available (news fetch failed)")

    key_facts.append(f"Execution mode: {mode}")
    if live_disabled_downgrade:
        key_facts.append("(LIVE disabled, running as PAPER)")

    return {
        "asset": asset,
        "side": side,
        "notional_usd": notional_usd,
        "asset_class": asset_class,
        "price": price,
        "change_24h_pct": change_pct,
        "change_7d_pct": change_7d_pct,
        "range_7d_high": range_7d_high,
        "range_7d_low": range_7d_low,
        "price_pct_of_range": price_pct_of_range,
        "range_position": range_position,
        "volatility": volatility,
        "volatility_7d_atr": volatility_7d_atr,
        "headlines": headlines,
        "risk_flags": risk_flags,
        "confidence": confidence,
        "key_facts": key_facts,
        "price_source": price_source,
        "mode": mode,
        "live_allowed": live_allowed,
        "estimated_fees_pct": estimated_fees_pct,
        "estimated_fees_usd": estimated_fees_usd,
        "fee_impact_pct": fee_impact_pct,
        "data_quality": data_quality,
        "headlines_window_hours": 48,
        "top_headlines": top_headlines,
        "headline_sources": headline_sources,
        "headline_sentiment_summary": headline_sentiment_summary,
        "sentiment_counts": sentiment_counts,
        "news_enabled": news_enabled,
    }


# ---------------------------------------------------------------------------
# Template insight (always available)
# ---------------------------------------------------------------------------

def _template_headline(facts: dict) -> str:
    asset = facts["asset"]
    change = facts.get("change_24h_pct")
    price = facts.get("price")
    range_position = facts.get("range_position")
    price_pct_of_range = facts.get("price_pct_of_range")
    headlines = facts.get("headlines", [])
    top_headlines = facts.get("top_headlines", [])
    live_allowed = facts.get("live_allowed", True)
    mode = facts.get("mode", "PAPER")
    news_enabled = facts.get("news_enabled", True)

    # LIVE disabled downgrade notice
    prefix = ""
    if not live_allowed and mode == "PAPER":
        from backend.core.config import get_settings
        if get_settings().trading_disable_live:
            prefix = "PAPER trade (LIVE disabled): "

    # Build trend with range context
    if change is not None:
        direction = "up" if change >= 0 else "down"
        trend = f"{asset} {direction} {abs(change):.1f}% in 24h"
        
        # Add range context if available
        if range_position == "near_high":
            trend += f", near 7d high"
        elif range_position == "near_low":
            trend += f", near 7d low"
    elif price is not None:
        trend = f"{asset} at ${price:,.2f}"
    else:
        trend = f"{asset}: price data not available"

    # Context suffix from headlines
    if len(headlines) > 0 and top_headlines:
        # Use first headline as thematic context (truncated)
        theme = top_headlines[0][:60]
        suffix = f"; {theme}"
    elif news_enabled and len(headlines) == 0:
        suffix = "; no headlines available"
    else:
        suffix = ""

    return f"{prefix}{trend}{suffix}"


def _template_why_it_matters(facts: dict) -> str:
    asset = facts["asset"]
    side = facts["side"].upper()
    notional = facts["notional_usd"]
    change = facts.get("change_24h_pct")
    change_7d = facts.get("change_7d_pct")
    range_position = facts.get("range_position")
    price_pct_of_range = facts.get("price_pct_of_range")
    volatility = facts.get("volatility")
    estimated_fees_usd = facts.get("estimated_fees_usd", 0)
    fee_impact_pct = facts.get("fee_impact_pct", 0)
    headlines = facts.get("headlines", [])
    top_headlines = facts.get("top_headlines", [])
    news_enabled = facts.get("news_enabled", True)
    live_allowed = facts.get("live_allowed", True)
    mode = facts.get("mode", "PAPER")

    sentences: List[str] = []

    # 1. Opening with strategic context (BUY vs SELL differentiation)
    if side == "BUY":
        # BUY-specific scenarios
        if range_position == "near_low" and change is not None and change < 0:
            sentences.append(
                f"You're buying ${notional:.2f} of {asset} near its 7-day low "
                f"(down {abs(change):.1f}% in 24h, {price_pct_of_range:.0f}% of range). "
                f"This could be buying a dip or catching a falling knife."
            )
        elif range_position == "near_high" and change is not None and change > 0:
            sentences.append(
                f"You're buying ${notional:.2f} of {asset} near its 7-day high "
                f"(up {abs(change):.1f}% in 24h, {price_pct_of_range:.0f}% of range). "
                f"This could be momentum buying or buying into strength."
            )
        elif change is not None and change < -3:
            sentences.append(
                f"You're buying ${notional:.2f} of {asset} after a {abs(change):.1f}% drop in 24h. "
                f"Consider whether this is a dip-buying opportunity or continued weakness."
            )
        elif change is not None and change > 3:
            sentences.append(
                f"You're buying ${notional:.2f} of {asset} after a {abs(change):.1f}% rally in 24h. "
                f"You're buying into strength—watch for potential pullback."
            )
        else:
            sentences.append(f"You're buying ${notional:.2f} of {asset}.")
    else:
        # SELL-specific scenarios
        if range_position == "near_high" and change is not None and change > 0:
            sentences.append(
                f"You're selling ${notional:.2f} of {asset} near its 7-day high "
                f"(up {abs(change):.1f}% in 24h, {price_pct_of_range:.0f}% of range). "
                f"This could be profit-taking or selling into strength."
            )
        elif range_position == "near_low" and change is not None and change < 0:
            sentences.append(
                f"You're selling ${notional:.2f} of {asset} near its 7-day low "
                f"(down {abs(change):.1f}% in 24h, {price_pct_of_range:.0f}% of range). "
                f"This could be cutting losses or selling into weakness."
            )
        elif change is not None and change > 3:
            sentences.append(
                f"You're selling ${notional:.2f} of {asset} after a {abs(change):.1f}% rally in 24h. "
                f"Selling into strength can be a good profit-taking strategy."
            )
        elif change is not None and change < -3:
            sentences.append(
                f"You're selling ${notional:.2f} of {asset} after a {abs(change):.1f}% drop in 24h. "
                f"Consider whether you're cutting losses or selling into panic."
            )
        elif change is not None and abs(change) > 2:
            sentences.append(
                f"You're selling ${notional:.2f} of {asset} during a volatile window ({abs(change):.1f}% 24h move)."
            )
        else:
            sentences.append(f"You're selling ${notional:.2f} of {asset}.")

    # 2. Fee impact (always for small orders)
    if notional < 50:
        sentences.append(
            f"At ${notional:.2f}, the ~0.6% taker fee is ${estimated_fees_usd:.2f} "
            f"({fee_impact_pct:.1f}% of your order)."
        )

    # 3. Headlines context with sentiment
    sentiment_summary = facts.get("headline_sentiment_summary")
    sentiment_counts = facts.get("sentiment_counts", {})
    
    if len(headlines) > 0 and top_headlines:
        theme = top_headlines[0][:80]
        
        # Add sentiment context
        if sentiment_summary:
            sentences.append(
                f'Recent headlines ({sentiment_summary}) mention "{theme}". '
                f"Consider whether this sentiment aligns with your {side} thesis."
            )
        else:
            sentences.append(
                f'Recent headlines mention "{theme}". '
                f"Consider whether this aligns with your {side} thesis."
            )
        
        # Add specific sentiment guidance for BUY/SELL
        if side == "BUY" and sentiment_counts.get("bearish", 0) > sentiment_counts.get("bullish", 0):
            sentences.append(
                f"Bearish sentiment dominates recent headlines—buying into negative news can be contrarian or risky."
            )
        elif side == "SELL" and sentiment_counts.get("bullish", 0) > sentiment_counts.get("bearish", 0):
            sentences.append(
                f"Bullish sentiment dominates recent headlines—selling into positive news may mean taking profit early."
            )
    elif news_enabled and len(headlines) == 0:
        data_quality = facts.get("data_quality", {})
        if data_quality.get("headlines_fetch_failed"):
            sentences.append(
                f"No headlines pulled in the last 48h (news fetch failed for {asset})."
            )
        else:
            sentences.append(
                f"No headlines pulled in the last 48h "
                f"(news feed may not be configured or returned no results for {asset})."
            )

    # 4. Volatility (never say "UNKNOWN")
    if volatility is None:
        sentences.append(
            f"Volatility data not available (no candle feed configured for {asset})."
        )
    elif volatility == "HIGH":
        sentences.append(
            f"{asset} moved {abs(change):.1f}% in 24h, suggesting HIGH volatility. "
            f"Consider execution price carefully."
        )
    elif volatility == "MODERATE":
        sentences.append(
            f"{asset} moved {abs(change):.1f}% in 24h, suggesting MODERATE volatility."
        )

    # 5. LIVE disabled warning
    if not live_allowed and mode == "PAPER":
        from backend.core.config import get_settings
        if get_settings().trading_disable_live:
            sentences.append(
                "Note: LIVE trading is currently disabled. "
                "This will execute as a PAPER trade."
            )

    return " ".join(sentences)


def _strip_markdown_headings(text: str) -> str:
    """Remove markdown headings (###, ##, #) and collapse excessive blank lines.
    Ensures enterprise RAG output never shows heading tokens."""
    if not text or not isinstance(text, str):
        return text
    # Remove lines that are markdown headings: optional whitespace + 1-6 # + space + rest
    lines = text.split("\n")
    out = []
    for line in lines:
        stripped = re.sub(r"^\s{0,10}#{1,6}\s+", "", line)
        out.append(stripped)
    # Collapse excessive blank lines to max 1
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return result.strip()


def _is_llm_available() -> bool:
    """Check if OpenAI API key is configured (cached)."""
    global _llm_available
    if _llm_available is None:
        _llm_available = bool(os.getenv("OPENAI_API_KEY"))
    return _llm_available


async def _llm_enhance_insight(facts: dict, template: dict, timeout_s: float = 2.0) -> Optional[dict]:
    """Enhance template insight with LLM narrative. Returns None on failure/timeout.

    Input: fact_pack + template insight.
    Output: dict with enhanced 'headline' and 'why_it_matters', or None.
    """
    if not _is_llm_available():
        return None

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI()

        # Build structured prompt from fact_pack
        headlines_section = ""
        top_headlines = facts.get("top_headlines", [])
        headline_sources = facts.get("headline_sources", [])
        if top_headlines:
            headlines_section = (
                f"\nRecent headlines ({len(top_headlines)}):\n"
                + "\n".join(f"- {h}" for h in top_headlines)
                + f"\nSources: {', '.join(headline_sources) if headline_sources else 'unknown'}"
            )
        elif facts.get("news_enabled"):
            dq = facts.get("data_quality", {})
            reason = dq.get("missing_headlines_reason", "0 headlines returned")
            headlines_section = f"\nNo headlines available: {reason}"

        price_info = ""
        if facts.get("price") is not None:
            price_info = f"Current price: ${facts['price']:,.2f}"
            if facts.get("change_24h_pct") is not None:
                direction = "up" if facts["change_24h_pct"] >= 0 else "down"
                price_info += f", {direction} {abs(facts['change_24h_pct']):.1f}% in 24h"
                if facts.get("volatility"):
                    price_info += f" (volatility: {facts['volatility']})"
        else:
            dq = facts.get("data_quality", {})
            price_info = f"Price data not available: {dq.get('missing_price_reason', 'unknown reason')}"

        prompt = f"""Generate a concise pre-trade financial insight for the following trade:

Trade: {facts['side'].upper()} ${facts['notional_usd']:.2f} of {facts['asset']} ({facts.get('mode', 'PAPER')} mode)
{price_info}
Estimated fee: ${facts.get('estimated_fees_usd', 0):.2f} ({facts.get('estimated_fees_pct', 0.6):.1f}% taker fee)
{f"Fee as % of order: {facts.get('fee_impact_pct', 0):.1f}%" if facts.get('notional_usd', 0) < 50 else ""}
{headlines_section}

Requirements:
1. Write a headline (1 sentence, max 100 chars) specific to THIS trade
2. Write why_it_matters (2-4 sentences) referencing specific numbers from above
3. Write 2-4 bullet points as key_facts
4. If headlines exist, cite at least one headline topic and explain why it matters for {facts['side'].upper()}
5. If 0 headlines, explicitly state "0 headlines in the last 48 hours" and focus on microstructure/cost analysis
6. For any missing data, say "not available because [reason]" instead of "UNKNOWN"
7. Do NOT give financial advice. Frame as informational context only.
8. CRITICAL: Do NOT use markdown headings or any # characters. Use only plain text. No ###, no ##, no #. No bold/italic markdown. Output clean label-style prose only.

Respond in JSON format:
{{"headline": "...", "why_it_matters": "...", "key_facts": ["...", "..."]}}"""

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,
                response_format={"type": "json_object"},
            ),
            timeout=timeout_s,
        )

        content = response.choices[0].message.content
        if not content:
            return None

        result = json.loads(content)
        # Validate required fields exist
        if not result.get("headline") or not result.get("why_it_matters"):
            return None

        # Post-process: strip any markdown headings the model may have emitted
        headline = _strip_markdown_headings(str(result["headline"])[:150])
        why_it_matters = _strip_markdown_headings(str(result["why_it_matters"])[:600])
        key_facts = [_strip_markdown_headings(str(f)[:200]) for f in (result.get("key_facts") or [])[:4]]

        return {
            "headline": headline,
            "why_it_matters": why_it_matters,
            "key_facts": key_facts,
        }

    except asyncio.TimeoutError:
        logger.info("LLM insight enhancement timed out after %.1fs", timeout_s)
        return None
    except Exception as e:
        logger.info("LLM insight enhancement failed: %s", str(e)[:150])
        return None


def _build_template_insight(facts: dict, request_id: str) -> dict:
    """Build a complete template-based insight from facts."""
    # Include headline objects with sentiment so the UI can render sentiment badges
    headline_objs = []
    for h in facts.get("headlines", [])[:3]:
        headline_objs.append({
            "title": h["title"],
            "sentiment": h.get("sentiment", "neutral"),
            "confidence": h.get("confidence", 0),
            "driver": h.get("driver", "none"),
            "rationale": h.get("rationale", ""),
            "source": h.get("source", "Unknown"),
            "url": h.get("url"),
            "published_at": h.get("published_at"),
        })

    return InsightSchema(
        headline=_template_headline(facts),
        why_it_matters=_template_why_it_matters(facts),
        key_facts=facts.get("key_facts", []),
        risk_flags=facts.get("risk_flags", []),
        confidence=facts.get("confidence", 0.0),
        sources={
            "price_source": facts.get("price_source", "none"),
            "headlines": headline_objs
        },
        generated_by="template",
        request_id=request_id
    ).model_dump()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_insight(
    asset: str,
    side: str,
    notional_usd: float,
    asset_class: str = "CRYPTO",
    news_enabled: bool = True,
    mode: str = "PAPER",
    request_id: str = ""
) -> dict:
    """Generate a pre-confirm financial insight.

    Always returns a valid InsightSchema dict. Never raises.
    Uses in-memory cache with 60s TTL.
    """
    try:
        # Check cache
        ck = _cache_key(asset, side, notional_usd, mode, news_enabled)
        cached = _cache_get(ck)
        if cached:
            # Update request_id for this specific request
            cached["request_id"] = request_id
            return cached

        # Gather facts
        price_data = await _fetch_price_data(asset)
        headlines_fetch_failed = False
        headlines_diagnostic = ""
        if news_enabled:
            headlines, headlines_fetch_failed, headlines_diagnostic = _fetch_headlines(asset)
        else:
            headlines = []
            headlines_diagnostic = "news toggle is OFF"

        facts = build_fact_pack(
            asset, side, notional_usd, asset_class, price_data, headlines,
            mode=mode, news_enabled=news_enabled,
            headlines_fetch_failed=headlines_fetch_failed,
            headlines_diagnostic=headlines_diagnostic,
        )

        # Build template insight (always works)
        insight = _build_template_insight(facts, request_id)

        # Attempt LLM enhancement (2s timeout, non-blocking)
        if _is_llm_available():
            try:
                llm_result = await _llm_enhance_insight(facts, insight)
                if llm_result:
                    insight["headline"] = llm_result["headline"]
                    insight["why_it_matters"] = llm_result["why_it_matters"]
                    if llm_result.get("key_facts"):
                        insight["key_facts"] = llm_result["key_facts"]
                    insight["generated_by"] = "hybrid"
            except Exception:
                pass  # Keep template insight

        # Cache and return
        _cache_set(ck, insight)
        return insight

    except Exception as e:
        logger.warning("Insight generation failed: %s", str(e)[:200])
        # Absolute fallback
        return InsightSchema(
            headline="Market insight unavailable",
            why_it_matters="Unable to generate insight. Confirm or cancel at your discretion.",
            key_facts=[],
            risk_flags=["insight_unavailable"],
            confidence=0.0,
            sources={"price_source": "none", "headlines": []},
            generated_by="template",
            request_id=request_id
        ).model_dump()
