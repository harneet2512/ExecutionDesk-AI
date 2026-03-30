from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Depends
from typing import List, Optional
from backend.services.news_ingestion import NewsIngestionService
from backend.services.news_brief import NewsBriefService
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.api.deps import require_viewer

router = APIRouter()
logger = get_logger(__name__)

ingestion_service = NewsIngestionService()
news_brief_service = NewsBriefService()

@router.on_event("startup")
async def startup_event():
    # Seed default sources on startup
    try:
        ingestion_service.seed_default_sources()
    except Exception as e:
        logger.error(f"Failed to seed news sources: {e}")

@router.get("/sources")
async def get_news_sources(user: dict = Depends(require_viewer)):
    """Get all configured news sources."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM news_sources")
        return [dict(row) for row in cursor.fetchall()]

@router.post("/ingest")
async def trigger_ingestion(background_tasks: BackgroundTasks):
    """Trigger news ingestion in background."""
    background_tasks.add_task(ingestion_service.ingest_all)
    return {"status": "Ingestion triggered"}

@router.get("/runs/{run_id}/evidence")
async def get_run_news_evidence(run_id: str, user: dict = Depends(require_viewer)):
    """Get news evidence used in a specific run."""
    tenant_id = user["tenant_id"]
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.*, i.title, i.url, i.published_at, i.source_id, s.name as source_name
            FROM run_news_evidence e
            JOIN news_items i ON e.item_id = i.id
            LEFT JOIN news_sources s ON i.source_id = s.id
            JOIN runs r ON e.run_id = r.run_id
            WHERE e.run_id = ? AND r.tenant_id = ?
            """,
            (run_id, tenant_id)
        )
        return [dict(row) for row in cursor.fetchall()]

@router.get("/runs/{run_id}/artifacts")
async def get_run_artifacts(run_id: str, user: dict = Depends(require_viewer), step_name: Optional[str] = None, artifact_type: Optional[str] = None):
    """Get visible reasoning artifacts."""
    tenant_id = user["tenant_id"]
    # Verify run belongs to tenant
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT run_id FROM runs WHERE run_id = ? AND tenant_id = ?", (run_id, tenant_id))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Run not found")
    query = "SELECT * FROM run_artifacts WHERE run_id = ?"
    params = [run_id]
    
    if step_name:
        query += " AND step_name = ?"
        params.append(step_name)
        
    if artifact_type:
        query += " AND artifact_type = ?"
        params.append(artifact_type)
        
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        results = []
        for row in cursor.fetchall():
            res = dict(row)
            # Parse JSON content for convenience
            import json
            try:
                res["artifact_json"] = json.loads(res["artifact_json"])
            except:
                pass
            results.append(res)
        return results
