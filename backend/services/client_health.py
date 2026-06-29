"""Client health scoring and alert detection service."""
import json
from datetime import datetime, timezone, timedelta
from backend.db.connect import get_conn, row_get
from backend.core.utils import _safe_json_loads, json_dumps
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Health classification thresholds
CLASSIFICATION_THRESHOLDS = {
    "healthy": 90,    # 90-100
    "good": 70,       # 70-89
    "at_risk": 40,    # 40-69
    "churning": 1,    # 1-39
    "inactive": 0,    # 0
}


def classify_health(score: float) -> str:
    """Classify health score into category."""
    if score >= 90:
        return "healthy"
    elif score >= 70:
        return "good"
    elif score >= 40:
        return "at_risk"
    elif score >= 1:
        return "churning"
    else:
        return "inactive"


def compute_health_score(tenant_id: str) -> dict:
    """Compute health score for a tenant.

    Weights:
    - activity (30%): runs in last 30 days relative to historical average
    - success_rate (25%): successful runs / total runs
    - volume_trend (20%): recent volume vs prior period
    - error_frequency (15%): inverse of error rate
    - feature_adoption (10%): unique features used (dag nodes, evals, etc.)

    Returns dict with score, classification, and component breakdown.
    """
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat().replace('+00:00', 'Z')
    sixty_days_ago = (now - timedelta(days=60)).isoformat().replace('+00:00', 'Z')
    seven_days_ago = (now - timedelta(days=7)).isoformat().replace('+00:00', 'Z')

    with get_conn() as conn:
        cursor = conn.cursor()

        # Total runs
        cursor.execute("SELECT COUNT(*) as cnt FROM runs WHERE tenant_id = ?", (tenant_id,))
        total_runs = cursor.fetchone()["cnt"]

        # Runs in last 30 days
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM runs WHERE tenant_id = ? AND created_at >= ?",
            (tenant_id, thirty_days_ago)
        )
        recent_runs = cursor.fetchone()["cnt"]

        # Runs in prior 30 days (30-60 days ago)
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM runs WHERE tenant_id = ? AND created_at >= ? AND created_at < ?",
            (tenant_id, sixty_days_ago, thirty_days_ago)
        )
        prior_runs = cursor.fetchone()["cnt"]

        # Successful runs
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM runs WHERE tenant_id = ? AND status = 'COMPLETED'",
            (tenant_id,)
        )
        successful_runs = cursor.fetchone()["cnt"]

        # Failed runs
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM runs WHERE tenant_id = ? AND status = 'FAILED'",
            (tenant_id,)
        )
        failed_runs = cursor.fetchone()["cnt"]

        # Orders and volume
        cursor.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(CAST(filled_qty AS REAL) * CAST(avg_fill_price AS REAL)), 0) as vol FROM orders WHERE tenant_id = ?",
            (tenant_id,)
        )
        order_row = cursor.fetchone()
        total_orders = order_row["cnt"]
        total_volume = order_row["vol"]

        # Recent volume (30d)
        cursor.execute(
            "SELECT COALESCE(SUM(CAST(filled_qty AS REAL) * CAST(avg_fill_price AS REAL)), 0) as vol FROM orders WHERE tenant_id = ? AND created_at >= ?",
            (tenant_id, thirty_days_ago)
        )
        recent_volume = cursor.fetchone()["vol"]

        # Prior period volume
        cursor.execute(
            "SELECT COALESCE(SUM(CAST(filled_qty AS REAL) * CAST(avg_fill_price AS REAL)), 0) as vol FROM orders WHERE tenant_id = ? AND created_at >= ? AND created_at < ?",
            (tenant_id, sixty_days_ago, thirty_days_ago)
        )
        prior_volume = cursor.fetchone()["vol"]

        # Last activity
        cursor.execute(
            "SELECT MAX(created_at) as last_at FROM runs WHERE tenant_id = ?",
            (tenant_id,)
        )
        last_row = cursor.fetchone()
        last_activity = row_get(last_row, "last_at")

        # First seen
        cursor.execute(
            "SELECT MIN(created_at) as first_at FROM runs WHERE tenant_id = ?",
            (tenant_id,)
        )
        first_row = cursor.fetchone()
        first_seen = row_get(first_row, "first_at")

        # Feature adoption: count distinct DAG node types used
        cursor.execute(
            "SELECT COUNT(DISTINCT dn.name) as cnt FROM dag_nodes dn JOIN runs r ON dn.run_id = r.run_id WHERE r.tenant_id = ?",
            (tenant_id,)
        )
        features_used = cursor.fetchone()["cnt"]

        # Runs in last 7 days (for alerts)
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM runs WHERE tenant_id = ? AND created_at >= ?",
            (tenant_id, seven_days_ago)
        )
        runs_7d = cursor.fetchone()["cnt"]

        # Error spike: failed runs in last 7d vs prior 7d
        fourteen_days_ago = (now - timedelta(days=14)).isoformat().replace('+00:00', 'Z')
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM runs WHERE tenant_id = ? AND status = 'FAILED' AND created_at >= ?",
            (tenant_id, seven_days_ago)
        )
        errors_7d = cursor.fetchone()["cnt"]

        cursor.execute(
            "SELECT COUNT(*) as cnt FROM runs WHERE tenant_id = ? AND status = 'FAILED' AND created_at >= ? AND created_at < ?",
            (tenant_id, fourteen_days_ago, seven_days_ago)
        )
        errors_prior_7d = cursor.fetchone()["cnt"]

    # If no runs ever, score is 0 (inactive)
    if total_runs == 0:
        return {
            "tenant_id": tenant_id,
            "score": 0,
            "classification": "inactive",
            "components": {
                "activity": 0,
                "success_rate": 0,
                "volume_trend": 0,
                "error_frequency": 0,
                "feature_adoption": 0,
            },
            "stats": {
                "total_runs": 0,
                "successful_runs": 0,
                "failed_runs": 0,
                "total_orders": total_orders,
                "total_volume_usd": total_volume,
                "last_activity_at": last_activity,
                "first_seen_at": first_seen,
                "runs_7d": 0,
                "errors_7d": 0,
            },
        }

    # 1. Activity score (30%): recent runs vs expectations
    # If they had runs before, compare recent to prior. Otherwise just check if active.
    if prior_runs > 0:
        activity_ratio = min(recent_runs / max(prior_runs, 1), 2.0)  # cap at 2x
        activity_score = min(activity_ratio * 50, 100)  # 1x = 50, 2x+ = 100
    else:
        activity_score = min(recent_runs * 20, 100)  # 5+ runs in 30d = 100

    # 2. Success rate (25%)
    success_rate = successful_runs / total_runs if total_runs > 0 else 0
    success_score = success_rate * 100

    # 3. Volume trend (20%)
    if prior_volume > 0:
        volume_ratio = min(recent_volume / prior_volume, 2.0)
        volume_score = min(volume_ratio * 50, 100)
    elif recent_volume > 0:
        volume_score = 80  # new activity is good
    else:
        volume_score = 50  # no orders is neutral

    # 4. Error frequency (15%): inverse of error rate
    error_rate = failed_runs / total_runs if total_runs > 0 else 0
    error_score = max(0, (1 - error_rate) * 100)

    # 5. Feature adoption (10%)
    max_features = 10  # approximate max distinct DAG node types
    feature_score = min((features_used / max_features) * 100, 100)

    # Weighted total
    score = (
        activity_score * 0.30 +
        success_score * 0.25 +
        volume_score * 0.20 +
        error_score * 0.15 +
        feature_score * 0.10
    )
    score = round(min(max(score, 0), 100), 1)

    classification = classify_health(score)

    return {
        "tenant_id": tenant_id,
        "score": score,
        "classification": classification,
        "components": {
            "activity": round(activity_score, 1),
            "success_rate": round(success_score, 1),
            "volume_trend": round(volume_score, 1),
            "error_frequency": round(error_score, 1),
            "feature_adoption": round(feature_score, 1),
        },
        "stats": {
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
            "total_orders": total_orders,
            "total_volume_usd": float(total_volume),
            "last_activity_at": last_activity,
            "first_seen_at": first_seen,
            "runs_7d": runs_7d,
            "errors_7d": errors_7d,
        },
    }


