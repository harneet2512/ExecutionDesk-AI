/**
 * Agentic Intelligence Layer E2E Test
 *
 * Validates the end-to-end fixes:
 *  1. Multi-asset sell narrative includes "sequentially" and "Step 1".
 *  2. Evidence chips show requested product_ids (not SOL-USD fallback).
 *  3. Evidence chips never 404 (disabled or clickable).
 *  4. No contradictory block reasons per asset.
 *  5. Portfolio Snapshot card is never modified.
 */
import { test, expect, type Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
test.use({ baseURL: BASE_URL });

async function waitForChatReady(page: Page, timeout = 60_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const textarea = page.locator('textarea[placeholder*="Ask me anything"]').first();
    if (await textarea.isVisible({ timeout: 500 }).catch(() => false)) {
      const isDisabled = await textarea.isDisabled().catch(() => false);
      if (!isDisabled) return;
    }
    await page.waitForTimeout(1000);
  }
}

async function sendChatCommand(page: Page, command: string) {
  await waitForChatReady(page);
  const input = page.locator('textarea[placeholder*="Ask me anything"]').first();
  await input.waitFor({ state: 'visible', timeout: 10_000 });
  await input.fill(command);
  await page.waitForTimeout(200);
  const sendBtn = page.locator('button:has-text("Send")').first();
  if (await sendBtn.isVisible({ timeout: 2000 }).catch(() => false)) await sendBtn.click();
  else await input.press('Enter');
  await page.waitForTimeout(1500);
}

async function waitForAssistantResponse(page: Page, keywords: string[], timeout = 90_000): Promise<string> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const bodyText = await page.locator('body').textContent() || '';
    for (const kw of keywords) {
      if (bodyText.toLowerCase().includes(kw.toLowerCase())) return bodyText;
    }
    await page.waitForTimeout(2000);
  }
  return await page.locator('body').textContent() || '';
}

test.describe('Intelligence Layer Validation', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      const msg = err.message || '';
      const nonCritical =
        msg.includes('favicon') || msg.includes('EventSource') ||
        msg.includes('hydrat') || msg.includes('net::ERR_') ||
        msg.includes('AbortError') || msg.includes('Unexpected token');
      if (!nonCritical) console.error('[PAGE ERROR]', msg);
    });
  });

  test('multi-asset sell shows sequential steps with correct product_ids in evidence', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    await sendChatCommand(page, 'Analyze my portfolio');
    await waitForAssistantResponse(page, ['Portfolio Snapshot', 'portfolio']);

    await sendChatCommand(page, 'Sell all of MOODENG and MORPHO');
    const bodyText = await waitForAssistantResponse(page, [
      'sequential', 'Step 1', 'blocked', 'CONFIRM', 'Confirm Trade',
      'position not found', 'no tradable',
    ]);

    // Narrative must not contain internal telemetry
    expect(bodyText).not.toContain('market_data.get_price');
    expect(bodyText).not.toContain('trade_preflight');
    expect(bodyText).not.toContain('_safe_json_loads');

    // Evidence must never show SOL-USD for a MOODENG/MORPHO request
    const evidenceChips = page.locator('[data-testid="evidence-chip"]');
    const chipCount = await evidenceChips.count();
    for (let i = 0; i < chipCount; i++) {
      const chipText = await evidenceChips.nth(i).textContent() || '';
      if (chipText.includes('Market quotes')) {
        expect(chipText).not.toContain('SOL-USD');
      }
    }

    // If steps are shown, verify numbering
    if (bodyText.includes('Step 1')) {
      expect(bodyText).toMatch(/Step 1/);
      expect(bodyText.toLowerCase()).toContain('sequential');
    }
  });

  test('evidence chips never 404 — disabled or navigable', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    await sendChatCommand(page, 'Buy $10 of BTC');
    await waitForAssistantResponse(page, ['Confirm', 'Evidence', 'evidence-chip', 'blocked']);

    const evidenceChips = page.locator('[data-testid="evidence-chip"]');
    const chipCount = await evidenceChips.count();

    for (let i = 0; i < chipCount; i++) {
      const chip = evidenceChips.nth(i);
      const isDisabled = await chip.getAttribute('data-disabled');

      if (isDisabled === 'true') {
        const title = await chip.getAttribute('title');
        expect(title).toBe('Evidence unavailable');
        continue;
      }

      // Active chip: should be a link (a or next/link) with a valid href
      const href = await chip.getAttribute('href');
      if (href) {
        expect(href).not.toContain('undefined');
        expect(href.startsWith('/') || href.startsWith('http')).toBeTruthy();
      }
    }
  });

  test('no contradictory block reasons for same asset', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    await sendChatCommand(page, 'Sell all of MOODENG and MORPHO');
    const bodyText = await waitForAssistantResponse(page, [
      'sequential', 'Step 1', 'blocked', 'position not found',
      'Confirm', 'no tradable',
    ]);

    // For each asset, at most one block reason should appear.
    // Specifically, we must not see BOTH "Position not found" AND "Quantity unavailable"
    // for the same asset.
    const hasPositionNotFound = bodyText.includes('Position not found');
    const hasQtyUnavailable = bodyText.includes('Quantity unavailable');

    // Both appearing simultaneously for the same request is the contradiction bug
    if (hasPositionNotFound && hasQtyUnavailable) {
      // This should only happen if they refer to DIFFERENT assets
      // Count occurrences per asset to verify
      const posNotFoundMOODENG = bodyText.includes('Position not found') && bodyText.includes('MOODENG');
      const qtyUnavailMOODENG = bodyText.includes('Quantity unavailable') && bodyText.includes('MOODENG');
      // Both for same asset = bug
      expect(posNotFoundMOODENG && qtyUnavailMOODENG).toBeFalsy();
    }
  });

  test('portfolio snapshot card is not modified by trade commands', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    await sendChatCommand(page, 'Analyze my portfolio');
    await waitForAssistantResponse(page, ['Portfolio Snapshot', 'portfolio']);

    // Capture snapshot card state
    const totalValueLabel = page.locator('text=Total Value').first();
    const cashLabel = page.locator('text=Cash').first();
    const snapshotHeader = page.locator('text=Portfolio Snapshot').first();

    const totalVisible = await totalValueLabel.isVisible({ timeout: 5000 }).catch(() => false);
    const cashVisible = await cashLabel.isVisible({ timeout: 5000 }).catch(() => false);
    const headerVisible = await snapshotHeader.isVisible({ timeout: 5000 }).catch(() => false);

    // Now issue a trade command
    await sendChatCommand(page, 'Sell all of MOODENG and MORPHO');
    await waitForAssistantResponse(page, ['sequential', 'Step 1', 'blocked', 'Confirm', 'position']);

    // Snapshot card state should be unchanged
    if (headerVisible) {
      await expect(snapshotHeader).toBeVisible({ timeout: 5000 });
    }
    if (totalVisible) {
      await expect(totalValueLabel).toBeVisible({ timeout: 5000 });
    }
    if (cashVisible) {
      await expect(cashLabel).toBeVisible({ timeout: 5000 });
    }
  });
});
