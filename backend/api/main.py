"""FastAPI application entry point."""
import contextvars
import logging
import os
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from backend.core.logging import setup_logging, get_logger
from backend.db.connect import init_db
from backend.api.routes import runs, approvals, portfolio, orders, ops, market, policies, agent, commands, trace, analytics, chat, evals, analytics_pnl, analytics_slippage, analytics_risk, conversations, telemetry, news, confirmations, prometheus, trade_tickets, debug
from backend.api.auth import router as auth_router

# Thread/async-safe request ID propagation via contextvars
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar('request_id', default='')


class RequestIDFilter(logging.Filter):
    """Logging filter that injects request_id from contextvars into log records."""
    def filter(self, record):
        record.request_id = _request_id_ctx.get('')
        return True


setup_logging()
# Add the RequestIDFilter to root logger so all log records get request_id
logging.getLogger().addFilter(RequestIDFilter())
logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add request_id to requests and responses.

    Uses contextvars for async/thread-safe request ID propagation instead
    of the global logging.setLogRecordFactory() which is NOT thread-safe.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Set request_id in contextvar (async-safe, no global mutation)
        token = _request_id_ctx.set(request_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        except HTTPException as exc:
            # Catch HTTPException before BaseHTTPMiddleware wraps it in ExceptionGroup
            from fastapi.responses import JSONResponse
            detail = exc.detail
            # Pass through structured error dicts from endpoints
            if isinstance(detail, dict) and "error" in detail:
                content = {
                    "status": "ERROR",
                    "detail": detail,
                    "request_id": request_id,
                }
            else:
                content = {
                    "status": "ERROR",
                    "error": {"code": f"HTTP_{exc.status_code}", "message": str(detail), "request_id": request_id},
                    "content": str(detail),
                    "request_id": request_id,
                }
            resp = JSONResponse(
                status_code=exc.status_code,
                content=content,
                headers={"X-Request-ID": request_id},
            )
            return resp
        except Exception as exc:
            # Last-resort catch: convert ANY exception to JSON so it never
            # escapes into BaseHTTPMiddleware's ExceptionGroup wrapping.
            from fastapi.responses import JSONResponse
            try:
                logger.error(
                    "Unhandled in RequestIDMiddleware: %s | req=%s | %s %s",
                    str(exc)[:200], request_id, request.method, str(request.url.path)
                )
            except Exception:
                pass  # Never let logging crash the error handler
            return JSONResponse(
                status_code=500,
                content={
                    "status": "ERROR",
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An internal error occurred",
                        "request_id": request_id,
                    },
                    "content": f"Something went wrong. Request ID: {request_id}",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        finally:
            _request_id_ctx.reset(token)

_enable_otel = os.getenv("ENABLE_OTEL", "0").lower() in ("1", "true", "yes")
# Initialize OpenTelemetry only when explicitly enabled.
if _enable_otel:
    try:
        from backend.core.otel import setup_otel
        setup_otel()
        logger.info("OpenTelemetry initialized")
    except Exception as e:
        logger.warning(f"OpenTelemetry init failed: {e}")
else:
    logger.info("OpenTelemetry disabled (set ENABLE_OTEL=1 to enable)")

# Flag to enable FastAPI instrumentation after app creation
_fastapi_instrumentation_enabled = False

# Initialize database - FATAL on failure (server cannot serve without schema)
init_db()
logger.info("Database initialized")

# Store schema status for runtime health checks
from backend.db.connect import get_schema_status
_schema_status = get_schema_status()
logger.info(
    "Schema status: db=%s | applied=%d | pending=%d | ok=%s",
    _schema_status["db_path"],
    len(_schema_status["applied_migrations"]),
    len(_schema_status["pending_migrations"]),
    _schema_status["schema_ok"],
)

# Check news sources configuration
try:
    from backend.db.connect import get_conn
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM news_sources")
        news_sources_count = cursor.fetchone()["count"]
        
        cursor.execute("SELECT COUNT(*) as count FROM news_items WHERE published_at >= datetime('now', '-7 days')")
        recent_news_count = cursor.fetchone()["count"]
        
        logger.info(
            "News pipeline status: sources=%d | recent_items_7d=%d",
            news_sources_count,
            recent_news_count
        )
        
        if news_sources_count == 0:
            logger.warning(
                "No news sources configured. News insights will be limited. "
                "Run news ingestion setup or trigger: POST /api/v1/news/ingest"
            )
except Exception as e:
    logger.debug(f"News sources check failed (tables may not exist): {e}")



def is_schema_healthy() -> bool:
    """Return True if database schema passed validation at startup."""
    return _schema_status.get("schema_ok", False)

# Validate market data mode and log provider
try:
    from backend.core.config import get_settings
    settings = get_settings()
    settings.validate_market_data_mode()
    logger.info(f"market_data_provider = {settings.market_data_mode}")
except ValueError as e:
    logger.error(str(e))
    raise

# Startup warning for LIVE trading with real keys
try:
    from backend.core.config import get_settings
    from backend.core.env_utils import detect_real_keys

    settings = get_settings()
    if settings.enable_live_trading:
        key_detection = detect_real_keys()
        if key_detection["any_real_keys"]:
            logger.warning(
                "⚠️  LIVE TRADING ENABLED WITH REAL KEYS DETECTED ⚠️\n"
                "    Ensure keys were rotated if previously shared.\n"
                "    Secrets are never logged by this application."
            )
except Exception as e:
    logger.warning(f"Key detection check failed: {e}")

app = FastAPI(
    title="ExecutiveDesk AI API",
    version="1.0.0"
)


def _find_http_exception(exc):
    """Recursively search ExceptionGroup tree for the first HTTPException.

    With 4+ BaseHTTPMiddleware layers, exceptions can be nested multiple levels
    deep in ExceptionGroups. A flat one-level check misses deeply nested
    HTTPExceptions, causing them to fall through to global_exception_handler as 500.
    """
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ExceptionGroup):
        for sub in exc.exceptions:
            found = _find_http_exception(sub)
            if found:
                return found
    return None


# HTTPException handler: preserve original status codes (e.g. 404, 403, 422)
# so they are never swallowed by the generic Exception handler below
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return structured JSON for any HTTPException that leaks through."""
    from fastapi.responses import JSONResponse
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4())[:8])
    detail = exc.detail
    # Pass through structured error dicts from endpoints
    if isinstance(detail, dict) and "error" in detail:
        content = {
            "status": "ERROR",
            "detail": detail,
            "request_id": request_id,
        }
    else:
        content = {
            "status": "ERROR",
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "error_code": f"HTTP_{exc.status_code}",
                "message": str(detail),
                "request_id": request_id,
                "remediation": None,
            },
            "content": str(detail),
            "request_id": request_id,
        }
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers={"X-Request-ID": request_id, **(exc.headers or {})},
    )


# Global exception handler to ensure all errors return JSON, never HTML
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and return JSON error response."""
    import traceback
    from fastapi.responses import JSONResponse
    
    # Get or generate request_id
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4())[:8])
    
    # Log the error (NEVER use extra={"request_id": ...} - RequestIDMiddleware
    # sets request_id on LogRecords via factory; using extra causes
    # "Attempt to overwrite 'request_id'" crash that kills this handler)
    try:
        logger.error(
            "Unhandled exception: %s | req=%s | %s %s\n%s",
            str(exc)[:200],
            request_id,
            request.method,
            str(request.url.path),
            traceback.format_exc()[-500:]
        )
    except Exception:
        pass  # Never let logging crash the exception handler
    
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "error_code": "INTERNAL_ERROR",
                "message": "An internal error occurred",
                "request_id": request_id,
                "remediation": None,
            },
            "content": f"Something went wrong. Request ID: {request_id}",
            "status": "ERROR",
            "run_id": None,
            "intent": "ERROR",
            "request_id": request_id
        },
        headers={"X-Request-ID": request_id}
    )


