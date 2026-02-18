"""Intent parser - converts natural language to structured intent."""
import json
import re
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from backend.core.logging import get_logger

logger = get_logger(__name__)


class TradeIntent(BaseModel):
    """Structured trade intent schema."""
    action: str = Field(..., description="BUY or SELL")
    objective: str = Field(..., description="MOST_PROFITABLE, DIRECT_ASSET, etc.")
    asset_class: str = Field(..., description="CRYPTO, STOCK, etc.")
    budget_usd: float = Field(..., description="Budget in USD")
    lookback_hours: int = Field(..., description="Lookback window in hours (default 24)")
    universe: list = Field(default_factory=list, description="Allowed symbols (empty = use default)")
    constraints: Dict[str, Any] = Field(default_factory=dict, description="Additional constraints")
    raw_command: str = Field(..., description="Original command text")


def parse_intent(
    text: str,
    budget_usd: float = 10.0,
    universe: Optional[list] = None,
    lookback_hours: int = 24
) -> TradeIntent:
    """
    Parse natural language command into structured TradeIntent.
    
    Examples:
        - "Buy me the most profitable crypto of the last 24 hours for $10"
        - "buy $10 of BTC"
        - "sell $50 worth of ETH"
    
    Returns:
        TradeIntent object
    """
    text_lower = text.lower().strip()
    
    # Determine action (BUY or SELL)
    action = "BUY"
    if "sell" in text_lower:
        action = "SELL"
    
    # Extract budget
    budget = budget_usd
    budget_match = re.search(r'\$(\d+(?:\.\d+)?)', text)
    if budget_match:
        budget = float(budget_match.group(1))
    
    # Determine objective
    objective = "DIRECT_ASSET"
    if "most profitable" in text_lower or "best performing" in text_lower or "top" in text_lower:
        objective = "MOST_PROFITABLE"
    
    # Extract lookback hours
    lookback = lookback_hours
    if "24 hour" in text_lower or "last 24" in text_lower:
        lookback = 24
    elif "7 day" in text_lower or "last week" in text_lower:
        lookback = 168  # 7 * 24
    elif "1 hour" in text_lower or "last hour" in text_lower:
        lookback = 1
    
    # Determine asset class
    asset_class = "CRYPTO"
    if "stock" in text_lower or "equity" in text_lower:
        asset_class = "STOCK"
    
    # Extract universe (specific symbols)
    parsed_universe = universe or []
    symbol_map = {
        "bitcoin": "BTC-USD", "btc": "BTC-USD",
        "ethereum": "ETH-USD", "eth": "ETH-USD",
        "solana": "SOL-USD", "sol": "SOL-USD",
        "polygon": "MATIC-USD", "matic": "MATIC-USD",
        "avalanche": "AVAX-USD", "avax": "AVAX-USD",
    }
    
    found_symbols = []
    for key, symbol in symbol_map.items():
        if key in text_lower:
            found_symbols.append(symbol)
    
    if found_symbols:
        parsed_universe = found_symbols
    elif objective == "MOST_PROFITABLE":
        # Default universe for "most profitable" queries
        parsed_universe = ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "AVAX-USD"]
    
    # Extract constraints
    constraints = {}
    if "limit" in text_lower:
        constraints["order_type"] = "limit"
    if "market" in text_lower:
        constraints["order_type"] = "market"
    if "max" in text_lower:
        max_match = re.search(r'max[_\s]+(\d+)', text_lower)
        if max_match:
            constraints["max_trades"] = int(max_match.group(1))
    
    return TradeIntent(
        action=action,
        objective=objective,
        asset_class=asset_class,
        budget_usd=budget,
        lookback_hours=lookback,
        universe=parsed_universe,
        constraints=constraints,
        raw_command=text
    )


def parse_intent_with_llm(text: str, budget_usd: float = 10.0, universe: Optional[list] = None, lookback_hours: int = 24) -> TradeIntent:
    """
    Parse intent using LLM (optional enhancement - for now falls back to rule-based).
    
    TODO: Integrate with OpenAI or local LLM for better parsing.
    """
    # For now, use rule-based parser
    return parse_intent(text, budget_usd, universe, lookback_hours)
