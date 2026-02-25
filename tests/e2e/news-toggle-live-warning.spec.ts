import { test, expect, type Page, type Route } from '@playwright/test';

test.use({ baseURL: 'http://localhost:3001' });

async function mockApi(page: Page) {
  await page.route('**/api/v1/**', async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();

    if (url.includes('/api/v1/ops/health')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, db_ok: true, schema_ok: true, message: 'ok', migrations_applied: 1, migrations_pending: 0, pending_list: [] }) });
      return;
    }
    if (url.includes('/api/v1/ops/capabilities')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          live_trading_enabled: false,
          paper_trading_enabled: true,
          insights_enabled: true,
          news_enabled: true,
          db_ready: true,
          remediation: 'disabled by test',
        }),
      });
      return;
    }
    if (url.endsWith('/api/v1/conversations') && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
      return;
    }
    if (url.endsWith('/api/v1/conversations') && method === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ conversation_id: 'conv_test', title: null, created_at: new Date().toISOString() }) });
      return;
    }
    if (url.includes('/api/v1/conversations/conv_test/messages') && method === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ message_id: `msg_${Date.now()}`, conversation_id: 'conv_test', created_at: new Date().toISOString() }) });
      return;
    }
    if (url.includes('/api/v1/conversations/conv_test/messages') && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
      return;
    }
    if (url.includes('/api/v1/runs') && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
      return;
    }
    if (url.includes('/api/v1/chat/command') && method === 'POST') {
      const body = req.postDataJSON() as { text: string; news_enabled?: boolean };
      const newsOn = body.news_enabled !== false;
      const response = {
        content: newsOn
          ? 'Please confirm.\n\nNo relevant news found. Query: Bitcoin, BTC, BTC-USD; Lookback: 24h; Sources: RSS, GDELT.'
          : 'Please confirm.',
        run_id: null,
        intent: 'TRADE_CONFIRMATION_PENDING',
        status: 'AWAITING_CONFIRMATION',
        confirmation_id: 'conf_test',
        pending_trade: { side: 'BUY', asset: 'BTC', amount_usd: 2, mode: 'LIVE', asset_class: 'CRYPTO', confirmation_id: 'conf_test' },
        narrative_structured: {
          lead: 'Please confirm.',
          lines: ['Action required.'],
          evidence: newsOn
            ? [{ label: 'News evidence (BTC, last 24h)', ref: 'url:/runs' }]
            : [{ label: 'Trade preflight report', ref: 'url:/runs' }],
        },
        financial_insight: newsOn
          ? {
              headline: 'BTC insight',
              why_it_matters: 'news context',
              key_facts: [],
              risk_flags: ['news_empty'],
              confidence: 0.5,
              sources: { price_source: 'coinbase', headlines: [] },
              generated_by: 'template',
              news_outcome: {
                queries: ['Bitcoin', 'BTC', 'BTC-USD'],
                lookback: '24h',
                sources: ['RSS', 'GDELT'],
                status: 'empty',
                reason: 'No relevant news found for requested asset in lookback window',
              },
            }
          : undefined,
      };
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) });
      return;
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

async function sendCommand(page: Page, text: string) {
  if (text.toLowerCase().includes('buy') && text.toLowerCase().includes('btc')) {
    await page.getByRole('button', { name: '💰 Buy $2 of BTC' }).click();
  } else {
    const input = page.getByRole('textbox', { name: 'Ask me anything about trading...' });
    await expect(input).toBeVisible();
    await input.fill(text);
  }
  const sendButton = page.getByRole('button', { name: 'Send' });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
}

test.describe('News toggle and concise live warning', () => {
  test('news ON shows explicit outcome + clickable news chip (no 404)', async ({ page }) => {
    await mockApi(page);
    await page.goto('/chat');

    const toggle = page.getByTestId('news-toggle');
    await expect(toggle).toBeVisible();
    if ((await toggle.getAttribute('aria-checked')) !== 'true') await toggle.click();

    await sendCommand(page, 'Buy $2 of BTC');
    await expect(page.getByText('Please confirm.').first()).toBeVisible();
    await expect(page.getByText('No relevant news found.')).toBeVisible();

    const chip = page.getByTestId('evidence-chip').filter({ hasText: 'News evidence (BTC, last 24h)' }).first();
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page).toHaveURL(/\/runs/);
  });

  test('news OFF omits news section and news evidence chip', async ({ page }) => {
    await mockApi(page);
    await page.goto('/chat');

    const toggle = page.getByTestId('news-toggle');
    await expect(toggle).toBeVisible();
    if ((await toggle.getAttribute('aria-checked')) !== 'false') await toggle.click();

    await sendCommand(page, 'Buy $2 of BTC');
    await expect(page.getByText('Please confirm.').first()).toBeVisible();
    await expect(page.getByText('No relevant news found.')).toHaveCount(0);
    await expect(page.getByText('News evidence (BTC, last 24h)')).toHaveCount(0);
  });

  test('live staging warning copy is concise', async ({ page }) => {
    await mockApi(page);
    await page.goto('/chat');
    await sendCommand(page, 'Buy $2 of BTC');
    await expect(page.getByText('Please confirm.').first()).toBeVisible();

    const callout = page.getByText('To execute this LIVE trade, confirm it in your Coinbase wallet.').first();
    await expect(callout).toBeVisible();
    await expect(page.getByText('Confirmation required')).toBeVisible();
    await expect(page.getByText('No funds move until you confirm.')).toBeVisible();

    const h = await callout.evaluate((el) => (el as HTMLElement).getBoundingClientRect().height);
    expect(h).toBeLessThan(70);
  });
});
