import { createHash } from 'node:crypto';
import { test, expect, type Page, type APIRequestContext, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type { CatalogSnapshot } from '../../src/domain/types';

async function context(page: Page, request: APIRequestContext) {
  const snapshot: CatalogSnapshot = await (await request.get('/api/catalogs/watershed')).json();
  snapshot.capabilities.sql = true;
  await page.route('**/api/catalogs/watershed', (route) => route.fulfill({ json: snapshot }));
  const dataset = snapshot.catalog.datasets[0];
  const version = snapshot.catalog.versions.find((item) => item.dataset === dataset.alias)!;
  return { snapshot, dataset, version };
}

async function answer(route: Route, text = 'Retained answer') {
  const body = route.request().postDataJSON();
  await route.fulfill({
    json: {
      status: 'ok',
      transport: 'ddk-exact-json-v1',
      bindings: body.bindings,
      columns: ['text'],
      rows: [{ text }],
      returned: 1,
      execution: {
        kind: 'owner',
        recipeId: 'urn:ddk:ad-hoc-sql',
        sqlSha256: createHash('sha256').update(body.sql).digest('hex'),
        inputs: Object.keys(body.bindings),
        contextualRelationships: [],
      },
    },
  });
}

async function openTables(page: Page) {
  const details = page.locator('[aria-label="Query tables"] > details');
  if (!(await details.evaluate((element) => (element as HTMLDetailsElement).open)))
    await details.locator('> summary').click();
}

test('record page, page search and selection survive evidence and another dataset without a reread', async ({
  page,
}) => {
  let reads = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/api/read')) reads++;
  });
  await page.goto('/?catalog=watershed&tab=Data');
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await page.getByRole('button', { name: 'Next →', exact: true }).click();
  await page
    .getByRole('searchbox', { name: 'Search this page', exact: true })
    .fill('source literal');
  await page.getByRole('button', { name: 'Inspect record 13', exact: true }).click();
  await page.getByRole('tab', { name: 'Checks & sources', exact: true }).click();
  await page.goBack();
  await expect(page.getByRole('searchbox', { name: 'Search this page', exact: true })).toHaveValue(
    'source literal',
  );
  await expect(page.getByRole('region', { name: 'Record detail', exact: true })).toContainText(
    'source literal',
  );
  await page
    .getByRole('navigation', { name: 'Datasets', exact: true })
    .getByRole('button')
    .filter({ hasText: 'Synthetic station register' })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Synthetic station register', exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('searchbox', { name: 'Search this page', exact: true })).toHaveValue(
    'source literal',
  );
  await expect(page.getByRole('region', { name: 'Record detail', exact: true })).toContainText(
    'source literal',
  );
  await expect(page.getByRole('button', { name: 'Inspect record 13', exact: true })).toBeVisible();
  expect(reads).toBe(2);
});

