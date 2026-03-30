"""Prometheus metrics endpoint for production observability.

This module avoids heavyweight metric registry initialization at import time.
All Prometheus objects are initialized lazily on first use so backend startup
cannot be blocked by metrics setup.
"""
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, Response

from backend.api.deps import require_viewer
from backend.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

_metrics_lock = Lock()
_metrics_ready = False
_metrics_failed = False

# Prometheus objects are set during lazy initialization.
RUN_SUCCESS_TOTAL: Any = None
RUN_FAILURE_TOTAL: Any = None
RUN_DURATION_SECONDS: Any = None
NODE_LATENCY_SECONDS: Any = None
NODE_FAILURE_TOTAL: Any = None
EXTERNAL_API_LATENCY_SECONDS: Any = None
EXTERNAL_API_ERRORS_TOTAL: Any = None
COINBASE_429_TOTAL: Any = None
COINBASE_TIMEOUT_TOTAL: Any = None
RANKED_ASSETS_GAUGE: Any = None
DROPPED_ASSETS_TOTAL: Any = None
CONFIRMATION_CONFIRM_TOTAL: Any = None
CONFIRMATION_EXPIRED_TOTAL: Any = None
CONFIRMATION_CANCELLED_TOTAL: Any = None
REPLAY_DETERMINISM_FAILURES_TOTAL: Any = None
SERVICE_INFO: Any = None
CONTENT_TYPE_LATEST: str = "text/plain; version=0.0.4; charset=utf-8"
REGISTRY: Any = None
generate_latest: Any = None


def _ensure_metrics_ready() -> bool:
    """Initialize Prometheus collectors once; never crash callers."""
    global _metrics_ready, _metrics_failed
    global RUN_SUCCESS_TOTAL, RUN_FAILURE_TOTAL, RUN_DURATION_SECONDS
    global NODE_LATENCY_SECONDS, NODE_FAILURE_TOTAL
    global EXTERNAL_API_LATENCY_SECONDS, EXTERNAL_API_ERRORS_TOTAL
    global COINBASE_429_TOTAL, COINBASE_TIMEOUT_TOTAL
    global RANKED_ASSETS_GAUGE, DROPPED_ASSETS_TOTAL
    global CONFIRMATION_CONFIRM_TOTAL, CONFIRMATION_EXPIRED_TOTAL, CONFIRMATION_CANCELLED_TOTAL
    global REPLAY_DETERMINISM_FAILURES_TOTAL, SERVICE_INFO
    global CONTENT_TYPE_LATEST, REGISTRY, generate_latest

    if _metrics_ready:
        return True
    if _metrics_failed:
        return False

    with _metrics_lock:
        if _metrics_ready:
            return True
        if _metrics_failed:
            return False
        try:
            from prometheus_client import (
                CONTENT_TYPE_LATEST as _CONTENT_TYPE_LATEST,
                REGISTRY as _REGISTRY,
                Counter,
                Gauge,
                Histogram,
                Info,
                generate_latest as _generate_latest,
            )

            RUN_SUCCESS_TOTAL = Counter("run_success_total", "Total successful runs", ["mode"])
            RUN_FAILURE_TOTAL = Counter("run_failure_total", "Total failed runs", ["mode", "reason"])
            RUN_DURATION_SECONDS = Histogram(
                "run_duration_seconds",
                "Run execution duration in seconds",
                ["mode"],
                buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300],
            )
            NODE_LATENCY_SECONDS = Histogram(
                "node_latency_seconds",
                "Node execution latency in seconds",
                ["node"],
                buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
            )
            NODE_FAILURE_TOTAL = Counter("node_failure_total", "Total node failures", ["node", "error_class"])
            EXTERNAL_API_LATENCY_SECONDS = Histogram(
                "external_api_latency_seconds",
                "External API call latency in seconds",
                ["provider", "endpoint"],
                buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10],
            )
            EXTERNAL_API_ERRORS_TOTAL = Counter(
                "external_api_errors_total",
                "Total external API errors",
                ["provider", "endpoint", "status_code"],
            )
            COINBASE_429_TOTAL = Counter("coinbase_429_total", "Total Coinbase 429 (rate limit) responses")
            COINBASE_TIMEOUT_TOTAL = Counter("coinbase_timeout_total", "Total Coinbase timeout errors")
            RANKED_ASSETS_GAUGE = Gauge("ranked_assets_count", "Number of assets successfully ranked in last research")
            DROPPED_ASSETS_TOTAL = Counter(
                "dropped_assets_total",
                "Total assets dropped from ranking",
                ["reason"],
            )
            CONFIRMATION_CONFIRM_TOTAL = Counter("confirmation_confirm_total", "Total confirmations confirmed")
            CONFIRMATION_EXPIRED_TOTAL = Counter("confirmation_expired_total", "Total confirmations expired")
            CONFIRMATION_CANCELLED_TOTAL = Counter("confirmation_cancelled_total", "Total confirmations cancelled")
            REPLAY_DETERMINISM_FAILURES_TOTAL = Counter(
                "replay_determinism_failures_total", "Total replay determinism failures"
            )
            SERVICE_INFO = Info("executivedesk_ai", "Service information")

            CONTENT_TYPE_LATEST = _CONTENT_TYPE_LATEST
            REGISTRY = _REGISTRY
            generate_latest = _generate_latest
            _metrics_ready = True
            return True
        except Exception as e:
            _metrics_failed = True
            logger.warning("Prometheus disabled (failed to initialize metrics): %s", str(e)[:200])
            return False


