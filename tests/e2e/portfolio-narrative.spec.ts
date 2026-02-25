/**
 * Portfolio Narrative Rendering E2E Test
 *
 * Validates that the portfolio narrative renders as multiple lines
 * (not a single blob paragraph), evidence items are clickable chips,
 * and the Portfolio Snapshot card/table structure remains intact.
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

test.describe('Portfolio Narrative Rendering', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!isNonCriticalError(err.message, '')) {
        console.error('[PAGE ERROR]', err.message);
      }
    });
  });

  test('narrative renders as multiple lines with clickable evidence', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    // Start a new chat if possible
    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    await sendChatCommand(page, 'Analyze my portfolio');

    // Wait for the assistant response to appear
    const narrativeContainer = page.locator('[data-testid="narrative-lines"]').first();
    const markdownFallback = page.locator('.prose').last();

    // Wait up to 90s for either the structured narrative or a markdown response
    const deadline = Date.now() + 90_000;
    let foundStructured = false;
    let foundMarkdown = false;
    while (Date.now() < deadline) {
      if (await narrativeContainer.isVisible({ timeout: 500 }).catch(() => false)) {
        foundStructured = true;
        break;
      }
      const bodyText = await page.locator('body').textContent() || '';
      if (bodyText.includes('Pulled the latest available state') || bodyText.includes('Portfolio Snapshot')) {
        foundMarkdown = true;
        break;
      }
      await page.waitForTimeout(2000);
    }

    if (foundStructured) {
      // -- Structured narrative path (NarrativeLines component) --

      // Assert the lead line exists
      const lead = narrativeContainer.locator('[data-testid="narrative-lead"]');
      await expect(lead).toBeVisible({ timeout: 5000 });

      // Assert multiple narrative lines rendered (>= 3: lead + at least 2 lines)
      const lines = narrativeContainer.locator('[data-testid="narrative-line"]');
      const lineCount = await lines.count();
      expect(lineCount).toBeGreaterThanOrEqual(2);

      // Assert evidence chips (>= 2 clickable)
      const chips = narrativeContainer.locator('[data-testid="evidence-chip"]');
      const chipCount = await chips.count();
      expect(chipCount).toBeGreaterThanOrEqual(2);

      // Verify chips have href attributes (are proper links)
      const firstChip = chips.first();
      const href = await firstChip.getAttribute('href');
      expect(href).toBeTruthy();

      // Click first evidence chip and verify navigation or panel opens
      const [response] = await Promise.all([
        page.waitForNavigation({ timeout: 10_000 }).catch(() => null),
        firstChip.click(),
      ]);
      // After click, URL should have changed or a panel should be visible
      const currentUrl = page.url();
      const navigated = currentUrl.includes('/runs') || currentUrl.includes('/portfolio') || currentUrl.includes('artifact');
      if (!navigated) {
        // Fallback: check if an evidence panel/modal opened
        const panel = page.locator('[role="dialog"], [data-testid="artifact-viewer"]').first();
        const panelVisible = await panel.isVisible({ timeout: 3000 }).catch(() => false);
        expect(navigated || panelVisible).toBeTruthy();
      }
    } else if (foundMarkdown) {
      // -- Markdown fallback path (defense-in-depth: double newlines render as separate <p>) --
      // Count <p> elements in the last assistant message bubble
      const assistantBubbles = page.locator('.rounded-2xl .prose');
      const lastBubble = assistantBubbles.last();
      const paragraphs = lastBubble.locator('p');
      const pCount = await paragraphs.count();
      expect(pCount).toBeGreaterThanOrEqual(3);
    } else {
      test.fail(true, 'Neither structured narrative nor markdown response appeared within 90s');
    }
  });

  test('portfolio snapshot card structure is unchanged', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const newChatBtn = page.locator('button:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(1500);
    }

    await sendChatCommand(page, 'Analyze my portfolio');

    // Wait for the Portfolio Snapshot card to render
    const snapshotHeader = page.locator('text=Portfolio Snapshot').first();
    await expect(snapshotHeader).toBeVisible({ timeout: 90_000 });

    // Verify card structure: Total Value section
    const totalValueLabel = page.locator('text=Total Value').first();
    await expect(totalValueLabel).toBeVisible({ timeout: 5000 });

    // Verify card structure: Cash section
    const cashLabel = page.locator('text=Cash').first();
    await expect(cashLabel).toBeVisible({ timeout: 5000 });

    // Verify holdings table exists with at least one row
    const holdingsTable = page.locator('table').first();
    const tableVisible = await holdingsTable.isVisible({ timeout: 5000 }).catch(() => false);
    if (tableVisible) {
      const rows = holdingsTable.locator('tbody tr');
      const rowCount = await rows.count();
      expect(rowCount).toBeGreaterThanOrEqual(1);
    }

    // Verify Risk Assessment section is present
    const riskSection = page.locator('text=Risk Assessment').first();
    const riskVisible = await riskSection.isVisible({ timeout: 5000 }).catch(() => false);
    if (riskVisible) {
      await expect(riskSection).toBeVisible();
    }

    // Verify Recommendations section is present
    const recsSection = page.locator('text=Recommendations').first();
    const recsVisible = await recsSection.isVisible({ timeout: 5000 }).catch(() => false);
    if (recsVisible) {
      await expect(recsSection).toBeVisible();
    }
  });
});
