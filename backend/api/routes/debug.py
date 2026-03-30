from fastapi import APIRouter, HTTPException, Depends
from backend.db.connect import get_conn
from backend.core.config import get_settings
from backend.api.deps import require_viewer
from backend.core.logging import get_logger
import json

router = APIRouter()
logger = get_logger(__name__)

@router.get("/run_trace/{run_id}")
async def get_run_trace(run_id: str, user: dict = Depends(require_viewer)):
    tenant_id = user["tenant_id"]
    try:
        with get_conn() as conn:
            cursor = conn.cursor()

            # 1. Run Metadata (tenant-scoped)
            cursor.execute("SELECT * FROM runs WHERE run_id = ? AND tenant_id = ?", (run_id, tenant_id))
            run = cursor.fetchone()
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")

            # 2. Node Statuses
            cursor.execute("SELECT * FROM dag_nodes WHERE run_id = ? ORDER BY started_at", (run_id,))
            nodes = cursor.fetchall()

            # 3. Events Count
            cursor.execute("SELECT COUNT(*) as cnt FROM run_events WHERE run_id = ?", (run_id,))
            events_count = cursor.fetchone()["cnt"]

            # 4. Artifacts Count
            cursor.execute("SELECT COUNT(*) as cnt FROM run_artifacts WHERE run_id = ?", (run_id,))
            artifacts_count = cursor.fetchone()["cnt"]

        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "created_at": run["created_at"],
            "updated_at": run["completed_at"] or run["created_at"],
            "execution_mode": run["execution_mode"],
            "node_count": len(nodes),
            "node_statuses": [dict(n) for n in nodes],
            "sse_events_count": events_count,
            "artifacts_count": artifacts_count,
            "config": {}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Debug trace error for run %s: %s", run_id, str(e)[:200])
        return {"error": "Internal error fetching debug trace"}
