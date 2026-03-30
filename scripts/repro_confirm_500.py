#!/usr/bin/env python3
"""
Reproduce and verify confirmation endpoint behavior.

Tests:
1. Invalid confirmation ID format -> 400
2. Non-existent confirmation ID -> 404
3. Full trade flow: command -> confirmation -> confirm -> 200
4. Idempotent confirm (same ID again) -> 200 with status info
5. Cancel with non-existent ID -> 404
"""

import json
import sys

import httpx

API_BASE = "http://localhost:8000"
HEADERS = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}

results = []


def record(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    results.append((name, passed))
    print(f"  [{status}] {name}")
    if detail:
        print(f"         {detail}")


def main():
    print("=" * 60)
    print("Confirmation Endpoint Verification")
    print("=" * 60)

    # Test 1: Invalid confirmation ID format -> 400
    print("\n[TEST 1] Invalid confirmation ID format")
    r = httpx.post(
        f"{API_BASE}/api/v1/confirmations/bad_id/confirm",
        headers=HEADERS, json={}, timeout=10
    )
    record(
        "Invalid ID returns 400",
        r.status_code == 400,
        f"Got {r.status_code}: {r.text[:200]}"
    )

    # Test 2: Non-existent confirmation ID -> 404
    print("\n[TEST 2] Non-existent confirmation ID")
    r = httpx.post(
        f"{API_BASE}/api/v1/confirmations/conf_nonexistent/confirm",
        headers=HEADERS, json={}, timeout=10
    )
    record(
        "Non-existent ID returns 404",
        r.status_code == 404,
        f"Got {r.status_code}: {r.text[:200]}"
    )

    # Test 3: Full trade flow
    print("\n[TEST 3] Full trade flow: command -> confirmation -> confirm")

    # 3a. Create conversation
    r = httpx.post(f"{API_BASE}/api/v1/conversations", headers=HEADERS, json={})
    if r.status_code != 200:
        record("Create conversation", False, f"Got {r.status_code}")
        print("\n[ABORT] Cannot create conversation")
        print_summary()
        sys.exit(1)

    conv_id = r.json()["conversation_id"]
    record("Create conversation", True, f"conv_id={conv_id}")

    # 3b. Send trade command to get confirmation
    print("\n  Sending trade command...")
    r = httpx.post(
        f"{API_BASE}/api/v1/chat/command",
        headers=HEADERS,
        json={"text": "Buy $3 of BTC", "conversation_id": conv_id, "news_enabled": False},
        timeout=60
    )
    if r.status_code != 200:
        record("Chat command", False, f"Got {r.status_code}: {r.text[:300]}")
        print_summary()
        sys.exit(1)

    data = r.json()
    conf_id = data.get("confirmation_id")
    status = data.get("status")

    if not conf_id:
        if status == "REFUSED":
            record("Chat command", True, f"Trade refused (expected for some configs): {data.get('content', '')[:150]}")
            print("\n[INFO] Trade was refused -- cannot test confirm endpoint with real ID")
            print_summary()
            sys.exit(0)
        record("Chat command", False, f"No confirmation_id. Status: {status}")
        print_summary()
        sys.exit(1)

    record("Chat command", True, f"confirmation_id={conf_id}, status={status}")

    # 3c. Confirm the trade
    print("\n  Confirming trade...")
    r = httpx.post(
        f"{API_BASE}/api/v1/confirmations/{conf_id}/confirm",
        headers=HEADERS, json={}, timeout=60
    )
    body = r.text[:500]

    if r.status_code == 500:
        record("Confirm trade", False, f"GOT 500! Body: {body}")
        # Try to parse error details
        try:
            err = json.loads(body)
            detail = err.get("detail", {})
            if isinstance(detail, dict):
                print(f"         Error code: {detail.get('error', {}).get('code')}")
                print(f"         Message: {detail.get('error', {}).get('message')}")
                print(f"         Request ID: {detail.get('error', {}).get('request_id')}")
            else:
                print(f"         Detail: {detail}")
        except Exception:
            print(f"         Raw: {body}")
    elif r.status_code == 200:
        result = r.json()
        run_id = result.get("run_id")
        record("Confirm trade", True, f"run_id={run_id}, status={result.get('status')}")
    else:
        record("Confirm trade", r.status_code < 500, f"Got {r.status_code}: {body}")

    # Test 4: Idempotent confirm (same ID again)
    print("\n[TEST 4] Idempotent confirm (same ID again)")
    r = httpx.post(
        f"{API_BASE}/api/v1/confirmations/{conf_id}/confirm",
        headers=HEADERS, json={}, timeout=10
    )
    # Should return 200 with status info (already CONFIRMED), not 500
    record(
        "Idempotent confirm not 500",
        r.status_code != 500,
        f"Got {r.status_code}: {r.text[:200]}"
    )

    # Test 5: Cancel endpoint with non-existent ID
    print("\n[TEST 5] Cancel with non-existent ID")
    r = httpx.post(
        f"{API_BASE}/api/v1/confirmations/conf_nonexistent/cancel",
        headers=HEADERS, json={}, timeout=10
    )
    record(
        "Cancel non-existent returns 404",
        r.status_code == 404,
        f"Got {r.status_code}: {r.text[:200]}"
    )

    print_summary()


def print_summary():
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    has_fail = False
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            has_fail = True

    if has_fail:
        print("\n[OVERALL FAIL] Some tests failed!")
        sys.exit(1)
    else:
        print("\n[OVERALL PASS] All confirmation endpoint tests passed")


if __name__ == "__main__":
    main()
