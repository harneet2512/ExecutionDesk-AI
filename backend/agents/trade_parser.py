"""Enhanced command parser with natural language parsing.

Supports both crypto and stock asset classes:
- CRYPTO: BTC, ETH, SOL, etc. (default, via Coinbase)
- STOCK: AAPL, MSFT, NVDA, etc. (via Polygon.io, ASSISTED_LIVE mode)
"""
import re
import os
from typing import Optional, Literal
from pydantic import BaseModel


# Crypto symbols and their aliases
CRYPTO_SYMBOLS = {
    'btc': 'BTC', 'bitcoin': 'BTC',
    'eth': 'ETH', 'ethereum': 'ETH',
    'sol': 'SOL', 'solana': 'SOL',
    'ada': 'ADA', 'cardano': 'ADA',
    'dot': 'DOT', 'polkadot': 'DOT',
    'matic': 'MATIC', 'polygon': 'MATIC',
    'avax': 'AVAX', 'avalanche': 'AVAX',
    'link': 'LINK', 'chainlink': 'LINK',
    'uni': 'UNI', 'uniswap': 'UNI',
    'atom': 'ATOM', 'cosmos': 'ATOM',
    'doge': 'DOGE', 'dogecoin': 'DOGE',
    'shib': 'SHIB', 'shiba': 'SHIB',
    'xrp': 'XRP', 'ripple': 'XRP',
    'ltc': 'LTC', 'litecoin': 'LTC',
}

# Stock symbols and their aliases (common tickers + company names)
STOCK_SYMBOLS = {
    # Tech giants
    'aapl': 'AAPL', 'apple': 'AAPL',
    'msft': 'MSFT', 'microsoft': 'MSFT',
    'googl': 'GOOGL', 'google': 'GOOGL', 'alphabet': 'GOOGL',
    'goog': 'GOOG',
    'amzn': 'AMZN', 'amazon': 'AMZN',
    'meta': 'META', 'facebook': 'META',
    'nvda': 'NVDA', 'nvidia': 'NVDA',
    'tsla': 'TSLA', 'tesla': 'TSLA',
    # Indices/ETFs
    'spy': 'SPY', 's&p': 'SPY', 's&p500': 'SPY',
    'qqq': 'QQQ', 'nasdaq': 'QQQ',
    'dia': 'DIA', 'dow': 'DIA',
    'iwm': 'IWM', 'russell': 'IWM',
    'voo': 'VOO',
    # Other tech
    'amd': 'AMD',
    'intc': 'INTC', 'intel': 'INTC',
    'crm': 'CRM', 'salesforce': 'CRM',
    'orcl': 'ORCL', 'oracle': 'ORCL',
    'csco': 'CSCO', 'cisco': 'CSCO',
    'ibm': 'IBM',
    'nflx': 'NFLX', 'netflix': 'NFLX',
    'pypl': 'PYPL', 'paypal': 'PYPL',
    'adbe': 'ADBE', 'adobe': 'ADBE',
    # Finance
    'jpm': 'JPM', 'jpmorgan': 'JPM',
    'bac': 'BAC', 'bank of america': 'BAC',
    'gs': 'GS', 'goldman': 'GS',
    'v': 'V', 'visa': 'V',
    'ma': 'MA', 'mastercard': 'MA',
    # Healthcare
    'jnj': 'JNJ', 'johnson': 'JNJ',
    'unh': 'UNH', 'unitedhealth': 'UNH',
    'pfe': 'PFE', 'pfizer': 'PFE',
    'mrna': 'MRNA', 'moderna': 'MRNA',
    # Consumer
    'wmt': 'WMT', 'walmart': 'WMT',
    'ko': 'KO', 'coca-cola': 'KO', 'coke': 'KO',
    'pep': 'PEP', 'pepsi': 'PEP',
    'mcd': 'MCD', 'mcdonalds': 'MCD',
    'sbux': 'SBUX', 'starbucks': 'SBUX',
    'dis': 'DIS', 'disney': 'DIS',
    # Energy
    'xom': 'XOM', 'exxon': 'XOM',
    'cvx': 'CVX', 'chevron': 'CVX',
}

# Keywords that indicate asset class
CRYPTO_KEYWORDS = ['crypto', 'cryptocurrency', 'coin', 'token', 'defi']
STOCK_KEYWORDS = ['stock', 'stocks', 'equity', 'equities', 'share', 'shares', 'etf']


