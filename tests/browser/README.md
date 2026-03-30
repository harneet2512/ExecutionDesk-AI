# Browser Tests for Top Performer Feature

This directory contains automated browser tests for the "top performer" feature.

## Prerequisites

1. **Backend running**: Port 8000
2. **Frontend running**: Port 3000
3. **Test dependencies installed** (choose one approach below)

## Option 1: Playwright (Python)

### Install
```bash
pip install playwright pytest
playwright install chromium
```

### Run Tests
```bash
# Run all tests with browser visible
pytest tests/browser/test_top_performer.py -v --headed

# Run headless (CI/CD)
pytest tests/browser/test_top_performer.py -v

# Run specific test
pytest tests/browser/test_top_performer.py::TestTopPerformer::test_10_minutes_window -v --headed
```

### Test Output
- Screenshots saved to `test_results/`
- Console output shows pass/fail for each assertion
- Detailed error messages if tests fail

---

## Option 2: Puppeteer (Node.js)

### Install
```bash
npm install puppeteer
```

### Run Tests
```bash
node tests/browser/test_top_performer_puppeteer.js
```

### Test Output
- Screenshots saved to `test_results/`
- Console shows step-by-step progress
- Browser window opens automatically (set `headless: true` for CI/CD)

---

## Option 3: Manual Testing

Follow the comprehensive guide in `TEST_TOP_PERFORMER.md` for manual step-by-step testing.

---

## Test Cases

All test suites validate these three scenarios:

### Test 1: "Buy $2 of highest performing crypto in last 10 minutes"
- ✅ No clarification prompt
- ✅ Selection Panel with 10m window
- ✅ Financial Insight Card (not JSON)
- ✅ Confirm/Cancel buttons

### Test 2: "Buy $2 of highest performing crypto in last week"
- ✅ Selection Panel with ~7 day window
- ✅ Financial Insight Card renders
- ✅ Proper window description

### Test 3: "Buy $2 of highest performing crypto in last 7 weeks"
- ✅ Selection Panel with ~49 day window
- ✅ Financial Insight Card renders
- ✅ Proper window description

---

## Troubleshooting

### "Connection refused" errors
**Cause**: Backend or frontend not running

**Fix**:
```bash
# Terminal 1: Start backend
cd backend
uvicorn backend.api.main:app --reload --port 8000

# Terminal 2: Start frontend
cd frontend
npm run dev
```

### "Timeout waiting for selector" errors
**Cause**: Page elements not loading or changed class names

**Fix**:
- Check browser console for errors
- Verify Selection Panel component is rendering
- Inspect element class names in DevTools

### Tests fail but UI looks correct
**Cause**: Selector mismatch or timing issue

**Fix**:
- Check test selectors match actual HTML
- Increase timeout values in test code
- Add `await page.waitForTimeout(2000)` after interactions

### Screenshots not saved
**Cause**: Results directory doesn't exist

**Fix**:
```bash
mkdir -p test_results
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Browser Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install playwright pytest
          playwright install chromium
      
      - name: Start services
        run: |
          docker-compose up -d
          sleep 10
      
      - name: Run tests
        run: pytest tests/browser/test_top_performer.py -v
      
      - name: Upload screenshots
        if: failure()
        uses: actions/upload-artifact@v3
        with:
          name: test-screenshots
          path: test_results/
```

---

## Test Results Format

Example successful output:

```
=== Test Case 1: 10 minutes window ===
Sending: "Buy $2 of highest performing crypto in last 10 minutes"
✅ No clarification prompt
✅ Selection Panel found
✅ Window description found
✅ Return percentage displayed
✅ Financial Insight Card rendered properly
✅ Confirm/Cancel buttons present
✅ No console errors
📸 Screenshot saved: test_results/test_10_minutes.png
✅ Test Case 1: PASSED

==================================================
📊 TEST SUMMARY
==================================================
Test 1 (10 minutes): ✅ PASSED
Test 2 (1 week):     ✅ PASSED
Test 3 (7 weeks):    ✅ PASSED
==================================================
Overall: 3/3 tests passed
🎉 All tests passed!
```

---

## Extending Tests

To add new test cases:

1. **Playwright**: Add methods to `TestTopPerformer` class
2. **Puppeteer**: Add async functions and call in `runTests()`
3. Follow existing patterns for selectors and assertions

Example new test:
```python
def test_custom_window(self, page: Page):
    """Test custom time window."""
    page.goto(f"{BASE_URL}/chat")
    textarea = page.locator('textarea[placeholder*="Ask me anything"]')
    textarea.fill("Buy $2 of highest performing crypto in last 3 days")
    page.click('button:has-text("Send")')
    wait_for_assistant_response(page)
    
    # Add your assertions
    window_desc = page.locator('text=/3d|3 day/')
    expect(window_desc).to_be_visible()
```

---

## Support

If tests fail unexpectedly:

1. Check `TEST_TOP_PERFORMER.md` for manual verification steps
2. Inspect browser screenshots in `test_results/`
3. Review backend logs for API errors
4. Check frontend console in browser DevTools
5. Verify component imports in `frontend/app/chat/page.tsx`:
   - Line 35: `FinancialInsightCard`
   - Line 36: `SelectionPanel`
