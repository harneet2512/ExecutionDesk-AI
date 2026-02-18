"""Command parser agent - parses natural language into TradeIntent."""
import re
from typing import Optional
from backend.agents.schemas import TradeIntent
from backend.core.logging import get_logger

logger = get_logger(__name__)


def parse_command(text: str, default_budget: float = 10.0, default_universe: Optional[list] = None) -> TradeIntent:
    """
    Parse natural language command into TradeIntent.
    
    Examples:
        - "buy the most profitable crypto for $10" -> side=BUY, budget=10, metric=return
        - "buy the most profitable crypto of last 24hrs for $10" -> side=BUY, budget=10, metric=return, window=24h
        - "sell $50 of BTC" -> side=SELL, budget=50, universe=["BTC-USD"]
        - "buy $10 of BTC" -> side=BUY, budget=10, universe=["BTC-USD"]
        - "replay run run_xxx" -> (handled separately, not parsed here)
        - "show my performance last 7 days" -> (handled separately, not parsed here)
    """
    text_lower = text.lower().strip()
    
    # Special handling for "replay" and "show" commands (not trade intents)
    if text_lower.startswith("replay run"):
        # Extract run_id if possible, but this command is handled at API level
        pass
    if "show" in text_lower and "performance" in text_lower:
        # Analytics command, not a trade intent - handled at API level
        pass
    
    # Determine side (BUY or SELL)
    side = "BUY"
    if "sell" in text_lower:
        side = "SELL"
    elif "buy" not in text_lower and "purchase" not in text_lower:
        # Default to BUY if not specified
        side = "BUY"
    
    # Extract budget
    budget = default_budget
    budget_match = re.search(r'\$(\d+(?:\.\d+)?)', text)
    if budget_match:
        budget = float(budget_match.group(1))
    else:
        # Try numbers
        num_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:dollar|usd|us\s*dollar)', text_lower)
        if num_match:
            budget = float(num_match.group(1))
    
    # Determine metric (default: return)
    metric = "return"
    if "sharpe" in text_lower or "risk-adjusted" in text_lower:
        metric = "sharpe_proxy"
    elif "momentum" in text_lower:
        metric = "momentum"
    elif "profitable" in text_lower or "profit" in text_lower or "return" in text_lower:
        metric = "return"
    
    # Determine window (default: 24h)
    window = "24h"
    if "1h" in text_lower or "1 hour" in text_lower:
        window = "1h"
    elif "7d" in text_lower or "7 day" in text_lower or "week" in text_lower or "last 7 days" in text_lower:
        window = "7d"
    elif "24h" in text_lower or "24 hour" in text_lower or "day" in text_lower or "last 24hrs" in text_lower or "last 24 hrs" in text_lower:
        window = "24h"
    
    # Extract universe (symbols)
    universe = default_universe or ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "AVAX-USD"]
    
    # Check for specific symbols
    symbols_map = {
        "bitcoin": "BTC-USD",
        "btc": "BTC-USD",
        "ethereum": "ETH-USD",
        "eth": "ETH-USD",
        "solana": "SOL-USD",
        "sol": "SOL-USD",
        "polygon": "MATIC-USD",
        "matic": "MATIC-USD",
        "avalanche": "AVAX-USD",
        "avax": "AVAX-USD",
    }
    
    found_symbols = []
    for key, symbol in symbols_map.items():
        if key in text_lower:
            found_symbols.append(symbol)
    
    if found_symbols:
        universe = found_symbols
    elif "most profitable" in text_lower or "best" in text_lower or "top" in text_lower:
        # Keep default universe for "most profitable" searches
        pass
    else:
        # If no specific symbol mentioned, use full default universe
        universe = default_universe or ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "AVAX-USD"]
    
    # Constraints
    constraints = {}
    if "limit" in text_lower:
        constraints["order_type"] = "limit"
    if "market" in text_lower:
        constraints["order_type"] = "market"
    
    return TradeIntent(
        side=side,
        budget_usd=budget,
        metric=metric,
        window=window,
        universe=universe,
        constraints=constraints,
        raw_command=text
    )
