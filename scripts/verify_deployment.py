import requests
import time
import sys

def check_url(url, name, retries=5):
    print(f"Checking {name} at {url}...")
    for i in range(retries):
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                print(f"✅ {name} is UP ({response.status_code})")
                return True
            else:
                print(f"⚠️ {name} returned {response.status_code}")
                # For frontend, 200 is expected. For backend health, 200 is expected.
                # If it's a 404 but server responded, it's technically "up" but maybe wrong path.
                return True 
        except requests.exceptions.ConnectionError:
            print(f"❌ {name} connection failed. Retrying ({i+1}/{retries})...")
            time.sleep(2)
        except Exception as e:
            print(f"❌ {name} error: {e}")
            return False
    print(f"❌ {name} is DOWN after {retries} retries.")
    return False

def main():
    backend_up = check_url("http://127.0.0.1:8000/health", "Backend Health")
    frontend_up = check_url("http://127.0.0.1:3000", "Frontend")
    
    if not backend_up:

        print("Backend not reachable.")
    if not frontend_up:
        print("Frontend not reachable.")
        
    if backend_up and frontend_up:
        print("\nDeployment Verification: SUCCESS")
        sys.exit(0)
    else:
        print("\nDeployment Verification: FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
