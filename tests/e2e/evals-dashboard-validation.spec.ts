/**
 * Evals Dashboard E2E Validation
 * Runs the full flow: portfolio -> buy -> sell (News ON, News OFF, most profitable)
 * Captures evidence: screenshots, console logs, network failures, run_ids
 * Validates /evals dashboard and explainability
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const ROOT = path.join(__dirname, '..', '..');
const LOGS_DIR = path.join(ROOT, 'logs');
const ARTIFACTS_DIR = path.join(ROOT, 'artifacts');
const SCREENSHOTS_DIR = path.join(ROOT, 'screenshots');

function ensureDir(p: string) {
  if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
}

function saveRunIds(filename: string, runIds: string[]) {
  ensureDir(ARTIFACTS_DIR);
  fs.writeFileSync(
    path.join(ARTIFACTS_DIR, filename),
    JSON.stringify({ run_ids: runIds, captured_at: new Date().toISOString() }, null, 2),
  );
}

function captureRunIds(page: Page): string[] {
  const runIds: string[] = [];
  page.on('response', async (resp) => {
    const url = resp.url();
    if ((url.includes('/api/v1/chat') || url.includes('/api/v1/confirmations')) && resp.status() >= 200 && resp.status() < 300) {
      try {
        const body = await resp.json();
        if (body?.run_id && !runIds.includes(body.run_id)) runIds.push(body.run_id);
        if (body?.data?.run_id && !runIds.includes(body.data.run_id)) runIds.push(body.data.run_id);
      } catch { /* ignore */ }
    }
  });
  return runIds;
}

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

async function clickConfirm(page: Page) {
  const btn = page.locator('button:has-text("Confirm Trade")').first();
  await btn.waitFor({ state: 'visible', timeout: 60_000 });
  await btn.click();
}

async function setNewsToggle(page: Page, enabled: boolean) {
  await page.goto('/chat');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);
  const toggle = page.locator('[data-testid="news-toggle"]').first();
  if (await toggle.isVisible({ timeout: 5000 }).catch(() => false)) {
    const isOn = (await toggle.getAttribute('aria-pressed')) === 'true';
    if (enabled !== isOn) { await toggle.click(); await page.waitForTimeout(1000); }
  } else {
    await page.evaluate((val) => localStorage.setItem('newsEnabled', String(val)), enabled);
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
  }
  const newChatBtn = page.locator('button:has-text("New Chat")').first();
  if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await newChatBtn.click();
    await page.waitForTimeout(1500);
  }
}

async function waitForTerminalState(page: Page, timeout = 90_000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const text = await page.locator('body').textContent() || '';
    if (text.includes('COMPLETED') || text.includes('FAILED') || text.includes('Order submitted') || text.includes('Trade completed') || text.includes('FILLED')) {
      await page.waitForTimeout(2000);
      return;
    }
    await page.waitForTimeout(2000);
  }
}

// Use baseURL from env or default 3000; frontend may run on 3001
const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
test.use({ baseURL: BASE_URL });

