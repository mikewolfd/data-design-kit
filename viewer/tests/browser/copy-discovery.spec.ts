import { test, expect } from '@playwright/test';
import type { CatalogSnapshot } from '../../src/domain/types';

// Replay catalog metadata only. These tests never call an application reader.
async function capturedCatalog(page: any, request: any, edit?: (s: CatalogSnapshot) => void) {
  const snapshot: CatalogSnapshot = await (await request.get('/api/catalogs/watershed')).json();
  edit?.(snapshot);
  await page.route('**/api/catalogs/watershed', (route: any) => route.fulfill({ json: snapshot }));
  await page.route('**/api/read', (route: any) => route.abort('blockedbyclient'));
  await page.route('**/api/query', (route: any) => route.abort('blockedbyclient'));
  return snapshot;
}

test('discovery preserves route IDs with visitor labels, document identity and scoped search', async ({
  page,
  request,
}) => {
  await capturedCatalog(page, request);
  await page.goto('/?catalog=watershed');
  await expect(page).toHaveTitle('Watershed observations · Watershed observatory · DDK');
  await expect(page.getByRole('link', { name: 'Data catalog home' })).toBeVisible();
  for (const name of [
    'View data',
    'Related data',
    'Checks & sources',
    'History',
    'Compare versions',
  ]) {
    await expect(page.getByRole('tab', { name, exact: true })).toBeVisible();
  }
  await page.getByRole('tab', { name: 'History', exact: true }).click();
  await expect(page).toHaveURL(/tab=Activity/);
  await expect(
    page.getByRole('searchbox', { name: 'Search this catalog' }),
  ).toHaveAccessibleDescription(
    'Search dataset titles, descriptions, supplied alternate names and identifiers. Exact identifiers appear first. Field names and other catalogs are not searched.',
  );
  await page.getByRole('searchbox').fill('does-not-exist');
  await expect(page.getByText('No datasets match these filters.')).toBeVisible();
  await expect(page.getByText('Dataset list could not be loaded.')).toHaveCount(0);
});

test('catalog failure stays distinct from empty search and switching copy is explicit', async ({
  page,
  request,
}) => {
  await capturedCatalog(page, request);
  await page.goto('/?catalog=watershed&snapshot=wrong');
  await expect(page.getByText('Dataset list could not be loaded.')).toBeVisible();
  await expect(page.getByText('No datasets match these filters.')).toHaveCount(0);
  await expect(
    page.getByText(
      'This link refers to a different catalog copy. Opening the available copy may show different data.',
    ),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Open the catalog available here' }).click();
  await expect(
    page.getByRole('heading', { name: 'Watershed observations', exact: true }),
  ).toBeVisible();
});

test('record filter respects connected dataset scope and preserves unknown availability', async ({
  page,
  request,
}) => {
  await capturedCatalog(page, request, (s) => {
    s.capabilities.readDatasetIds = [];
  });
  await page.goto('/?catalog=watershed');
  await expect(
    page.getByRole('heading', { name: 'Watershed observations', exact: true }),
  ).toBeVisible();
  await page.getByRole('combobox', { name: 'Can I view records here?' }).selectOption('available');
  await expect(page.locator('.dataset-nav button.active')).toHaveCount(0);
  await expect(page.getByText('No datasets match these filters.')).toBeVisible();
  await page
    .getByRole('combobox', { name: 'Can I view records here?' })
    .selectOption('unavailable');
  await expect(page.locator('.dataset-nav button')).toHaveCount(2);
});

test('duplicate titles show aliases, technical descriptions retain limits and original source', async ({
  page,
  request,
}) => {
  await capturedCatalog(page, request, (s) => {
    s.catalog.datasets[1].title = s.catalog.datasets[0].title;
    const assembly = s.catalog.extensions!['urn:ddk:catalog:assembly'] as any;
    assembly.datasetDefinitions.observations.description =
      'Coverage limits:\nOnly retained observations.\nNullability basis:\nExact schema rationale.';
  });
  await page.goto('/?catalog=watershed');
  await expect(page.locator('.dataset-nav')).toContainText('observations');
  await expect(page.locator('.dataset-nav')).toContainText('stations');
  await expect(page.locator('.dataset-heading')).toContainText(
    'Coverage and important limits: Only retained observations.',
  );
  await expect(
    page.locator('.dataset-heading').getByText('Technical definition notes'),
  ).toBeVisible();
  await page.locator('.dataset-heading').getByText('Technical definition notes').click();
  await expect(page.locator('.dataset-heading')).toContainText('Exact schema rationale.');
  await page.getByRole('button', { name: 'Share & export' }).click();
  await expect(
    page.getByRole('button', { name: 'Download dataset reference (JSON)' }),
  ).toBeVisible();
  await expect(page.locator('.share-panel')).toContainText('It does not contain data records.');
});

test('unknown reads remain unknown in discovery and a source-labelled fixture is explicit', async ({
  page,
  request,
}) => {
  await capturedCatalog(page, request, (s) => {
    s.catalog.versions.forEach((v) => {
      v.retention = 'unknown';
    });
    s.catalog.datasets[0].title = 'Future reader fixture';
    s.catalog.datasets[0].rowMeaning = 'One future fixture row';
    s.mode = 'application';
  });
  await page.goto('/?catalog=watershed');
  await expect(
    page.getByRole('heading', { name: 'Future reader fixture', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Example dataset · not live archive data')).toBeVisible();
  await page.getByRole('combobox', { name: 'Can I view records here?' }).selectOption('unknown');
  await expect(page.locator('.dataset-nav button')).toHaveCount(2);
  await page.getByRole('button', { name: 'Share & export' }).click();
  await expect(
    page.getByRole('button', { name: 'Copy link to this dataset and version' }),
  ).toBeVisible();
});

test('sharing without a selected version names only the dataset', async ({ page, request }) => {
  await capturedCatalog(page, request, (s) => {
    delete s.catalog.currentSelection;
  });
  await page.goto('/?catalog=watershed');
  await page.getByRole('button', { name: 'Share & export' }).click();
  await expect(page.getByRole('button', { name: 'Copy dataset link', exact: true })).toBeVisible();
  await expect(page.locator('.share-panel')).toContainText(
    'Includes identifiers for the catalog and dataset.',
  );
});
