# 🚀 Quick Start: Testing Top Performer Feature

Since browser automation tools weren't available in this session, I've created comprehensive testing resources for you to run locally.

## 📦 What You Have

I've created **7 files** to help you test the "top performer" feature:

### 📋 Documentation
1. **`TESTING_SUMMARY.md`** ← **START HERE** - Overview of all resources
2. **`TEST_TOP_PERFORMER.md`** - Detailed manual testing guide
3. **`VISUAL_CHECKLIST.md`** - UI element verification checklist
4. **`tests/browser/README.md`** - Automation setup guide

### 🤖 Automated Tests
5. **`tests/browser/test_top_performer.py`** - Playwright tests (Python)
6. **`tests/browser/test_top_performer_puppeteer.js`** - Puppeteer tests (Node.js)

### 🎯 Quick Runners
7. **`run_tests.ps1`** - PowerShell test runner (Windows)
8. **`run_tests.sh`** - Bash test runner (Linux/Mac)

---

## ⚡ Fastest Way to Test

### Option 1: Manual (Recommended First) - 5 minutes

```powershell
# 1. Make sure services are running
# Terminal 1: Backend
uvicorn backend.api.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev

# 2. Open the guide
notepad TEST_TOP_PERFORMER.md

# 3. Open browser
start http://localhost:3000/chat

# 4. Follow the test steps in the guide
```

### Option 2: Automated - 2 minutes setup + 2 minutes run

```powershell
# One command to run all tests
.\run_tests.ps1 puppeteer

# OR if you prefer Python
.\run_tests.ps1 playwright
```

---

## 📝 What Gets Tested

All three test cases:

1. **"Buy $2 of highest performing crypto in last 10 minutes"**
2. **"Buy $2 of highest performing crypto in last week"**
3. **"Buy $2 of highest performing crypto in last 7 weeks"**

Each verifies:
- ✅ No "which crypto?" clarification prompt
- ✅ Selection Panel with correct window (10m / 1w / 7w)
- ✅ Financial Insight Card renders properly (NOT JSON)
- ✅ Confirm/Cancel buttons appear
- ✅ No console errors

---

## 🎯 Expected Visual Result

When working correctly, you should see:

```
┌─────────────────────────────────────────────────────────────┐
│ [User Bubble]                                               │
│ "Buy $2 of highest performing crypto in last 10 minutes"   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ [Assistant Bubble]                                          │
│                                                             │
│ "I found the highest performer: BTC-USD returned +2.34%    │
│ in the last 10 minutes. Ready to buy $2?"                  │
│                                                             │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ Asset Selection                          [Fallback?] │  │
│ │                                                       │  │
│ │ ┌─────────────────────────────────────────────────┐  │  │
│ │ │ [B]  BTC-USD                      +2.34%        │  │  │
│ │ │      Selected from tradeable...   10m           │  │  │
│ │ └─────────────────────────────────────────────────┘  │  │
│ │                                                       │  │
│ │ Top Candidates (10 evaluated)                        │  │
│ │ 1. BTC-USD  $50000 → $51170  +2.34% ← SELECTED      │  │
│ │ 2. ETH-USD  $3000 → $3065    +2.17%                 │  │
│ │ 3. SOL-USD  $100 → $102      +2.00%                 │  │
│ │                                                       │  │
│ │ BTC-USD showed the strongest performance...          │  │
│ └───────────────────────────────────────────────────────┘  │
│                                                             │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ BTC-USD shows strong 10-minute momentum  [85%] [AI]  │  │
│ │                                                       │  │
│ │ [Price] $51170  [24h] +1.2%  [Vol] Medium            │  │
│ │                                                       │  │
│ │ Why it matters for this trade                        │  │
│ │ Short-term momentum suggests buying opportunity...   │  │
│ │                                                       │  │
│ │ [High Volatility] [Paper Mode]                       │  │
│ │                                                       │  │
│ │ News Pulse: Bullish (3↑ 1↓ 1—) · 5 sources          │  │
│ │                                                       │  │
│ │ Recent Headlines                                     │  │
│ │ ↑ Bitcoin surges on institutional demand            │  │
│ │   Positive signal: "institutional demand"            │  │
│ │   Reuters · 2h ago                                   │  │
│ └───────────────────────────────────────────────────────┘  │
│                                                             │
│ [Confirm Trade]  [Cancel]                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔍 Quick Validation

After sending the test command:

1. **Look for these elements:**
   - [ ] Blue/white bordered panel with "Asset Selection" header
   - [ ] Selected asset name in bold (e.g., BTC-USD)
   - [ ] Return percentage with + or - sign
   - [ ] Window description (10m / 1w / 7w)
   - [ ] "Why it matters for this trade" section
   - [ ] Colored metric chips (Price, 24h, Volatility)
   - [ ] Recent headlines with sentiment arrows
   - [ ] Green "Confirm Trade" button
   - [ ] Red/gray "Cancel" button

2. **Check console (F12):**
   - [ ] No red error messages

3. **Verify NOT present:**
   - [ ] Raw JSON like `{"headline": ...}`
   - [ ] "Which crypto do you want?" prompt

---

## 🐛 Troubleshooting

### Issue: "Connection refused"
```powershell
# Backend not running - start it:
uvicorn backend.api.main:app --reload --port 8000

# Frontend not running - start it:
cd frontend
npm run dev
```

### Issue: Raw JSON displayed
**Cause:** FinancialInsightCard component not rendering

**Check:**
1. Browser console for errors
2. `frontend/components/FinancialInsightCard.tsx` exists
3. Import in `frontend/app/chat/page.tsx` line 35

### Issue: Selection Panel missing
**Cause:** Backend not returning `selection_result`

**Check:**
1. Network tab shows 200 response
2. Response includes `metadata_json.selection_result`
3. Backend logs for intent parsing

---

## 📊 Test Results

All tests save screenshots to `test_results/`:
- `test_10_minutes.png` - Test case 1
- `test_1_week.png` - Test case 2  
- `test_7_weeks.png` - Test case 3
- `*_error.png` - Failure screenshots

---

## 📚 Documentation Map

```
TESTING_SUMMARY.md ← Overview (read first)
├── TEST_TOP_PERFORMER.md ← Manual steps
├── VISUAL_CHECKLIST.md ← UI verification
└── tests/browser/README.md ← Automation setup
    ├── test_top_performer.py ← Playwright
    └── test_top_performer_puppeteer.js ← Puppeteer
```

---

## ✅ Success Looks Like

**Console Output (Automated):**
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

## 🎬 Next Steps

1. **Start services** (backend + frontend)
2. **Choose testing method:**
   - Quick: `.\run_tests.ps1 manual`
   - Automated: `.\run_tests.ps1 puppeteer`
3. **Review results** in `test_results/`
4. **Report findings** using template in `TEST_TOP_PERFORMER.md`

---

## 💡 Pro Tips

- Start with **manual testing** to understand the UI flow
- Use **automated tests** for regression testing
- Check **VISUAL_CHECKLIST.md** while manually testing
- Save screenshots showing successful UI rendering
- If tests fail, check `test_results/*_error.png`

---

## 📞 Need Help?

1. Check `tests/browser/README.md` troubleshooting section
2. Review component source code:
   - `frontend/components/SelectionPanel.tsx`
   - `frontend/components/FinancialInsightCard.tsx`
   - `frontend/app/chat/page.tsx` (lines 1044-1054)
3. Inspect backend response in Network tab (F12)

---

**Ready to test?** Run: `.\run_tests.ps1 manual`
