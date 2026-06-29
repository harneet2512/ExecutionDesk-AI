"""Analytics: Client-level analytical endpoints.

Five cross-tenant analytics endpoints for platform operators:
- Client churn risk
- Execution quality
- Error breakdown
- Feature adoption
- Revenue by tier

SQL queries are written to work with BOTH SQLite and PostgreSQL.
"""
from fastapi import APIRouter, Depends, Query
from backend.api.deps import require_viewer
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator, denominator, default=0.0):
    """Safe division, returns default when denominator is zero or None."""
    try:
        if not denominator:
            return default
        return numerator / denominator
    except (TypeError, ZeroDivisionError):
        return default


def _classify_churn_risk(total_runs: int, failed_runs: int, days_since_last: float) -> str:
    """Classify tenant churn risk as HIGH / MEDIUM / LOW."""
    if total_runs == 0 or days_since_last > 30:
        return "HIGH"
    fail_rate = _safe_div(failed_runs, total_runs)
    if fail_rate > 0.5 or days_since_last > 14:
        return "MEDIUM"
    return "LOW"


def _classify_tier(total_notional: float) -> str:
    """Classify tenant into a tier based on total notional traded."""
    if total_notional >= 10000:
        return "enterprise"
    elif total_notional >= 1000:
        return "pro"
    elif total_notional > 0:
        return "starter"
    return "free"


# ---------------------------------------------------------------------------
# 1. Client churn risk
# ---------------------------------------------------------------------------

@router.get("/client-churn-risk")
async def get_client_churn_risk(
    days: int = Query(default=30, description="Lookback window in days"),
    user: dict = Depends(require_viewer),
):
    """Identify tenants at risk of churning.

    Heuristic: high failure rate, long time since last run, or low activity.
    Works with both SQLite and PostgreSQL (uses portable SQL).
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        # Portable SQL: julianday works in SQLite; for PostgreSQL the
        # EXTRACT(EPOCH FROM ...) / 86400 equivalent would be needed.
        # Since this is a read-only analytical query on small result sets,
        # we fetch raw data and compute in Python for full dialect compat.
        cursor.execute(
            """
            SELECT
                tenant_id,
                COUNT(*) AS total_runs,
                SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_runs,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_runs,
                MAX(created_at) AS last_run_at
            FROM runs
            GROUP BY tenant_id
            """
        )
        rows = cursor.fetchall()

    from datetime import datetime, timezone

    clients = []
    for row in rows:
        total = row["total_runs"] or 0
        failed = row["failed_runs"] or 0
        completed = row["completed_runs"] or 0
        last_run = row["last_run_at"] or ""

        # Compute days since last run
        days_since = 999.0
        if last_run:
            try:
                # Handle ISO format with or without Z suffix
                clean = last_run.replace("Z", "+00:00") if last_run.endswith("Z") else last_run
                last_dt = datetime.fromisoformat(clean)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                days_since = (now - last_dt).total_seconds() / 86400.0
            except (ValueError, TypeError):
                days_since = 999.0

        risk_level = _classify_churn_risk(total, failed, days_since)

        clients.append({
            "tenant_id": row["tenant_id"],
            "total_runs": total,
            "completed_runs": completed,
            "failed_runs": failed,
            "last_run_at": last_run,
            "days_since_last_run": round(days_since, 1),
            "risk_level": risk_level,
        })

    # Sort by risk level (HIGH first)
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    clients.sort(key=lambda c: risk_order.get(c["risk_level"], 3))

    return {"clients": clients}


# ---------------------------------------------------------------------------
# 2. Execution quality
# ---------------------------------------------------------------------------

@router.get("/execution-quality")
async def get_execution_quality(
    user: dict = Depends(require_viewer),
):
    """Aggregate execution quality metrics across all runs.

    Returns success rate, average node completion, and eval scores.
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        # Run-level stats
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_runs,
                SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN status = 'RUNNING' THEN 1 ELSE 0 END) AS running
            FROM runs
            """
        )
        run_stats = cursor.fetchone()

        # Node-level stats
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_nodes,
                SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_nodes,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_nodes
            FROM dag_nodes
            """
        )
        node_stats = cursor.fetchone()

        # Eval scores (average)
        cursor.execute(
            """
            SELECT
                AVG(score) AS avg_score,
                COUNT(*) AS eval_count
            FROM eval_results
            """
        )
        eval_stats = cursor.fetchone()

    total_runs = run_stats["total_runs"] or 0
    completed = run_stats["completed"] or 0
    total_nodes = node_stats["total_nodes"] or 0
    completed_nodes = node_stats["completed_nodes"] or 0

    return {
        "summary": {
            "total_runs": total_runs,
            "completed_runs": completed,
            "failed_runs": run_stats["failed"] or 0,
            "running_runs": run_stats["running"] or 0,
            "success_rate": round(_safe_div(completed, total_runs) * 100, 2),
            "total_nodes": total_nodes,
            "completed_nodes": completed_nodes,
            "node_completion_rate": round(_safe_div(completed_nodes, total_nodes) * 100, 2),
            "avg_eval_score": round(float(eval_stats["avg_score"] or 0), 4),
            "eval_count": eval_stats["eval_count"] or 0,
        }
    }


# ---------------------------------------------------------------------------
# 3. Error breakdown
# ---------------------------------------------------------------------------

