"""Symbol normalization utilities."""
from typing import Optional


def to_product_id(symbol: str) -> str:
    """
    Convert symbol to canonical product_id format (BASE-USD).
    
    Examples:
        "SOL" -> "SOL-USD"
        "SOL-USD" -> "SOL-USD"
        "btc" -> "BTC-USD"
        "ETH-USD" -> "ETH-USD"
    """
    symbol = symbol.upper().strip()
    if "-" in symbol:
        # Already in product_id format, just uppercase
        return symbol
    else:
        # Base asset only, append -USD
        return f"{symbol}-USD"


def to_base(symbol: str) -> str:
    """
    Convert symbol to base asset (remove quote currency).
    
    Examples:
        "SOL-USD" -> "SOL"
        "BTC-USD" -> "BTC"
        "SOL" -> "SOL"
        "btc" -> "BTC"
    """
    symbol = symbol.upper().strip()
    if "-" in symbol:
        # Extract base asset (part before "-")
        return symbol.split("-")[0]
    else:
        # Already base asset
        return symbol
