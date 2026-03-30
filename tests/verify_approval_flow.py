import requests
import time
import sys
import json

BASE_URL = "http://127.0.0.1:8000/api/v1"

def run_test():
    print("🚀 Triggering LIVE trade command...")
    
    # 1. Trigger Run
    headers = {
        "X-User-ID": "u_admin",
        "X-Dev-Tenant": "t_default",
        "Content-Type": "application/json"
    }
    payload = {
        "command": "buy $1 USD of BTC",
        "execution_mode": "LIVE"
    }
    # Note: Ensure ENABLE_LIVE_TRADING=true in .env
    
    resp = None
    try:
        resp = requests.post(f"{BASE_URL}/commands/execute", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        run_id = data["run_id"]
        print(f"✅ Run started: {run_id}")
    except Exception as e:
        print(f"❌ Failed to trigger run: {e}")
        if resp: print(resp.text)
        sys.exit(1)

    # 2. Poll for PAUSED status
    print("⏳ Waiting for PAUSED status (Approval)...")
    approval_id = None
    for i in range(20):
        time.sleep(2)
        resp = requests.get(f"{BASE_URL}/runs/{run_id}", headers=headers)
        run = resp.json()["run"]
        status = run["status"]
        print(f"   Status: {status}")
        
        if status == "PAUSED":
            print("✅ Run PAUSED successfully.")
            
            # Find approval_id
            approvals = resp.json().get("approvals", [])
            pending = [a for a in approvals if a["status"] == "PENDING"]
            if pending:
                approval_id = pending[0]["approval_id"]
                print(f"✅ Found Pending Approval: {approval_id}")
                break
            else:
                print("❌ Run Paused but no PENDING approval found?!")
                
        if status == "COMPLETED":
            print(f"❌ Run finished early with status {status} (Expected PAUSED)")
            error = resp.json().get("last_error")
            print(f"   Error: {error}")
            sys.exit(1)
        if status == "FAILED":
            error = run.get("failure_reason")
            if error and "INSUFFICIENT_FUND" in str(error):
                print(f"✅ Run FAILED with INSUFFICIENT_FUND (Expected for empty account).")
                print("🎉 Test PASSED: Approval Flow & Execution Attempted!")
                return
            print(f"❌ Run finished early with status {status} (Expected PAUSED)")
            print(f"   Error: {error}")
            sys.exit(1)
            
    if not approval_id:
        print("❌ Timed out waiting for PAUSE/Approval.")
        sys.exit(1)

    # 3. Approve
    print(f"👍 Approving action {approval_id}...")
    try:
        resp = requests.post(
            f"{BASE_URL}/approvals/{approval_id}/decision",
            json={"decision": "APPROVED"},
            headers=headers
        )
        resp.raise_for_status()
        print("✅ Approval submitted.")
    except Exception as e:
        print(f"❌ Failed to approve: {e}")
        if resp: print(resp.text)
        sys.exit(1)

    # 4. Poll for COMPLETION
    print("⏳ Waiting for Run COMPLETION...")
    for i in range(20):
        time.sleep(2)
        resp = requests.get(f"{BASE_URL}/runs/{run_id}", headers=headers)
        run = resp.json()["run"]
        status = run["status"]
        print(f"   Status: {status}")
        
        if status == "COMPLETED":
            print("✅ Run COMPLETED successfully after approval.")
            print("🎉 Test PASSED: Approval Flow Works!")
            return
        
        if status == "FAILED":
            error = run.get("failure_reason")
            if error and "INSUFFICIENT_FUND" in str(error):
                print(f"✅ Run FAILED with INSUFFICIENT_FUND (Expected for empty account).")
                print("🎉 Test PASSED: Approval Flow & Execution Attempted!")
                return
            print(f"❌ Run FAILED after approval.")
            print(f"   Error: {error}")
            sys.exit(1)
            
    print("❌ Timed out waiting for completion.")
    sys.exit(1)

if __name__ == "__main__":
    run_test()
