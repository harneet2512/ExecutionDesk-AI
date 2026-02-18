"""Analytics: PnL endpoints."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.api.deps import require_viewer
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/pnl")
async def get_pnl(
    run_id: str = Query(..., description="Run ID"),
    user: dict = Depends(require_viewer)
):
    """
    Get PnL analytics for a run.
    
    Returns:
    {
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_pnl": 0.0,
        "pnl_over_time": [
            {"ts": "...", "realized": 0.0, "unrealized": 0.0, "total": 0.0}
        ]
    }
    """
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Verify run belongs to tenant
        cursor.execute(
            "SELECT run_id, execution_mode FROM runs WHERE run_id = ? AND tenant_id = ?",
            (run_id, tenant_id)
        )
        run_row = cursor.fetchone()
        if not run_row:
            raise HTTPException(status_code=404, detail="Run not found")
        
        # Get orders and fills
        cursor.execute(
            """
            SELECT o.order_id, o.symbol, o.side, o.notional_usd, o.avg_fill_price, o.total_fees,
                   o.status, o.created_at, o.filled_qty
            FROM orders o
            WHERE o.run_id = ? AND o.tenant_id = ?
            """,
            (run_id, tenant_id)
        )
        orders = cursor.fetchall()
        
        # Get fills for all orders
        order_ids = [o["order_id"] for o in orders]
        fills = []
        if order_ids:
            placeholders = ",".join(["?"] * len(order_ids))
            cursor.execute(
                f"""
                SELECT fill_id, order_id, product_id, price, size, fee, filled_at
                FROM fills
                WHERE order_id IN ({placeholders})
                ORDER BY filled_at ASC
                """,
                order_ids
            )
            fills = cursor.fetchall()
        
        # Get portfolio snapshots over time
        cursor.execute(
            """
            SELECT snapshot_id, total_value_usd, balances_json, positions_json, ts
            FROM portfolio_snapshots
            WHERE run_id = ? AND tenant_id = ?
            ORDER BY ts ASC
            """,
            (run_id, tenant_id)
        )
        snapshots = cursor.fetchall()
    
    # Calculate realized PnL from fills
    realized_pnl = 0.0
    for fill in fills:
        # Realized PnL = fees (negative)
        realized_pnl -= float(fill["fee"] or 0.0)
    
    # For BUY orders: realized PnL = fees only (we need exit price for full calculation)
    # For SELL orders: realized PnL = (sell_price - buy_price) * size - fees
    # Simplified: assume we're calculating from order creation cost vs current value
    
    # Calculate unrealized PnL (current value - cost basis)
    unrealized_pnl = 0.0
    if snapshots:
        # Get initial portfolio value
        initial_snapshot = snapshots[0]
        initial_value = float(initial_snapshot["total_value_usd"])
        
        # Get final portfolio value
        final_snapshot = snapshots[-1]
        final_value = float(final_snapshot["total_value_usd"])
        
        # Total cost of orders
        total_cost = sum(float(o["notional_usd"]) + float(o["total_fees"] or 0.0) for o in orders if o["side"] == "BUY")
        
        # Unrealized = current_value - cost_basis
        # Simplified: use final snapshot value - initial value - total cost
        unrealized_pnl = final_value - initial_value - total_cost
    
    total_pnl = realized_pnl + unrealized_pnl
    
    # Build PnL over time series
    pnl_over_time = []
    if snapshots:
        initial_value = float(snapshots[0]["total_value_usd"])
        cumulative_realized = 0.0
        
        for snapshot in snapshots:
            snapshot_value = float(snapshot["total_value_usd"])
            snapshot_ts = snapshot["ts"]
            
            # Accumulate realized from fills up to this timestamp
            snapshot_realized = sum(
                -float(f["fee"] or 0.0) for f in fills
                if f["filled_at"] <= snapshot_ts
            )
            
            # Unrealized = current value - initial value - cost + realized
            snapshot_unrealized = snapshot_value - initial_value - snapshot_realized
            snapshot_total = snapshot_realized + snapshot_unrealized
            
            pnl_over_time.append({
                "ts": snapshot_ts,
                "realized": snapshot_realized,
                "unrealized": snapshot_unrealized,
                "total": snapshot_total
            })
    
    return {
        "run_id": run_id,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "pnl_over_time": pnl_over_time,
        "orders_count": len(orders),
        "fills_count": len(fills)
    }

