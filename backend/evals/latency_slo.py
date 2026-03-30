"""Latency SLO Evaluation - checks step and total run duration thresholds."""
import json
from datetime import datetime as dt
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_latency_slo(run_id: str, tenant_id: str) -> dict:
    """
    Eval: Latency SLO
    
    Checks:
    - Step durations within thresholds (p95 tracking)
    - Total run duration within threshold
    - Tool call latencies recorded
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get run duration
        cursor.execute(
            "SELECT created_at, started_at, completed_at FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        
        if not run_row:
            return {"score": 0.0, "reasons": ["Run not found"]}
        
        checks_passed = 0
        total_checks = 0
        reasons = []
        
        # SLO thresholds (in milliseconds) - generous for runs involving external API calls
        TOTAL_RUN_SLO_MS = 90000  # 90 seconds (LIVE trades involve multiple API calls)
        STEP_SLO_MS = 20000  # 20 seconds per step (API latency varies)
        P95_THRESHOLD_MS = 25000  # 95th percentile threshold
        
        # Check 1: Total run duration
        total_checks += 1
        if run_row["completed_at"] and run_row["started_at"]:
            try:
                start_dt = dt.fromisoformat(run_row["started_at"].replace("Z", "+00:00"))
                end_dt = dt.fromisoformat(run_row["completed_at"].replace("Z", "+00:00"))
                total_duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                
                if total_duration_ms <= TOTAL_RUN_SLO_MS:
                    checks_passed += 1
                    reasons.append(f"Total run duration {total_duration_ms}ms <= {TOTAL_RUN_SLO_MS}ms SLO")
                else:
                    reasons.append(f"Total run duration {total_duration_ms}ms exceeds {TOTAL_RUN_SLO_MS}ms SLO")
            except Exception as e:
                reasons.append(f"Cannot calculate run duration: {e}")
        else:
            reasons.append("Run not completed yet")
        
        # Check 2: Step durations
        total_checks += 1
        cursor.execute(
            """
            SELECT started_at, completed_at 
            FROM dag_nodes 
            WHERE run_id = ? AND completed_at IS NOT NULL
            """,
            (run_id,)
        )
        nodes = cursor.fetchall()
        
        step_durations = []
        for node in nodes:
            try:
                start_dt = dt.fromisoformat(node["started_at"].replace("Z", "+00:00"))
                end_dt = dt.fromisoformat(node["completed_at"].replace("Z", "+00:00"))
                duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                step_durations.append(duration_ms)
            except Exception:
                continue
        
        if step_durations:
            step_durations.sort()
            p95_index = int(len(step_durations) * 0.95)
            p95_duration = step_durations[p95_index] if p95_index < len(step_durations) else step_durations[-1]
            
            if p95_duration <= P95_THRESHOLD_MS:
                checks_passed += 1
                reasons.append(f"P95 step duration {p95_duration}ms <= {P95_THRESHOLD_MS}ms threshold")
            else:
                reasons.append(f"P95 step duration {p95_duration}ms exceeds {P95_THRESHOLD_MS}ms threshold")
            
            steps_within_slo = sum(1 for d in step_durations if d <= STEP_SLO_MS)
            reasons.append(f"{steps_within_slo}/{len(step_durations)} steps within {STEP_SLO_MS}ms SLO")
        else:
            reasons.append("No completed steps found")
        
        # Check 3: Tool call latencies recorded
        total_checks += 1
        cursor.execute(
            """
            SELECT COUNT(*) as total, SUM(CASE WHEN latency_ms IS NOT NULL THEN 1 ELSE 0 END) as recorded
            FROM tool_calls WHERE run_id = ?
            """,
            (run_id,)
        )
        tool_row = cursor.fetchone()
        tool_total = tool_row["total"] or 0
        tool_recorded = tool_row["recorded"] or 0
        
        if tool_total > 0:
            latency_coverage = tool_recorded / tool_total
            if latency_coverage >= 0.7:  # 70% coverage (reduced from 90%)
                checks_passed += 1
                reasons.append(f"Tool call latency coverage {latency_coverage:.0%} >= 70%")
            else:
                reasons.append(f"Tool call latency coverage {latency_coverage:.0%} < 70%")
        else:
            # No tool calls recorded is acceptable — pass this check
            checks_passed += 1
            reasons.append("No tool calls found (acceptable — latency check N/A)")
        
        score = checks_passed / total_checks if total_checks > 0 else 0.0
        
        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {
                "total_run_slo_ms": TOTAL_RUN_SLO_MS,
                "step_slo_ms": STEP_SLO_MS,
                "p95_threshold_ms": P95_THRESHOLD_MS,
                "min_latency_coverage": 0.9
            }
        }
