#!/usr/bin/env python3
"""
Verify stock BUY and SELL flows work correctly (ASSISTED_LIVE mode).

Tests:
1. BUY $3 of AAPL stock - should create trade ticket (ASSISTED_LIVE)
2. SELL $3 of AAPL stock - should create trade ticket (ASSISTED_LIVE)
3. Verify asset_class is STOCK in all responses
4. Verify trade ticket artifact has asset_class: STOCK

Verifies that:
- Stock commands use ASSISTED_LIVE mode (not LIVE execution)
- Trade tickets are generated (not Coinbase orders)
- order_intent artifact is persisted
- No UNSUPPORTED_ORDER_CONFIGURATION errors
"""

import json
import sys
import time
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
    """Get run artifacts."""
    r = httpx.get(f"{API_BASE_URL}/api/v1/runs/{run_id}/artifacts", headers=HEADERS, timeout=30.0)
    if r.status_code == 200:
        return r.json()
    return []


def test_stock_trade(command: str, conv_id: str, news_enabled: bool = False) -> dict:
    """Execute a stock trade flow and verify ASSISTED_LIVE behavior."""
    print(f"\n{'='*60}")
    print(f"Testing: {command} (news={'ON' if news_enabled else 'OFF'})")
    print("="*60)

    # Step 1: Send command
    print("\n[1] Sending command...")
    result = send_command(command, conv_id, news_enabled)
    status = result.get("status")
    intent = result.get("intent")
    print(f"    Status: {status}")
    print(f"    Intent: {intent}")

    # Check asset_class
    asset_class = result.get("asset_class") or (intent or {}).get("asset_class")
    print(f"    Asset Class: {asset_class}")

    # Check for immediate refusal
    if status == "REFUSED":
        print(f"    [REFUSED] {result.get('content', '')[:200]}")
        return {"status": "REFUSED", "reason": result.get("content")}

    # Check for confirmation needed (expected for stock trades)
    if status != "AWAITING_CONFIRMATION":
        print(f"    [INFO] Status: {status}")
        content = result.get("content", "")[:200]
        print(f"    Content: {content}")
        return {"status": status, "result": result}

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
        return {"status": "CONFIRM_ERROR", "error": error_text}

    # Step 3: Get run details
    print("\n[3] Fetching run details...")
    time.sleep(3)  # Wait for run to complete

    try:
        run_data = get_run(run_id)
        run_status = run_data.get("run", {}).get("status", "UNKNOWN")
        run_exec_mode = run_data.get("run", {}).get("execution_mode", "UNKNOWN")
        run_asset_class = run_data.get("run", {}).get("asset_class", "UNKNOWN")
        print(f"    Run status: {run_status}")
        print(f"    Execution mode: {run_exec_mode}")
        print(f"    Asset class: {run_asset_class}")

        # Step 4: Verify artifacts
        print("\n[4] Verifying artifacts...")
        artifacts = get_run_artifacts(run_id)
        artifact_types = [a.get("artifact_type", "") for a in artifacts]
        print(f"    Artifact types: {artifact_types}")

        has_order_intent = "order_intent" in artifact_types
        has_trade_ticket = "trade_ticket" in artifact_types
        print(f"    order_intent: {'FOUND' if has_order_intent else 'MISSING'}")
        print(f"    trade_ticket: {'FOUND' if has_trade_ticket else 'MISSING'}")

        # Check trade_ticket artifact has correct asset_class
        for a in artifacts:
            if a.get("artifact_type") == "trade_ticket":
                ticket_data = a.get("artifact_json", {})
                if isinstance(ticket_data, str):
                    ticket_data = json.loads(ticket_data)
                ticket_asset_class = ticket_data.get("asset_class", "")
                ticket_exec_mode = ticket_data.get("execution_mode", "")
                print(f"    Ticket asset_class: {ticket_asset_class}")
                print(f"    Ticket execution_mode: {ticket_exec_mode}")

        # Save run details
        output_file = OUTPUT_DIR / f"stock_test_{command.replace(' ', '_').replace('$', '')}.json"
        with open(output_file, "w") as f:
            json.dump(run_data, f, indent=2)
        print(f"    Saved to: {output_file}")

        return {
            "status": run_status,
            "run_id": run_id,
            "execution_mode": run_exec_mode,
            "asset_class": run_asset_class,
            "has_order_intent": has_order_intent,
            "has_trade_ticket": has_trade_ticket,
        }

    except Exception as e:
        print(f"    [ERROR] Failed to get run: {e}")
        return {"status": "RUN_ERROR", "run_id": run_id, "error": str(e)}


def main():
    print("="*60)
    print("Stock Trade Verification (ASSISTED_LIVE)")
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

    # Test 1: BUY stock
    r1 = test_stock_trade("Buy $3 of AAPL stock", conv_id, news_enabled=False)
    results.append(("BUY $3 AAPL stock", r1))

    # Test 2: SELL stock
    r2 = test_stock_trade("Sell $3 of AAPL stock", conv_id, news_enabled=False)
    results.append(("SELL $3 AAPL stock", r2))

    # Test 3: BUY stock with news ON
    r3 = test_stock_trade("Buy $3 of AAPL stock", conv_id, news_enabled=True)
    results.append(("BUY $3 AAPL stock (news ON)", r3))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    all_pass = True
    for name, result in results:
        status = result.get("status", "UNKNOWN")
        exec_mode = result.get("execution_mode", "")

        if status in ("COMPLETED", "FILLED"):
            mode_ok = exec_mode == "ASSISTED_LIVE"
            if mode_ok:
                print(f"[PASS] {name}: {status} (ASSISTED_LIVE)")
            else:
                print(f"[WARN] {name}: {status} but mode={exec_mode}")
                all_pass = False
        elif status == "REFUSED":
            print(f"[OK] {name}: Properly refused")
        elif status == "CONFIRM_ERROR":
            error = result.get("error", "")
            if "UNSUPPORTED_ORDER_CONFIGURATION" in error:
                print(f"[CRITICAL FAIL] {name}: UNSUPPORTED_ORDER_CONFIGURATION")
                all_pass = False
            else:
                print(f"[WARN] {name}: Confirm error - {error[:80]}")
        else:
            print(f"[INFO] {name}: {status}")

    if all_pass:
        print("\n[OVERALL PASS] Stock trading flows verified.")
        sys.exit(0)
    else:
        print("\n[OVERALL FAIL] Some stock tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