def initialize_service_info():
    """Initialize service info metric."""
    if not _ensure_metrics_ready():
        return
    try:
        from backend.core.config import get_settings
        settings = get_settings()
        SERVICE_INFO.info({
            "service_name": settings.service_name,
            "service_version": settings.service_version,
            "execution_mode_default": settings.execution_mode_default,
            "market_data_mode": settings.market_data_mode
        })
    except Exception as e:
        logger.warning(f"Failed to initialize service info metric: {e}")


# === METRIC RECORDING FUNCTIONS ===

def record_run_success(mode: str, duration_seconds: float):
    """Record a successful run."""
    if not _ensure_metrics_ready():
        return
    RUN_SUCCESS_TOTAL.labels(mode=mode).inc()
    RUN_DURATION_SECONDS.labels(mode=mode).observe(duration_seconds)


def record_run_failure(mode: str, reason: str, duration_seconds: float = None):
    """Record a failed run."""
    if not _ensure_metrics_ready():
        return
    RUN_FAILURE_TOTAL.labels(mode=mode, reason=reason).inc()
    if duration_seconds is not None:
        RUN_DURATION_SECONDS.labels(mode=mode).observe(duration_seconds)


def record_node_latency(node: str, duration_seconds: float):
    """Record node execution latency."""
    if not _ensure_metrics_ready():
        return
    NODE_LATENCY_SECONDS.labels(node=node).observe(duration_seconds)


def record_node_failure(node: str, error_class: str):
    """Record a node failure."""
    if not _ensure_metrics_ready():
        return
    NODE_FAILURE_TOTAL.labels(node=node, error_class=error_class).inc()


def record_external_api_call(provider: str, endpoint: str, duration_seconds: float):
    """Record external API call latency."""
    if not _ensure_metrics_ready():
        return
    EXTERNAL_API_LATENCY_SECONDS.labels(provider=provider, endpoint=endpoint).observe(duration_seconds)


def record_external_api_error(provider: str, endpoint: str, status_code: str):
    """Record external API error."""
    if not _ensure_metrics_ready():
        return
    EXTERNAL_API_ERRORS_TOTAL.labels(provider=provider, endpoint=endpoint, status_code=status_code).inc()


def record_coinbase_429():
    """Record a Coinbase 429 response."""
    if not _ensure_metrics_ready():
        return
    COINBASE_429_TOTAL.inc()


def record_coinbase_timeout():
    """Record a Coinbase timeout."""
    if not _ensure_metrics_ready():
        return
    COINBASE_TIMEOUT_TOTAL.inc()


def record_ranked_assets(count: int):
    """Record number of ranked assets."""
    if not _ensure_metrics_ready():
        return
    RANKED_ASSETS_GAUGE.set(count)


def record_dropped_asset(reason: str):
    """Record a dropped asset."""
    if not _ensure_metrics_ready():
        return
    DROPPED_ASSETS_TOTAL.labels(reason=reason).inc()


def record_confirmation_confirmed():
    """Record a confirmation confirmed."""
    if not _ensure_metrics_ready():
        return
    CONFIRMATION_CONFIRM_TOTAL.inc()


def record_confirmation_expired():
    """Record a confirmation expired."""
    if not _ensure_metrics_ready():
        return
    CONFIRMATION_EXPIRED_TOTAL.inc()


def record_confirmation_cancelled():
    """Record a confirmation cancelled."""
    if not _ensure_metrics_ready():
        return
    CONFIRMATION_CANCELLED_TOTAL.inc()


def record_replay_determinism_failure():
    """Record a replay determinism failure."""
    if not _ensure_metrics_ready():
        return
    REPLAY_DETERMINISM_FAILURES_TOTAL.inc()


# === ENDPOINT ===

@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint.
    
    Returns metrics in Prometheus text format for scraping.
    """
    try:
        if not _ensure_metrics_ready():
            return Response(
                content="# Prometheus metrics disabled: initialization failed\n",
                media_type="text/plain",
                status_code=503
            )
        # Initialize service info if not done
        initialize_service_info()
        
        # Generate metrics
        output = generate_latest(REGISTRY)
        return Response(content=output, media_type=CONTENT_TYPE_LATEST)
    except Exception as e:
        logger.error(f"Failed to generate metrics: {e}")
        return Response(
            content=f"# Error generating metrics: {e}\n",
            media_type="text/plain",
            status_code=500
        )


@router.get("/metrics/json")
async def metrics_json(user: dict = Depends(require_viewer)):
    """JSON metrics endpoint for debugging.
    
    Returns a subset of metrics as JSON for easier debugging.
    """
    from backend.db.connect import get_conn
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Get run counts
            cursor.execute("SELECT status, COUNT(*) as cnt FROM runs GROUP BY status")
            run_counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            # Get recent run durations
            cursor.execute("""
                SELECT execution_mode, 
                       AVG(julianday(completed_at) - julianday(started_at)) * 86400 as avg_duration_s
                FROM runs 
                WHERE status = 'COMPLETED' AND completed_at IS NOT NULL
                GROUP BY execution_mode
            """)
            avg_durations = {row["execution_mode"]: row["avg_duration_s"] for row in cursor.fetchall()}
            
            # Get node failure counts
            cursor.execute("""
                SELECT name, COUNT(*) as cnt 
                FROM dag_nodes 
                WHERE status = 'FAILED' 
                GROUP BY name
            """)
            node_failures = {row["name"]: row["cnt"] for row in cursor.fetchall()}
            
            # Get confirmation stats
            cursor.execute("""
                SELECT status, COUNT(*) as cnt 
                FROM trade_confirmations 
                GROUP BY status
            """)
            confirmation_stats = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            return {
                "run_counts": run_counts,
                "avg_run_duration_seconds": avg_durations,
                "node_failures": node_failures,
                "confirmation_stats": confirmation_stats
            }
    except Exception as e:
        logger.error(f"Failed to generate JSON metrics: {e}")
        return {"error": str(e)}
