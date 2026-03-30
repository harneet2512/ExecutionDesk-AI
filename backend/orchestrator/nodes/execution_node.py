"""Execution node."""
import json
from decimal import Decimal, ROUND_DOWN
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.providers.replay import ReplayProvider
from backend.orchestrator.event_emitter import emit_event
from backend.core.logging import get_logger
from backend.services.notifications.pushover import notify_trade_placed, notify_trade_failed

logger = get_logger(__name__)

# DEPRECATED — see docs/trading_truth_contracts.md INV-3.
# This hardcoded constant is retained for backward compatibility only.
# Authoritative minimums come from broker preview or verified product catalog.
MIN_NOTIONAL_USD = 1.0


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

    # ── PRE-TRADE SNAPSHOT (idempotent) ──
    # Capture Coinbase-accurate balances before placing orders so charts get >=2 data points.
    try:
        from backend.services.executable_state import fetch_executable_state
        from backend.services.market_data import get_price as _get_price_safe_exec

        exec_state = fetch_executable_state(tenant_id)
        _snap_balances = {}
        _snap_positions = {}
        _snap_total = 0.0
        for ccy, eb in exec_state.balances.items():
            _snap_balances[ccy] = eb.available_qty
            if ccy.upper() not in ("USD", "USDC", "USDT") and eb.available_qty > 0:
                _snap_positions[ccy] = eb.available_qty
            try:
                _p = _get_price_safe_exec(f"{ccy}-USD") if ccy.upper() not in ("USD", "USDC", "USDT") else 1.0
                _snap_total += eb.available_qty * float(_p)
            except Exception:
                _snap_total += eb.available_qty if ccy.upper() in ("USD", "USDC", "USDT") else 0.0

        _pre_snap_id = f"snap_pre_{run_id}"
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR IGNORE INTO portfolio_snapshots (
                    snapshot_id, run_id, tenant_id, balances_json, positions_json, total_value_usd, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (_pre_snap_id, run_id, tenant_id, json.dumps(_snap_balances),
                 json.dumps(_snap_positions), _snap_total, now_iso()),
            )
            conn.commit()
        logger.info("PRE_TRADE_SNAPSHOT: run=%s snap=%s total=$%.2f", run_id, _pre_snap_id, _snap_total)
    except Exception as snap_err:
        logger.warning("Pre-trade snapshot failed (non-critical): %s", str(snap_err)[:200])

    # Get provider
    order_statuses = {}
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

        # ── EXECUTION-TIME PREFLIGHT CONSTRAINTS GATE ──
        # For LIVE SELL orders, refetch actual Coinbase balance and validate minimums
        # before sending each order to the exchange.
        if execution_mode == "LIVE":
            try:
                _preflight_state = fetch_executable_state(tenant_id)
            except Exception:
                _preflight_state = None

            for order in proposal.get("orders", []):
                if order.get("side", "").upper() != "SELL" or not _preflight_state:
                    continue
                base_ccy = order["symbol"].split("-")[0] if "-" in order["symbol"] else order["symbol"]
                bal = _preflight_state.balances.get(base_ccy)
                if not bal:
                    continue

                available_d = Decimal(str(bal.available_qty))
                hold_d = Decimal(str(bal.hold_qty))

                # Fetch product rules for sizing constraints
                try:
                    from backend.providers.coinbase_provider import CoinbaseProvider
                    _cb_prov = CoinbaseProvider()
                    _prod_details = _cb_prov._validate_product_constraints(order["symbol"], order.get("notional_usd", 0))
                except Exception:
                    _prod_details = {}

                increment_d = Decimal(_prod_details.get("base_increment", "0.00000001"))
                base_min_d = Decimal(_prod_details.get("base_min_size", "0"))
                min_market_d = Decimal(_prod_details.get("min_market_funds", "0"))
                epsilon_d = Decimal("1E-10")

                safe_qty = ((available_d - epsilon_d) / increment_d).to_integral_value(rounding=ROUND_DOWN) * increment_d
                if safe_qty <= 0:
                    safe_qty = Decimal("0")

                # Check minimums
                try:
                    _cp = _get_price_safe_exec(order["symbol"])
                    notional_d = safe_qty * Decimal(str(_cp))
                except Exception:
                    _cp = 0
                    notional_d = Decimal("0")

                if safe_qty < base_min_d or (min_market_d > 0 and notional_d < min_market_d):
                    logger.warning(
                        "PREFLIGHT_DUST: run=%s symbol=%s available=%s safe_qty=%s base_min=%s",
                        run_id, order["symbol"], available_d, safe_qty, base_min_d,
                    )
                    from backend.orchestrator.runner import _persist_artifact
                    _persist_artifact(run_id, "execution", "balance_mismatch_diagnostic", {
                        "snapshot_balance": float(order.get("qty") or order.get("notional_usd", 0)),
                        "coinbase_available": float(available_d),
                        "coinbase_hold": float(hold_d),
                        "account_uuid": bal.account_uuid,
                        "likely_causes": [
                            "funds on hold from open orders",
                            "portfolio/account mismatch",
                            "recent deposit not yet settled",
                        ],
                        "constraint_violated": "DUST_BELOW_MINIMUM",
                        "base_min_size": str(base_min_d),
                        "min_market_funds": str(min_market_d),
                        "computed_qty": str(safe_qty),
                        "diagnosed_at": now_iso(),
                    })
                    from backend.core.error_codes import TradeErrorException, TradeErrorCode
                    raise TradeErrorException(
                        error_code=TradeErrorCode.BELOW_MINIMUM_SIZE,
                        message=(
                            f"Cannot sell {order['symbol']}: position below minimum order size (dust). "
                            f"Minimum base_size={base_min_d}, available={available_d}, computed_qty={safe_qty}."
                        ),
                        remediation="Position is too small to sell. Consider accumulating more or skipping this asset.",
                    )

                # Override order qty with verified Coinbase balance
                order["qty"] = float(safe_qty)
                logger.info(
                    "PREFLIGHT_SELL_QTY: run=%s symbol=%s qty=%s (available=%s, hold=%s)",
                    run_id, order["symbol"], safe_qty, available_d, hold_d,
                )

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
                placed_order_id = result["order_id"]
                order_ids.append(placed_order_id)

                # Read back the canonical order status from DB after provider placement/polling.
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT status, filled_qty, avg_fill_price FROM orders WHERE order_id = ?",
                        (placed_order_id,),
                    )
                    order_row = cursor.fetchone()
                order_status = (
                    str(order_row["status"]).upper()
                    if order_row and order_row["status"]
                    else "SUBMITTED"
                )
                filled_qty = float(order_row["filled_qty"] or 0.0) if order_row else 0.0
                avg_fill_price = float(order_row["avg_fill_price"] or 0.0) if order_row else 0.0
                order_statuses[placed_order_id] = order_status

                await emit_event(run_id, "ORDER_SUBMITTED", {
                    "order_id": placed_order_id,
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "notional_usd": order["notional_usd"],
                    "provider": execution_mode,
                    "order_status": order_status,
                    "message": "Order submitted. You can confirm fill in your Coinbase app.",
                }, tenant_id=tenant_id)

                if order_status == "FILLED":
                    await emit_event(run_id, "ORDER_FILLED", {
                        "order_id": placed_order_id,
                        "symbol": order["symbol"],
                        "side": order["side"],
                        "notional_usd": order["notional_usd"],
                        "filled_qty": filled_qty,
                        "avg_fill_price": avg_fill_price,
                        "provider": execution_mode,
                        "message": "Order filled. You can also confirm in your Coinbase app.",
                    }, tenant_id=tenant_id)
                elif order_status in {"SUBMITTED", "OPEN", "PENDING", "PENDING_FILL"}:
                    await emit_event(run_id, "ORDER_PENDING_FILL", {
                        "order_id": placed_order_id,
                        "symbol": order["symbol"],
                        "side": order["side"],
                        "notional_usd": order["notional_usd"],
                        "provider": execution_mode,
                        "order_status": order_status,
                        "message": "Order submitted. You can confirm fill in your Coinbase app.",
                    }, tenant_id=tenant_id)
                
                # Send push notification for successful order
                try:
                    notify_trade_placed(
                        mode=execution_mode,
                        side=order["side"],
                        symbol=order["symbol"],
                        notional_usd=order["notional_usd"],
                        order_id=placed_order_id,
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
                "venue": {
                    "name": "Coinbase" if execution_mode == "LIVE" else "Paper (simulated)",
                    "execution_mode": execution_mode,
                    "order_type": "market",
                },
                "submitted_at": now_iso(),
                "created_at": now_iso(),
            }
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
                   VALUES (?, 'execution', 'trade_receipt', ?, ?)""",
                (run_id, json.dumps(receipt_artifact), now_iso())
            )
            conn.commit()
    except Exception:
        pass  # Non-critical observability

    if execution_mode in {"REPLAY", "PAPER"}:
        order_statuses = {}
        for oid in order_ids:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT status FROM orders WHERE order_id = ?", (oid,))
                row = cursor.fetchone()
            order_statuses[oid] = str(row["status"]).upper() if row and row["status"] else "SUBMITTED"

    all_filled = bool(order_ids) and all(
        str(order_statuses.get(oid, "SUBMITTED")).upper() == "FILLED" for oid in order_ids
    )
    safe_summary = (
        f"Placed {len(order_ids)} order(s) via {execution_mode}; fills confirmed."
        if all_filled
        else f"Placed {len(order_ids)} order(s) via {execution_mode}; pending fill confirmation."
    )

    return {
        "order_ids": order_ids,
        "order_statuses": order_statuses,
        "fill_confirmed": all_filled,
        "evidence_refs": [{"order_ids": order_ids}],
        "safe_summary": safe_summary,
    }
