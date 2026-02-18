#!/usr/bin/env python3
"""
Reproduce handleSend 500 error by calling the exact backend endpoints.

Tests the same flow as app/chat/page.tsx handleSend:
1. POST /api/v1/conversations (create conversation)
2. POST /api/v1/conversations/{id}/messages (create user message)  
3. POST /api/v1/chat/command (execute chat command)
"""

import json
import sys
import httpx

API_BASE = "http://localhost:8000"
HEADERS = {
    "Content-Type": "application/json",
    "X-Dev-Tenant": "t_default"
}

def log_response(step: str, response):
    """Log response details."""
    print(f"\n{'='*60}")
    print(f"[{step}]")
    print(f"  Status: {response.status_code}")
    print(f"  Content-Type: {response.headers.get('content-type', 'unknown')}")
    body = response.text[:1500] if len(response.text) > 1500 else response.text
    print(f"  Body: {body}")
    if response.status_code >= 500:
        print(f"  [!!!] GOT 500 ERROR")
    print(f"{'='*60}")

def main():
    print("=" * 60)
    print("Reproduce handleSend 500 Error")
    print("=" * 60)
    
    # Step 1: Create conversation (like line 346 in page.tsx)
    print("\n[STEP 1] POST /api/v1/conversations")
    r = httpx.post(
        f"{API_BASE}/api/v1/conversations",
        headers=HEADERS,
        json={},
        timeout=30
    )
    log_response("createConversation", r)
    
    if r.status_code >= 400:
        print(f"\n[FAIL] Could not create conversation")
        sys.exit(1)
    
    conv_id = r.json().get("conversation_id")
    print(f"\n  conversation_id: {conv_id}")
    
    # Step 2: Create user message (like line 360 in page.tsx)
    print("\n[STEP 2] POST /api/v1/conversations/{id}/messages")
    user_message = "Sell $1 of BTC"
    r = httpx.post(
        f"{API_BASE}/api/v1/conversations/{conv_id}/messages",
        headers=HEADERS,
        json={
            "content": user_message,
            "role": "user"
        },
        timeout=30
    )
    log_response("createMessage (user)", r)
    
    if r.status_code >= 500:
        print(f"\n[FAIL] createMessage returned 500")
        sys.exit(1)
    
    # Step 3: Execute chat command (like line 364 in page.tsx)
    print("\n[STEP 3] POST /api/v1/chat/command")
    r = httpx.post(
        f"{API_BASE}/api/v1/chat/command",
        headers=HEADERS,
        json={
            "text": user_message,
            "conversation_id": conv_id,
            "news_enabled": True  # Default in UI
        },
        timeout=120
    )
    log_response("executeChatCommand", r)
    
    if r.status_code >= 500:
        print(f"\n[FAIL] executeChatCommand returned 500")
        print(f"  This is the failing endpoint!")
        sys.exit(1)
    
    # Parse result
    try:
        result = r.json()
        print(f"\n[RESULT]")
        print(f"  intent: {result.get('intent')}")
        print(f"  status: {result.get('status')}")
        print(f"  run_id: {result.get('run_id')}")
        print(f"  confirmation_id: {result.get('confirmation_id')}")
        if result.get('content'):
            print(f"  content (first 200): {result.get('content', '')[:200]}")
    except Exception as e:
        print(f"\n[WARN] Could not parse response as JSON: {e}")
    
    # If we got a confirmation_id, try to confirm it
    conf_id = result.get("confirmation_id") if r.status_code == 200 else None
    if conf_id:
        print(f"\n[STEP 4] POST /api/v1/confirmations/{conf_id}/confirm")
        r = httpx.post(
            f"{API_BASE}/api/v1/confirmations/{conf_id}/confirm",
            headers=HEADERS,
            json={},
            timeout=60
        )
        log_response("confirmTrade", r)
        
        if r.status_code >= 500:
            print(f"\n[FAIL] confirmTrade returned 500")
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("[PASS] No 500 errors encountered")
    print("=" * 60)

if __name__ == "__main__":
    main()
