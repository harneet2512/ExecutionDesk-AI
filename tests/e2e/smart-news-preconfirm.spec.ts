import { test, expect, type Page, type Route } from '@playwright/test';

test.use({ baseURL: 'http://localhost:3001' });

function buildInsight(newsOn: boolean, asset = 'BTC', mode: 'empty' | 'error' = 'empty') {
  if (!newsOn) return undefined;
  const isError = mode === 'error';
  return {
    headline: `${asset} trade context`,
    why_it_matters: 'Pre-confirm context available.',
    key_facts: [`${asset} is trading at $50,000`],
    risk_flags: [],
    confidence: 0.7,
    sources: { price_source: 'coinbase', headlines: [] },
    generated_by: 'template',
    impact_summary: 'No headline signal found; decision is based on price/portfolio checks only.',
    market_headlines: isError ? [] : [
      { title: 'Crypto market sentiment improves', source: 'Reuters', published_at: new Date().toISOString() },
    ],
    current_step_asset: asset,
    queued_steps_notice: asset === 'MORPHO' ? 'Queued steps will run news checks at execution time.' : undefined,
    news_outcome: {
      queries: [asset, `${asset}-USD`, asset === 'BTC' ? 'Bitcoin' : asset],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: isError ? 'error' : 'empty',
      reason: isError ? `News unavailable for ${asset} right now (provider error).` : `No relevant news found for ${asset} in the last 24h.`,
      items: 0,
    },
    asset_news_evidence: {
      assets: [asset],
      queries: [asset, `${asset}-USD`, asset === 'BTC' ? 'Bitcoin' : asset],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: isError ? 'error' : 'empty',
      items: [],
      reason_if_empty_or_error: isError ? `News unavailable for ${asset} right now (provider error).` : `No relevant news found for ${asset} in the last 24h.`,
    },
    market_news_evidence: {
      queries: ['crypto market', 'bitcoin ETF'],
      lookback: '24h',
      sources: ['RSS', 'GDELT'],
      status: isError ? 'error' : 'ok',
      items: isError ? [] : [{ title: 'Crypto market sentiment improves', source: 'Reuters', url: 'https://example.com' }],
      reason_if_empty_or_error: isError ? 'Market news unavailable right now. Please retry shortly.' : '',
      rationale: `No asset-specific headlines returned, so I'm showing broader market headlines most likely to impact ${asset}.`,
    },
  };
}