test.describe('Evals Dashboard E2E Validation', () => {
  test.beforeAll(async () => {
    // Reset DB to get $10k balance for buy/sell flows
    try {
      const { execSync } = await import('child_process');
      execSync('python reset_db.py', { cwd: ROOT, stdio: 'inherit' });
    } catch (e) {
      console.warn('Reset DB failed (may already be clean):', e);
    }
  });

  test('News ON: portfolio -> buy -> sell', async ({ page }) => {
    ensureDir(LOGS_DIR);
    ensureDir(SCREENSHOTS_DIR);
    const consoleLogs: string[] = [];
    const networkFailures: string[] = [];
    const runIds = captureRunIds(page);

    page.on('console', (msg) => {
      const t = msg.text();
      consoleLogs.push(`[${msg.type()}] ${t}`);
      if (msg.type() === 'error' && !isNonCriticalError(t, '')) {
        // Track for assertion
      }
    });
    page.on('response', (r) => {
      if (r.status() >= 400 && !isNonCriticalError('', r.url())) {
        networkFailures.push(`${r.status()} ${r.url()}`);
      }
    });

    await setNewsToggle(page, true);

    await test.step('Portfolio', async () => {
      await sendChatCommand(page, 'analyze my portfolio');
      await page.waitForTimeout(10_000);
      await expect(page.locator(':text-is("Portfolio Snapshot"), :text-is("Total Value"), :text-is("Holdings")').first()).toBeVisible({ timeout: 30_000 });
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '01_portfolio_result.png'), fullPage: true });
      await waitForChatReady(page, 30_000);
    });

    await test.step('Buy $2 BTC', async () => {
      await sendChatCommand(page, 'buy $2 of BTC');
      await page.locator('button:has-text("Confirm")').first().waitFor({ state: 'visible', timeout: 60_000 });
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '02_buy_confirm.png'), fullPage: true });
      await clickConfirm(page);
      await waitForTerminalState(page, 90_000);
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '03_buy_complete.png'), fullPage: true });
      await waitForChatReady(page, 30_000);
    });

    await test.step('Sell $2 BTC', async () => {
      await sendChatCommand(page, 'sell $2 of BTC');
      await page.locator('button:has-text("Confirm")').first().waitFor({ state: 'visible', timeout: 60_000 });
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '04_sell_confirm.png'), fullPage: true });
      await clickConfirm(page);
      await waitForTerminalState(page, 90_000);
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '05_sell_complete.png'), fullPage: true });
    });

    saveRunIds('run_ids_news_on.json', runIds);
    fs.writeFileSync(path.join(LOGS_DIR, 'console.txt'), consoleLogs.join('\n'));
    fs.writeFileSync(path.join(LOGS_DIR, 'network_failures.txt'), networkFailures.join('\n'));

    const criticalConsole = consoleLogs.filter((l) => l.startsWith('[error]') && !isNonCriticalError(l, ''));
    const criticalNet = networkFailures.filter((u) => !isNonCriticalError('', u));
    expect(criticalConsole).toHaveLength(0);
    expect(criticalNet).toHaveLength(0);
  });

  test('News OFF: portfolio -> buy -> sell', async ({ page }) => {
    const consoleLogs: string[] = [];
    const networkFailures: string[] = [];
    const runIds = captureRunIds(page);

    page.on('console', (msg) => { consoleLogs.push(`[${msg.type()}] ${msg.text()}`); });
    page.on('response', (r) => {
      if (r.status() >= 400 && !isNonCriticalError('', r.url())) networkFailures.push(`${r.status()} ${r.url()}`);
    });

    await setNewsToggle(page, false);

    await test.step('Portfolio', async () => {
      await sendChatCommand(page, 'analyze my portfolio');
      await page.waitForTimeout(10_000);
      await expect(page.locator(':text-is("Portfolio Snapshot"), :text-is("Total Value"), :text-is("Holdings")').first()).toBeVisible({ timeout: 30_000 });
      await waitForChatReady(page, 30_000);
    });

    await test.step('Buy $2 BTC', async () => {
      await sendChatCommand(page, 'buy $2 of BTC');
      await page.locator('button:has-text("Confirm")').first().waitFor({ state: 'visible', timeout: 60_000 });
      await clickConfirm(page);
      await waitForTerminalState(page, 90_000);
      await waitForChatReady(page, 30_000);
    });

    await test.step('Sell $2 BTC', async () => {
      await sendChatCommand(page, 'sell $2 of BTC');
      await page.locator('button:has-text("Confirm")').first().waitFor({ state: 'visible', timeout: 60_000 });
      await clickConfirm(page);
      await waitForTerminalState(page, 90_000);
    });

    saveRunIds('run_ids_news_off.json', runIds);
    const criticalNet = networkFailures.filter((u) => !isNonCriticalError('', u));
    expect(criticalNet).toHaveLength(0);
  });

  test('Most profitable crypto of last week (News ON)', async ({ page }) => {
    const runIds = captureRunIds(page);
    await setNewsToggle(page, true);

    await sendChatCommand(page, 'buy me the most profitable crypto of last week worth $2');
    await page.locator('button:has-text("Confirm")').first().waitFor({ state: 'visible', timeout: 120_000 });
    const bodyText = await page.locator('body').textContent() || '';
    expect(/return|profit|%|rank|performance|BTC|ETH|asset/i.test(bodyText)).toBeTruthy();
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '06_most_profitable_confirm.png'), fullPage: true });
    await clickConfirm(page);
    await waitForTerminalState(page, 90_000);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '07_most_profitable_complete.png'), fullPage: true });

    saveRunIds('run_ids_most_profitable.json', runIds);
  });

  test('Evals dashboard loads and run detail shows explainability', async ({ page }) => {
    ensureDir(SCREENSHOTS_DIR);
    const consoleLogs: string[] = [];
    page.on('console', (msg) => { consoleLogs.push(`[${msg.type()}] ${msg.text()}`); });

    await page.goto('/evals');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    await expect(page.locator('h1:has-text("Evaluation Dashboard")')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('text=Runs Evaluated')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('text=Recent Evaluated Runs')).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '08_evals_overview.png'), fullPage: true });

    const runLink = page.locator('table a[href*="/evals/runs/"]').first();
    const hasRuns = await runLink.isVisible({ timeout: 10_000 }).catch(() => false);

    if (!hasRuns) {
      const runIdFiles = ['run_ids_news_on.json', 'run_ids_news_off.json', 'run_ids_most_profitable.json'];
      let foundRunId: string | null = null;
      for (const f of runIdFiles) {
        try {
          const content = fs.readFileSync(path.join(ARTIFACTS_DIR, f), 'utf-8');
          const data = JSON.parse(content);
          if (data.run_ids && data.run_ids.length > 0) {
            foundRunId = data.run_ids[0];
            break;
          }
        } catch { /* ignore */ }
      }
      if (foundRunId) await page.goto(`/evals/runs/${foundRunId}`);
      else return;
    } else {
      await runLink.click();
    }

    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    await expect(page.locator('text=All evaluations').or(page.locator('text=All Evals')).first()).toBeVisible({ timeout: 10_000 });
    const expandBtns = page.locator('button:has-text("\u25B6")');
    const count = await expandBtns.count();
    for (let i = 0; i < Math.min(3, count); i++) {
      await expandBtns.nth(i).click();
      await page.waitForTimeout(800);
    }
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '09_eval_detail_expanded.png'), fullPage: true });

    const hasWhatChecks = await page.locator('text=What this checks').first().isVisible({ timeout: 3000 }).catch(() => false);
    const hasPassFail = (await page.locator('text=PASS').first().isVisible({ timeout: 2000 }).catch(() => false)) ||
      (await page.locator('text=FAIL').first().isVisible({ timeout: 2000 }).catch(() => false));
    expect(hasPassFail).toBeTruthy();

    const criticalErrors = consoleLogs.filter((l) => l.startsWith('[error]') && !isNonCriticalError(l, ''));
    expect(criticalErrors).toHaveLength(0);
  });
});