@router.get("/error-breakdown")
async def get_error_breakdown(
    user: dict = Depends(require_viewer),
):
    """Breakdown of errors by failure code/reason across failed runs.

    Groups by failure_code (if available) or extracts a short label from
    failure_reason.
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        # Failed runs grouped by failure code
        cursor.execute(
            """
            SELECT
                COALESCE(failure_code, 'UNKNOWN') AS failure_code,
                COUNT(*) AS count
            FROM runs
            WHERE status = 'FAILED'
            GROUP BY COALESCE(failure_code, 'UNKNOWN')
            ORDER BY count DESC
            """
        )
        code_rows = cursor.fetchall()

        # Failed DAG nodes grouped by name
        cursor.execute(
            """
            SELECT
                name AS node_name,
                COUNT(*) AS count
            FROM dag_nodes
            WHERE status = 'FAILED'
            GROUP BY name
            ORDER BY count DESC
            """
        )
        node_rows = cursor.fetchall()

        # Total error count
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM runs WHERE status = 'FAILED'"
        )
        total_row = cursor.fetchone()

    errors = []
    for row in code_rows:
        errors.append({
            "failure_code": row["failure_code"],
            "count": row["count"],
        })

    node_errors = []
    for row in node_rows:
        node_errors.append({
            "node_name": row["node_name"],
            "count": row["count"],
        })

    return {
        "total_errors": total_row["cnt"] or 0,
        "errors": errors,
        "node_errors": node_errors,
    }


# ---------------------------------------------------------------------------
# 4. Feature adoption
# ---------------------------------------------------------------------------

@router.get("/feature-adoption")
async def get_feature_adoption(
    user: dict = Depends(require_viewer),
):
    """Feature adoption metrics: which DAG nodes and tools are most used.

    Features are inferred from DAG node names and tool_calls table.
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        # DAG node usage (feature = node name)
        cursor.execute(
            """
            SELECT
                name AS feature,
                COUNT(*) AS usage_count,
                COUNT(DISTINCT run_id) AS unique_runs
            FROM dag_nodes
            GROUP BY name
            ORDER BY usage_count DESC
            """
        )
        node_rows = cursor.fetchall()

        # Tool usage
        cursor.execute(
            """
            SELECT
                tool_name AS feature,
                COUNT(*) AS usage_count,
                COUNT(DISTINCT run_id) AS unique_runs
            FROM tool_calls
            GROUP BY tool_name
            ORDER BY usage_count DESC
            """
        )
        tool_rows = cursor.fetchall()

    features = []
    for row in node_rows:
        features.append({
            "feature": row["feature"],
            "type": "dag_node",
            "usage_count": row["usage_count"],
            "unique_runs": row["unique_runs"],
        })
    for row in tool_rows:
        features.append({
            "feature": row["feature"],
            "type": "tool",
            "usage_count": row["usage_count"],
            "unique_runs": row["unique_runs"],
        })

    # Sort combined list by usage
    features.sort(key=lambda f: f["usage_count"], reverse=True)

    return {"features": features}


# ---------------------------------------------------------------------------
# 5. Revenue by tier
# ---------------------------------------------------------------------------

@router.get("/revenue-by-tier")
async def get_revenue_by_tier(
    user: dict = Depends(require_viewer),
):
    """Revenue proxy grouped by tenant tier (based on total notional traded).

    Tiers:
    - free:       no orders
    - starter:    < $1,000 total notional
    - pro:        $1,000 - $9,999
    - enterprise: >= $10,000
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        # Aggregate notional per tenant
        cursor.execute(
            """
            SELECT
                o.tenant_id,
                COUNT(DISTINCT o.run_id) AS run_count,
                COUNT(o.order_id) AS order_count,
                COALESCE(SUM(o.notional_usd), 0) AS total_notional_usd,
                COALESCE(SUM(o.total_fees), 0) AS total_fees
            FROM orders o
            WHERE o.status = 'FILLED'
            GROUP BY o.tenant_id
            """
        )
        rows = cursor.fetchall()

    # Classify into tiers and aggregate
    tier_agg = {}  # tier -> {run_count, order_count, total_notional_usd, total_fees, tenant_count}
    for row in rows:
        notional = float(row["total_notional_usd"] or 0)
        tier = _classify_tier(notional)
        if tier not in tier_agg:
            tier_agg[tier] = {
                "tier": tier,
                "tenant_count": 0,
                "run_count": 0,
                "order_count": 0,
                "total_notional_usd": 0.0,
                "total_fees": 0.0,
            }
        tier_agg[tier]["tenant_count"] += 1
        tier_agg[tier]["run_count"] += row["run_count"] or 0
        tier_agg[tier]["order_count"] += row["order_count"] or 0
        tier_agg[tier]["total_notional_usd"] += notional
        tier_agg[tier]["total_fees"] += float(row["total_fees"] or 0)

    # Round floats
    tiers = []
    for t in tier_agg.values():
        t["total_notional_usd"] = round(t["total_notional_usd"], 2)
        t["total_fees"] = round(t["total_fees"], 2)
        tiers.append(t)

    # Sort by notional descending
    tiers.sort(key=lambda t: t["total_notional_usd"], reverse=True)

    return {"tiers": tiers}
