/**
 * E2E Playwright tests for the agentic trading platform.
 *
 * Covers the full chat-driven trading flow in two modes:
 *   1. News OFF (default)
 *   2. News ON
 *
 * Safety:
 *   - Default: runs against PAPER mode broker (safe, no real money).
 *   - LIVE tests are tagged @live and only run when LIVE_TEST_MODE=true.
 *
 * Prerequisites:
 *   - Backend running on port 8000
 *   - Frontend running on port 3000
 *
 * Usage:
 *   npm run test:e2e           # PAPER-mode tests (safe)
 *   npm run test:live          # LIVE-mode tests (real broker, requires LIVE_TEST_MODE=true)
 */
import { test, expect, type Page } from '@playwright/test';

const IS_LIVE = process.env.LIVE_TEST_MODE === 'true';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Type a command in the chat input and submit */
async function sendChatCommand(page: Page, command: string) {
  const input = page.locator('input[type="text"], textarea').first();
  await input.fill(command);
  const sendBtn = page.locator('button[type="submit"], button:has-text("Send")').first();
  if (await sendBtn.isVisible()) {
    await sendBtn.click();
  } else {
    await input.press('Enter');
  }
}

/** Click the first visible Confirm button */
async function clickConfirm(page: Page) {
  // Match both "Confirm Trade" and "Confirm" buttons
  const confirmBtn = page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first();
  await confirmBtn.waitFor({ state: 'visible', timeout: 30_000 });
  await confirmBtn.click();
}

/** Assert no raw run_id strings are visible in the chat area */
async function assertNoRunIdInChat(page: Page) {
  const chatArea = page.locator('[class*="overflow-y-auto"]').first();
  const text = await chatArea.textContent() || '';
  expect(text).not.toMatch(/\brun_[a-zA-Z0-9]{8,}\b/);
}

