"""LLM-based intent classifier with regex fallback.

Provides structured intent classification using OpenAI's JSON mode.
Falls back to regex-based parsing when:
- OPENAI_API_KEY is not set
- The OpenAI API call fails or times out (3s max)
- The response cannot be parsed

The LLM classifier is the FALLBACK for ambiguous cases, not the primary
parser. The regex path handles obvious cases ("buy $5 of BTC") without
any API call. The LLM is invoked only when regex confidence is low.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── CONFIRM / CANCEL synonym sets ──────────────────────────────────────

CONFIRM_SYNONYMS = frozenset({
    "CONFIRM", "CONFIRM LIVE", "YES", "OK", "PROCEED",
    "GO AHEAD", "DO IT", "EXECUTE", "APPROVED", "GO",
})

CANCEL_SYNONYMS = frozenset({
    "CANCEL", "NO", "NEVERMIND", "NEVER MIND", "STOP",
    "ABORT", "DONT", "DON'T", "NOPE", "SKIP",
})


# ── ParsedIntent dataclass ─────────────────────────────────────────────

@dataclass
class ParsedIntent:
    """Structured output from the LLM or regex classifier."""
    action: str  # BUY, SELL, QUERY, PORTFOLIO_ANALYSIS, GREETING, OUT_OF_SCOPE, CONFIRM, CANCEL, PREDICTION_MARKET
    asset: Optional[str] = None  # BTC, ETH, AAPL, etc.
    amount_usd: Optional[float] = None
    side: Optional[str] = None  # BUY or SELL
    strategy: Optional[str] = None  # TOP_PERFORMER, WORST_PERFORMER, etc.
    timeframe: Optional[str] = None  # 24h, 48h, 7d, 30d
    outcome: Optional[str] = None  # YES/NO for prediction markets
    market_query: Optional[str] = None  # for prediction market search
    confidence: float = 0.0  # 0.0-1.0
    raw_text: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────

def _get_openai_key() -> Optional[str]:
    """Return OpenAI API key from settings, or None."""
    try:
        from backend.core.config import get_settings
        key = get_settings().openai_api_key
        return key if key else None
    except Exception:
        return None


def _get_openai_model() -> str:
    """Return OpenAI model name from settings."""
    try:
        from backend.core.config import get_settings
        return get_settings().openai_model
    except Exception:
        return "gpt-4o-mini"


# ── LLM system prompt ──────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an intent classifier for a crypto/stock trading platform.

Given user text, classify it into a structured JSON object with these fields:

{
  "action": "<one of: BUY, SELL, QUERY, PORTFOLIO_ANALYSIS, GREETING, OUT_OF_SCOPE, CONFIRM, CANCEL, PREDICTION_MARKET>",
  "asset": "<symbol like BTC, ETH, AAPL, or null>",
  "amount_usd": <number or null>,
  "side": "<BUY or SELL or null>",
  "strategy": "<TOP_PERFORMER, WORST_PERFORMER, MOMENTUM, or null>",
  "timeframe": "<e.g. 24h, 48h, 7d, 30d, or null>",
  "outcome": "<YES or NO for prediction markets, or null>",
  "market_query": "<search text for prediction markets, or null>",
  "confidence": <0.0 to 1.0>
}

RULES:
- Normalize common typos: "byu" -> BUY, "sel" -> SELL, "etherium" -> ETH
- Recognize colloquial phrasings:
  "pick up some" / "grab" / "get" / "invest in" -> BUY
  "get rid of" / "dump" / "offload" / "unload" -> SELL
  "what's the price" / "how much is" / "check" -> QUERY
  "analyze my portfolio" / "how's my portfolio" -> PORTFOLIO_ANALYSIS
- Map common names to symbols:
  bitcoin -> BTC, ethereum -> ETH, solana -> SOL, dogecoin -> DOGE, etc.
- "best performing" / "top performer" / "most profitable" -> strategy = TOP_PERFORMER
- "worst performing" / "biggest loser" -> strategy = WORST_PERFORMER
- "momentum" / "rising" / "moving up" -> strategy = MOMENTUM
- Prediction market keywords: "polymarket", "prediction", "odds", "probability"
- CONFIRM synonyms: "yes", "ok", "proceed", "go ahead", "do it"
- CANCEL synonyms: "no", "nevermind", "stop", "abort"

Return ONLY the JSON object. No markdown, no explanation.\
"""


# ── OpenAI call ─────────────────────────────────────────────────────────

