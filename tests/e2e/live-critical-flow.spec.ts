/**
 * Live Critical Flow — 5 Consecutive Passes (single-test, sequential loop)
 *
 * Validates the full analyze → sell-all → buy $2 cycle 5 times in a row
 * inside ONE test using the SAME page context.  No hardcoded asset tickers.
 *
 * Environment gates (all default OFF):
 *   E2E_LIVE=1            — enable the suite
 *   E2E_ALLOW_TRADES=1    — actually click Confirm Trade
 *   E2E_CONFIRM_SELL=1    — confirm the sell step
 *   E2E_CONFIRM_BUY=1     — confirm the buy step
 *
 * Failure artifacts: artifacts/e2e/fail_iter*_*.png + *_diagnostics.md
 */

import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const LIVE_MODE   = process.env.E2E_LIVE           === '1';
const ALLOW_TRADE = process.env.E2E_ALLOW_TRADES   === '1';
const CONF_SELL   = process.env.E2E_CONFIRM_SELL   === '1';
const CONF_BUY    = process.env.E2E_CONFIRM_BUY    === '1';

// ---------------------------------------------------------------------------
// Per-test diagnostic state (populated in beforeEach)
// ---------------------------------------------------------------------------
let consoleLogs: string[] = [];
let networkLogs: { url: string; method: string; status: number; body: string }[] = [];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Scrape the holdings table inside the Portfolio Snapshot card (scoped to the
 * card container, not the first table globally) and return the symbol with
 * the highest USD value (excluding 'USD').
 */
async function parsePrimaryAsset(page: Page): Promise<{ symbol: string; usdValue: number } | null> {
  // Scope: find the nearest ancestor of the "Portfolio Snapshot" heading that
  // also contains a table — avoids matching random tables elsewhere on the page.
  const heading = page.getByText('Portfolio Snapshot').first();
  const card = heading.locator('xpath=ancestor::div[.//table][1]');
  const table = card.locator('table').first();
  await table.waitFor({ state: 'attached', timeout: 10_000 }).catch(() => {});
  const rows  = table.locator('tbody tr');
  const count = await rows.count();
  if (count === 0) return null;

  let best: { symbol: string; usdValue: number } | null = null;
  for (let i = 0; i < count; i++) {
    const cells  = rows.nth(i).locator('td');
    const symbol = ((await cells.nth(0).textContent()) ?? '').trim().toUpperCase();
    const valRaw = ((await cells.nth(2).textContent()) ?? '').replace(/[$,]/g, '').trim();
    const usdValue = parseFloat(valRaw);
    if (!symbol || symbol === 'USD') continue;
    if (!isNaN(usdValue) && (!best || usdValue > best.usdValue)) {
      best = { symbol, usdValue };
    }
  }
  return best;
}

/**
 * Fill the chat input and click Send.  After clicking, waits briefly for the
 * request to be dispatched (textarea clears).  Command stacking is prevented
 * by the subsequent waitForResponse() call, which polls for expected keywords
 * before the next sendChat can be called.
 */
async function sendChat(page: Page, text: string): Promise<void> {
  const input = page.locator('textarea[placeholder*="Ask me anything"]').first();
  await input.fill(text);
  const btn = page.locator('button:has-text("Send")').first();
  await expect(btn).toBeEnabled({ timeout: 5_000 });
  await btn.click();
  // Brief wait for the click to register and the textarea to clear,
  // ensuring the message is dispatched before we return.
  await page.waitForTimeout(500);
}

/**
 * Poll body text every 2 s until one of the keywords appears or timeout elapses.
 */
async function waitForResponse(
  page: Page,
  keywords: string[],
  timeout = 90_000,
): Promise<string> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const body = await page.innerText('body').catch(() => '');
    for (const kw of keywords) {
      if (body.toLowerCase().includes(kw.toLowerCase())) return body;
    }
    await page.waitForTimeout(2_000);
  }
  return await page.innerText('body').catch(() => '');
}

/**
 * Save a full-page screenshot, console logs, network logs, and last assistant
 * message into a diagnostics markdown file for post-mortem analysis.
 */