class ParsedTradeCommand(BaseModel):
    """Parsed trade command structure."""
    side: Optional[str] = None  # "buy" or "sell"
    asset: Optional[str] = None  # "BTC", "ETH", "AAPL", etc.
    amount_usd: Optional[float] = None
    amount_base: Optional[float] = None  # base units if specified directly
    amount_mode: str = "quote_usd"  # "quote_usd" or "base_units"
    venue_symbol: Optional[str] = None  # "BTC-USD" for crypto, "AAPL" for stock
    mode: str = "LIVE"  # LIVE, PAPER, or ASSISTED_LIVE (stocks)
    is_most_profitable: bool = False
    lookback_hours: float = 24.0  # Supports fractional hours for minute-level lookbacks
    raw_text: str = ""
    asset_class: Literal["CRYPTO", "STOCK", "AMBIGUOUS"] = "CRYPTO"  # Default to crypto for backwards compatibility
    # Extended selection criteria fields
    selection_criteria: Optional[str] = None  # "highest_performing", "best_return", "momentum", etc.
    threshold_pct: Optional[float] = None  # Percentage threshold (e.g., "up 20%" -> 20.0)
    universe_constraint: Optional[str] = None  # "majors_only", "top_25_volume", "exclude_stablecoins"
    # Structured time window (enterprise feature)
    time_window: Optional[dict] = None  # TimeWindow.to_dict() output
    # "sell last purchase" support
    is_sell_last_purchase: bool = False
    # Dynamic resolution metadata
    resolution_source: Optional[str] = None  # "hardcoded", "portfolio", "order_history", "catalog"


def detect_test_environment() -> bool:
    """Detect if running in pytest environment."""
    import sys
    return 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ


