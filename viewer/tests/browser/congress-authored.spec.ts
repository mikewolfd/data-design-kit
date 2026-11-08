import { test, expect } from '@playwright/test';
import { mkdir, readFile } from 'node:fs/promises';

const catalogId = 'congress-authored';
const nativeRelease = '0ed378bde1c3dfbf218d1b3be9b067551dbc522f3b00bc854fe8b9f9a664b311';
const captureDirectory = process.env.DDK_VIEWER_CAPTURE_DIR || 'work/browser-captures';

// These checks use actual retained Congress inputs through /api/read. No read or
// query response is intercepted and no native producer is invoked.
async function congress(request: any) {
  const response = await request.get(`/api/catalogs/${catalogId}`);
  expect(response.ok()).toBe(true);
  const snapshot = await response.json();
  expect(snapshot.audience).toBe('local');
  expect(snapshot.exampleData).toBe('authored');
  expect(snapshot.catalog.datasets).toHaveLength(23);
  expect(snapshot.catalog.versions).toHaveLength(17);
  expect(snapshot.catalog.releases).toEqual([]);
  expect(snapshot.catalog.selections).toEqual([]);
  expect(snapshot.capabilities.query).toBe(false);
  return snapshot;
}
function binding(snapshot: any, alias: string) {
  const dataset = snapshot.catalog.datasets.find((row: any) => row.alias === alias);
  const versions = snapshot.catalog.versions.filter((row: any) => row.dataset === alias);
  expect(versions).toHaveLength(1);
  const representations = snapshot.catalog.representations.filter(
    (row: any) => row.version === versions[0].id,
  );
  expect(representations).toHaveLength(1);
  return { dataset, version: versions[0], representation: representations[0] };
}
function route(alias: string, version?: string) {
  const params = new URLSearchParams({ catalog: catalogId, dataset: alias, tab: 'Data' });
  if (version) params.set('version', version);
  return `/?${params}`;
}

test('Congress requires an explicit version and keeps native provenance outside standard release selection', async ({
  page,
  request,
}) => {
  const snapshot = await congress(request);
  const { version } = binding(snapshot, 'list');
  let reads = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/api/read')) reads++;
  });
  await page.route('**/api/read', (request) => request.abort());
  await page.goto(route('list'));
  await expect(page.getByRole('combobox', { name: 'Data version', exact: true })).toHaveValue('');
  await expect(
    page.getByText('Choose a data version to view records', { exact: true }),
  ).toBeVisible();
  expect(reads).toBe(0);
  await page.getByRole('button', { name: /Share & export/ }).click();
  const download = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Download dataset reference (JSON)', exact: true })
    .click();
  const reference = JSON.parse(await readFile((await (await download).path())!, 'utf8'));
  expect(reference.version).toBeNull();
  expect(reference.release).toBeNull();
  expect(reference.selection).toEqual([]);
  expect(version.id).toMatch(/^urn:ddk:file-version:/);
  await page.getByRole('tab', { name: 'Related data', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run query', exact: true })).toHaveCount(0);
  expect(reads).toBe(0);
});

