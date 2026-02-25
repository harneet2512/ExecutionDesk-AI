import { test, expect, type Page, type Route } from '@playwright/test';

test.use({ baseURL: 'http://localhost:3001' });

const portfolioSnapshotCardData = {
  as_of: new Date().toISOString(),
  mode: 'PAPER',
  total_value_usd: 1250.5,
  cash_usd: 400.25,
  holdings: [
    { asset_symbol: 'BTC', qty: 0.01, usd_value: 500.0, current_price: 50000.0 },
    { asset_symbol: 'ETH', qty: 0.2, usd_value: 350.25, current_price: 1751.25 },
  ],
  risk: {
    risk_level: 'MEDIUM',
    concentration_pct_top1: 40.0,
    concentration_pct_top3: 90.0,
    diversification_score: 0.52,
  },
  recommendations: [
    { title: 'Rebalance concentration', description: 'Top position exceeds 35%.', priority: 'HIGH' },
  ],
};

function buildInsight(asset = 'BTC') {
  return {
    headline: `${asset} trade context`,
    why_it_matters: 'Pre-confirm context available.',
    key_facts: [`${asset} is trading with mixed momentum`],
    risk_flags: [],
    confidence: 0.65,
    sources: { price_source: 'coinbase', headlines: [] },
    generated_by: 'template',
    news_outcome: {
      queries: [asset, `${asset}-USD`],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: 'empty',
      reason: `No relevant news found for ${asset} in the last 24h.`,
      items: 0,
    },
    asset_news_evidence: {
      assets: [asset],
      queries: [asset, `${asset}-USD`],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: 'empty',
      items: [],
      reason_if_empty_or_error: `No relevant news found for ${asset} in the last 24h.`,
    },
    market_news_evidence: {
      queries: ['crypto market'],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: 'ok',
      items: [{ title: 'Crypto market steady', source: 'Reuters', url: 'https://example.com' }],
    },
  };
}

async function mockApi(page: Page) {
  await page.route('**/api/v1/**', async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();

    if (url.includes('/api/v1/ops/health')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, db_ok: true, schema_ok: true }) });
      return;
    }
    if (url.includes('/api/v1/ops/capabilities')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ live_trading_enabled: false, paper_trading_enabled: true, news_enabled: true, db_ready: true }),
      });
      return;
    }
    if (url.endsWith('/api/v1/conversations') && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
      return;
    }
    if (url.endsWith('/api/v1/conversations') && method === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ conversation_id: 'conv_test', created_at: new Date().toISOString() }) });
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
    if (url.includes('/api/v1/runs/run_portfolio/trace') && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          plan: null,
          parsed_intent: null,
          steps: [],
          artifacts: {},
          status: 'COMPLETED',
          portfolio_brief: portfolioSnapshotCardData,
        }),
      });
      return;
    }
    if (url.includes('/api/v1/chat/command') && method === 'POST') {
      const body = req.postDataJSON() as { text?: string; news_enabled?: boolean };
      const text = String(body.text || '').toLowerCase();
      if (text.includes('analyze') && text.includes('portfolio')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            content: 'Portfolio analysis complete.',
            run_id: 'run_portfolio',
            intent: 'PORTFOLIO_ANALYSIS',
            status: 'COMPLETED',
            portfolio_snapshot_card_data: portfolioSnapshotCardData,
            narrative_structured: { lead: 'Portfolio Snapshot ready.', lines: ['Review allocation and risk.'] },
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          content: 'Please confirm.',
          run_id: null,
          intent: 'TRADE_CONFIRMATION_PENDING',
          status: 'AWAITING_CONFIRMATION',
          news_enabled: body.news_enabled !== false,
          confirmation_id: 'conf_test',
          pending_trade: {
            side: 'BUY',
            asset: 'BTC',
            amount_usd: 2,
            mode: 'PAPER',
            asset_class: 'CRYPTO',
            confirmation_id: 'conf_test',
          },
          preconfirm_insight: buildInsight('BTC'),
        }),
      });
      return;
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

async function sendTextCommand(page: Page, text: string) {
  const input = page.getByRole('textbox', { name: 'Ask me anything about trading...' });
  await input.fill(text);
  const sendButton = page.getByRole('button', { name: 'Send' });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
}

test('Analyze my portfolio shows Portfolio Snapshot card', async ({ page }) => {
  await mockApi(page);
  await page.goto('/chat');
  await sendTextCommand(page, 'Analyze my portfolio');

  await expect(page.getByText('Portfolio Snapshot').first()).toBeVisible();
  await expect(page.getByText('Total Value').first()).toBeVisible();
  await expect(page.getByText('Cash').first()).toBeVisible();
  await expect(page.getByRole('cell', { name: 'BTC' }).first()).toBeVisible();
});

test('Buy $2 BTC keeps trade confirmation news panel', async ({ page }) => {
  await mockApi(page);
  await page.goto('/chat');
  await sendTextCommand(page, 'Buy $2 BTC');

  await expect(page.getByText('Action Required').first()).toBeVisible();
  await expect(page.getByText('News (BTC)').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'News evidence (BTC, 24h)' }).first()).toBeVisible();
});

test('Portfolio snapshot persists after staging trade in same session', async ({ page }) => {
  await mockApi(page);
  await page.goto('/chat');

  await sendTextCommand(page, 'Analyze my portfolio');
  await expect(page.getByText('Portfolio Snapshot').first()).toBeVisible();

  await sendTextCommand(page, 'Buy $2 BTC');
  await expect(page.getByText('Action Required').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'News evidence (BTC, 24h)' }).first()).toBeVisible();
  await expect(page.getByText('Portfolio Snapshot').first()).toBeVisible();
});
