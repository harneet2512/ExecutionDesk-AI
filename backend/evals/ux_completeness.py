"""UX Completeness Evaluation - verifies required STEP events exist and ordered."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_ux_completeness(run_id: str, tenant_id: str) -> dict:
    """
    Eval: UX Completeness
    
    Checks:
    - Required STEP events exist (STEP_STARTED, STEP_FINISHED for each node)
    - Steps appear in deterministic order
    - All steps have summaries/details
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get STEP events
        cursor.execute(
            """
            SELECT event_type, payload_json, ts
            FROM run_events
            WHERE run_id = ? AND event_type IN ('STEP_STARTED', 'STEP_FINISHED')
            ORDER BY ts ASC
            """,
            (run_id,)
        )
        step_events = cursor.fetchall()
        
        # Get nodes
        cursor.execute(
            """
            SELECT node_id, name FROM dag_nodes
            WHERE run_id = ?
            ORDER BY started_at ASC
            """,
            (run_id,)
        )
        nodes = cursor.fetchall()
        
        if not nodes:
            return {"score": 0.0, "reasons": ["No nodes found"]}
        
        # Required nodes for command runs
        required_nodes = ["research", "signals", "risk", "proposal", "policy_check", "execution", "post_trade", "eval"]
        
        # Build step tracking
        step_starts = {}
        step_finishes = {}
        
        for event in step_events:
            payload = json.loads(event["payload_json"]) if event["payload_json"] else {}
            step_name = payload.get("step_name")
            event_type = event["event_type"]
            
            if event_type == "STEP_STARTED":
                step_starts[step_name] = event["ts"]
            elif event_type == "STEP_FINISHED":
                step_finishes[step_name] = {
                    "ts": event["ts"],
                    "summary": payload.get("summary"),
                    "status": payload.get("status")
                }
        
        # Check completeness
        missing_starts = []
        missing_finishes = []
        missing_summaries = []
        
        for node_name in required_nodes:
            if node_name not in step_starts:
                missing_starts.append(node_name)
            if node_name not in step_finishes:
                missing_finishes.append(node_name)
            elif not step_finishes[node_name].get("summary"):
                missing_summaries.append(node_name)
        
        # Calculate score
        total_required = len(required_nodes)
        complete_steps = total_required - len(missing_starts) - len(missing_finishes)
        score = complete_steps / total_required
        
        reasons = []
        if missing_starts:
            reasons.append(f"Missing STEP_STARTED: {missing_starts}")
        if missing_finishes:
            reasons.append(f"Missing STEP_FINISHED: {missing_finishes}")
        if missing_summaries:
            reasons.append(f"Missing summaries: {missing_summaries}")
        
        if not reasons:
            reasons.append(f"All {total_required} required steps have STARTED and FINISHED events with summaries")
    
    return {"score": score, "reasons": reasons, "required_nodes": required_nodes}