# ExceptionGroup handler: BaseHTTPMiddleware wraps HTTPException in ExceptionGroup
# which bypasses the HTTPException handler above. Unwrap and re-dispatch.
@app.exception_handler(ExceptionGroup)
async def exception_group_handler(request: Request, exc: ExceptionGroup):
    """Unwrap ExceptionGroup from BaseHTTPMiddleware and preserve original status.

    Uses recursive search because 4+ BaseHTTPMiddleware layers can nest
    ExceptionGroups multiple levels deep (ExceptionGroup(ExceptionGroup(HTTPException))).
    """
    http_exc = _find_http_exception(exc)
    if http_exc:
        return await http_exception_handler(request, http_exc)
    return await global_exception_handler(request, exc)


# Request ID middleware (must be first)
app.add_middleware(RequestIDMiddleware)

# Request size limiting (after request ID, before rate limiting)
if os.getenv("ENABLE_REQUEST_SIZE_LIMIT", "0").lower() in ("1", "true", "yes"):
    try:
        from backend.api.middleware.request_size import RequestSizeLimitMiddleware
        app.add_middleware(RequestSizeLimitMiddleware)
        logger.info("Request size limiting middleware enabled")
    except Exception as e:
        logger.warning(f"Request size limiting middleware not available: {e}")
