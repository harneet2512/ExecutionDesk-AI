"""Smoke test: full PAPER mode trade flow.

Exercises the complete trading chat flow:
  1. Health check -- verify backend is ready
  2. Capabilities check -- verify feature flags
  3. Create conversation
  4. Send "buy $10 of BTC" -- get confirmation card
  5. Confirm trade -- get run_id
  6. Poll run status until terminal
  7. Verify final state is COMPLETED or FAILED with structured data

Usage:
    python scripts/smoke_paper_flow.py [--base-url http://localhost:8000]

Exit code:
    0  all steps passed
    1  one or more steps failed
"""
import sys
import json
import time
import argparse
import requests

BASE_URL = "http://localhost:8000"
HEADERS = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}


def step(label: str):
    print(f"\n{'='*60}")
    print(f"[STEP] {label}")


def ok(msg: str):
    print(f"  [OK] {msg}")


def fail(msg: str):
    print(f"  [FAIL] {msg}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    failures = []

    # --- 1. Health check ---
    step("1. Health check")
    try:
        r = requests.get(f"{base}/health", timeout=10)
        data = r.json()
        if data.get("ok"):
            ok(f"Backend healthy: db_ready={data.get('db_ready')}, schema_ok={data.get('schema_ok')}")
        else:
            fail(f"Backend unhealthy: {json.dumps(data, indent=2)}")
            failures.append("health")
    except Exception as e:
        fail(f"Health check failed: {e}")
        failures.append("health")
        print("\nBackend may not be running. Start with:")
        print("  python -m uvicorn backend.api.main:app --port 8000")
        sys.exit(1)

    # --- 2. Capabilities ---
    step("2. Capabilities check")
    try:
        r = requests.get(f"{base}/api/v1/ops/capabilities", headers=HEADERS, timeout=10)
        caps = r.json()
        ok(f"live_trading={caps.get('live_trading_enabled')}, "
           f"db_ready={caps.get('db_ready')}, "
           f"news_provider={caps.get('news_provider_status')}")
    except Exception as e:
        fail(f"Capabilities fetch failed: {e}")
        failures.append("capabilities")

    # --- 3. Create conversation ---
    step("3. Create conversation")
    try:
        r = requests.post(
            f"{base}/api/v1/conversations",
            headers=HEADERS,
            json={"title": "Smoke test"},
            timeout=10,
        )
        conv = r.json()
        conv_id = conv.get("conversation_id")
        ok(f"Conversation created: {conv_id}")
    except Exception as e:
        fail(f"Create conversation failed: {e}")
        failures.append("create_conversation")
        conv_id = None

    # --- 4. Send trade command ---
    step("4. Send 'buy $10 of BTC'")
    confirmation_id = None
    try:
        r = requests.post(
            f"{base}/api/v1/chat/command",
            headers=HEADERS,
            json={"text": "buy $10 of BTC", "conversation_id": conv_id, "news_enabled": True},
            timeout=30,
        )
        data = r.json()
        intent = data.get("intent")
        confirmation_id = data.get("confirmation_id")

        if intent == "TRADE_EXECUTION" and confirmation_id:
            ok(f"Got confirmation card: intent={intent}, confirmation_id={confirmation_id}")
            # Check for financial insight
            if data.get("financial_insight"):
                insight = data["financial_insight"]
                ok(f"Financial insight present: confidence={insight.get('confidence')}, "
                   f"headlines={len(insight.get('sources', {}).get('headlines', []))}")
            else:
                ok("No financial insight returned (may be expected if news not ingested)")
        else:
            fail(f"Unexpected response: intent={intent}, status={data.get('status')}")
            failures.append("trade_command")
    except Exception as e:
        fail(f"Trade command failed: {e}")
        failures.append("trade_command")

    if not confirmation_id:
        fail("No confirmation_id to confirm. Stopping.")
        sys.exit(1)

    # --- 5. Confirm trade ---
    step("5. Confirm trade")
    run_id = None
    try:
        r = requests.post(
            f"{base}/api/v1/confirmations/{confirmation_id}/confirm",
            headers=HEADERS,
            json={},
            timeout=30,
        )
        data = r.json()
        run_id = data.get("run_id")
        status = data.get("status")

        if run_id and status == "EXECUTING":
            ok(f"Trade confirmed: run_id={run_id}, status={status}")
        else:
            fail(f"Unexpected confirm response: {json.dumps(data)}")
            failures.append("confirm")
    except Exception as e:
        fail(f"Confirm failed: {e}")
        failures.append("confirm")

    # --- 5b. Idempotency check ---
    step("5b. Idempotency: confirm same ID again")
    try:
        r = requests.post(
            f"{base}/api/v1/confirmations/{confirmation_id}/confirm",
            headers=HEADERS,
            json={},
            timeout=10,
        )
        data = r.json()
        if data.get("status") == "CONFIRMED" and data.get("run_id") == run_id:
            ok(f"Idempotent: second confirm returned existing run_id={run_id}")
        else:
            fail(f"Idempotency issue: {json.dumps(data)}")
            failures.append("idempotency")
    except Exception as e:
        fail(f"Idempotency check failed: {e}")
        failures.append("idempotency")

    if not run_id:
        fail("No run_id. Stopping.")
        sys.exit(1)

    # --- 6. Poll run status ---
    step("6. Poll run status until terminal")
    terminal_status = None
    max_polls = 60
    for i in range(max_polls):
        try:
            r = requests.get(
                f"{base}/api/v1/runs/status/{run_id}",
                headers=HEADERS,
                timeout=10,
            )
            data = r.json()
            status = data.get("status", "UNKNOWN")
            current_step = data.get("current_step", "")

            if status in ("COMPLETED", "FAILED"):
                terminal_status = status
                ok(f"Terminal status reached: {status} after {i+1} polls")
                break

            if i % 5 == 0:
                print(f"  ... status={status}, step={current_step} (poll {i+1}/{max_polls})")

            time.sleep(2)
        except Exception as e:
            print(f"  ... poll error: {e}")
            time.sleep(2)

    if not terminal_status:
        fail(f"Run did not reach terminal status in {max_polls * 2}s")
        failures.append("poll_timeout")

    # --- 7. Verify final state ---
    step("7. Verify run detail")
    try:
        r = requests.get(
            f"{base}/api/v1/runs/{run_id}",
            headers=HEADERS,
            timeout=10,
        )
        detail = r.json()
        run_data = detail.get("run", {})
        orders = detail.get("orders", [])

        ok(f"Run status: {run_data.get('status')}")
        ok(f"Execution mode: {run_data.get('execution_mode')}")
        ok(f"Orders: {len(orders)}")

        if terminal_status == "COMPLETED" and len(orders) > 0:
            order = orders[0]
            ok(f"Order: {order.get('symbol')} {order.get('side')} "
               f"qty={order.get('filled_qty')} avg_price={order.get('avg_fill_price')}")
    except Exception as e:
        fail(f"Run detail fetch failed: {e}")
        failures.append("run_detail")

    # --- Summary ---
    print(f"\n{'='*60}")
    if failures:
        print(f"[RESULT] FAILED -- {len(failures)} step(s) failed: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("[RESULT] ALL STEPS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
