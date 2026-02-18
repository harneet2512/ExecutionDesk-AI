#!/usr/bin/env python3
"""
Reproduction script for 500 error on loadMessages endpoint.

Tests the same endpoint the frontend uses to load messages.
"""

import json
import sys
from pathlib import Path

import httpx

API_BASE_URL = "http://localhost:8000"
HEADERS = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}


def main():
    print("=" * 60)
    print("STEP 1: Create conversation")
    print("=" * 60)
    
    try:
        response = httpx.post(
            f"{API_BASE_URL}/api/v1/conversations",
            headers=HEADERS,
            json={},
            timeout=10.0
        )
    except httpx.ConnectError:
        print("[FAIL] Cannot connect to backend at localhost:8000")
        sys.exit(1)
    
    print(f"Create conversation status: {response.status_code}")
    
    if response.status_code not in (200, 201):
        print(f"[FAIL] Could not create conversation: {response.text[:500]}")
        sys.exit(1)
    
    conv_data = response.json()
    conv_id = conv_data.get("conversation_id")
    print(f"Created conversation: {conv_id}")
    
    # STEP 2: Post a message
    print("\n" + "=" * 60)
    print("STEP 2: Post a message")
    print("=" * 60)
    
    msg_response = httpx.post(
        f"{API_BASE_URL}/api/v1/conversations/{conv_id}/messages",
        headers=HEADERS,
        json={"content": "Test message", "role": "user"},
        timeout=10.0
    )
    
    print(f"Post message status: {msg_response.status_code}")
    if msg_response.status_code not in (200, 201):
        print(f"[WARNING] Could not post message: {msg_response.text[:500]}")
    
    # STEP 3: Load messages (this is what the frontend does)
    print("\n" + "=" * 60)
    print("STEP 3: Load messages (GET /api/v1/conversations/{id}/messages)")
    print("=" * 60)
    
    load_response = httpx.get(
        f"{API_BASE_URL}/api/v1/conversations/{conv_id}/messages",
        headers=HEADERS,
        timeout=10.0
    )
    
    print(f"Load messages status: {load_response.status_code}")
    print(f"Response body: {load_response.text[:1000]}")
    
    # Save response
    output_dir = Path(__file__).parent / "demo_outputs"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "load_messages_response.json"
    try:
        data = load_response.json()
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved response to: {output_file}")
    except Exception as e:
        print(f"Could not parse JSON: {e}")
        with open(output_file, "w") as f:
            f.write(load_response.text)
    
    # Check for 500
    if load_response.status_code == 500:
        print("\n[FAIL] Got 500 error on loadMessages!")
        sys.exit(1)
    elif load_response.status_code == 200:
        print("\n[PASS] loadMessages returned 200")
    else:
        print(f"\n[WARNING] Unexpected status: {load_response.status_code}")
    
    # STEP 4: Test with non-existent conversation
    print("\n" + "=" * 60)
    print("STEP 4: Test with non-existent conversation")
    print("=" * 60)
    
    bad_response = httpx.get(
        f"{API_BASE_URL}/api/v1/conversations/conv_nonexistent/messages",
        headers=HEADERS,
        timeout=10.0
    )
    
    print(f"Non-existent conversation status: {bad_response.status_code}")
    print(f"Response: {bad_response.text[:500]}")
    
    if bad_response.status_code == 500:
        print("[FAIL] Got 500 for non-existent conversation (should be 404)")
    elif bad_response.status_code == 404:
        print("[PASS] Correctly returned 404 for non-existent conversation")
    
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
