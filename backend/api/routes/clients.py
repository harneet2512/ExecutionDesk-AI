"""Client Operations Dashboard API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
import json
from backend.api.deps import require_viewer, require_admin, get_current_user
from backend.db.connect import get_conn, row_get
from backend.core.utils import _safe_json_loads, json_dumps
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("")
async def list_clients(
    classification: Optional[str] = Query(None),
    user: dict = Depends(require_admin)
):
    """List all client profiles with health summaries."""
    with get_conn() as conn:
        cursor = conn.cursor()

        if classification:
            cursor.execute(
                """SELECT * FROM client_profiles
                   WHERE health_classification = ?
                   ORDER BY health_score DESC""",
                (classification,)
            )
        else:
            cursor.execute(
                "SELECT * FROM client_profiles ORDER BY health_score DESC"
            )
        rows = cursor.fetchall()

    clients = []
    for row in rows:
        client = dict(row)
        client["metadata"] = _safe_json_loads(row_get(row, "metadata_json"), default={})
        clients.append(client)

    return {"clients": clients, "total": len(clients)}


@router.get("/{tenant_id}")
async def get_client_profile(
    tenant_id: str,
    user: dict = Depends(require_admin)
):
    """Get detailed client profile with health breakdown."""
    # Compute fresh health data
    from backend.services.client_health import compute_health_score, detect_alerts, save_health_profile, save_alerts

    health = compute_health_score(tenant_id)
    save_health_profile(tenant_id, health)

    alerts_data = detect_alerts(tenant_id, health)
    save_alerts(tenant_id, alerts_data)

    # Fetch saved alerts
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT * FROM client_alerts
               WHERE tenant_id = ? AND acknowledged = 0
               ORDER BY created_at DESC LIMIT 20""",
            (tenant_id,)
        )
        alerts = [dict(r) for r in cursor.fetchall()]

        # Fetch recent issues
        cursor.execute(
            """SELECT * FROM client_issues
               WHERE tenant_id = ?
               ORDER BY created_at DESC LIMIT 10""",
            (tenant_id,)
        )
        issues = [dict(r) for r in cursor.fetchall()]

    return {
        "tenant_id": tenant_id,
        "health": health,
        "alerts": alerts,
        "issues": issues,
    }


@router.post("/refresh")
async def refresh_clients(user: dict = Depends(require_admin)):
    """Refresh health scores for all clients."""
    from backend.services.client_health import refresh_all_clients

    results = refresh_all_clients()
    return {"refreshed": len(results), "results": results}


@router.get("/{tenant_id}/issues")
async def list_issues(
    tenant_id: str,
    status: Optional[str] = Query(None),
    user: dict = Depends(require_admin)
):
    """List issues for a client."""
    with get_conn() as conn:
        cursor = conn.cursor()

        if status:
            cursor.execute(
                """SELECT * FROM client_issues
                   WHERE tenant_id = ? AND status = ?
                   ORDER BY created_at DESC""",
                (tenant_id, status)
            )
        else:
            cursor.execute(
                """SELECT * FROM client_issues
                   WHERE tenant_id = ?
                   ORDER BY created_at DESC""",
                (tenant_id,)
            )
        rows = cursor.fetchall()

    issues = []
    for row in rows:
        issue = dict(row)
        # Fetch comment count
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM client_issue_comments WHERE issue_id = ?",
                (row_get(row, "issue_id"),)
            )
            issue["comment_count"] = cursor.fetchone()["cnt"]
        issues.append(issue)

    return {"issues": issues, "total": len(issues)}


