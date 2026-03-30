"""Base market data provider interface."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class MarketDataProvider(ABC):
    """Abstract base class for market data providers."""
    
    @abstractmethod
    def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get candles for a symbol.
        
        Args:
            symbol: Trading pair (e.g., "BTC-USD")
            interval: Time interval (1h, 24h)
            start_time: ISO timestamp (optional)
            end_time: ISO timestamp (optional)
            limit: Max number of candles
        
        Returns:
            List of candles: [{start_time, end_time, open, high, low, close, volume}, ...]
        """
        pass
    
    @abstractmethod
    def get_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        pass
