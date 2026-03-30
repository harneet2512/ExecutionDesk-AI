#!/usr/bin/env python3
"""
verify_commands.py - End-to-end verification of Command A and Command B.

Usage:
    python scripts/verify_commands.py
    BACKEND_URL=http://localhost:9000 python scripts/verify_commands.py

Expects backend running on localhost:8000 (or BACKEND_URL env var).
"""
import os
import sys
import json
import time
import sqlite3
import requests

# Fix Windows encoding issues
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, errors='replace')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, errors='replace')

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
TENANT = "t_default"
HEADERS = {
    "Content-Type": "application/json",
    "X-Dev-Tenant": TENANT,
}
MAX_POLL = 120
POLL_INTERVAL = 2

pass_count = 0
fail_count = 0

# --- helpers -----------------------------------------------------------------
def safe_print(s):
    """Print with fallback for encoding issues."""
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('ascii', errors='replace').decode('ascii'))

def green(s): safe_print(f"\033[32m{s}\033[0m")
def red(s): safe_print(f"\033[31m{s}\033[0m")
def yellow(s): safe_print(f"\033[33m{s}\033[0m")
def bold(s): safe_print(f"\033[1m{s}\033[0m")

def mark_pass(msg):
    global pass_count
    pass_count += 1
    green(f"  PASS  {msg}")

def mark_fail(msg, detail=""):
    global fail_count
    fail_count += 1
    red(f"  FAIL  {msg}")
    if detail:
        safe_print(f"  -- response --\n{str(detail)[:500]}\n  --------------")

def api(method, path, body=None, timeout=30):
    url = BACKEND_URL + path
    try:
        if method == "GET":
            r = requests.get(url, headers=HEADERS, timeout=timeout)
        else:
            r = requests.post(url, headers=HEADERS, json=body or {}, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"error": f"Non-JSON response (HTTP {r.status_code}): {r.text[:200]}"}
    except Exception as e:
        return 0, {"error": str(e)}


# ─── Stage 0: Health check ──────────────────────────────────────────────
bold("\n=== Stage 0: Health check ===")
healthy = False
for i in range(15):
    code, data = api("GET", "/api/v1/ops/health")
    if code == 200 and data.get("status"):
        healthy = True
        break
    safe_print(f"  Waiting for backend... ({i+1}/15)")
    time.sleep(2)

if healthy:
    mark_pass("Backend healthy")
else:
    mark_fail("Backend not reachable", data)
    sys.exit(1)


# ─── Stage 1: Create conversation ───────────────────────────────────────
bold("\n=== Stage 1: Create conversation ===")
code, data = api("POST", "/api/v1/conversations", {"title": "Verify Commands Test"})
conv_id = data.get("conversation_id", "")
if conv_id:
    mark_pass(f"Conversation created: {conv_id}")
else:
    mark_fail("Failed to create conversation", data)
    sys.exit(1)


# ─── Stage 2: Command A — "Analyze my portfolio" ────────────────────────
bold("\n=== Stage 2: Command A — Analyze my portfolio ===")
code, data = api("POST", "/api/v1/chat/command", {
    "text": "Analyze my portfolio",
    "conversation_id": conv_id
})
cmd_a_status = data.get("status", "")
cmd_a_content = data.get("content", "")[:200]

if cmd_a_status == "COMPLETED":
    mark_pass(f"Command A returned status=COMPLETED")
    safe_print(f"  Content: {cmd_a_content}")
else:
    mark_fail(f"Command A unexpected status={cmd_a_status}", data)


# ─── Stage 3: Command B — propose trade ─────────────────────────────────
bold("\n=== Stage 3: Command B — Buy most profitable crypto (propose) ===")
code, data = api("POST", "/api/v1/chat/command", {
    "text": "Buy the most profitable crypto of the last 48 hours for $3",
    "conversation_id": conv_id
})
confirmation_id = data.get("confirmation_id", "")
cmd_b_intent = data.get("intent", "")
cmd_b_content = data.get("content", "")[:200]

pending_trade = data.get("pending_trade", {})
cmd_b_mode = pending_trade.get("mode", "")

