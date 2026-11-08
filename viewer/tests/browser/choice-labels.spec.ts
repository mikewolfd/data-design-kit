import { test, expect, type Route } from '@playwright/test';
import type { ReadRequest, ReadResult } from '../../src/domain/types';

function emptyRead(route: Route): ReadResult {
  const { datasetId, versionId, representationId, releaseId } = route
    .request()
    .postDataJSON() as ReadRequest;
  return {
    status: 'ok',
    binding: { datasetId, versionId, representationId, releaseId },
    rows: [],
    columns: [],
    returned: 0,
    total: 0,
    continuation: 'complete',
    transport: 'ddk-exact-json-v1',
  };
}

// These tests use synthetic catalog metadata and intercept every read. They do
// not open an application reader or call the native Commerce implementation.
test('descriptive choices retain exact version and representation request bindings', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  const version = snapshot.catalog.versions.find((row: any) => row.id.endsWith('observations:v1'));
  const representation = snapshot.catalog.representations.find(
    (row: any) => row.version === version.id,
  );
  const reads: any[] = [];
  await page.route('**/api/read', async (route) => {
    const binding = route.request().postDataJSON();
    reads.push(binding);
    await route.fulfill({ json: emptyRead(route) });
  });
  await page.goto('/?catalog=watershed&tab=Data');
  const selector = page.getByRole('combobox', { name: 'Data version', exact: true });
  await expect(selector).toContainText(
    'Watershed observations · Version label not supplied · JSON file',
  );
  await selector.selectOption(version.id);
  const openRecords = page.getByRole('button', { name: 'Open records', exact: true });
  await expect(openRecords).toBeVisible();
  expect(reads).toHaveLength(0);
  await openRecords.click();
  await expect.poll(() => reads.at(-1)?.versionId).toBe(version.id);
  await expect(page.getByText('This request returned no records', { exact: true })).toBeVisible();
  expect(reads.at(-1)?.representationId).toBe(representation.id);
  await expect(
    page.getByRole('combobox', { name: 'File, table or service', exact: true }),
  ).toHaveCount(0);
  await expect(page.locator('.data-toolbar')).toContainText(
    'Watershed observations · JSON file · Available',
  );
  await page.getByText('Data version identifiers', { exact: true }).click();
  await expect(page.locator('.context-bar')).toContainText(version.id);
  await page.getByText('File, table or service identifiers', { exact: true }).click();
  await expect(page.locator('.data-toolbar')).toContainText(representation.id);
});

test('one unselected version still requires a deliberate choice and invalid routes stay invalid', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  const version = snapshot.catalog.versions.find((row: any) => row.id.endsWith('observations:v1'));
  snapshot.catalog.versions = [version];
  delete snapshot.catalog.currentSelection;
  await page.route('**/api/catalogs/watershed', (route) => route.fulfill({ json: snapshot }));
  let reads = 0;
  await page.route('**/api/read', (route) => {
    reads++;
    return route.fulfill({ json: emptyRead(route) });
  });
  await page.goto('/?catalog=watershed&tab=Data');
  const selector = page.getByRole('combobox', { name: 'Data version', exact: true });
  await expect(selector).toHaveValue('');
  await expect(
    page.getByText('Choose a data version to view records', { exact: true }),
  ).toBeVisible();
  expect(reads).toBe(0);
  await page.goto('/?catalog=watershed&tab=Data&version=not-a-listed-version');
  await expect(page.getByText('The linked version is unavailable', { exact: true })).toBeVisible();
  await expect(selector).toHaveValue('');
  expect(reads).toBe(0);
  expect(new URL(page.url()).searchParams.get('version')).toBe('not-a-listed-version');
  await selector.selectOption(version.id);
  const openRecords = page.getByRole('button', { name: 'Open records', exact: true });
  await expect(openRecords).toBeVisible();
  expect(reads).toBe(0);
  await openRecords.click();
  await expect.poll(() => reads).toBe(1);
  await expect(selector).toHaveCount(0);
  await expect(page.locator('.context-bar')).toContainText('Version label not supplied');
});

test('colliding descriptions use list numbers while representation selection stays explicit', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  const version = snapshot.catalog.versions.find((row: any) => row.id.endsWith('observations:v1'));
  const file = snapshot.catalog.representations.find((row: any) => row.version === version.id);
  const alternative = { ...file, id: 'urn:example:opaque-alternative' };
  snapshot.catalog.representations.push(alternative);
  await page.route('**/api/catalogs/watershed', (route) => route.fulfill({ json: snapshot }));
  const reads: any[] = [];
  await page.route('**/api/read', (route) => {
    reads.push(route.request().postDataJSON());
    return route.fulfill({ json: emptyRead(route) });
  });
  await page.goto(`/?catalog=watershed&tab=Data&version=${encodeURIComponent(version.id)}`);
  const selector = page.getByRole('combobox', { name: 'File, table or service', exact: true });
  await expect(selector).toHaveValue('');
  await expect(selector).toContainText('Watershed observations · JSON file · Available · Choice 2');
  expect(reads).toHaveLength(0);
  await selector.selectOption(alternative.id);
  const openRecords = page.getByRole('button', { name: 'Open records', exact: true });
  await expect(openRecords).toBeVisible();
  expect(reads).toHaveLength(0);
  await openRecords.click();
  await expect.poll(() => reads.at(-1)?.representationId).toBe(alternative.id);
  await expect(page.getByText('This request returned no records', { exact: true })).toBeVisible();
  await page.getByText('File, table or service identifiers', { exact: true }).click();
  await expect(page.locator('.data-toolbar')).toContainText('do not indicate age or priority');
  expect(reads).toHaveLength(1);

  await selector.selectOption(file.id);
  await expect(openRecords).toBeVisible();
  await expect(page.getByText('This request returned no records', { exact: true })).toHaveCount(0);
  expect(reads).toHaveLength(1);
  await openRecords.click();
  await expect.poll(() => reads.at(-1)?.representationId).toBe(file.id);
  await expect(page.getByText('This request returned no records', { exact: true })).toBeVisible();
  expect(reads).toHaveLength(2);
});