def _openai_classify(text: str) -> dict:
    """Call OpenAI to classify intent. Raises on failure.

    Timeout: 3 seconds hard limit.
    """
    api_key = _get_openai_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=3.0)
    response = client.chat.completions.create(
        model=_get_openai_model(),
        max_tokens=300,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    raw = (response.choices[0].message.content or "").strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


# ── Regex fallback classifier ──────────────────────────────────────────

# Crypto symbols for regex fallback (subset of trade_parser's full map)
_CRYPTO_ALIASES = {
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
    'xrp': 'XRP', 'ripple': 'XRP',
    'ltc': 'LTC', 'litecoin': 'LTC',
    'near': 'NEAR', 'sui': 'SUI',
}

_GREETING_RE = re.compile(
    r'^(hi|hello|hey|yo|sup|howdy|greetings|good\s+(morning|afternoon|evening|day))\b',
    re.IGNORECASE,
)

_PORTFOLIO_RE = re.compile(
    r'(analyze|analysis|summary|health|breakdown)\s+(my\s+)?(crypto\s+|stock\s+)?portfolio'
    r'|portfolio\s+(analysis|summary|health|breakdown)'
    r'|how\s+is\s+(my\s+)?portfolio',
    re.IGNORECASE,
)

_BUY_RE = re.compile(
    r'\b(buy|purchase|invest|pick\s+up|grab|get)\b',
    re.IGNORECASE,
)

_SELL_RE = re.compile(
    r'\b(sell|dump|get\s+rid\s+of|offload|unload|liquidate|exit|close)\b',
    re.IGNORECASE,
)


def _regex_fallback_classify(text: str) -> ParsedIntent:
    """Classify using regex patterns. Always returns a ParsedIntent."""
    text_lower = text.lower().strip()

    # Check confirmation/cancellation first
    conf = classify_confirmation(text)
    if conf == "CONFIRM":
        return ParsedIntent(action="CONFIRM", confidence=0.99, raw_text=text)
    if conf == "CANCEL":
        return ParsedIntent(action="CANCEL", confidence=0.99, raw_text=text)

    # Greeting
    if _GREETING_RE.search(text_lower):
        return ParsedIntent(action="GREETING", confidence=0.95, raw_text=text)

    # Portfolio analysis
    if _PORTFOLIO_RE.search(text_lower):
        return ParsedIntent(action="PORTFOLIO_ANALYSIS", confidence=0.9, raw_text=text)

    # Determine side
    side = None
    action = "QUERY"
    if _BUY_RE.search(text_lower):
        side = "BUY"
        action = "BUY"
    elif _SELL_RE.search(text_lower):
        side = "SELL"
        action = "SELL"

    # Extract amount
    amount_usd = None
    usd_match = re.search(r'\$\s*(\d+(?:\.\d+)?)', text)
    if usd_match:
        amount_usd = float(usd_match.group(1))
    else:
        usd_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:dollars?|usd)\b', text_lower)
        if usd_match:
            amount_usd = float(usd_match.group(1))

    # Extract asset
    asset = None
    for alias, symbol in sorted(_CRYPTO_ALIASES.items(), key=lambda x: -len(x[0])):
        if re.search(rf'\b{re.escape(alias)}\b', text_lower):
            asset = symbol
            break

    # Strategy
    strategy = None
    text_norm = text_lower.replace('-', ' ')
    if any(p in text_norm for p in ('most profitable', 'best performing', 'top gainer',
                                     'highest performing', 'top performer')):
        strategy = "TOP_PERFORMER"
        if action == "QUERY":
            action = "BUY"
            side = "BUY"
    elif any(p in text_norm for p in ('worst performing', 'biggest loser', 'lowest performing')):
        strategy = "WORST_PERFORMER"

    # If still QUERY but has price keywords
    if action == "QUERY" and any(kw in text_lower for kw in ('price', 'how much', 'what is', 'check')):
        action = "QUERY"

    # Confidence: higher when more fields are filled
    filled = sum(1 for v in [side, asset, amount_usd, strategy] if v is not None)
    confidence = min(0.5 + filled * 0.1, 0.8)

    return ParsedIntent(
        action=action,
        asset=asset,
        amount_usd=amount_usd,
        side=side,
        strategy=strategy,
        confidence=confidence,
        raw_text=text,
    )


# ── Public API ──────────────────────────────────────────────────────────

def classify_confirmation(text: str) -> Optional[str]:
    """Classify text as CONFIRM, CANCEL, or None (not a confirmation command).

    Uses expanded synonym sets for both CONFIRM and CANCEL.
    """
    upper = text.strip().upper()
    if upper in CONFIRM_SYNONYMS:
        return "CONFIRM"
    if upper in CANCEL_SYNONYMS:
        return "CANCEL"
    return None


def classify_with_llm(text: str) -> ParsedIntent:
    """Classify user intent, using LLM when available, regex as fallback.

    Flow:
    1. If no OpenAI key, use regex immediately.
    2. Try LLM classification (3s timeout).
    3. On any failure, fall back to regex.

    Returns ParsedIntent (never raises).
    """
    # Fast path: if no API key, skip LLM entirely
    if not _get_openai_key():
        logger.debug("No OpenAI key configured; using regex fallback")
        return _regex_fallback_classify(text)

    try:
        data = _openai_classify(text)
        intent = ParsedIntent(
            action=data.get("action", "QUERY"),
            asset=data.get("asset"),
            amount_usd=data.get("amount_usd"),
            side=data.get("side"),
            strategy=data.get("strategy"),
            timeframe=data.get("timeframe"),
            outcome=data.get("outcome"),
            market_query=data.get("market_query"),
            confidence=float(data.get("confidence", 0.5)),
            raw_text=text,
        )
        logger.info(
            "LLM classify OK: action=%s asset=%s confidence=%.2f text=%s",
            intent.action, intent.asset, intent.confidence, text[:60],
        )
        return intent
    except Exception as exc:
        logger.warning("LLM classify failed (falling back to regex): %s", str(exc)[:200])
        return _regex_fallback_classify(text)
