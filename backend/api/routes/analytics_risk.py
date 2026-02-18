"""Analytics: Risk endpoints."""
import json
from fastapi import APIRouter, Depends, HTTPException
from backend.api.deps import require_viewer
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/risk")
async def get_risk(
    user: dict = Depends(require_viewer)
):
    """
    Get risk analytics across all runs.
    
    Returns:
    {
        "exposure_by_asset": [
            {"asset": "BTC-USD", "total_value": 500.0, "percentage": 50.0}
        ],
        "concentration": {
            "top_asset_pct": 50.0,
            "top_3_assets_pct": 80.0
        },
        "drawdown": [
            {"ts": "...", "peak_value": 1000.0, "current_value": 950.0, "drawdown_pct": 5.0}
        ]
    }
    """
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get latest portfolio snapshot
        cursor.execute(
            """
            SELECT balances_json, positions_json, total_value_usd, ts
            FROM portfolio_snapshots
            WHERE tenant_id = ?
            ORDER BY ts DESC LIMIT 1
            """,
            (tenant_id,)
        )
        snapshot_row = cursor.fetchone()
        
        if not snapshot_row:
            return {
                "exposure_by_asset": [],
                "concentration": {"top_asset_pct": 0.0, "top_3_assets_pct": 0.0},
                "drawdown": []
            }
        
        positions = json.loads(snapshot_row["positions_json"])
        total_value = float(snapshot_row["total_value_usd"])
        
        # Get current prices for positions
        from backend.providers.coinbase_market_data import CoinbaseMarketDataProvider
        market_data_provider = CoinbaseMarketDataProvider()
        
        exposure_by_asset = []
        for symbol, qty in positions.items():
            try:
                price = market_data_provider.get_price(f"{symbol}-USD" if "-" not in symbol else symbol)
                asset_value = float(qty) * price
                exposure_by_asset.append({
                    "asset": symbol,
                    "quantity": float(qty),
                    "price": price,
                    "total_value": asset_value,
                    "percentage": (asset_value / total_value * 100) if total_value > 0 else 0.0
                })
            except Exception:
                pass
        
        # Sort by value descending
        exposure_by_asset.sort(key=lambda x: x["total_value"], reverse=True)
        
        # Concentration metrics
        top_asset_pct = exposure_by_asset[0]["percentage"] if exposure_by_asset else 0.0
        top_3_assets_pct = sum(e["percentage"] for e in exposure_by_asset[:3])
        
        # Drawdown calculation
        cursor.execute(
            """
            SELECT total_value_usd, ts
            FROM portfolio_snapshots
            WHERE tenant_id = ?
            ORDER BY ts ASC
            """,
            (tenant_id,)
        )
        snapshots = cursor.fetchall()
        
        drawdown = []
        peak_value = 0.0
        for snapshot in snapshots:
            current_value = float(snapshot["total_value_usd"])
            if current_value > peak_value:
                peak_value = current_value
            
            drawdown_pct = ((peak_value - current_value) / peak_value * 100) if peak_value > 0 else 0.0
            
            drawdown.append({
                "ts": snapshot["ts"],
                "peak_value": peak_value,
                "current_value": current_value,
                "drawdown_pct": drawdown_pct
            })
    
    return {
        "exposure_by_asset": exposure_by_asset,
        "concentration": {
            "top_asset_pct": top_asset_pct,
            "top_3_assets_pct": top_3_assets_pct
        },
        "drawdown": drawdown
    }

