import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const root = '/?catalog=watershed';
async function open(page: any, tab = 'Overview') {
  await page.goto(`${root}&tab=${tab}`);
  await expect(
    page.getByRole('heading', { name: 'Watershed observations', exact: true }),
  ).toBeVisible();
}
async function snapshot(request: any, id = 'watershed') {
  return (await request.get(`/api/catalogs/${id}`)).json();
}

test('discovery opens no rows; exact numbers, missing, null and empty survive pages and export', async ({
  page,
  request,
}) => {
  const rows: string[] = [];
  page.on('request', (r) => {
    if (r.url().endsWith('/api/read')) rows.push(r.url());
  });
  await open(page);
  expect(rows).toHaveLength(0);
  await page.getByRole('tab', { name: 'View data', exact: true }).click();
  const openRecords = page.getByRole('button', { name: 'Open records', exact: true });
  await expect(openRecords).toBeVisible();
  expect(rows).toHaveLength(0);
  await openRecords.click();
  await expect(page.getByRole('cell', { name: '9007199254740993', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: '0.200000000000000001', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'missing', exact: true }).first()).toBeVisible();
  await expect(page.getByRole('cell', { name: 'null', exact: true }).first()).toBeVisible();
  await expect(page.getByRole('cell', { name: 'empty text', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Next →', exact: true }).click();
  await expect(page.getByRole('cell', { name: '9007199254741021', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'source literal', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Inspect record 13', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Record detail' })).toContainText('$number');
  await expect(page.getByRole('region', { name: 'Record detail' })).toContainText('source literal');
  await page.getByRole('button', { name: 'Close detail', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Inspect record 13', exact: true })).toBeFocused();
  await page.getByText('Visible fields (').click();
  await page.getByRole('checkbox', { name: 'concentration', exact: true }).uncheck();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download this page (JSON) ↓', exact: true }).click();
  const file = await (await download).path();
  const fs = await import('node:fs/promises');
  const saved = JSON.parse(await fs.readFile(file!, 'utf8'));
  expect(saved.display.columns).not.toContain('concentration');
  expect(saved.scope).toContain('displayed page');
  expect(saved.result.rows).toHaveLength(4);
  expect(saved.request.catalogSha256).toBe((await snapshot(request)).identity.catalogSha256);
  expect(JSON.stringify(saved)).toContain('9007199254741021');
  await page.getByRole('button', { name: '← Previous', exact: true }).click();
  await expect(page.getByRole('cell', { name: '9007199254740993', exact: true })).toBeVisible();
});

test('exact decimal filtering and error retry keep request context', async ({ page }) => {
  await open(page, 'Data');
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await expect(page.getByRole('cell', { name: '9007199254740993', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Field', exact: true }).selectOption('concentration');
  await page.getByRole('combobox', { name: 'Value type', exact: true }).selectOption('number');
  await page.getByLabel('Equals', { exact: true }).fill('0.200000000000000001');
  let failed = false;
  await page.route('**/api/read', (route) => {
    if (!failed) {
      failed = true;
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: { message: 'Planted temporary reader failure' } }),
      });
    }
    return route.continue();
  });
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Planted temporary reader failure');
  await expect(page.getByLabel('Equals', { exact: true })).toHaveValue('0.200000000000000001');
  await page.getByRole('button', { name: 'Retry read', exact: true }).click();
  await expect(page.getByRole('cell', { name: '9007199254740993', exact: true })).toBeVisible();
  await expect(page.locator('.data-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.result-bar [role="status"]')).toHaveText(
    '1 record on this page · 1 matching record',
  );
  await page.getByLabel('Equals', { exact: true }).fill('999');
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  await expect(page.getByText('No records match this filter', { exact: true })).toBeVisible();
});

test('supported recipe consumes only real inputs and exports exact parameters', async ({
  page,
  request,
}) => {
  const data = await snapshot(request);
  await open(page, 'Connections');
  await page
    .getByRole('combobox', { name: 'Named release', exact: true })
    .selectOption(
      data.catalog.releases.find((r: any) =>
        r.members.some((v: string) => v.endsWith('observations:v2')),
      ).id,
    );
  await page.locator('.recipe-form input').fill('2.000000000000000000');
  await page.getByRole('button', { name: 'Run query', exact: true }).click();
  await expect(page.locator('.recipe .data-table tbody tr')).toHaveCount(3);
  await expect(page.getByRole('cell', { name: '9007199254740999', exact: true })).toBeVisible();
  await page.getByText('Technical execution record', { exact: true }).click();
  await expect(page.locator('.recipe')).toContainText('"inputs": [\n    "records"');
  await page.getByText('View SQL', { exact: true }).click();
  await expect(page.locator('.sql-preview pre')).toContainText('SELECT');
});

test('historical relationship navigation keeps target version and release', async ({
  page,
  request,
}) => {
  const data = await snapshot(request);
  const old = data.catalog.versions.find((v: any) => v.id.endsWith('observations:v1'));
  await page.goto(`${root}&tab=Connections&version=${encodeURIComponent(old.id)}`);
  await page
    .getByRole('button', {
      name: 'Synthetic station register · version in the same release ↗',
      exact: true,
    })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Synthetic station register', exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get('version')).toMatch(/stations:v1$/);
  expect(new URL(page.url()).searchParams.get('release')).toBeTruthy();
  await page.getByRole('tab', { name: 'View data', exact: true }).click();
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await expect(page.locator('.data-table')).toContainText('historical');
});

test('withheld and unresolved versions remain refused or unknown', async ({ page, request }) => {
  const data = await snapshot(request);
  await open(page, 'Data');
  await page
    .getByRole('combobox', { name: 'Data version', exact: true })
    .selectOption(data.catalog.versions.find((v: any) => v.id.endsWith(':withheld')).id);
  await expect(
    page.getByText('The publisher has withheld the exact reference needed to open these records.', {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole('combobox', { name: 'Data version', exact: true })
    .selectOption(data.catalog.versions.find((v: any) => v.id.endsWith(':unresolved')).id);
  await expect(
    page.getByText('Record availability is unknown. No read request has been made.', {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole('tab', { name: 'Checks & sources', exact: true }).click();
  await expect(page.getByText(/required checks? (is|are) unresolved or failed/)).toBeVisible();
  await expect(
    page.getByText('No checks are recorded for this data version', { exact: true }),
  ).toBeVisible();
});

test('comparison uses genuine pinned DDK impact and distinguishes reuse', async ({ page }) => {
  await open(page, 'Compare');
  await expect(
    page.getByRole('heading', { name: 'Follow-up work identified by the report', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('metadata regeneration', { exact: false }).first()).toBeVisible();
  await expect(
    page.getByText('The report does not carry out these updates', { exact: true }),
  ).toBeVisible();
  await page.getByText('Computation and qualification reuse evidence', { exact: true }).click();
  await expect(page.getByRole('tabpanel', { name: 'Compare versions' })).toContainText(
    'Both snapshots need runtime-issued identities',
  );
});

test('same-catalog history digest mismatch cannot display a different snapshot', async ({
  page,
}) => {
  await open(page);
  await page.evaluate(() => {
    const u = new URL(location.href);
    u.searchParams.set('snapshot', 'f'.repeat(64));
    history.pushState({}, '', u);
    dispatchEvent(new PopStateEvent('popstate'));
  });
  await expect(page.getByRole('alert')).toContainText('different catalog copy');
  await expect(
    page.getByRole('heading', { name: 'Watershed observations', exact: true }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Open the catalog available here', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Watershed observations', exact: true }),
  ).toBeVisible();
});

test('late catalog response cannot overwrite the current catalog', async ({ page }) => {
  await page.route('**/api/catalogs/watershed', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600));
    try {
      await route.continue();
    } catch {}
  });
  await page.goto(root);
  await page.getByRole('combobox', { name: 'Catalog', exact: true }).selectOption('grants');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Public-service grants');
  await page.waitForTimeout(700);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Public-service grants');
});

test('keyboard tab activation, no console errors and desktop accessibility', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await open(page);
  await page.getByRole('tab', { name: 'Overview', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'View data', exact: true })).toBeFocused();
  await expect(page.getByRole('tabpanel', { name: 'Overview' })).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('tabpanel', { name: 'View data' })).toBeVisible();
  await page.getByRole('button', { name: 'Open records', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('cell', { name: '9007199254740993', exact: true })).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  expect(errors).toEqual([]);
});

for (const width of [390, 320])
  test(`mobile ${width}px supports tabs, overflow and reduced motion`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await open(page, 'Data');
    await page.getByRole('button', { name: 'Open records', exact: true }).click();
    await expect(page.getByRole('cell', { name: '9007199254740993', exact: true })).toBeVisible();
    for (const control of [
      page.getByRole('combobox', { name: 'Catalog', exact: true }),
      page.getByRole('searchbox', { name: 'Search this catalog', exact: true }),
    ]) {
      const bounds = await control.boundingBox();
      expect(bounds!.width, 'Discovery controls need room for readable text').toBeGreaterThan(
        width * 0.6,
      );
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
          .analyze()
      ).violations,
    ).toEqual([]);
    await page.getByRole('button', { name: 'Inspect record 01', exact: true }).click();
    await expect(page.getByRole('region', { name: 'Record detail' })).toBeVisible();
  });

test('real application catalogs preserve discovery-only scope', async ({ page, request }) => {
  const list = await (await request.get('/api/catalogs')).json();
  for (const id of ['spicy-regs', 'congress']) {
    test.skip(
      !list.catalogs.some((c: any) => c.id === id),
      'Application fixture not enabled for this preview',
    );
    await page.goto(`/?catalog=${id}&tab=Data`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    const data = await snapshot(request, id);
    expect(data.mode).toBe('application');
    expect(data.capabilities.read).toBe(false);
    expect(data.capabilities.query).toBe(false);
    if (id === 'spicy-regs') {
      expect(data.catalog.versions).toHaveLength(0);
      await expect(
        page.getByText('Records are not available in this portal', { exact: true }),
      ).toBeVisible();
    } else expect(data.catalog.datasets.length).toBeGreaterThanOrEqual(23);
  }
});

test('incoming same-release links return to historical source; skip link and all views are accessible', async ({
  page,
  request,
}) => {
  const data = await snapshot(request);
  const old = data.catalog.versions.find((v: any) => v.id.endsWith('observations:v1'));
  await page.goto(`${root}&tab=Connections&version=${encodeURIComponent(old.id)}`);
  await page
    .getByRole('button', {
      name: 'Synthetic station register · version in the same release ↗',
      exact: true,
    })
    .click();
  await page.getByRole('tab', { name: 'Related data', exact: true }).click();
  await page
    .getByRole('button', {
      name: 'Watershed observations · version in the same release ↗',
      exact: true,
    })
    .click();
  expect(new URL(page.url()).searchParams.get('version')).toBe(old.id);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const tab of ['Overview', 'Connections', 'Evidence', 'Activity', 'Compare']) {
    await page
      .getByRole('tab', {
        name:
          (
            {
              Data: 'View data',
              Connections: 'Related data',
              Evidence: 'Checks & sources',
              Activity: 'History',
              Compare: 'Compare versions',
            } as Record<string, string>
          )[tab] || tab,
        exact: true,
      })
      .click();
    if (tab === 'Compare')
      await expect(
        page.getByRole('heading', { name: 'Follow-up work identified by the report', exact: true }),
      ).toBeVisible();
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
          .analyze()
      ).violations,
      `${tab} accessibility`,
    ).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      `${tab} overflow`,
    ).toBe(true);
  }
  await open(page);
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to dataset', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('main')).toBeFocused();
});

test('nested scalar-list paths and source discovery retain their meaning', async ({ page }) => {
  await open(page);
  await page.getByText('Nested fields in readings', { exact: true }).click();
  await page.getByText('Nested fields in flags', { exact: true }).click();
  await page
    .getByLabel('Technical field details for ["readings"][each]["flags"][each]', { exact: true })
    .click();
  await expect(page.getByText('["readings"][each]["flags"][each]', { exact: true })).toBeVisible();
  await expect(
    page.locator('.field-meta').filter({ hasText: '["readings"][each]["flags"][each]' }),
  ).toHaveCount(1);
  await expect(
    page.locator('.field-meta').filter({ hasText: '["readings"][each]["flags"][each]["flag"]' }),
  ).toHaveCount(0);
  await page
    .getByRole('searchbox', { name: 'Search this catalog', exact: true })
    .fill('no-such-dataset');
  await expect(page.getByText('No datasets match these filters.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Datasets' }).getByRole('button')).toHaveCount(
    2,
  );
  await expect(page.getByRole('combobox', { name: 'Source capture', exact: true })).toBeVisible();
});

