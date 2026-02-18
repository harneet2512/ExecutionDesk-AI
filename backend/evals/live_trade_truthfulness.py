"""Live Trade Truthfulness Evaluation.

Ensures the system never claims an order is FILLED unless fill evidence
(filled_qty > 0, avg_fill_price > 0) exists in the orders table.
"""
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_live_trade_truthfulness(run_id: str, tenant_id: str) -> dict:
    """Check every FILLED order has actual fill evidence.

    Returns:
        {"score": float, "reasons": list[str], "thresholds": dict, "details": dict}
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT order_id, symbol, status, filled_qty, avg_fill_price FROM orders WHERE run_id = ?",
            (run_id,),
        )
        orders = cursor.fetchall()

    if not orders:
        return {
            "score": 1.0,
            "reasons": ["No orders for this run (vacuously true)"],
            "thresholds": {"pass": 1.0},
            "details": {"order_count": 0},
        }

    total_filled = 0
    truthful = 0
    issues = []

    for order in orders:
        status = order["status"]
        if status and status.upper() == "FILLED":
            total_filled += 1
            filled_qty = order["filled_qty"]
            avg_price = order["avg_fill_price"]

            has_qty = filled_qty is not None and float(filled_qty) > 0
            has_price = avg_price is not None and float(avg_price) > 0

            if has_qty and has_price:
                truthful += 1
            else:
                missing = []
                if not has_qty:
                    missing.append("filled_qty")
                if not has_price:
                    missing.append("avg_fill_price")
                issues.append(
                    f"Order {order['order_id']} ({order['symbol']}): "
                    f"status=FILLED but missing {', '.join(missing)}"
                )

    if total_filled == 0:
        return {
            "score": 1.0,
            "reasons": ["No FILLED orders to verify"],
            "thresholds": {"pass": 1.0},
            "details": {"order_count": len(orders), "filled_count": 0},
        }

    score = truthful / total_filled
    if score == 1.0:
        reasons = [f"All {total_filled} FILLED orders have valid fill evidence"]
    else:
        reasons = issues

    return {
        "score": score,
        "reasons": reasons,
        "thresholds": {"pass": 1.0},
        "details": {
            "order_count": len(orders),
            "filled_count": total_filled,
            "truthful_count": truthful,
        },
    }
