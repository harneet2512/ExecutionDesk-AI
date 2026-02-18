"""MCP server for broker operations."""
import json
from typing import Dict, Any
from backend.providers.coinbase_provider import CoinbaseProvider
from backend.providers.paper import PaperProvider
from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.core.tool_calls import record_tool_call_sync as record_tool_call

logger = get_logger(__name__)


class BrokerMCPServer:
    """MCP server for broker operations."""
    
    def __init__(self, execution_mode: str = "PAPER"):
        self.execution_mode = execution_mode
        
        if execution_mode == "LIVE":
            settings = get_settings()
            try:
                self.provider = CoinbaseProvider()
            except Exception as e:
                logger.error(f"Failed to initialize Coinbase provider: {e}")
                raise
        else:
            self.provider = PaperProvider()
    
    def place_order(
        self,
        run_id: str,
        node_id: str,
        tenant_id: str,
        symbol: str,
        side: str,
        notional_usd: float,
        qty: float = None,
        client_order_id: str = None
    ) -> Dict[str, Any]:
        """
        Place an order via broker.
        
        Returns:
            {order_id: str, status: str, provider: str}
        """
        # Normalize symbol to product_id format (e.g. BTC -> BTC-USD)
        from backend.core.symbols import to_product_id
        product_id = to_product_id(symbol)

        request_json = {
            "symbol": product_id,
            "side": side,
            "notional_usd": notional_usd,
            "qty": qty
        }

        # Pre-flight: verify product metadata is reachable for LIVE orders
        # NOTE: coinbase_provider._validate_product_constraints has its own
        # fallback logic (exchange-API generic defaults), so this check is
        # intentionally lenient — we only hard-reject if the product is NOT
        # listed on the public Coinbase Exchange API at all.
        if self.execution_mode == "LIVE":
            try:
                from backend.services.market_metadata import get_metadata_service
                svc = get_metadata_service()
                probe = svc.get_product_details_sync(product_id, allow_stale=True)
                if not probe.success:
                    # Metadata API failed — check if the product is at least
                    # listed on the public Exchange API before rejecting.
                    # The provider has generic fallback precision for these.
                    try:
                        from backend.services.asset_selection_engine import get_tradeable_product_ids
                        tradeable = get_tradeable_product_ids()
                        if product_id in tradeable:
                            logger.info(
                                "BROKER_PREFLIGHT_FALLBACK: %s metadata unavailable but listed on exchange; "
                                "deferring to provider fallback precision",
                                product_id
                            )
                        else:
                            from backend.core.error_codes import TradeErrorException, TradeErrorCode
                            raise TradeErrorException(
                                error_code=TradeErrorCode.PRODUCT_DETAILS_UNAVAILABLE,
                                message=f"Product {product_id} is not listed on Coinbase Exchange. Cannot trade.",
                                remediation="Verify the product symbol is correct and listed on Coinbase."
                            )
                    except ImportError:
                        logger.warning("asset_selection_engine not available for fallback check")
            except ImportError:
                logger.warning("market_metadata service not available, skipping pre-flight check")
            except Exception as preflight_err:
                # If it's already a TradeErrorException, re-raise; otherwise log and continue
                if hasattr(preflight_err, 'error_code'):
                    raise
                logger.warning("Pre-flight product check failed (non-fatal): %s", str(preflight_err)[:200])

        try:
            # Pass client_order_id if provided (for idempotency)
            if self.execution_mode == "LIVE" and client_order_id:
                order_id = self.provider.place_order(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    symbol=product_id,
                    side=side,
                    notional_usd=notional_usd,
                    qty=qty,
                    node_id=node_id,
                    client_order_id=client_order_id
                )
            else:
                # Paper provider doesn't need node_id/client_order_id
                order_id = self.provider.place_order(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    symbol=product_id,
                    side=side,
                    notional_usd=notional_usd,
                    qty=qty
                )
            
            response_json = {
                "order_id": order_id,
                "status": "SUBMITTED",
                "provider": self.execution_mode
            }
            
            # Record tool call (redact sensitive data)
            redacted_request = request_json.copy()
            record_tool_call(
                run_id=run_id,
                node_id=node_id,
                tool_name="place_order",
                mcp_server="broker_server",
                request_json=redacted_request,
                response_json=response_json,
                status="SUCCESS"
            )
            
            return response_json
            
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            response_json = {"error": str(e), "status": "FAILED"}
            record_tool_call(
                run_id=run_id,
                node_id=node_id,
                tool_name="place_order",
                mcp_server="broker_server",
                request_json=request_json,
                response_json=response_json,
                status="FAILED"
            )
            raise
    
    def get_balances(
        self,
        run_id: str,
        node_id: str,
        tenant_id: str
    ) -> Dict[str, Any]:
        """Get account balances."""
        request_json = {"tenant_id": tenant_id}
        
        try:
            balances = self.provider.get_balances(tenant_id)
            
            response_json = balances
            
            record_tool_call(
                run_id=run_id,
                node_id=node_id,
                tool_name="get_balances",
                mcp_server="broker_server",
                request_json=request_json,
                response_json=response_json,
                status="SUCCESS"
            )
            
            return response_json
            
        except Exception as e:
            logger.error(f"Balance fetch failed: {e}")
            response_json = {"error": str(e)}
            record_tool_call(
                run_id=run_id,
                node_id=node_id,
                tool_name="get_balances",
                mcp_server="broker_server",
                request_json=request_json,
                response_json=response_json,
                status="FAILED"
            )
            raise
