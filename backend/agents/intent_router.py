"""Intent classification router with deterministic rules and hard guardrails."""
import re
from enum import Enum
from typing import Optional, Tuple


class IntentType(str, Enum):
    """Intent taxonomy - single source of truth."""
    GREETING = "GREETING"
    CAPABILITIES_HELP = "CAPABILITIES_HELP"
    FINANCE_ANALYSIS = "FINANCE_ANALYSIS"
    TRADE_EXECUTION = "TRADE_EXECUTION"
    PORTFOLIO = "PORTFOLIO"
    PORTFOLIO_ANALYSIS = "PORTFOLIO_ANALYSIS"  # Deep portfolio analysis with risk/allocation/trading behavior
    APP_DIAGNOSTICS = "APP_DIAGNOSTICS"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


# Keyword sets and patterns
GREETING_PATTERNS = [
    r'^(hi|hello|hey|yo|sup|howdy|greetings)\b',
    r'^good (morning|afternoon|evening|day)\b',
    r'^how are you\b',
    r'^what\'?s up\b',
]

CAPABILITIES_KEYWORDS = [
    'capabilities', 'what can you do', 'what do you do', 'help', 'examples', 'example',
    'how do i use', 'how to use', 'commands', 'supported queries', 'features',
    'what are you', 'who are you', 'introduce yourself'
]

OUT_OF_SCOPE_PATTERNS = [
    # Politics
    r'who is (the )?(president|prime minister|senator|governor|mayor)',
    r'\b(election|vote|voting|ballot|campaign)\b',
    r'\b(democrat|republican|liberal|conservative|party)\b',
    
    # Geography/History
    r'capital of',
    r'history of',
    r'when was .+ (born|founded|created|invented)',
    r'where is .+ located',
    
    # Sports
    r'(sports? score|game score|who won the (game|match|championship))',
    r'\b(nfl|nba|mlb|nhl|fifa|olympics)\b',
    
    # Celebrity/Entertainment
    r'(celebrity|actor|actress|singer|movie|film|tv show)',
    r'who (starred|played|sang)',
    
    # General trivia
    r'what is the (tallest|biggest|smallest|longest)',
    r'how many .+ in the world',
]

FINANCE_KEYWORDS = [
    'buy', 'sell', 'trade', 'order', 'execute', 'purchase',
    'portfolio', 'pnl', 'profit', 'loss', 'gain', 'return',
    'risk', 'volatility', 'drawdown', 'sharpe', 'allocation', 'exposure',
    'btc', 'eth', 'sol', 'ada', 'crypto', 'bitcoin', 'ethereum',
    'candles', 'ohlc', 'price', 'volume', 'market cap',
    'technical', 'indicator', 'moving average', 'rsi', 'macd',
    'bullish', 'bearish', 'trend', 'support', 'resistance',
    'most profitable', 'top gainer', 'top loser', 'best performer',
    'analyze', 'analysis', 'compare', 'comparison',
    'slippage', 'limit', 'market order', 'stop loss',
]

TRADE_EXECUTION_KEYWORDS = [
    'buy', 'sell', 'purchase', 'order', 'execute', 'trade',
    'long', 'short', 'position'
]

PORTFOLIO_KEYWORDS = [
    'portfolio', 'holdings', 'positions', 'allocation', 'exposure',
    'pnl', 'profit and loss', 'performance', 'returns',
    'diversification', 'risk', 'drawdown'
]

# Portfolio analysis patterns - require explicit "analyze" intent
PORTFOLIO_ANALYSIS_PATTERNS = [
    r'analyze\s+(my\s+)?(crypto\s+|stock\s+)?portfolio',
    r'portfolio\s+analysis',
    r'analyze\s+(my\s+)?holdings',
    r'analyze\s+(my\s+)?positions',
    r'analyze\s+(my\s+)?allocation',
    r'portfolio\s+risk\s+analysis',
    r'risk\s+analysis\s+(of\s+)?(my\s+)?portfolio',
    r'how\s+is\s+(my\s+)?portfolio\s+doing',
    r'portfolio\s+health',
    r'portfolio\s+summary',
    r'full\s+portfolio\s+analysis',
    r'deep\s+portfolio\s+analysis',
    r'portfolio\s+breakdown',
    r'trading\s+behavior\s+analysis',
    r'trading\s+summary',
]

# Holdings query patterns - specific asset balance questions that need live data
# These should route to PORTFOLIO_ANALYSIS to fetch real Coinbase data
HOLDINGS_QUERY_PATTERNS = [
    # "How much BTC do I own/have?"
    r'how\s+much\s+(\w+)\s+do\s+i\s+(own|have)',
    # "What is my BTC balance/holding?"
    r'what\s+is\s+(my\s+)?(\w+)\s+(balance|holding|holdings)',
    # "Do I own any BTC?"
    r'do\s+i\s+(own|have)\s+(any\s+)?(\w+)',
    # "My BTC balance" / "BTC balance"
    r'(my\s+)?(\w+)\s+balance\b',
    # "Show my BTC" / "Show me my BTC"
    r'show\s+(me\s+)?(my\s+)?(\w+)\s+(balance|holdings?)',
    # "What's my BTC?"
    r'what\'?s\s+(my\s+)?(\w+)\s*(balance|holding)?',
    # "Check my BTC balance"
    r'check\s+(my\s+)?(\w+)\s+(balance|holdings?)',
]