def detect_alerts(tenant_id: str, health_data: dict) -> list:
    """Detect alert conditions for a tenant based on health data.

    Returns list of alert dicts with type, severity, message.
    """
    alerts = []
    stats = health_data.get("stats", {})

    # ALERT_NO_ACTIVITY_7D: no runs in 7 days but had previous activity
    if stats.get("total_runs", 0) > 0 and stats.get("runs_7d", 0) == 0:
        alerts.append({
            "alert_type": "ALERT_NO_ACTIVITY_7D",
            "severity": "warning",
            "message": f"No activity from tenant {tenant_id} in the last 7 days",
        })

    # ERROR_SPIKE: more errors this week than last
    if stats.get("errors_7d", 0) > 3 and stats.get("errors_7d", 0) > stats.get("total_runs", 1) * 0.3:
        alerts.append({
            "alert_type": "ERROR_SPIKE",
            "severity": "critical",
            "message": f"Error spike detected: {stats['errors_7d']} failures in last 7 days",
        })

    # VOLUME_DROP_50PCT: significant volume drop
    components = health_data.get("components", {})
    if components.get("volume_trend", 100) < 50 and stats.get("total_orders", 0) > 0:
        alerts.append({
            "alert_type": "VOLUME_DROP_50PCT",
            "severity": "warning",
            "message": "Trading volume dropped more than 50% vs prior period",
        })

    # Health-based alerts
    classification = health_data.get("classification", "")
    if classification == "at_risk":
        alerts.append({
            "alert_type": "HEALTH_AT_RISK",
            "severity": "warning",
            "message": f"Client health score is {health_data.get('score', 0)} (at risk)",
        })
    elif classification == "churning":
        alerts.append({
            "alert_type": "HEALTH_CHURNING",
            "severity": "critical",
            "message": f"Client health score is {health_data.get('score', 0)} (churning)",
        })

    return alerts


