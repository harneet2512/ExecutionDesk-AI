import { expect, test, type Page, type Route } from '@playwright/test';

test.use({ baseURL: 'http://localhost:3001', trace: 'retain-on-failure' });

type FillMode = 'always_pending' | 'fills_on_third_poll';

function buildDeterministicInsight() {
  return {
    headline: 'BTC trade context',
    why_it_matters: 'Pre-confirm smart-news context is available.',
    key_facts: [],
    risk_flags: [],
    confidence: 0.8,
    sources: { price_source: 'coinbase', headlines: [] },
    generated_by: 'template',
    impact_summary: 'No headline signal found; decision is based on price/portfolio checks only.',
    current_step_asset: 'BTC',
    news_outcome: {
      queries: ['BTC', 'BTC-USD', 'Bitcoin'],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: 'empty',
      reason: 'No relevant news found for BTC in the last 24h.',
      items: 0,
    },
    asset_news_evidence: {
      assets: ['BTC'],
      queries: ['BTC', 'BTC-USD', 'Bitcoin'],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: 'empty',
      items: [],
      reason_if_empty_or_error: 'No relevant news found for BTC in the last 24h.',
    },
    market_news_evidence: {
      queries: ['crypto market', 'bitcoin ETF'],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: 'ok',
      items: [
        { title: 'Crypto market sentiment improves', source: 'Reuters', url: 'https://example.com/market-1' },
        { title: 'Bitcoin ETF flows remain positive', source: 'Bloomberg', url: 'https://example.com/market-2' },
      ],
      reason_if_empty_or_error: '',
      rationale: "No asset-specific headlines returned, so I'm showing broader market headlines most likely to impact BTC.",
    },
  };
}