test('explicit-version recipe binding runs without treating context as an input', async ({
  page,
  request,
}) => {
  const data = await snapshot(request);
  await open(page, 'Connections');
  await page
    .getByRole('combobox', { name: 'Data versions to use', exact: true })
    .selectOption('versions');
  await page
    .getByRole('combobox', { name: 'Version for records', exact: true })
    .selectOption(data.catalog.versions.find((v: any) => v.id.endsWith('observations:v2')).id);
  await page.locator('.recipe-form input').fill('2');
  await page.getByRole('button', { name: 'Run query', exact: true }).click();
  await expect(page.locator('.recipe .data-table tbody tr')).toHaveCount(3);
});

test('unknown pagination stays explicit and long nested values keep accessible structure', async ({
  page,
}) => {
  await page.route('**/api/read', async (route) => {
    const response = await route.fetch();
    const value = await response.json();
    value.continuation = 'unknown';
    delete value.total;
    delete value.hasMore;
    delete value.nextCursor;
    value.rows[0].readings = Array.from({ length: 51 }, (_, i) => ({ label: `occurrence ${i}` }));
    await route.fulfill({ response, json: value });
  });
  await open(page, 'Data');
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await expect(page.getByText('More records: unknown', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Inspect record 01', exact: true }).click();
  await expect(
    page.getByText('First 50 items displayed. Downloading the result retains the complete value.', {
      exact: true,
    }),
  ).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
});
