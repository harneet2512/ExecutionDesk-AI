"""Operations API routes."""
from fastapi import APIRouter, Depends
from datetime import datetime
import json
import sqlite3
from pathlib import Path
from backend.api.deps import get_current_user
from backend.db.connect import get_conn
from backend.core.config import get_settings
from backend.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/capabilities")
async def get_capabilities():
    """Lightweight capabilities endpoint for frontend bootstrap.

    Returns feature flags + DB readiness without auth.
    """
    settings = get_settings()

    # DB readiness
    db_ready = False
    remediation = None
    try:
        from backend.db.connect import get_schema_status
        schema_status = get_schema_status()
        db_ready = schema_status["schema_ok"]
        if not db_ready:
            pending = schema_status.get("pending_migrations", [])
            count = len(pending)
            import platform
            is_windows = platform.system() == "Windows"
            cmd = (
                "python -m uvicorn backend.api.main:app --port 8000"
                if is_windows
                else "uvicorn backend.api.main:app --port 8000"
            )
            remediation = (
                f"Database has {count} pending migration(s). "
                f"Restart backend to apply: {cmd}"
            )
    except Exception as e:
        logger.warning("Capabilities DB check failed: %s", str(e)[:100])
        remediation = "Could not verify database status."

    # News provider status
    news_provider_status = "unknown"
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM news_sources WHERE is_enabled = 1")
            row = cursor.fetchone()
            enabled_count = row["cnt"] if row else 0
            news_provider_status = f"{enabled_count} source(s) enabled" if enabled_count > 0 else "no sources enabled"
    except Exception:
        news_provider_status = "news tables not available"

    # Market data provider
    market_data_provider = "unknown"
    try:
        market_data_provider = settings.market_data_mode or "coinbase"
    except Exception:
        pass

    return {
        "live_trading_enabled": settings.is_live_execution_allowed(),
        "paper_trading_enabled": True,
        "insights_enabled": True,
        "news_enabled": True,
        "db_ready": db_ready,
        "migrations_needed": not db_ready,
        "remediation": remediation,
        "news_provider_status": news_provider_status,
        "market_data_provider": market_data_provider,
        "version": "0.1.0",
    }


