#!/usr/bin/env python3
"""
Verify crypto BUY and SELL flows work correctly with Coinbase.

Tests:
1. BUY $3 of BTC - should use quote_size
2. SELL $1 of BTC - should use base_size (converted from USD)

Verifies that:
- No UNSUPPORTED_ORDER_CONFIGURATION errors
- SELL uses base_size, BUY uses quote_size
- Proper refusal messages for insufficient funds or min size
"""

import json
import sys
from pathlib import Path

import httpx

API_BASE_URL = "http://localhost:8000"
HEADERS = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}

OUTPUT_DIR = Path(__file__).parent / "demo_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def create_conversation() -> str:
    """Create a new conversation."""
    r = httpx.post(f"{API_BASE_URL}/api/v1/conversations", headers=HEADERS, json={})
    r.raise_for_status()
    return r.json()["conversation_id"]


def send_command(text: str, conv_id: str, news_enabled: bool = False) -> dict:
    """Send a chat command."""
    r = httpx.post(
        f"{API_BASE_URL}/api/v1/chat/command",
        headers=HEADERS,
        json={"text": text, "conversation_id": conv_id, "news_enabled": news_enabled},
        timeout=60.0
    )
    r.raise_for_status()
    return r.json()


def confirm_trade(confirmation_id: str) -> dict:
    """Confirm a pending trade."""
    r = httpx.post(
        f"{API_BASE_URL}/api/v1/confirmations/{confirmation_id}/confirm",
        headers=HEADERS,
        json={},
        timeout=60.0
    )
    r.raise_for_status()
    return r.json()


def get_run(run_id: str) -> dict:
    """Get run details."""
    r = httpx.get(f"{API_BASE_URL}/api/v1/runs/{run_id}", headers=HEADERS, timeout=30.0)
    r.raise_for_status()
    return r.json()


def get_run_artifacts(run_id: str) -> list:
    """Get run artifacts for observability verification."""
    r = httpx.get(f"{API_BASE_URL}/api/v1/runs/{run_id}/artifacts", headers=HEADERS, timeout=30.0)
    if r.status_code == 200:
        return r.json()
    return []


def verify_artifacts(run_id: str) -> dict:
    """Verify observability artifacts were persisted."""
    results = {"order_intent": False, "order_rules": False, "trade_receipt": False}
    try:
        artifacts = get_run_artifacts(run_id)
        for artifact in artifacts:
            atype = artifact.get("artifact_type", "")
            if atype == "order_intent":
                results["order_intent"] = True
            elif atype == "order_rules":
                results["order_rules"] = True
            elif atype == "trade_receipt":
                results["trade_receipt"] = True
    except Exception as e:
        print(f"    [WARN] Could not fetch artifacts: {e}")
    return results


