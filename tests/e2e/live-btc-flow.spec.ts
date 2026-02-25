/**
 * Live BTC flow test — manual opt-in only.
 *
 * Requires:
 *   E2E_LIVE=1 E2E_ALLOW_TRADES=1 npx playwright test tests/e2e/live-btc-flow.spec.ts
 *
 * This test hits the real backend (no mocking) and verifies:
 *   1. "Analyze my portfolio" returns a Portfolio Snapshot card
 *   2. "Sell all of my BTC" does NOT produce the generic "Unable to compute" message
 *   3. "Buy $2 of BTC" stages a confirmation card (not a generic error)
 */
import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://localhost:3000' });

const LIVE_MODE = process.env.E2E_LIVE === '1' && process.env.E2E_ALLOW_TRADES === '1';

test.describe('Live BTC flow (manual opt-in only)', () => {
  test.skip(!LIVE_MODE, 'Live test requires E2E_LIVE=1 and E2E_ALLOW_TRADES=1');

  test('analyze → sell-all BTC (no generic message) → buy $2 BTC staging', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');

    const input = page.getByRole('textbox', { name: 'Ask me anything about trading...' });
    const sendBtn = page.getByRole('button', { name: 'Send' });

    // ── Step 1: Analyze portfolio ──────────────────────────────────────────
    await input.fill('Analyze my portfolio');
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();

    // Wait up to 15s for portfolio card
    await expect(page.getByText(/Portfolio|holdings|BTC/i).first()).toBeVisible({ timeout: 15000 });
    const step1Text = await page.innerText('body');
    expect(step1Text).not.toContain('Something went wrong');

    // ── Step 2: Sell all BTC ───────────────────────────────────────────────
    await input.fill('Sell all of my BTC');
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();
    await page.waitForTimeout(6000);

    const step2Text = await page.innerText('body');

    // Critical assertion: generic poison message must NOT appear
    expect(step2Text).not.toContain('Unable to compute an executable amount');
    expect(step2Text).not.toContain('Something went wrong');

    // Must show either a confirmation/staging card OR a specific blocked reason
    const isReady = /confirm|staging|Action Required|sell.*btc/i.test(step2Text);
    const isBlockedSpecific = /ASSET_NOT_IN_BALANCES|NO_AVAILABLE_BALANCE|FUNDS_ON_HOLD|PRICE_UNAVAILABLE|PREVIEW_REJECTED|BALANCES_UNAVAILABLE/i.test(step2Text);
    expect(isReady || isBlockedSpecific).toBe(true);

    // ── Step 3: Buy $2 BTC ─────────────────────────────────────────────────
    await input.fill('Buy $2 of BTC');
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();
    await page.waitForTimeout(6000);

    const step3Text = await page.innerText('body');

    // Must show staging confirmation or a clear (specific) error
    const hasBuyStaging = /confirm|staging|Action Required|\$2|2\.00/i.test(step3Text);
    const hasClearError = /INSUFFICIENT_CASH|INSUFFICIENT_FUND|ASSET_NOT_IN_BALANCES/i.test(step3Text);
    expect(hasBuyStaging || hasClearError).toBe(true);

    // Must NOT show generic internal error
    expect(step3Text).not.toContain('Something went wrong');
    expect(step3Text).not.toContain('Unable to compute an executable amount');
  });
});
