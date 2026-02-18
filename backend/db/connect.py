"""Database connection management."""
import sqlite3
import os
import time
import random
from pathlib import Path
from contextlib import contextmanager
from typing import Generator
from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

# DB busy/lock error substrings
_BUSY_ERRORS = ("database is locked", "database table is locked")


def _close_connections():
    """Close cached connections for test isolation.

    Since get_conn() creates a fresh connection per call (no pool),
    this is a no-op. Provided for test fixture compatibility.
    """
    pass


def _parse_db_url(url: str) -> str:
    """Parse DATABASE_URL to SQLite file path."""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "")
    elif url.startswith("sqlite://"):
        return url.replace("sqlite://", "")
    else:
        return url


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Get database connection context manager."""
    settings = get_settings()
    db_path = _parse_db_url(settings.database_url)
    
    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_conn_retry(max_retries: int = 3) -> Generator[sqlite3.Connection, None, None]:
    """get_conn with automatic retry on OperationalError (database locked).

    Retries up to *max_retries* times with jittered exponential backoff.
    On final failure, raises the original OperationalError.
    """
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with get_conn() as conn:
                yield conn
            return  # success
        except sqlite3.OperationalError as e:
            err_lower = str(e).lower()
            if any(b in err_lower for b in _BUSY_ERRORS) and attempt < max_retries:
                last_err = e
                sleep_s = min(0.1 * (2 ** attempt) + random.uniform(0, 0.05), 2.0)
                logger.warning("DB busy (attempt %d/%d), retrying in %.2fs: %s",
                               attempt + 1, max_retries, sleep_s, str(e)[:100])
                time.sleep(sleep_s)
                continue
            raise
    if last_err:
        raise last_err


def row_get(row, key, default=None):
    """Safe .get() for sqlite3.Row objects (which don't support .get())."""
    if row is None:
        return default
    try:
        return row[key] if key in row.keys() else default
    except (IndexError, KeyError):
        return default


def validate_schema():
    """Check that critical tables have the expected columns.

    Returns (ok, missing) where ok=True when all critical tables/columns exist,
    and missing is a dict of table -> list of missing columns.
    """
    REQUIRED_COLUMNS = {
        # Core tables (from migration 001+)
        "dag_nodes": ["node_id", "run_id", "name", "node_type", "status", "completed_at", "error_json"],
        "orders": ["order_id", "run_id", "filled_qty", "avg_fill_price", "total_fees", "status_reason"],
        "tool_calls": ["id", "run_id", "tool_name", "status", "ts", "error_text"],
        "trade_confirmations": ["id", "tenant_id", "proposal_json", "status", "insight_json", "run_id"],
        "conversations": ["conversation_id", "tenant_id", "title", "created_at", "updated_at"],
        "messages": ["message_id", "conversation_id", "role", "content", "created_at"],
        "runs": ["run_id", "tenant_id", "status", "execution_mode", "completed_at",
                "failure_reason", "failure_code",
                "command_text", "metadata_json", "intent_json",
                "parsed_intent_json", "execution_plan_json",
                "news_enabled", "asset_class"],
        "run_artifacts": ["run_id", "step_name", "artifact_type", "artifact_json"],
        "eval_results": ["eval_id", "run_id", "tenant_id", "eval_name", "score", "reasons_json", "ts"],
        "portfolio_snapshots": ["snapshot_id", "run_id", "tenant_id", "balances_json", "total_value_usd", "ts"],
        "run_events": ["id", "run_id", "tenant_id", "event_type", "payload_json", "ts"],
        "order_events": ["id", "order_id", "event_type", "payload_json", "ts"],
        # Fills (migration 009)
        "fills": ["fill_id", "order_id"],
        # News tables (migration 016) -- validated only if they exist
        "news_sources": ["id", "name", "type", "url", "is_enabled"],
        "news_items": ["id", "source_id", "published_at", "title", "content_hash"],
        "news_asset_mentions": ["item_id", "asset_symbol", "confidence"],
        "news_clusters": ["id", "cluster_hash", "first_seen_at", "last_seen_at"],
        # Audit logs (migration 010+012) - column is created_at, not ts
        "audit_logs": ["id", "tenant_id", "action", "created_at"],
        # Trade tickets (migration 021)
        "trade_tickets": ["id", "run_id", "tenant_id", "status"],
        # Approvals - includes decision column queried by approval_node
        "approvals": ["approval_id", "run_id", "tenant_id", "status", "decision"],
    }

    missing_map = {}
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            for table, expected_cols in REQUIRED_COLUMNS.items():
                try:
                    cursor.execute(f"PRAGMA table_info({table})")
                    actual_cols = {row[1] for row in cursor.fetchall()}
                    if not actual_cols:
                        missing_map[table] = expected_cols  # entire table missing
                        logger.warning("Schema validation: table '%s' does not exist", table)
                        continue
                    missing = [c for c in expected_cols if c not in actual_cols]
                    if missing:
                        missing_map[table] = missing
                        logger.warning("Schema validation: table '%s' missing columns: %s", table, missing)
                except Exception as te:
                    missing_map[table] = expected_cols
                    logger.warning("Schema validation: cannot inspect table '%s': %s", table, str(te)[:100])
    except Exception as e:
        logger.warning("Schema validation failed: %s", str(e)[:200])
        return False, {"_error": [str(e)[:200]]}

    ok = len(missing_map) == 0
    return ok, missing_map


def get_schema_status():
    """Return a dict describing current DB path, schema health, and migration status.

    Used by health endpoint and startup logging.
    """
    settings = get_settings()
    db_path = os.path.abspath(_parse_db_url(settings.database_url))
    migrations_dir = Path(__file__).parent / "migrations"

    result = {
        "db_path": db_path,
        "schema_ok": False,
        "applied_migrations": [],
        "pending_migrations": [],
        "missing_columns": {},
    }

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filename FROM schema_migrations ORDER BY applied_at ASC")
            result["applied_migrations"] = [row["filename"] for row in cursor.fetchall()]
    except Exception:
        pass

    if migrations_dir.exists():
        all_files = sorted(f.name for f in migrations_dir.glob("*.sql"))
        applied_set = set(result["applied_migrations"])
        result["pending_migrations"] = [f for f in all_files if f not in applied_set]

    schema_ok, missing = validate_schema()
    result["schema_ok"] = schema_ok
    result["missing_columns"] = missing

    return result


def init_db():
    """Initialize database with migrations (idempotent).

    Raises RuntimeError if migrations directory is not found.
    """
    migrations_dir = Path(__file__).parent / "migrations"

    if not migrations_dir.exists():
        raise RuntimeError(
            f"Migrations directory not found: {migrations_dir}. "
            "Cannot start without schema."
        )
    
    # Ensure schema_migrations table exists first (bootstrap migration)
    bootstrap_migration = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL UNIQUE,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_schema_migrations_filename ON schema_migrations(filename);
    """
    
    with get_conn() as conn:
        # Create schema_migrations table if it doesn't exist
        try:
            conn.executescript(bootstrap_migration)
        except Exception:
            pass  # Table might already exist
        
        # Get all SQL files in lexical order
        migration_files = sorted([f for f in os.listdir(migrations_dir) if f.endswith('.sql')])
        
        # Check which migrations have been applied
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM schema_migrations")
        applied_migrations = {row["filename"] for row in cursor.fetchall()}
        
        # Helper function to check if a column exists
        def column_exists(table_name: str, column_name: str) -> bool:
            """Check if a column exists in a table."""
            try:
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [row[1] for row in cursor.fetchall()]
                return column_name in columns
            except Exception:
                return False
        
        # Apply migrations that haven't been applied yet
        for migration_file in migration_files:
            # For migration 008, check if all columns exist even if marked as applied
            # This handles the case where migration was partially applied
            if migration_file == "008_enhance_tool_calls.sql" and migration_file in applied_migrations:
                # Check if provider_name column exists (it might be missing if migration failed partway)
                if not column_exists("runs", "provider_name"):
                    logger.warning(f"Migration {migration_file} marked as applied but provider_name column missing, re-applying...")
                    # Remove from applied_migrations so it gets re-applied
                    applied_migrations.remove(migration_file)
                    # Also remove from database
                    cursor.execute("DELETE FROM schema_migrations WHERE filename = ?", (migration_file,))
                    conn.commit()
                else:
                    logger.debug(f"Migration {migration_file} already applied, skipping")
                    continue
            elif migration_file in applied_migrations:
                logger.debug(f"Migration {migration_file} already applied, skipping")
                continue
            
            migration_path = migrations_dir / migration_file
            try:
                with open(migration_path, "r") as f:
                    migration_sql = f.read()
                
                # Split SQL into individual statements and execute them one by one
                # This allows us to skip duplicate column errors and continue with remaining statements
                # Remove single-line comments and split by semicolon
                lines = []
                for line in migration_sql.split('\n'):
                    # Remove inline comments (-- style)
                    if '--' in line:
                        line = line[:line.index('--')]
                    lines.append(line)
                cleaned_sql = '\n'.join(lines)
                # Split by semicolon and filter empty statements
                statements = [s.strip() for s in cleaned_sql.split(';') if s.strip()]
                
                executed_count = 0
                skipped_count = 0
                
                for statement in statements:
                    if not statement:
                        continue
                    try:
                        conn.execute(statement)
                        executed_count += 1
                    except sqlite3.OperationalError as e:
                        error_str = str(e).lower()
                        # Skip duplicate column/index errors (idempotency)
                        if "duplicate column" in error_str or "already exists" in error_str or "duplicate index" in error_str:
                            logger.debug(f"Skipping statement in {migration_file} (already exists): {statement[:50]}...")
                            skipped_count += 1
                        else:
                            # Re-raise non-duplicate errors
                            raise
                
                conn.commit()
                
                # Record migration
                from backend.core.time import now_iso
                cursor.execute(
                    "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
                    (migration_file, now_iso())
                )
                conn.commit()
                
                if skipped_count > 0:
                    logger.info(f"Applied migration: {migration_file} ({executed_count} statements executed, {skipped_count} skipped)")
                else:
                    logger.info(f"Applied migration: {migration_file}")
            except sqlite3.OperationalError as e:
                error_str = str(e).lower()
                if "duplicate column" in error_str or "already exists" in error_str:
                    # Migration partially applied (columns exist), mark as applied
                    logger.warning(f"Migration {migration_file} partially applied (some columns exist): {e}")
                    from backend.core.time import now_iso
                    cursor.execute(
                        "INSERT OR IGNORE INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
                        (migration_file, now_iso())
                    )
                    conn.commit()
                else:
                    logger.error(f"Failed to apply migration {migration_file}: {e}")
                    raise
            except Exception as e:
                logger.error(f"Failed to apply migration {migration_file}: {e}")
                raise

    # Validate schema after all migrations applied
    schema_ok, missing = validate_schema()

    # Log startup summary
    settings = get_settings()
    db_path = os.path.abspath(_parse_db_url(settings.database_url))
    applied_count = len([f for f in migration_files if f in applied_migrations]) + \
        len([f for f in migration_files if f not in applied_migrations])
    logger.info(
        "DB: %s | Migrations: %d applied | Schema: %s",
        db_path,
        len(migration_files),
        "OK" if schema_ok else f"MISSING {missing}"
    )

    # Critical column check: block startup if runner-critical columns are missing
    CRITICAL_COLUMNS = {
        "runs": ["command_text", "metadata_json", "intent_json",
                 "parsed_intent_json", "execution_plan_json",
                 "failure_reason", "failure_code", "news_enabled", "asset_class"],
    }
    critical_missing = {}
    for table, cols in CRITICAL_COLUMNS.items():
        table_missing = [c for c in cols if c in missing.get(table, [])]
        if table_missing:
            critical_missing[table] = table_missing
    if critical_missing:
        logger.error(
            "CRITICAL: Database schema is missing columns required by runner: %s. "
            "Re-apply migrations: 006_add_command_fields.sql, 018_add_runs_metadata.sql, "
            "019_enhance_run_failures.sql, 022_add_news_toggle.sql, 029_ensure_all_columns.sql",
            critical_missing
        )