if confirmation_id and cmd_b_intent == "TRADE_CONFIRMATION_PENDING":
    mark_pass(f"Trade proposed: confirmation_id={confirmation_id}")
    safe_print(f"  Content: {cmd_b_content}")
    safe_print(f"  Mode: {cmd_b_mode}")

    # Verify LIVE mode is default
    if cmd_b_mode == "LIVE":
        mark_pass("Default mode is LIVE")
    else:
        mark_fail(f"Expected mode=LIVE, got mode={cmd_b_mode}")
else:
    mark_fail(f"No confirmation_id or wrong intent ({cmd_b_intent})", data)
    red("\nCannot continue without confirmation_id.")
    sys.exit(1)


# ─── Stage 4: Confirm trade ─────────────────────────────────────────────
bold("\n=== Stage 4: Confirm trade via /confirmations/{id}/confirm ===")
code, data = api("POST", f"/api/v1/confirmations/{confirmation_id}/confirm", {})
run_id = data.get("run_id", "")
confirm_status = data.get("status", "")

if run_id and confirm_status == "EXECUTING":
    mark_pass(f"Trade confirmed: run_id={run_id}, status={confirm_status}")
else:
    mark_fail(f"Confirm failed: run_id={run_id}, status={confirm_status}", data)
    red("\nCannot continue without run_id.")
    sys.exit(1)


# ─── Stage 5: Poll run until completion ──────────────────────────────────
bold(f"\n=== Stage 5: Poll run {run_id} until completion ===")
elapsed = 0
final_status = ""
run_resp = {}
while elapsed < MAX_POLL:
    code, run_resp = api("GET", f"/api/v1/runs/{run_id}")
    run_data = run_resp.get("run", run_resp)
    final_status = run_data.get("status", "")

    if final_status in ("COMPLETED", "FAILED"):
        break
    safe_print(f"  status={final_status} ({elapsed}s/{MAX_POLL}s)")
    time.sleep(POLL_INTERVAL)
    elapsed += POLL_INTERVAL

if final_status == "COMPLETED":
    mark_pass(f"Run {run_id} completed successfully")
elif final_status == "FAILED":
    mark_fail(f"Run {run_id} failed", run_resp)
else:
    mark_fail(f"Run {run_id} timed out after {MAX_POLL}s (status={final_status})", run_resp)


# ─── Stage 6: Verify DB state ───────────────────────────────────────────
bold("\n=== Stage 6: Verify DB trade_confirmations row ===")
db_path = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "enterprise.db"))
db_status = ""
try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM trade_confirmations WHERE id = ? AND tenant_id = ?",
        (confirmation_id, TENANT)
    ).fetchone()
    conn.close()
    if row:
        db_status = dict(row).get("status", "")
        safe_print(f"  DB row: status={db_status}, mode={dict(row).get('mode','')}")
    else:
        db_status = "NOT_FOUND"
except Exception as e:
    safe_print(f"  DB error: {e}")
    db_status = "DB_ERROR"

if db_status == "CONFIRMED":
    mark_pass("DB confirmation status=CONFIRMED")
else:
    mark_fail(f"DB confirmation status={db_status} (expected CONFIRMED)")


# ─── Stage 6b: Test re-confirmation (idempotency) ───────────────────────
bold("\n=== Stage 6b: Test re-confirmation (idempotency) ===")
code, data = api("POST", f"/api/v1/confirmations/{confirmation_id}/confirm", {})
reconfirm_status = data.get("status", "")
if reconfirm_status == "CONFIRMED":
    mark_pass("Re-confirmation returns CONFIRMED (idempotent)")
else:
    mark_fail(f"Re-confirmation unexpected status={reconfirm_status}", data)

# ─── Stage 6c: Test tenant isolation ─────────────────────────────────────
bold("\n=== Stage 6c: Test tenant isolation ===")
wrong_tenant_headers = {**HEADERS, "X-Dev-Tenant": "t_wrong"}
try:
    r = requests.post(
        f"{BACKEND_URL}/api/v1/confirmations/{confirmation_id}/confirm",
        headers=wrong_tenant_headers,
        json={},
        timeout=10
    )
    if r.status_code == 404:
        mark_pass("Wrong tenant gets 404 (tenant isolation works)")
    else:
        mark_fail(f"Wrong tenant should get 404, got {r.status_code}")
