"""Post-trade node - fetches fills, balances, positions, snapshots."""
import json
import time
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.tool_calls import record_tool_call_sync as record_tool_call
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute post-trade node - fetch fills, balances, positions, create snapshots."""
    # Get execution mode, asset_class, and orders
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT execution_mode, asset_class FROM runs WHERE run_id = ?",
            (run_id,)
        )
        exec_row = cursor.fetchone()
        execution_mode = exec_row["execution_mode"] if exec_row else "PAPER"
        asset_class = exec_row["asset_class"] if exec_row and "asset_class" in exec_row.keys() and exec_row["asset_class"] else "CRYPTO"

        # For ASSISTED_LIVE mode (stocks), skip balance fetching - just a ticket was created
        if execution_mode == "ASSISTED_LIVE" or asset_class == "STOCK":
            logger.info(f"PostTradeNode: ASSISTED_LIVE mode - skipping balance/fills fetching for run {run_id}")

            # Get ticket info for the response
            cursor.execute(
                "SELECT id, symbol, side, notional_usd, status FROM trade_tickets WHERE run_id = ?",
                (run_id,)
            )
            tickets = cursor.fetchall()

            post_trade_output = {
                "execution_mode": "ASSISTED_LIVE",
                "asset_class": asset_class,
                "order_placed": False,
                "tickets": [
                    {
                        "ticket_id": t["id"],
                        "symbol": t["symbol"],
                        "side": t["side"],
                        "notional_usd": t["notional_usd"],
                        "status": t["status"]
                    }
                    for t in tickets
                ] if tickets else [],
                "message": "Order ticket generated. User must execute manually in brokerage.",
                "evidence_refs": [],
                "safe_summary": f"Order ticket created for manual execution ({len(tickets) if tickets else 0} ticket(s))"
            }

            # Store in dag_nodes
            cursor.execute(
                "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
                (json.dumps(post_trade_output), node_id)
            )
            conn.commit()

            return post_trade_output

        # Get orders from this run
        cursor.execute(
            "SELECT order_id, symbol, side, notional_usd, status FROM orders WHERE run_id = ?",
            (run_id,)
        )
        orders = cursor.fetchall()
    
    fills = []
    balances = {}
    positions = {}
    
    if execution_mode == "LIVE":
        # Fetch fills from Coinbase
        from backend.providers.coinbase_provider import CoinbaseProvider
        try:
            provider = CoinbaseProvider()
            
            for order_row in orders:
                order_id = order_row["order_id"]
                
                # Fetch fills
                start_tool = time.time()
                try:
                    order_fills = provider.get_fills(order_id, run_id=run_id, node_id=node_id)
                    fills.extend(order_fills)
                    latency_ms = int((time.time() - start_tool) * 1000)
                    
                    # Record tool call
                    record_tool_call(
                        run_id=run_id,
                        node_id=node_id,
                        tool_name="get_fills",
                        mcp_server="coinbase_provider",
                        request_json={"order_id": order_id},
                        response_json={"fills_count": len(order_fills)},
                        status="SUCCESS",
                        latency_ms=latency_ms
                    )
                except Exception as e:
                    logger.warning(f"Failed to fetch fills for order {order_id}: {e}")
            
            # Fetch balances and positions
            balances_data = provider.get_balances(tenant_id, run_id=run_id, node_id=node_id)
            balances = balances_data.get("balances", {})
            
            positions_data = provider.get_positions(tenant_id, run_id=run_id, node_id=node_id)
            positions = positions_data.get("positions", {})
            
        except Exception as e:
            logger.error(f"Coinbase post-trade fetch failed: {e}")
            # Fallback to DB state
            cursor.execute(
                """
                SELECT balances_json, positions_json, total_value_usd
                FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC LIMIT 1
                """,
                (tenant_id,)
            )
            row = cursor.fetchone()
            if row:
                balances = json.loads(row["balances_json"])
                positions = json.loads(row["positions_json"])
            else:
                balances = {"USD": 100.0}
                positions = {}
    
    elif execution_mode == "PAPER":
        # Paper mode: balances/positions are in DB from PaperProvider
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT balances_json, positions_json, total_value_usd
                FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC LIMIT 1
                """,
                (tenant_id,)
            )
            row = cursor.fetchone()
            if row:
                balances = json.loads(row["balances_json"])
                positions = json.loads(row["positions_json"])
            else:
                balances = {"USD": 100.0}
                positions = {}

            # Backfill fill columns for PAPER orders that have NULL filled_qty
            # (handles orders created before PaperProvider was updated)
            cursor.execute(
                """SELECT order_id, qty, symbol FROM orders
                   WHERE run_id = ? AND filled_qty IS NULL""",
                (run_id,)
            )
            unfilled_orders = cursor.fetchall()
            for uo in unfilled_orders:
                try:
                    from backend.services.market_data import get_price as _get_price
                    uo_price = _get_price(uo["symbol"]) if uo["symbol"] else 0
                except Exception:
                    uo_price = 0
                cursor.execute(
                    """UPDATE orders SET filled_qty = ?, avg_fill_price = ?, total_fees = 0,
                       status_updated_at = ? WHERE order_id = ?""",
                    (uo["qty"], uo_price, now_iso(), uo["order_id"])
                )
            if unfilled_orders:
                conn.commit()
    
    # Calculate total portfolio value
    from backend.services.market_data_provider import get_market_data_provider
    market_data_provider = get_market_data_provider()
    total_value = balances.get("USD", 0.0)
    for pos_symbol, pos_qty in positions.items():
        try:
            pos_price = market_data_provider.get_price(pos_symbol)
            total_value += pos_qty * pos_price
        except Exception:
            # Fallback: use last known price from candles if available
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT close FROM market_candles WHERE symbol = ? ORDER BY ts DESC LIMIT 1",
                    (pos_symbol,)
                )
                price_row = cursor.fetchone()
                if price_row:
                    total_value += pos_qty * float(price_row["close"])
    
    # Create portfolio snapshot
    snapshot_id = new_id("snap_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO portfolio_snapshots (
                snapshot_id, run_id, tenant_id, balances_json, positions_json, total_value_usd, ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (snapshot_id, run_id, tenant_id, json.dumps(balances), json.dumps(positions), total_value, now_iso())
        )
        conn.commit()
    
    post_trade_output = {
        "snapshot_id": snapshot_id,
        "balances": balances,
        "positions": positions,
        "total_value_usd": total_value,
        "fills_count": len(fills),
        "execution_mode": execution_mode
    }
    
    # Store in dag_nodes
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(post_trade_output), node_id)
        )
        conn.commit()
    
    return post_trade_output