test('SQL draft, selected exact input, answer and selected record survive tab and dataset round trips', async ({
  page,
  request,
}) => {
  const { version } = await context(page, request);
  let queries = 0;
  await page.route('**/api/sql', (route) => {
    queries++;
    return answer(route);
  });
  await page.goto(`/?catalog=watershed&tab=Query&version=${encodeURIComponent(version.id)}`);
  const draft = 'SELECT * FROM observations WHERE concentration > 0 ORDER BY id LIMIT 1';
  await page.getByRole('textbox', { name: 'SQL query', exact: true }).fill(draft);
  await expect(page.getByRole('button', { name: 'Run SQL query' })).toBeEnabled();
  await page.getByRole('button', { name: 'Run SQL query' }).click();
  await page.getByRole('button', { name: 'Inspect record 01', exact: true }).click();
  await page.getByRole('tab', { name: 'Checks & sources', exact: true }).click();
  await page.getByRole('tab', { name: 'Query lab', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'SQL query', exact: true })).toHaveValue(draft);
  await expect(page.getByRole('region', { name: 'Record detail', exact: true })).toContainText(
    'Retained answer',
  );
  await page
    .getByRole('navigation', { name: 'Datasets', exact: true })
    .getByRole('button')
    .filter({ hasText: 'Synthetic station register' })
    .click();
  await page.goBack();
  await expect(page.getByRole('textbox', { name: 'SQL query', exact: true })).toHaveValue(draft);
  await expect(page.getByRole('region', { name: 'Record detail', exact: true })).toContainText(
    'Retained answer',
  );
  await openTables(page);
  await expect(
    page.getByRole('combobox', { name: 'Data version for observations', exact: true }),
  ).toHaveValue(version.id);
  expect(queries).toBe(1);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test('table insertion preserves authored clauses and bindings; explicit replacement asks for input and can be undone', async ({
  page,
  request,
}) => {
  const { dataset, version } = await context(page, request);
  await page.goto(`/?catalog=watershed&tab=Query&version=${encodeURIComponent(version.id)}`);
  const editor = page.getByRole('textbox', { name: 'SQL query', exact: true });
  const draft = 'SELECT * FROM observations WHERE concentration > 0 ORDER BY id';
  await editor.fill(draft);
  await editor.press('End');
  await editor.press(' ');
  await openTables(page);
  const station = page.locator('.query-table').filter({
    has: page.getByRole('heading', { name: 'Synthetic station register', exact: true }),
  });
  await station.getByRole('button', { name: 'Insert table name', exact: true }).click();
  await expect(editor).toHaveValue(`${draft} "stations"`);
  await expect(
    page.getByRole('combobox', { name: `Data version for ${dataset.alias}`, exact: true }),
  ).toHaveValue(version.id);
  await station.getByRole('button', { name: 'Replace with new query', exact: true }).click();
  await expect(editor).toHaveValue('SELECT *\nFROM "stations"\nLIMIT 25');
  await expect(page.getByRole('button', { name: 'Run SQL query' })).toBeDisabled();
  await expect(
    page.getByRole('status').filter({ hasText: 'Choose a data version before running it' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Undo query edit', exact: true }).click();
  await expect(editor).toHaveValue(`${draft} "stations"`);
  await expect(
    page.getByRole('combobox', { name: `Data version for ${dataset.alias}`, exact: true }),
  ).toHaveValue(version.id);
});

test('leaving a pending SQL request keeps its draft, cancels waiting and ignores a late answer', async ({
  page,
  request,
}) => {
  const { version } = await context(page, request);
  let pending: Route | undefined;
  await page.route('**/api/sql', (route) => {
    pending = route;
  });
  await page.goto(`/?catalog=watershed&tab=Query&version=${encodeURIComponent(version.id)}`);
  await page
    .getByRole('textbox', { name: 'SQL query', exact: true })
    .fill('SELECT * FROM observations');
  await page.getByRole('button', { name: 'Run SQL query' }).click();
  await expect.poll(() => !!pending).toBe(true);
  await page.getByRole('tab', { name: 'Checks & sources', exact: true }).click();
  await answer(pending!, 'Late answer must not replace this task');
  await page.goBack();
  await expect(page.getByRole('textbox', { name: 'SQL query', exact: true })).toHaveValue(
    'SELECT * FROM observations',
  );
  await expect(
    page.getByText(/Stopped waiting for the query when you left this view/),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run SQL query' })).toBeEnabled();
  await expect(
    page.getByRole('cell', { name: 'Late answer must not replace this task' }),
  ).toHaveCount(0);
});

for (const viewport of [
  { width: 1440, height: 720 },
  { width: 390, height: 844 },
]) {
  test(`query completion is focused below the editor with bounded choices at ${viewport.width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize(viewport);
    const { snapshot, dataset, version } = await context(page, request);
    for (let i = 0; i < 3; i++) {
      const alias = `additional_table_${i}`;
      snapshot.catalog.datasets.push({
        ...dataset,
        id: `urn:test:${alias}`,
        alias,
        title: `Additional table ${i}`,
      });
      snapshot.catalog.versions.push({ ...version, id: `urn:test:${alias}:v1`, dataset: alias });
    }
    await page.route('**/api/sql', (route) => answer(route, 'A completed bounded answer'));
    await page.goto('/?catalog=watershed&tab=Query');
    const picker = page.locator('.query-table-list');
    await expect(picker).toBeVisible();
    expect(await page.locator('.query-table').count()).toBeGreaterThanOrEqual(5);
    expect((await picker.boundingBox())!.height).toBeLessThanOrEqual(
      viewport.width < 1100 ? 300 : 480,
    );
    await page
      .getByRole('combobox', { name: `Data version for ${dataset.alias}`, exact: true })
      .selectOption(version.id);
    await page
      .getByRole('textbox', { name: 'SQL query', exact: true })
      .fill('SELECT * FROM observations LIMIT 1');
    await page.getByRole('button', { name: 'Run SQL query' }).click();
    await expect(
      page.getByRole('cell', { name: 'A completed bounded answer', exact: true }),
    ).toBeVisible();
    await expect(page.locator('.query-outcome')).toBeFocused();
    expect(
      await page
        .locator('[aria-label="Query tables"] > details')
        .evaluate((element) => (element as HTMLDetailsElement).open),
    ).toBe(false);
    const editor = (await page.locator('.query-editor').boundingBox())!;
    const result = (await page.locator('.query-outcome').boundingBox())!;
    expect(result.y - (editor.y + editor.height)).toBeLessThan(40);
    expect(result.y).toBeGreaterThanOrEqual(0);
    expect(result.y).toBeLessThan(viewport.height);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
}

test('a different exact version gets a separate draft and a changed catalog invalidates retained tasks', async ({
  page,
  request,
}) => {
  const { snapshot, dataset, version } = await context(page, request);
  await page.goto(`/?catalog=watershed&tab=Query&version=${encodeURIComponent(version.id)}`);
  await page
    .getByLabel('SQL query', { exact: true })
    .fill('SELECT * FROM observations WHERE id = 1');
  const other = snapshot.catalog.versions.find(
    (item) => item.dataset === dataset.alias && item.id !== version.id,
  )!;
  await page.getByRole('combobox', { name: 'Data version', exact: true }).selectOption(other.id);
  await expect(page.getByRole('textbox', { name: 'SQL query', exact: true })).toHaveValue('');
  await page.goBack();
  await expect(page.getByRole('textbox', { name: 'SQL query', exact: true })).toHaveValue(
    'SELECT * FROM observations WHERE id = 1',
  );
  snapshot.identity = { ...snapshot.identity, catalogSha256: '1'.repeat(64) };
  await page.getByRole('combobox', { name: 'Catalog', exact: true }).selectOption('grants');
  await page.getByRole('combobox', { name: 'Catalog', exact: true }).selectOption('watershed');
  await page.getByRole('tab', { name: 'Query lab', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'SQL query', exact: true })).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Run SQL query' })).toBeDisabled();
});

test('retained task views have a fixed budget and explain when an older view must reopen', async ({
  page,
  request,
}) => {
  const { snapshot, dataset, version } = await context(page, request);
  for (let i = 0; i < 3; i++)
    snapshot.catalog.versions.push({ ...version, id: `urn:test:extra-version:${i}` });
  const versions = snapshot.catalog.versions.filter((item) => item.dataset === dataset.alias);
  expect(versions).toHaveLength(7);
  await page.goto(`/?catalog=watershed&tab=Query&version=${encodeURIComponent(version.id)}`);
  await page
    .getByRole('textbox', { name: 'SQL query', exact: true })
    .fill('SELECT * FROM observations');
  for (const item of versions.filter((item) => item.id !== version.id))
    await page.getByRole('combobox', { name: 'Data version', exact: true }).selectOption(item.id);
  await expect(page.locator('.query-lab')).toHaveCount(6);
  await expect(
    page.getByRole('status').filter({ hasText: 'six most recent data and query views' }),
  ).toBeVisible();
  await page.getByRole('combobox', { name: 'Data version', exact: true }).selectOption(version.id);
  await expect(page.getByRole('textbox', { name: 'SQL query', exact: true })).toHaveValue('');
  await expect(page.locator('.query-lab')).toHaveCount(6);
});

test('an unrelated resource in the URL never becomes a query binding', async ({
  page,
  request,
}) => {
  const { version } = await context(page, request);
  await page.goto(
    `/?catalog=watershed&tab=Query&version=${encodeURIComponent(version.id)}&resource=urn:unrelated:resource`,
  );
  await page
    .getByRole('textbox', { name: 'SQL query', exact: true })
    .fill('SELECT * FROM observations');
  await expect(
    page.getByRole('combobox', { name: 'Resource for observations', exact: true }),
  ).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Run SQL query' })).toBeDisabled();
  await expect(
    page.getByText('Choose a resource for every included version.', { exact: false }),
  ).toBeVisible();
});
