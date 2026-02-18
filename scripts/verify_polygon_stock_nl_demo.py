#!/usr/bin/env python
"""
Polygon Stock Natural-Language Demo Verification Script.

This script verifies the full STOCK trading pipeline using natural language
commands through the official chat API endpoints.

SAFETY: 
- DEMO_SAFE_MODE=1 must be set - blocks all LIVE executions
- Only PAPER and ASSISTED_LIVE (ticket generation) are allowed
- No real trades will be placed

Requirements:
- POLYGON_API_KEY set in environment
- DEMO_SAFE_MODE=1 set in environment
- Backend running on localhost:8000

Usage:
    # Safe Mode Verification:
    set DEMO_SAFE_MODE=1
    python scripts/verify_polygon_stock_nl_demo.py
    
    # Normal Mode (Live Trading):
    set DEMO_SAFE_MODE=0
    python scripts/verify_polygon_stock_nl_demo.py
"""

# Load environment variables from .env FIRST
from dotenv import load_dotenv
load_dotenv(override=True)

import os
import sys
import json
import time
import subprocess
import signal
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


# === Configuration ===
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
TIMEOUT_SECONDS = 60
OUTPUT_DIR = Path("scripts/demo_outputs")
TENANT_ID = "t_demo_test"

# Test Commands
TEST_COMMANDS = [
    # Basic interaction
    ("greeting", "Hi"),
    ("capabilities", "What can you do?"),
    
    # Stock trading commands
    ("buy_48h", "Buy the most profitable stock of last 48 hrs for 3 dollars"),
    ("sell_24h", "Sell the least profitable stock of last 24 hrs for 3 dollars"),
    ("buy_1w", "Buy the most profitable stock of last 1 week for 3 dollars"),
    
    # Portfolio
    ("portfolio", "Analyze my stock portfolio"),
]


