import { test, expect, type Page } from '@playwright/test';

const RUN_ID = 'run-test-enterprise';

async function setupRunDetailsMocks(page: Page) {
  const manyEvals = Array.from({ length: 24 }).map((_, i) => ({
    eval_name: `metric_${i}`,
    score: i % 4 === 0 ? 0.42 : 0.86,
    reasons: [`reason_${i}`],
    evaluator_type: 'enterprise',
    thresholds: { threshold: 0.5 },
    details: { sample_input: i, artifact: `artifact_${i}` },
    definition: {
      title: `Metric ${i}`,
      description: `Checks quality metric ${i}`,
      category: 'quality',
      rubric: `score = weighted(metric_${i})`,
      how_to_improve: ['improve input quality'],
      threshold: 0.5,
      evaluator_type: 'enterprise',
    },
    category: 'quality',
    pass: i % 4 !== 0,
  }));

  await page.route(`**/api/v1/runs/${RUN_ID}/events`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: 'data: {"event_type":"PING"}\n\n',
    });
  });

  await page.route(`**/api/v1/runs/status/${RUN_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ run_id: RUN_ID, status: 'COMPLETED' }),
    });
  });

  await page.route(`**/api/v1/runs/${RUN_ID}/trace`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        plan: { strategy_spec: { window: '1h' } },
        steps: Array.from({ length: 20 }).map((_, i) => ({
          step_id: `s_${i}`,
          step_name: `step_${i}`,
          status: 'COMPLETED',
        })),
        artifacts: {
          rankings: [
            {
              symbol: 'BTC-USD',
              score: 0.93,
              first_price: null,
              last_price: null,
              first_price_reason: 'Missing first candle open for selected lookback',
              last_price_reason: 'Missing last candle close for selected lookback',
              return_reason: 'Return unavailable because first/last price could not be computed',
            },
          ],
          candles_batches: [],
          tool_calls: [],
          rankings_meta: { lookback_window: '1h', universe_count: 1 },
        },
        status: 'COMPLETED',
      }),
    });
  });

  await page.route(`**/api/v1/runs/${RUN_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run: {
          run_id: RUN_ID,
          status: 'COMPLETED',
          execution_mode: 'PAPER',
          command_text: 'buy $10 btc',
        },
        nodes: [{ node_id: 'n1', name: 'research', status: 'COMPLETED' }],
        policy_events: [],
        approvals: [],
        orders: [{ order_id: 'o1', symbol: 'BTC-USD', side: 'BUY', notional_usd: 10, status: 'SUBMITTED' }],
        snapshots: [],
        evals: [],
        fills: [],
      }),
    });
  });

  await page.route('**/api/v1/portfolio/metrics/value-over-time**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.route('**/api/v1/approvals**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.route('**/api/v1/analytics/pnl**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(null) });
  });
  await page.route('**/api/v1/analytics/slippage**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(null) });
  });

  await page.route(`**/api/v1/evals/run/${RUN_ID}/details`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run: { run_id: RUN_ID, command: 'buy $10 btc', mode: 'PAPER', status: 'COMPLETED', created_at: new Date().toISOString() },
        summary: { total_evals: manyEvals.length, avg_score: 0.8, grade: 'B', passed: 20, failed: 4 },
        categories: {
          quality: { avg_score: 0.8, grade: 'B', total: manyEvals.length, passed: 20, failed: 4, evals: manyEvals },
        },
      }),
    });
  });
}

test.describe('Run Details enterprise reliability', () => {
  test('loads without console errors and supports page scroll', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await setupRunDetailsMocks(page);
    await page.goto(`/runs/${RUN_ID}`);
    await expect(page.getByText('Run Details')).toBeVisible();

    const scrollChanged = await page.evaluate(() => {
      const main = document.querySelector('main');
      if (!main) return false;
      const before = main.scrollTop;
      main.scrollTop = main.scrollHeight;
      return main.scrollTop > before;
    });
    expect(scrollChanged).toBeTruthy();
    expect(errors).toEqual([]);
  });

  test('evals tab scrolls and details include formula and raw json', async ({ page }) => {
    await setupRunDetailsMocks(page);
    await page.goto(`/runs/${RUN_ID}`);
    await page.getByTestId('run-tab-evals').click();
    await expect(page.getByTestId('run-evals-list')).toBeVisible();

    const listScrolled = await page.getByTestId('run-evals-list').evaluate((el) => {
      const node = el as HTMLElement;
      const before = node.scrollTop;
      node.scrollTop = node.scrollHeight;
      return node.scrollTop > before;
    });
    expect(listScrolled).toBeTruthy();

    await page.getByTestId('eval-view-details-0').click();
    await expect(page.getByText('Formula:')).toBeVisible();
    await expect(page.getByTestId('eval-raw-json-0')).toContainText('metric_0');
  });

  test('charts/evidence tabs never show blank box states', async ({ page }) => {
    await setupRunDetailsMocks(page);
    await page.goto(`/runs/${RUN_ID}`);

    await page.getByTestId('run-tab-charts').click();
    const hasCoverage = await page.getByText(/Data coverage: Points:/).count();
    const hasUnavailable = await page.getByText(/chart unavailable because|unavailable because/i).count();
    expect(hasCoverage + hasUnavailable).toBeGreaterThan(0);

    await page.getByTestId('run-tab-evidence').click();
    await expect(page.getByText('Asset Rankings')).toBeVisible();
    await expect(page.getByText('Unavailable').first()).toBeVisible();
  });
});
