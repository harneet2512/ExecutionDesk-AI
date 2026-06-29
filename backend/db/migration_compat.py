"""SQL dialect adapter for SQLite/PostgreSQL compatibility.

Provides helper functions that emit the correct SQL syntax depending
on the active database backend.
"""
from backend.db.connect import _is_postgres
from backend.core.config import get_settings


def _dialect() -> str:
    """Return 'postgres' or 'sqlite' based on DATABASE_URL."""
    settings = get_settings()
    return "postgres" if _is_postgres(settings.database_url) else "sqlite"


def now_sql() -> str:
    """SQL expression for current UTC timestamp.

    SQLite:     datetime('now')
    PostgreSQL: NOW()
    """
    if _dialect() == "postgres":
        return "NOW()"
    return "datetime('now')"


def date_diff_days(column: str, days: int) -> str:
    """SQL expression for  column >= (now - N days).

    SQLite:     column >= datetime('now', '-N days')
    PostgreSQL: column >= NOW() - INTERVAL 'N days'
    """
    if _dialect() == "postgres":
        return f"{column} >= NOW() - INTERVAL '{days} days'"
    return f"{column} >= datetime('now', '-{days} days')"


def date_trunc_day(column: str) -> str:
    """SQL expression to truncate a timestamp to date (YYYY-MM-DD).

    SQLite:     DATE(column)
    PostgreSQL: DATE(column)
    Both support DATE() for simple day truncation.
    """
    return f"DATE({column})"


def placeholder() -> str:
    """Parameter placeholder.

    SQLite:     ?
    PostgreSQL: %s
    """
    if _dialect() == "postgres":
        return "%s"
    return "?"


def autoincrement_pk() -> str:
    """Primary key definition for auto-increment.

    SQLite:     INTEGER PRIMARY KEY AUTOINCREMENT
    PostgreSQL: SERIAL PRIMARY KEY
    """
    if _dialect() == "postgres":
        return "SERIAL PRIMARY KEY"
    return "INTEGER PRIMARY KEY AUTOINCREMENT"


def concat_json_array(column: str) -> str:
    """SQL expression to aggregate values into a JSON array.

    SQLite:     json_group_array(column)
    PostgreSQL: json_agg(column)
    """
    if _dialect() == "postgres":
        return f"json_agg({column})"
    return f"json_group_array({column})"


def coalesce_zero(expr: str) -> str:
    """Wrap expression in COALESCE(..., 0). Works on both dialects."""
    return f"COALESCE({expr}, 0)"


def iif_sql(condition: str, true_val: str, false_val: str) -> str:
    """Conditional expression.

    SQLite 3.32+: IIF(cond, true, false)
    PostgreSQL:   CASE WHEN cond THEN true ELSE false END
    Both dialects: use CASE WHEN for maximum compat.
    """
    return f"CASE WHEN {condition} THEN {true_val} ELSE {false_val} END"
