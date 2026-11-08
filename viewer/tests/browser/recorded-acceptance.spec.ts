import { test, expect } from '@playwright/test';

for (const [name, viewport] of [
  ['desktop', { width: 1440, height: 1000 }],
  ['mobile', { width: 390, height: 844 }],
] as const) {
  test(`recorded publisher acceptance is visible without opening payloads on ${name}`, async ({
    page,
    request,
  }) => {
    const response = await request.get('/api/catalogs/congress-authored');
    test.skip(response.status() === 404, 'The local Congress metadata example is not enabled.');
    expect(response.ok()).toBe(true);
    const snapshot = await response.json();
    const run = snapshot.catalog.runs[0];
    const trace = snapshot.catalog.extensions['urn:ddk:catalog:assembly'].managedExecutions[0];
    expect(trace.run).toBe(run.id);
    expect(trace.record).toEqual(run.record);
    const version = snapshot.catalog.versions.find((row: any) => run.outputs.includes(row.id));
    const operations: string[] = [];
    const errors: string[] = [];
    page.on('request', (request) => {
      if (/\/api\/(read|query|evidence)(?:\?|$)/.test(request.url()))
        operations.push(request.url());
    });
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize(viewport);
    const params = new URLSearchParams({
      catalog: 'congress-authored',
      dataset: version.dataset,
      version: version.id,
      tab: 'Activity',
    });
    await page.goto(`/?${params}`);
    const acceptance = page.locator('.recorded-acceptance');
    await expect(
      acceptance.getByText('Recorded processing acceptance', { exact: true }),
    ).toBeVisible();
    await expect(acceptance.locator('code')).toHaveText(trace.acceptedQualification);
    await expect(acceptance).toContainText('currently accepted, selected or published');
    await expect(acceptance).not.toContainText('file:');
    await expect(acceptance.locator('a, .badge.good')).toHaveCount(0);
    await expect(
      page.getByText('No release membership is recorded for this version.', { exact: false }),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(operations).toEqual([]);
    expect(errors).toEqual([]);
  });
}