async function mockChatFlow(page: Page, fillMode: FillMode) {
  let fillStatusCalls = 0;
  let stagedTradeReady = false;
  let tradeConfirmed = false;
  const insight = buildDeterministicInsight();

  await page.route('**/api/v1/**', async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();

    if (url.includes('/api/v1/ops/health')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          db_ok: true,
          schema_ok: true,
          message: 'ok',
          migrations_applied: 1,
          migrations_pending: 0,
          pending_list: [],
        }),
      });
      return;
    }

    if (url.includes('/api/v1/ops/capabilities')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          live_trading_enabled: true,
          paper_trading_enabled: true,
          insights_enabled: true,
          news_enabled: true,
          db_ready: true,
        }),
      });
      return;
    }

    if (url.endsWith('/api/v1/conversations') && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
      return;
    }

    if (url.endsWith('/api/v1/conversations') && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          conversation_id: 'conv_timeout',
          title: null,
          created_at: new Date().toISOString(),
        }),
      });
      return;
    }

    if (url.includes('/api/v1/conversations/conv_timeout') && !url.includes('/messages') && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          conversation_id: 'conv_timeout',
          tenant_id: 't_default',
          title: 'Timeout Test',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      });
      return;
    }

    if (url.includes('/api/v1/conversations/conv_timeout/messages') && method === 'GET') {
      const stagedAssistantMessage = stagedTradeReady && !tradeConfirmed
        ? [
          {
            message_id: 'msg_staged_timeout',
            conversation_id: 'conv_timeout',
            role: 'assistant',
            content: 'Please confirm.',
            created_at: new Date().toISOString(),
            metadata_json: {
              intent: 'TRADE_CONFIRMATION_PENDING',
              status: 'AWAITING_CONFIRMATION',
              news_enabled: true,
              confirmation_id: 'conf_timeout',
              pending_trade: {
                side: 'BUY',
                asset: 'BTC',
                amount_usd: 2,
                mode: 'LIVE',
                asset_class: 'CRYPTO',
                confirmation_id: 'conf_timeout',
              },
              preconfirm_insight: insight,
              financial_insight: insight,
            },
          },
        ]
        : [];
      const executionMessages = tradeConfirmed
        ? [
          {
            message_id: 'msg_confirm_user',
            conversation_id: 'conv_timeout',
            role: 'user',
            content: 'CONFIRM',
            created_at: new Date().toISOString(),
          },
          {
            message_id: 'msg_execution_timeout',
            conversation_id: 'conv_timeout',
            role: 'assistant',
            content: 'Executing BUY $2.00 BTC...',
            run_id: 'run_timeout',
            created_at: new Date().toISOString(),
            metadata_json: {
              intent: 'TRADE_EXECUTION',
              status: 'EXECUTING',
              preconfirm_insight: insight,
              financial_insight: insight,
            },
          },
        ]
        : [];
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([...stagedAssistantMessage, ...executionMessages]),
      });
      return;
    }

    if (url.includes('/api/v1/conversations/conv_timeout/messages') && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          message_id: `msg_${Date.now()}`,
          conversation_id: 'conv_timeout',
          created_at: new Date().toISOString(),
        }),
      });
      return;
    }

    if (url.includes('/api/v1/chat/command') && method === 'POST') {
      stagedTradeReady = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          content: 'Please confirm.',
          run_id: null,
          intent: 'TRADE_CONFIRMATION_PENDING',
          status: 'AWAITING_CONFIRMATION',
          news_enabled: true,
          confirmation_id: 'conf_timeout',
          pending_trade: {
            side: 'BUY',
            asset: 'BTC',
            amount_usd: 2,
            mode: 'LIVE',
            asset_class: 'CRYPTO',
            confirmation_id: 'conf_timeout',
          },
          preconfirm_insight: insight,
          financial_insight: insight,
        }),
      });
      return;
    }

    if (url.includes('/api/v1/confirmations') && method === 'POST') {
      tradeConfirmed = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'run_timeout',
          order_id: 'ord_timeout',
          status: 'EXECUTING',
          executed: true,
          order_status: 'submitted',
          confirmation_id: 'conf_timeout',
          intent: 'TRADE_EXECUTION',
          execution_mode: 'LIVE',
          content: 'Trade confirmed.',
        }),
      });
      return;
    }

    if (url.includes('/api/v1/runs/status/run_timeout')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'run_timeout',
          status: 'COMPLETED',
          started_at: new Date(Date.now() - 1000).toISOString(),
          completed_at: new Date().toISOString(),
          current_step: 'execution',
          total_steps: 10,
          completed_steps: 10,
          updated_at: new Date().toISOString(),
          execution_mode: 'LIVE',
        }),
      });
      return;
    }

    if (url.includes('/api/v1/runs/run_timeout/events')) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
        body: 'event: keepalive\ndata: {}\n\n',
      });
      return;
    }

    if (url.includes('/api/v1/runs/run_timeout/trace')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'COMPLETED',
          artifacts: {},
          recent_events: [],
        }),
      });
      return;
    }

    if (url.includes('/api/v1/runs/run_timeout') && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run: {
            run_id: 'run_timeout',
            status: 'COMPLETED',
            execution_mode: 'LIVE',
            metadata_json: JSON.stringify({ side: 'BUY', asset: 'BTC', amount_usd: 2 }),
          },
          orders: [
            {
              order_id: 'ord_timeout',
              symbol: 'BTC-USD',
              side: 'BUY',
              notional_usd: 2,
              status: 'SUBMITTED',
              filled_qty: 0,
              avg_fill_price: 0,
              total_fees: 0,
              created_at: new Date().toISOString(),
            },
          ],
          fills: [],
          nodes: [],
          approvals: [],
          evals: [],
          snapshots: [],
        }),
      });
      return;
    }

    if (url.includes('/api/v1/orders/ord_timeout/fill-status')) {
      fillStatusCalls += 1;
      if (fillMode === 'fills_on_third_poll' && fillStatusCalls >= 3) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            order_id: 'ord_timeout',
            status: 'FILLED',
            filled_qty: 0.00004,
            avg_fill_price: 50000,
            fill_confirmed: true,
            message: 'Order filled. You can also confirm in your Coinbase app.',
          }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          order_id: 'ord_timeout',
          status: 'PENDING',
          filled_qty: 0,
          avg_fill_price: 0,
          fill_confirmed: false,
          message: 'Order submitted. You can confirm fill in your Coinbase app.',
        }),
      });
      return;
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

