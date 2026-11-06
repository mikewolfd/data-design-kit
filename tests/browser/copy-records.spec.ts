import { test, expect } from '@playwright/test';

test('refused and unknown reads announce no loaded records and offer no futile retry', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  for (const [suffix, title] of [
    [':withheld', 'This version is withheld'],
    [':unresolved', 'Record availability is unknown'],
  ]) {
    const version = snapshot.catalog.versions.find((v: { id: string }) => v.id.endsWith(suffix));
    await page.goto(`/?catalog=watershed&tab=Data&version=${encodeURIComponent(version.id)}`);
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await expect(page.locator('.result-bar [role="status"]')).toHaveText(
      'Records were not loaded.',
    );
    await expect(page.getByRole('button', { name: 'Retry read', exact: true })).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Download this page (JSON) ↓', exact: true }),
    ).toHaveCount(0);
  }
});

test('expired cursor recovery starts the first page and keeps selected version and filter', async ({
  page,
}) => {
  let failed = false;
  const seen: any[] = [];
  await page.route('**/api/read', async (route) => {
    const body = route.request().postDataJSON();
    seen.push(body);
    if (body.cursor && !failed) {
      failed = true;
      await route.fulfill({
        status: 400,
        json: { error: { code: 'invalid_cursor', message: 'Original cursor diagnostic' } },
      });
    } else await route.continue();
  });
  await page.goto('/?catalog=watershed&tab=Data');
  await expect(page.locator('.data-table tbody tr')).toHaveCount(10);
  await page.getByRole('button', { name: 'Next →', exact: true }).click();
  await expect(page.getByText('This page link is no longer valid', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Return to first page', exact: true }).click();
  await expect(page.locator('.data-table tbody tr')).toHaveCount(10);
  expect(seen.at(-1).cursor).toBeUndefined();
  expect(seen.at(-1).versionId).toBe(seen[0].versionId);
  expect(seen.at(-1).filter).toEqual(seen[0].filter);
});

test('quota and response size errors recommend only supported recovery', async ({ page }) => {
  await page.route('**/api/read', (route) =>
    route.fulfill({
      status: 413,
      json: { error: { code: 'native_quota', message: 'Original quota diagnostic' } },
    }),
  );
  await page.goto('/?catalog=watershed&tab=Data');
  await expect(page.getByRole('alert')).toContainText('until the operator resolves the limit');
  await expect(page.getByRole('button', { name: 'Retry read', exact: true })).toHaveCount(0);
  await expect(page.locator('.result-bar [role="status"]')).toHaveText('Records were not loaded.');
  await page.getByText('Error details', { exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Original quota diagnostic');
  await page.unroute('**/api/read');
  await page.route('**/api/read', (route) =>
    route.fulfill({
      status: 413,
      json: { error: { code: 'result_budget', message: 'Original size diagnostic' } },
    }),
  );
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('too large to display');
  await expect(page.getByRole('alert')).toContainText('change the filter');
  await expect(page.getByRole('button', { name: 'Retry read', exact: true })).toHaveCount(0);
});

test('query inputs have a short name and separate help and downloads describe exact scope', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  await page.goto('/?catalog=watershed&tab=Connections');
  const input = page.getByRole('textbox', {
    name: 'Minimum concentration (mg/L) (required)',
    exact: true,
  });
  await expect(input).toBeVisible();
  await expect(input).toHaveAttribute('aria-describedby', /help$/);
  await page
    .getByRole('combobox', { name: 'Named release', exact: true })
    .selectOption(
      snapshot.catalog.releases.find((r: any) =>
        r.members.some((id: string) => id.endsWith('observations:v2')),
      ).id,
    );
  await input.fill('2.000000000000000000');
  await page.getByRole('button', { name: 'Run query', exact: true }).click();
  await expect(page.locator('.recipe .data-table tbody tr')).toHaveCount(3);
  await expect(page.getByText(/Download includes the query request/)).toBeVisible();
  const download = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Download query and results (JSON) ↓', exact: true })
    .click();
  const path = await (await download).path();
  const saved = JSON.parse(await (await import('node:fs/promises')).readFile(path!, 'utf8'));
  expect(saved.scope).toContain('Up to 25');
  expect(saved.numericEncoding).toContain('$number');
  expect(saved.request.parameters.minimum_concentration.$number).toBe('2.000000000000000000');
  await page.getByText('View SQL', { exact: true }).click();
  await expect(page.locator('.sql-preview pre')).toContainText('SELECT');
});

test('an unknown request outcome does not invent unknown catalog availability', async ({
  page,
}) => {
  await page.route('**/api/read', (route) =>
    route.fulfill({
      json: {
        status: 'unknown',
        reason: 'The source deadline elapsed; work may still finish.',
        rows: [],
        columns: [],
        returned: 0,
      },
    }),
  );
  await page.goto('/?catalog=watershed&tab=Data');
  await expect(page.getByText('Request outcome is unknown', { exact: true })).toBeVisible();
  await expect(page.getByText('Record availability is unknown', { exact: true })).toHaveCount(0);
  await expect(page.locator('.result-bar [role="status"]')).toHaveText('Records were not loaded.');
  await page.getByText('Access details', { exact: true }).click();
  await expect(page.locator('.notice')).toContainText(
    'The source deadline elapsed; work may still finish.',
  );
});

test('saved request safety errors preserve the mapped recovery without claiming a quota reset', async ({
  page,
}) => {
  await page.route('**/api/read', (route) =>
    route.fulfill({
      status: 413,
      json: {
        error: {
          code: 'native_quota',
          message: 'A symbolic link was found in the saved request records.',
        },
      },
    }),
  );
  await page.goto('/?catalog=watershed&tab=Data');
  await expect(page.getByRole('alert')).toContainText('operator checks its saved request records');
  await expect(page.getByRole('alert')).not.toContainText('request limit');
  await expect(page.getByRole('button', { name: 'Retry read', exact: true })).toHaveCount(0);
});