except Exception as e:
    mark_fail(f"Tenant isolation test failed: {e}")

# ─── Stage 6d: Test invalid confirmation_id format ────────────────────────
bold("\n=== Stage 6d: Test invalid confirmation_id format ===")
code, data = api("POST", "/api/v1/confirmations/invalid_id/confirm", {})
if code in (400, 404):
    mark_pass(f"Invalid confirmation_id returns {code}")
else:
    mark_fail(f"Invalid confirmation_id should return 400 or 404, got {code}")

# ─── Stage 7: Check run has strategy evidence ────────────────────────────
bold("\n=== Stage 7: Verify run has strategy selection evidence ===")
selected_asset = ""
selected_return = None
if final_status == "COMPLETED":
    nodes = run_resp.get("nodes", [])
    strategy_nodes = [n for n in nodes if n.get("name") == "strategy" or n.get("node_type") == "strategy"]
    if strategy_nodes:
        node = strategy_nodes[0]
        outputs_raw = node.get("outputs_json", "{}")
        outputs = json.loads(outputs_raw) if isinstance(outputs_raw, str) else outputs_raw
        sr = outputs.get("strategy_result", {})
        selected_asset = sr.get("selected_symbol", "")
        score = sr.get("score", 0)
        lookback = sr.get("features_json", {}).get("lookback_hours", "?")
        if selected_asset:
            mark_pass(f"Strategy selected asset: {selected_asset} (score={score:.4f}, lookback={lookback}h)")
            selected_return = score
        else:
            mark_fail("No selected_symbol in strategy result", outputs)
    else:
        mark_fail("No strategy node found in run", [n.get("name") for n in nodes])
else:
    yellow("  Skipping (run did not complete)")