else:
    logger.info("Request size limiting middleware disabled")

# Rate limiting (after request size)
if os.getenv("ENABLE_RATE_LIMIT", "0").lower() in ("1", "true", "yes"):
    try:
        from backend.api.middleware.rate_limit import RateLimitMiddleware
        app.add_middleware(RateLimitMiddleware)
        logger.info("Rate limiting middleware enabled")
    except Exception as e:
        logger.warning(f"Rate limiting middleware not available: {e}")
else:
    logger.info("Rate limiting middleware disabled")

# Audit logging (after rate limiting)
if os.getenv("ENABLE_AUDIT_LOG", "0").lower() in ("1", "true", "yes"):
    try:
        from backend.api.middleware.audit_log import AuditLogMiddleware
        app.add_middleware(AuditLogMiddleware)
        logger.info("Audit logging middleware enabled")
    except Exception as e:
        logger.warning(f"Audit logging middleware not available: {e}")
else:
    logger.info("Audit logging middleware disabled")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://localhost:3003", "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:3002", "http://127.0.0.1:3003"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(runs.router, prefix="/api/v1/runs", tags=["runs"])
app.include_router(approvals.router, prefix="/api/v1/approvals", tags=["approvals"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio", tags=["portfolio"])
app.include_router(orders.router, prefix="/api/v1/orders", tags=["orders"])
app.include_router(ops.router, prefix="/api/v1/ops", tags=["ops"])
app.include_router(market.router, prefix="/api/v1/market", tags=["market"])
app.include_router(policies.router, prefix="/api/v1/policies", tags=["policies"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["agent"])
app.include_router(commands.router, prefix="/api/v1/commands", tags=["commands"])
app.include_router(trace.router, prefix="/api/v1/runs", tags=["trace"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(evals.router, prefix="/api/v1/evals", tags=["evals"])
app.include_router(analytics_pnl.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(analytics_slippage.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(analytics_risk.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"])
app.include_router(telemetry.router, prefix="/api/v1/telemetry", tags=["telemetry"])
app.include_router(news.router, prefix="/api/v1/news", tags=["news"])
app.include_router(confirmations.router, prefix="/api/v1/confirmations", tags=["confirmations"])
app.include_router(trade_tickets.router)  # trade_tickets has its own prefix
app.include_router(prometheus.router, prefix="/api/v1", tags=["observability"])
app.include_router(debug.router, prefix="/api/v1/debug", tags=["debug"])

# Enable FastAPI OpenTelemetry instrumentation only when explicitly enabled.
if _enable_otel:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI OpenTelemetry instrumentation enabled")
    except Exception as e:
        logger.warning(f"FastAPI instrumentation not available: {e}")


@app.get("/")
async def root():
    return {"message": "ExecutiveDesk AI API"}


@app.get("/health")
async def health():
    """Root health endpoint -- delegates to the deep /ops/health check.

    Returns structured health status including DB readiness, schema health,
    migration status, and provider configuration so that callers (including
    the frontend bootstrap) can gate behaviour before user interaction.
    """
    try:
        from backend.db.connect import get_schema_status, get_conn
        import platform

        db_ok = False
        schema_ok = False
        pending_migrations: list[str] = []

        # DB connectivity
        try:
            with get_conn() as conn:
                conn.execute("SELECT 1")
                db_ok = True
        except Exception:
            pass

        # Schema / migrations
        try:
            schema_status = get_schema_status()
            schema_ok = schema_status.get("schema_ok", False)
            pending_migrations = schema_status.get("pending_migrations", [])
        except Exception:
            pass

        # Live trading flag
        from backend.core.config import get_settings
        settings = get_settings()
        live_trading_enabled = settings.is_live_execution_allowed()

        ok = db_ok and schema_ok

        is_windows = platform.system() == "Windows"
        migrate_cmd = (
            "python -m uvicorn backend.api.main:app --port 8000"
            if is_windows
            else "uvicorn backend.api.main:app --port 8000"
        )

        return {
            "status": "ok" if ok else "degraded",
            "ok": ok,
            "db_ready": db_ok,
            "schema_ok": schema_ok,
            "migrations_needed": len(pending_migrations) > 0,
            "pending_migrations": pending_migrations,
            "live_trading_enabled": live_trading_enabled,
            "migrate_cmd": migrate_cmd,
        }
    except Exception as e:
        return {
            "status": "error",
            "ok": False,
            "db_ready": False,
            "schema_ok": False,
            "migrations_needed": True,
            "error": str(e)[:200],
        }


@app.on_event("startup")
async def startup_product_catalog():
    """Populate the persistent product catalog from Coinbase public API."""
    import threading

    def _bg_catalog():
        try:
            from backend.services.product_catalog import get_product_catalog
            catalog = get_product_catalog()
            if catalog.needs_refresh():
                count = catalog.refresh_catalog()
                logger.info("Product catalog populated on startup: %d products", count)
            else:
                logger.info("Product catalog already fresh, skipping refresh")
        except Exception as e:
            logger.warning("Product catalog startup refresh failed (non-fatal): %s", str(e)[:200])

    thread = threading.Thread(target=_bg_catalog, daemon=True)
    thread.start()


@app.on_event("startup")
async def startup_news_ingest():
    """Auto-ingest news on startup so headlines are available for the first trade."""
    import asyncio
    import threading

    def _bg_ingest():
        try:
            from backend.db.connect import get_conn
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as cnt FROM news_sources WHERE is_enabled = 1")
                row = cursor.fetchone()
                enabled = row["cnt"] if row else 0
            if enabled == 0:
                logger.info("Startup news ingest: no enabled sources, skipping")
                return
            from backend.services.news_ingestion import NewsIngestionService
            svc = NewsIngestionService()
            # ingest_all is async, so run it in a fresh event loop
            result = asyncio.run(svc.ingest_all())
            logger.info("Startup news ingest complete: %s", str(result)[:200])
        except Exception as e:
            logger.warning("Startup news ingest failed (non-fatal): %s", str(e)[:200])

    thread = threading.Thread(target=_bg_ingest, daemon=True)
    thread.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown: close OpenTelemetry tracer provider."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        
        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            provider.shutdown()
            logger.info("OpenTelemetry tracer provider shut down cleanly")
    except Exception as e:
        logger.warning(f"Failed to shutdown OpenTelemetry: {e}")