def parse_trade_command(text: str) -> ParsedTradeCommand:
    """
    Parse natural language trade command.

    Examples:
        "Buy $10 of BTC" → {side: buy, asset: BTC, amount_usd: 10, mode: LIVE, asset_class: CRYPTO}
        "Buy $50 of AAPL stock" → {side: buy, asset: AAPL, amount_usd: 50, mode: ASSISTED_LIVE, asset_class: STOCK}
        "Buy the most profitable crypto last 24h for $10" → {side: buy, is_most_profitable: True, amount_usd: 10}
        "Buy $10 BTC paper" → {side: buy, asset: BTC, amount_usd: 10, mode: PAPER}
    """
    text_lower = text.lower().strip()
    result = ParsedTradeCommand(raw_text=text)

    # Detect "sell last purchase" / "sell last" / "sell previous" patterns
    # Also handles "sell $2 of last purchase" and "sell 2 dollars of last purchase"
    _sell_last_patterns = [
        'sell last purchase', 'sell my last purchase', 'sell the last purchase',
        'sell last buy', 'sell the last buy', 'sell previous purchase',
        'sell previous buy', 'sell last asset', 'sell the last asset',
        'sell last', 'undo last buy', 'reverse last buy',
        'last purchase', 'last buy', 'previous purchase',
    ]
    # Match if any pattern is present AND "sell" is in the text
    _has_sell_last = any(pat in text_lower for pat in _sell_last_patterns) and 'sell' in text_lower
    # Also match regex for "sell ... last purchase/buy"
    if not _has_sell_last:
        _has_sell_last = bool(re.search(r'sell\b.*\blast\s+(?:purchase|buy|asset)', text_lower))
    if _has_sell_last:
        result.is_sell_last_purchase = True
        result.side = "sell"
    # Parse side (buy/sell)
    elif 'buy' in text_lower or 'purchase' in text_lower:
        result.side = "buy"
    elif 'sell' in text_lower:
        result.side = "sell"

    # Parse "most profitable" and selection criteria
    # Normalize hyphens to spaces for matching (e.g. "highest-performing" -> "highest performing")
    _text_norm = text_lower.replace('-', ' ')
    _highest_perf_phrases = (
        'most profitable', 'best performing', 'top gainer', 'highest performing',
        'best return', 'top performing', 'top performer', 'best crypto',
        'top crypto', 'strongest', 'leading crypto', 'outperforming',
        'highest returning', 'best gains',
    )
    if any(phrase in _text_norm for phrase in _highest_perf_phrases):
        result.is_most_profitable = True
        result.selection_criteria = "highest_performing"
    elif 'moving up' in _text_norm or 'momentum' in _text_norm or 'rising' in _text_norm:
        result.is_most_profitable = True
        result.selection_criteria = "momentum"
    elif 'worst performing' in _text_norm or 'lowest performing' in _text_norm:
        result.is_most_profitable = True
        result.selection_criteria = "lowest_performing"

    # Parse threshold filters (e.g., "up 20%", "down 5%", "> 10%")
    threshold_match = re.search(r'(?:up|above|over|>)\s*(\d+(?:\.\d+)?)\s*%', text_lower)
    if threshold_match:
        result.threshold_pct = float(threshold_match.group(1))
    else:
        threshold_match = re.search(r'(?:down|below|under|<)\s*(\d+(?:\.\d+)?)\s*%', text_lower)
        if threshold_match:
            result.threshold_pct = -float(threshold_match.group(1))

    # Parse universe constraints
    if 'only majors' in text_lower or 'majors only' in text_lower or 'major crypto' in text_lower:
        result.universe_constraint = "majors_only"
    elif 'exclude stablecoin' in text_lower or 'no stablecoin' in text_lower:
        result.universe_constraint = "exclude_stablecoins"
    elif 'top by volume' in text_lower or 'highest volume' in text_lower:
        result.universe_constraint = "top_25_volume"

    # Parse lookback period using enterprise timeframe parser
    # Supports: relative, anchored (since Monday, YTD), bounded (between dates)
    try:
        from backend.services.timeframe_parser import parse_timeframe, emit_timeframe_parse_telemetry
        
        parse_result = parse_timeframe(text, default_hours=24.0)
        if parse_result.success and parse_result.time_window:
            result.lookback_hours = parse_result.time_window.lookback_hours
            result.time_window = parse_result.time_window.to_dict()
            
            # Emit telemetry for timeframe parsing
            emit_timeframe_parse_telemetry(parse_result, text)
    except Exception:
        # Fallback to legacy parsing if timeframe_parser fails
        time_pattern = r'(?:last\s+)?(\d+)\s*(min(?:ute)?s?|m|hours?|h|days?|d|weeks?|w)\b'
        time_match = re.search(time_pattern, text_lower)
        
        if time_match:
            value = int(time_match.group(1))
            unit = time_match.group(2).lower()
            
            if unit.startswith('min') or unit == 'm':
                result.lookback_hours = max(0.1, value / 60.0)
            elif unit.startswith('hour') or unit == 'h':
                result.lookback_hours = float(value)
            elif unit.startswith('day') or unit == 'd':
                result.lookback_hours = float(value * 24)
            elif unit.startswith('week') or unit == 'w':
                result.lookback_hours = float(value * 24 * 7)
        else:
            # Legacy simple patterns as fallback
            if 'last 48' in text_lower or '48 hour' in text_lower or '48h' in text_lower or '2 day' in text_lower:
                result.lookback_hours = 48.0
            elif 'last 24' in text_lower or '24 hour' in text_lower or '24h' in text_lower:
                result.lookback_hours = 24.0
            elif 'last 7 day' in text_lower or '7 day' in text_lower or '1 week' in text_lower:
                result.lookback_hours = 168.0
            elif 'last hour' in text_lower or '1 hour' in text_lower or '1h' in text_lower:
                result.lookback_hours = 1.0

    # Parse amount (USD) - support multiple formats:
    # - "$10" or "$10.50" (dollar sign before)
    # - "10$" or "10.50$" (dollar sign after)
    # - "10 USD" or "10 usd" or "10USD"
    # - "10 dollars" or "10 dollar"
    
    # Format 1: $X (dollar sign before amount)
    usd_match = re.search(r'\$\s*(\d+(?:\.\d+)?)', text)
    if usd_match:
        result.amount_usd = float(usd_match.group(1))
    
    # Format 2: X$ (dollar sign after amount)
    if result.amount_usd is None:
        usd_match = re.search(r'(\d+(?:\.\d+)?)\s*\$', text)
        if usd_match:
            result.amount_usd = float(usd_match.group(1))
    
    # Format 3: X USD or X usd (with or without space)
    if result.amount_usd is None:
        usd_match = re.search(r'(\d+(?:\.\d+)?)\s*usd\b', text_lower)
        if usd_match:
            result.amount_usd = float(usd_match.group(1))
    
    # Format 4: X dollars or X dollar
    if result.amount_usd is None:
        usd_match = re.search(r'(\d+(?:\.\d+)?)\s*dollars?\b', text_lower)
        if usd_match:
            result.amount_usd = float(usd_match.group(1))

    # === Detect asset class from keywords first ===
    has_crypto_keyword = any(kw in text_lower for kw in CRYPTO_KEYWORDS)
    has_stock_keyword = any(kw in text_lower for kw in STOCK_KEYWORDS)

    # === Parse asset/symbol and determine asset_class ===
    found_crypto = None
    found_stock = None

    # Check crypto symbols (check longer names first to avoid partial matches)
    for alias, symbol in sorted(CRYPTO_SYMBOLS.items(), key=lambda x: -len(x[0])):
        # Use word boundary matching to avoid false positives
        if re.search(rf'\b{re.escape(alias)}\b', text_lower):
            found_crypto = symbol
            break

    # Check stock symbols (check longer names first)
    for alias, symbol in sorted(STOCK_SYMBOLS.items(), key=lambda x: -len(x[0])):
        if re.search(rf'\b{re.escape(alias)}\b', text_lower):
            found_stock = symbol
            break

    # === Determine asset_class and asset ===
    # Priority: explicit keyword > symbol lookup > default (CRYPTO)

    if has_stock_keyword and not has_crypto_keyword:
        # User explicitly said "stock" or "equity"
        result.asset_class = "STOCK"
        result.asset = found_stock  # May be None if symbol not recognized
    elif has_crypto_keyword and not has_stock_keyword:
        # User explicitly said "crypto" or "coin"
        result.asset_class = "CRYPTO"
        result.asset = found_crypto  # May be None if symbol not recognized
    elif found_crypto and not found_stock:
        # Symbol found only in crypto dict
        result.asset_class = "CRYPTO"
        result.asset = found_crypto
    elif found_stock and not found_crypto:
        # Symbol found only in stock dict
        result.asset_class = "STOCK"
        result.asset = found_stock
    elif found_crypto and found_stock:
        # Symbol found in both dicts (unlikely but handle it)
        # Use keyword to disambiguate, or mark as ambiguous
        if has_stock_keyword:
            result.asset_class = "STOCK"
            result.asset = found_stock
        elif has_crypto_keyword:
            result.asset_class = "CRYPTO"
            result.asset = found_crypto
        else:
            result.asset_class = "AMBIGUOUS"
            result.asset = found_crypto  # Default to crypto
    elif has_stock_keyword and has_crypto_keyword:
        # Both keywords present, no symbol match - ambiguous
        result.asset_class = "AMBIGUOUS"
    else:
        # No symbol found, no keyword - default to CRYPTO for backwards compatibility
        result.asset_class = "CRYPTO"

    # === Determine execution mode ===
    # 1. Check for explicit paper/simulation keywords
    if any(keyword in text_lower for keyword in ['paper', 'simulation', 'test trade']):
        result.mode = "PAPER"
    # 2. Check test environment
    elif detect_test_environment():
        result.mode = "PAPER"
    # 3. STOCK asset class -> ASSISTED_LIVE (user executes manually)
    elif result.asset_class == "STOCK":
        result.mode = "ASSISTED_LIVE"
    # 4. Default: respect EXECUTION_MODE_DEFAULT from config, then check LIVE guards
    else:
        from backend.core.config import get_settings
        settings = get_settings()
        default_mode = getattr(settings, 'execution_mode_default', 'PAPER').upper()
        if default_mode == "PAPER":
            result.mode = "PAPER"
        elif settings.trading_disable_live or not settings.enable_live_trading:
            result.mode = "PAPER"
        else:
            result.mode = "LIVE"

    # Derive venue_symbol from asset and asset_class
    if result.asset:
        if result.asset_class == "CRYPTO":
            result.venue_symbol = f"{result.asset}-USD"
        else:
            result.venue_symbol = result.asset

    # --- Dynamic symbol resolution for unrecognised assets ---
    # If no asset was matched from hardcoded maps but the user specified
    # something that looks like a symbol, try dynamic resolution.
    if result.asset is None and not result.is_most_profitable and not result.is_sell_last_purchase:
        # Extract candidate symbol tokens from the text
        # Look for uppercase words (2-10 chars) that could be tickers
        _candidate_tokens = re.findall(r'\b([A-Z]{2,10})\b', text)
        # Also try the word after "of" (common in "sell $2 of MORPHO")
        _of_match = re.search(r'\bof\s+(\w+)', text_lower)
        if _of_match:
            _candidate_tokens.insert(0, _of_match.group(1).upper())

        for tok in _candidate_tokens:
            # Skip common English words and command words
            if tok.upper() in {'BUY', 'SELL', 'USD', 'THE', 'FOR', 'AND', 'LAST', 'MOST', 'BEST', 'TOP', 'OF', 'MY', 'IN', 'AT'}:
                continue
            try:
                from backend.services.symbol_resolver import resolve as resolve_symbol
                resolved = resolve_symbol(tok.upper())
                if resolved:
                    result.asset = resolved.base_symbol
                    result.venue_symbol = resolved.product_id
                    result.resolution_source = resolved.source
                    result.asset_class = "CRYPTO"  # Dynamic resolution defaults to crypto
                    break
            except Exception:
                pass

    return result


def is_missing_amount(parsed: ParsedTradeCommand) -> bool:
    """Check if amount is missing from parsed command."""
    return parsed.amount_usd is None


def is_missing_asset(parsed: ParsedTradeCommand) -> bool:
    """Check if asset is missing (and not a 'most profitable' query)."""
    return parsed.asset is None and not parsed.is_most_profitable
