import { createHash } from 'node:crypto';
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type { CatalogSnapshot } from '../../src/domain/types';

async function queryCatalog(page: any, request: any) {
  const snapshot: CatalogSnapshot = await (await request.get('/api/catalogs/watershed')).json();
  snapshot.capabilities.sql = true;
  await page.route('**/api/catalogs/watershed', (route: any) => route.fulfill({ json: snapshot }));
  const dataset = snapshot.catalog.datasets[0];
  const version = snapshot.catalog.versions.find((item) => item.dataset === dataset.alias)!;
  return { snapshot, dataset, version };
}

test('query lab requires explicit versions and preserves exact results in the reading pane', async ({
  page,
  request,
}) => {
  const { dataset, version } = await queryCatalog(page, request);
  await page.route('**/api/sql', async (route) => {
    const body = route.request().postDataJSON();
    await route.fulfill({
      json: {
        status: 'ok',
        transport: 'ddk-exact-json-v1',
        bindings: body.bindings,
        columns: ['identifier', 'text'],
        returned: 2,
        rows: [
          { identifier: { $number: '9007199254740993' }, text: 'First retained text' },
          { identifier: { $number: '9007199254740994' }, text: 'Second retained text' },
        ],
        execution: {
          kind: 'owner',
          recipeId: 'urn:ddk:ad-hoc-sql',
          sqlSha256: createHash('sha256').update(body.sql).digest('hex'),
          inputs: Object.keys(body.bindings),
          contextualRelationships: [],
        },
      },
    });
  });
  await page.goto('/?catalog=watershed&tab=Query');
  await page.getByLabel('SQL query', { exact: true }).fill('SELECT * FROM observations LIMIT 2');
  await expect(page.getByRole('button', { name: 'Run SQL query' })).toBeDisabled();
  await page
    .getByRole('combobox', { name: `Data version for ${dataset.alias}`, exact: true })
    .selectOption(version.id);
  await page.getByRole('button', { name: 'Run SQL query' }).click();
  await expect(page.getByRole('cell', { name: '9007199254740993', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Inspect record 01', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Record detail', exact: true })).toContainText(
    'First retained text',
  );
  await page.getByRole('button', { name: 'Next record', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Record detail', exact: true })).toContainText(
    'Second retained text',
  );
  await page.getByRole('button', { name: 'Close detail', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Inspect record 01', exact: true })).toBeFocused();
  await page.getByLabel('SQL query', { exact: true }).fill('SELECT * FROM observations LIMIT 1');
  await expect(page.getByRole('cell', { name: '9007199254740993', exact: true })).toHaveCount(0);
});

for (const outcome of ['empty', 'refused', 'unknown', 'wrong-sql', 'wrong-binding'] as const)
  test(`query lab preserves the ${outcome} outcome`, async ({ page, request }) => {
    const { dataset, version } = await queryCatalog(page, request);
    await page.route('**/api/sql', async (route) => {
      const body = route.request().postDataJSON();
      await route.fulfill({
        json: {
          status: outcome === 'refused' || outcome === 'unknown' ? outcome : 'ok',
          reason: `Recorded ${outcome} outcome`,
          transport: 'ddk-exact-json-v1',
          bindings: outcome === 'wrong-binding' ? {} : body.bindings,
          columns: [],
          rows: [],
          returned: 0,
          execution: {
            kind: 'owner',
            recipeId: 'urn:ddk:ad-hoc-sql',
            sqlSha256:
              outcome === 'wrong-sql'
                ? '0'.repeat(64)
                : createHash('sha256').update(body.sql).digest('hex'),
            inputs: Object.keys(body.bindings),
            contextualRelationships: [],
          },
        },
      });
    });
    await page.goto('/?catalog=watershed&tab=Query');
    await page
      .getByLabel('SQL query', { exact: true })
      .fill('SELECT * FROM observations WHERE false');
    await page
      .getByRole('combobox', { name: `Data version for ${dataset.alias}`, exact: true })
      .selectOption(version.id);
    await page.getByRole('button', { name: 'Run SQL query' }).click();
    if (outcome === 'empty')
      await expect(page.getByText('No matching results', { exact: true })).toBeVisible();
    else if (outcome === 'refused')
      await expect(page.getByText('Query results were not loaded', { exact: true })).toBeVisible();
    else if (outcome === 'unknown')
      await expect(
        page.getByText('Query request outcome is unknown', { exact: true }),
      ).toBeVisible();
    else
      await expect(
        page.getByText(
          'The response does not match the submitted SQL and selected inputs. Run the query again to retry.',
          { exact: true },
        ),
      ).toBeVisible();
    if (outcome !== 'empty')
      await expect(page.getByText('No matching results', { exact: true })).toHaveCount(0);
  });

test('source inventory inspects only the pinned original and rejects a mismatched response identity', async ({
  page,
  request,
}) => {
  const { snapshot } = await queryCatalog(page, request);
  const reference = {
    scheme: 'urn:ddk:version:local-file-sha256',
    authority: 'urn:test',
    value: { location: 'file:///retained/original.json', sha256: 'a'.repeat(64) },
  };
  snapshot.capabilities.evidence = true;
  snapshot.catalog.sources = [
    {
      id: 'urn:test:capture',
      scope: 'One retained original',
      outcome: 'ok',
      reference,
      content: reference,
      record: { uri: 'urn:test:receipt' },
    },
  ];
  await page.route('**/api/evidence', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.record).toEqual({ uri: 'file:///retained/original.json', sha256: 'a'.repeat(64) });
    await route.fulfill({
      json: {
        record: { ...body.record, sha256: 'b'.repeat(64) },
        document: { text: 'Unmatched source document' },
        scope: 'retained original',
      },
    });
  });
  await page.goto('/?catalog=watershed&tab=Evidence');
  await expect(
    page.getByRole('heading', { name: 'Captured sources in this catalog' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Inspect retained original', exact: true }).click();
  const rejection = page.getByRole('alert');
  await expect(rejection).toBeVisible();
  await expect(rejection).toContainText(
    'The returned file identity does not match the requested record.',
  );
  await expect(page.getByText('Unmatched source document', { exact: true })).toHaveCount(0);
});

test('dataset and reading panels keep readable contrast throughout their entrance motion', async ({
  page,
}) => {
  await page.goto('/?catalog=watershed&tab=Overview');
  await expect(
    page.getByRole('heading', { name: 'Watershed observations', exact: true }),
  ).toBeVisible();
  // Freeze a real intermediate frame; timing alone must not hide a contrast failure.
  await page.addStyleTag({
    content: '.tab-content, .record-inspector { animation-duration: 10s !important; }',
  });
  await page.getByRole('tab', { name: 'View data', exact: true }).click();
  await page.getByRole('tabpanel').evaluate((element) => {
    for (const animation of element.getAnimations()) {
      animation.pause();
      animation.currentTime = 5000;
    }
  });
  await page.getByRole('button', { name: 'Open records', exact: true }).click();
  await page.getByRole('button', { name: 'Inspect record 01', exact: true }).click();
  const detail = page.getByRole('region', { name: 'Record detail', exact: true });
  await detail.evaluate((element) => {
    for (const animation of element.getAnimations()) {
      animation.pause();
      animation.currentTime = 5000;
    }
  });
  await expect(page.getByRole('tabpanel')).toHaveCSS('opacity', '1');
  await expect(detail).toHaveCSS('opacity', '1');
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
});
