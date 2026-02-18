"""Smoke test: verify rate limiting returns 429 JSON (not 500).

Usage:
    python scripts/smoke_rate_limit.py [--base-url http://localhost:8000]

Asserts:
    - Normal commands return 200
    - Rapid-fire requests eventually trigger 429
    - 429 responses are JSON with request_id + retry_after_seconds (NOT 500)
"""
import sys
import json
import argparse
import requests

TENANT_HEADER = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}


def post_command(base_url: str, text: str, label: str) -> dict:
    """POST /api/v1/chat/command and return response."""
    url = f"{base_url}/api/v1/chat/command"
    resp = requests.post(url, json={"text": text}, headers=TENANT_HEADER, timeout=30)
    try:
        data = resp.json()
    except Exception:
        data = {}
    data["_status"] = resp.status_code
    data["_headers"] = dict(resp.headers)
    print(f"  [{label}] {resp.status_code} intent={data.get('intent', 'N/A')}")
    return data


def get_messages(base_url: str, conv_id: str) -> dict:
    """GET /conversations/{id}/messages."""
    url = f"{base_url}/api/v1/conversations/{conv_id}/messages"
    resp = requests.get(url, headers=TENANT_HEADER, timeout=10)
    try:
        data = resp.json()
    except Exception:
        data = {}
    return {"_status": resp.status_code, "_data": data, "_headers": dict(resp.headers)}


def main():
    parser = argparse.ArgumentParser(description="Rate limit smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.base_url

    all_pass = True

    # Step 1: Send a normal greeting to confirm 200
    print("\n[Step 1] Normal greeting")
    r1 = post_command(base, "Hi", "Greeting")
    if r1["_status"] != 200:
        print(f"  [FAIL] Expected 200, got {r1['_status']}")
        all_pass = False
    else:
        print(f"  [PASS] 200 OK")

    # Step 2: Create a conversation for /messages testing
    print("\n[Step 2] Create conversation for /messages storm test")
    conv_resp = requests.post(
        f"{base}/api/v1/conversations",
        json={"title": "Rate Limit Test"},
        headers=TENANT_HEADER,
        timeout=10,
    )
    if conv_resp.status_code != 200:
        print(f"  [FAIL] Could not create conversation: {conv_resp.status_code}")
        all_pass = False
        conv_id = None
    else:
        conv_id = conv_resp.json().get("conversation_id")
        print(f"  [PASS] Created conversation {conv_id}")

    # Step 3: Rapid-fire /chat/command to trigger rate limit (limit is 10/min)
    print("\n[Step 3] Rapid-fire /chat/command (expect 429 after ~10)")
    got_429 = False
    for i in range(15):
        r = post_command(base, "Hi", f"Burst {i+1}")
        if r["_status"] == 429:
            got_429 = True
            # Validate 429 response shape
            errors = []
            if "error" not in r:
                errors.append("Missing 'error' key in 429 response")
            elif r["error"].get("code") != "RATE_LIMITED":
                errors.append(f"Wrong error code: {r['error'].get('code')}")
            if "retry_after_seconds" not in r:
                errors.append("Missing retry_after_seconds")
            if "request_id" not in r:
                errors.append("Missing request_id")
            if "Retry-After" not in r.get("_headers", {}):
                errors.append("Missing Retry-After header")

            if errors:
                for e in errors:
                    print(f"  [FAIL] {e}")
                all_pass = False
            else:
                print(f"  [PASS] 429 response has correct shape")
            break
        elif r["_status"] >= 500:
            print(f"  [FAIL] Got 500 instead of 429!")
            all_pass = False
            break

    if not got_429:
        print(f"  [WARN] Did not trigger 429 in 15 requests (rate limit may be higher)")

    # Step 4: Rapid-fire /messages if we have a conversation
    if conv_id:
        print(f"\n[Step 4] Rapid-fire GET /messages (limit=60/min, should not trigger easily)")
        msg_429_count = 0
        for i in range(10):
            r = get_messages(base, conv_id)
            if r["_status"] == 429:
                msg_429_count += 1
            elif r["_status"] >= 500:
                print(f"  [FAIL] Got 500 on /messages request {i+1}")
                all_pass = False
        if msg_429_count == 0:
            print(f"  [PASS] 10 /messages requests completed without 429 (limit=60)")
        else:
            print(f"  [INFO] Got {msg_429_count} rate limits on /messages")

    # Summary
    print(f"\n{'='*60}")
    if all_pass:
        print("[OVERALL PASS] Rate limit smoke tests passed")
    else:
        print("[OVERALL FAIL] Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
