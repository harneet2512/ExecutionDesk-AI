"""MCP server for market data operations."""
import json
from typing import Dict, Any, List
from backend.services.market_data_provider import get_market_data_provider
from backend.core.logging import get_logger
from backend.core.tool_calls import record_tool_call_sync as record_tool_call

logger = get_logger(__name__)


class MarketDataMCPServer:
    """MCP server for market data fetching."""
    
    def __init__(self):
        # Use provider factory to select appropriate provider
        self.provider = get_market_data_provider()
    
    def fetch_candles(
        self,
        run_id: str,
        node_id: str,
        symbol: str,
        interval: str,
        start_time: str = None,
        end_time: str = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Fetch candles for a symbol.
        
        Returns:
            {candles: [...], count: N, symbol: str, interval: str}
        """
        request_json = {
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
            "limit": limit
        }
        
        try:
            candles = self.provider.get_candles(symbol, interval, start_time, end_time, limit)
            
            response_json = {
                "candles": candles,
                "count": len(candles),
                "symbol": symbol,
                "interval": interval
            }
            
            # Record tool call
            record_tool_call(
                run_id=run_id,
                node_id=node_id,
                tool_name="fetch_candles",
                mcp_server="market_data_server",
                request_json=request_json,
                response_json=response_json,
                status="SUCCESS"
            )
            
            return response_json
            
        except Exception as e:
            logger.error(f"Market data fetch failed: {e}")
            response_json = {"error": str(e), "candles": []}
            record_tool_call(
                run_id=run_id,
                node_id=node_id,
                tool_name="fetch_candles",
                mcp_server="market_data_server",
                request_json=request_json,
                response_json=response_json,
                status="FAILED"
            )
            raise
    
    def get_current_price(
        self,
        run_id: str,
        node_id: str,
        symbol: str
    ) -> Dict[str, Any]:
        """Get current price for a symbol."""
        request_json = {"symbol": symbol}
        
        try:
            price = self.provider.get_price(symbol)
            
            response_json = {"symbol": symbol, "price": price}
            
            record_tool_call(
                run_id=run_id,
                node_id=node_id,
                tool_name="get_current_price",
                mcp_server="market_data_server",
                request_json=request_json,
                response_json=response_json,
                status="SUCCESS"
            )
            
            return response_json
            
        except Exception as e:
            logger.error(f"Price fetch failed: {e}")
            response_json = {"error": str(e)}
            record_tool_call(
                run_id=run_id,
                node_id=node_id,
                tool_name="get_current_price",
                mcp_server="market_data_server",
                request_json=request_json,
                response_json=response_json,
                status="FAILED"
            )
            raise
    


# Global instance
market_data_server = MarketDataMCPServer()
