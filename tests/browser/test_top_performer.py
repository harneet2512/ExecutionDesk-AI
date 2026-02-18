"""
Automated browser test for "top performer" feature.

Requirements:
    pip install playwright pytest
    playwright install chromium

Run:
    pytest tests/browser/test_top_performer.py -v --headed
"""
import pytest
import re
from playwright.sync_api import Page, expect


BASE_URL = "http://localhost:3000"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context."""
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
    }


def wait_for_assistant_response(page: Page, timeout: int = 30000):
    """Wait for assistant message to appear after user sends a message."""
    # Wait for loading indicator to disappear
    page.wait_for_selector('[data-testid="loading-indicator"]', state="hidden", timeout=timeout)
    # Wait for assistant message bubble
    page.wait_for_selector('.bg-slate-100.dark\\:bg-slate-800', timeout=timeout)


def check_console_errors(page: Page):
    """Check for console errors."""
    errors = []
    
    def on_console(msg):
        if msg.type == "error":
            errors.append(msg.text)
    
    page.on("console", on_console)
    return errors


class TestTopPerformer:
    """Test suite for top performer feature."""

    def test_10_minutes_window(self, page: Page):
        """Test Case 1: Buy $2 of highest performing crypto in last 10 minutes."""
        console_errors = check_console_errors(page)
        
        # Navigate to chat
        page.goto(f"{BASE_URL}/chat")
        page.wait_for_load_state("networkidle")
        
        # Type the command
        textarea = page.locator('textarea[placeholder*="Ask me anything"]')
        textarea.fill("Buy $2 of highest performing crypto in last 10 minutes")
        
        # Send message
        page.click('button:has-text("Send")')
        
        # Wait for response
        wait_for_assistant_response(page)
        
        # Verify: NO "which crypto?" prompt
        page_content = page.content()
        assert "which crypto" not in page_content.lower(), "Should not ask for clarification"
        
        # Verify: Selection Panel appears
        selection_panel = page.locator('[data-testid="selection-panel"]').or_(
            page.locator('text="Asset Selection"')
        )
        expect(selection_panel).to_be_visible(timeout=5000)
        
        # Verify: Window description mentions 10 minutes
        window_desc = page.locator('text=/10m|10 min|last 10 minutes/i')
        expect(window_desc).to_be_visible()
        
        # Verify: Return percentage is shown
        return_pct = page.locator('text=/[+-]?\\d+\\.\\d+%/')
        expect(return_pct).to_be_visible()
        
        # Verify: Financial Insight Card renders (NOT JSON)
        # Should have structured content, not raw JSON
        insight_card = page.locator('text="Why it matters for this trade"')
        expect(insight_card).to_be_visible(timeout=5000)
        
        # Verify: NOT raw JSON blob
        json_blob = page.locator('text=/"headline":/')
        expect(json_blob).not_to_be_visible()
        
        # Verify: Confirm/Cancel buttons appear
        confirm_btn = page.locator('button:has-text("Confirm")')
        cancel_btn = page.locator('button:has-text("Cancel")')
        expect(confirm_btn).to_be_visible()
        expect(cancel_btn).to_be_visible()
        expect(confirm_btn).to_be_enabled()
        expect(cancel_btn).to_be_enabled()
        
        # Take screenshot
        page.screenshot(path="test_results/test_10_minutes.png", full_page=True)
        
        # Check for console errors
        assert len(console_errors) == 0, f"Console errors found: {console_errors}"

    def test_1_week_window(self, page: Page):
        """Test Case 2: Buy $2 of highest performing crypto in last week."""
        console_errors = check_console_errors(page)
        
        # Navigate to chat
        page.goto(f"{BASE_URL}/chat")
        page.wait_for_load_state("networkidle")
        
        # Type the command
        textarea = page.locator('textarea[placeholder*="Ask me anything"]')
        textarea.fill("Buy $2 of highest performing crypto in last week")
        
        # Send message
        page.click('button:has-text("Send")')
        
        # Wait for response
        wait_for_assistant_response(page)
        
        # Verify: Selection Panel appears
        selection_panel = page.locator('text="Asset Selection"')
        expect(selection_panel).to_be_visible(timeout=5000)
        
        # Verify: Window description mentions week or 7 days
        window_desc = page.locator('text=/1w|7d|7 day|last week|week/i')
        expect(window_desc).to_be_visible()
        
        # Verify: Financial Insight Card renders
        insight_card = page.locator('text="Why it matters for this trade"')
        expect(insight_card).to_be_visible()
        
        # Take screenshot
        page.screenshot(path="test_results/test_1_week.png", full_page=True)
        
        # Check for console errors
        assert len(console_errors) == 0, f"Console errors found: {console_errors}"

    def test_7_weeks_window(self, page: Page):
        """Test Case 3: Buy $2 of highest performing crypto in last 7 weeks."""
        console_errors = check_console_errors(page)
        
        # Navigate to chat
        page.goto(f"{BASE_URL}/chat")
        page.wait_for_load_state("networkidle")
        
        # Type the command
        textarea = page.locator('textarea[placeholder*="Ask me anything"]')
        textarea.fill("Buy $2 of highest performing crypto in last 7 weeks")
        
        # Send message
        page.click('button:has-text("Send")')
        
        # Wait for response
        wait_for_assistant_response(page)
        
        # Verify: Selection Panel appears
        selection_panel = page.locator('text="Asset Selection"')
        expect(selection_panel).to_be_visible(timeout=5000)
        
        # Verify: Window description mentions weeks or ~49 days
        window_desc = page.locator('text=/7w|49d|7 week|weeks/i')
        expect(window_desc).to_be_visible()
        
        # Verify: Financial Insight Card renders
        insight_card = page.locator('text="Why it matters for this trade"')
        expect(insight_card).to_be_visible()
        
        # Take screenshot
        page.screenshot(path="test_results/test_7_weeks.png", full_page=True)
        
        # Check for console errors
        assert len(console_errors) == 0, f"Console errors found: {console_errors}"

    def test_api_response_structure(self, page: Page):
        """Validate API response contains selection_result and financial_insight."""
        # Set up network interception
        responses = []
        
        def handle_response(response):
            if "/api/v1/chat/execute" in response.url:
                responses.append(response.json())
        
        page.on("response", handle_response)
        
        # Navigate and send command
        page.goto(f"{BASE_URL}/chat")
        page.wait_for_load_state("networkidle")
        
        textarea = page.locator('textarea[placeholder*="Ask me anything"]')
        textarea.fill("Buy $2 of highest performing crypto in last 10 minutes")
        page.click('button:has-text("Send")')
        
        # Wait for response
        page.wait_for_timeout(5000)
        
        # Check API response structure
        assert len(responses) > 0, "No API responses captured"
        
        response_data = responses[-1]
        
        # Check for selection_result in metadata or direct response
        # (structure may vary based on backend implementation)
        assert "selection_result" in str(response_data) or "selection" in str(response_data), \
            "Response should contain selection_result"
        
        assert "financial_insight" in str(response_data) or "insight" in str(response_data), \
            "Response should contain financial_insight"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--headed", "-s"])
