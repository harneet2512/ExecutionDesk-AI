#!/usr/bin/env python3
"""
Reproduction script for portfolio analysis verification.
Tests that POST /api/v1/chat/command with "Analyze my portfolio" returns:
- status == COMPLETED
- content is non-empty with portfolio data
"""

import json
import sys
from pathlib import Path

import httpx

API_BASE_URL = "http://localhost:8000"
TENANT_HEADER = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}


def main():
    print("=" * 60)
    print("Portfolio Analysis Repro Script")
    print("=" * 60)
    
    # Step 1: Send chat command
    print("\n[1] Sending: POST /api/v1/chat/command")
    print("    Payload: {'text': 'Analyze my portfolio'}")
    
    try:
        response = httpx.post(
            f"{API_BASE_URL}/api/v1/chat/command",
            headers=TENANT_HEADER,
            json={"text": "Analyze my portfolio"},
            timeout=60.0
        )
    except httpx.ConnectError:
        print("\n[FAIL] Cannot connect to backend at localhost:8000")
        print("       Start the backend with: python -m uvicorn backend.api.main:app --reload --port 8000")
        sys.exit(1)
    
    print(f"    Response status code: {response.status_code}")
    
    if response.status_code != 200:
        print(f"\n[FAIL] Expected 200, got {response.status_code}")
        print(f"       Body: {response.text[:500]}")
        sys.exit(1)
    
    data = response.json()
    
    # Save full response
    output_dir = Path(__file__).parent / "demo_outputs"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "analyze_portfolio_response.json"
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n[2] Saved response to: {output_file}")
    
    # Step 3: Validate response
    print("\n[3] Validating response fields...")
    
    status = data.get("status")
    content = data.get("content", "")
    run_id = data.get("run_id")
    intent = data.get("intent")
    
    print(f"    status: {status}")
    print(f"    intent: {intent}")
    print(f"    run_id: {run_id}")
    print(f"    content length: {len(content)} chars")
    
    errors = []
    
    if status != "COMPLETED":
        errors.append(f"Expected status=COMPLETED, got {status}")
    
    if not content:
        errors.append("Content is empty")
    
    if not run_id:
        errors.append("run_id is missing")
    
    # Check content contains expected portfolio fields
    content_lower = content.lower()
    expected_fields = ["portfolio", "value", "holdings"]
    found_fields = [f for f in expected_fields if f in content_lower]
    
    if len(found_fields) < 2:
        errors.append(f"Content missing expected fields. Found: {found_fields}")
    
    print("\n" + "=" * 60)
    if errors:
        print("[FAIL] Validation failed:")
        for err in errors:
            print(f"       - {err}")
        print("=" * 60)
        sys.exit(1)
    else:
        print("[PASS] All validations passed")
        print("=" * 60)
        print("\nContent preview (first 500 chars):")
        print("-" * 40)
        print(content[:500])
        print("-" * 40)
        sys.exit(0)


if __name__ == "__main__":
    main()
