"""Confirm Trade Idempotency Evaluation.

Checks that no duplicate orders were placed for the same trade confirmation.
"""
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_confirm_trade_idempotency(run_id: str, tenant_id: str) -> dict:
    """Verify no duplicate orders exist for the same confirmation or client_order_id.

    Returns:
        {"score": float, "reasons": list[str], "thresholds": dict, "details": dict}
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        # Check for duplicate client_order_ids within this run
        cursor.execute(
            """
            SELECT client_order_id, COUNT(*) as cnt
            FROM orders
            WHERE run_id = ? AND client_order_id IS NOT NULL
            GROUP BY client_order_id
            HAVING cnt > 1
            """,
            (run_id,),
        )
        dup_client_ids = cursor.fetchall()

        # Check for duplicate symbol+side combinations (same order placed twice)
        cursor.execute(
            """
            SELECT symbol, side, COUNT(*) as cnt
            FROM orders
            WHERE run_id = ?
            GROUP BY symbol, side
            HAVING cnt > 1
            """,
            (run_id,),
        )
        dup_symbol_sides = cursor.fetchall()

        # Get total order count
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE run_id = ?",
            (run_id,),
        )
        total_orders = cursor.fetchone()["cnt"]

    if total_orders == 0:
        return {
            "score": 1.0,
            "reasons": ["No orders for this run (vacuously idempotent)"],
            "thresholds": {"pass": 1.0},
            "details": {"order_count": 0},
        }

    issues = []

    for row in dup_client_ids:
        issues.append(
            f"Duplicate client_order_id '{row['client_order_id']}' "
            f"appeared {row['cnt']} times"
        )

    for row in dup_symbol_sides:
        issues.append(
            f"Duplicate order: {row['symbol']} {row['side']} "
            f"appeared {row['cnt']} times"
        )

    if not issues:
        score = 1.0
        reasons = [f"All {total_orders} orders are unique (no duplicates)"]
    else:
        score = 0.0
        reasons = issues

    return {
        "score": score,
        "reasons": reasons,
        "thresholds": {"pass": 1.0},
        "details": {
            "order_count": total_orders,
            "duplicate_client_ids": len(dup_client_ids),
            "duplicate_symbol_sides": len(dup_symbol_sides),
        },
    }
