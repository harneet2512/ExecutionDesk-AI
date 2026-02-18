#!/usr/bin/env python3
"""
Comprehensive reproduction script for messages endpoint reliability.

Creates a conversation, posts N messages, then hammers list-messages
both sequentially and concurrently. Asserts zero 500 responses.
Every non-200 must be 429/503/404 with a JSON error envelope.

Usage:
    python scripts/repro_messages_500.py          # run against localhost:8000
    python scripts/repro_messages_500.py --url http://host:port
"""

import argparse
import json
import sys
import time
import concurrent.futures

import httpx

HEADERS = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}
NUM_MESSAGES = 10
CONCURRENT_READS = 20
SEQUENTIAL_READS = 30


def create_conversation(base: str) -> str:
    r = httpx.post(f"{base}/api/v1/conversations", headers=HEADERS, json={}, timeout=10)
    assert r.status_code == 200, f"Create conversation failed: {r.status_code} {r.text[:200]}"
    return r.json()["conversation_id"]


def post_message(base: str, conv_id: str, idx: int):
    r = httpx.post(
        f"{base}/api/v1/conversations/{conv_id}/messages",
        headers=HEADERS,
        json={"content": f"Test message #{idx}", "role": "user"},
        timeout=10,
    )
    assert r.status_code in (200, 201), f"Post msg failed: {r.status_code} {r.text[:200]}"


def list_messages(base: str, conv_id: str) -> httpx.Response:
    return httpx.get(
        f"{base}/api/v1/conversations/{conv_id}/messages",
        headers=HEADERS,
        timeout=10,
    )


def validate_error_envelope(r: httpx.Response):
    """Every non-200 must have JSON envelope with error.code, error.message, request_id."""
    try:
        data = r.json()
    except Exception:
        return False, f"Non-JSON response body: {r.text[:200]}"
    err = data.get("error")
    if not isinstance(err, dict):
        return False, f"Missing error envelope: {json.dumps(data)[:200]}"
    for key in ("code", "message"):
        if key not in err:
            return False, f"Missing error.{key}: {json.dumps(err)[:200]}"
    # request_id can be in error.request_id or top-level
    req_id = err.get("request_id") or data.get("request_id") or ""
    if not req_id:
        return False, f"Missing request_id: {json.dumps(data)[:200]}"
    return True, ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    failures = []

    # Step 1: create conversation
    print(f"[1] Creating conversation on {base}")
    try:
        conv_id = create_conversation(base)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        print("[FAIL] Cannot connect to backend. Is it running?")
        sys.exit(1)
    print(f"    conversation_id = {conv_id}")

    # Step 2: post messages
    print(f"[2] Posting {NUM_MESSAGES} messages")
    for i in range(NUM_MESSAGES):
        post_message(base, conv_id, i)
    print(f"    Posted {NUM_MESSAGES} messages")

    # Step 3: sequential reads
    print(f"[3] Sequential reads ({SEQUENTIAL_READS}x)")
    status_counts: dict[int, int] = {}
    for _ in range(SEQUENTIAL_READS):
        r = list_messages(base, conv_id)
        status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
        if r.status_code == 500:
            failures.append(f"500 on sequential read: {r.text[:200]}")
        elif r.status_code != 200:
            ok, reason = validate_error_envelope(r)
            if not ok:
                failures.append(f"{r.status_code} bad envelope: {reason}")
    print(f"    Status distribution: {status_counts}")

    # Step 4: concurrent reads
    print(f"[4] Concurrent reads ({CONCURRENT_READS}x)")
    status_counts = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(list_messages, base, conv_id) for _ in range(CONCURRENT_READS)]
        for fut in concurrent.futures.as_completed(futs):
            try:
                r = fut.result()
                status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
                if r.status_code == 500:
                    failures.append(f"500 on concurrent read: {r.text[:200]}")
                elif r.status_code != 200:
                    ok, reason = validate_error_envelope(r)
                    if not ok:
                        failures.append(f"{r.status_code} bad envelope: {reason}")
            except Exception as e:
                failures.append(f"Exception: {e}")
    print(f"    Status distribution: {status_counts}")

    # Step 5: non-existent conversation
    print("[5] Non-existent conversation (should be 404)")
    r = list_messages(base, "conv_does_not_exist")
    if r.status_code == 500:
        failures.append(f"500 for non-existent conv: {r.text[:200]}")
    elif r.status_code != 404:
        print(f"    WARNING: expected 404, got {r.status_code}")
    else:
        print(f"    Correctly returned 404")
        ok, reason = validate_error_envelope(r)
        if not ok:
            failures.append(f"404 bad envelope: {reason}")

    # Report
    print("\n" + "=" * 60)
    if failures:
        print(f"[FAIL] {len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("[PASS] Zero 500s. All error responses have proper envelopes.")
        sys.exit(0)


if __name__ == "__main__":
    main()