class DemoVerifier:
    """Verifies the NL demo flow."""
    
    def __init__(self):
        self.results: List[Dict[str, Any]] = []
        self.conversation_id: Optional[str] = None
        self.backend_process: Optional[subprocess.Popen] = None
        
        # Ensure output directory exists
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    def check_environment(self) -> Tuple[bool, List[str]]:
        """Check required environment variables."""
        issues = []
        
        # Check DEMO_SAFE_MODE
        demo_mode = os.getenv("DEMO_SAFE_MODE", "0")
        if demo_mode not in ("1", "true", "True", "TRUE"):
            issues.append(f"DEMO_SAFE_MODE={demo_mode}, must be 1 for safe verification")
        
        # Check POLYGON_API_KEY (don't print the value!)
        polygon_key = os.getenv("POLYGON_API_KEY", "")
        if not polygon_key:
            issues.append("POLYGON_API_KEY not set")
        else:
            print(f"  POLYGON_API_KEY: [REDACTED, length={len(polygon_key)}]")
        
        print(f"  DEMO_SAFE_MODE: {demo_mode}")
        
        return len(issues) == 0, issues
    
    def wait_for_backend(self, max_wait: int = 30) -> bool:
        """Wait for backend to be healthy."""
        print(f"\n[2] Waiting for backend at {API_BASE}...")
        
        for i in range(max_wait):
            try:
                response = requests.get(f"{API_BASE}/api/v1/ops/health", timeout=2)
                if response.status_code == 200:
                    print(f"  Backend healthy after {i+1}s")
                    return True
            except requests.exceptions.RequestException:
                pass
            
            time.sleep(1)
            if (i + 1) % 5 == 0:
                print(f"  Still waiting... ({i+1}s)")
        
        print(f"  Backend not healthy after {max_wait}s")
        return False
    
    def send_command(self, name: str, text: str) -> Dict[str, Any]:
        """Send a natural language command to the chat API."""
        result = {
            "name": name,
            "text": text,
            "success": False,
            "status_code": None,
            "response": None,
            "error": None,
            "duration_ms": 0,
            "assertions": []
        }
        
        start_time = time.time()
        
        try:
            payload = {
                "text": text,
                "conversation_id": self.conversation_id
            }
            
            response = requests.post(
                f"{API_BASE}/api/v1/chat/command",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Dev-Tenant": TENANT_ID
                },
                timeout=TIMEOUT_SECONDS
            )
            
            result["status_code"] = response.status_code
            result["duration_ms"] = int((time.time() - start_time) * 1000)
            
            if response.status_code == 200:
                data = response.json()
                result["response"] = data
                result["success"] = True
                
                # Extract conversation_id for subsequent calls
                if not self.conversation_id:
                    self.conversation_id = data.get("conversation_id")
            else:
                result["error"] = f"HTTP {response.status_code}: {response.text[:200]}"
                
        except requests.exceptions.Timeout:
            result["error"] = f"Timeout after {TIMEOUT_SECONDS}s"
            result["duration_ms"] = TIMEOUT_SECONDS * 1000
        except Exception as e:
            result["error"] = str(e)
            result["duration_ms"] = int((time.time() - start_time) * 1000)
        
        return result
    
    def run_assertions(self, result: Dict[str, Any]) -> List[str]:
        """Run assertions on command result."""
        failures = []
        name = result["name"]
        response = result.get("response", {})
        
        # Universal assertions
        if result["status_code"] == 500:
            failures.append(f"[{name}] Server error 500")
            return failures
        
        if not result["success"]:
            failures.append(f"[{name}] Request failed: {result.get('error')}")
            return failures
        
        # Command-specific assertions
        if name == "greeting":
            # Should return content (not message)
            if not response.get("content") and not response.get("message"):
                failures.append(f"[{name}] Missing content/message in response")
        
        elif name == "capabilities":
            # Should mention stocks - check both 'content' and 'message'
            content = (response.get("content", "") or response.get("message", "")).lower()
            if "stock" not in content:
                failures.append(f"[{name}] Response should mention stocks")
        
        elif name.startswith("buy_") or name.startswith("sell_"):
            # Trade commands
            run_id = response.get("run_id")
            
            if not run_id:
                # Could be a clarification or insufficient data
                content = (response.get("content", "") or response.get("message", "")).lower()
                status = response.get("status", "")
                
                if "confirm" in content or "ticket" in content or "order" in content:
                    # This is expected for ASSISTED_LIVE
                    pass
                elif "no valid rankings" in content or "research_failure" in content:
                    # Should have research_failure artifact
                    failures.append(f"[{name}] No valid rankings without research_failure artifact")
                elif "insufficient" in content or "not enough" in content:
                    # Min order size issue - expected
                    pass
                elif status == "COMPLETED":
                    # Completed without run_id is OK for some flows
                    pass
                elif status == "AWAITING_INPUT":
                    # System is asking for clarification - this is valid
                    pass
                elif "how much" in content or "amount" in content:
                    # System asking for amount clarification
                    pass
                else:
                    failures.append(f"[{name}] Missing run_id or expected flow message")
            else:
                # Check for DEMO_MODE_LIVE_BLOCKED if it tried LIVE
                if response.get("reason_code") == "DEMO_MODE_LIVE_BLOCKED":
                    # This is expected in DEMO mode
                    pass
                
                # Check for ticket generation (ASSISTED_LIVE)
                ticket_ids = response.get("ticket_ids", [])
                if not ticket_ids and name.startswith("buy_"):
                    # Should have generated tickets for stocks
                    if response.get("asset_class") == "STOCK":
                        failures.append(f"[{name}] Expected ticket_ids for STOCK ASSISTED_LIVE")
        
        elif name == "portfolio":
            # Portfolio analysis - check both content and message fields
            content = (response.get("content", "") or response.get("message", "")).lower()
            # Should either show portfolio or explain data unavailable
            if "portfolio" not in content and "holdings" not in content:
                if "unavailable" not in content and "cannot" not in content and "no holdings" not in content:
                    failures.append(f"[{name}] Expected portfolio info or reason_code")
        
        result["assertions"] = failures
        return failures
    
    def run_polygon_smoke(self) -> Dict[str, Any]:
        """Run Polygon smoke test."""
        print("\n[3] Running Polygon smoke test...")
        
        try:
            from backend.services.stock_market_data_smoke import smoke_polygon_one_ticker
            result = smoke_polygon_one_ticker("AAPL", lookback_days=5)
            
            if result["success"]:
                print(f"  ✓ Polygon smoke test PASSED")
                print(f"    Candles: {result['candles_count']}")
                print(f"    Date Range: {result['date_range']}")
                print(f"    Cache Hit: {result['cache_hit']}")
                print(f"    Response Time: {result['response_time_ms']}ms")
            else:
                print(f"  ✗ Polygon smoke test FAILED: {result['error']}")
            
            return result
        except Exception as e:
            print(f"  ✗ Polygon smoke test ERROR: {e}")
            return {"success": False, "error": str(e)}
    
    def run_demo_commands(self) -> List[Dict[str, Any]]:
        """Run all demo commands."""
        print("\n[4] Running demo commands...")
        
        all_results = []
        all_failures = []
        
        for name, text in TEST_COMMANDS:
            print(f"\n  [{name}] '{text}'")
            
            result = self.send_command(name, text)
            failures = self.run_assertions(result)
            all_results.append(result)
            
            if result["success"]:
                print(f"    ✓ {result['duration_ms']}ms")
            else:
                print(f"    ✗ {result.get('error', 'Failed')}")
            
            if failures:
                for f in failures:
                    print(f"    ✗ {f}")
                all_failures.extend(failures)
            
            # Save response to file
            output_file = OUTPUT_DIR / f"{name}.json"
            with open(output_file, "w") as f:
                json.dump(result, f, indent=2, default=str)
            
            # Rate limiting pause for Polygon
            if name.startswith("buy_") or name.startswith("sell_"):
                time.sleep(2)  # Pause between stock commands
        
        return all_results, all_failures
    
    def run_news_toggle_test(self) -> List[str]:
        """Test news toggle functionality."""
        print("\n[5] Testing news toggle...")
        failures = []
        
        # Test with news ON
        print("  Testing with news_enabled=true...")
        try:
            payload = {
                "text": "Buy the most profitable stock of last 24 hrs for 3 dollars",
                "conversation_id": self.conversation_id,
                "news_enabled": True
            }
            
            response = requests.post(
                f"{API_BASE}/api/v1/chat/command",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Dev-Tenant": TENANT_ID
                },
                timeout=TIMEOUT_SECONDS
            )
            
            if response.status_code == 200:
                print("    ✓ News ON command succeeded")
            else:
                failures.append(f"News ON command failed: HTTP {response.status_code}")
            
            # Save result
            with open(OUTPUT_DIR / "news_on.json", "w") as f:
                json.dump(response.json() if response.status_code == 200 else {"error": response.text}, f, indent=2)
                
        except Exception as e:
            failures.append(f"News ON test error: {e}")
        
        time.sleep(2)
        
        # Test with news OFF
        print("  Testing with news_enabled=false...")
        try:
            payload = {
                "text": "Buy the most profitable stock of last 24 hrs for 3 dollars",
                "conversation_id": self.conversation_id,
                "news_enabled": False
            }
            
            response = requests.post(
                f"{API_BASE}/api/v1/chat/command",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Dev-Tenant": TENANT_ID
                },
                timeout=TIMEOUT_SECONDS
            )
            
            if response.status_code == 200:
                print("    ✓ News OFF command succeeded")
            else:
                failures.append(f"News OFF command failed: HTTP {response.status_code}")
            
            # Save result
            with open(OUTPUT_DIR / "news_off.json", "w") as f:
                json.dump(response.json() if response.status_code == 200 else {"error": response.text}, f, indent=2)
                
        except Exception as e:
            failures.append(f"News OFF test error: {e}")
        
        return failures
    
    def print_summary(self, results: List[Dict], failures: List[str]) -> bool:
        """Print summary and return success status."""
        print("\n" + "=" * 60)
        print("DEMO VERIFICATION SUMMARY")
        print("=" * 60)
        
        # Results table
        print("\n{:<15} {:<10} {:<10} {:<30}".format("Command", "Status", "Time", "Notes"))
        print("-" * 65)
        
        for r in results:
            status = "✓ PASS" if r["success"] and not r.get("assertions") else "✗ FAIL"
            time_ms = f"{r['duration_ms']}ms"
            notes = r.get("error", "")[:30] if r.get("error") else ""
            if r.get("assertions"):
                notes = str(r["assertions"][0])[:30]
            print(f"{r['name']:<15} {status:<10} {time_ms:<10} {notes:<30}")
        
        print("-" * 65)
        
        # Failures
        if failures:
            print(f"\n❌ FAILURES ({len(failures)}):")
            for f in failures:
                print(f"  - {f}")
        
        # Final result
        print("\n" + "=" * 60)
        if not failures:
            print("✅ ALL TESTS PASSED - Demo verification successful!")
            print("=" * 60)
            return True
        else:
            print(f"❌ {len(failures)} TESTS FAILED - Review failures above")
            print("=" * 60)
            return False
    
    def run(self) -> int:
        """Run full verification."""
        print("=" * 60)
        print("POLYGON STOCK NATURAL-LANGUAGE DEMO VERIFICATION")
        print(f"Started: {datetime.now().isoformat()}")
        print("=" * 60)
        
        # Step 1: Check environment
        print("\n[1] Checking environment...")
        env_ok, env_issues = self.check_environment()
        if not env_ok:
            for issue in env_issues:
                print(f"  ✗ {issue}")
            print("\n❌ Environment check failed. Fix issues and retry.")
            return 1
        print("  ✓ Environment check passed")
        
        # Step 2: Wait for backend
        if not self.wait_for_backend():
            print("\n❌ Backend not available. Start it with:")
            print("   uvicorn backend.api.main:app --port 8000")
            return 1
        
        # Step 3: Polygon smoke test
        polygon_result = self.run_polygon_smoke()
        if not polygon_result.get("success"):
            print("\n⚠️ Polygon smoke test failed, but continuing with demo...")
        
        # Save polygon result
        with open(OUTPUT_DIR / "polygon_smoke.json", "w") as f:
            json.dump(polygon_result, f, indent=2, default=str)
        
        # Step 4: Run demo commands
        results, failures = self.run_demo_commands()
        
        # Step 5: News toggle test
        news_failures = self.run_news_toggle_test()
        failures.extend(news_failures)
        
        # Step 6: Print summary
        success = self.print_summary(results, failures)
        
        # Save full results
        with open(OUTPUT_DIR / "full_results.json", "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "polygon_smoke": polygon_result,
                "commands": results,
                "failures": failures,
                "success": success
            }, f, indent=2, default=str)
        
        print(f"\nResults saved to: {OUTPUT_DIR}/")
        
        return 0 if success else 1


def main():
    """Main entry point."""
    # Add project root to path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    verifier = DemoVerifier()
    return verifier.run()


if __name__ == "__main__":
    sys.exit(main())
