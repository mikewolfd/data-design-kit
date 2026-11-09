import { readFile } from 'node:fs/promises';
import { test, expect } from '@playwright/test';
import type { ReadRequest, ReadResult } from '../../src/domain/types';

test('withheld and unknown resources show distinct states without requesting a read', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  const reads: string[] = [];
  page.on('request', (read) => {
    if (read.url().endsWith('/api/read')) reads.push(read.url());
  });
  for (const [suffix, notice] of [
    [':withheld', 'The publisher has withheld the exact reference needed to open these records.'],
    [':unresolved', 'Record availability is unknown. No read request has been made.'],
  ]) {
    const version = snapshot.catalog.versions.find((v: { id: string }) => v.id.endsWith(suffix));
    await page.goto(`/?catalog=watershed&tab=Data&version=${encodeURIComponent(version.id)}`);
    await expect(page.getByText(notice, { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open records', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Retry read', exact: true })).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Download this page (JSON) ↓', exact: true }),
    ).toHaveCount(0);
    expect(reads).toHaveLength(0);
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
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
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
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
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
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('too large to display');
  await expect(page.getByRole('alert')).toContainText('change the filter');
  await expect(page.getByRole('button', { name: 'Retry read', exact: true })).toHaveCount(0);
});

test('query inputs have a short name and separate help and downloads describe exact scope', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  const operations: string[] = [];
  page.on('request', (operation) => {
    if (/\/api\/(read|query)$/.test(operation.url())) operations.push(operation.url());
  });
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
  expect(operations).toHaveLength(0);
  await page.getByRole('button', { name: 'Run query', exact: true }).click();
  await expect(page.locator('.recipe .data-table tbody tr')).toHaveCount(3);
  expect(operations).toEqual([expect.stringMatching(/\/api\/query$/)]);
  await expect(page.getByText(/Download includes the query request/)).toBeVisible();
  const download = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Download query and results (JSON) ↓', exact: true })
    .click();
  const path = await (await download).path();
  const saved = JSON.parse(await readFile(path!, 'utf8'));
  expect(saved.scope).toContain('Up to 25');
  expect(saved.numericEncoding).toContain('$number');
  expect(saved.request.parameters.minimum_concentration.$number).toBe('2.000000000000000000');
  await page.getByText('View SQL', { exact: true }).click();
  await expect(page.locator('.sql-preview pre')).toContainText('SELECT');
});

test('an unknown request outcome does not invent unknown catalog availability', async ({
  page,
}) => {
  await page.route('**/api/read', (route) => {
    const { datasetId, versionId, representationId, releaseId } = route
      .request()
      .postDataJSON() as ReadRequest;
    const unknown: ReadResult = {
      status: 'unknown',
      reason: 'The source deadline elapsed; work may still finish.',
      binding: { datasetId, versionId, representationId, releaseId },
      rows: [],
      columns: [],
      returned: 0,
      transport: 'ddk-exact-json-v1',
    };
    return route.fulfill({ json: unknown });
  });
  await page.goto('/?catalog=watershed&tab=Data');
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await expect(page.getByText('Request outcome is unknown', { exact: true })).toBeVisible();
  await expect(page.getByText('Record availability is unknown', { exact: true })).toHaveCount(0);
  await expect(page.locator('.result-bar [role="status"]')).toHaveText('Records were not loaded.');
  await page.getByText('Access details', { exact: true }).click();
  const notice = page.locator('.notice').filter({
    has: page.getByText('Request outcome is unknown', { exact: true }),
  });
  await expect(notice).toContainText('The source deadline elapsed; work may still finish.');
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
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('operator checks its saved request records');
  await expect(page.getByRole('alert')).not.toContainText('request limit');
  await expect(page.getByRole('button', { name: 'Retry read', exact: true })).toHaveCount(0);
});

test('publisher question counts only the returned page and both downloads keep its exact scope', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  await page.goto('/?catalog=watershed&tab=Data');
  const question = page.getByRole('heading', {
    name: 'How many returned observations refer to each station code?',
    exact: true,
  });
  await expect(question).toHaveCount(0);
  const reading = page.waitForResponse((response) => response.url().endsWith('/api/read'));
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  const response = await reading;
  expect(response.ok()).toBe(true);
  const read = (await response.json()) as ReadResult;
  const submitted = response.request().postDataJSON() as ReadRequest;
  expect(read.returned).toBe(10);
  expect(read.total).toBe(14);
  expect(read.continuation).toBe('more');
  await expect(question).toBeVisible();
  const chart = page.getByRole('figure', {
    name: 'How many returned observations refer to each station code?',
    exact: true,
  });
  const counts = chart.getByRole('table', { name: /Counts by value/ });
  await expect(counts.getByRole('row')).toHaveCount(4);
  for (const [label, count] of [
    ['"ALDER"', '5'],
    ['"BIRCH"', '4'],
    ['Null', '1'],
  ]) {
    const row = counts
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: label, exact: true }) });
    await expect(row.getByRole('cell', { name: count, exact: true })).toBeVisible();
    await expect(row.locator('meter')).toHaveAttribute('max', '10');
  }
  await expect(chart).toContainText('More records are available for this request.');
  await chart.getByText('Page and calculation details', { exact: true }).click();
  await expect(chart).toContainText(submitted.versionId);
  await expect(chart).toContainText(submitted.representationId);

  const underlying = page.waitForEvent('download');
  await chart.getByRole('button', { name: 'Download underlying page (JSON)', exact: true }).click();
  const exported = JSON.parse(await readFile((await (await underlying).path())!, 'utf8'));
  expect(exported.request).toEqual(submitted);
  expect(exported.result.rows).toEqual(read.rows);
  expect(exported.scope).toContain('Only the displayed page');
  expect(exported.result.rows[0].id.$number).toBe('9007199254740993');

  await page.getByText('Exact request, fields and reuse', { exact: true }).click();
  const readme = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download result README (text)', exact: true }).click();
  const instructions = await readFile((await (await readme).path())!, 'utf8');
  expect(instructions).toContain(snapshot.identity.catalogSha256);
  expect(instructions).toContain(submitted.versionId);
  expect(instructions).toContain(submitted.representationId);
  expect(instructions).toContain('Rows returned for this request only');
  expect(instructions).toContain('10 requested');
  expect(instructions).toContain('$number strings');
});

test('an otherwise successful response with a different resource is refused before preview and export', async ({
  page,
}) => {
  await page.route('**/api/read', async (route) => {
    const response = await route.fetch();
    const result: ReadResult = await response.json();
    expect(result.status).toBe('ok');
    expect(result.rows.length).toBeGreaterThan(0);
    result.binding.representationId = 'urn:example:wrong-resource';
    await route.fulfill({ response, json: result });
  });
  await page.goto('/?catalog=watershed&tab=Data');
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    'The response does not match this catalog, version and resource.',
  );
  await expect(page.locator('.data-table')).toHaveCount(0);
  await expect(page.locator('.prepared-counts')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Download this page (JSON) ↓', exact: true }),
  ).toHaveCount(0);
});
