import { test, expect } from '@playwright/test';
import { resolve } from 'node:path';
import { CatalogStore } from '../../src/server/catalog-store';
import { exactStringify } from '../../src/domain/exact';

// An optional, pinned catalog made by the maintained DDK assembler from its synthetic
// producer fixture. Only browser test responses are replaced; no runtime registration changes.
const directory = process.env.DDK_VIEWER_PRODUCER_FIXTURE_DIRECTORY;
const lockSha256 = process.env.DDK_VIEWER_PRODUCER_FIXTURE_LOCK;

for (const [name, viewport] of [
  ['desktop', { width: 1440, height: 1000 }],
  ['mobile', { width: 390, height: 844 }],
] as const) {
  test(`recorded producer evidence preserves the assembled model metadata on ${name}`, async ({
    page,
  }, testInfo) => {
    test.skip(!directory && !lockSha256, 'The pinned synthetic producer catalog is not supplied.');
    expect(directory).toBeTruthy();
    expect(lockSha256).toMatch(/^[a-f0-9]{64}$/);
    const store = new CatalogStore(
      [
        {
          id: 'producer-model-example',
          directory: resolve(directory!),
          lockSha256: lockSha256!,
          mode: 'application',
          exampleData: 'synthetic',
          navigationLabel: 'Synthetic producer metadata example',
        },
      ],
      'local',
    );
    const snapshot = await store.snapshot('producer-model-example');
    const assembly = snapshot.catalog.extensions!['urn:ddk:catalog:assembly'] as any;
    const trace = assembly.managedExecutions[0];
    const run = snapshot.catalog.runs.find((row) => row.id === trace.run)!;
    const version = snapshot.catalog.versions.find((row) => run.outputs.includes(row.id))!;
    expect(trace.record).toEqual(run.record);
    expect(trace.producerEvidence.role).toBe('model');
    expect(trace.acceptedQualification).not.toBe(
      trace.producerEvidence.prerequisite.accepted_qualification,
    );
    expect(snapshot.capabilities.read).toBe(false);
    expect(snapshot.capabilities.query).toBe(false);
    const operations: string[] = [];
    const errors: string[] = [];
    page.on('request', (request) => {
      if (/\/api\/(read|query|evidence)(?:\?|$)/.test(request.url()))
        operations.push(request.url());
    });
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/catalogs', (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ catalogs: [] }),
      }),
    );
    await page.route('**/api/catalogs/producer-model-example', (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(snapshot),
      }),
    );
    await page.setViewportSize(viewport);
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
    const producer = page.locator('.recorded-producer-evidence');
    await expect(producer).toContainText('whether proof files are still available');
    await producer.getByText('Recorded producer evidence for this event', { exact: true }).click();
    await expect(producer.locator('pre')).toBeVisible();
    expect(await producer.locator('pre').textContent()).toBe(
      exactStringify(trace.producerEvidence),
    );
    await expect(producer.locator('a, button, .badge')).toHaveCount(0);
    await expect(producer).not.toContainText('bytes_base64');
    await expect(producer).not.toContainText('producer_evidence_witness');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(operations).toEqual([]);
    expect(errors).toEqual([]);
    await producer.screenshot({ path: testInfo.outputPath(`producer-${name}.png`) });
  });
}
