"""Time Window Correctness Evaluation.

Checks that stored candle window matches the oracle-computed expected window
derived from the intent's lookback period.
"""
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.utils import _safe_json_loads
from backend.evals.oracle_artifacts import compute_oracle_time_window

logger = get_logger(__name__)


def evaluate_time_window_correctness(run_id: str, tenant_id: str) -> dict:
    """Verify actual candle window covers the expected oracle window.

    Returns:
        {"score": float, "reasons": list[str], "thresholds": dict, "details": dict}
    """
    oracle_window = compute_oracle_time_window(run_id)
    if not oracle_window:
        return {
            "score": 0.5,
            "reasons": ["No intent/run data available for time window computation"],
            "thresholds": {"min_coverage": 0.9},
            "details": {},
        }

    # Get actual candle window from frozen evidence
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT symbol, candles_json FROM market_candles_batches WHERE run_id = ?",
            (run_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return {
            "score": 0.0,
            "reasons": ["No candle batches found for this run"],
            "thresholds": {"min_coverage": 0.9},
            "details": {"expected_lookback_hours": oracle_window["lookback_hours"]},
        }

    from datetime import datetime

    def _parse_ts(ts_str):
        if not ts_str:
            return None
        try:
            s = str(ts_str)
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    # Compute actual coverage across all symbols
    actual_start = None
    actual_end = None
    for row in rows:
        candles = _safe_json_loads(row["candles_json"], default=[])
        if not candles:
            continue
        first_ts = _parse_ts(candles[0].get("start_time", candles[0].get("t")))
        last_ts = _parse_ts(candles[-1].get("end_time", candles[-1].get("t")))
        if first_ts and (actual_start is None or first_ts < actual_start):
            actual_start = first_ts
        if last_ts and (actual_end is None or last_ts > actual_end):
            actual_end = last_ts

    if not actual_start or not actual_end:
        return {
            "score": 0.0,
            "reasons": ["Could not parse candle timestamps"],
            "thresholds": {"min_coverage": 0.9},
            "details": {},
        }

    expected_start = _parse_ts(oracle_window["expected_start"])
    expected_end = _parse_ts(oracle_window["expected_end"])

    if not expected_start or not expected_end:
        return {
            "score": 0.5,
            "reasons": ["Could not parse expected window timestamps"],
            "thresholds": {"min_coverage": 0.9},
            "details": {},
        }

    expected_span = (expected_end - expected_start).total_seconds()
    if expected_span <= 0:
        return {
            "score": 0.5,
            "reasons": ["Expected window has zero or negative span"],
            "thresholds": {"min_coverage": 0.9},
            "details": {},
        }

    # Compute overlap
    overlap_start = max(actual_start, expected_start)
    overlap_end = min(actual_end, expected_end)
    overlap = max(0, (overlap_end - overlap_start).total_seconds())
    coverage = overlap / expected_span

    score = min(1.0, coverage)
    if coverage >= 0.9:
        reasons = [f"Candle window covers {coverage:.0%} of expected {oracle_window['lookback_hours']}h window"]
    else:
        reasons = [
            f"Candle window covers only {coverage:.0%} of expected {oracle_window['lookback_hours']}h window"
        ]

    return {
        "score": round(score, 4),
        "reasons": reasons,
        "thresholds": {"min_coverage": 0.9},
        "details": {
            "coverage_pct": round(coverage, 4),
            "expected_hours": oracle_window["lookback_hours"],
            "actual_start": actual_start.isoformat(),
            "actual_end": actual_end.isoformat(),
        },
    }
