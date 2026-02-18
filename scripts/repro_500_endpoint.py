#!/usr/bin/env python3
"""
Reproduce 500 errors on various endpoints to identify the root cause.
Tests the exact endpoints the frontend uses.
"""

import json
import sys
from pathlib import Path

import httpx

API_BASE_URL = "http://localhost:8000"
HEADERS = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}


def test_endpoint(name: str, method: str, url: str, body: dict = None) -> tuple:
    """Test an endpoint and return status, response."""
    print(f"\n[{name}] {method} {url}")
    try:
        if method == "GET":
            r = httpx.get(f"{API_BASE_URL}{url}", headers=HEADERS, timeout=10.0)
        else:
            r = httpx.post(f"{API_BASE_URL}{url}", headers=HEADERS, json=body or {}, timeout=30.0)
        
        status = r.status_code
        body_text = r.text[:500]
        print(f"  Status: {status}")
        print(f"  Body: {body_text}")
        
        if status == 500:
            print("  [FAIL] 500 Internal Server Error!")
            return False, status, body_text
        elif status >= 400:
            print(f"  [WARN] Client error {status}")
            return None, status, body_text
        else:
            print("  [OK]")
            return True, status, body_text
            
    except httpx.ConnectError:
        print("  [FAIL] Connection refused")
        return False, 0, "Connection refused"


def main():
    results = []
    
    print("=" * 60)
    print("Testing API Endpoints for 500 Errors")
    print("=" * 60)
    
    # 1. Create conversation
    ok, status, body = test_endpoint(
        "Create Conversation",
        "POST", "/api/v1/conversations", {}
    )
    results.append(("Create Conversation", status))
    
    if not ok and status == 0:
        print("\n[ABORT] Backend not running")
        sys.exit(1)
    
    # Extract conversation_id
    try:
        conv_id = json.loads(body).get("conversation_id")
    except:
        conv_id = None
    
    if conv_id:
        # 2. Get conversation
        results.append(test_endpoint(
            "Get Conversation",
            "GET", f"/api/v1/conversations/{conv_id}"
        )[:2])
        
        # 3. List messages (empty)
        results.append(test_endpoint(
            "List Messages (empty)",
            "GET", f"/api/v1/conversations/{conv_id}/messages"
        )[:2])
        
        # 4. Create message
        msg_result = test_endpoint(
            "Create Message",
            "POST", f"/api/v1/conversations/{conv_id}/messages",
            {"content": "Test message", "role": "user"}
        )
        results.append(msg_result[:2])
        
        # 5. List messages (with content)
        results.append(test_endpoint(
            "List Messages (with content)",
            "GET", f"/api/v1/conversations/{conv_id}/messages"
        )[:2])
        
        # 6. Chat command
        results.append(test_endpoint(
            "Chat Command",
            "POST", "/api/v1/chat/command",
            {"text": "Hello", "conversation_id": conv_id}
        )[:2])
    
    # 7. List conversations
    results.append(test_endpoint(
        "List Conversations",
        "GET", "/api/v1/conversations"
    )[:2])
    
    # 8. Non-existent conversation
    results.append(test_endpoint(
        "Non-existent Conversation",
        "GET", "/api/v1/conversations/conv_nonexistent/messages"
    )[:2])
    
    # 9. List runs
    ok, status, body = test_endpoint(
        "List Runs",
        "GET", "/api/v1/runs"
    )
    results.append(("List Runs", status))

    # 10. Get a real run detail (if any runs exist)
    run_id = None
    try:
        runs_data = json.loads(body)
        if isinstance(runs_data, list) and len(runs_data) > 0:
            run_id = runs_data[0].get("run_id")
        elif isinstance(runs_data, dict) and runs_data.get("runs"):
            run_id = runs_data["runs"][0].get("run_id")
    except Exception:
        pass

    if run_id:
        results.append(test_endpoint(
            "Run Detail (real)",
            "GET", f"/api/v1/runs/{run_id}"
        )[:2])

        results.append(test_endpoint(
            "Run Trace (real)",
            "GET", f"/api/v1/runs/{run_id}/trace"
        )[:2])
    else:
        # Test with a fake run_id to verify 404 not 500
        results.append(test_endpoint(
            "Run Detail (fake)",
            "GET", "/api/v1/runs/run_nonexistent"
        )[:2])

        results.append(test_endpoint(
            "Run Trace (fake)",
            "GET", "/api/v1/runs/run_nonexistent/trace"
        )[:2])
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    has_500 = False
    for name, status in [(r[0], r[1]) if isinstance(r, tuple) else ("?", "?") for r in results]:
        if status == 500:
            print(f"  [500 ERROR] {name}")
            has_500 = True
        elif isinstance(status, int) and status < 400:
            print(f"  [OK] {name}: {status}")
        else:
            print(f"  [WARN] {name}: {status}")
    
    if has_500:
        print("\n[OVERALL FAIL] Found 500 errors!")
        sys.exit(1)
    else:
        print("\n[OVERALL PASS] No 500 errors found")
        sys.exit(0)


if __name__ == "__main__":
    main()
