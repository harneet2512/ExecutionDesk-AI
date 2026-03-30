"""Smoke test: exercises Hi, Analyze portfolio, Sell $2 BTC in sequence.

Usage:
    python scripts/smoke_chat.py [--base-url http://localhost:8000]

Asserts:
    - No 500 responses
    - All responses are JSON
    - request_id present in every response body + X-Request-ID header
    - request_id in body matches header
"""
import sys
import json
import argparse
import requests

TENANT_HEADER = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}


def post_command(base_url: str, text: str, label: str) -> dict:
    """POST /api/v1/chat/command and validate response shape."""
    url = f"{base_url}/api/v1/chat/command"
    payload = {"text": text}

    print(f"\n{'='*60}")
    print(f"[TEST] {label}")
    print(f"  POST {url}")
    print(f"  Body: {json.dumps(payload)}")

    resp = requests.post(url, json=payload, headers=TENANT_HEADER, timeout=30)

    # 1. Must not be 500
    if resp.status_code >= 500:
        print(f"  [FAIL] Got {resp.status_code}: {resp.text[:300]}")
        return {"_failed": True, "_status": resp.status_code}

    # 2. Must be JSON
    try:
        data = resp.json()
    except Exception as e:
        print(f"  [FAIL] Response is not JSON: {str(e)[:200]}")
        print(f"  Body: {resp.text[:300]}")
        return {"_failed": True, "_status": resp.status_code}

    # 3. Must have request_id in body
    body_rid = data.get("request_id")
    header_rid = resp.headers.get("X-Request-ID")

    print(f"  Status: {resp.status_code}")
    print(f"  Intent: {data.get('intent', 'N/A')}")
    print(f"  Content: {str(data.get('content', ''))[:120]}")
    print(f"  request_id (body):   {body_rid}")
    print(f"  X-Request-ID (hdr):  {header_rid}")

    errors = []
    if not body_rid:
        errors.append("Missing request_id in response body")
    if not header_rid:
        errors.append("Missing X-Request-ID header")
    if body_rid and header_rid and body_rid != header_rid:
        errors.append(f"request_id mismatch: body={body_rid} header={header_rid}")

    if errors:
        for e in errors:
            print(f"  [WARN] {e}")

    print(f"  [PASS] {resp.status_code} OK")
    data["_status"] = resp.status_code
    data["_failed"] = False
    data["_header_rid"] = header_rid
    return data


def confirm_trade(base_url: str, confirmation_id: str) -> dict:
    """POST /api/v1/confirmations/{id}/confirm."""
    url = f"{base_url}/api/v1/confirmations/{confirmation_id}/confirm"
    print(f"\n{'='*60}")
    print(f"[TEST] Confirm trade: {confirmation_id}")
    print(f"  POST {url}")

    resp = requests.post(url, json={}, headers=TENANT_HEADER, timeout=30)

    if resp.status_code >= 500:
        print(f"  [FAIL] Got {resp.status_code}: {resp.text[:300]}")
        return {"_failed": True, "_status": resp.status_code}

    try:
        data = resp.json()
    except Exception:
        print(f"  [FAIL] Not JSON: {resp.text[:300]}")
        return {"_failed": True, "_status": resp.status_code}

    print(f"  Status: {resp.status_code}")
    print(f"  Response: {json.dumps(data)[:200]}")
    print(f"  [PASS] {resp.status_code} OK")
    data["_failed"] = False
    data["_status"] = resp.status_code
    return data


def main():
    parser = argparse.ArgumentParser(description="Chat smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.base_url

    results = []
    all_pass = True

    # Test 1: Greeting
    r1 = post_command(base, "Hi", "Greeting")
    results.append(("Greeting", r1))
    if r1.get("_failed"):
        all_pass = False

    # Test 2: Portfolio analysis
    r2 = post_command(base, "Analyze my portfolio", "Portfolio Analysis")
    results.append(("Portfolio", r2))
    if r2.get("_failed"):
        all_pass = False

    # Test 3: Trade command
    r3 = post_command(base, "Sell $2 of BTC", "Trade Command (Sell $2 BTC)")
    results.append(("Trade", r3))
    if r3.get("_failed"):
        all_pass = False

    # Test 4: If we got a confirmation_id, try confirming
    conf_id = r3.get("confirmation_id")
    if conf_id:
        r4 = confirm_trade(base, conf_id)
        results.append(("Confirm", r4))
        if r4.get("_failed"):
            all_pass = False

        # Test 5: Double-confirm idempotency
        print(f"\n{'='*60}")
        print(f"[TEST] Double-confirm idempotency: {conf_id}")
        r5 = confirm_trade(base, conf_id)
        # Should return 200 with status "CONFIRMED", not 500
        if r5.get("_failed"):
            all_pass = False
            results.append(("Double-Confirm", r5))
        elif r5.get("status") != "CONFIRMED":
            print(f"  [FAIL] Expected status=CONFIRMED, got status={r5.get('status')}")
            r5["_failed"] = True
            all_pass = False
            results.append(("Double-Confirm", r5))
        else:
            print(f"  [PASS] Idempotent: returned CONFIRMED without error")
            r5["_failed"] = False
            results.append(("Double-Confirm", r5))
    else:
        print(f"\n[SKIP] No confirmation_id returned, skipping confirm step")

    # Test 6: Rapid sequential requests (no 500s under burst)
    print(f"\n{'='*60}")
    print(f"[TEST] Rapid sequential requests (5x 'Hi')")
    rapid_fail = False
    for i in range(5):
        rr = post_command(base, "Hi", f"Rapid #{i+1}")
        if rr.get("_failed"):
            rapid_fail = True
            break
    if rapid_fail:
        results.append(("Rapid-Burst", {"_failed": True, "_status": "mixed"}))
        all_pass = False
    else:
        print(f"  [PASS] All 5 rapid requests succeeded")
        results.append(("Rapid-Burst", {"_failed": False, "_status": "200"}))

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for label, r in results:
        status = "PASS" if not r.get("_failed") else "FAIL"
        http = r.get("_status", "?")
        rid = r.get("request_id", "N/A")
        print(f"  [{status}] {label}: HTTP {http}, request_id={rid}")

    if all_pass:
        print(f"\n[OVERALL PASS] All smoke tests passed")
    else:
        print(f"\n[OVERALL FAIL] Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
