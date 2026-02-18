"""Execution node."""
import json
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.providers.replay import ReplayProvider
from backend.orchestrator.event_emitter import emit_event
from backend.core.logging import get_logger
from backend.services.notifications.pushover import notify_trade_placed, notify_trade_failed

logger = get_logger(__name__)

# Coinbase minimum order sizes (approximate, in USD)
# These are conservative minimums; actual minimums vary per product
MIN_NOTIONAL_USD = 1.0  # Coinbase generally allows orders >= $1


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute execution node."""
    # Get run execution mode, proposal, source_run_id, asset_class, and LOCKED product_id
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT execution_mode, trade_proposal_json, source_run_id, asset_class, locked_product_id FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()

        execution_mode = row["execution_mode"]
        proposal = json.loads(row["trade_proposal_json"])
        source_run_id = row["source_run_id"] if row and "source_run_id" in row.keys() else None
        asset_class = row["asset_class"] if row and "asset_class" in row.keys() and row["asset_class"] else "CRYPTO"
        locked_product_id = row["locked_product_id"] if row and "locked_product_id" in row.keys() else None

    # ── AUTO-SELL (FUNDS RECYCLING) ──
    # If the run metadata includes an auto_sell directive, execute the sell first
    # to raise cash, then proceed with the original BUY order.
    auto_sell = proposal.get("auto_sell")
    if auto_sell and auto_sell.get("needs_recycle") and auto_sell.get("sell_symbol"):
        sell_symbol = auto_sell["sell_symbol"]
        sell_amount = float(auto_sell.get("sell_amount_usd", 2.0))
        logger.info(
            "AUTO_SELL_START: run=%s selling $%.2f of %s to raise cash for BUY",
            run_id, sell_amount, sell_symbol,
        )
        try:
            from backend.mcp_servers.broker import BrokerMCPServer
            sell_broker = BrokerMCPServer(execution_mode=execution_mode)
            sell_result = await sell_broker.place_order(
                product_id=sell_symbol,
                side="SELL",
                notional_usd=sell_amount,
                tenant_id=tenant_id,
            )
            sell_order_id = sell_result.get("order_id", "unknown")
            logger.info(
                "AUTO_SELL_DONE: run=%s order=%s symbol=%s amount=$%.2f",
                run_id, sell_order_id, sell_symbol, sell_amount,
            )
            # Persist auto-sell order in orders table
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR IGNORE INTO orders
                       (order_id, run_id, tenant_id, symbol, side, notional_usd,
                        status, parent_order_id, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        sell_order_id, run_id, tenant_id, sell_symbol,
                        "SELL", sell_amount, "FILLED", "auto_sell", now_iso(),
                    ),
                )
                conn.commit()
            # Store audit artifact
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO run_artifacts
                       (run_id, step_name, artifact_type, artifact_json, created_at)
                       VALUES (?, 'execution', 'auto_sell_receipt', ?, ?)""",
                    (run_id, json.dumps({
                        "sell_symbol": sell_symbol,
                        "sell_amount_usd": sell_amount,
                        "sell_order_id": sell_order_id,
                        "reason": auto_sell.get("reason", "Funds recycling"),
                        "available_cash_before": auto_sell.get("available_cash", 0),
                        "required_cash": auto_sell.get("required_cash", 0),
                    }), now_iso()),
                )
                conn.commit()
        except Exception as e:
            logger.error("AUTO_SELL_FAILED: run=%s error=%s", run_id, str(e)[:200])
            # Continue with the BUY anyway — the broker may still succeed
            # if there's partial balance available

    # ── DECISION LOCK ENFORCEMENT ──
    # If a locked_product_id exists, override ALL order symbols in the proposal
    # to match the confirmed product. This prevents symbol drift between
    # confirmation and execution (e.g., confirming HNT but executing MORPHO).
    if locked_product_id:
        logger.info(
            "DECISION_LOCK_ENFORCED: run=%s locked_product_id=%s, overriding proposal orders",
            run_id, locked_product_id
        )
        for order in proposal.get("orders", []):
            original_symbol = order.get("symbol")
            if original_symbol != locked_product_id:
                logger.warning(
                    "SYMBOL_DRIFT_PREVENTED: run=%s original=%s locked=%s",
                    run_id, original_symbol, locked_product_id
                )
            order["symbol"] = locked_product_id
    else:
        # No locked product — this is unexpected for confirmed trades
        # For safety, log a warning but continue with proposal as-is
        logger.warning(
            "NO_DECISION_LOCK: run=%s has no locked_product_id; using proposal orders as-is",
            run_id
        )

    # Persist order_intent artifact for observability
    intent_artifact = {
        "execution_mode": execution_mode,
        "asset_class": asset_class,
        "proposal": proposal,
        "source_run_id": source_run_id,
        "created_at": now_iso()
    }
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
                   VALUES (?, 'execution', 'order_intent', ?, ?)""",
                (run_id, json.dumps(intent_artifact), now_iso())
            )
            conn.commit()
    except Exception:
        pass  # Non-critical observability

    # Pre-validate: check min-notional for all orders
    for order in proposal.get("orders", []):
        notional = order.get("notional_usd", 0)
        if notional < MIN_NOTIONAL_USD:
            failure_artifact = {
                "summary": f"Order notional ${notional:.2f} is below minimum ${MIN_NOTIONAL_USD:.2f}",
                "symbol": order.get("symbol"),
                "notional_usd": notional,
                "min_notional_usd": MIN_NOTIONAL_USD,
                "failed_at": now_iso()
            }
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                       VALUES (?, 'execution', 'execution_failure', ?)""",
                    (run_id, json.dumps(failure_artifact))
                )
                conn.commit()
            raise ValueError(
                f"Order for {order.get('symbol')} notional ${notional:.2f} is below "
                f"minimum ${MIN_NOTIONAL_USD:.2f}. Increase order amount."
            )

    # === DEMO_SAFE_MODE: Block LIVE crypto execution ===
    from backend.core.config import get_settings
    settings = get_settings()
    
    if settings.demo_safe_mode and execution_mode == "LIVE" and asset_class == "CRYPTO":
        logger.warning(
            "DEMO_SAFE_MODE: Blocking LIVE crypto execution for run %s mode=%s asset_class=%s",
            run_id, execution_mode, asset_class
        )
        
        blocked_artifact = {
            "reason_code": "DEMO_MODE_LIVE_BLOCKED",
            "summary": "LIVE order execution blocked by DEMO_SAFE_MODE",
            "execution_mode": execution_mode,
            "asset_class": asset_class,
            "orders_blocked": len(proposal.get("orders", [])),
            "blocked_at": now_iso(),
            "instructions": (
                "DEMO_SAFE_MODE is enabled. To execute real LIVE orders, "
                "set DEMO_SAFE_MODE=0 in environment. "
                "Use PAPER mode for simulated trading or review the proposal."
            )
        }
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                   VALUES (?, 'execution', 'demo_mode_blocked', ?)""",
                (run_id, json.dumps(blocked_artifact))
            )
            conn.commit()
        
        await emit_event(run_id, "DEMO_MODE_LIVE_BLOCKED", blocked_artifact, tenant_id=tenant_id)
        
        return {
            "execution_mode": execution_mode,
            "order_placed": False,
            "reason_code": "DEMO_MODE_LIVE_BLOCKED",
            "blocked_orders": len(proposal.get("orders", [])),
            "evidence_refs": [{"reason_code": "DEMO_MODE_LIVE_BLOCKED"}],
            "safe_summary": "LIVE execution blocked by DEMO_SAFE_MODE - no orders placed"
        }

    # === ASSISTED_LIVE mode: Create trade ticket instead of executing ===
    if execution_mode == "ASSISTED_LIVE" or asset_class == "STOCK":
        from backend.db.repo.trade_tickets_repo import TradeTicketsRepo
        from backend.core.config import get_settings

        settings = get_settings()
        tickets_repo = TradeTicketsRepo()
        ticket_ids = []

        for order in proposal.get("orders", []):
            symbol = order["symbol"].replace("-USD", "")  # Strip -USD for stock symbols
            side = order["side"].upper()
            notional = order["notional_usd"]

            # Estimate quantity from latest price (if available)
            est_qty = None
            suggested_limit = None
            try:
                from backend.services.market_data_provider import get_market_data_provider
                provider = get_market_data_provider(asset_class=asset_class)
                price = provider.get_price(symbol)
                if price and price > 0:
                    est_qty = notional / price
                    suggested_limit = price
            except Exception as e:
                logger.warning(f"Could not estimate quantity for {symbol}: {e}")

            ticket_id = tickets_repo.create_ticket(
                tenant_id=tenant_id,
                run_id=run_id,
                symbol=symbol,
                side=side,
                notional_usd=notional,
                est_qty=est_qty,
                suggested_limit=suggested_limit,
                tif="DAY",
                ttl_hours=settings.stock_ticket_ttl_hours,
                asset_class=asset_class
            )
            ticket_ids.append(ticket_id)

            await emit_event(run_id, "TRADE_TICKET_CREATED", {
                "ticket_id": ticket_id,
                "symbol": symbol,
                "side": side,
                "notional_usd": notional,
                "est_qty": est_qty,
                "suggested_limit": suggested_limit,
                "asset_class": asset_class
            }, tenant_id=tenant_id)

            # Send push notification for ASSISTED_LIVE ticket
            from backend.services.notifications.pushover import notify_stock_ticket_created
            notify_stock_ticket_created(
                symbol=symbol,
                side=side,
                notional_usd=notional,
                ticket_id=ticket_id,
                run_id=run_id
            )

            logger.info(
                "Created trade ticket %s for %s %s run=%s notional=%s asset_class=%s",
                ticket_id, side, symbol, run_id, notional, asset_class
            )

        # Persist trade_ticket artifact
        ticket_artifact = {
            "execution_mode": "ASSISTED_LIVE",
            "asset_class": asset_class,
            "ticket_ids": ticket_ids,
            "tickets": [
                {
                    "ticket_id": tid,
                    "symbol": order["symbol"].replace("-USD", ""),
                    "side": order["side"].upper(),
                    "notional_usd": order["notional_usd"]
                }
                for tid, order in zip(ticket_ids, proposal.get("orders", []))
            ],
            "instructions": (
                "Order ticket generated. Please execute manually in your brokerage "
                "(Schwab, Fidelity, etc.) then submit execution receipt."
            ),
            "created_at": now_iso()
        }
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                   VALUES (?, 'execution', 'trade_ticket', ?)""",
                (run_id, json.dumps(ticket_artifact))
            )
            conn.commit()

        return {
            "execution_mode": "ASSISTED_LIVE",
            "order_placed": False,
            "ticket_ids": ticket_ids,
            "evidence_refs": [{"ticket_ids": ticket_ids}],
            "safe_summary": f"Generated {len(ticket_ids)} order ticket(s) for manual execution"
        }

    # Get provider
    if execution_mode == "REPLAY":
        if not source_run_id:
            raise ValueError(f"REPLAY mode requires source_run_id for run {run_id}")
        provider = ReplayProvider(source_run_id)
        order_ids = []
        for order in proposal.get("orders", []):
            order_id = provider.place_order(
                run_id=run_id,
                tenant_id=tenant_id,
                symbol=order["symbol"],
                side=order["side"],
                notional_usd=order["notional_usd"]
            )
            order_ids.append(order_id)
    else:
        from backend.mcp_servers.broker_server import BrokerMCPServer
        broker_server = BrokerMCPServer(execution_mode=execution_mode)

        order_ids = []
        for order in proposal.get("orders", []):
            client_order_id = new_id("client_")
            try:
                result = broker_server.place_order(
                    run_id=run_id,
                    node_id=node_id,
                    tenant_id=tenant_id,
                    symbol=order["symbol"],
                    side=order["side"],
                    notional_usd=order["notional_usd"],
                    qty=order.get("qty"),
                    client_order_id=client_order_id
                )
                order_ids.append(result["order_id"])

                await emit_event(run_id, "ORDER_SUBMITTED", {
                    "order_id": result["order_id"],
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "notional_usd": order["notional_usd"],
                    "provider": execution_mode
                }, tenant_id=tenant_id)
                
                # Send push notification for successful order
                try:
                    notify_trade_placed(
                        mode=execution_mode,
                        side=order["side"],
                        symbol=order["symbol"],
                        notional_usd=order["notional_usd"],
                        order_id=result["order_id"],
                        run_id=run_id
                    )
                except Exception as notif_err:
                    logger.warning(f"Failed to send trade notification: {notif_err}")
                    
            except Exception as e:
                logger.error(f"Order placement failed for {order['symbol']}: {e}")
                
                # Classify error and wrap in TradeErrorException if needed
                from backend.core.error_codes import TradeErrorException, TradeErrorCode
                
                # If already a TradeErrorException, re-raise as-is
                if isinstance(e, TradeErrorException):
                    structured_error = e
                else:
                    # Classify based on error message
                    error_str = str(e).lower()
                    if "product details unavailable" in error_str:
                        structured_error = TradeErrorException(
                            error_code=TradeErrorCode.PRODUCT_DETAILS_UNAVAILABLE,
                            message=str(e),
                            remediation="Check Coinbase API connectivity. Product metadata is required for SELL orders."
                        )
                    elif "timeout" in error_str:
                        structured_error = TradeErrorException(
                            error_code=TradeErrorCode.ORDER_TIMEOUT,
                            message=str(e),
                            remediation="Check network connectivity and try again."
                        )
                    elif "insufficient" in error_str and "balance" in error_str:
                        structured_error = TradeErrorException(
                            error_code=TradeErrorCode.INSUFFICIENT_BALANCE,
                            message=str(e),
                            remediation="Deposit funds or reduce order size."
                        )
                    elif "below minimum" in error_str or "min_market_funds" in error_str:
                        structured_error = TradeErrorException(
                            error_code=TradeErrorCode.BELOW_MINIMUM_SIZE,
                            message=str(e),
                            remediation="Increase order size to meet minimum requirements."
                        )
                    else:
                        structured_error = TradeErrorException(
                            error_code=TradeErrorCode.EXECUTION_FAILED,
                            message=str(e),
                            remediation="Check error details and system logs."
                        )
                
                # Send push notification for failed order
                try:
                    notify_trade_failed(
                        mode=execution_mode,
                        symbol=order["symbol"],
                        notional_usd=order["notional_usd"],
                        error=str(e),
                        run_id=run_id
                    )
                except Exception as notif_err:
                    logger.warning(f"Failed to send failure notification: {notif_err}")
                
                # Persist execution error artifact with structured error code
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                           VALUES (?, 'execution', 'execution_error', ?)""",
                        (run_id, json.dumps({
                            "symbol": order["symbol"],
                            "error": str(e),
                            "error_code": structured_error.error_code.value,
                            "remediation": structured_error.remediation,
                            "requested_notional_usd": order["notional_usd"],
                            "notional_usd": order["notional_usd"],
                            "failed_at": now_iso()
                        }))
                    )
                    conn.commit()
                raise structured_error

    # Emit ORDER_FILLED events (in PAPER mode orders are filled immediately)
    if execution_mode == "PAPER":
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT order_id, symbol, side, notional_usd FROM orders WHERE run_id = ? AND status = 'FILLED'",
                (run_id,)
            )
            filled_orders = cursor.fetchall()
            for order_row in filled_orders:
                await emit_event(run_id, "ORDER_FILLED", {
                    "order_id": order_row["order_id"],
                    "symbol": order_row["symbol"],
                    "side": order_row["side"],
                    "notional_usd": order_row["notional_usd"]
                }, tenant_id=tenant_id)

    # Persist trade_receipt artifact for observability
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT order_id, symbol, side, notional_usd, qty, status,
                          filled_qty, avg_fill_price, total_fees, client_order_id,
                          status_reason, status_updated_at, created_at
                   FROM orders WHERE run_id = ?""",
                (run_id,)
            )
            order_rows = [dict(r) for r in cursor.fetchall()]

            cursor.execute(
                """SELECT fill_id, order_id, product_id, price, size, fee, trade_id,
                          liquidity_indicator, filled_at
                   FROM fills WHERE run_id = ?""",
                (run_id,)
            )
            fill_rows = [dict(r) for r in cursor.fetchall()]

            receipt_artifact = {
                "run_id": run_id,
                "execution_mode": execution_mode,
                "asset_class": asset_class,
                "orders": order_rows,
                "fills": fill_rows,
                "total_orders": len(order_rows),
                "total_fills": len(fill_rows),
                "created_at": now_iso()
            }
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
                   VALUES (?, 'execution', 'trade_receipt', ?, ?)""",
                (run_id, json.dumps(receipt_artifact), now_iso())
            )
            conn.commit()
    except Exception:
        pass  # Non-critical observability

    return {
        "order_ids": order_ids,
        "evidence_refs": [{"order_ids": order_ids}],
        "safe_summary": f"Placed {len(order_ids)} order(s) via {execution_mode} provider"
    }