for (const denied of [false, true]) {
  test(`exact choice identifiers support clipboard ${denied ? 'denial' : 'success'} without native reads`, async ({
    page,
    request,
  }) => {
    const snapshot = await (await request.get('/api/catalogs/watershed')).json();
    const version = snapshot.catalog.versions.find((row: any) =>
      row.id.endsWith('observations:v1'),
    );
    const representation = snapshot.catalog.representations.find(
      (row: any) => row.version === version.id,
    );
    await page.addInitScript((deny) => {
      (window as any).__copiedIds = [];
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async (value: string) => {
            (window as any).__copiedIds.push(value);
            if (deny) throw new Error('Clipboard denied');
          },
        },
      });
    }, denied);
    let reads = 0;
    await page.route('**/api/read', (route) => {
      reads++;
      return route.abort();
    });
    await page.goto(`/?catalog=watershed&tab=Data&version=${encodeURIComponent(version.id)}`);
    await page.getByText('Data version identifiers', { exact: true }).click();
    const versionDetails = page.locator('.version-context details').first();
    await versionDetails
      .locator('p')
      .filter({ has: page.locator('code', { hasText: version.id }) })
      .getByRole('button', { name: 'Copy version identifier', exact: true })
      .click();
    await expect(page.locator('.sr-only[role="status"]')).toHaveText(
      denied
        ? 'Clipboard access is unavailable. Select and copy the identifier shown here.'
        : 'Version identifier copied.',
    );
    await page.getByText('File, table or service identifiers', { exact: true }).click();
    await page
      .locator('.data-toolbar')
      .getByRole('button', { name: 'Copy identifier', exact: true })
      .click();
    await expect(page.locator('.data-toolbar [role="status"]')).toHaveText(
      denied
        ? 'Clipboard access is unavailable. Select and copy the identifier shown here.'
        : 'File, table or service identifier copied.',
    );
    expect(await page.evaluate(() => (window as any).__copiedIds)).toEqual([
      version.id,
      representation.id,
    ]);
    expect(reads).toBe(0);
  });
}

test('scalar release timestamps and nonhex identities remain exact details rather than version names', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  const values = ['2026-11-06T12:34:56Z', 'opaque_ZyX987'];
  snapshot.catalog.releases.forEach((release: any, index: number) => {
    release.reference.value = values[index % values.length];
  });
  await page.route('**/api/catalogs/watershed', (route) => route.fulfill({ json: snapshot }));
  let reads = 0;
  await page.route('**/api/read', (route) => {
    reads++;
    return route.abort();
  });
  await page.goto('/?catalog=watershed');
  const selector = page.getByRole('combobox', { name: 'Data version', exact: true });
  await expect(selector).toContainText('Version label not supplied');
  for (const value of values) await expect(selector).not.toContainText(value);
  await page.getByText('Data version identifiers', { exact: true }).click();
  await page.getByText('Version and release references', { exact: true }).click();
  for (const value of values)
    await expect(page.locator('.version-context pre')).toContainText(value);
  expect(reads).toBe(0);
});

test('a listed notification service opens its own description without a record request', async ({
  page,
  request,
}) => {
  const snapshot = await (await request.get('/api/catalogs/watershed')).json();
  const dataset = snapshot.catalog.datasets.find((row: any) => row.alias === 'observations');
  const version = snapshot.catalog.versions.find((row: any) => row.id.endsWith('observations:v1'));
  const { record } = snapshot.catalog.representations.find(
    (row: any) => row.version === version.id,
  );
  const notification = {
    id: 'urn:example:notification-service',
    version: version.id,
    kind: 'service',
    availability: 'available',
    record,
  };
  snapshot.catalog.representations.push(notification);
  const profile = snapshot.catalog.extensions['urn:ddk:catalog:assembly'].projectExtensions.find(
    (row: any) => row.project.id === snapshot.catalog.project.id,
  ).extensions['urn:ddk:publisher:discovery'];
  profile.records.push({
    target: {
      kind: 'representation',
      datasetId: dataset.id,
      versionId: version.id,
      representationId: notification.id,
    },
    resource: {
      kind: 'notification',
      purpose: 'Synthetic notifications about a published fixture file.',
      destination: { kind: 'notification', url: 'https://example.invalid/notifications' },
    },
  });
  await page.route('**/api/catalogs/watershed', (route) => route.fulfill({ json: snapshot }));
  const operations: string[] = [];
  await page.route(/\/api\/(read|query)$/, (route) => {
    operations.push(route.request().url());
    return route.abort();
  });
  await page.goto(`/?catalog=watershed&tab=Data&version=${encodeURIComponent(version.id)}`);
  await page
    .getByRole('combobox', { name: 'File, table or service', exact: true })
    .selectOption(notification.id);
  await expect(
    page.getByText('Synthetic notifications about a published fixture file.', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: /Open notification service/ })).toHaveAttribute(
    'href',
    'https://example.invalid/notifications',
  );
  await expect(
    page.getByText(
      'This resource supplies documentation, metadata or notifications rather than record access.',
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open records', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Apply filter', exact: true })).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Download this page (JSON) ↓', exact: true }),
  ).toHaveCount(0);
  expect(operations).toHaveLength(0);
});
