import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

const awards = 'urn:ddk-viewer:fixture:grants:dataset:awards';
const v1 = 'urn:ddk-viewer:fixture:grants:awards:v1';

test.beforeEach(async ({ page }) => {
  await page.route(/\/api\/(read|query)(?:\?|$)/, (route) => {
    const request = route.request();
    if (
      new URL(request.url()).pathname === '/api/read' &&
      ['watershed', 'grants'].includes(request.postDataJSON()?.catalogId)
    )
      return route.continue();
    return route.abort('blockedbyclient');
  });
});

test('search explains the retained selection and puts supplied variant purpose on cards', async ({
  page,
}) => {
  const reads: string[] = [];
  page.on('request', (r) => {
    if (/\/api\/(read|query)$/.test(r.url())) reads.push(r.url());
  });
  await page.goto('/?catalog=spicy-regs&q=Public%20comments');
  const notice = page.getByText('The open dataset is outside these results', { exact: true });
  await expect(notice).toBeVisible();
  const results = page.getByRole('navigation', { name: 'Datasets' });
  const native = results.getByRole('button', {
    name: /Public comments — native output definition/,
  });
  const retained = results.getByRole('button', {
    name: /Public comments — retained source interpretation/,
  });
  await expect(native.locator('.dataset-result-summary')).toContainText(
    'Independent writer declaration',
  );
  await expect(retained.locator('.dataset-result-summary')).toContainText(
    'source/processing fields',
  );
  await expect(native).toContainText('One record: One posted public-comment record');
  await native.click();
  await expect(notice).toHaveCount(0);
  const selected = new URL(page.url()).searchParams.get('dataset');
  await page.getByRole('combobox', { name: 'Can I view records here?' }).selectOption('available');
  await expect(page.getByText('No datasets match these filters.', { exact: true })).toBeVisible();
  await expect(notice).toBeVisible();
  expect(new URL(page.url()).searchParams.get('dataset')).toBe(selected);
  await page.getByRole('button', { name: 'Clear search and filters', exact: true }).click();
  await expect(notice).toHaveCount(0);
  await expect(page.getByRole('searchbox')).toHaveValue('');
  expect(reads).toEqual([]);
});

test('version choices show scoped counts and both share routes carry explicit identities', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (value: string) => {
          Reflect.set(window, '__personaCopied', value);
        },
      },
    });
  });
  let reads = 0;
  page.on('request', (r) => {
    if (r.url().endsWith('/api/read')) reads++;
  });
  await page.goto('/?catalog=grants');
  const selector = page.getByRole('combobox', { name: 'Data version', exact: true });
  await expect(
    selector.getByRole('option', { name: /3 rows observed \(Authored sample rows only\)/ }),
  ).toHaveCount(1);
  await expect(
    selector.getByRole('option', { name: /2 rows observed \(Authored sample rows only\)/ }),
  ).toHaveCount(1);
  await selector.selectOption(v1);
  await page.getByRole('button', { name: 'Share & export' }).click();
  await expect(page.locator('.share-panel')).toContainText(
    'To share row filters and returned records',
  );
  await page
    .getByRole('button', { name: 'Copy link to this dataset and version', exact: true })
    .click();
  const copied = await page.evaluate(() => Reflect.get(window, '__personaCopied') as string);
  const downloading = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Download dataset reference (JSON)', exact: true })
    .click();
  const downloaded = await downloading;
  const reference = JSON.parse(await readFile((await downloaded.path())!, 'utf8'));
  expect(reference.link).toBe(copied);
  const query = new URL(reference.link).searchParams;
  expect(query.get('dataset')).toBe(awards);
  expect(query.get('version')).toBe(v1);
  expect(query.get('snapshot')).toBe(reference.catalogIdentity.catalogSha256);
  expect(query.get('release')).toBe('urn:ddk-viewer:fixture:grants:release:1');
  expect(reference).not.toHaveProperty('rows');
  expect(reads).toBe(0);
});

test('unavailable records provide working source and related-definition routes without reads', async ({
  page,
}) => {
  let reads = 0;
  page.on('request', (r) => {
    if (/\/api\/(read|query)$/.test(r.url())) reads++;
  });
  await page.goto('/?catalog=spicy-regs&dataset=current-comments&tab=Data');
  await expect(
    page.getByText('Records are not available in this portal', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Checks & sources', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Checks & sources', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  expect(new URL(page.url()).searchParams.get('dataset')).toBe('current-comments');
  await page.getByRole('tab', { name: 'View data', exact: true }).click();
  await page.getByRole('button', { name: 'Related data', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Related data', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  expect(reads).toBe(0);
});

test('mobile keyboard reaches the actual page summary without another record request', async ({
  page,
}) => {
  let reads = 0;
  page.on('request', (r) => {
    if (r.url().endsWith('/api/read')) reads++;
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?catalog=watershed&tab=Data');
  await expect(page.getByRole('button', { name: 'View page summary', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  const jump = page.getByRole('button', { name: 'View page summary', exact: true });
  await expect(jump).toBeVisible();
  await jump.focus();
  await jump.press('Enter');
  const summary = page.getByRole('region', { name: 'Page summary', exact: true });
  await expect(summary).toBeFocused();
  await expect(summary).toContainText('10 records returned on this page');
  await expect(summary).toContainText('Time range for these returned records: not supplied');
  await expect(summary.getByRole('table')).toContainText('"ALDER"');
  await expect(
    summary.getByRole('button', { name: 'Download underlying page (JSON)' }),
  ).toBeVisible();
  expect(reads).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
