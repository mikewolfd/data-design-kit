import { test, expect } from '@playwright/test';
import { resolve } from 'node:path';
import { CatalogStore } from '../../src/server/catalog-store';
import { exactStringify } from '../../src/domain/exact';

test('accepted proof history preserves an input-only catalog without record access', async ({
  page,
}, testInfo) => {
  const directory = process.env.DDK_VIEWER_PROOF_FIXTURE_DIRECTORY;
  const lockSha256 = process.env.DDK_VIEWER_PROOF_FIXTURE_LOCK;
  test.skip(!directory && !lockSha256, 'The pinned synthetic proof catalog is not supplied.');
  expect(directory).toBeTruthy();
  expect(lockSha256).toMatch(/^[a-f0-9]{64}$/);
  // Admit the actual DDK-assembled bytes. Browser responses are replaced only in this test;
  // no application registration, data reader or evidence reader is added.
  const store = new CatalogStore(
    [
      {
        id: 'producer-proof-example',
        directory: resolve(directory!),
        lockSha256: lockSha256!,
        mode: 'application',
        exampleData: 'synthetic',
        navigationLabel: 'Synthetic proof metadata example',
      },
    ],
    'local',
  );
  const snapshot = await store.snapshot('producer-proof-example');
  const { catalog } = snapshot;
  const assembly = catalog.extensions!['urn:ddk:catalog:assembly'] as any;
  expect(snapshot.report.decision).toBe('passed');
  expect(catalog.runs).toHaveLength(1);
  expect(catalog.versions).toHaveLength(1);
  for (const values of [
    catalog.representations,
    catalog.checks,
    catalog.releases,
    catalog.selections,
  ])
    expect(values).toEqual([]);
  const [run] = catalog.runs;
  const [version] = catalog.versions;
  const [trace] = assembly.managedExecutions;
  expect(run.inputs).toEqual([version.id]);
  expect(run.outputs).toEqual([]);
  expect(run.inputCoverage.status).toBe('unknown');
  expect(trace.run).toBe(run.id);
  expect(trace.record).toEqual(run.record);
  expect(trace.producerEvidence.role).toBe('proof');
  expect(trace.producerEvidence).not.toHaveProperty('prerequisite');
  expect(trace.acceptedQualification).toMatch(/^[a-f0-9]{64}$/);
  expect(snapshot.capabilities.read).toBe(false);
  expect(snapshot.capabilities.query).toBe(false);
  expect(snapshot.capabilities.evidence).toBeFalsy();

  const operations: string[] = [],
    errors: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/(read|query|evidence)(?:\?|$)/.test(request.url())) operations.push(request.url());
  });
  page.on('pageerror', (error) => errors.push(error.message));
  const listing = await store.list();
  await page.route('**/api/catalogs', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(listing),
    }),
  );
  await page.route('**/api/catalogs/producer-proof-example', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(snapshot),
    }),
  );
  await page.goto(
    `/?${new URLSearchParams({
      catalog: snapshot.id,
      dataset: version.dataset,
      version: version.id,
      snapshot: snapshot.identity.catalogSha256,
      tab: 'Activity',
    })}`,
  );
  const acceptance = page.locator('.recorded-acceptance');
  await expect(acceptance.locator('code')).toHaveText(trace.acceptedQualification);
  await expect(acceptance).toContainText('does not establish that every record was verified');
  await expect(acceptance.locator('a, .badge')).toHaveCount(0);
  await expect(
    page
      .locator('.run dt')
      .filter({ hasText: /^Input coverage$/ })
      .locator('..'),
  ).toContainText('unknown');
  await page.getByText('Exact consumed inputs and outputs', { exact: true }).click();
  const membership = page
    .locator('details')
    .filter({ has: page.getByText('Exact consumed inputs and outputs', { exact: true }) });
  await expect(membership.locator('pre')).toBeVisible();
  expect(await membership.locator('pre').textContent()).toBe(
    exactStringify({ inputs: run.inputs, outputs: [] }),
  );
  const producer = page.locator('.recorded-producer-evidence');
  await producer.getByText('Recorded producer evidence for this event', { exact: true }).click();
  await expect(producer.locator('pre')).toBeVisible();
  expect(await producer.locator('pre').textContent()).toBe(exactStringify(trace.producerEvidence));
  await expect(producer.locator('a, button, .badge')).toHaveCount(0);
  await expect(
    page.getByText('No release membership is recorded for this version.', { exact: false }),
  ).toBeVisible();
  await page
    .locator('.run')
    .first()
    .screenshot({ path: testInfo.outputPath('proof-history.png') });

  await page.getByRole('tab', { name: 'View data', exact: true }).click();
  await expect(page.getByText('Viewing records is not connected', { exact: true })).toBeVisible();
  await expect(page.locator('.data-table')).toHaveCount(0);
  await expect(
    page.getByRole('combobox', { name: 'File, table or service', exact: true }).locator('option'),
  ).toHaveCount(1);
  expect(operations).toEqual([]);
  expect(errors).toEqual([]);
});