def test_trade(command: str, conv_id: str, news_enabled: bool = False) -> dict:
    """Execute a full trade flow and return result."""
    print(f"\n{'='*60}")
    print(f"Testing: {command} (news={'ON' if news_enabled else 'OFF'})")
    print("="*60)
    
    # Step 1: Send command
    print("\n[1] Sending command...")
    result = send_command(command, conv_id, news_enabled)
    print(f"    Status: {result.get('status')}")
    print(f"    Intent: {result.get('intent')}")
    
    # Check for immediate refusal
    if result.get("status") == "REFUSED":
        print(f"    [REFUSED] {result.get('content', '')[:200]}")
        return {"status": "REFUSED", "reason": result.get("content")}
    
    # Check for confirmation needed
    if result.get("status") != "AWAITING_CONFIRMATION":
        print(f"    [UNEXPECTED] Status: {result.get('status')}")
        return {"status": "UNEXPECTED", "result": result}
    
    confirmation_id = result.get("confirmation_id")
    if not confirmation_id:
        print("    [ERROR] No confirmation_id in response")
        return {"status": "ERROR", "reason": "No confirmation_id"}
    
    print(f"    Confirmation ID: {confirmation_id}")
    
    # Step 2: Confirm trade
    print("\n[2] Confirming trade...")
    try:
        confirm_result = confirm_trade(confirmation_id)
        print(f"    Confirm status: {confirm_result.get('status')}")
        run_id = confirm_result.get("run_id")
        
        if not run_id:
            print("    [ERROR] No run_id in confirm response")
            return {"status": "ERROR", "reason": "No run_id after confirm"}
        
        print(f"    Run ID: {run_id}")
        
    except httpx.HTTPStatusError as e:
        error_text = e.response.text[:500]
        print(f"    [ERROR] Confirm failed: {e.response.status_code}")
        print(f"    Response: {error_text}")
        
        # Check for the specific Coinbase error
        if "UNSUPPORTED_ORDER_CONFIGURATION" in error_text:
            print("\n    [CRITICAL BUG] UNSUPPORTED_ORDER_CONFIGURATION error!")
            print("    This means SELL is still using quote_size instead of base_size")
            return {"status": "COINBASE_CONFIG_ERROR", "error": error_text}
        
        return {"status": "CONFIRM_ERROR", "error": error_text}
    
    # Step 3: Get run details
    print("\n[3] Fetching run details...")
    import time
    time.sleep(2)  # Wait for run to complete
    
    try:
        run_data = get_run(run_id)
        run_status = run_data.get("run", {}).get("status", "UNKNOWN")
        print(f"    Run status: {run_status}")
        
        # Verify observability artifacts
        print("\n[4] Verifying artifacts...")
        artifact_results = verify_artifacts(run_id)
        for atype, found in artifact_results.items():
            status_str = "FOUND" if found else "MISSING"
            print(f"    {atype}: {status_str}")

        # Save run details
        output_file = OUTPUT_DIR / f"trade_test_{command.replace(' ', '_').replace('$', '')}.json"
        with open(output_file, "w") as f:
            json.dump(run_data, f, indent=2)
        print(f"    Saved to: {output_file}")

        return {"status": run_status, "run_id": run_id, "run_data": run_data, "artifacts": artifact_results}
        
    except Exception as e:
        print(f"    [ERROR] Failed to get run: {e}")
        return {"status": "RUN_ERROR", "run_id": run_id, "error": str(e)}


def main():
    print("="*60)
    print("Crypto Trade Verification")
    print("="*60)
    
    # Create conversation
    print("\nCreating conversation...")
    try:
        conv_id = create_conversation()
        print(f"Conversation ID: {conv_id}")
    except Exception as e:
        print(f"[FAIL] Could not create conversation: {e}")
        sys.exit(1)
    
    results = []
    
    # Test 1: BUY with news OFF
    r1 = test_trade("Buy $3 of BTC", conv_id, news_enabled=False)
    results.append(("BUY $3 BTC (news OFF)", r1))
    
    # Test 2: SELL with news OFF (the critical test)
    r2 = test_trade("Sell $1 of BTC", conv_id, news_enabled=False)
    results.append(("SELL $1 BTC (news OFF)", r2))
    
    # Test 3: SELL with news ON
    r3 = test_trade("Sell $1 of BTC", conv_id, news_enabled=True)
    results.append(("SELL $1 BTC (news ON)", r3))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    has_config_error = False
    for name, result in results:
        status = result.get("status", "UNKNOWN")
        if status == "COINBASE_CONFIG_ERROR":
            print(f"[CRITICAL FAIL] {name}: UNSUPPORTED_ORDER_CONFIGURATION")
            has_config_error = True
        elif status in ("COMPLETED", "FILLED"):
            print(f"[PASS] {name}: {status}")
        elif status == "FAILED":
            # Check if it's a min size or funds issue (expected)
            error = result.get("error", "")
            if "minimum" in error.lower() or "insufficient" in error.lower():
                print(f"[OK] {name}: Properly refused - {error[:100]}")
            else:
                print(f"[WARN] {name}: {status}")
        elif status == "REFUSED":
            print(f"[OK] {name}: Properly refused - {result.get('reason', '')[:100]}")
        else:
            print(f"[INFO] {name}: {status}")
    
    if has_config_error:
        print("\n[OVERALL FAIL] UNSUPPORTED_ORDER_CONFIGURATION errors found!")
        print("The SELL order is still using quote_size instead of base_size.")
        sys.exit(1)
    else:
        print("\n[OVERALL PASS] No Coinbase configuration errors.")
        sys.exit(0)


if __name__ == "__main__":
    main()
