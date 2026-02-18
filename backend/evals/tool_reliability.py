"""Tool Reliability Evaluation - checks error rates, retries, timeouts."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_tool_reliability(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Tool Reliability
    
    Checks:
    - Error rate <= threshold (default 10%)
    - Retries recorded for transient failures
    - Tool calls have latency recorded
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get all tool calls for this run
        cursor.execute(
            """
            SELECT tool_name, status, latency_ms, error_text, http_status, attempt
            FROM tool_calls
            WHERE run_id = ?
            """,
            (run_id,)
        )
        tool_calls = cursor.fetchall()
        
        if not tool_calls:
            return {"score": 1.0, "reasons": ["No tool calls (evaluation skipped)"]}
        
        total_calls = len(tool_calls)
        failed_calls = sum(1 for tc in tool_calls if tc["status"] == "FAILED")
        error_rate = failed_calls / total_calls if total_calls > 0 else 0.0
        
        error_rate_threshold = 0.10  # 10%
        error_rate_pass = error_rate <= error_rate_threshold
        
        # Check retries recorded (use dictionary-style access for sqlite3.Row)
        retries_recorded = sum(1 for tc in tool_calls if "attempt" in tc.keys() and tc["attempt"] and tc["attempt"] > 1)
        
        # Check latency recorded (use dictionary-style access for sqlite3.Row)
        latency_recorded = sum(1 for tc in tool_calls if "latency_ms" in tc.keys() and tc["latency_ms"] is not None)
        latency_recorded_pct = latency_recorded / total_calls if total_calls > 0 else 0.0
        latency_recorded_pass = latency_recorded_pct >= 0.9  # 90% should have latency
        
        # Calculate score
        checks_passed = 0
        total_checks = 2
        
        if error_rate_pass:
            checks_passed += 1
        
        if latency_recorded_pass:
            checks_passed += 1
        
        score = checks_passed / total_checks
        
        reasons = [
            f"Error rate: {error_rate:.1%} (threshold: {error_rate_threshold:.1%}) - {'PASS' if error_rate_pass else 'FAIL'}",
            f"Retries recorded: {retries_recorded} tool calls",
            f"Latency recorded: {latency_recorded}/{total_calls} ({latency_recorded_pct:.1%}) - {'PASS' if latency_recorded_pass else 'FAIL'}"
        ]
    
    return {
        "score": score,
        "reasons": reasons,
        "thresholds": {"error_rate": error_rate_threshold},
        "metrics": {
            "error_rate": error_rate,
            "total_calls": total_calls,
            "failed_calls": failed_calls,
            "retries_recorded": retries_recorded,
            "latency_recorded_pct": latency_recorded_pct
        }
    }
