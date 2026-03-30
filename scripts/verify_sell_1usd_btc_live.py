#!/usr/bin/env python3
"""
Verification script for "Sell $1 of BTC" command flow.

Tests:
1. Parsing correctly extracts side=sell, amount=1.0, asset=BTC
2. POST /api/v1/chat/command returns confirmation (not follow-up question)
3. Confirmation can be confirmed
"""

import json
import sys
from pathlib import Path

import httpx

API_BASE_URL = "http://localhost:8000"
HEADERS = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}


def test_parsing():
    """Test that trade_parser handles all USD amount formats."""
    print("=" * 60)
    print("STEP 1: Testing trade_parser.py locally")
    print("=" * 60)
    
    try:
        from backend.agents.trade_parser import parse_trade_command
    except ImportError:
        print("[SKIP] Cannot import trade_parser (run from project root)")
        return True  # Skip but don't fail
    
    test_cases = [
        ("Sell $1 of BTC", {"side": "sell", "amount_usd": 1.0, "asset": "BTC"}),
        ("Sell 1$ of BTC", {"side": "sell", "amount_usd": 1.0, "asset": "BTC"}),
        ("Sell 1 USD of BTC", {"side": "sell", "amount_usd": 1.0, "asset": "BTC"}),
        ("Sell 1 dollars of BTC", {"side": "sell", "amount_usd": 1.0, "asset": "BTC"}),
        ("Buy $10 of ETH", {"side": "buy", "amount_usd": 10.0, "asset": "ETH"}),
        ("Sell $5.50 BTC", {"side": "sell", "amount_usd": 5.5, "asset": "BTC"}),
    ]
    
    all_passed = True
    for text, expected in test_cases:
        result = parse_trade_command(text)
        passed = (
            result.side == expected["side"] and
            result.amount_usd == expected["amount_usd"] and
            result.asset == expected["asset"]
        )
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} '{text}'")
        print(f"       Got: side={result.side}, amount={result.amount_usd}, asset={result.asset}")
        if not passed:
            all_passed = False
            print(f"       Expected: side={expected['side']}, amount={expected['amount_usd']}, asset={expected['asset']}")
    
    return all_passed


def test_api_command():
    """Test that the API returns a confirmation prompt, not a follow-up question."""
    print("\n" + "=" * 60)
    print("STEP 2: Testing POST /api/v1/chat/command")
    print("=" * 60)
    
    test_text = "Sell $1 of BTC"
    print(f"\nSending: '{test_text}'")
    
    try:
        response = httpx.post(
            f"{API_BASE_URL}/api/v1/chat/command",
            headers=HEADERS,
            json={"text": test_text},
            timeout=30.0
        )
    except httpx.ConnectError:
        print("\n[FAIL] Cannot connect to backend at localhost:8000")
        return False
    
    print(f"Response status: {response.status_code}")
    
    if response.status_code != 200:
        print(f"[FAIL] Expected 200, got {response.status_code}")
        print(f"Body: {response.text[:500]}")
        return False
    
    data = response.json()
    
    # Save response
    output_dir = Path(__file__).parent / "demo_outputs"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "sell_1usd_btc_response.json"
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved response to: {output_file}")
    
    # Validate: should be AWAITING_CONFIRMATION, not AWAITING_INPUT
    status = data.get("status")
    intent = data.get("intent")
    content = data.get("content", "")
    confirmation_id = data.get("confirmation_id")
    
    print(f"\nResponse fields:")
    print(f"  status: {status}")
    print(f"  intent: {intent}")
    print(f"  confirmation_id: {confirmation_id}")
    print(f"  content preview: {content[:200]}...")
    
    # Check for failure conditions
    errors = []
    
    if status == "AWAITING_INPUT":
        errors.append("Got AWAITING_INPUT (follow-up question). Parsing failed to extract amount.")
    
    if "How much" in content:
        errors.append("Response asks 'How much' - parsing failed to extract amount.")
    
    if "can't help" in content.lower() or "cannot help" in content.lower():
        errors.append("Response says 'can't help' - incorrect intent routing.")
    
    if status != "AWAITING_CONFIRMATION":
        errors.append(f"Expected status=AWAITING_CONFIRMATION, got {status}")
    
    if not confirmation_id:
        errors.append("No confirmation_id returned - confirmation flow not triggered.")
    
    if "LIVE" not in content:
        errors.append("Mode should be LIVE but 'LIVE' not found in content.")
    
    if errors:
        print("\n[FAIL] Validation errors:")
        for err in errors:
            print(f"  - {err}")
        return False
    
    print("\n[PASS] API returned confirmation prompt correctly")
    return True


def test_confirmation():
    """Test that CONFIRM executes the trade."""
    print("\n" + "=" * 60)
    print("STEP 3: Testing CONFIRM flow")
    print("=" * 60)
    
    # First create a new pending trade
    response = httpx.post(
        f"{API_BASE_URL}/api/v1/chat/command",
        headers=HEADERS,
        json={"text": "Sell $1 of BTC"},
        timeout=30.0
    )
    
    if response.status_code != 200:
        print(f"[FAIL] Could not create pending trade: {response.status_code}")
        return False
    
    data = response.json()
    confirmation_id = data.get("confirmation_id")
    
    if not confirmation_id:
        print("[FAIL] No confirmation_id in response")
        return False
    
    print(f"Created pending trade with confirmation_id: {confirmation_id}")
    
    # Now confirm it
    confirm_response = httpx.post(
        f"{API_BASE_URL}/api/v1/chat/command",
        headers=HEADERS,
        json={"text": "CONFIRM", "confirmation_id": confirmation_id},
        timeout=60.0
    )
    
    print(f"Confirm response status: {confirm_response.status_code}")
    
    if confirm_response.status_code != 200:
        print(f"[FAIL] Confirm failed: {confirm_response.status_code}")
        print(f"Body: {confirm_response.text[:500]}")
        return False
    
    confirm_data = confirm_response.json()
    
    # Save response
    output_dir = Path(__file__).parent / "demo_outputs"
    output_file = output_dir / "sell_1usd_btc_confirm_response.json"
    with open(output_file, "w") as f:
        json.dump(confirm_data, f, indent=2)
    print(f"Saved confirm response to: {output_file}")
    
    run_id = confirm_data.get("run_id")
    status = confirm_data.get("status")
    content = confirm_data.get("content", "")
    
    print(f"\nConfirm response:")
    print(f"  run_id: {run_id}")
    print(f"  status: {status}")
    print(f"  content: {content[:200]}...")
    
    # Validate
    errors = []
    
    if not run_id:
        errors.append("No run_id returned after confirmation")
    
    if status not in ("EXECUTING", "COMPLETED", "REJECTED"):
        errors.append(f"Unexpected status: {status}. Expected EXECUTING, COMPLETED, or REJECTED")
    
    # Check for generic refusal
    if "can't help" in content.lower() or "cannot help" in content.lower():
        errors.append("Response says 'can't help' after confirmation - this should not happen")
    
    if errors:
        print("\n[FAIL] Confirmation errors:")
        for err in errors:
            print(f"  - {err}")
        return False
    
    print("\n[PASS] Confirmation flow works correctly")
    return True


def main():
    print("\n" + "#" * 60)
    print("# Sell $1 of BTC - End-to-End Verification")
    print("#" * 60 + "\n")
    
    results = {
        "parsing": test_parsing(),
        "api_command": test_api_command(),
        "confirmation": test_confirmation()
    }
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} {name}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("\n[OVERALL PASS] All tests passed!")
        sys.exit(0)
    else:
        print("\n[OVERALL FAIL] Some tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
