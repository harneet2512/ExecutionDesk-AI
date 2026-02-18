"""Execution Quality Evaluation - checks slippage, fees, fill prices."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_execution_quality(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Execution Quality
    
    Checks:
    - Slippage within threshold (default 50 bps = 0.5%)
    - Fees present for all fills
    - Avg fill price present for orders
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get orders with fills
        cursor.execute(
            """
            SELECT o.order_id, o.symbol, o.avg_fill_price, o.total_fees, o.filled_qty
            FROM orders o
            WHERE o.run_id = ? AND o.tenant_id = ? AND o.status = 'FILLED'
            """,
            (run_id, tenant_id)
        )
        orders = cursor.fetchall()
        
        if not orders:
            return {"score": 1.0, "reasons": ["No filled orders (evaluation skipped)"]}
        
        # Get fills
        order_ids = [o["order_id"] for o in orders]
        fills = []
        if order_ids:
            placeholders = ",".join(["?"] * len(order_ids))
            cursor.execute(
                f"""
                SELECT fill_id, order_id, price, size, fee
                FROM fills
                WHERE order_id IN ({placeholders})
                """,
                order_ids
            )
            fills = cursor.fetchall()
        
        # Check metrics
        slippage_threshold_bps = 50.0  # 0.5%
        checks = {
            "fees_present": 0,
            "avg_fill_price_present": 0,
            "slippage_within_threshold": 0
        }
        total_checks = 0
        
        for order in orders:
            order_id = order["order_id"]
            # Use dictionary-style access for sqlite3.Row (check if key exists)
            avg_fill_price = order["avg_fill_price"] if "avg_fill_price" in order.keys() else None
            total_fees = order["total_fees"] if "total_fees" in order.keys() else None
            
            # Check avg_fill_price present
            total_checks += 1
            if avg_fill_price is not None and float(avg_fill_price) > 0:
                checks["avg_fill_price_present"] += 1
            
            # Check fees present
            total_checks += 1
            if total_fees is not None and float(total_fees) >= 0:
                checks["fees_present"] += 1
            
            # Check slippage (simplified: assume expected price from proposal or signals)
            if avg_fill_price:
                cursor.execute(
                    """
                    SELECT outputs_json FROM dag_nodes
                    WHERE run_id = ? AND name IN ('signals', 'proposal')
                    ORDER BY started_at DESC LIMIT 1
                    """,
                    (run_id,)
                )
                outputs_row = cursor.fetchone()
                if outputs_row:
                    outputs = json.loads(outputs_row["outputs_json"])
                    expected_price = None
                    
                    # Try to get expected price
                    if "last_price" in outputs:
                        expected_price = outputs["last_price"]
                    elif "expected_price" in outputs:
                        expected_price = outputs["expected_price"]
                    
                    if expected_price and float(expected_price) > 0:
                        slippage_pct = abs(float(avg_fill_price) - float(expected_price)) / float(expected_price)
                        slippage_bps = slippage_pct * 10000
                        
                        total_checks += 1
                        if slippage_bps <= slippage_threshold_bps:
                            checks["slippage_within_threshold"] += 1
        
        # Calculate score
        passed_checks = sum(checks.values())
        score = passed_checks / total_checks if total_checks > 0 else 1.0
        
        reasons = [
            f"Fees present: {checks['fees_present']}/{len(orders)} orders",
            f"Avg fill price present: {checks['avg_fill_price_present']}/{len(orders)} orders",
            f"Slippage within {slippage_threshold_bps}bps: {checks['slippage_within_threshold']} orders"
        ]
    
    return {"score": score, "reasons": reasons, "thresholds": {"slippage_bps": slippage_threshold_bps}}