async function stageAndConfirmBuy(page: Page) {
  await page.goto('/chat');
  const input = page.getByRole('textbox', { name: 'Ask me anything about trading...' });
  await input.fill('Buy $2 BTC');
  const sendButton = page.getByRole('button', { name: 'Send' });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();

  // Staging card + pre-confirm news should still render.
  await expect(page.getByText('Action Required')).toBeVisible();
  const hasNewsTitle = await page.getByText('News (BTC)').first().isVisible().catch(() => false);
  const hasNoRelevantNews = await page.getByText('No relevant news found for BTC').first().isVisible().catch(() => false);
  const hasGeneralMarketNews = await page.getByText('General market news').first().isVisible().catch(() => false);
  expect(hasNewsTitle || hasNoRelevantNews || hasGeneralMarketNews).toBeTruthy();
  await expect(page.getByRole('button', { name: 'News evidence (BTC, 24h)' }).first()).toBeVisible();
  await expect(page.getByText('Portfolio Snapshot')).toHaveCount(0);

  await page.getByRole('button', { name: 'Confirm Trade' }).click();
}

test.describe('Fill Timeout Banner', () => {
  test.describe.configure({ retries: 0 });

  test('pending fill shows exact timeout message and never filled label', async ({ page }) => {
    test.skip(
      process.env.NEXT_PUBLIC_FILL_POLL_TIMEOUT_MS !== '2000' ||
      process.env.NEXT_PUBLIC_FILL_POLL_INTERVAL_MS !== '200',
      'Run with NEXT_PUBLIC_FILL_POLL_TIMEOUT_MS=2000 and NEXT_PUBLIC_FILL_POLL_INTERVAL_MS=200',
    );

    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (!text.includes('EventSource')) consoleErrors.push(text);
      }
    });
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));

    await mockChatFlow(page, 'always_pending');
    await stageAndConfirmBuy(page);

    await expect(page.getByText('Order submitted. You can confirm fill in your Coinbase app.').first()).toBeVisible();
    await expect(page.getByText('Order filled. You can also confirm in your Coinbase app.')).toHaveCount(0);
    await expect(
      page.getByText('Order submitted; fill not confirmed within 60s. Check Coinbase app for final status.')
    ).toBeVisible({ timeout: 7000 });
    await expect(page.getByText('Order filled. You can also confirm in your Coinbase app.')).toHaveCount(0);

    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
  });

  test('fills before timeout upgrades to filled and never shows timeout banner', async ({ page }) => {
    test.skip(
      process.env.NEXT_PUBLIC_FILL_POLL_TIMEOUT_MS !== '2000' ||
      process.env.NEXT_PUBLIC_FILL_POLL_INTERVAL_MS !== '200',
      'Run with NEXT_PUBLIC_FILL_POLL_TIMEOUT_MS=2000 and NEXT_PUBLIC_FILL_POLL_INTERVAL_MS=200',
    );

    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (!text.includes('EventSource')) consoleErrors.push(text);
      }
    });
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));

    await mockChatFlow(page, 'fills_on_third_poll');
    await stageAndConfirmBuy(page);

    await expect(page.getByText('Order submitted. You can confirm fill in your Coinbase app.').first()).toBeVisible();
    await expect(page.getByText('Order filled. You can also confirm in your Coinbase app.')).toBeVisible({ timeout: 7000 });
    await expect(
      page.getByText('Order submitted; fill not confirmed within 60s. Check Coinbase app for final status.')
    ).toHaveCount(0);

    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
  });
});