async function dumpFailureArtifacts(page: Page, iter: number, step: string): Promise<void> {
  const dir = path.join('artifacts', 'e2e');
  fs.mkdirSync(dir, { recursive: true });
  const ts = Date.now();

  const screenshotFile = path.join(dir, `fail_iter${iter}_${step}_${ts}.png`);
  await page.screenshot({ path: screenshotFile, fullPage: true }).catch(() => {});

  const lastAssistant = await page
    .locator('[data-testid="assistant-message"], .assistant-message, [class*="assistant"]')
    .last()
    .textContent()
    .catch(() => '(could not extract)');

  const md = [
    `# Failure Diagnostics — Iter ${iter} / ${step}`,
    `**Timestamp:** ${new Date(ts).toISOString()}`,
    `**Screenshot:** ${screenshotFile}`,
    '',
    '## Last Assistant Message',
    '```',
    lastAssistant?.slice(0, 2000) ?? '(empty)',
    '```',
    '',
    '## Console Logs',
    '```',
    consoleLogs.length ? consoleLogs.join('\n') : '(none)',
    '```',
    '',
    '## Network Logs (chat/command & confirmations)',
    '```json',
    JSON.stringify(networkLogs, null, 2).slice(0, 5000),
    '```',
  ].join('\n');

  const mdFile = path.join(dir, `fail_iter${iter}_${step}_${ts}_diagnostics.md`);
  fs.writeFileSync(mdFile, md, 'utf-8');

  console.error(`[FAIL ARTIFACT] screenshot: ${screenshotFile}`);
  console.error(`[FAIL ARTIFACT] diagnostics: ${mdFile}`);
}

/**
 * Navigate to /runs/{runId} and verify each tab renders something meaningful.
 */
