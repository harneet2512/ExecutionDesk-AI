"""Coinbase Advanced Trade broker provider (JWT auth with ES256)."""
import os
import json
import time
from typing import Dict, Any, Optional, List
from backend.providers.base import BrokerProvider
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger
from backend.core.config import get_settings
from backend.services.coinbase_auth import build_jwt
from backend.core.tool_calls import record_tool_call_sync as record_tool_call
import httpx

logger = get_logger(__name__)


class CoinbaseProvider(BrokerProvider):
    """Coinbase Advanced Trade provider (real exchange integration)."""
    
    BASE_URL = "https://api.coinbase.com/api/v3/brokerage"
    
    def __init__(self, api_key_name: Optional[str] = None, api_private_key: Optional[str] = None):
        from backend.providers.base import BrokerCapabilities
        self.capabilities = BrokerCapabilities(
            max_orders_per_submit=1,
            supports_batch_submit=False,
            sell_uses_base_size=True,
            buy_uses_quote_size=True,
        )
        settings = get_settings()

        if not settings.enable_live_trading:
            raise ValueError("LIVE_TRADING is disabled. Set ENABLE_LIVE_TRADING=true to enable.")

        self.api_key_name = api_key_name or settings.coinbase_api_key_name
        self.api_private_key = api_private_key or settings.coinbase_api_private_key

        if not self.api_key_name or not self.api_private_key:
            raise ValueError("COINBASE_API_KEY_NAME and COINBASE_API_PRIVATE_KEY required for live trading (CDP JWT auth)")
    
    def _get_headers(self, method: str, path: str) -> Dict[str, str]:
        """Get request headers with JWT token for Coinbase Advanced Trade API (CDP)."""
        jwt_token = build_jwt(
            method=method,
            path=path,
            host="api.coinbase.com",
            api_key_name=self.api_key_name,
            api_private_key_pem=self.api_private_key
        )
        
        return {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }
    
    def _redact_sensitive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive fields for logging."""
        redacted = data.copy()
        for key in ["api_key", "api_secret", "CB-ACCESS-KEY", "CB-ACCESS-SIGN", "CB-ACCESS-TIMESTAMP"]:
            if key in redacted:
                redacted[key] = "***REDACTED***"
        return redacted
    
    def _check_idempotency(self, tenant_id: str, client_order_id: str) -> Optional[str]:
        """Check if order with client_order_id already exists (idempotency)."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT order_id FROM orders 
                WHERE tenant_id = ? AND provider = ? AND client_order_id = ?
                LIMIT 1
                """,
                (tenant_id, "COINBASE", client_order_id)
            )
            row = cursor.fetchone()
            if row:
                return row["order_id"]
        return None
    
    def _get_order_status(self, order_id: str, run_id: str = None, node_id: str = None) -> Optional[Dict[str, Any]]:
        """Get order status from Coinbase (with retry on 429)."""
        path = f"/api/v3/brokerage/orders/historical/{order_id}"
        headers = self._get_headers("GET", path)
        max_attempts = 3
        backoff_seconds = 1
        
        for attempt in range(1, max_attempts + 1):
            start_time = time.time()
            try:
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(f"https://api.coinbase.com{path}", headers=headers)
                    latency_ms = int((time.time() - start_time) * 1000)
                    http_status = response.status_code
                    
                    if http_status == 429:  # Rate limit
                        if attempt < max_attempts:
                            wait_time = backoff_seconds * (2 ** (attempt - 1))
                            logger.warning(f"Rate limited (429), retrying after {wait_time}s (attempt {attempt}/{max_attempts})")
                            time.sleep(wait_time)
                            continue
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    if run_id:
                        record_tool_call(
                            run_id=run_id,
                            node_id=node_id,
                            tool_name="get_order_status",
                            mcp_server="coinbase_provider",
                            request_json={"order_id": order_id},
                            response_json={"status": data.get("status"), "order_id": order_id},
                            status="SUCCESS",
                            latency_ms=latency_ms,
                            http_status=http_status,
                            attempt=attempt
                        )
                    
                    return data
            except Exception as e:
                if attempt == max_attempts:
                    if run_id:
                        record_tool_call(
                            run_id=run_id,
                            node_id=node_id,
                            tool_name="get_order_status",
                            mcp_server="coinbase_provider",
                            request_json={"order_id": order_id},
                            response_json={"error": str(e)},
                            status="FAILED",
                            latency_ms=int((time.time() - start_time) * 1000),
                            error_text=str(e),
                            http_status=getattr(e, "response", None) and getattr(e.response, "status_code", None) or None,
                            attempt=attempt
                        )
                    raise
                wait_time = backoff_seconds * (2 ** (attempt - 1))
                time.sleep(wait_time)
        
        return None
    
    def _poll_order_until_terminal(
        self,
        order_id: str,
        run_id: str,
        tenant_id: str,
        node_id: str = None,
        timeout_seconds: int = 30,
        poll_interval: float = 1.0
    ) -> Dict[str, Any]:
        """Poll order status until terminal state (FILLED, CANCELED, REJECTED) or timeout."""
        start_time = time.time()
        last_status = None
        consecutive_errors = 0
        max_consecutive_errors = 5  # Give up early if we keep getting errors
        
        while time.time() - start_time < timeout_seconds:
            try:
                status_data = self._get_order_status(order_id, run_id, node_id)
                if not status_data:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logger.warning(f"Order {order_id} polling stopped after {consecutive_errors} consecutive errors")
                        break
                    time.sleep(poll_interval)
                    continue
                
                # Reset error counter on successful response
                consecutive_errors = 0
                
                order_status = status_data.get("status", "").upper()
                last_status = order_status
                
                # Update order status in DB
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE orders 
                        SET status = ?, status_updated_at = ?, status_reason = ?
                        WHERE order_id = ?
                        """,
                        (
                            order_status,
                            now_iso(),
                            status_data.get("reject_reason") or status_data.get("reason", ""),
                            order_id
                        )
                    )
                    
                    # Emit status event
                    event_id = new_id("evt_")
                    cursor.execute(
                        """
                        INSERT INTO order_events (id, order_id, event_type, payload_json, ts)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (event_id, order_id, order_status, json.dumps(self._redact_sensitive(status_data)), now_iso())
                    )
                    conn.commit()
                
                # Terminal states
                if order_status in ("FILLED", "CANCELED", "REJECTED", "EXPIRED"):
                    # If filled, fetch and store fills
                    if order_status == "FILLED":
                        self._fetch_and_store_fills(order_id, run_id, tenant_id, node_id)
                    return status_data
                
                time.sleep(poll_interval)
            except Exception as e:
                consecutive_errors += 1
                logger.warning(f"Error polling order {order_id} (attempt {consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"Order {order_id} polling stopped after {consecutive_errors} consecutive errors")
                    break
                time.sleep(poll_interval)
        
        # Timeout or too many errors - mark as SUBMITTED (order was placed, status unknown)
        final_status = "TIMEOUT" if time.time() - start_time >= timeout_seconds else "POLL_FAILED"
        logger.warning(f"Order {order_id} polling ended: {final_status} (last status: {last_status})")
        with get_conn() as conn:
            cursor = conn.cursor()
            # Don't override to TIMEOUT if we already have a status
            if last_status:
                cursor.execute(
                    "UPDATE orders SET status_updated_at = ?, status_reason = ? WHERE order_id = ?",
                    (now_iso(), f"Polling ended: {final_status}", order_id)
                )
            else:
                cursor.execute(
                    "UPDATE orders SET status = ?, status_updated_at = ? WHERE order_id = ?",
                    ("SUBMITTED", now_iso(), order_id)
                )
            conn.commit()
        return {"status": last_status or "SUBMITTED", "order_id": order_id}
    
    def _fetch_and_store_fills(
        self,
        order_id: str,
        run_id: str,
        tenant_id: str,
        node_id: str = None
    ) -> List[Dict[str, Any]]:
        """Fetch fills for an order and store them in DB."""
        fills = self.get_fills(order_id, run_id, node_id)
        
        if not fills:
            return []
        
        # Compute aggregate metrics
        total_size = 0.0
        total_fees = 0.0
        weighted_price_sum = 0.0
        
        with get_conn() as conn:
            cursor = conn.cursor()
            
            for fill_data in fills:
                fill_id = new_id("fill_")
                price = float(fill_data.get("price", 0))
                size = float(fill_data.get("size", 0))
                fee = float(fill_data.get("commission", 0))
                trade_id = fill_data.get("trade_id", "")
                liquidity = fill_data.get("liquidity", "").upper()
                
                product_id = fill_data.get("product_id", "")
                
                cursor.execute(
                    """
                    INSERT INTO fills (
                        fill_id, order_id, run_id, tenant_id, product_id,
                        price, size, fee, trade_id, liquidity_indicator, filled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (fill_id, order_id, run_id, tenant_id, product_id, price, size, fee, trade_id, liquidity, now_iso())
                )
                
                total_size += size
                total_fees += fee
                weighted_price_sum += price * size
            
            # Update order with aggregate metrics
            avg_fill_price = weighted_price_sum / total_size if total_size > 0 else 0.0
            
            cursor.execute(
                """
                UPDATE orders 
                SET filled_qty = ?, avg_fill_price = ?, total_fees = ?
                WHERE order_id = ?
                """,
                (total_size, avg_fill_price, total_fees, order_id)
            )
            conn.commit()
        
        return fills
    
    def _validate_product_constraints(self, product_id: str, notional_usd: float) -> Dict[str, Any]:
        """Fetch and validate product constraints using MarketMetadataService with retry/fallback."""
        from backend.services.market_metadata import get_metadata_service
        from backend.core.error_codes import TradeErrorException, TradeErrorCode

        # Get auth headers for API call (if available)
        path = f"/api/v3/brokerage/products/{product_id}"
        try:
            headers = self._get_headers("GET", path)
        except Exception:
            # Fallback for no-auth (public) requests if we have no creds
            headers = {}
        
        # Use MarketMetadataService sync method (safe inside running event loops)
        service = get_metadata_service()
        result = service.get_product_details_sync(product_id, allow_stale=True, headers=headers)
        
        # If API failed, try to construct a "safe default" product object
        # This allows execution to proceed even if Coinbase metadata API is unreachable
        if not result.success:
            logger.warning(f"Product metadata failed for {product_id}, attempting fallback defaults.")
            upper_product = product_id.upper()

            # Check if the product is listed on the Exchange API (public, no auth)
            product_on_exchange = False
            try:
                from backend.services.asset_selection_engine import get_tradeable_product_ids
                product_on_exchange = upper_product in get_tradeable_product_ids()
            except Exception:
                pass

            if upper_product in ["BTC-USD", "ETH-USD", "SOL-USD"]:
                 # Safe defaults for major cryptos (known precision)
                 product_data = {
                     "product_id": upper_product,
                     "base_min_size": "0.00000001",
                     "base_increment": "0.00000001",
                     "quote_increment": "0.01",
                     "min_market_funds": "1.0"
                 }
            elif product_on_exchange:
                # Product is listed on the Exchange API (status=online) but metadata
                # API failed (likely 401 auth error). Use conservative generic defaults.
                # BUY orders use quote_size (USD) so base precision is less critical.
                logger.warning(
                    "Using generic fallback precision for %s (exchange-listed, metadata API unavailable)",
                    product_id
                )
                product_data = {
                    "product_id": upper_product,
                    "base_min_size": "0.00000001",
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                    "min_market_funds": "1.0",
                    "_fallback": True,  # Flag to indicate this is a fallback
                }
            else:
                # Product not found on exchange listing — genuinely not tradeable
                if result.error_code and result.error_code.value == "PRODUCT_NOT_FOUND":
                    raise TradeErrorException(
                        error_code=TradeErrorCode.PRODUCT_NOT_FOUND,
                        message=f"Product {product_id} not found on Coinbase",
                        remediation="Verify the symbol is correct and supported by Coinbase Advanced Trade."
                    )
                else:
                    raise TradeErrorException(
                        error_code=TradeErrorCode.PRODUCT_DETAILS_UNAVAILABLE,
                        message=f"Failed to fetch product details for {product_id}: {result.error_message}",
                        remediation="Check Coinbase API connectivity and credentials."
                    )
        else:
            product_data = result.data
        
        # Log if using stale cache
        if result.success and result.used_stale_cache:
            logger.warning(
                f"Using stale cache for {product_id} (age: {result.cache_age_seconds}s) "
                f"due to API unavailability"
            )
        
        # Validate min order size
        min_market_funds = product_data.get("min_market_funds", "")
        if min_market_funds:
            try:
                min_notional = float(min_market_funds)
                if notional_usd < min_notional:
                    raise TradeErrorException(
                        error_code=TradeErrorCode.BELOW_MINIMUM_SIZE,
                        message=f"Notional ${notional_usd} below minimum ${min_notional} for {product_id}",
                        remediation="Increase order size to meet minimum requirements."
                    )
            except (ValueError, TypeError):
                pass
        
        return product_data
    
    def _validate_order_locally(self, side: str, product_id: str,
                               order_configuration: dict, product_details: dict,
                               notional_usd: float) -> list:
        """Pre-flight validation before submitting to Coinbase. Returns list of error strings."""
        errors = []
        market_ioc = order_configuration.get("market_market_ioc", {})

        if side == "BUY":
            quote_size = market_ioc.get("quote_size")
            if quote_size:
                qs = float(quote_size)
                min_funds_str = product_details.get("min_market_funds", "0") or "0"
                try:
                    min_funds = float(min_funds_str)
                    if min_funds > 0 and qs < min_funds:
                        errors.append(f"quote_size ${qs:.2f} below min_market_funds ${min_funds:.2f}")
                except (ValueError, TypeError):
                    pass
                if qs <= 0:
                    errors.append("quote_size must be positive")
            if "base_size" in market_ioc:
                errors.append("BUY market order must use quote_size, not base_size")

        elif side == "SELL":
            base_size = market_ioc.get("base_size")
            if base_size:
                bs = float(base_size)
                min_base_str = product_details.get("base_min_size", "0") or "0"
                try:
                    min_base = float(min_base_str)
                    if min_base > 0 and bs < min_base:
                        errors.append(f"base_size {bs:.8f} below base_min_size {min_base:.8f}")
                except (ValueError, TypeError):
                    pass
                if bs <= 0:
                    errors.append("base_size must be positive")
            if "quote_size" in market_ioc:
                errors.append("SELL market order must use base_size, not quote_size")

        return errors

    def _get_current_price(self, product_id: str, run_id: str = None, node_id: str = None) -> Optional[float]:
        """Get current spot price for a product (used for SELL USD-to-base conversion).
        
        Args:
            product_id: Product ID like "BTC-USD"
            run_id: Optional run ID for tool call recording
            node_id: Optional node ID for tool call recording
            
        Returns:
            Current price as float, or None if unavailable
        """
        # Try to get from product ticker endpoint
        path = f"/api/v3/brokerage/products/{product_id}"
        headers = self._get_headers("GET", path)
        start_time = time.time()
        
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"https://api.coinbase.com{path}", headers=headers)
                latency_ms = int((time.time() - start_time) * 1000)
                response.raise_for_status()
                data = response.json()
                
                product = data.get("product", data)
                price = product.get("price")
                
                if price:
                    price_float = float(price)
                    logger.info(f"Current price for {product_id}: ${price_float:.2f}")
                    
                    if run_id:
                        record_tool_call(
                            run_id=run_id,
                            node_id=node_id,
                            tool_name="get_current_price",
                            mcp_server="coinbase_provider",
                            request_json={"product_id": product_id},
                            response_json={"price": price_float},
                            status="SUCCESS",
                            latency_ms=latency_ms,
                            http_status=response.status_code
                        )
                    
                    return price_float
                    
        except Exception as e:
            logger.warning(f"Failed to get price for {product_id}: {e}")
            if run_id:
                record_tool_call(
                    run_id=run_id,
                    node_id=node_id,
                    tool_name="get_current_price",
                    mcp_server="coinbase_provider",
                    request_json={"product_id": product_id},
                    response_json={"error": str(e)},
                    status="FAILED",
                    latency_ms=int((time.time() - start_time) * 1000),
                    error_text=str(e)
                )
        
        return None
    
    def place_order(
        self,
        run_id: str,
        tenant_id: str,
        symbol: str,
        side: str,
        notional_usd: float,
        qty: float = None,
        node_id: str = None,
        client_order_id: Optional[str] = None,
        poll_until_filled: bool = True
    ) -> str:
        """Place order on Coinbase Advanced Trade with side-aware configuration.
        
        CRITICAL: Coinbase market order rules:
        - BUY: use quote_size (USD amount to spend)
        - SELL: use base_size (crypto amount to sell) - NEVER use quote_size
        """
        product_id = symbol
        side_upper = side.upper()
        
        # Generate client_order_id for idempotency if not provided
        if not client_order_id:
            client_order_id = new_id("client_")
        
        # Check idempotency (return existing order if found)
        existing_order_id = self._check_idempotency(tenant_id, client_order_id)
        if existing_order_id:
            logger.info(f"Order with client_order_id {client_order_id} already exists: {existing_order_id}")
            return existing_order_id
        
        # Validate product constraints and get product details using MarketMetadataService
        product_details = {}
        try:
            product_details = self._validate_product_constraints(product_id, notional_usd)
        except ValueError as e:
            logger.error(f"Product validation failed: {e}")
            raise

        # SELL requires product details for precision - fail early if unavailable
        if not product_details and side_upper == "SELL":
            from backend.core.error_codes import TradeErrorException, TradeErrorCode
            raise TradeErrorException(
                error_code=TradeErrorCode.PRODUCT_DETAILS_UNAVAILABLE,
                message=f"Cannot place SELL order for {product_id}: product details unavailable. Cannot determine precision requirements.",
                remediation="Check Coinbase API connectivity. Product metadata is required for SELL orders with proper precision."
            )
        
        # Build side-aware order configuration
        # CRITICAL: SELL must use base_size, BUY uses quote_size
        if side_upper == "BUY":
            # BUY: specify USD amount to spend
            order_configuration = {
                "market_market_ioc": {
                    "quote_size": f"{notional_usd:.2f}"
                }
            }
            logger.info(f"BUY order using quote_size: ${notional_usd:.2f}")
        else:
            # SELL: must use base_size (crypto units)
            # If qty (base_size) is provided directly, use it
            # Otherwise, convert USD to base units using current price
            current_price = None  # Track for min-size error messages
            if qty is not None and qty > 0:
                base_size = qty
            else:
                # Fetch current price to convert USD to base units
                current_price = self._get_current_price(product_id, run_id, node_id)
                if current_price is None or current_price <= 0:
                    raise ValueError(f"Cannot determine price for {product_id} to convert ${notional_usd} to base units")
                
                base_size = notional_usd / current_price
                logger.info(f"SELL: Converted ${notional_usd} to {base_size:.8f} {product_id.split('-')[0]} at price ${current_price:.2f}")
            
            # Apply precision rounding using Decimal to avoid float imprecision
            base_increment = product_details.get("base_increment", "0.00000001")
            try:
                from decimal import Decimal, ROUND_DOWN as _RD
                _inc_d = Decimal(str(base_increment))
                _bs_d = Decimal(str(base_size))
                _eps_d = Decimal("1E-10")
                if _inc_d > 0:
                    base_size = float(
                        ((_bs_d - _eps_d) / _inc_d).to_integral_value(rounding=_RD) * _inc_d
                    )
            except (ValueError, TypeError, ArithmeticError):
                pass
            
            # Validate base_size > 0 after rounding
            if base_size <= 0:
                raise ValueError(
                    f"SELL amount ${notional_usd:.2f} is too small for {product_id} "
                    f"(rounds to 0 base units at increment {base_increment}). "
                    f"Increase order amount."
                )

            # Validate against base_min_size
            base_min_size_str = product_details.get("base_min_size", "0") or "0"
            try:
                base_min_size = float(base_min_size_str)
                if base_min_size > 0 and base_size < base_min_size:
                    min_usd = base_min_size * (current_price or 0)
                    raise ValueError(
                        f"SELL base_size {base_size:.8f} is below minimum {base_min_size:.8f} for {product_id} "
                        f"(≈ ${min_usd:.2f}). "
                        f"Source field: product_details.base_min_size={base_min_size_str!r}."
                    )
            except (ValueError, TypeError) as e:
                if "below minimum" in str(e) or "too small" in str(e):
                    raise

            # Emit debug trace when DEBUG_MIN_RULES=1
            if os.environ.get("DEBUG_MIN_RULES") == "1" and run_id:
                self._emit_min_rules_trace_static(
                    run_id=run_id,
                    product_id=product_id,
                    requested_base_size=base_size,
                    requested_notional_usd=notional_usd,
                    base_min_size_str=base_min_size_str,
                    current_price=current_price,
                    product_details=product_details,
                )

            # Format with appropriate precision (8 decimal places for crypto)
            order_configuration = {
                "market_market_ioc": {
                    "base_size": f"{base_size:.8f}"
                }
            }
            logger.info(f"SELL order using base_size: {base_size:.8f}")
            
            # Update qty for DB storage
            qty = base_size
        
        payload = {
            "product_id": product_id,
            "side": side_upper,
            "order_configuration": order_configuration,
            "client_order_id": client_order_id
        }

        # Local dry-run validation before sending to Coinbase
        validation_errors = self._validate_order_locally(
            side=side_upper,
            product_id=product_id,
            order_configuration=order_configuration,
            product_details=product_details,
            notional_usd=notional_usd
        )
        if validation_errors:
            raise ValueError(f"Order pre-flight validation failed: {'; '.join(validation_errors)}")

        # Persist order_rules artifact for observability
        order_rules_artifact = {
            "product_id": product_id,
            "side": side_upper,
            "base_min_size": product_details.get("base_min_size"),
            "base_increment": product_details.get("base_increment"),
            "min_market_funds": product_details.get("min_market_funds"),
            "quote_increment": product_details.get("quote_increment"),
            "notional_usd": notional_usd,
            "qty_provided": qty,
            "computed_base_size": qty if side_upper == "SELL" else None,
            "current_price": current_price if side_upper == "SELL" else None,
            "rounding_applied": side_upper == "SELL",
            "validation_passed": True,
            "fetched_at": now_iso()
        }
        if run_id:
            try:
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
                           VALUES (?, 'execution', 'order_rules', ?, ?)""",
                        (run_id, json.dumps(order_rules_artifact), now_iso())
                    )
                    conn.commit()
            except Exception:
                pass  # Non-critical observability

        path = "/api/v3/brokerage/orders"
        body = json.dumps(payload)
        headers = self._get_headers("POST", path)

        order_id = new_id("ord_")
        start_time = time.time()
        attempt = 1
        max_retries = 3
        backoff_seconds = 1

        request_data = {
            "method": "POST",
            "path": path,
            "product_id": product_id,
            "side": side.upper(),
            "notional_usd": notional_usd,
            "client_order_id": client_order_id
        }
        
        while attempt <= max_retries:
            try:
                with httpx.Client(timeout=10.0) as http_client:
                    response = http_client.post(
                        f"https://api.coinbase.com{path}",
                        headers=headers,
                        content=body
                    )
                    
                    latency_ms = int((time.time() - start_time) * 1000)
                    http_status = response.status_code
                    
                    # Handle rate limiting (429)
                    if http_status == 429:
                        if attempt < max_retries:
                            wait_time = backoff_seconds * (2 ** (attempt - 1))
                            logger.warning(f"Rate limited (429), retrying after {wait_time}s (attempt {attempt}/{max_retries})")
                            time.sleep(wait_time)
                            attempt += 1
                            continue
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    # Check if request was successful
                    if result.get("success") is False:
                        error_response = result.get("error_response", {})
                        error_msg = error_response.get("error", "Unknown error")
                        error_detail = error_response.get("message", error_response.get("error_details", ""))
                        logger.error(f"Coinbase order failed: {error_msg} - {error_detail}")
                        
                        # Store failed order (don't retry - Coinbase rejected it)
                        with get_conn() as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                """
                                INSERT OR IGNORE INTO orders (
                                    order_id, run_id, tenant_id, provider, symbol, side,
                                    order_type, qty, notional_usd, status, created_at, client_order_id,
                                    status_reason, status_updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    order_id, run_id, tenant_id, "COINBASE", symbol, side.upper(),
                                    "MARKET", qty, notional_usd, "REJECTED", now_iso(), client_order_id,
                                    f"{error_msg}: {error_detail}", now_iso()
                                )
                            )
                            conn.commit()
                        
                        raise Exception(f"Coinbase order rejected: {error_msg} - {error_detail}")
                    
                    # Extract order ID from Coinbase response
                    # Coinbase Advanced Trade API returns order_id in success_response
                    order_response_id = (
                        result.get("success_response", {}).get("order_id") or
                        result.get("order_id") or 
                        result.get("order", {}).get("order_id")
                    )
                    if order_response_id:
                        order_id = order_response_id
                        logger.info(f"Extracted Coinbase order_id: {order_id}")
                    else:
                        logger.warning(f"Could not extract order_id from Coinbase response: {json.dumps(result)[:500]}")
                    
                    # Record successful tool call
                    record_tool_call(
                        run_id=run_id,
                        node_id=node_id,
                        tool_name="place_order",
                        mcp_server="coinbase_provider",
                        request_json=request_data,
                        response_json={"order_id": order_id, "status": "SUBMITTED"},
                        status="SUCCESS",
                        latency_ms=latency_ms,
                        http_status=http_status,
                        attempt=attempt
                    )
                    
                    # Store order in DB
                    with get_conn() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO orders (
                                order_id, run_id, tenant_id, provider, symbol, side,
                                order_type, qty, notional_usd, status, created_at, client_order_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                order_id, run_id, tenant_id, "COINBASE", symbol, side.upper(),
                                "MARKET", qty, notional_usd, "SUBMITTED", now_iso(), client_order_id
                            )
                        )
                        
                        # Store order event
                        event_id = new_id("evt_")
                        cursor.execute(
                            """
                            INSERT INTO order_events (id, order_id, event_type, payload_json, ts)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (event_id, order_id, "SUBMITTED", json.dumps(self._redact_sensitive(result)), now_iso())
                        )
                        conn.commit()
                    
                    logger.info(f"Order placed on Coinbase: {order_id} for {symbol} {side} ${notional_usd}")
                    
                    # Poll until terminal state if requested
                    if poll_until_filled:
                        self._poll_order_until_terminal(order_id, run_id, tenant_id, node_id)
                    
                    return order_id
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 502, 503, 504) and attempt < max_retries:
                    wait_time = backoff_seconds * (2 ** (attempt - 1))
                    logger.warning(f"Transient error {e.response.status_code}, retrying after {wait_time}s (attempt {attempt}/{max_retries})")
                    time.sleep(wait_time)
                    attempt += 1
                    continue
                
                latency_ms = int((time.time() - start_time) * 1000)
                error_msg = str(e)
                http_status = e.response.status_code
                
                record_tool_call(
                    run_id=run_id,
                    node_id=node_id,
                    tool_name="place_order",
                    mcp_server="coinbase_provider",
                    request_json=request_data,
                    response_json={"error": error_msg},
                    status="FAILED",
                    latency_ms=latency_ms,
                    error_text=error_msg,
                    http_status=http_status,
                    attempt=attempt
                )
                
                logger.error(f"Coinbase order failed: {e}")
                raise
                
            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                error_msg = str(e)
                
                record_tool_call(
                    run_id=run_id,
                    node_id=node_id,
                    tool_name="place_order",
                    mcp_server="coinbase_provider",
                    request_json=request_data,
                    response_json={"error": error_msg},
                    status="FAILED",
                    latency_ms=latency_ms,
                    error_text=error_msg,
                    attempt=attempt
                )
                
                logger.error(f"Coinbase order failed: {e}")
                
                # Store failed order (use INSERT OR IGNORE to handle retries)
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO orders (
                            order_id, run_id, tenant_id, provider, symbol, side,
                            order_type, qty, notional_usd, status, created_at, client_order_id,
                            status_reason, status_updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            order_id, run_id, tenant_id, "COINBASE", symbol, side.upper(),
                            "MARKET", qty, notional_usd, "FAILED", now_iso(), client_order_id,
                            error_msg, now_iso()
                        )
                    )
                    conn.commit()
                
                if attempt >= max_retries:
                    raise
                attempt += 1
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))
        
        raise Exception(f"Order placement failed after {max_retries} attempts")

    @staticmethod
    def _emit_min_rules_trace_static(
        run_id: str,
        product_id: str,
        requested_base_size: float,
        requested_notional_usd: float,
        base_min_size_str: str,
        current_price: Optional[float],
        product_details: Dict[str, Any],
    ) -> None:
        """Persist a single structured min_rules_trace artifact (behind DEBUG_MIN_RULES=1)."""
        trace = {
            "artifact_type": "min_rules_trace",
            "product_id": product_id,
            "requested_base_size": requested_base_size,
            "requested_notional_usd": requested_notional_usd,
            "current_price": current_price,
            "preview_called": False,
            "preview_min_rule": None,
            "metadata_base_min_size": product_details.get("base_min_size"),
            "metadata_base_increment": product_details.get("base_increment"),
            "metadata_min_market_funds": product_details.get("min_market_funds"),
            "metadata_quote_increment": product_details.get("quote_increment"),
            "default_min_rule_used": base_min_size_str == "0" or not product_details.get("base_min_size"),
            "final_enforced_min_base": base_min_size_str,
            "final_enforced_min_notional_usd": float(base_min_size_str or 0) * (current_price or 0),
            "reason": "metadata" if product_details.get("base_min_size") else "default",
        }
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
                       VALUES (?, 'execution', 'min_rules_trace', ?, ?)""",
                    (run_id, json.dumps(trace), now_iso()),
                )
                conn.commit()
        except Exception:
            pass

    def preview_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Preview an order with Coinbase and return normalized validation result."""
        path = "/api/v3/brokerage/orders/preview"
        headers = self._get_headers("POST", path)
        body = json.dumps(payload)

        with httpx.Client(timeout=10.0) as http_client:
            response = http_client.post(
                f"https://api.coinbase.com{path}",
                headers=headers,
                content=body,
            )

        try:
            data = response.json()
        except Exception:
            data = {}

        # Coinbase can return business failures with 200 and success=false.
        if response.status_code >= 400:
            message = ""
            if isinstance(data, dict):
                er = data.get("error_response") if isinstance(data.get("error_response"), dict) else {}
                message = (
                    er.get("error_details")
                    or er.get("message")
                    or er.get("error")
                    or data.get("message")
                    or data.get("error")
                    or ""
                )
            if not message:
                message = f"HTTP {response.status_code} from preview endpoint"
            return {"success": False, "error_message": message, "raw": data}

        if not isinstance(data, dict):
            return {"success": False, "error_message": "Invalid preview response", "raw": data}

        if data.get("success") is False:
            er = data.get("error_response") if isinstance(data.get("error_response"), dict) else {}
            message = (
                er.get("error_details")
                or er.get("message")
                or er.get("error")
                or data.get("message")
                or data.get("error")
                or "Order rejected by Coinbase preview."
            )
            return {"success": False, "error_message": message, "raw": data}

        if data.get("success") is True or data.get("preview_id"):
            return {"success": True, "raw": data}

        # Unrecognized response shape => caller can fallback to metadata checks.
        return {"success": None, "raw": data}
    
    def get_positions(self, tenant_id: str, run_id: str = None, node_id: str = None) -> Dict[str, Any]:
        """Get current positions from Coinbase."""
        path = "/api/v3/brokerage/accounts"
        headers = self._get_headers("GET", path)
        start_time = time.time()
        
        request_data = {"method": "GET", "path": path}
        
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"https://api.coinbase.com{path}", headers=headers)
                latency_ms = int((time.time() - start_time) * 1000)
                http_status = response.status_code
                response.raise_for_status()
                data = response.json()
                
                # Record tool call
                if run_id:
                    record_tool_call(
                        run_id=run_id,
                        node_id=node_id,
                        tool_name="get_positions",
                        mcp_server="coinbase_provider",
                        request_json=request_data,
                        response_json={"accounts_count": len(data.get("accounts", []))},
                        status="SUCCESS",
                        latency_ms=latency_ms,
                        http_status=http_status
                    )
                
                # Extract positions
                positions = {}
                for account in data.get("accounts", []):
                    currency = account.get("currency")
                    available = float(account.get("available_balance", {}).get("value", 0))
                    if available > 0 and currency != "USD":  # Exclude USD (cash)
                        positions[currency] = available
                
                return {"positions": positions}
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            if run_id:
                record_tool_call(
                    run_id=run_id,
                    node_id=node_id,
                    tool_name="get_positions",
                    mcp_server="coinbase_provider",
                    request_json=request_data,
                    response_json={"error": error_msg},
                    status="FAILED",
                    latency_ms=latency_ms,
                    error_text=error_msg,
                    http_status=getattr(e, "response", None) and getattr(e.response, "status_code", None) or None
                )
            logger.error(f"Coinbase get_positions failed: {e}")
            return {"positions": {}}
    
    def get_balances(self, tenant_id: str, run_id: str = None, node_id: str = None) -> Dict[str, Any]:
        """Get account balances from Coinbase."""
        path = "/api/v3/brokerage/accounts"
        headers = self._get_headers("GET", path)
        start_time = time.time()
        
        request_data = {"method": "GET", "path": path}
        
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"https://api.coinbase.com{path}", headers=headers)
                latency_ms = int((time.time() - start_time) * 1000)
                http_status = response.status_code
                response.raise_for_status()
                data = response.json()
                
                # Record tool call
                if run_id:
                    record_tool_call(
                        run_id=run_id,
                        node_id=node_id,
                        tool_name="get_balances",
                        mcp_server="coinbase_provider",
                        request_json=request_data,
                        response_json={"accounts_count": len(data.get("accounts", []))},
                        status="SUCCESS",
                        latency_ms=latency_ms,
                        http_status=http_status
                    )
                
                # Extract balances
                balances = {}
                for account in data.get("accounts", []):
                    currency = account.get("currency")
                    balance = float(account.get("available_balance", {}).get("value", 0))
                    if balance > 0:
                        balances[currency] = balance
                return {"balances": balances}
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            if run_id:
                record_tool_call(
                    run_id=run_id,
                    node_id=node_id,
                    tool_name="get_balances",
                    mcp_server="coinbase_provider",
                    request_json=request_data,
                    response_json={"error": error_msg},
                    status="FAILED",
                    latency_ms=latency_ms,
                    error_text=error_msg,
                    http_status=getattr(e, "response", None) and getattr(e.response, "status_code", None) or None
                )
            logger.error(f"Coinbase get_balances failed: {e}")
            return {"balances": {}}
    
    def get_fills(self, order_id: str, run_id: str = None, node_id: str = None) -> List[Dict[str, Any]]:
        """Get order fills from Coinbase."""
        path = f"/api/v3/brokerage/orders/historical/fills"
        headers = self._get_headers("GET", path)
        start_time = time.time()
        
        request_data = {"method": "GET", "path": path, "order_id": order_id}
        
        try:
            with httpx.Client(timeout=5.0) as client:
                # Filter by order_id via query params
                params = {"order_id": order_id}
                response = client.get(f"https://api.coinbase.com{path}", headers=headers, params=params)
                latency_ms = int((time.time() - start_time) * 1000)
                http_status = response.status_code
                response.raise_for_status()
                data = response.json()
                
                fills = data.get("fills", [])
                
                # Record tool call
                if run_id:
                    record_tool_call(
                        run_id=run_id,
                        node_id=node_id,
                        tool_name="get_fills",
                        mcp_server="coinbase_provider",
                        request_json=request_data,
                        response_json={"fills_count": len(fills)},
                        status="SUCCESS",
                        latency_ms=latency_ms,
                        http_status=http_status
                    )
                
                return fills
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            if run_id:
                record_tool_call(
                    run_id=run_id,
                    node_id=node_id,
                    tool_name="get_fills",
                    mcp_server="coinbase_provider",
                    request_json=request_data,
                    response_json={"error": error_msg},
                    status="FAILED",
                    latency_ms=latency_ms,
                    error_text=error_msg,
                    http_status=getattr(e, "response", None) and getattr(e.response, "status_code", None) or None
                )
            logger.error(f"Coinbase get_fills failed: {e}")
            return []
    
    def get_order_history(
        self,
        tenant_id: str,
        run_id: str = None,
        node_id: str = None,
        start_date: str = None,
        end_date: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get order history from Coinbase for portfolio analysis.
        
        Args:
            tenant_id: Tenant ID for scoping
            run_id: Run ID for tool call recording
            node_id: Node ID for tool call recording
            start_date: Start date ISO string (optional)
            end_date: End date ISO string (optional)
            limit: Maximum number of orders to return
        
        Returns:
            List of order dicts with order_id, product_id, side, size, price, status, created_time
        """
        path = "/api/v3/brokerage/orders/historical"
        headers = self._get_headers("GET", path)
        start_time = time.time()
        
        params = {
            "limit": str(limit),
            "order_status": "FILLED",  # Only get filled orders for analysis
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        
        request_data = {
            "method": "GET",
            "path": path,
            "params": params
        }
        
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"https://api.coinbase.com{path}", headers=headers, params=params)
                latency_ms = int((time.time() - start_time) * 1000)
                http_status = response.status_code
                response.raise_for_status()
                data = response.json()
                
                orders = data.get("orders", [])
                
                # Normalize orders to a clean schema
                normalized_orders = []
                for order in orders:
                    normalized = {
                        "order_id": order.get("order_id"),
                        "product_id": order.get("product_id"),
                        "side": order.get("side"),
                        "order_type": order.get("order_type"),
                        "status": order.get("status"),
                        "created_time": order.get("created_time"),
                        "filled_size": order.get("filled_size"),
                        "filled_value": order.get("filled_value"),
                        "average_filled_price": order.get("average_filled_price"),
                        "total_fees": order.get("total_fees"),
                    }
                    normalized_orders.append(normalized)
                
                # Record tool call (redact order IDs)
                if run_id:
                    record_tool_call(
                        run_id=run_id,
                        node_id=node_id,
                        tool_name="get_order_history",
                        mcp_server="coinbase_provider",
                        request_json=request_data,
                        response_json={
                            "orders_count": len(normalized_orders),
                            "start_date": start_date,
                            "end_date": end_date
                        },
                        status="SUCCESS",
                        latency_ms=latency_ms,
                        http_status=http_status
                    )
                
                return normalized_orders
                
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            if run_id:
                record_tool_call(
                    run_id=run_id,
                    node_id=node_id,
                    tool_name="get_order_history",
                    mcp_server="coinbase_provider",
                    request_json=request_data,
                    response_json={"error": error_msg},
                    status="FAILED",
                    latency_ms=latency_ms,
                    error_text=error_msg,
                    http_status=getattr(e, "response", None) and getattr(e.response, "status_code", None) or None
                )
            logger.error(f"Coinbase get_order_history failed: {e}")
            return []
    
    def get_accounts_detailed(
        self,
        tenant_id: str,
        run_id: str = None,
        node_id: str = None
    ) -> Dict[str, Any]:
        """
        Get detailed account information from Coinbase for portfolio analysis.
        
        Returns a dict with:
            - accounts: List of account objects with currency, available_balance, hold
            - total_balance_usd: Estimated total balance in USD
        """
        path = "/api/v3/brokerage/accounts"
        headers = self._get_headers("GET", path)
        start_time = time.time()
        
        request_data = {"method": "GET", "path": path}
        
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"https://api.coinbase.com{path}", headers=headers)
                latency_ms = int((time.time() - start_time) * 1000)
                http_status = response.status_code
                response.raise_for_status()
                data = response.json()
                
                accounts = []
                for account in data.get("accounts", []):
                    acc_data = {
                        "uuid": account.get("uuid", ""),  # Redact in logs
                        "currency": account.get("currency"),
                        "name": account.get("name"),
                        "available_balance": float(account.get("available_balance", {}).get("value", 0)),
                        "hold": float(account.get("hold", {}).get("value", 0)),
                        "type": account.get("type"),
                        "active": account.get("active", True),
                    }
                    accounts.append(acc_data)
                
                # Record tool call (redact account UUIDs)
                if run_id:
                    record_tool_call(
                        run_id=run_id,
                        node_id=node_id,  # Pass None if not in DAG context (avoids FK violation)
                        tool_name="get_accounts_detailed",
                        mcp_server="coinbase_provider",
                        request_json=request_data,
                        response_json={
                            "accounts_count": len(accounts),
                            "currencies": [a["currency"] for a in accounts if a["available_balance"] > 0]
                        },
                        status="SUCCESS",
                        latency_ms=latency_ms,
                        http_status=http_status
                    )
                
                return {
                    "accounts": accounts,
                    "raw_account_count": len(data.get("accounts", []))
                }
                
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            if run_id:
                record_tool_call(
                    run_id=run_id,
                    node_id=node_id,  # Pass None if not in DAG context (avoids FK violation)
                    tool_name="get_accounts_detailed",
                    mcp_server="coinbase_provider",
                    request_json=request_data,
                    response_json={"error": error_msg},
                    status="FAILED",
                    latency_ms=latency_ms,
                    error_text=error_msg,
                    http_status=getattr(e, "response", None) and getattr(e.response, "status_code", None) or None
                )
            logger.error(f"Coinbase get_accounts_detailed failed: {e}")
            return {"accounts": [], "raw_account_count": 0}
