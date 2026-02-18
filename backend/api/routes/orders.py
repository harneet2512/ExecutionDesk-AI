"""Orders API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
import json
from backend.api.deps import require_viewer, require_trader, get_current_user
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.time import now_iso

logger = get_logger(__name__)

router = APIRouter()


@router.get("")
async def list_orders(
    run_id: Optional[str] = Query(None),
    user: dict = Depends(require_viewer)
):
    """List orders."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        if run_id:
            cursor.execute(
                "SELECT * FROM orders WHERE run_id = ? AND tenant_id = ?",
                (run_id, tenant_id)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM orders 
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (tenant_id,)
            )
        rows = cursor.fetchall()
    
    return [dict(row) for row in rows]


@router.get("/metrics/fill-latency")
async def get_fill_latency_metrics(user: dict = Depends(get_current_user)):
    """Get order fill latency metrics."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT oe.ts, oe.payload_json
            FROM order_events oe
            JOIN orders o ON oe.order_id = o.order_id
            WHERE o.tenant_id = ? AND oe.event_type = 'FILLED'
            ORDER BY oe.ts ASC
            """,
            (tenant_id,)
        )
        rows = cursor.fetchall()
    
    metrics = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
            latency_ms = payload.get("latency_ms", 0)
            metrics.append({
                "ts": row["ts"],
                "latency_ms": latency_ms
            })
        except Exception as e:
            continue

    return metrics


@router.post("/{order_id}/reconcile")
async def reconcile_order(order_id: str, user: dict = Depends(require_trader)):
    """Check exchange status for a SUBMITTED order and update local DB to match."""
    tenant_id = user["tenant_id"]

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM orders WHERE order_id = ? AND tenant_id = ?",
            (order_id, tenant_id)
        )
        order = cursor.fetchone()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order_dict = dict(order)

    if order_dict["status"] not in ("SUBMITTED",):
        return {
            "order_id": order_id,
            "status": order_dict["status"],
            "message": f"Order already in terminal state: {order_dict['status']}",
            "reconciled": False,
        }

    provider = (order_dict.get("provider") or "").upper()
    if provider != "COINBASE":
        return {
            "order_id": order_id,
            "status": order_dict["status"],
            "message": f"Reconciliation not supported for provider: {provider}",
            "reconciled": False,
        }

    try:
        from backend.providers.coinbase_provider import CoinbaseProvider

        cb = CoinbaseProvider()
        status_data = cb._get_order_status(order_id, run_id=order_dict.get("run_id"))

        if not status_data:
            return {
                "order_id": order_id,
                "status": order_dict["status"],
                "message": "Could not fetch status from exchange",
                "reconciled": False,
            }

        new_status = (status_data.get("status") or "").upper()

        if new_status and new_status != order_dict["status"]:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE orders SET status = ?, status_updated_at = ?, status_reason = ? WHERE order_id = ?",
                    (new_status, now_iso(), f"Reconciled from {order_dict['status']}", order_id),
                )
                conn.commit()

            # If filled, fetch fills too
            if new_status == "FILLED":
                try:
                    cb._fetch_and_store_fills(order_id, order_dict["run_id"], tenant_id)
                except Exception:
                    pass  # best effort

            logger.info(f"Order {order_id} reconciled: {order_dict['status']} -> {new_status}")
            return {
                "order_id": order_id,
                "status": new_status,
                "previous_status": order_dict["status"],
                "message": f"Order reconciled: {order_dict['status']} -> {new_status}",
                "reconciled": True,
            }

        return {
            "order_id": order_id,
            "status": new_status or order_dict["status"],
            "message": "Order status unchanged on exchange",
            "reconciled": False,
        }
    except ValueError as e:
        # Live trading disabled or keys missing
        return {
            "order_id": order_id,
            "status": order_dict["status"],
            "message": f"Cannot reconcile: {str(e)[:200]}",
            "reconciled": False,
        }
    except Exception as e:
        logger.warning(f"Reconciliation failed for order {order_id}: {e}")
        return {
            "order_id": order_id,
            "status": order_dict["status"],
            "message": f"Reconciliation error: {str(e)[:200]}",
            "reconciled": False,
        }
