"""Portfolio API routes."""
from fastapi import APIRouter, Depends, Query
from typing import Optional
import json
from backend.api.deps import require_viewer
from backend.db.connect import get_conn

router = APIRouter()


@router.get("/metrics/value-over-time")
async def get_value_over_time(
    run_id: Optional[str] = Query(None),
    user: dict = Depends(require_viewer)
):
    """Get portfolio value over time for charts."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        if run_id:
            cursor.execute(
                """
                SELECT ts, total_value_usd, balances_json
                FROM portfolio_snapshots
                WHERE run_id = ? AND tenant_id = ?
                ORDER BY ts ASC
                """,
                (run_id, tenant_id)
            )
        else:
            cursor.execute(
                """
                SELECT ts, total_value_usd, balances_json
                FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC
                LIMIT 100
                """,
                (tenant_id,)
            )
        rows = cursor.fetchall()
    
    metrics = []
    for row in rows:
        balances = json.loads(row["balances_json"])
        cash_usd = balances.get("USD", 0.0)
        metrics.append({
            "ts": row["ts"],
            "total_value_usd": row["total_value_usd"],
            "cash_usd": cash_usd
        })
    
    return metrics
