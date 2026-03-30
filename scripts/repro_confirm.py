#!/usr/bin/env python3
"""
Reproduce confirmation endpoint behavior.
Tests the full flow: chat command -> get confirmation -> confirm trade.
"""
import httpx
import json
import sys
import time

BASE_URL = "http://localhost:8000"
HEADERS = {
    "X-Dev-Tenant": "t_default",
    "Content-Type": "application/json"
}

def log(title: str, status: int, body: str):
    print(f"\n{'='*60}")
    print(f"[{title}]")
    print(f"  Status: {status}")
    body_preview = body[:800] if len(body) > 800 else body
    print(f"  Body: {body_preview}")
    if status >= 500:
        print(f"  *** ERROR: Got {status} - this should never happen! ***")

def test_confirm_flow(command: str):
    """Test the full confirmation flow for a trade command."""
    print(f"\n{'#'*60}")
    print(f"# Testing: {command}")
    print(f"{'#'*60}")
    
    client = httpx.Client(timeout=60.0)
    
    # Step 1: Create conversation
    r = client.post(f"{BASE_URL}/api/v1/conversations", headers=HEADERS, json={})
    log("Create Conversation", r.status_code, r.text)
    if r.status_code != 200:
        print("FAIL: Could not create conversation")
        return False
    conv_id = r.json().get("conversation_id")
    
    # Step 2: Send trade command
    r = client.post(
        f"{BASE_URL}/api/v1/chat/command",
        headers=HEADERS,
        json={"text": command, "conversation_id": conv_id}
    )
    log("Chat Command", r.status_code, r.text)
    if r.status_code != 200:
        print(f"FAIL: Chat command returned {r.status_code}")
        return False
    
    data = r.json()
    confirmation_id = data.get("confirmation_id")
    if not confirmation_id:
        # Check if it was rejected for min notional or other reason
        status = data.get("status")
        if status == "REJECTED":
            print(f"INFO: Trade was rejected - {data.get('content', 'unknown reason')}")
            return True  # Not a failure, just a business rejection
        print(f"WARN: No confirmation_id in response. Intent: {data.get('intent')}, Status: {status}")
        return True
    
    print(f"\n  confirmation_id: {confirmation_id}")
    
    # Step 3: Confirm the trade
    confirm_url = f"{BASE_URL}/api/v1/confirmations/{confirmation_id}/confirm"
    r = client.post(confirm_url, headers=HEADERS, json={})
    log("Confirm Trade", r.status_code, r.text)
    
    if r.status_code >= 500:
        print("*** CRITICAL: Confirm returned 500 - THIS IS THE BUG ***")
        return False
    
    if r.status_code == 200:
        result = r.json()
        run_id = result.get("run_id")
        status = result.get("status")
        print(f"\n  CONFIRMED: run_id={run_id}, status={status}")
        
        # Step 4: Test idempotent confirm (should return 200, not error)
        r2 = client.post(confirm_url, headers=HEADERS, json={})
        log("Idempotent Confirm (2nd call)", r2.status_code, r2.text)
        if r2.status_code >= 500:
            print("*** ERROR: Idempotent confirm returned 500 ***")
            return False
    
    return True

def test_error_cases():
    """Test error handling for edge cases."""
    print(f"\n{'#'*60}")
    print("# Testing Error Cases")
    print(f"{'#'*60}")
    
    client = httpx.Client(timeout=30.0)
    all_pass = True
    
    # Test 1: Invalid confirmation ID format
    r = client.post(
        f"{BASE_URL}/api/v1/confirmations/invalid_id/confirm",
        headers=HEADERS, json={}
    )
    log("Invalid ID Format", r.status_code, r.text)
    if r.status_code == 400:
        print("  PASS: Invalid ID returns 400")
    else:
        print(f"  FAIL: Expected 400, got {r.status_code}")
        all_pass = False
    
    # Test 2: Non-existent confirmation ID
    r = client.post(
        f"{BASE_URL}/api/v1/confirmations/conf_nonexistent123456/confirm",
        headers=HEADERS, json={}
    )
    log("Non-existent ID", r.status_code, r.text)
    if r.status_code == 404:
        print("  PASS: Non-existent ID returns 404")
    else:
        print(f"  FAIL: Expected 404, got {r.status_code}")
        all_pass = False
    
    # Test 3: Cancel non-existent
    r = client.post(
        f"{BASE_URL}/api/v1/confirmations/conf_nonexistent123456/cancel",
        headers=HEADERS, json={}
    )
    log("Cancel Non-existent", r.status_code, r.text)
    if r.status_code == 404:
        print("  PASS: Cancel non-existent returns 404")
    else:
        print(f"  FAIL: Expected 404, got {r.status_code}")
        all_pass = False
    
    return all_pass

def main():
    print("=" * 60)
    print("CONFIRMATION ENDPOINT REPRODUCTION SCRIPT")
    print("=" * 60)
    
    results = []
    
    # Test sell flow
    results.append(("Sell $2 BTC", test_confirm_flow("Sell $2 of BTC")))
    
    # Test buy flow
    results.append(("Buy $2 BTC", test_confirm_flow("Buy $2 of BTC")))
    
    # Test error cases
    results.append(("Error Cases", test_error_cases()))
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print("="*60)
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_pass = False
    
    print()
    if all_pass:
        print("[OVERALL PASS] All confirmation tests passed - no 500 errors")
    else:
        print("[OVERALL FAIL] Some tests failed - see above for details")
    
    return 0 if all_pass else 1

if __name__ == "__main__":
    sys.exit(main())
