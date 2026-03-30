import requests
import time
import json
import sys
import os

BASE_URL = "http://localhost:8000/api/v1"

def diagnose():
    print("🚀 Starting diagnosis of 'Analyze my portfolio' hang...")
    
    headers = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}
    
    # 1. Create Conversation
    print("1️⃣ Creating conversation...")
    try:
        res = requests.post(f"{BASE_URL}/conversations/", json={"title": "Debug Portfolio"}, headers=headers)
        res.raise_for_status()
        conv_id = res.json()["conversation_id"]
        print(f"   Conversation ID: {conv_id}")
    except Exception as e:
        print(f"❌ Failed to create conversation: {e}")
        sys.exit(1)

    # 2. Send Command
    print("2️⃣ Sending 'Analyze my portfolio' command...")
    run_id = None
    try:
        cmd_res = requests.post(
            f"{BASE_URL}/chat/command",
            json={"text": "Analyze my portfolio", "conversation_id": conv_id},
            headers=headers
        )
        if cmd_res.status_code != 200:
            print(f"❌ Command failed: {cmd_res.status_code} {cmd_res.text}")
            sys.exit(1)
            
        data = cmd_res.json()
        print(f"   Response: {json.dumps(data, indent=2)}")
        
        run_id = data.get("run_id")
        if not run_id:
            print("❌ No run_id returned! (Message-only response?)")
            sys.exit(1)
        print(f"   Run ID: {run_id}")
            
    except Exception as e:
        print(f"❌ Command exception: {e}")
        sys.exit(1)

    # 3. Poll Trace
    print(f"3️⃣ Polling trace for run {run_id} (timeout 30s)...")
    start_time = time.time()
    last_status = None
    
    while time.time() - start_time < 30:
        try:
            trace_res = requests.get(f"{BASE_URL}/debug/run_trace/{run_id}", headers=headers)
            if trace_res.status_code == 200:
                trace = trace_res.json()
                status = trace.get("status")
                node_statuses = trace.get("node_statuses", [])
                
                # Print progress if changed
                if status != last_status:
                    print(f"   Run Status: {status}")
                    last_status = status
                
                # Check nodes
                for node in node_statuses:
                    print(f"   Node {node['name']}: {node['status']}")
                    if node['status'] == 'FAILED':
                        print(f"❌ Node FAILED! Error: {node.get('error_json')}")
                        sys.exit(1)
                
                if status in ["COMPLETED", "FAILED"]:
                    print(f"✅ Run finished with status: {status}")
                    
                    if status == "FAILED":
                        print("❌ Run FAILED in orchestrator.")
                        sys.exit(1)
                    sys.exit(0)
            
            else:
                print(f"⚠️ Failed to get trace: {trace_res.status_code}")
                if trace_res.status_code == 500:
                    print(trace_res.text)
                
        except Exception as e:
            print(f"⚠️ Polling error: {e}")
            
        time.sleep(1)

    print("❌ TIMEOUT: Run did not complete in 30 seconds.")
    
    # Final Dump
    print("\ndumping final state:")
    try:
        final_trace = requests.get(f"{BASE_URL}/debug/run_trace/{run_id}", headers=headers).json()
        print(json.dumps(final_trace, indent=2))
    except:
        pass
    
    sys.exit(1)

if __name__ == "__main__":
    diagnose()