# ─── Stage 8: Verify research debug + financial_brief artifacts ──────────
bold("\n=== Stage 8: Verify research artifacts in DB ===")
try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Check universe_snapshot artifact (FDE requirement)
    row = conn.execute(
        "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'universe_snapshot'",
        (run_id,)
    ).fetchone()
    if row:
        snapshot = json.loads(dict(row)["artifact_json"])
        quote = snapshot.get("quote_currency_used", "?")
        products = len(snapshot.get("products_final", []))
        filters = snapshot.get("filters_applied", [])
        mark_pass(f"universe_snapshot: quote={quote}, products={products}, filters={filters}")
    else:
        mark_fail("No universe_snapshot artifact found in DB (FDE required)")
    
    # Check research_summary artifact (FDE requirement)
    row = conn.execute(
        "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'research_summary'",
        (run_id,)
    ).fetchone()
    if row:
        summary = json.loads(dict(row)["artifact_json"])
        window = summary.get("window_hours", 0)
        ranked = summary.get("ranked_assets_count", 0)
        api_stats = summary.get("api_call_stats", {})
        calls = api_stats.get("calls", 0)
        rate_429s = api_stats.get("rate_429s", 0)
        mark_pass(f"research_summary: window={window}h, ranked={ranked}, calls={calls}, 429s={rate_429s}")
    else:
        mark_fail("No research_summary artifact found in DB (FDE required)")
    
    # Check research_debug artifact
    row = conn.execute(
        "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'research_debug'",
        (run_id,)
    ).fetchone()
    if row:
        debug = json.loads(dict(row)["artifact_json"])
        universe_size = debug.get("universe_size", 0)
        dropped = debug.get("dropped_count", 0)
        successful = debug.get("successful_fetches", 0)
        gran = debug.get("granularity", "?")
        mark_pass(f"research_debug: universe={universe_size}, fetched={successful}, dropped={dropped}, granularity={gran}")
    else:
        mark_fail("No research_debug artifact found in DB")

    # Check financial_brief artifact
    row = conn.execute(
        "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'financial_brief'",
        (run_id,)
    ).fetchone()
    if row:
        brief = json.loads(dict(row)["artifact_json"])
        ranked = brief.get("ranked_assets", [])
        if ranked:
            top = ranked[0]
            mark_pass(f"financial_brief: top={top['symbol']} return={top['return_pct']:.2%} ({len(ranked)} ranked)")
        else:
            mark_fail("financial_brief has no ranked assets")
    else:
        mark_fail("No financial_brief artifact found in DB")

    # Check strategy_decision artifact
    row = conn.execute(
        "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'strategy_decision'",
        (run_id,)
    ).fetchone()
    if row:
        decision = json.loads(dict(row)["artifact_json"])
        mark_pass(f"strategy_decision: chosen={decision.get('chosen_asset')}, alternatives={len(decision.get('alternatives', []))}")
    else:
        mark_fail("No strategy_decision artifact found in DB")

    # Check for eval results
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM eval_results WHERE run_id = ?",
        (run_id,)
    ).fetchone()
    if row:
        eval_count = dict(row)["cnt"]
        if eval_count > 0:
            mark_pass(f"eval_results: {eval_count} evals recorded")
        else:
            mark_fail("No eval results recorded for run")
    
    # Check for hallucination_detection eval specifically
    row = conn.execute(
        "SELECT score, reasons_json FROM eval_results WHERE run_id = ? AND eval_name = 'hallucination_detection'",
        (run_id,)
    ).fetchone()
    if row:
        score = dict(row)["score"]
        reasons = json.loads(dict(row)["reasons_json"])
        status = "PASS" if score >= 0.8 else "WARN"
        mark_pass(f"hallucination_detection: score={score:.2f} ({status})")
    else:
        yellow("  SKIP  hallucination_detection: eval not yet run")
    
    # Check for agent_quality eval
    row = conn.execute(
        "SELECT score, reasons_json FROM eval_results WHERE run_id = ? AND eval_name = 'agent_quality'",
        (run_id,)
    ).fetchone()
    if row:
        score = dict(row)["score"]
        mark_pass(f"agent_quality: score={score:.2f}")
    else:
        yellow("  SKIP  agent_quality: eval not yet run")

    conn.close()
except Exception as e:
    mark_fail(f"Artifact verification error: {e}")


# --- Stage 9: Observability check ------------------------------------------
bold("\n=== Stage 9: Observability check ===")
try:
    # Check Prometheus metrics endpoint
    code, data = api("GET", "/api/v1/metrics")
    if code == 200:
        # Check for expected metrics in response text
        if isinstance(data, dict) and "error" not in data:
            mark_pass("Prometheus /metrics endpoint accessible")
        elif isinstance(data, str):
            if "run_success_total" in data or "node_latency" in data:
                mark_pass("Prometheus /metrics returns proper format")
            else:
                yellow("  SKIP  Prometheus metrics may not have data yet")
        else:
            mark_pass("Prometheus /metrics endpoint returns 200")
    else:
        mark_fail(f"Prometheus /metrics returned HTTP {code}")
    
    # Check JSON metrics endpoint
    code, data = api("GET", "/api/v1/metrics/json")
    if code == 200 and isinstance(data, dict):
        run_counts = data.get("run_counts", {})
        mark_pass(f"JSON /metrics: run_counts={run_counts}")
    else:
        mark_fail("JSON /metrics endpoint failed")
except Exception as e:
    mark_fail(f"Observability check error: {e}")


