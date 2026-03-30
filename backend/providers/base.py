"""Base provider interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class BrokerCapabilities:
    """Broker submission constraints exposed to the planner/orchestrator."""
    max_orders_per_submit: int = 1
    supports_batch_submit: bool = False
    sell_uses_base_size: bool = True
    buy_uses_quote_size: bool = True


class BrokerProvider(ABC):
    """Abstract base class for broker providers."""

    capabilities: BrokerCapabilities = BrokerCapabilities()

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