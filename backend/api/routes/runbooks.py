"""Runbook/Playbook API routes.

Provides CRUD, search, suggestion, and usage tracking for operational runbooks.
"""
import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.deps import get_current_user
from backend.core.ids import new_id
from backend.core.logging import get_logger
from backend.core.time import now_iso
from backend.core.utils import _safe_json_loads, json_dumps
from backend.db.connect import get_conn, row_get

router = APIRouter()
logger = get_logger(__name__)


# ── Pydantic models ─────────────────────────────────────────────────────


class RunbookCreate(BaseModel):
    title: str
    slug: str
    category: str = "general"
    error_codes: List[str] = Field(default_factory=list)
    symptoms: str = ""
    diagnosis_steps: str = ""
    resolution: str = ""
    prevention: str = ""
    severity: str = "medium"


class RunbookUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    error_codes: Optional[List[str]] = None
    symptoms: Optional[str] = None
    diagnosis_steps: Optional[str] = None
    resolution: Optional[str] = None
    prevention: Optional[str] = None
    severity: Optional[str] = None


class RunbookUseRequest(BaseModel):
    outcome: str = ""
    notes: str = ""
    issue_id: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a dict with parsed error_codes JSON."""
    if row is None:
        return {}
    d = dict(row)
    d["error_codes"] = _safe_json_loads(row_get(row, "error_codes", "[]"), default=[])
    return d


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("")
async def list_runbooks(
    category: Optional[str] = Query(None),
    error_code: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """List runbooks with optional filtering by category, error_code, or free-text search."""
    with get_conn() as conn:
        cursor = conn.cursor()

        # Build query dynamically
        conditions = []
        params: list = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if error_code:
            # Search within JSON array stored as text
            conditions.append("error_codes LIKE ?")
            params.append(f"%{error_code}%")

        if q:
            # Free-text search across title, symptoms, error_codes
            conditions.append(
                "(title LIKE ? OR symptoms LIKE ? OR error_codes LIKE ?)"
            )
            pattern = f"%{q}%"
            params.extend([pattern, pattern, pattern])

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        cursor.execute(
            f"SELECT * FROM runbooks{where_clause} ORDER BY times_used DESC, title ASC",
            params,
        )
        rows = cursor.fetchall()

    return {"runbooks": [_row_to_dict(r) for r in rows]}


@router.get("/suggest")
async def suggest_runbooks(
    error_code: str = Query(..., description="Error code to find matching runbooks"),
    user: dict = Depends(get_current_user),
):
    """Auto-suggest runbooks matching an error code."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM runbooks WHERE error_codes LIKE ? ORDER BY times_used DESC",
            (f"%{error_code}%",),
        )
        rows = cursor.fetchall()

    return {"suggestions": [_row_to_dict(r) for r in rows]}


@router.get("/{slug}")
async def get_runbook(slug: str, user: dict = Depends(get_current_user)):
    """Get a single runbook by slug."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runbooks WHERE slug = ?", (slug,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Runbook not found")

    return _row_to_dict(row)


@router.post("", status_code=201)
async def create_runbook(body: RunbookCreate, user: dict = Depends(get_current_user)):
    """Create a new runbook."""
    runbook_id = new_id("rb_")
    now = now_iso()
    error_codes_json = json.dumps(body.error_codes)

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO runbooks
                    (runbook_id, title, slug, category, error_codes, symptoms,
                     diagnosis_steps, resolution, prevention, severity,
                     times_used, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    runbook_id,
                    body.title,
                    body.slug,
                    body.category,
                    error_codes_json,
                    body.symptoms,
                    body.diagnosis_steps,
                    body.resolution,
                    body.prevention,
                    body.severity,
                    user.get("user_id"),
                    now,
                    now,
                ),
            )
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(status_code=409, detail=f"Runbook with slug '{body.slug}' already exists")
        raise

    # Return the created runbook
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runbooks WHERE runbook_id = ?", (runbook_id,))
        row = cursor.fetchone()

    return _row_to_dict(row)


@router.patch("/{slug}")
async def update_runbook(slug: str, body: RunbookUpdate, user: dict = Depends(get_current_user)):
    """Update an existing runbook by slug."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT runbook_id FROM runbooks WHERE slug = ?", (slug,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Runbook not found")

        # Build SET clause from provided fields
        updates = []
        params: list = []
        update_data = body.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if field == "error_codes":
                updates.append("error_codes = ?")
                params.append(json.dumps(value))
            else:
                updates.append(f"{field} = ?")
                params.append(value)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates.append("updated_at = ?")
        params.append(now_iso())
        params.append(slug)

        cursor.execute(
            f"UPDATE runbooks SET {', '.join(updates)} WHERE slug = ?",
            params,
        )

    # Return updated runbook
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runbooks WHERE slug = ?", (slug,))
        row = cursor.fetchone()

    return _row_to_dict(row)


@router.delete("/{slug}")
async def delete_runbook(slug: str, user: dict = Depends(get_current_user)):
    """Delete a runbook by slug."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT runbook_id FROM runbooks WHERE slug = ?", (slug,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Runbook not found")

        cursor.execute("DELETE FROM runbooks WHERE slug = ?", (slug,))

    return {"status": "deleted", "slug": slug}


@router.post("/{slug}/use")
async def log_usage(slug: str, body: RunbookUseRequest, user: dict = Depends(get_current_user)):
    """Log usage of a runbook and increment times_used."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT runbook_id FROM runbooks WHERE slug = ?", (slug,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Runbook not found")

        runbook_id = row["runbook_id"]
        now = now_iso()
        usage_id = new_id("rbu_")

        # Insert usage record
        cursor.execute(
            """
            INSERT INTO runbook_usage (usage_id, runbook_id, tenant_id, issue_id, outcome, notes, used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                usage_id,
                runbook_id,
                user.get("tenant_id"),
                body.issue_id,
                body.outcome,
                body.notes,
                now,
            ),
        )

        # Increment times_used and update last_used_at
        cursor.execute(
            "UPDATE runbooks SET times_used = times_used + 1, last_used_at = ? WHERE runbook_id = ?",
            (now, runbook_id),
        )

    return {"status": "recorded", "usage_id": usage_id, "slug": slug}
