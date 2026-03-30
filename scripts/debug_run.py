import requests
import sys
import json

BASE_URL = "http://127.0.0.1:8000/api/v1"

def debug_run(run_id):
    headers = {
        "X-User-ID": "u_admin",
        "X-Dev-Tenant": "t_default",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.get(f"{BASE_URL}/runs/{run_id}", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        
        print(f"Run ID: {data['run']['run_id']}")
        print(f"Status: {data['run']['status']}")
        print(f"Mode: {data['run']['execution_mode']}")
        
        print("\nNodes:")
        for node in data['nodes']:
            print(f"  - {node['name']}: {node['status']} (Error: {node.get('error_json')})")
            
        print("\nApprovals:")
        for app in data['approvals']:
            print(f"  - {app['approval_id']}: {app['status']} / {app['decision']}")
            
        print("\nPolicy Events:")
        for pe in data['policy_events']:
            print(f"  - {pe['event_type']}: {pe['decision']}")

    except Exception as e:
        print(f"Error fetching run: {e}")
        if resp: print(resp.text)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_run.py <run_id>")
        sys.exit(1)
    debug_run(sys.argv[1])
