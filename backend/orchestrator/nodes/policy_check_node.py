"""Policy check node."""
import json
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.services.policy_engine import check_policy

async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute policy check node."""
    # Get proposal
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT trade_proposal_json FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        
        if not row or not row["trade_proposal_json"]:
            raise ValueError("No proposal found")
        
        proposal = json.loads(row["trade_proposal_json"])
        
        # Count existing orders
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE run_id = ?",
            (run_id,)
        )
        existing_count = cursor.fetchone()["cnt"]
        
        # Get execution mode
        cursor.execute(
            "SELECT execution_mode FROM runs WHERE run_id = ?",
            (run_id,)
        )
        exec_row = cursor.fetchone()
        execution_mode = exec_row["execution_mode"] if exec_row else "PAPER"
        
        # Check policy (pass execution_mode for LIVE checks)
        decision = check_policy(tenant_id, proposal, existing_count, execution_mode)
        
        # Store policy event
        event_id = new_id("pol_")
        cursor.execute(
            """
            INSERT INTO policy_events (id, run_id, node_id, decision, reasons_json, ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, run_id, node_id, decision["decision"], json.dumps(decision["reasons"]), now_iso())
        )
        conn.commit()
    
    # Emit POLICY_DECISION event (user-visible)
    from backend.orchestrator.event_emitter import emit_event
    await emit_event(run_id, "POLICY_DECISION", {
        "decision": decision["decision"],
        "reasons": decision["reasons"],
        "summary": f"Policy check: {decision['decision']}"
    }, tenant_id=tenant_id)
    
    if decision["decision"] == "REQUIRES_APPROVAL":
        await emit_event(run_id, "APPROVAL_REQUIRED", {
            "reason": "; ".join(decision["reasons"])
        }, tenant_id=tenant_id)
    
    return {
        **decision,
        "evidence_refs": [{"policy_event_id": event_id}],
        "safe_summary": f"Policy check: {decision['decision']}"
    }
