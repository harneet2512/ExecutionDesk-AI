"""Oracle Artifacts System.

Computes deterministic ground-truth rankings from frozen evidence
(market_candles_batches) to compare against agent decisions.
"""
import json
from typing import Optional
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger
from backend.core.utils import _safe_json_loads

logger = get_logger(__name__)


def compute_oracle_profit_ranking(run_id: str) -> Optional[dict]:
    """From frozen market_candles_batches, recompute asset returns and rank.

    Returns:
        Dict with oracle_top_symbol, oracle_top_return, rankings list,
        window_start, window_end.  None if no candle data found.
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT symbol, candles_json, window FROM market_candles_batches WHERE run_id = ?",
            (run_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return None

    rankings = []
    window_start = None
    window_end = None

    for row in rows:
        symbol = row["symbol"]
        candles = _safe_json_loads(row["candles_json"], default=[])
        if not candles:
            continue

        # Extract first and last close prices
        try:
            first_close = float(candles[0].get("close", candles[0].get("c", 0)))
            last_close = float(candles[-1].get("close", candles[-1].get("c", 0)))
        except (TypeError, ValueError, IndexError):
            continue

        if first_close <= 0:
            continue

        gross_return = (last_close - first_close) / first_close

        # Track window bounds
        first_ts = candles[0].get("start_time", candles[0].get("t"))
        last_ts = candles[-1].get("end_time", candles[-1].get("t"))
        if first_ts:
            if window_start is None or str(first_ts) < str(window_start):
                window_start = first_ts
        if last_ts:
            if window_end is None or str(last_ts) > str(window_end):
                window_end = last_ts

        rankings.append({
            "symbol": symbol,
            "gross_return": round(gross_return, 6),
            "first_close": first_close,
            "last_close": last_close,
            "candle_count": len(candles),
        })

    if not rankings:
        return None

    # Sort descending by return
    rankings.sort(key=lambda r: r["gross_return"], reverse=True)

    return {
        "oracle_top_symbol": rankings[0]["symbol"],
        "oracle_top_return": rankings[0]["gross_return"],
        "rankings": rankings,
        "window_start": window_start,
        "window_end": window_end,
    }


def compute_oracle_time_window(run_id: str) -> Optional[dict]:
    """From frozen intent + run.created_at, compute expected UTC window.

    Returns:
        Dict with expected_start, expected_end, lookback_hours.
        None if no intent data found.
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        # Try intents table first
        cursor.execute(
            "SELECT intent_json FROM intents WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,),
        )
        intent_row = cursor.fetchone()
        intent = _safe_json_loads(
            intent_row["intent_json"] if intent_row else None, default=None
        )

        # Fallback to runs table
        if not intent:
            cursor.execute(
                "SELECT intent_json, parsed_intent_json, created_at FROM runs WHERE run_id = ?",
                (run_id,),
            )
            run_row = cursor.fetchone()
            if not run_row:
                return None
            intent = _safe_json_loads(run_row["intent_json"], default=None)
            if not intent and "parsed_intent_json" in run_row.keys():
                intent = _safe_json_loads(run_row["parsed_intent_json"], default=None)
            created_at = run_row["created_at"]
        else:
            cursor.execute(
                "SELECT created_at FROM runs WHERE run_id = ?",
                (run_id,),
            )
            r = cursor.fetchone()
            created_at = r["created_at"] if r else None

    if not intent or not created_at:
        return None

    # Parse lookback from intent
    window_str = intent.get("window", "48h")
    lookback_hours = 48  # default
    try:
        if isinstance(window_str, str):
            if window_str.endswith("h"):
                lookback_hours = int(window_str[:-1])
            elif window_str.endswith("d"):
                lookback_hours = int(window_str[:-1]) * 24
            elif window_str.endswith("w"):
                lookback_hours = int(window_str[:-1]) * 168
    except (ValueError, TypeError):
        pass

    from datetime import datetime, timedelta

    try:
        if created_at.endswith("Z"):
            created_at = created_at[:-1] + "+00:00"
        run_time = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return None

    expected_start = (run_time - timedelta(hours=lookback_hours)).isoformat()
    expected_end = run_time.isoformat()

    return {
        "expected_start": expected_start,
        "expected_end": expected_end,
        "lookback_hours": lookback_hours,
    }


def save_oracle_artifacts(run_id: str, artifacts: dict) -> None:
    """Store oracle artifacts in run_artifacts table."""
    with get_conn() as conn:
        cursor = conn.cursor()
        for artifact_type, data in artifacts.items():
            if data is None:
                continue
            cursor.execute(
                """
                INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, "oracle", artifact_type, json.dumps(data, default=str), now_iso()),
            )
        conn.commit()