# Known crypto symbols for holdings query validation
CRYPTO_SYMBOLS = {
    'btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana', 'ada', 'cardano',
    'dot', 'polkadot', 'matic', 'polygon', 'avax', 'avalanche', 'link', 
    'chainlink', 'uni', 'uniswap', 'atom', 'cosmos', 'xrp', 'ripple',
    'doge', 'dogecoin', 'shib', 'ltc', 'litecoin', 'xlm', 'stellar'
}

APP_DIAGNOSTIC_KEYWORDS = [
    'telemetry', 'evals', 'evaluations', 'runs', 'run history',
    'steps panel', 'trace', 'latency', 'errors', 'logs',
    'why was', 'what happened', 'debug', 'status',
    'charts', 'graph', 'visualization'
]


def normalize_text(text: str) -> str:
    """Normalize text for matching: lowercase, trim, collapse whitespace."""
    # Lowercase
    text = text.lower()
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text)
    
    # Remove some punctuation for matching (but keep for context)
    # We'll use the original for pattern matching, but normalized for keyword matching
    return text


def is_greeting(text: str) -> bool:
    """Check if text is a greeting."""
    normalized = normalize_text(text)
    
    for pattern in GREETING_PATTERNS:
        if re.search(pattern, normalized):
            return True
    
    return False


def is_capabilities_help(text: str) -> bool:
    """Check if text is asking for capabilities/help."""
    normalized = normalize_text(text)
    
    for keyword in CAPABILITIES_KEYWORDS:
        if keyword in normalized:
            return True
    
    return False


def is_out_of_scope(text: str) -> bool:
    """Check if text is out of scope (politics, sports, trivia, etc.)."""
    normalized = normalize_text(text)
    
    # Check hard out-of-scope patterns
    for pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, normalized):
            # Exception: if query also contains strong finance keywords, it might be contextual
            # e.g., "how could an election affect BTC volatility?"
            if has_finance_keywords(text):
                # Count finance keywords
                finance_count = sum(1 for kw in FINANCE_KEYWORDS if kw in normalized)
                if finance_count >= 2:  # At least 2 finance keywords = likely finance context
                    return False
            return True
    
    return False


def has_finance_keywords(text: str) -> bool:
    """Check if text contains finance/trading keywords."""
    normalized = normalize_text(text)
    
    for keyword in FINANCE_KEYWORDS:
        if keyword in normalized:
            return True
    
    return False


def has_trade_execution_keywords(text: str) -> bool:
    """Check if text contains trade execution keywords."""
    normalized = normalize_text(text)
    
    for keyword in TRADE_EXECUTION_KEYWORDS:
        if keyword in normalized:
            return True
    
    return False


def has_portfolio_keywords(text: str) -> bool:
    """Check if text contains portfolio keywords."""
    normalized = normalize_text(text)
    
    for keyword in PORTFOLIO_KEYWORDS:
        if keyword in normalized:
            return True
    
    return False


def has_app_diagnostic_keywords(text: str) -> bool:
    """Check if text contains app diagnostic keywords."""
    normalized = normalize_text(text)
    
    for keyword in APP_DIAGNOSTIC_KEYWORDS:
        if keyword in normalized:
            return True
    
    return False


def is_portfolio_analysis_request(text: str) -> bool:
    """Check if text is explicitly requesting portfolio analysis (not just mentioning portfolio)."""
    normalized = normalize_text(text)
    
    for pattern in PORTFOLIO_ANALYSIS_PATTERNS:
        if re.search(pattern, normalized):
            return True
    
    return False


def is_holdings_query(text: str) -> bool:
    """
    Check if text is asking about specific asset holdings.
    
    Examples:
    - "How much BTC do I own?"
    - "What is my ETH balance?"
    - "Do I have any SOL?"
    
    NOT a holdings query:
    - "What's the price of BTC?" (price query)
    - "Analyze BTC volatility" (analysis query)
    """
    normalized = normalize_text(text)
    
    # Exclude price queries
    price_patterns = [
        r'price of',
        r'current price',
        r'what\'?s the price',
        r'how much is (\w+) worth',
        r'(\w+) price\b',  # "BTC price" but not "BTC balance"
    ]
    for pattern in price_patterns:
        if re.search(pattern, normalized):
            return False
    
    for pattern in HOLDINGS_QUERY_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            # Extract the potential asset symbol from the match
            groups = match.groups()
            for g in groups:
                if g and g.lower() in CRYPTO_SYMBOLS:
                    return True
            # Also check if any crypto symbol appears in the text
            for symbol in CRYPTO_SYMBOLS:
                if symbol in normalized:
                    return True
    
    return False


