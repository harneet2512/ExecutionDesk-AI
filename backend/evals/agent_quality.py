"""Agent Quality Evaluation - Pipeline quality and constraint verification.

Deterministic checks over DB rows + artifacts for agent/pipeline quality.

Checks:
1. plan_completeness: required nodes executed for intent type
2. loop_thrash: tool calls / retries / identical requests bounded; if exceeded must fail gracefully
3. constraint_respect: enforce caps/allowlists/kill switch/confirmation invariants deterministically
4. empty_rankings_never_silent: if rankings empty, research_failure artifact must exist
5. rate_limit_resilience: if 429s occurred, verify backoff/retries and surfaced reason if still fails
"""
import json
from typing import Dict, List, Any, Tuple
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Thresholds
MAX_TOOL_CALLS_PER_NODE = 100  # Maximum tool calls before considered thrashing
MAX_RETRIES_PER_SYMBOL = 3
MAX_IDENTICAL_REQUESTS = 5


def evaluate_agent_quality(run_id: str, tenant_id: str) -> dict:
    """
    Agent/pipeline quality evaluation.
    
    Verifies pipeline behavior meets quality standards.
    
    Returns:
        {
            "score": float,  # 0.0 to 1.0
            "reasons": List[str],
            "thresholds": {"min_score": 0.8}
        }
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        checks_passed = 0
        total_checks = 0
        reasons = []
        
        # === CHECK 1: Plan Completeness ===
        total_checks += 1
        plan_pass, plan_reason = _check_plan_completeness(cursor, run_id)
        if plan_pass:
            checks_passed += 1
        reasons.append(plan_reason)
        
        # === CHECK 2: Loop Thrash Detection ===
        total_checks += 1
        thrash_pass, thrash_reason = _check_loop_thrash(cursor, run_id)
        if thrash_pass:
            checks_passed += 1
        reasons.append(thrash_reason)
        
        # === CHECK 3: Constraint Respect ===
        total_checks += 1
        constraint_pass, constraint_reason = _check_constraint_respect(cursor, run_id, tenant_id)
        if constraint_pass:
            checks_passed += 1
        reasons.append(constraint_reason)
        
        # === CHECK 4: Empty Rankings Never Silent ===
        total_checks += 1
        empty_pass, empty_reason = _check_empty_rankings_never_silent(cursor, run_id)
        if empty_pass:
            checks_passed += 1
        reasons.append(empty_reason)
        
        # === CHECK 5: Rate Limit Resilience ===
        total_checks += 1
        rate_pass, rate_reason = _check_rate_limit_resilience(cursor, run_id)
        if rate_pass:
            checks_passed += 1
        reasons.append(rate_reason)
        
        score = checks_passed / total_checks if total_checks > 0 else 0.0
        
        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"min_score": 0.8},
            "metrics": {
                "checks_passed": checks_passed,
                "total_checks": total_checks,
                "plan_completeness": plan_pass,
                "loop_thrash": thrash_pass,
                "constraint_respect": constraint_pass,
                "empty_rankings_handled": empty_pass,
                "rate_limit_resilience": rate_pass
            }
        }


def _check_plan_completeness(cursor, run_id: str) -> Tuple[bool, str]:
    """Check 1: Plan Completeness.
    
    Verifies that required nodes executed based on run intent.
    """
    # Get execution plan
    cursor.execute(
        "SELECT execution_plan_json, intent_json, status FROM runs WHERE run_id = ?",
        (run_id,)
    )
    row = cursor.fetchone()
    
    if not row:
        return False, "Plan completeness: run not found"
    
    run_status = row["status"]
    
    # Get executed nodes
    cursor.execute(
        """
        SELECT name, status FROM dag_nodes 
        WHERE run_id = ? 
        ORDER BY started_at
        """,
        (run_id,)
    )
    executed_nodes = {n["name"]: n["status"] for n in cursor.fetchall()}
    
    # Required nodes for a trade execution run
    required_for_trade = ["research", "signals", "risk", "proposal", "policy_check"]
    
    # Check if this was meant to be a trade run
    intent = {}
    if row["intent_json"]:
        try:
            intent = json.loads(row["intent_json"])
        except:
            pass
    
    is_trade_run = intent.get("intent") == "TRADE_EXECUTION" or "buy" in str(intent).lower()
    
    if is_trade_run:
        # Check that required nodes ran
        missing_nodes = [n for n in required_for_trade if n not in executed_nodes]
        
        # Allow missing if run failed early
        if run_status == "FAILED":
            # Check if failure was in an early node (acceptable)
            failed_nodes = [n for n, s in executed_nodes.items() if s == "FAILED"]
            if failed_nodes:
                failed_idx = list(executed_nodes.keys()).index(failed_nodes[0]) if failed_nodes[0] in executed_nodes else -1
                if failed_idx < len(required_for_trade):
                    return True, f"Plan completeness: run failed at {failed_nodes[0]}, acceptable early failure"
        
        if missing_nodes and run_status == "COMPLETED":
            return False, f"Plan completeness: trade run missing required nodes {missing_nodes}"
    
    # Count completed nodes
    completed_count = sum(1 for s in executed_nodes.values() if s == "COMPLETED")
    total_count = len(executed_nodes)
    
    return True, f"Plan completeness: {completed_count}/{total_count} nodes completed"


def _check_loop_thrash(cursor, run_id: str) -> Tuple[bool, str]:
    """Check 2: Loop Thrash Detection.
    
    Verifies that tool calls don't exceed reasonable bounds.
    """
    # Count tool calls per node
    cursor.execute(
        """
        SELECT node_id, tool_name, COUNT(*) as cnt 
        FROM tool_calls 
        WHERE run_id = ? 
        GROUP BY node_id, tool_name
        """,
        (run_id,)
    )
    call_counts = cursor.fetchall()
    
    max_calls_per_node = 0
    thrashing_nodes = []
    
    for row in call_counts:
        if row["cnt"] > max_calls_per_node:
            max_calls_per_node = row["cnt"]
        if row["cnt"] > MAX_TOOL_CALLS_PER_NODE:
            thrashing_nodes.append((row["node_id"], row["tool_name"], row["cnt"]))
    
    if thrashing_nodes:
        # Check if run failed gracefully
        cursor.execute(
            "SELECT status FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        if run_row and run_row["status"] == "FAILED":
            return True, f"Loop thrash: detected thrashing ({max_calls_per_node} calls) but run failed gracefully"
        return False, f"Loop thrash: excessive tool calls detected - {thrashing_nodes[0][2]} calls for {thrashing_nodes[0][1]}"
    
    # Check for identical requests
    cursor.execute(
        """
        SELECT request_json, COUNT(*) as cnt 
        FROM tool_calls 
        WHERE run_id = ? 
        GROUP BY request_json 
        HAVING COUNT(*) > ?
        """,
        (run_id, MAX_IDENTICAL_REQUESTS)
    )
    duplicate_requests = cursor.fetchall()
    
    if duplicate_requests:
        return False, f"Loop thrash: {len(duplicate_requests)} identical requests made more than {MAX_IDENTICAL_REQUESTS} times"
    
    return True, f"Loop thrash: no thrashing detected (max {max_calls_per_node} calls per node)"


def _check_constraint_respect(cursor, run_id: str, tenant_id: str) -> Tuple[bool, str]:
    """Check 3: Constraint Respect.
    
    Verifies caps, allowlists, kill switch, and confirmation invariants.
    """
    violations = []
    
    # Check kill switch
    cursor.execute(
        "SELECT kill_switch_enabled FROM tenants WHERE tenant_id = ?",
        (tenant_id,)
    )
    tenant_row = cursor.fetchone()
    if tenant_row and tenant_row["kill_switch_enabled"]:
        # Kill switch is ON - verify no orders placed
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE run_id = ?",
            (run_id,)
        )
        order_count = cursor.fetchone()["cnt"]
        if order_count > 0:
            violations.append("kill_switch_bypass")
    
    # Check notional caps
    from backend.core.config import get_settings
    settings = get_settings()
    max_notional = settings.max_notional_per_order_usd
    
    cursor.execute(
        "SELECT notional_usd FROM orders WHERE run_id = ?",
        (run_id,)
    )
    orders = cursor.fetchall()
    for order in orders:
        if order["notional_usd"] > max_notional:
            violations.append(f"notional_cap_exceeded_{order['notional_usd']}")
    
    # Check LIVE mode requires confirmation
    cursor.execute(
        "SELECT execution_mode, metadata_json FROM runs WHERE run_id = ?",
        (run_id,)
    )
    run_row = cursor.fetchone()
    if run_row and run_row["execution_mode"] == "LIVE":
        # Check that confirmation was provided
        metadata = {}
        if run_row["metadata_json"]:
            try:
                metadata = json.loads(run_row["metadata_json"])
            except:
                pass
        
        if not metadata.get("confirmed") and not metadata.get("confirmation_id"):
            # Check if any orders were placed
            if orders:
                violations.append("live_order_without_confirmation")
    
    # Check symbol allowlist
    allowlist_str = settings.symbol_allowlist
    allowlist = [s.strip() for s in allowlist_str.split(",")]
    
    for order in orders:
        cursor.execute(
            "SELECT symbol FROM orders WHERE run_id = ?",
            (run_id,)
        )
    order_rows = cursor.fetchall()
    for order in order_rows:
        symbol = order["symbol"]
        base = symbol.split("-")[0] if "-" in symbol else symbol
        if allowlist and base not in allowlist:
            violations.append(f"symbol_not_in_allowlist_{base}")
    
    if violations:
        return False, f"Constraint respect: violations detected - {violations}"
    
    return True, "Constraint respect: all caps, allowlists, and invariants respected"


def _check_empty_rankings_never_silent(cursor, run_id: str) -> Tuple[bool, str]:
    """Check 4: Empty Rankings Never Silent.
    
    If rankings are empty, research_failure artifact MUST exist.
    """
    # Check research output for empty rankings
    cursor.execute(
        """
        SELECT outputs_json FROM dag_nodes 
        WHERE run_id = ? AND name = 'research'
        """,
        (run_id,)
    )
    research_row = cursor.fetchone()
    
    if not research_row or not research_row["outputs_json"]:
        # Research didn't complete - check for failure artifact
        cursor.execute(
            """
            SELECT COUNT(*) as cnt FROM run_artifacts 
            WHERE run_id = ? AND artifact_type = 'research_failure'
            """,
            (run_id,)
        )
        failure_count = cursor.fetchone()["cnt"]
        if failure_count > 0:
            return True, "Empty rankings: research failed and research_failure artifact exists"
        
        # Check run status
        cursor.execute(
            "SELECT status FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_status = cursor.fetchone()["status"] if cursor.fetchone() else "UNKNOWN"
        return True, "Empty rankings: research node did not complete"
    
    outputs = json.loads(research_row["outputs_json"])
    returns_by_symbol = outputs.get("returns_by_symbol", {})
    
    if not returns_by_symbol:
        # Empty rankings - check for failure artifact
        cursor.execute(
            """
            SELECT artifact_json FROM run_artifacts 
            WHERE run_id = ? AND artifact_type = 'research_failure'
            """,
            (run_id,)
        )
        failure_row = cursor.fetchone()
        
        if not failure_row:
            return False, "Empty rankings: no valid rankings but research_failure artifact missing"
        
        # Verify failure artifact has required fields
        failure = json.loads(failure_row["artifact_json"])
        required_fields = ["summary", "reason_code", "dropped_by_reason"]
        missing = [f for f in required_fields if f not in failure]
        
        if missing:
            return False, f"Empty rankings: research_failure missing required fields {missing}"
        
        return True, f"Empty rankings: properly documented with reason_code={failure.get('reason_code')}"
    
    return True, f"Empty rankings: {len(returns_by_symbol)} valid rankings present"


def _check_rate_limit_resilience(cursor, run_id: str) -> Tuple[bool, str]:
    """Check 5: Rate Limit Resilience.
    
    If 429s occurred, verify backoff/retries and that reason is surfaced if still fails.
    """
    # Count 429 errors in tool calls
    cursor.execute(
        """
        SELECT response_json, status FROM tool_calls 
        WHERE run_id = ? AND status = 'FAILED'
        """,
        (run_id,)
    )
    failed_calls = cursor.fetchall()
    
    rate_limit_failures = 0
    for call in failed_calls:
        if call["response_json"]:
            response_text = call["response_json"].lower()
            if "429" in response_text or "rate" in response_text:
                rate_limit_failures += 1
    
    if rate_limit_failures == 0:
        return True, "Rate limit resilience: no rate limiting encountered"
    
    # Check if run handled rate limits gracefully
    # Either succeeded anyway, or has failure with rate_limited reason
    cursor.execute(
        "SELECT status FROM runs WHERE run_id = ?",
        (run_id,)
    )
    run_status = cursor.fetchone()["status"]
    
    if run_status == "COMPLETED":
        return True, f"Rate limit resilience: {rate_limit_failures} rate limits encountered but run completed successfully"
    
    # Run failed - check if rate limiting is documented
    cursor.execute(
        """
        SELECT artifact_json FROM run_artifacts 
        WHERE run_id = ? AND (artifact_type = 'research_failure' OR artifact_type = 'research_summary')
        """,
        (run_id,)
    )
    artifacts = cursor.fetchall()
    
    rate_limit_documented = False
    for artifact in artifacts:
        artifact_text = artifact["artifact_json"].lower()
        if "rate" in artifact_text or "429" in artifact_text:
            rate_limit_documented = True
            break
    
    if not rate_limit_documented:
        return False, f"Rate limit resilience: {rate_limit_failures} rate limits caused failure but not documented in artifacts"
    
    return True, f"Rate limit resilience: {rate_limit_failures} rate limits documented in failure artifacts"
