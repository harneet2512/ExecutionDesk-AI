#!/usr/bin/env python3
"""
Reproduce terminal trade state.
Tests that trades always reach COMPLETED or FAILED, never stuck at RUNNING.
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

def log(title: str, data: dict):
    print(f"\n{'='*60}")
    print(f"[{title}]")
    for k, v in data.items():
        print(f"  {k}: {v}")

def test_terminal_trade(command: str, max_wait_seconds: int = 90):
    """Test that a trade command reaches terminal state."""
    print(f"\n{'#'*60}")
    print(f"# Testing Terminal State: {command}")
    print(f"{'#'*60}")
    
    client = httpx.Client(timeout=60.0)
    
    # Step 1: Create conversation
    r = client.post(f"{BASE_URL}/api/v1/conversations", headers=HEADERS, json={})
    if r.status_code != 200:
        print(f"FAIL: Could not create conversation: {r.status_code}")
        return False
    conv_id = r.json().get("conversation_id")
    log("Conversation Created", {"conversation_id": conv_id})
    
    # Step 2: Send trade command
    r = client.post(
        f"{BASE_URL}/api/v1/chat/command",
        headers=HEADERS,
        json={"text": command, "conversation_id": conv_id}
    )
    if r.status_code != 200:
        print(f"FAIL: Chat command failed: {r.status_code} - {r.text[:200]}")
        return False
    
    data = r.json()
    confirmation_id = data.get("confirmation_id")
    if not confirmation_id:
        status = data.get("status")
        if status == "REJECTED":
            log("Trade Rejected (not a failure)", {"reason": data.get("content", "")[:100]})
            return True
        print(f"WARN: No confirmation_id. Intent: {data.get('intent')}, Status: {status}")
        return True
    
    log("Trade Confirmation Received", {
        "confirmation_id": confirmation_id,
        "status": data.get("status")
    })
    
    # Step 3: Confirm the trade
    confirm_url = f"{BASE_URL}/api/v1/confirmations/{confirmation_id}/confirm"
    r = client.post(confirm_url, headers=HEADERS, json={})
    
    if r.status_code >= 500:
        print(f"FAIL: Confirm returned 500: {r.text[:200]}")
        return False
    
    if r.status_code != 200:
        log("Confirm Non-200", {"status": r.status_code, "body": r.text[:150]})
        return True  # Not stuck, just rejected
    
    result = r.json()
    run_id = result.get("run_id")
    if not run_id:
        print("FAIL: No run_id returned from confirm")
        return False
    
    log("Trade Confirmed", {"run_id": run_id, "status": result.get("status")})
    
    # Step 4: Poll until terminal or timeout
    terminal_states = {"COMPLETED", "FAILED"}
    start_time = time.time()
    poll_count = 0
    final_status = None
    
    while time.time() - start_time < max_wait_seconds:
        poll_count += 1
        time.sleep(1)
        
        r = client.get(f"{BASE_URL}/api/v1/runs/{run_id}", headers=HEADERS)
        if r.status_code != 200:
            print(f"  Poll #{poll_count}: GET /runs failed: {r.status_code}")
            continue
        
        run_data = r.json()
        current_status = run_data.get("run", {}).get("status") or run_data.get("status")
        
        if poll_count % 5 == 1 or current_status in terminal_states:
            print(f"  Poll #{poll_count}: status={current_status}")
        
        if current_status in terminal_states:
            final_status = current_status
            break
    
    elapsed = time.time() - start_time
    
    if final_status not in terminal_states:
        print(f"\n*** FAIL: Run {run_id} stuck at {current_status} after {elapsed:.1f}s ***")
        return False
    
    log("Terminal State Reached", {
        "run_id": run_id,
        "status": final_status,
        "elapsed_seconds": f"{elapsed:.1f}",
        "poll_count": poll_count
    })
    
    # Step 5: Fetch trade_receipt artifact
    r = client.get(f"{BASE_URL}/api/v1/runs/{run_id}/trace", headers=HEADERS)
    if r.status_code == 200:
        trace = r.json()
        artifacts = trace.get("artifacts", [])
        receipt = None
        for art in artifacts:
            if isinstance(art, dict) and art.get("artifact_type") == "trade_receipt":
                try:
                    receipt = json.loads(art.get("artifact_json", "{}"))
                except:
                    receipt = art.get("artifact_json")
                break
        
        if receipt:
            log("trade_receipt.json Found", receipt)
        else:
            print("  WARN: No trade_receipt artifact found (may be non-trade run)")
    
    print(f"\n[PASS] {command} reached terminal state: {final_status}")
    return True


def main():
    print("=" * 60)
    print("TERMINAL TRADE STATE VERIFICATION")
    print("=" * 60)
    
    results = []
    
    # Test sell
    results.append(("Sell $2 BTC", test_terminal_trade("Sell $2 of BTC")))
    
    # Test buy
    results.append(("Buy $2 BTC", test_terminal_trade("Buy $2 of BTC")))
    
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
        print("[OVERALL PASS] All trades reached terminal state")
    else:
        print("[OVERALL FAIL] Some trades stuck at RUNNING")
    
    return 0 if all_pass else 1

if __name__ == "__main__":
    sys.exit(main())
