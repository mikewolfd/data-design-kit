import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFile, writeFile } from 'node:fs/promises';

const versionId =
  'urn:ddk:file-version:737bacee2ec6b3ada9d212f8206e4905647dc155ff71433646a645054d6a8e50';
const resultSha = 'ff0efd8f35eb3b64e23a2f195cbfd2c9989173020b4681ae783bc0f2301ba4c6';
const sqlSha = 'ca01fbd8506181c0f7a4766c61712613a32f8882007b2a941247b13703183670';
const root = `/?catalog=commerce-native&dataset=daily-revenue&version=${encodeURIComponent(versionId)}`;
const byGrain = (rows: any[]) =>
  [...rows].sort((a, b) =>
    `${a.order_day}\0${a.region}`.localeCompare(`${b.order_day}\0${b.region}`),
  );
async function enabled(request: any) {
  const list = await (await request.get('/api/catalogs')).json();
  test.skip(
    !list.catalogs.some((c: any) => c.id === 'commerce-native'),
    'The local qualified owner flow is not enabled',
  );
  const response = await request.get('/api/catalogs/commerce-native');
  expect(response.ok()).toBe(true);
  return response.json();
}

test('real DocSpec read, recipe, exact export and retained quality evidence form one consumer journey', async ({
  page,
  request,
}) => {
  const snapshot = await enabled(request);
  expect(snapshot.audience).toBe('local');
  expect(snapshot.capabilities.readDatasetIds).toEqual([
    'urn:example:commerce:dataset:daily-revenue',
  ]);
  expect(snapshot.capabilities.queryRecipeIds).toEqual([
    'urn:example:commerce:recipe:checked-revenue',
  ]);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const reading = page.waitForResponse(
    (r) => r.url().endsWith('/api/read') && r.request().method() === 'POST',
  );
  await page.goto(`${root}&tab=Data`);
  const read = await (await reading).json();
  expect(read.status).toBe('ok');
  expect(read.binding.versionId).toBe(versionId);
  expect(read.readEvidence.kind).toBe('owner');
  expect(read.rowOrder).toBe('query-result');
  expect(read.release.id).toBe('urn:test:reference:release');
  expect(Object.hasOwn(read.release, 'selected')).toBe(false);
  expect(read.continuation).toBe('complete');
  expect(byGrain(read.rows).map((row: any) => row.amount_cents.$number)).toEqual([
    '1700',
    '500',
    '250',
  ]);
  await expect(page.locator('.data-table tbody tr')).toHaveCount(3);
  await expect(
    page.getByText('Complete read · native query result order', { exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: 'outputs/viewer-native-desktop.png' });
  const inspecting = page.waitForResponse((r) => r.url().endsWith('/api/evidence'));
  await page.getByRole('button', { name: 'Inspect native read receipt', exact: true }).click();
  const receipt = await (await inspecting).json();
  expect(receipt.record).toEqual(read.readEvidence.record);
  expect(receipt.document.inputs).toHaveLength(1);
  expect(receipt.document.inputs[0].sha256).toBe(resultSha);
  expect(receipt.document.operation.execution).toBe('succeeded');
  expect(receipt.document.operation.selection).toBe('not_requested');
  expect(receipt.document.operation.requestIdentity.value).toMatch(/^[a-f0-9]{64}$/);
  await expect(
    page.getByRole('status').filter({ hasText: 'Exact evidence verified.' }),
  ).toBeVisible();
  const pageDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export this page ↓', exact: true }).click();
  const pageFile = await (await pageDownload).path();
  const exportedPage = JSON.parse(await readFile(pageFile!, 'utf8'));
  expect(exportedPage.result.binding.versionId).toBe(versionId);
  expect(exportedPage.result.readEvidence.record).toEqual(read.readEvidence.record);
  await page.getByRole('tab', { name: 'Connections', exact: true }).click();
  const recipe = page
    .locator('.recipe')
    .filter({ has: page.getByRole('heading', { name: 'checked-revenue', exact: true }) });
  await recipe
    .getByRole('combobox', { name: 'Exact release', exact: true })
    .selectOption('urn:test:reference:release');
  const querying = page.waitForResponse((r) => r.url().endsWith('/api/query'));
  await recipe.getByRole('button', { name: 'Run query', exact: true }).click();
  const query = await (await querying).json();
  expect(query.status).toBe('ok');
  expect(query.bindings.daily_revenue.versionId).toBe(versionId);
  expect(query.execution.kind).toBe('owner');
  expect(query.execution.sqlSha256).toBe(sqlSha);
  expect(query.execution.inputs).toEqual(['daily_revenue']);
  expect(byGrain(query.rows)).toEqual(byGrain(read.rows));
  const queryDownload = page.waitForEvent('download');
  await recipe.getByRole('button', { name: 'Export query & result ↓', exact: true }).click();
  const queryFile = await (await queryDownload).path();
  const exportedQuery = JSON.parse(await readFile(queryFile!, 'utf8'));
  expect(exportedQuery.result.execution.record).toEqual(query.execution.record);
  expect(byGrain(exportedQuery.result.rows).map((row: any) => row.amount_cents.$number)).toEqual([
    '1700',
    '500',
    '250',
  ]);
  await page.getByRole('tab', { name: 'Evidence', exact: true }).click();
  await expect(page.getByText('13 recorded', { exact: true })).toBeVisible();
  await expect(page.getByText('Not established by this viewer', { exact: true })).toBeVisible();
  const qualityRead = page.waitForResponse((r) => r.url().endsWith('/api/evidence'));
  await page
    .getByRole('button', { name: 'Inspect retained quality evidence', exact: true })
    .click();
  const quality = await (await qualityRead).json();
  expect(quality.record.sha256).toBe(
    '06b1c688e93d6c5c19abe02f8dff26fa06c9e6ee0b4e4c3f6d47b709151d9bab',
  );
  expect(JSON.stringify(quality.document)).toContain(resultSha);
  await page.screenshot({ path: 'outputs/viewer-native-evidence.png' });
  expect(errors).toEqual([]);
  await writeFile(
    'work/commerce-browser-journey.json',
    JSON.stringify(
      {
        recordedAt: new Date().toISOString(),
        catalog: snapshot.identity,
        sourceVersionId: versionId,
        sourceResultSha256: resultSha,
        read,
        nativeReadReceipt: receipt,
        query,
        qualityEvidence: quality.record,
        exportedPageRetainsIdentity: true,
        exportedQueryRetainsIdentity: true,
      },
      null,
      2,
    ) + '\n',
  );
});

test('connected commerce preserves unsupported controls and all-view accessibility on desktop and mobile', async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const snapshot = await enabled(request);
  const customerVersion = snapshot.catalog.versions.find((v: any) => v.dataset === 'customers').id;
  await page.goto(
    `/?catalog=commerce-native&dataset=customers&version=${encodeURIComponent(customerVersion)}&tab=Data`,
  );
  await expect(
    page.getByText('Dataset outside the connected reader scope', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Apply filter', exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: 'Connections', exact: true }).click();
  await expect(
    page.getByText('Recipe outside the connected query scope', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run query', exact: true })).toHaveCount(0);
  await page.goto(`${root}&tab=Connections`);
  await expect(page.getByRole('button', { name: 'Run query', exact: true })).toHaveCount(1);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const tab of ['Overview', 'Data', 'Connections', 'Evidence', 'Activity', 'Compare']) {
      await page.getByRole('tab', { name: tab, exact: true }).click();
      if (tab === 'Data') await expect(page.locator('.data-table tbody tr')).toHaveCount(3);
      if (width === 390 && tab === 'Data')
        await page.screenshot({ path: 'outputs/viewer-native-mobile.png' });
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
    }
  }
});
