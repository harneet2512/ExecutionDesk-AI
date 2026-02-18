"""Analytics: Slippage endpoints."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.api.deps import require_viewer
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/slippage")
async def get_slippage(
    run_id: str = Query(..., description="Run ID"),
    user: dict = Depends(require_viewer)
):
    """
    Get slippage analytics for a run.
    
    Returns:
    {
        "slippage_data": [
            {
                "order_id": "...",
                "symbol": "BTC-USD",
                "expected_price": 45000.0,
                "avg_fill_price": 45010.0,
                "slippage_bps": 2.22,  # (45010 - 45000) / 45000 * 10000
                "slippage_pct": 0.0222
            }
        ],
        "distribution": {
            "bins": [0, 1, 5, 10, 50, 100],
            "counts": [2, 3, 1, 0, 0, 0]  # Count of orders in each bin
        },
        "summary": {
            "avg_slippage_bps": 2.5,
            "max_slippage_bps": 10.0,
            "min_slippage_bps": 0.0
        }
    }
    """
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Verify run belongs to tenant
        cursor.execute(
            "SELECT run_id FROM runs WHERE run_id = ? AND tenant_id = ?",
            (run_id, tenant_id)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Run not found")
        
        # Get orders with expected prices from proposal or signals
        cursor.execute(
            """
            SELECT o.order_id, o.symbol, o.notional_usd, o.avg_fill_price, o.created_at,
                   dn.outputs_json
            FROM orders o
            LEFT JOIN dag_nodes dn ON dn.run_id = o.run_id AND dn.name = 'signals'
            WHERE o.run_id = ? AND o.tenant_id = ? AND o.avg_fill_price IS NOT NULL
            ORDER BY o.created_at ASC
            """,
            (run_id, tenant_id)
        )
        orders = cursor.fetchall()
        
        # Get expected prices from signals node or proposal
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes
            WHERE run_id = ? AND (name = 'signals' OR name = 'proposal')
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        signals_row = cursor.fetchone()
        
        expected_prices = {}
        if signals_row:
            signals_output = json.loads(signals_row["outputs_json"])
            # Extract expected prices from signals or proposal
            if "top_symbol" in signals_output and "last_price" in signals_output:
                expected_prices[signals_output["top_symbol"]] = signals_output.get("last_price", 0.0)
            elif "chosen_product_id" in signals_output:
                # Try to get from research node
                cursor.execute(
                    """
                    SELECT outputs_json FROM dag_nodes
                    WHERE run_id = ? AND name = 'research'
                    ORDER BY started_at DESC LIMIT 1
                    """,
                    (run_id,)
                )
                research_row = cursor.fetchone()
                if research_row:
                    research_output = json.loads(research_row["outputs_json"])
                    returns_by_symbol = research_output.get("returns_by_symbol", {})
                    # Use last_close from candles (approximate)
                    # For now, use avg_fill_price as proxy if not available
                    pass
    
    slippage_data = []
    all_slippage_bps = []
    
    for order in orders:
        symbol = order["symbol"]
        avg_fill_price = float(order["avg_fill_price"])
        notional = float(order["notional_usd"])
        
        # Get expected price from signals/research or use market data at order time
        expected_price = expected_prices.get(symbol)
        if not expected_price:
            # Fallback: use price from market_candles at order creation time
            cursor.execute(
                """
                SELECT close FROM market_candles
                WHERE symbol = ? AND start_time <= ? AND end_time >= ?
                ORDER BY ts DESC LIMIT 1
                """,
                (symbol, order["created_at"], order["created_at"])
            )
            price_row = cursor.fetchone()
            if price_row:
                expected_price = float(price_row["close"])
            else:
                # If no candles, assume no slippage (expected = actual)
                expected_price = avg_fill_price
        
        # Calculate slippage in basis points (1 bp = 0.01%)
        if expected_price > 0:
            slippage_pct = (avg_fill_price - expected_price) / expected_price
            slippage_bps = slippage_pct * 10000  # Convert to basis points
            
            slippage_data.append({
                "order_id": order["order_id"],
                "symbol": symbol,
                "expected_price": expected_price,
                "avg_fill_price": avg_fill_price,
                "slippage_bps": slippage_bps,
                "slippage_pct": slippage_pct
            })
            all_slippage_bps.append(abs(slippage_bps))
    
    # Distribution bins (bps): [0, 1, 5, 10, 50, 100, 1000]
    bins = [0, 1, 5, 10, 50, 100, 1000]
    counts = [0] * (len(bins) - 1)
    
    for slippage_bps_val in all_slippage_bps:
        for i in range(len(bins) - 1):
            if bins[i] <= slippage_bps_val < bins[i + 1]:
                counts[i] += 1
                break
        if slippage_bps_val >= bins[-1]:
            counts[-1] += 1
    
    # Summary stats
    avg_slippage_bps = sum(all_slippage_bps) / len(all_slippage_bps) if all_slippage_bps else 0.0
    max_slippage_bps = max(all_slippage_bps) if all_slippage_bps else 0.0
    min_slippage_bps = min(all_slippage_bps) if all_slippage_bps else 0.0
    
    return {
        "run_id": run_id,
        "slippage_data": slippage_data,
        "distribution": {
            "bins": bins,
            "counts": counts
        },
        "summary": {
            "avg_slippage_bps": avg_slippage_bps,
            "max_slippage_bps": max_slippage_bps,
            "min_slippage_bps": min_slippage_bps,
            "orders_count": len(slippage_data)
        }
    }