@router.post("/{tenant_id}/issues")
async def create_issue(
    tenant_id: str,
    body: dict,
    user: dict = Depends(require_admin)
):
    """Create a new issue for a client."""
    title = body.get("title")
    if not title:
        raise HTTPException(status_code=422, detail="title is required")

    issue_id = new_id("issue_")
    now = now_iso()

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO client_issues
               (issue_id, tenant_id, title, description, status, priority, category, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                issue_id,
                tenant_id,
                title,
                body.get("description", ""),
                body.get("status", "open"),
                body.get("priority", "medium"),
                body.get("category", "general"),
                user.get("user_id", "unknown"),
                now,
                now,
            ),
        )
        conn.commit()

    return {
        "issue_id": issue_id,
        "tenant_id": tenant_id,
        "title": title,
        "status": "open",
        "created_at": now,
    }


@router.patch("/{tenant_id}/issues/{issue_id}")
async def update_issue(
    tenant_id: str,
    issue_id: str,
    body: dict,
    user: dict = Depends(require_admin)
):
    """Update an issue (status, priority, assignment, add comment)."""
    with get_conn() as conn:
        cursor = conn.cursor()

        # Verify issue exists and belongs to tenant
        cursor.execute(
            "SELECT * FROM client_issues WHERE issue_id = ? AND tenant_id = ?",
            (issue_id, tenant_id)
        )
        issue = cursor.fetchone()
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")

        # Build update fields
        updates = []
        params = []
        for field in ("status", "priority", "assigned_to", "category"):
            if field in body:
                updates.append(f"{field} = ?")
                params.append(body[field])

        # Handle resolution
        if body.get("status") == "resolved":
            updates.append("resolved_at = ?")
            params.append(now_iso())

        if updates:
            updates.append("updated_at = ?")
            params.append(now_iso())
            params.extend([issue_id, tenant_id])

            cursor.execute(
                f"UPDATE client_issues SET {', '.join(updates)} WHERE issue_id = ? AND tenant_id = ?",
                params,
            )

        # Add comment if provided
        comment_text = body.get("comment")
        if comment_text:
            comment_id = new_id("cmt_")
            cursor.execute(
                """INSERT INTO client_issue_comments (comment_id, issue_id, author, content, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (comment_id, issue_id, user.get("user_id", "unknown"), comment_text, now_iso()),
            )

        conn.commit()

    # Return updated issue
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM client_issues WHERE issue_id = ?",
            (issue_id,)
        )
        updated = cursor.fetchone()

        cursor.execute(
            "SELECT * FROM client_issue_comments WHERE issue_id = ? ORDER BY created_at ASC",
            (issue_id,)
        )
        comments = [dict(c) for c in cursor.fetchall()]

    result = dict(updated) if updated else {}
    result["comments"] = comments
    return result


@router.get("/{tenant_id}/alerts")
async def list_alerts(
    tenant_id: str,
    acknowledged: Optional[bool] = Query(None),
    user: dict = Depends(require_admin)
):
    """List alerts for a client."""
    with get_conn() as conn:
        cursor = conn.cursor()

        if acknowledged is not None:
            cursor.execute(
                """SELECT * FROM client_alerts
                   WHERE tenant_id = ? AND acknowledged = ?
                   ORDER BY created_at DESC LIMIT 50""",
                (tenant_id, 1 if acknowledged else 0)
            )
        else:
            cursor.execute(
                """SELECT * FROM client_alerts
                   WHERE tenant_id = ?
                   ORDER BY created_at DESC LIMIT 50""",
                (tenant_id,)
            )
        rows = cursor.fetchall()

    return {"alerts": [dict(r) for r in rows], "total": len(rows)}


@router.post("/{tenant_id}/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    tenant_id: str,
    alert_id: str,
    user: dict = Depends(require_admin)
):
    """Acknowledge an alert."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM client_alerts WHERE alert_id = ? AND tenant_id = ?",
            (alert_id, tenant_id)
        )
        alert = cursor.fetchone()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        cursor.execute(
            "UPDATE client_alerts SET acknowledged = 1, acknowledged_by = ?, acknowledged_at = ? WHERE alert_id = ?",
            (user.get("user_id", "unknown"), now_iso(), alert_id),
        )
        conn.commit()

    return {"alert_id": alert_id, "acknowledged": True}