# --- Stage 10: Holdings query verification -----------------------------------
bold("\n=== Stage 10: Holdings query ('How much BTC do I own?') ===")
holdings_query = "How much BTC do I own?"
try:
    code, data = api("POST", "/api/v1/chat/command", {
        "text": holdings_query,
        "conversation_id": conv_id
    }, timeout=60)
    
    if code == 200:
        intent = data.get("intent", "")
        status = data.get("status", "")
        content = data.get("content", "")
        queried_asset = data.get("queried_asset")
        portfolio_brief = data.get("portfolio_brief", {})
        
        # Check intent is correct
        if intent == "PORTFOLIO_ANALYSIS":
            mark_pass(f"Intent correctly classified as PORTFOLIO_ANALYSIS")
        else:
            mark_fail(f"Wrong intent: expected PORTFOLIO_ANALYSIS, got {intent}")
        
        # Check queried_asset is extracted
        if queried_asset == "BTC":
            mark_pass(f"Queried asset correctly extracted: {queried_asset}")
        else:
            yellow(f"  INFO  queried_asset={queried_asset} (expected BTC)")
        
        # Check response mentions BTC
        if "BTC" in content or "btc" in content.lower():
            mark_pass("Response mentions BTC")
        else:
            mark_fail("Response does not mention BTC", content[:200])
        
        # Check for quantity in response
        if any(c.isdigit() for c in content):
            mark_pass("Response contains numeric quantity")
        else:
            mark_fail("Response has no numeric quantity")
        
        # Check portfolio_brief has holdings
        holdings = portfolio_brief.get("holdings", [])
        evidence_refs = portfolio_brief.get("evidence_refs", {})
        mode = portfolio_brief.get("mode", "UNKNOWN")
        
        safe_print(f"  Mode: {mode}")
        safe_print(f"  Holdings count: {len(holdings)}")
        safe_print(f"  Evidence refs: {bool(evidence_refs)}")
        
        # Check for BTC in holdings (or explicit zero message)
        btc_holding = next((h for h in holdings if h.get("asset_symbol") == "BTC"), None)
        if btc_holding:
            btc_qty = btc_holding.get("qty", 0)
            btc_usd = btc_holding.get("usd_value", 0)
            mark_pass(f"BTC holding found: {btc_qty} (~${btc_usd:.2f})")
        elif "0" in content and ("do not" in content.lower() or "don't" in content.lower()):
            mark_pass("Zero BTC balance explicitly stated")
        else:
            yellow("  INFO  No BTC in holdings (account may have 0 BTC)")
        
        # Check for evidence refs
        if evidence_refs.get("accounts_call_id"):
            mark_pass(f"Evidence ref: accounts_call_id present")
        else:
            yellow("  SKIP  No accounts_call_id in evidence_refs")
    else:
        mark_fail(f"Holdings query failed: HTTP {code}", data)
    
    # Check notification_events table for this action
    try:
        conn = sqlite3.connect("enterprise.db")
        conn.row_factory = sqlite3.Row
        
        # Look for notification event (sent or skipped)
        row = conn.execute(
            """SELECT status, action, payload_redacted 
               FROM notification_events 
               WHERE action LIKE '%portfolio%' 
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        
        if row:
            notif_status = dict(row)["status"]
            notif_action = dict(row)["action"]
            payload = dict(row).get("payload_redacted", "{}")
            
            if notif_status in ("sent", "skipped"):
                mark_pass(f"Notification event recorded: {notif_status} ({notif_action})")
                if notif_status == "skipped":
                    try:
                        reason = json.loads(payload).get("reason", "unknown")
                        safe_print(f"  Skipped reason: {reason}")
                    except:
                        pass
            else:
                yellow(f"  INFO  Notification status: {notif_status}")
        else:
            yellow("  SKIP  No notification_events found for portfolio")
        
        conn.close()
    except Exception as e:
        yellow(f"  SKIP  Could not check notification_events: {e}")

except Exception as e:
    mark_fail(f"Holdings query error: {e}")


# --- Summary -----------------------------------------------------------------
bold("\n" + "=" * 50)
safe_print(f"  confirmation_id : {confirmation_id}")
safe_print(f"  run_id          : {run_id or 'N/A'}")
safe_print(f"  selected_asset  : {selected_asset or 'N/A'}")
safe_print(f"  selected_return : {f'{selected_return:.4f}' if selected_return is not None else 'N/A'}")
safe_print(f"  run_status      : {final_status or 'N/A'}")
bold("=" * 50)
green(f"  PASSED: {pass_count}")
if fail_count > 0:
    red(f"  FAILED: {fail_count}")
else:
    green(f"  FAILED: 0")
bold("=" * 50)

sys.exit(1 if fail_count > 0 else 0)
