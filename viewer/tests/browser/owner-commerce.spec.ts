import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { parseExactData } from '../../src/domain/exact';
import { DEFAULT_DOCSPEC_SHA256 } from '../../src/server/commerce-native';

const versionId =
  'urn:ddk:file-version:667e1cdb71e36ebef8639a894100bcc50d3ab83bc4c02f18ab2e3f9a6f71eb24';
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

const runNative = process.env.DDK_VIEWER_RUN_NATIVE_ACCEPTANCE === '1';
const replayPath = runNative ? undefined : process.env.DDK_VIEWER_REPLAY_COMMERCE;
const noJourney =
  'The retained Commerce journey is evidence kept outside the repository; set DDK_VIEWER_REPLAY_COMMERCE to it (see README, Evidence archive).';
const captures = process.env.DDK_VIEWER_CAPTURE_DIR || 'work/browser-captures';
test(`${runNative ? 'real DocSpec execution' : 'retained DocSpec responses'}: read, query, exact export and quality evidence form one consumer journey`, async ({
  page,
  request,
}) => {
  test.skip(!runNative && !replayPath, noJourney);
  const snapshot = await enabled(request);
  await mkdir(captures, { recursive: true });
  if (replayPath) {
    const retained = JSON.parse(await readFile(replayPath, 'utf8'));
    expect(retained.catalog.catalogSha256).toBe(snapshot.identity.catalogSha256);
    const nativeReceipt = retained.nativeReadReceipt;
    expect(nativeReceipt.record).toEqual(retained.read.readEvidence.record);
    const receiptBytes = await readFile(fileURLToPath(nativeReceipt.record.uri));
    expect(createHash('sha256').update(receiptBytes).digest('hex')).toBe(
      nativeReceipt.record.sha256,
    );
    expect(parseExactData(receiptBytes.toString('utf8'))).toEqual(nativeReceipt.document);
    // Replay the verified historical receipt without granting the preview access to its archive.
    await page.route('**/api/evidence', async (route) => {
      const body = route.request().postDataJSON();
      if (body.record.uri !== nativeReceipt.record.uri) return route.continue();
      expect(body.record).toEqual(nativeReceipt.record);
      await route.fulfill({ json: nativeReceipt });
    });
    await page.route('**/api/read', async (route) => {
      const body = route.request().postDataJSON();
      expect(body.datasetId).toBe(retained.read.binding.datasetId);
      expect(body.versionId).toBe(retained.read.binding.versionId);
      expect(body.representationId).toBe(retained.read.binding.representationId);
      expect(body.releaseId).toBe(retained.read.binding.releaseId);
      await route.fulfill({ json: retained.read });
    });
    await page.route('**/api/query', async (route) => {
      const body = route.request().postDataJSON();
      expect(body.recipeId).toBe(retained.query.execution.recipeId);
      expect(body.bindings.daily_revenue.versionId).toBe(
        retained.query.bindings.daily_revenue.versionId,
      );
      await route.fulfill({ json: retained.query });
    });
  }
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
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  const read = await (await reading).json();
  expect(read.status).toBe('ok');
  expect(read.binding.versionId).toBe(versionId);
  expect(read.readEvidence.kind).toBe('owner');
  expect(read.rowOrder).toBe(runNative ? 'source-row' : 'query-result');
  expect(read.readEvidence.consumed).toEqual(read.binding);
  expect(read.release.id).toBe('urn:example:commerce:release:copy-refresh-20261106');
  expect(Object.hasOwn(read.release, 'selected')).toBe(false);
  expect(read.continuation).toBe('complete');
  expect(byGrain(read.rows).map((row: any) => row.amount_cents.$number)).toEqual([
    '1700',
    '500',
    '250',
  ]);
  await expect(page.locator('.data-table tbody tr')).toHaveCount(3);
  await expect(
    page.getByText(
      runNative
        ? '10 records per page · source-reported positions'
        : 'All records in this saved result returned · query result order',
      { exact: true },
    ),
  ).toBeVisible();
  await page.screenshot({ path: `${captures}/viewer-native-desktop.png` });
  let receipt;
  if (runNative) {
    // Direct Parquet reads supply response-bound details, not a job execution receipt.
    expect(read.readEvidence.record).toBeUndefined();
    expect(read.rowPositions).toEqual([0, 1, 2]);
    expect(read.readEvidence.details).toMatchObject({
      kind: 'owner-page',
      consumed: read.binding,
      offset: { $number: '0' },
      totalRows: { $number: '3' },
      rowPositions: [{ $number: '0' }, { $number: '1' }, { $number: '2' }],
      shardCount: { $number: '1' },
    });
    expect(read.readEvidence.details.shards).toHaveLength(1);
    expect(read.readEvidence.details.shards[0].sha256).toBe(resultSha);
    expect(read.readEvidence.details.shards[0].uri).toBe(
      snapshot.catalog.versions.find((version: any) => version.id === versionId).reference.value
        .location,
    );
    await page.getByText('Read details', { exact: true }).click();
    await expect(page.locator('.raw[open]').filter({ hasText: 'Read details' })).toContainText(
      resultSha,
    );
    await expect(
      page.getByRole('button', { name: 'Inspect native read receipt', exact: true }),
    ).toHaveCount(0);
  } else {
    const inspecting = page.waitForResponse((r) => r.url().endsWith('/api/evidence'));
    await page.getByRole('button', { name: 'Inspect native read receipt', exact: true }).click();
    receipt = await (await inspecting).json();
    expect(receipt.record).toEqual(read.readEvidence.record);
    expect(receipt.document.inputs).toHaveLength(1);
    expect(receipt.document.inputs[0].sha256).toBe(resultSha);
    expect(receipt.document.operation.execution).toBe('succeeded');
    expect(receipt.document.operation.selection).toBe('not_requested');
    expect(receipt.document.operation.requestIdentity.value).toMatch(/^[a-f0-9]{64}$/);
    await expect(
      page
        .getByRole('status')
        .filter({ hasText: 'Evidence file matches its recorded fingerprint.' }),
    ).toBeVisible();
  }
  const pageDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download this page (JSON) ↓', exact: true }).click();
  const pageFile = await (await pageDownload).path();
  const exportedPage = JSON.parse(await readFile(pageFile!, 'utf8'));
  expect(exportedPage.result.binding.versionId).toBe(versionId);
  expect(exportedPage.result.readEvidence).toEqual(read.readEvidence);
  await page.getByRole('tab', { name: 'Related data', exact: true }).click();
  const recipe = page
    .locator('.recipe')
    .filter({ has: page.getByRole('button', { name: 'Run query', exact: true }) });
  await recipe
    .getByRole('combobox', { name: 'Named release', exact: true })
    .selectOption('urn:example:commerce:release:copy-refresh-20261106');
  const querying = page.waitForResponse((r) => r.url().endsWith('/api/query'));
  await recipe.getByRole('button', { name: 'Run query', exact: true }).click();
  const query = await (await querying).json();
  expect(query.status).toBe('ok');
  expect(query.bindings.daily_revenue.versionId).toBe(versionId);
  expect(query.execution.kind).toBe('owner');
  expect(query.execution.sqlSha256).toBe(sqlSha);
  expect(query.execution.inputs).toEqual(['daily_revenue']);
  if (runNative) {
    expect(query.execution.engine).toMatchObject({
      id: 'docspec',
      binarySha256: DEFAULT_DOCSPEC_SHA256,
    });
    expect(query.execution.consumedBindings).toEqual(query.bindings);
  }
  expect(byGrain(query.rows)).toEqual(byGrain(read.rows));
  const queryDownload = page.waitForEvent('download');
  await recipe
    .getByRole('button', { name: 'Download query and results (JSON) ↓', exact: true })
    .click();
  const queryFile = await (await queryDownload).path();
  const exportedQuery = JSON.parse(await readFile(queryFile!, 'utf8'));
  expect(exportedQuery.result.execution).toEqual(query.execution);
  expect(byGrain(exportedQuery.result.rows).map((row: any) => row.amount_cents.$number)).toEqual([
    '1700',
    '500',
    '250',
  ]);
  await page.getByRole('tab', { name: 'Checks & sources', exact: true }).click();
  await expect(
    page.getByText('13 recorded; 13 passed; 0 failed; 0 unknown; 0 not run', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Acceptance by the publishing system: not established here.', { exact: true }),
  ).toBeVisible();
  const qualityRead = page.waitForResponse((r) => r.url().endsWith('/api/evidence'));
  await page.getByRole('button', { name: 'View saved check evidence', exact: true }).click();
  const quality = await (await qualityRead).json();
  expect(quality.record.sha256).toBe(
    'be9652b1676abef804ebef83d2ce5cca8ebefbccecab5c9a00a626233569aea7',
  );
  expect(JSON.stringify(quality.document)).toContain(resultSha);
  await page.screenshot({ path: `${captures}/viewer-native-evidence.png` });
  expect(errors).toEqual([]);
  if (!replayPath)
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
  test.skip(!runNative && !replayPath, noJourney);
  const snapshot = await enabled(request);
  const customerVersion = snapshot.catalog.versions.find((v: any) => v.dataset === 'customers').id;
  // Reuse the actual owner response proven by the consumer journey for visual checks.
  // Changing a viewport or revisiting a tab does not require another native read.
  const retained = JSON.parse(
    await readFile(replayPath || 'work/commerce-browser-journey.json', 'utf8'),
  );
  expect(retained.catalog.catalogSha256).toBe(snapshot.identity.catalogSha256);
  await page.route('**/api/read', async (route) => {
    expect(route.request().postDataJSON()).toMatchObject(retained.read.binding);
    await route.fulfill({ json: retained.read });
  });
  await page.goto(
    `/?catalog=commerce-native&dataset=customers&version=${encodeURIComponent(customerVersion)}&tab=Data`,
  );
  await expect(
    page.getByText('Records for this dataset are not connected', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Apply filter', exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: 'Related data', exact: true }).click();
  await expect(page.getByText('Example query — cannot run here', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run query', exact: true })).toHaveCount(0);
  await page.goto(`${root}&tab=Connections`);
  await expect(page.getByRole('button', { name: 'Run query', exact: true })).toHaveCount(1);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const tab of ['Overview', 'Data', 'Connections', 'Evidence', 'Activity', 'Compare']) {
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
      if (tab === 'Data') {
        // Returning from other views retains the accepted page; only the first visit reads it.
        if (width === 1440)
          await page.getByRole('button', { name: 'Open records', exact: true }).click();
        await expect(page.getByRole('tabpanel').locator('.data-table tbody tr')).toHaveCount(3);
      }
      if (width === 390 && tab === 'Data')
        await page.screenshot({ path: `${captures}/viewer-native-mobile.png` });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `${width}px ${tab} must fit the viewport`,
      ).toBe(true);
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