def save_health_profile(tenant_id: str, health_data: dict):
    """Save or update client health profile in the database."""
    stats = health_data.get("stats", {})
    now = now_iso()

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO client_profiles (
                tenant_id, health_score, health_classification,
                total_runs, successful_runs, failed_runs,
                total_orders, total_volume_usd,
                last_activity_at, first_seen_at,
                metadata_json, computed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id) DO UPDATE SET
                health_score = excluded.health_score,
                health_classification = excluded.health_classification,
                total_runs = excluded.total_runs,
                successful_runs = excluded.successful_runs,
                failed_runs = excluded.failed_runs,
                total_orders = excluded.total_orders,
                total_volume_usd = excluded.total_volume_usd,
                last_activity_at = excluded.last_activity_at,
                metadata_json = excluded.metadata_json,
                computed_at = excluded.computed_at,
                updated_at = excluded.updated_at
            """,
            (
                tenant_id,
                health_data.get("score", 0),
                health_data.get("classification", "inactive"),
                stats.get("total_runs", 0),
                stats.get("successful_runs", 0),
                stats.get("failed_runs", 0),
                stats.get("total_orders", 0),
                stats.get("total_volume_usd", 0),
                stats.get("last_activity_at"),
                stats.get("first_seen_at"),
                json_dumps(health_data.get("components", {})),
                now,
                now,
            ),
        )
        conn.commit()


def save_alerts(tenant_id: str, alerts: list):
    """Save new alerts, avoiding duplicates for same type within 24h."""
    if not alerts:
        return

    now_dt = datetime.now(timezone.utc)
    one_day_ago = (now_dt - timedelta(days=1)).isoformat().replace('+00:00', 'Z')
    now = now_iso()

    with get_conn() as conn:
        cursor = conn.cursor()
        for alert in alerts:
            # Check for recent duplicate
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM client_alerts WHERE tenant_id = ? AND alert_type = ? AND created_at >= ?",
                (tenant_id, alert["alert_type"], one_day_ago)
            )
            if cursor.fetchone()["cnt"] > 0:
                continue

            alert_id = new_id("alert_")
            cursor.execute(
                """
                INSERT INTO client_alerts (alert_id, tenant_id, alert_type, severity, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alert_id, tenant_id, alert["alert_type"], alert["severity"], alert["message"], now),
            )
        conn.commit()


def refresh_all_clients():
    """Refresh health scores and alerts for all known tenants."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT tenant_id FROM runs")
        tenants = [row["tenant_id"] for row in cursor.fetchall()]

    results = []
    for tid in tenants:
        try:
            health = compute_health_score(tid)
            save_health_profile(tid, health)
            alerts = detect_alerts(tid, health)
            save_alerts(tid, alerts)
            results.append({"tenant_id": tid, "score": health["score"], "alerts": len(alerts)})
        except Exception as e:
            logger.warning("Failed to refresh health for tenant %s: %s", tid, str(e)[:200])
            results.append({"tenant_id": tid, "error": str(e)[:200]})

    return results
