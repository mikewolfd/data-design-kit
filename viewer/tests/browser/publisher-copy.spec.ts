import { test, expect } from '@playwright/test';

async function snapshot(request: any, id: string) {
  const response = await request.get(`/api/catalogs/${id}`);
  test.skip(response.status() === 404, `${id} is not enabled`);
  expect(response.ok()).toBe(true);
  return response.json();
}

test('Congress visitor introductions precede retained technical limits and the reader fixture stays explicit', async ({ page, request }) => {
  const source = await snapshot(request, 'congress');
  expect(source.capabilities.read).toBe(false);
  await page.goto('/?catalog=congress&dataset=detail');
  await expect(page.getByRole('heading', { name: 'Document details', exact: true })).toBeVisible();
  const intro = page.locator('.dataset-heading .dataset-subtitle').first();
  await expect(intro).not.toContainText('Nullability basis:');
  await expect(intro).not.toContainText('Coverage limits:');
  await expect(page.getByText('Coverage and important limits:', { exact: true })).toBeVisible();
  const technical = page.locator('.dataset-heading details').filter({ has: page.locator('summary', { hasText: 'Technical definition notes' }) });
  await technical.locator('summary').click();
  await expect(technical).toContainText('Nullability basis:');
  await page.goto('/?catalog=congress&dataset=future-data');
  await expect(page.getByText('Example dataset · not live archive data', { exact: true })).toBeVisible();
  await expect(page.locator('.dataset-heading')).toContainText('Synthetic reader example');
});

test('SpicyRegs titles and record meanings display without implying connected rows', async ({ page, request }) => {
  const source = await snapshot(request, 'spicy-regs');
  expect(source.catalog.versions).toHaveLength(0);
  expect(source.capabilities.read).toBe(false);
  for (const [alias, title] of [
    ['current-bill-summaries', 'AI-generated bill summaries'],
    ['current-etl-receipts', 'Data processing records'],
    ['current-court-dockets', 'Court dockets for Administrative Procedure Act cases — native output definition'],
  ]) {
    await page.goto(`/?catalog=spicy-regs&dataset=${alias}`);
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open records', exact: true })).toHaveCount(0);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('Commerce shows publisher check meanings and named source captures with exact evidence', async ({ page, request }) => {
  const source = await snapshot(request, 'commerce-native');
  const revenue = source.catalog.versions.find((v: any) => v.dataset === 'daily-revenue');
  await page.goto(`/?catalog=commerce-native&dataset=daily-revenue&version=${encodeURIComponent(revenue.id)}&tab=Evidence`);
  await expect(page.getByText('13 recorded; 13 passed; 0 failed; 0 unknown; 0 not run', { exact: true })).toBeVisible();
  await expect(page.locator('.evidence-row p', { hasText: 'Amounts are zero or greater.' })).toBeVisible();
  await expect(page.locator('.evidence-row strong', { hasText: 'title not supplied' })).toHaveCount(0);
  const orders = source.catalog.versions.find((v: any) => v.dataset === 'orders' && v.sources.length);
  await page.goto(`/?catalog=commerce-native&dataset=orders&version=${encodeURIComponent(orders.id)}&tab=Evidence`);
  const selectedVersionSources = page.locator('.context-scope').filter({
    has: page.getByRole('heading', {
      name: 'Recorded source observations for this version',
      exact: true,
    }),
  });
  await expect(
    selectedVersionSources.getByText(
      'Example orders: orders.csv. Source file recorded for this data load.',
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByText('No checks are recorded for this data version', { exact: true })).toBeVisible();
});

test('relationship cards preserve disclosed assessments and unresolved references', async ({
  page,
  request,
}) => {
  const operations: string[] = [],
    errors: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/(read|query|evidence)(?:\?|$)/.test(request.url())) operations.push(request.url());
  });
  page.on('pageerror', (error) => errors.push(error.message));
  for (const id of ['congress', 'spicy-regs', 'congress-authored']) {
    const source = await snapshot(request, id);
    const assembly = source.catalog.extensions['urn:ddk:catalog:assembly'];
    const assessment = assembly.relationshipAssessments?.find(
      (row: any) => row.externalExistence === 'not_assessed',
    );
    const relationship = source.catalog.relationships.find((row: any) =>
      id === 'congress-authored'
        ? row.id === assessment.relationship
        : id === 'congress'
          ? !!row.target.external
          : row.resolution === 'unresolved_allowed',
    );
    expect(relationship).toBeTruthy();
    await page.goto(
      `/?${new URLSearchParams({ catalog: id, dataset: relationship.source.dataset, tab: 'Connections' })}`,
    );
    const card = page.locator(`[data-relationship-id="${relationship.id}"]`);
    await expect(card).toBeVisible();
    await expect(page.getByText('Matches have not been checked', { exact: false })).toHaveCount(0);
    if (id === 'congress-authored') {
      await expect(card).toContainText('Matching rule assessment: Supported');
      await expect(card).toContainText(assessment.reason);
      await expect(card).toContainText(
        'Whether this external target exists has not been assessed.',
      );
    } else {
      await expect(
        page.getByText(assembly.relationshipAssessmentScope.reason, { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText('Matching rule assessment: Unknown', { exact: true }),
      ).toBeVisible();
      await expect(card.locator('.relationship-assessment')).toHaveCount(0);
      if (id === 'congress')
        await expect(card).toContainText('Whether this external target exists is unknown here.');
    }
    await expect(card).toContainText(
      id === 'spicy-regs'
        ? 'Declared requirement: Unmatched records allowed'
        : 'Declared requirement: External reference',
    );
    await expect(card.locator('.badge.good')).toHaveCount(0);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(operations).toEqual([]);
  expect(errors).toEqual([]);
});
