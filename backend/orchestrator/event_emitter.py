"""Event emitter helper to avoid circular imports."""
import json
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.orchestrator.event_pubsub import event_pubsub


async def emit_event(run_id: str, event_type: str, payload: dict, tenant_id: str = None):
    """Emit run event to DB and pubsub (helper to avoid circular imports)."""
    event_id = new_id("evt_")
    ts = now_iso()
    
    # Get tenant_id if not provided
    if tenant_id is None:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tenant_id FROM runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            tenant_id = row["tenant_id"] if row else "t_default"
    
    # Store in DB
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO run_events (id, run_id, tenant_id, event_type, payload_json, ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, run_id, tenant_id, event_type, json.dumps(payload), ts)
        )
        conn.commit()
    
    # Publish to pubsub
    await event_pubsub.publish(run_id, {
        "event_type": event_type,
        "payload": payload,
        "ts": ts
    })
