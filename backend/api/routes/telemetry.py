"""Telemetry API routes."""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from backend.api.deps import require_viewer
from backend.db.connect import get_conn

router = APIRouter()


class RunTelemetryResponse(BaseModel):
    run_id: str
    tenant_id: str
    started_at: Optional[str]
    ended_at: Optional[str]
    duration_ms: Optional[int]
    tool_calls_count: int
    sse_events_count: int
    error_count: int
    last_error: Optional[str]
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    trace_id: Optional[str]
    created_at: str
    updated_at: str


class TelemetrySummaryResponse(BaseModel):
    run_id: str
    tenant_id: str
    duration_ms: Optional[int]
    tool_calls_count: int
    sse_events_count: int
    error_count: int
    started_at: Optional[str]
    ended_at: Optional[str]


@router.get("/runs", response_model=List[TelemetrySummaryResponse])
async def list_run_telemetry(user: dict = Depends(require_viewer)):
    """List telemetry for all runs."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                run_id,
                tenant_id,
                started_at,
                ended_at,
                duration_ms,
                tool_calls_count,
                sse_events_count,
                error_count
            FROM run_telemetry
            WHERE tenant_id = ?
            ORDER BY started_at DESC
            LIMIT 100
            """,
            (tenant_id,)
        )
        rows = cursor.fetchall()
    
    return [
        TelemetrySummaryResponse(
            run_id=row["run_id"],
            tenant_id=row["tenant_id"],
            duration_ms=row["duration_ms"],
            tool_calls_count=row["tool_calls_count"],
            sse_events_count=row["sse_events_count"],
            error_count=row["error_count"],
            started_at=row["started_at"],
            ended_at=row["ended_at"]
        )
        for row in rows
    ]


@router.get("/runs/{run_id}", response_model=RunTelemetryResponse)
async def get_run_telemetry(
    run_id: str,
    user: dict = Depends(require_viewer)
):
    """Get detailed telemetry for a specific run."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                run_id,
                tenant_id,
                started_at,
                ended_at,
                duration_ms,
                tool_calls_count,
                sse_events_count,
                error_count,
                last_error,
                tokens_in,
                tokens_out,
                trace_id,
                created_at,
                updated_at
            FROM run_telemetry
            WHERE run_id = ? AND tenant_id = ?
            """,
            (run_id, tenant_id)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Run telemetry not found")
    
    return RunTelemetryResponse(
        run_id=row["run_id"],
        tenant_id=row["tenant_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_ms=row["duration_ms"],
        tool_calls_count=row["tool_calls_count"],
        sse_events_count=row["sse_events_count"],
        error_count=row["error_count"],
        last_error=row["last_error"],
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        trace_id=row["trace_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )
