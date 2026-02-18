"""Base provider interface."""
from abc import ABC, abstractmethod
from typing import Dict, Any, List


class BrokerProvider(ABC):
    """Abstract base class for broker providers."""
    
    @abstractmethod
    def place_order(
        self,
        run_id: str,
        tenant_id: str,
        symbol: str,
        side: str,
        notional_usd: float,
        qty: float = None
    ) -> str:
        """Place an order. Returns order_id."""
        pass
    
    @abstractmethod
    def get_positions(self, tenant_id: str) -> Dict[str, Any]:
        """Get current positions."""
        pass
    
    @abstractmethod
    def get_balances(self, tenant_id: str, run_id: str = None, node_id: str = None) -> Dict[str, Any]:
        """Get account balances."""
        pass
    
    def get_fills(self, order_id: str, run_id: str = None, node_id: str = None) -> List[Dict[str, Any]]:
        """Get order fills (optional - only Coinbase implements)."""
        return []