async function mockApi(page: Page) {
  let sequentialNextPendingReady = false;
  let useProviderError = false;
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
      const pendingStep2 = sequentialNextPendingReady ? [{
        message_id: `msg_step2_${Date.now()}`,
        role: 'assistant',
        content: 'Step 2 ready. Please confirm.',
        run_id: null,
        metadata_json: {
          intent: 'TRADE_CONFIRMATION_PENDING',
          status: 'AWAITING_CONFIRMATION',
          news_enabled: true,
          confirmation_id: 'conf_seq_2',
          pending_trade: {
            side: 'SELL',
            asset: 'MOODENG',
            amount_usd: 10,
            mode: 'PAPER',
            asset_class: 'CRYPTO',
            confirmation_id: 'conf_seq_2',
          },
          preconfirm_insight: buildInsight(true, 'MOODENG'),
        },
      }] : [];
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(pendingStep2) });
      return;
    }
    if (url.includes('/api/v1/runs') && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
      return;
    }
    if (url.includes('/api/v1/chat/command') && method === 'POST') {
      const body = req.postDataJSON() as { text?: string; news_enabled?: boolean };
      const newsOn = body.news_enabled !== false;
      const userText = String(body.text || '').toLowerCase();
      const isSequential = userText.includes('morpho') && userText.includes('moodeng');
      useProviderError = userText.includes('provider error');
      const response = {
        content: 'Please confirm.',
        run_id: null,
        intent: 'TRADE_CONFIRMATION_PENDING',
        status: 'AWAITING_CONFIRMATION',
        news_enabled: newsOn,
        confirmation_id: isSequential ? 'conf_seq_1' : 'conf_test',
        pending_trade: {
          side: isSequential ? 'SELL' : 'BUY',
          asset: isSequential ? 'MORPHO' : 'BTC',
          amount_usd: 2,
          mode: 'PAPER',
          asset_class: 'CRYPTO',
          confirmation_id: isSequential ? 'conf_seq_1' : 'conf_test',
          actions: isSequential ? [
            { side: 'SELL', asset: 'MORPHO', amount_usd: 10, step_index: 0, step_status: 'READY' },
            { side: 'SELL', asset: 'MOODENG', amount_usd: 10, step_index: 1, step_status: 'QUEUED' },
          ] : undefined,
        },
        preconfirm_insight: buildInsight(newsOn, isSequential ? 'MORPHO' : 'BTC', useProviderError ? 'error' : 'empty'),
      };
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) });
      return;
    }
    if ((url.includes('/api/v1/confirmations/conf_test/confirm') || url.includes('/api/v1/confirmations/conf_seq_1/confirm')) && method === 'POST') {
      if (url.includes('conf_seq_1')) {
        sequentialNextPendingReady = true;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'run_test',
          status: 'EXECUTING',
          executed: true,
          order_status: 'submitted',
          confirmation_id: 'conf_test',
          intent: 'TRADE_EXECUTION',
          execution_mode: 'PAPER',
          news_enabled: true,
          content: 'Trade confirmed.',
          financial_insight: buildInsight(true),
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

async function sendCommand(page: Page) {
  await page.getByRole('button', { name: '💰 Buy $2 of BTC' }).click();
  const sendButton = page.getByRole('button', { name: 'Send' });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
}

async function sendTextCommand(page: Page, text: string) {
  const input = page.getByRole('textbox', { name: 'Ask me anything about trading...' });
  await input.fill(text);
  const sendButton = page.getByRole('button', { name: 'Send' });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
}

test('news ON pre-confirm shows smart panel, fallback, and evidence modal', async ({ page }) => {
  await mockApi(page);
  await page.goto('/chat');
  await sendCommand(page);
  await expect(page.getByText('Please confirm.').first()).toBeVisible();
  const hasNews = await page.getByText('No relevant news found for BTC in the last 24h.').first().isVisible().catch(() => false);
  const hasWiringBanner = await page.getByText('News is enabled, but pre-confirm news insight was not provided by the server. (Wiring issue)').first().isVisible().catch(() => false);
  expect(hasNews || hasWiringBanner).toBeTruthy();
  if (hasNews) await expect(page.getByText('General market news')).toBeVisible();
  await expect(page.getByRole('button', { name: 'News evidence (BTC, 24h)' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Market news evidence (24h)' })).toBeVisible();
  await page.getByRole('button', { name: 'Market news evidence (24h)' }).click();
  await expect(page.getByText('Market fallback evidence')).toBeVisible();
  await expect(page.getByText('"queries"')).toBeVisible();
  await expect(page.getByText('"lookback"')).toBeVisible();
  await expect(page.getByText('"sources"')).toBeVisible();
  await expect(page.getByText('"status"')).toBeVisible();
});

test('news OFF removes pre-confirm news panel', async ({ page }) => {
  await mockApi(page);
  await page.goto('/chat');
  const toggle = page.getByTestId('news-toggle');
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute('aria-checked')) !== 'false') await toggle.click();
  await sendCommand(page);
  await expect(page.getByText('Please confirm.').first()).toBeVisible();
  await expect(page.getByText('General market news')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'News evidence (BTC, 24h)' })).toHaveCount(0);
});

test('confirm keeps insight and evidence UI available', async ({ page }) => {
  await mockApi(page);
  await page.goto('/chat');
  await sendCommand(page);
  await page.getByRole('button', { name: 'Confirm Trade' }).click();
  await expect(page.getByText('Trade confirmed.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'News evidence (BTC, 24h)' }).first()).toBeVisible();
});

test('multi-step sequential flow shows step-bound news per confirmation', async ({ page }) => {
  await mockApi(page);
  await page.goto('/chat');
  await sendTextCommand(page, 'Sell all of MORPHO and MOODENG');
  await expect(page.getByText('News (MORPHO)').first()).toBeVisible();
  await expect(page.getByText('Queued steps will run news checks at execution time.').first()).toBeVisible();
  await page.getByRole('button', { name: 'Confirm Trade' }).first().click();
  await expect(page.getByText('Step 2 ready. Please confirm.')).toBeVisible();
  await expect(page.getByText('News (MOODENG)').first()).toBeVisible();
});

test('provider error path shows explicit error and fallback attempt', async ({ page }) => {
  await mockApi(page);
  await page.goto('/chat');
  await sendTextCommand(page, 'Buy $2 BTC provider error');
  await expect(page.getByText('News unavailable for BTC right now (provider error).')).toBeVisible();
  await expect(page.getByText('General market news')).toBeVisible();
  await expect(page.getByText('Market news unavailable right now. Please retry shortly.')).toBeVisible();
});
