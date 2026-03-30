"""Analytics API endpoint."""
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from backend.api.deps import require_viewer
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/performance")
async def get_performance(
    window: str = Query(default="7d", description="Time window: 1d, 7d, 30d"),
    user: dict = Depends(require_viewer)
):
    """
    Get performance analytics for last N days.
    
    Returns:
    {
        "daily_pnl": [{date, pnl, returns, trades_count}],
        "summary": {
            "total_pnl": ...,
            "total_returns": ...,
            "win_rate": ...,
            "avg_trade_size": ...
        },
        "trades": [...]
    }
    """
    tenant_id = user["tenant_id"]
    
    # Parse window
    days = 7
    if window == "1d":
        days = 1
    elif window == "7d":
        days = 7
    elif window == "30d":
        days = 30
    
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get completed runs in window
        cursor.execute(
            """
            SELECT run_id, created_at, completed_at, status, execution_mode
            FROM runs
            WHERE tenant_id = ? AND status = 'COMPLETED' AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (tenant_id, cutoff_date)
        )
        runs = cursor.fetchall()
        
        # Get orders from these runs
        run_ids = [r["run_id"] for r in runs]
        if not run_ids:
            return {
                "daily_pnl": [],
                "summary": {
                    "total_pnl": 0.0,
                    "total_returns": 0.0,
                    "win_rate": 0.0,
                    "avg_trade_size": 0.0,
                    "trades_count": 0
                },
                "trades": []
            }
        
        placeholders = ",".join("?" * len(run_ids))
        cursor.execute(
            f"""
            SELECT order_id, run_id, symbol, side, notional_usd, created_at
            FROM orders
            WHERE run_id IN ({placeholders}) AND status = 'FILLED'
            ORDER BY created_at DESC
            """,
            run_ids
        )
        orders = cursor.fetchall()
        
        # Get portfolio snapshots for PnL calculation
        cursor.execute(
            f"""
            SELECT run_id, ts, total_value_usd
            FROM portfolio_snapshots
            WHERE run_id IN ({placeholders})
            ORDER BY ts ASC
            """,
            run_ids
        )
        snapshots = cursor.fetchall()
        
        # Group by date
        daily_data = {}
        for snapshot in snapshots:
            date_str = snapshot["ts"][:10]  # YYYY-MM-DD
            if date_str not in daily_data:
                daily_data[date_str] = {
                    "date": date_str,
                    "pnl": 0.0,
                    "returns": 0.0,
                    "trades_count": 0,
                    "start_value": snapshot["total_value_usd"],
                    "end_value": snapshot["total_value_usd"]
                }
            daily_data[date_str]["end_value"] = snapshot["total_value_usd"]
        
        # Calculate daily PnL (simplified: end - start)
        daily_pnl = []
        for date_str in sorted(daily_data.keys()):
            day = daily_data[date_str]
            if day.get("start_value"):
                day["pnl"] = day["end_value"] - day["start_value"]
                day["returns"] = day["pnl"] / day["start_value"] if day["start_value"] > 0 else 0.0
            
            # Count trades for this date
            day["trades_count"] = sum(1 for o in orders if o["created_at"][:10] == date_str)
            daily_pnl.append(day)
        
        # Calculate summary
        total_pnl = sum(d["pnl"] for d in daily_pnl)
        total_returns = sum(d["returns"] for d in daily_pnl) / len(daily_pnl) if daily_pnl else 0.0
        trades_count = len(orders)
        avg_trade_size = sum(float(o["notional_usd"]) for o in orders) / trades_count if trades_count > 0 else 0.0
        
        # Win rate (simplified: based on positive returns)
        winning_days = sum(1 for d in daily_pnl if d["returns"] > 0)
        win_rate = winning_days / len(daily_pnl) if daily_pnl else 0.0
        
        # Build trades list
        trades = []
        for order in orders[:100]:  # Last 100 trades
            trades.append({
                "order_id": order["order_id"],
                "run_id": order["run_id"],
                "symbol": order["symbol"],
                "side": order["side"],
                "notional_usd": float(order["notional_usd"]),
                "created_at": order["created_at"]
            })
        
        return {
            "daily_pnl": daily_pnl,
            "summary": {
                "total_pnl": total_pnl,
                "total_returns": total_returns,
                "win_rate": win_rate,
                "avg_trade_size": avg_trade_size,
                "trades_count": trades_count
            },
            "trades": trades
        }
