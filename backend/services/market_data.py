"""Market data service - uses provider factory with symbol normalization."""
from backend.core.logging import get_logger
from backend.services.market_data_provider import get_market_data_provider
from backend.core.symbols import to_base

logger = get_logger(__name__)


class MarketDataError(Exception):
    """Market data error."""
    pass


def get_price(symbol: str) -> float:
    """
    Get price for a symbol.
    
    Uses provider factory to select appropriate provider (test/live).
    Normalizes symbol to base asset for price lookup.
    
    Args:
        symbol: Symbol in any format (SOL, SOL-USD, etc.)
    
    Returns:
        Price as float
    """
    provider = get_market_data_provider()
    
    # Normalize to base asset for price lookup (provider uses base asset keys)
    base = to_base(symbol)
    
    try:
        # Use provider's get_price method (handles normalization internally)
        return provider.get_price(symbol)
    except Exception as e:
        logger.error(f"Price fetch failed for {symbol} (base: {base}): {e}")
        raise MarketDataError(f"Failed to get price for {symbol}: {str(e)}")