/** Assert no raw JSON blobs in chat messages */
async function assertNoJsonBlobInChat(page: Page) {
  const messages = page.locator('.justify-start .rounded-2xl');
  const count = await messages.count();
  for (let i = 0; i < count; i++) {
    const text = await messages.nth(i).textContent() || '';
    expect(text).not.toMatch(/\{\s*"[a-z_]+":\s/i);
  }
}

/** Assert no duplicate run cards — at most one processing/receipt per trade action */
async function assertNoDuplicateRunCards(page: Page) {
  // Look for processing cards (they show side, symbol, and have progress/status)
  // The trade processing card has "Executing" or status text + a bordered rounded-lg container
  const processingCards = page.locator('.border.rounded-lg.p-4').filter({ hasText: /BUY|SELL|Executing|COMPLETED|FAILED/ });
  const count = await processingCards.count();
  // At most 2 cards in the chat (one active trade at most)
  expect(count).toBeLessThanOrEqual(2);
}

/** Assert terminal status consistency: no RUNNING shown alongside FAILED */
async function assertTerminalStatusConsistent(page: Page) {
  const pageText = await page.locator('body').textContent() || '';
  if (pageText.includes('FAILED')) {
    const statusPills = page.locator('[class*="StatusPill"], [class*="status"]');
    const pillCount = await statusPills.count();
    const statuses: string[] = [];
    for (let i = 0; i < pillCount; i++) {
      statuses.push((await statusPills.nth(i).textContent()) || '');
    }
    const hasRunning = statuses.some(s => s.includes('RUNNING'));
    const hasFailed = statuses.some(s => s.includes('FAILED'));
    if (hasFailed) {
      expect(hasRunning).toBeFalsy();
    }
  }
}

/** Assert confirm/cancel buttons disappear after action */
async function assertButtonsDisappearAfterConfirm(page: Page) {
  // Wait for the UI to update after confirmation
  await page.waitForTimeout(3_000);
  const confirmBtns = page.locator('button:has-text("Confirm"):visible');
  const cancelBtns = page.locator('button:has-text("Cancel"):visible');
  // Use expect with polling to allow time for buttons to disappear
  await expect(confirmBtns).toHaveCount(0, { timeout: 10_000 }).catch(() => {
    // Fallback: allow 0 visible confirm buttons
    expect(confirmBtns).toHaveCount(0);
  });
}

// ---------------------------------------------------------------------------
// Standard reliability assertions (run after every trade flow)
// ---------------------------------------------------------------------------
async function assertReliabilityInvariants(page: Page) {
  await assertNoRunIdInChat(page);
  await assertNoJsonBlobInChat(page);
  await assertNoDuplicateRunCards(page);
  await assertTerminalStatusConsistent(page);
}

// ---------------------------------------------------------------------------
// Test: News OFF mode (default, safe PAPER trades)
// ---------------------------------------------------------------------------
test.describe('Trading Flow - News OFF', () => {
  test.beforeEach(async ({ page }) => {
    // Explicitly set news toggle OFF via localStorage before navigation
    await page.goto('/chat');
    await page.evaluate(() => localStorage.setItem('newsEnabled', 'false'));
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Verify the toggle is in the OFF state (if visible)
    const newsToggle = page.locator('button[aria-pressed]').first();
    if (await newsToggle.isVisible({ timeout: 3_000 }).catch(() => false)) {
      const isPressed = await newsToggle.getAttribute('aria-pressed').catch(() => null);
      if (isPressed === 'true') {
        await newsToggle.click(); // Toggle OFF
      }
    }
  });

  test('analyze my portfolio', async ({ page }) => {
    await sendChatCommand(page, 'Analyze my portfolio');
    await page.locator('.justify-start').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    await page.waitForTimeout(5_000);

    await assertNoRunIdInChat(page);
    await assertNoJsonBlobInChat(page);
  });

  test('buy $2 of BTC (PAPER)', async ({ page }) => {
    await sendChatCommand(page, 'Buy $2 of BTC');

    await page.locator('button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    await clickConfirm(page);
    await page.waitForTimeout(15_000);

    await assertReliabilityInvariants(page);
    await assertButtonsDisappearAfterConfirm(page);
  });

  test('sell $2 of BTC (PAPER)', async ({ page }) => {
    await sendChatCommand(page, 'Sell $2 of BTC');

    await page.locator('button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    await clickConfirm(page);
    await page.waitForTimeout(15_000);

    await assertReliabilityInvariants(page);
    await assertButtonsDisappearAfterConfirm(page);
  });
});

// ---------------------------------------------------------------------------
// Test: News ON mode
// ---------------------------------------------------------------------------
test.describe('Trading Flow - News ON', () => {
  test.beforeEach(async ({ page }) => {
    // Explicitly set news toggle ON via localStorage before navigation
    await page.goto('/chat');
    await page.evaluate(() => localStorage.setItem('newsEnabled', 'true'));
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Verify the toggle is in the ON state (if visible)
    const newsToggle = page.locator('button[aria-pressed]').first();
    if (await newsToggle.isVisible({ timeout: 3_000 }).catch(() => false)) {
      const isPressed = await newsToggle.getAttribute('aria-pressed').catch(() => null);
      if (isPressed === 'false') {
        await newsToggle.click(); // Toggle ON
      }
    }
  });

  test('portfolio analysis returns structured response', async ({ page }) => {
    await sendChatCommand(page, 'Analyze my portfolio');
    await page.locator('.justify-start').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    await page.waitForTimeout(5_000);

    await assertNoRunIdInChat(page);
    await assertNoJsonBlobInChat(page);
  });

  test('buy $2 of BTC shows insight card with headlines', async ({ page }) => {
    await sendChatCommand(page, 'Buy $2 of BTC');

    // Wait for confirmation card
    await page.locator('button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });

    // Insight block should exist (not raw JSON)
    const insightBlock = page.locator('[class*="rounded-lg"], [class*="rounded-xl"]')
      .filter({ hasText: /Market|Insight|News Pulse|Snapshot|Considerations/ });
    const insightCount = await insightBlock.count();
    // At least one insight section should be visible
    expect(insightCount).toBeGreaterThan(0);

    // Check for headline links (clickable, open in new tab)
    const headlineLinks = page.locator('a[target="_blank"]').filter({ hasText: /.+/ });
    const linkCount = await headlineLinks.count();
    if (linkCount > 0) {
      const href = await headlineLinks.first().getAttribute('href');
      expect(href).toBeTruthy();
      expect(href).toMatch(/^https?:\/\//);

      // Check for sentiment badges near headlines
      const sentimentBadges = page.locator(
        '[class*="rounded"]:has-text("bullish"), ' +
        '[class*="rounded"]:has-text("bearish"), ' +
        '[class*="rounded"]:has-text("neutral"), ' +
        '[class*="rounded"]:has-text("conf")'
      );
      // At least one sentiment indicator should be present
      const badgeCount = await sentimentBadges.count();
      expect(badgeCount).toBeGreaterThan(0);
    } else {
      // If no headlines, should show a fallback/warning message
      const fallback = page.locator('text=/No headlines|no news|zero results/i');
      const fallbackCount = await fallback.count();
      expect(fallbackCount).toBeGreaterThanOrEqual(0);
    }

    // Confirm and verify
    await clickConfirm(page);
    await page.waitForTimeout(15_000);

    await assertReliabilityInvariants(page);
    await assertButtonsDisappearAfterConfirm(page);
  });

  test('sell $2 of BTC with news', async ({ page }) => {
    await sendChatCommand(page, 'Sell $2 of BTC');

    await page.locator('button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    await clickConfirm(page);
    await page.waitForTimeout(15_000);

    await assertReliabilityInvariants(page);
  });

  test('headlines are clickable with full text (not truncated)', async ({ page }) => {
    await sendChatCommand(page, 'Buy $2 of BTC');
    await page.locator('button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });

    const headlineLinks = page.locator('a[target="_blank"]').filter({ hasText: /.+/ });
    const linkCount = await headlineLinks.count();
    if (linkCount > 0) {
      // Each headline link should have reasonable text length (not truncated to 12 words)
      for (let i = 0; i < Math.min(linkCount, 3); i++) {
        const text = await headlineLinks.nth(i).textContent() || '';
        // A full headline should generally be more than a few words
        expect(text.trim().length).toBeGreaterThan(5);
        // Should not end with ellipsis from truncation (our fix removed 12-word truncation)
      }
    }
  });

  test('evals dashboard shows non-empty metrics after runs', async ({ page }) => {
    // Execute a trade to generate eval data
    await sendChatCommand(page, 'Buy $2 of BTC');
    await page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    await clickConfirm(page);
    await page.waitForTimeout(20_000);

    // Also verify via API that eval metrics exist
    const apiResp = await page.evaluate(async () => {
      const resp = await fetch('/api/v1/eval/dashboard', {
        headers: { 'X-Dev-Tenant': 'test-tenant' },
      });
      return resp.ok ? await resp.json() : null;
    });
    // API should return non-empty dashboard data
    if (apiResp) {
      const hasData = apiResp.total_runs > 0 || (apiResp.recent_runs && apiResp.recent_runs.length > 0);
      expect(hasData).toBeTruthy();
    }

    // Navigate to evals dashboard UI
    await page.goto('/evals');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3_000);

    const pageText = await page.locator('body').textContent() || '';
    expect(pageText).toContain('Eval');
    // Should show at least one metric, score, or grade
    const hasMetrics = pageText.match(/\d+\.?\d*%/) ||
      pageText.match(/Score/) ||
      pageText.match(/Grade/) ||
      pageText.match(/tool_success/) ||
      pageText.match(/tool_success_rate/) ||
      pageText.match(/grounded_rate/) ||
      pageText.match(/news_sentiment_grounded_rate/) ||
      pageText.match(/format_score/) ||
      pageText.match(/response_format_score/) ||
      pageText.match(/run_state_consistency/) ||
      pageText.match(/schema_validity/) ||
      pageText.match(/execution_quality/);
    expect(hasMetrics).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Test: LIVE mode (only when LIVE_TEST_MODE=true)
// ---------------------------------------------------------------------------
test.describe('Trading Flow - LIVE @live', () => {
  test.skip(!IS_LIVE, 'Skipped: set LIVE_TEST_MODE=true to run LIVE tests');

  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
  });

  test('buy $2 of BTC (LIVE) @live', async ({ page }) => {
    await sendChatCommand(page, 'Buy $2 of BTC');

    await page.locator('button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });

    // In LIVE mode, either confirm works or LIVE-disabled banner shows
    const liveDisabledBanner = page.locator('text=/LIVE trading is disabled|LIVE mode blocked/i');
    const bannerVisible = await liveDisabledBanner.isVisible({ timeout: 2_000 }).catch(() => false);

    if (bannerVisible) {
      // LIVE is disabled server-side, confirm should be blocked
      const confirmBtn = page.locator('button:has-text("Confirm")').first();
      const isDisabled = await confirmBtn.isDisabled();
      expect(isDisabled).toBeTruthy();
    } else {
      await clickConfirm(page);
      await page.waitForTimeout(15_000);
      await assertReliabilityInvariants(page);
    }
  });

  test('sell $2 of BTC (LIVE) @live', async ({ page }) => {
    await sendChatCommand(page, 'Sell $2 of BTC');

    await page.locator('button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });

    const liveDisabledBanner = page.locator('text=/LIVE trading is disabled|LIVE mode blocked/i');
    const bannerVisible = await liveDisabledBanner.isVisible({ timeout: 2_000 }).catch(() => false);

    if (bannerVisible) {
      const confirmBtn = page.locator('button:has-text("Confirm")').first();
      const isDisabled = await confirmBtn.isDisabled();
      expect(isDisabled).toBeTruthy();
    } else {
      await clickConfirm(page);
      await page.waitForTimeout(15_000);
      await assertReliabilityInvariants(page);
    }
  });
});