@router.get("/metrics")
async def get_metrics(user: dict = Depends(get_current_user)):
    """Get operations metrics for charts."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Run durations
        cursor.execute(
            """
            SELECT created_at, completed_at
            FROM runs
            WHERE tenant_id = ? AND status = 'COMPLETED' AND completed_at IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT 100
            """,
            (tenant_id,)
        )
        run_rows = cursor.fetchall()
        
        run_durations = []
        for row in run_rows:
            try:
                created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                completed = datetime.fromisoformat(row["completed_at"].replace("Z", "+00:00"))
                duration_ms = int((completed - created).total_seconds() * 1000)
                run_durations.append({
                    "ts": row["completed_at"],
                    "duration_ms": duration_ms
                })
            except Exception:
                continue
        
        # Order fill latency
        cursor.execute(
            """
            SELECT oe.ts, oe.payload_json
            FROM order_events oe
            JOIN orders o ON oe.order_id = o.order_id
            WHERE o.tenant_id = ? AND oe.event_type = 'FILLED'
            ORDER BY oe.ts DESC
            LIMIT 100
            """,
            (tenant_id,)
        )
        order_rows = cursor.fetchall()
        
        fill_latency = []
        for row in order_rows:
            try:
                payload = json.loads(row["payload_json"])
                latency_ms = payload.get("latency_ms", 0)
                fill_latency.append({
                    "ts": row["ts"],
                    "latency_ms": latency_ms
                })
            except Exception:
                continue
        
        # Eval trends
        cursor.execute(
            """
            SELECT ts, eval_name, score
            FROM eval_results
            WHERE tenant_id = ?
            ORDER BY ts DESC
            LIMIT 100
            """,
            (tenant_id,)
        )
        eval_rows = cursor.fetchall()
        
        eval_trends = []
        for row in eval_rows:
            eval_trends.append({
                "ts": row["ts"],
                "eval_name": row["eval_name"],
                "score": row["score"]
            })
        
        # Policy blocks
        cursor.execute(
            """
            SELECT pe.ts
            FROM policy_events pe
            JOIN runs r ON pe.run_id = r.run_id
            WHERE r.tenant_id = ? AND pe.decision = 'BLOCKED'
            ORDER BY pe.ts DESC
            LIMIT 100
            """,
            (tenant_id,)
        )
        block_rows = cursor.fetchall()
        
        # Group by date
        blocked_counts = {}
        for row in block_rows:
            date = row["ts"][:10]  # Date only
            blocked_counts[date] = blocked_counts.get(date, 0) + 1
        
        policy_blocks = [
            {"ts": ts, "count": count}
            for ts, count in sorted(blocked_counts.items())
        ]
        
        # Additional metrics for enterprise observability
        cursor.execute(
            "SELECT COUNT(*) as total FROM runs WHERE tenant_id = ?",
            (tenant_id,)
        )
        runs_total = cursor.fetchone()["total"]
        
        cursor.execute(
            "SELECT COUNT(*) as failed FROM runs WHERE tenant_id = ? AND status = 'FAILED'",
            (tenant_id,)
        )
        runs_failed = cursor.fetchone()["failed"]
        
        cursor.execute(
            "SELECT COUNT(*) as pending FROM approvals WHERE tenant_id = ? AND status = 'PENDING'",
            (tenant_id,)
        )
        approvals_pending = cursor.fetchone()["pending"]
        
        # Recent errors (last 10 failed nodes)
        cursor.execute(
            """
            SELECT dn.run_id, dn.status, dn.error_json
            FROM dag_nodes dn
            JOIN runs r ON dn.run_id = r.run_id
            WHERE dn.error_json IS NOT NULL AND r.tenant_id = ?
            ORDER BY dn.completed_at DESC
            LIMIT 10
            """,
            (tenant_id,)
        )
        recent_errors = []
        for row in cursor.fetchall():
            try:
                error_data = json.loads(row["error_json"])
                recent_errors.append({
                    "run_id": row["run_id"],
                    "error": error_data.get("error", "Unknown error")
                })
            except:
                pass
    
    return {
        "run_durations": run_durations,
        "order_fill_latency_ms": fill_latency,
        "eval_trends": eval_trends,
        "policy_blocks": policy_blocks,
        "counts": {
            "runs_total": runs_total,
            "runs_failed": runs_failed,
            "approvals_pending": approvals_pending
        },
        "recent_errors": recent_errors
    }


@router.get("/health")
async def health_check():
    """
    Enhanced health check with DB connectivity, migration status, and provider config sanity.
    Does not expose secrets.  Top-level ``ok`` boolean gates frontend UI.
    """
    import platform

    health = {
        "ok": False,
        "db_ok": False,
        "schema_ok": False,
        "status": "ok",
        "database": "unknown",
        "migrations": {"applied": [], "total": 0, "pending": []},
        "migrations_applied": 0,
        "migrations_pending": 0,
        "pending_list": [],
        "message": "Checking...",
        "providers": {
            "coinbase": {"configured": False, "live_trading_enabled": False},
            "market_data": "unknown"
        },
        "config": {}
    }

    # Check DB connectivity
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
            health["database"] = "connected"
            health["db_ok"] = True
    except Exception as e:
        health["status"] = "degraded"
        health["database"] = "disconnected"
        health["database_error"] = str(e)[:100]
        health["message"] = f"Database connection failed: {str(e)[:100]}"
        return health

    # Lightweight schema and migrations status (avoid heavy full-schema scans that
    # can stall bootstrap when the DB is under write load).
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name IN ('runs', 'conversations', 'messages')
                """
            )
            required_tables = {row["name"] for row in cursor.fetchall()}
            health["schema_ok"] = len(required_tables) == 3

            try:
                cursor.execute("SELECT filename FROM schema_migrations")
                applied = [row["filename"] for row in cursor.fetchall()]
            except Exception:
                applied = []

        migrations_dir = Path(__file__).resolve().parents[2] / "db" / "migrations"
        all_migrations = sorted([p.name for p in migrations_dir.glob("*.sql")]) if migrations_dir.exists() else []
        pending = [m for m in all_migrations if m not in set(applied)]

        health["migrations"] = {
            "applied": applied,
            "total": len(all_migrations) if all_migrations else (len(applied) + len(pending)),
            "pending": pending,
        }
        health["migrations_applied"] = len(applied)
        health["migrations_pending"] = len(pending)
        health["pending_list"] = pending

        # Add migration details for actionable instructions.
        health["db_path"] = str((Path(__file__).resolve().parents[3] / "enterprise.db").resolve())
        health["current_version"] = len(applied)
        health["required_version"] = len(applied) + len(pending)

        # Generate platform-specific migration command
        # Migrations are automatically applied on backend restart via init_db()
        is_windows = platform.system() == "Windows"
        if is_windows:
            health["migrate_cmd"] = "python -m uvicorn backend.api.main:app --port 8000"
        else:
            health["migrate_cmd"] = "uvicorn backend.api.main:app --port 8000"
            
    except Exception as e:
        health["migrations_error"] = str(e)[:100]

    # Derive top-level ok
    health["ok"] = health["db_ok"] and health["schema_ok"]
    if health["ok"]:
        health["message"] = "All systems operational"
    elif not health["schema_ok"]:
        count = health.get("migrations_pending", 0)
        plural = "migration" if count == 1 else "migrations"
        health["message"] = f"Database schema is outdated. {count} pending {plural}. Restart the backend to apply."
    else:
        health["message"] = "System degraded"

    # Check provider configuration (sanity checks, no secrets)
    try:
        settings = get_settings()

        key_source = "missing"
        if settings.coinbase_api_private_key_path:
            key_source = "path"
        elif settings.coinbase_api_private_key:
            key_source = "env"

        health["providers"]["coinbase"] = {
            "configured": bool(settings.coinbase_api_key_name and (settings.coinbase_api_private_key or settings.coinbase_api_private_key_path)),
            "live_trading_enabled": settings.enable_live_trading,
            "kill_switch_enabled": settings.kill_switch_enabled
        }
        health["providers"]["market_data"] = settings.market_data_mode

        health["config"] = {
            "enable_live_trading": settings.enable_live_trading,
            "execution_mode_default": settings.execution_mode_default,
            "market_data_mode": settings.market_data_mode,
            "coinbase_private_key_source": key_source,
            "live_max_notional_usd": settings.live_max_notional_usd,
            "trading_disable_live": settings.trading_disable_live,
            "live_execution_allowed": settings.is_live_execution_allowed()
        }
    except Exception as e:
        health["providers_error"] = str(e)[:100]

    return health