def extract_holdings_asset(text: str) -> Optional[str]:
    """
    Extract the specific asset being queried from a holdings query.
    
    Returns the normalized symbol (uppercase) or None if not found.
    
    Examples:
    - "How much BTC do I own?" -> "BTC"
    - "What is my bitcoin balance?" -> "BTC"
    - "Do I have any ethereum?" -> "ETH"
    """
    normalized = normalize_text(text)
    
    # Symbol normalization map
    symbol_map = {
        'bitcoin': 'BTC', 'btc': 'BTC',
        'ethereum': 'ETH', 'eth': 'ETH',
        'solana': 'SOL', 'sol': 'SOL',
        'cardano': 'ADA', 'ada': 'ADA',
        'polkadot': 'DOT', 'dot': 'DOT',
        'polygon': 'MATIC', 'matic': 'MATIC',
        'avalanche': 'AVAX', 'avax': 'AVAX',
        'chainlink': 'LINK', 'link': 'LINK',
        'uniswap': 'UNI', 'uni': 'UNI',
        'cosmos': 'ATOM', 'atom': 'ATOM',
        'ripple': 'XRP', 'xrp': 'XRP',
        'dogecoin': 'DOGE', 'doge': 'DOGE',
        'shib': 'SHIB',
        'litecoin': 'LTC', 'ltc': 'LTC',
        'stellar': 'XLM', 'xlm': 'XLM',
    }
    
    # Try each pattern to extract asset
    for pattern in HOLDINGS_QUERY_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            groups = match.groups()
            for g in groups:
                if g and g.lower() in symbol_map:
                    return symbol_map[g.lower()]
    
    # Fallback: find any known symbol in the text
    for symbol, normalized_symbol in symbol_map.items():
        if symbol in normalized:
            return normalized_symbol
    
    return None


def classify_intent(text: str) -> IntentType:
    """
    Classify user intent using deterministic rules.
    
    Priority order:
    1. GREETING (high precision)
    2. CAPABILITIES_HELP
    3. OUT_OF_SCOPE (hard block)
    4. APP_DIAGNOSTICS
    5. PORTFOLIO_ANALYSIS (explicit analysis request - must check before TRADE_EXECUTION)
    6. TRADE_EXECUTION (if has trade keywords)
    7. PORTFOLIO (if has portfolio keywords but not explicit analysis request)
    8. FINANCE_ANALYSIS (if has finance keywords)
    9. OUT_OF_SCOPE (default fallback)
    """
    if not text or not text.strip():
        return IntentType.OUT_OF_SCOPE
    
    # 1. Check for greeting (high precision, short queries)
    if is_greeting(text):
        return IntentType.GREETING
    
    # 2. Check for capabilities/help
    if is_capabilities_help(text):
        return IntentType.CAPABILITIES_HELP
    
    # 3. Check for out-of-scope (hard block)
    if is_out_of_scope(text):
        return IntentType.OUT_OF_SCOPE
    
    # 4. Check for app diagnostics
    if has_app_diagnostic_keywords(text):
        return IntentType.APP_DIAGNOSTICS
    
    # 5. Check for explicit portfolio analysis request (BEFORE trade execution check)
    # This handles "Analyze my portfolio" type commands
    if is_portfolio_analysis_request(text):
        return IntentType.PORTFOLIO_ANALYSIS
    
    # 5b. Check for specific asset holdings queries (BEFORE trade execution check)
    # This handles "How much BTC do I own?" type queries that need live data
    if is_holdings_query(text):
        return IntentType.PORTFOLIO_ANALYSIS
    
    # 6. Check for trade execution (buy/sell orders)
    if has_trade_execution_keywords(text):
        return IntentType.TRADE_EXECUTION

    # 7. Check for portfolio vs finance analysis
    # If text has both portfolio and finance keywords with specific crypto symbols,
    # prefer FINANCE_ANALYSIS (e.g., "Compare ETH vs BTC returns")
    is_portfolio = has_portfolio_keywords(text)
    is_finance = has_finance_keywords(text)

    if is_portfolio and is_finance:
        # Count crypto symbols — if present, this is comparative analysis, not portfolio
        normalized = normalize_text(text)
        crypto_symbols = ['btc', 'eth', 'sol', 'ada', 'dot', 'matic', 'avax', 'bitcoin', 'ethereum']
        symbol_count = sum(1 for s in crypto_symbols if s in normalized)
        if symbol_count >= 1:
            return IntentType.FINANCE_ANALYSIS
        return IntentType.PORTFOLIO

    if is_portfolio:
        return IntentType.PORTFOLIO

    # 8. Check for finance analysis
    if is_finance:
        return IntentType.FINANCE_ANALYSIS
    
    # 9. Default: out of scope
    return IntentType.OUT_OF_SCOPE
