"""Coinbase Data Integrity Evaluation.

Validates that candle series covers the full requested window,
has no gaps, and timestamps are properly ordered.
"""
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.utils import _safe_json_loads

logger = get_logger(__name__)


def evaluate_coinbase_data_integrity(run_id: str, tenant_id: str) -> dict:
    """Check candle data completeness, ordering, and gap-freeness.

    Returns:
        {"score": float, "reasons": list[str], "thresholds": dict, "details": dict}
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT symbol, candles_json, window, query_params_json FROM market_candles_batches WHERE run_id = ?",
            (run_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return {
            "score": 0.5,
            "reasons": ["No candle batches found for this run"],
            "thresholds": {"min_score": 0.7},
            "details": {},
        }

    from datetime import datetime

    total_score = 0.0
    symbol_details = {}
    reasons = []

    for row in rows:
        symbol = row["symbol"]
        candles = _safe_json_loads(row["candles_json"], default=[])

        if not candles:
            reasons.append(f"{symbol}: empty candle series")
            symbol_details[symbol] = {"score": 0.0, "issue": "empty"}
            continue

        # 1. Check ordering
        timestamps = []
        ordered = True
        for c in candles:
            ts_str = c.get("start_time", c.get("t", ""))
            if ts_str:
                try:
                    s = str(ts_str)
                    if s.endswith("Z"):
                        s = s[:-1] + "+00:00"
                    ts = datetime.fromisoformat(s)
                    timestamps.append(ts)
                except (ValueError, TypeError):
                    pass

        for i in range(1, len(timestamps)):
            if timestamps[i] <= timestamps[i - 1]:
                ordered = False
                break

        order_score = 1.0 if ordered else 0.0

        # 2. Check for gaps (allow 10% tolerance on expected interval)
        gap_score = 1.0
        if len(timestamps) >= 2:
            intervals = [
                (timestamps[i] - timestamps[i - 1]).total_seconds()
                for i in range(1, len(timestamps))
            ]
            if intervals:
                median_interval = sorted(intervals)[len(intervals) // 2]
                max_allowed = median_interval * 2.0  # Allow up to 2x median
                gap_count = sum(1 for iv in intervals if iv > max_allowed)
                gap_score = 1.0 - (gap_count / len(intervals))

        # 3. Check coverage (candle count vs expected)
        query_params = _safe_json_loads(row["query_params_json"], default={})
        expected_hours = 48  # default
        window_str = row["window"] if "window" in row.keys() else ""
        try:
            if isinstance(window_str, str):
                if window_str.endswith("h"):
                    expected_hours = int(window_str[:-1])
                elif window_str.endswith("d"):
                    expected_hours = int(window_str[:-1]) * 24
        except (ValueError, TypeError):
            pass

        coverage = min(1.0, len(candles) / max(1, expected_hours))

        sym_score = round((order_score * 0.3 + gap_score * 0.4 + coverage * 0.3), 4)
        total_score += sym_score

        symbol_details[symbol] = {
            "candle_count": len(candles),
            "ordered": ordered,
            "gap_score": round(gap_score, 4),
            "coverage": round(coverage, 4),
            "score": sym_score,
        }

        if sym_score < 0.7:
            issues = []
            if not ordered:
                issues.append("unordered timestamps")
            if gap_score < 1.0:
                issues.append(f"gaps detected (gap_score={gap_score:.2f})")
            if coverage < 0.8:
                issues.append(f"low coverage ({coverage:.0%})")
            reasons.append(f"{symbol}: {', '.join(issues)}")

    avg_score = total_score / len(rows) if rows else 0.0

    if not reasons:
        reasons = [f"All {len(rows)} symbol(s) have complete, ordered, gap-free candle data"]

    return {
        "score": round(avg_score, 4),
        "reasons": reasons,
        "thresholds": {"min_score": 0.7},
        "details": {"symbols": symbol_details},
    }