@router.get("/coinbase/status")
async def coinbase_status(user: dict = Depends(get_current_user)):
    """
    Check if Coinbase credentials are valid and live trading is enabled.
    Attempts a lightweight API call (Get Time) to verify auth.
    """
    settings = get_settings()
    
    # 1. Config check
    status = {
        "enabled": settings.enable_live_trading,
        "configured": bool(settings.coinbase_api_key_name and (settings.coinbase_api_private_key or settings.coinbase_api_private_key_path)),
        "execution_mode_default": settings.execution_mode_default,
        "demo_safe_mode": settings.demo_safe_mode,
        "live_max_notional_usd": settings.live_max_notional_usd,
        "force_paper_mode": settings.force_paper_mode,
        "auth_ok": False,
        "permissions": [],
        "sandbox": False,  # Coinbase Advanced Trade API has no sandbox mode
        "error": None
    }
    
    if not status["configured"]:
        return status
        
    # 2. Auth check (if configured)
    try:
        from backend.providers.coinbase_provider import CoinbaseProvider
        import httpx
        
        # Initialize provider (loads keys)
        provider = CoinbaseProvider()
        
        # Make a lightweight call - Get Accounts with limit 1
        path = "/api/v3/brokerage/accounts"
        headers = provider._get_headers("GET", path)
        
        with httpx.Client(timeout=5.0) as client:
             response = client.get(f"https://api.coinbase.com{path}?limit=1", headers=headers)
             response.raise_for_status()
        
        status["auth_ok"] = True
        status["permissions"] = ["read"] # Inferred from successful call
        
        # Check if we can supposedly trade (without actually trading)
        if settings.enable_live_trading and not settings.demo_safe_mode:
             status["permissions"].append("trade")

    except Exception as e:
        status["auth_ok"] = False
        status["error"] = str(e)
        
    return status
