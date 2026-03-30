import { expect, test } from '@playwright/test';

test.use({ baseURL: process.env.BASE_URL || 'http://localhost:3000' });

test('single-asset sell uses executable quantity', async ({ page }) => {
  await page.goto('/portfolio');
  await expect(page).toHaveURL(/portfolio/);

  await page.goto('/chat');
  const input = page.locator('input[type="text"], textarea').first();
  await input.fill('Sell my complete holding of MORPHO');
  await input.press('Enter');

  await expect(page.locator('[data-testid="narrative-lines"]')).toBeVisible({ timeout: 30_000 });
  const text = (await page.locator('[data-testid="narrative-lines"]').first().textContent()) || '';
  expect(text).not.toContain('Quantity unavailable');
  expect(text.toLowerCase()).toContain('step 1');
});

test('sell all holdings plans sequential executable subset', async ({ page }) => {
  await page.goto('/chat');
  const input = page.locator('input[type="text"], textarea').first();
  await input.fill('Sell all holdings');
  await input.press('Enter');

  const narrative = page.locator('[data-testid="narrative-lines"]').first();
  await expect(narrative).toBeVisible({ timeout: 30_000 });
  const content = (await narrative.textContent()) || '';
  expect(content.toLowerCase()).toContain('sequentially');
  expect(content).toMatch(/Queued|Skipped|Step 1/i);
});

test('evidence chips never navigate to 404', async ({ page }) => {
  await page.goto('/chat');
  const chips = page.locator('[data-testid="evidence-chip"]');
  const count = await chips.count();
  if (count === 0) {
    test.skip();
    return;
  }

  for (let i = 0; i < count; i++) {
    const chip = chips.nth(i);
    const disabled = await chip.getAttribute('data-disabled');
    if (disabled === 'true') {
      await expect(chip).toHaveAttribute('title', 'Evidence unavailable');
      continue;
    }
    await chip.click();
    await page.waitForTimeout(300);
    await expect(page).not.toHaveURL(/404|not-found/i);
  }
});