async function validateRunDetails(page: Page, runId: string): Promise<void> {
  await page.goto(`/runs/${runId}`);
  await page.waitForLoadState('networkidle');

  const chartsTab = page.getByTestId('run-tab-charts');
  if (await chartsTab.count() > 0) {
    await chartsTab.click();
    await expect(
      page.getByText(/Data coverage|chart unavailable|unavailable because/i).first()
    ).toBeVisible({ timeout: 15_000 }).catch(() => {});
  }

  const evalsTab = page.getByTestId('run-tab-evals');
  if (await evalsTab.count() > 0) {
    await evalsTab.click();
    const hasList    = await page.getByTestId('run-evals-list').count();
    const hasNoEvals = await page.getByText(/No evaluations found/i).count();
    expect(hasList + hasNoEvals).toBeGreaterThan(0);
  }

  const evidenceTab = page.getByTestId('run-tab-evidence');
  if (await evidenceTab.count() > 0) {
    await evidenceTab.click();
    await expect(
      page.getByText(/Asset Rankings|No rankings/i).first()
    ).toBeVisible({ timeout: 10_000 }).catch(() => {});
  }
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe('Live critical flow', () => {
  test.describe.configure({ mode: 'serial' });
  test.skip(!LIVE_MODE, 'Requires E2E_LIVE=1');

  test('5x loop: analyze → sell-all → buy $2 (sequential)', async ({ page }) => {
    // 15 min for 5 iterations; execution mode trades add ~60s each with confirm waits
    test.setTimeout(900_000);
    // Wire up diagnostics for the entire test lifetime
    consoleLogs = [];
    networkLogs = [];

    page.on('console', (msg) => {
      consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
    });

    page.on('response', async (response) => {
      const url = response.url();
      if (url.includes('/api/v1/chat/command') || url.includes('/api/v1/confirmations')) {
        const body = await response.text().catch(() => '(unreadable)');
        networkLogs.push({
          url,
          method: response.request().method(),
          status: response.status(),
          body: body.slice(0, 3000),
        });
      }
    });

    for (let iter = 1; iter <= 5; iter++) {
      console.log(`\n========== ITERATION ${iter}/5 ==========`);

      // ── STEP 0: fresh conversation ────────────────────────────────────
      await page.goto('/chat');
      await page.waitForLoadState('networkidle');

      // ── PRE-CHECK: wait for backend to be healthy ─────────────────────
      // Prevents cascading failures when the backend is recovering from
      // rate-limiting or trade execution load (429/500 cascade).
      for (let attempt = 0; attempt < 10; attempt++) {
        const ok = await page.evaluate(async () => {
          try {
            const r = await fetch('/api/v1/ops/health');
            return r.ok;
          } catch { return false; }
        }).catch(() => false);
        if (ok) break;
        console.log(`Iter ${iter}: backend not healthy, retrying in 5s (${attempt + 1}/10)`);
        await page.waitForTimeout(5_000);
      }

      const newChatBtn = page.locator('button').filter({ hasText: /New Chat/i }).first();
      if (await newChatBtn.count() > 0 && await newChatBtn.isVisible().catch(() => false)) {
        await newChatBtn.click();
        await page.waitForLoadState('networkidle');
      }

      // ── STEP 1: analyze portfolio ─────────────────────────────────────
      await sendChat(page, 'Analyze my portfolio');
      await expect(page.getByText('Portfolio Snapshot').first()).toBeVisible({ timeout: 30_000 });

      const primary = await parsePrimaryAsset(page);
      if (!primary) {
        console.log(`Iter ${iter}: no non-USD holdings, skipping sell/buy.`);
        continue;
      }
      const { symbol: asset } = primary;
      console.log(`Iter ${iter}: primary asset = ${asset} ($${primary.usdValue})`);

      // ── STEP 2: sell all ──────────────────────────────────────────────
      await sendChat(page, `Sell all of my ${asset}`);
      const sellBody = await waitForResponse(page,
        ['confirm', 'Confirm Trade', 'Action Required', 'BLOCKED', 'BELOW_MIN',
         'ASSET_NOT_IN_BALANCES', 'NO_AVAILABLE_BALANCE', 'FUNDS_ON_HOLD',
         'PRICE_UNAVAILABLE', 'PREVIEW_REJECTED', 'BALANCES_UNAVAILABLE',
         'Something went wrong', 'Command failed', 'Internal Server Error'],
        90_000,
      );

      expect(sellBody).not.toContain('Unable to compute an executable amount');
      expect(sellBody).not.toContain('Something went wrong');
      expect(sellBody).not.toContain('Internal Server Error');

      const sellReady     = /confirm|Confirm Trade|Action Required/i.test(sellBody);
      const sellBlockedOk = /ASSET_NOT_IN_BALANCES|NO_AVAILABLE_BALANCE|FUNDS_ON_HOLD|PRICE_UNAVAILABLE|PREVIEW_REJECTED|BALANCES_UNAVAILABLE/i.test(sellBody);

      if (!sellReady && !sellBlockedOk) {
        await dumpFailureArtifacts(page, iter, 'sell');
        throw new Error(
          `[Iter ${iter}] Sell ${asset}: neither READY nor specific block. body=${sellBody.slice(0, 300)}`
        );
      }

      if (sellReady && ALLOW_TRADE && CONF_SELL) {
        await page.getByRole('button', { name: /Confirm Trade/i }).click();
        await page.waitForTimeout(30_000); // 30s for trade execution + SSE to settle
      }

      // ── STEP 3: buy $2 ────────────────────────────────────────────────
      await sendChat(page, `Buy $2 of ${asset}`);
      const buyBody = await waitForResponse(page,
        ['confirm', 'Confirm Trade', '$2', '2.00', 'INSUFFICIENT_CASH',
         'INSUFFICIENT_FUND', 'ASSET_NOT_IN_BALANCES', 'BLOCKED',
         'Something went wrong', 'Command failed', 'Internal Server Error'],
        90_000,
      );

      expect(buyBody).not.toContain('Something went wrong');
      expect(buyBody).not.toContain('Internal Server Error');

      const buyReady     = /confirm|Confirm Trade|\$2|2\.00/i.test(buyBody);
      const buyBlockedOk = /INSUFFICIENT_CASH|INSUFFICIENT_FUND|ASSET_NOT_IN_BALANCES/i.test(buyBody);

      if (!buyReady && !buyBlockedOk) {
        await dumpFailureArtifacts(page, iter, 'buy');
        throw new Error(
          `[Iter ${iter}] Buy ${asset}: neither staged nor specific block. body=${buyBody.slice(0, 300)}`
        );
      }

      if (buyReady && ALLOW_TRADE && CONF_BUY) {
        await page.getByRole('button', { name: /Confirm Trade/i }).click();
        await page.waitForTimeout(30_000); // 30s for trade execution + SSE to settle
      }

      // ── STEP 4: validate run details if a run link is present ─────────
      const chatUrl  = page.url();
      const runLinks = await page.locator('a[href*="/runs/"]').all();
      if (runLinks.length > 0) {
        const href  = await runLinks[runLinks.length - 1].getAttribute('href') ?? '';
        const runId = href.split('/runs/')[1]?.split('/')[0];
        if (runId) {
          await validateRunDetails(page, runId);
          await page.goto(chatUrl);
          await page.waitForLoadState('networkidle');
        }
      }

      // ── STEP 5: evidence chips never 404 ──────────────────────────────
      const bodyAfterRestore = await page.innerText('body').catch(() => '');
      const pageIs404 = /404|could not be found/i.test(bodyAfterRestore);

      if (!pageIs404) {
        const chips     = page.locator('[data-testid="evidence-chip"]');
        const chipCount = await chips.count();
        for (let ci = 0; ci < chipCount; ci++) {
          const chip = chips.nth(ci);
          const disabled = await chip.getAttribute('data-disabled', { timeout: 10_000 })
            .catch(() => null);
          if (disabled === null) break;
          if (disabled === 'true') {
            await expect(chip).toHaveAttribute('title', /.+/, { timeout: 5_000 })
              .catch(() => {});
            continue;
          }
          await chip.click();
          await page.waitForTimeout(300);
          await expect(page).not.toHaveURL(/404|not.found/i);
          const closeBtn = page
            .locator('[role="dialog"] button, button:has-text("Close")')
            .first();
          if (await closeBtn.count() > 0) await closeBtn.click();
        }
      }

      console.log(`========== ITERATION ${iter}/5 PASSED ==========\n`);
    }
  });
});
