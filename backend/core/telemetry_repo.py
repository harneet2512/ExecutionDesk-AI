"""Telemetry persistence repository."""
from typing import Optional
from backend.db.connect import get_conn
from backend.core.time import now_iso
from backend.core.logging import get_logger

logger = get_logger(__name__)


def create_or_update_run_telemetry(
    run_id: str,
    tenant_id: str,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    duration_ms: Optional[int] = None,
    tool_calls_count: int = 0,
    sse_events_count: int = 0,
    error_count: int = 0,
    last_error: Optional[str] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    trace_id: Optional[str] = None
):
    """Create or update run telemetry record."""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            # Check if telemetry exists
            cursor.execute("SELECT run_id FROM run_telemetry WHERE run_id = ?", (run_id,))
            exists = cursor.fetchone()
            
            now = now_iso()
            
            if exists:
                # Update existing
                cursor.execute(
                    """
                    UPDATE run_telemetry
                    SET ended_at = COALESCE(?, ended_at),
                        duration_ms = COALESCE(?, duration_ms),
                        tool_calls_count = ?,
                        sse_events_count = ?,
                        error_count = ?,
                        last_error = COALESCE(?, last_error),
                        tokens_in = COALESCE(?, tokens_in),
                        tokens_out = COALESCE(?, tokens_out),
                        trace_id = COALESCE(?, trace_id),
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (ended_at, duration_ms, tool_calls_count, sse_events_count, error_count, 
                     last_error, tokens_in, tokens_out, trace_id, now, run_id)
                )
            else:
                # Create new
                cursor.execute(
                    """
                    INSERT INTO run_telemetry (
                        run_id, tenant_id, started_at, ended_at, duration_ms,
                        tool_calls_count, sse_events_count, error_count, last_error,
                        tokens_in, tokens_out, trace_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, tenant_id, started_at or now, ended_at, duration_ms,
                     tool_calls_count, sse_events_count, error_count, last_error,
                     tokens_in, tokens_out, trace_id, now, now)
                )
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to persist telemetry for run {run_id}: {e}")


def update_run_telemetry_counts(
    run_id: str,
    tool_calls_delta: int = 0,
    sse_events_delta: int = 0,
    error_delta: int = 0
):
    """Increment telemetry counters."""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            now = now_iso()
            cursor.execute(
                """
                UPDATE run_telemetry
                SET tool_calls_count = tool_calls_count + ?,
                    sse_events_count = sse_events_count + ?,
                    error_count = error_count + ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (tool_calls_delta, sse_events_delta, error_delta, now, run_id)
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to update telemetry counts for run {run_id}: {e}")
