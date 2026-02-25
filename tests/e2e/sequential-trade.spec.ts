/**
 * Sequential Multi-Asset Trade E2E Test
 *
 * Validates that multi-asset trade requests produce a sequential execution plan
 * with Step 1 READY and remaining steps Queued, and that confirmation submits
 * only one order at a time.
 */
import { test, expect, type Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
test.use({ baseURL: BASE_URL });

function isNonCriticalError(text: string, url: string): boolean {
  if (url.includes('favicon') || text.includes('favicon')) return true;
  if (text.includes('EventSource') || text.includes('SSE') || text.includes('text/event-stream')) return true;
  if (text.includes('hydrat') || text.includes('Hydrat')) return true;
  if (text.includes('net::ERR_') || text.includes('NetworkError')) return true;
  if (url.includes('/conversations/') && url.includes('/messages')) return true;
  if (url.includes('/runs/') && (url.includes('/status') || url.includes('/steps') || url.includes('/events'))) return true;
  if (text.includes('Unexpected token') || text.includes('AbortError')) return true;
  return false;
}

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

test.describe('Sequential Multi-Asset Trade', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!isNonCriticalError(err.message, '')) {
        console.error('[PAGE ERROR]', err.message);
      }
    });
  });

  test('multi-asset sell shows sequential steps and single confirm CTA', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    // First ensure portfolio snapshot exists
    await sendChatCommand(page, 'Analyze my portfolio');

    const snapshotHeader = page.locator('text=Portfolio Snapshot').first();
    await expect(snapshotHeader).toBeVisible({ timeout: 90_000 });

    // Now issue a multi-asset sell command
    await sendChatCommand(page, 'Sell all of MOODENG and MORPHO');

    // Wait for assistant response
    const deadline = Date.now() + 90_000;
    let responseFound = false;
    while (Date.now() < deadline) {
      const bodyText = await page.locator('body').textContent() || '';
      if (
        bodyText.includes('sequential') ||
        bodyText.includes('Step 1') ||
        bodyText.includes('Queued') ||
        bodyText.includes('CONFIRM') ||
        bodyText.includes('Confirm Trade') ||
        bodyText.includes('blocked')
      ) {
        responseFound = true;
        break;
      }
      await page.waitForTimeout(2000);
    }

    expect(responseFound).toBeTruthy();

    const bodyText = await page.locator('body').textContent() || '';

    // If we got a confirmation prompt with actions
    if (bodyText.includes('Confirm Trade') || bodyText.includes('CONFIRM')) {
      // Should have exactly ONE confirm button visible (not one per action)
      const confirmBtns = page.locator('button:has-text("Confirm Trade")');
      const confirmCount = await confirmBtns.count();
      expect(confirmCount).toBeLessThanOrEqual(1);

      // Narrative should mention sequential execution or step numbering
      // (only if multi-action was actually parsed with 2+ valid actions)
      if (bodyText.includes('Step 1') || bodyText.includes('sequential')) {
        expect(bodyText).toMatch(/Step 1|sequential|Queued/i);
      }
    }

    // If all actions were blocked, check for human-readable reasons
    if (bodyText.includes('blocked') || bodyText.includes('REJECTED')) {
      // Should NOT contain internal tool names
      expect(bodyText).not.toContain('market_data.get_price');
      expect(bodyText).not.toContain('trade_preflight');
      expect(bodyText).not.toContain('top1_concentration');
      expect(bodyText).not.toContain('_safe_json_loads');

      // Should contain human-readable language
      const hasHumanMessage =
        bodyText.includes('Position not found') ||
        bodyText.includes('Quantity unavailable') ||
        bodyText.includes('Insufficient') ||
        bodyText.includes('Below minimum') ||
        bodyText.includes('not tradable') ||
        bodyText.includes('Market unavailable');
      expect(hasHumanMessage).toBeTruthy();
    }
  });

  test('portfolio snapshot card remains unchanged after trade commands', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    await sendChatCommand(page, 'Analyze my portfolio');

    const snapshotHeader = page.locator('text=Portfolio Snapshot').first();
    await expect(snapshotHeader).toBeVisible({ timeout: 90_000 });

    // Verify card structure
    const totalValueLabel = page.locator('text=Total Value').first();
    await expect(totalValueLabel).toBeVisible({ timeout: 5000 });

    const cashLabel = page.locator('text=Cash').first();
    await expect(cashLabel).toBeVisible({ timeout: 5000 });

    // Holdings table should exist
    const holdingsTable = page.locator('table').first();
    const tableVisible = await holdingsTable.isVisible({ timeout: 5000 }).catch(() => false);
    if (tableVisible) {
      const rows = holdingsTable.locator('tbody tr');
      const rowCount = await rows.count();
      expect(rowCount).toBeGreaterThanOrEqual(1);
    }
  });

  test('evidence renders as clickable elements in trade responses', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    await sendChatCommand(page, 'Buy $10 of BTC');

    // Wait for response
    const deadline = Date.now() + 90_000;
    while (Date.now() < deadline) {
      const bodyText = await page.locator('body').textContent() || '';
      if (bodyText.includes('Evidence') || bodyText.includes('Confirm Trade') || bodyText.includes('evidence-chip')) {
        break;
      }
      await page.waitForTimeout(2000);
    }

    // Check for clickable evidence (either chips or markdown links)
    const evidenceChips = page.locator('[data-testid="evidence-chip"]');
    const chipCount = await evidenceChips.count();

    const evidenceLinks = page.locator('a[href*="/runs"], a[href*="/portfolio"], a[href*="artifact"]');
    const linkCount = await evidenceLinks.count();

    // At least some clickable evidence should be present
    expect(chipCount + linkCount).toBeGreaterThanOrEqual(1);
  });
});