test('Congress actual list read preserves seven rows, exact identities and original read evidence', async ({
  page,
  request,
}) => {
  const snapshot = await congress(request);
  expect(snapshot.capabilities.read).toBe(true);
  const { dataset, version, representation } = binding(snapshot, 'list');
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => {
    (window as any).__copiedIds = [];
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (value: string) => {
          (window as any).__copiedIds.push(value);
        },
      },
    });
  });
  const reading = page.waitForResponse(
    (response) => response.url().endsWith('/api/read') && response.request().method() === 'POST',
  );
  await page.goto(route('list', version.id));
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  const response = await reading;
  expect(response.ok()).toBe(true);
  const read = await response.json();
  expect(read.status).toBe('ok');
  expect(read.binding).toMatchObject({
    datasetId: dataset.id,
    versionId: version.id,
    representationId: representation.id,
  });
  expect(read.binding.releaseId).toBeUndefined();
  expect(read.release).toBeUndefined();
  expect(read.returned).toBe(7);
  expect(read.rows).toHaveLength(7);
  expect(read.rowPositions).toEqual([0, 1, 2, 3, 4, 5, 6]);
  expect(read.readEvidence.kind).toBe('owner');
  expect(read.readEvidence.consumed).toEqual(read.binding);
  expect(read.readEvidence.details.releaseId).toBe(nativeRelease);
  expect(read.readEvidence.details.file.name).toBe('list.parquet');
  expect(read.readEvidence.details.file.sha256).toBe(version.reference.value.sha256);
  expect(read.readEvidence.details.schema.length).toBeGreaterThan(0);
  expect(read.readEvidence.details.rowPositions).toHaveLength(7);
  expect(read.readEvidence.details.ownerModule.configuration.sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(read.readEvidence.details.ownerModule.entry).toBeTruthy();
  await expect(page.locator('.data-table tbody tr')).toHaveCount(7);
  await expect(page.getByText('Saved example data', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Apply filter', exact: true })).toHaveCount(0);
  await page.getByText('Data version identifiers', { exact: true }).click();
  await expect(page.locator('.version-context')).toContainText(version.id);
  await page
    .locator('.version-context')
    .getByRole('button', { name: 'Copy version identifier', exact: true })
    .click();
  await page.getByText('File, table or service identifiers', { exact: true }).click();
  await expect(page.locator('.data-toolbar')).toContainText(representation.id);
  await page
    .locator('.data-toolbar')
    .getByRole('button', { name: 'Copy identifier', exact: true })
    .click();
  expect(await page.evaluate(() => (window as any).__copiedIds)).toEqual([
    version.id,
    representation.id,
  ]);
  await page.getByText('Read details', { exact: true }).click();
  await expect(page.locator('.raw[open]').filter({ hasText: 'Read details' })).toContainText(
    nativeRelease,
  );
  await page.getByRole('button', { name: /Share & export/ }).click();
  const download = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Download dataset reference (JSON)', exact: true })
    .click();
  const reference = JSON.parse(await readFile((await (await download).path())!, 'utf8'));
  expect(reference.version.id).toBe(version.id);
  expect(reference.version.reference).toEqual(version.reference);
  expect(reference.release).toBeNull();
  expect(reference.selection).toEqual([]);
  await page.getByRole('button', { name: /Share & export/ }).click();
  await page.getByText('Data version identifiers', { exact: true }).click();
  await page.getByText('File, table or service identifiers', { exact: true }).click();
  await page.getByText('Read details', { exact: true }).click();
  await page.getByRole('heading', { name: 'Searchable documents', exact: true }).click();
  await page.mouse.move(1400, 80);
  await mkdir(captureDirectory, { recursive: true });
  await page.screenshot({ path: `${captureDirectory}/congress-data.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test('Congress detail read keeps nested occurrences in the real retained rows and page download', async ({
  page,
  request,
}) => {
  const snapshot = await congress(request);
  const { version } = binding(snapshot, 'detail');
  const reading = page.waitForResponse(
    (response) => response.url().endsWith('/api/read') && response.request().method() === 'POST',
  );
  await page.goto(route('detail', version.id));
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  const response = await reading;
  expect(response.ok()).toBe(true);
  const read = await response.json();
  expect(read.status).toBe('ok');
  expect(read.rows).toHaveLength(7);
  const nested = read.rows
    .flatMap((row: any) => Object.values(row))
    .filter((value: any) => value && typeof value === 'object' && !Object.hasOwn(value, '$number'));
  expect(nested.length).toBeGreaterThan(0);
  expect(nested.some((value: any) => Array.isArray(value))).toBe(true);
  await expect(page.locator('.data-table tbody tr')).toHaveCount(7);
  await expect(page.locator('.structured-value').first()).toBeVisible();
  await page.getByRole('button', { name: 'Inspect record 01', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Record detail', exact: true })).toBeVisible();
  await expect(page.locator('.record-inspector .nested-values').first()).toBeVisible();
  await expect(page.locator('.record-inspector')).toContainText('Occurrence [0]');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download this page (JSON) ↓', exact: true }).click();
  const saved = JSON.parse(await readFile((await (await download).path())!, 'utf8'));
  expect(saved.result.rows).toEqual(read.rows);
  expect(saved.result.binding.versionId).toBe(version.id);
  expect(saved.result.readEvidence).toEqual(read.readEvidence);
});
