import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import type { CatalogSnapshot } from '../../src/domain/types';

const dedicatedPreview = process.env.DDK_PRODUCT_BROWSER_URL;
if (dedicatedPreview) test.use({ baseURL: dedicatedPreview });

const observationId = 'urn:ddk-viewer:fixture:watershed:dataset:observations';
const stationsId = 'urn:ddk-viewer:fixture:watershed:dataset:stations';
const v1 = 'urn:ddk-viewer:fixture:watershed:observations:v1';
const watershedUrl = `/?${new URLSearchParams({ catalog: 'watershed', dataset: observationId, version: v1 })}`;
const assemblyKey = 'urn:ddk:catalog:assembly';
const discoveryKey = 'urn:ddk:publisher:discovery';

// The only data access allowed here is the viewer's registered synthetic fixture read.
test.beforeEach(async ({ page }) => {
  await page.route(/\/api\/(read|query|evidence)(?:\?|$)/, (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/read' && request.postDataJSON()?.catalogId === 'watershed')
      return route.continue();
    return route.abort('blockedbyclient');
  });
});

function section(page: Page, heading: string) {
  return page.locator('section.section').filter({
    has: page.getByRole('heading', { name: heading, exact: true }),
  });
}

async function openWithKeyboard(summary: Locator) {
  await summary.focus();
  await expect(summary).toBeFocused();
  await summary.press('Enter');
  await expect(summary.locator('..')).toHaveAttribute('open', '');
}

async function clipboard(page: Page) {
  await page.addInitScript(() => {
    const state = { copied: [] as string[], deny: false };
    Object.defineProperty(window, '__productClipboard', { value: state });
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (value: string) => {
          state.copied.push(value);
          if (state.deny) throw new Error('Clipboard denied for the test');
        },
      },
    });
  });
  return {
    copied: () => page.evaluate(() => Reflect.get(window, '__productClipboard').copied as string[]),
    deny: () =>
      page.evaluate(() => {
        Reflect.get(window, '__productClipboard').deny = true;
      }),
  };
}

async function admittedSpicy(request: APIRequestContext) {
  const response = await request.get('/api/catalogs/spicy-regs');
  test.skip(
    response.status() === 404 && !dedicatedPreview,
    'The optional public SpicyRegs registration is disabled.',
  );
  expect(
    response.ok(),
    'The retained public catalog must be admitted by this preview.',
  ).toBeTruthy();
  const snapshot: CatalogSnapshot = await response.json();
  expect(snapshot.audience).toBe('public');
  expect(snapshot.mode).toBe('application');
  return snapshot;
}

test('Spicy search cards show distinctions and access before opening the selected dataset', async ({
  page,
  request,
}) => {
  const snapshot = await admittedSpicy(request);
  const dataset = snapshot.catalog.datasets.find(({ alias }) => alias === 'current-cftc-comments')!;
  await page.goto('/?catalog=spicy-regs');
  const search = page.getByRole('searchbox', { name: 'Search this catalog' });
  await search.fill('public comments');
  const results = page.getByRole('navigation', { name: 'Datasets' });
  const retained = results.getByRole('button', {
    name: /Public comments — retained source interpretation/,
  });
  const native = results.getByRole('button', {
    name: /Public comments — native output definition/,
  });
  await expect(retained).toContainText('One posted public-comment record');
  await expect(native).toContainText('One posted public-comment record');
  await expect(native).toContainText('Description and fields only');
  await search.fill(dataset.id);
  const cftc = results.getByRole('button', { name: /Selected CFTC comment observations/ });
  await expect(results.getByRole('button')).toHaveCount(1);
  await expect(cftc).toContainText('One selected comment observation');
  await expect(cftc).toContainText('Commodity Futures Trading Commission comments');
  await expect(cftc).toContainText('Description and fields only');
  await cftc.click();
  await expect(page.getByRole('heading', { name: dataset.title, exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get('dataset')).toBe(dataset.id);
  await expect(section(page, 'Coverage')).toContainText(
    'Sampled. Selected retained listing observations',
  );
  const dates = section(page, 'Dates and update expectations');
  const observationDate = dates.locator('dt', { hasText: /^Coverage observation date$/ });
  await expect(observationDate.locator('..').locator('time')).toHaveAttribute(
    'datetime',
    '2026-10-13',
  );
  for (const fact of ['Source publication date', 'Data update date', 'Source retrieval date'])
    await expect(
      dates.locator('dt', { hasText: new RegExp(`^${fact}$`) }).locator('..'),
    ).toContainText('Not supplied');
  await page.getByRole('tab', { name: 'Checks & sources' }).click();
  await expect(page.getByText('Declared source publishers', { exact: true })).toBeVisible();
  await expect(page.getByText(/Source observations remain unknown/)).toBeVisible();
});

test('Spicy unknown publisher facet and scoped publisher code/field limits remain explicit', async ({
  page,
  request,
}) => {
  await admittedSpicy(request);
  await page.goto('/?catalog=spicy-regs&dataset=current-comment-attributes');
  await page.getByText('More filters', { exact: true }).click();
  const publisher = page.getByRole('combobox', { name: 'Declared source publisher' });
  const unknown = publisher.getByRole('option', { name: /Unknown or not supplied \([1-9]\d*\)/ });
  await expect(unknown).toHaveCount(1);
  const count = Number((await unknown.textContent())?.match(/\((\d+)\)/)?.[1]);
  await publisher.selectOption('__unknown__');
  await expect(page.locator('.nav-label [aria-live]')).toHaveText(String(count));
  await expect(page.getByRole('navigation', { name: 'Datasets' })).not.toContainText(
    'Declared publisher:',
  );
  const dictionary = section(page, 'What each field means');
  await openWithKeyboard(
    dictionary.locator('.field-row summary').filter({ hasText: 'file_formats' }),
  );
  await expect(dictionary.getByText(/Size in bytes reported by Regulations.gov/)).toBeVisible();
  await openWithKeyboard(
    dictionary.getByLabel('Technical field details for ["file_formats"][each]["size"]', {
      exact: true,
    }),
  );
  await expect(
    dictionary.getByRole('button', {
      name: 'Copy name for ["file_formats"][each]["size"]',
      exact: true,
    }),
  ).toBeVisible();

  await page.goto('/?catalog=spicy-regs&dataset=current-comments');
  const field = section(page, 'What each field means')
    .locator('li.field')
    .filter({
      has: page.getByRole('button', {
        name: 'Copy name for ["document_type"]',
        exact: true,
        includeHidden: true,
      }),
    });
  await openWithKeyboard(field.locator('.field-values summary'));
  await expect(field.getByText('Other values may occur.', { exact: true })).toBeVisible();
  await expect(
    field.getByText('Observed outside this reference list', { exact: true }),
  ).toBeVisible();
  await expect(field.getByText('Source documentation', { exact: true })).toBeVisible();
});

test('synthetic search matches alternate and exact dataset names and counts distinct datasets', async ({
  page,
}) => {
  await page.goto(watershedUrl);
  const search = page.getByRole('searchbox', { name: 'Search this catalog' });
  const results = page.getByRole('navigation', { name: 'Datasets' });
  await expect(search).toHaveAccessibleDescription(
    /supplied alternate names.*Field names and other catalogs are not searched/,
  );
  await search.fill('Example water measurements');
  await expect(results.getByRole('button')).toHaveCount(1);
  await expect(results.getByRole('button')).toContainText(
    'Instrument observations with their nested readings',
  );
  await expect(results.getByRole('button')).toContainText('Records connected here');
  await search.fill(stationsId);
  await expect(results.getByRole('button')).toHaveCount(1);
  await expect(results.getByRole('button')).toContainText('Synthetic station register');
  await search.fill('$number');
  await expect(results.getByText('No datasets match these filters.')).toBeVisible();
  await search.fill('');
  await page.getByText('More filters', { exact: true }).click();
  await expect(
    page.getByRole('combobox', { name: 'Topic', exact: true }).getByRole('option', {
      name: 'Water-quality examples (2)',
      exact: true,
    }),
  ).toHaveCount(1);
  const formats = page.getByRole('combobox', { name: 'Format of listed resources' });
  await expect(formats.getByRole('option', { name: 'JSON file (2)', exact: true })).toHaveCount(1);
  await formats.selectOption({ label: 'JSON file (2)' });
  await expect(results.getByRole('button')).toHaveCount(2);
});

test('the synthetic guide keeps its scope and links to the exact dataset and catalog copy', async ({
  page,
}) => {
  const dataCalls: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/(read|query|evidence)(?:\?|$)/.test(request.url())) dataCalls.push(request.url());
  });
  await page.goto(watershedUrl);
  await page
    .getByRole('button', {
      name: 'How can I connect example measurements to station names?',
      exact: true,
    })
    .click();
  const guide = section(page, 'Guides for using this catalog');
  await expect(
    guide.getByRole('heading', { name: 'Connect measurements to stations' }),
  ).toBeVisible();
  await expect(guide).toContainText('Publisher guidance · Example data');
  await expect(guide).toContainText(
    'Synthetic station labels; no real geographic coverage is claimed.',
  );
  const lookup = guide.getByRole('link', { name: 'Understand station names', exact: true });
  const target = new URL((await lookup.getAttribute('href'))!, page.url());
  expect(target.searchParams.get('dataset')).toBe(stationsId);
  expect(target.searchParams.get('snapshot')).toBe(
    new URL(page.url()).searchParams.get('snapshot'),
  );
  await lookup.click();
  await expect(
    page.getByRole('heading', { name: 'Synthetic station register', exact: true }),
  ).toBeVisible();
  expect(dataCalls).toEqual([]);
});

test('mobile keyboard opens nested details and copies exact item name and array path', async ({
  page,
}) => {
  const sink = await clipboard(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(watershedUrl);
  const dictionary = section(page, 'What each field means');
  await expect(dictionary.locator('.field-label', { hasText: 'Nested readings' })).toBeVisible();
  await openWithKeyboard(
    dictionary.locator('.field-row summary').filter({ hasText: 'Nested fields in readings' }),
  );
  await expect(dictionary.locator('.field-label', { hasText: 'Reading depth' })).toBeVisible();
  await expect(dictionary.getByText(/A measurement unit is not specified/)).toBeVisible();
  await openWithKeyboard(
    dictionary.locator('.field-row summary').filter({ hasText: 'Nested fields in flags' }),
  );
  const path = '["readings"][each]["flags"][each]';
  const nameButton = page.getByRole('button', {
    name: `Copy name for ${path}`,
    exact: true,
    includeHidden: true,
  });
  const item = dictionary.locator('li.field').filter({ has: nameButton }).last();
  await expect(item.locator('.field-label')).toHaveText('Reading label');
  await expect(item.locator('.field-native code')).toHaveText('flag');
  await expect(nameButton).not.toBeVisible();
  await openWithKeyboard(item.locator('.field-meta summary'));
  await nameButton.focus();
  await nameButton.press('Enter');
  await expect(item.getByRole('status')).toHaveText('Copied field name.');
  await expect(item.locator('.field-meta code').filter({ hasText: path })).toHaveText(path);
  const pathButton = item.getByRole('button', { name: `Copy path for ${path}`, exact: true });
  await page.keyboard.press('Tab');
  await expect(pathButton).toBeFocused();
  await pathButton.press('Enter');
  await expect(item.getByRole('status')).toHaveText('Copied field path.');
  expect(await sink.copied()).toEqual(['flag', path]);
  await sink.deny();
  await pathButton.press('Enter');
  await expect(item.getByRole('status')).toHaveText(
    'Clipboard access is unavailable. Select and copy the path shown here.',
  );
  await expect(item.locator('.field-meta code').filter({ hasText: path })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('fixture coverage, citation, caution, checks and history identify the selected version', async ({
  page,
}) => {
  const sink = await clipboard(page);
  await page.goto(watershedUrl);
  await expect(page.getByText('What this dataset is for', { exact: true })).toBeVisible();
  await expect(page.getByText('What one record represents', { exact: true })).toBeVisible();
  const coverage = section(page, 'Coverage');
  await expect(coverage).toContainText('Authored sample rows only');
  await expect(coverage).toContainText('3 rows observed.');
  await expect(coverage).toContainText('Expected population total 3 rows.');
  await expect(coverage).toContainText('Coverage: Complete');
  const dates = section(page, 'Dates and update expectations');
  await expect(dates.getByText('Nov 7, 2026', { exact: true })).toBeVisible();
  for (const label of ['Dataset definition', 'Selected data version']) {
    const scope = dates.locator('.context-scope').filter({
      has: page.getByRole('heading', { name: label, exact: true }),
    });
    await expect(
      scope
        .locator('dt', { hasText: /^Data update date$/ })
        .locator('..')
        .locator('dd'),
    ).toHaveText('Not supplied');
  }
  const credit = section(page, 'Credit, reuse terms and help');
  await expect(credit).toContainText('Publisher citation not supplied for this scope.');
  await expect(credit).toContainText('Data reuse terms not supplied for this scope.');
  await credit
    .getByRole('button', {
      name: 'Copy publisher citation for dataset definition with selected reference',
    })
    .click();
  await expect(credit.getByRole('status').filter({ hasText: 'Copied.' })).toBeVisible();
  const [copy] = await sink.copied();
  expect(copy).toContain(
    'DDK viewer example publisher. Watershed observations. Synthetic demonstration data.',
  );
  expect(copy).toContain(`Original publisher identifier\n${observationId}`);
  expect(copy).toContain(`"versionId": "${v1}"`);

  await page.getByRole('tab', { name: 'View data', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open records', exact: true })).toBeVisible();
  await expect(
    page.getByText('Nested readings are separate occurrences.', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Open questions · Selected resource', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Checks & sources' }).click();
  const checks = section(page, 'Checks for this data version');
  await expect(
    checks.getByText('Authored synthetic sample evidence only', { exact: true }),
  ).toBeVisible();
  await expect(checks.getByText('Passed', { exact: true })).toBeVisible();
  await expect(
    page
      .getByRole('tabpanel')
      .getByText(/Example source capture 1/)
      .first(),
  ).toBeVisible();
  await page.getByRole('tab', { name: 'History', exact: true }).click();
  const notes = section(page, 'Publisher change notes');
  await expect(notes).toContainText('Added human-readable field labels and example guidance.');
  await expect(notes.getByText('Nov 7, 2026', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Recorded processing events', exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get('version')).toBe(v1);
  const unavailable = new URL(page.url());
  unavailable.searchParams.set('version', `${v1}-unavailable`);
  await page.goto(unavailable.href);
  await expect(page.getByText('The linked version is unavailable', { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get('version')).toBe(`${v1}-unavailable`);
});

test('resource dates retain their exact scope without starting a record read', async ({
  page,
  request,
}) => {
  const snapshot: CatalogSnapshot = await (await request.get('/api/catalogs/watershed')).json();
  const assembly = snapshot.catalog.extensions![assemblyKey] as any;
  const profile = assembly.projectExtensions.find((row: any) => row.extensions[discoveryKey])
    .extensions[discoveryKey];
  const resource = snapshot.catalog.representations.find((row) => row.version === v1)!;
  const metadata = profile.records.find((row: any) => row.target.representationId === resource.id);
  metadata.dates = [
    { kind: 'retrieved', value: '2026-10-29' },
    { kind: 'metadataUpdated', value: '2026-11-02' },
  ];
  await page.route('**/api/catalogs/watershed', (route) => route.fulfill({ json: snapshot }));
  let reads = 0;
  page.on('request', (call) => {
    if (new URL(call.url()).pathname === '/api/read') reads++;
  });
  await page.goto(`${watershedUrl}&tab=Data`);
  await openWithKeyboard(
    page.getByText('Dates and update expectations for this selection', { exact: true }),
  );
  const selected = page
    .locator('.resource-dates .context-scope')
    .filter({ has: page.getByRole('heading', { name: 'Selected resource', exact: true }) });
  await expect(
    selected
      .locator('dt', { hasText: /^Source retrieval date$/ })
      .locator('..')
      .locator('time'),
  ).toHaveAttribute('datetime', '2026-10-29');
  await expect(
    selected
      .locator('dt', { hasText: /^Metadata update date$/ })
      .locator('..')
      .locator('time'),
  ).toHaveAttribute('datetime', '2026-11-02');
  await expect(
    selected
      .locator('dt', { hasText: /^Data update date$/ })
      .locator('..')
      .locator('dd'),
  ).toHaveText('Not supplied');
  await expect(page.getByRole('button', { name: 'Open records', exact: true })).toBeVisible();
  expect(reads).toBe(0);
});

test('malformed publisher metadata is refused while the same fixture catalog remains usable', async ({
  page,
  request,
}) => {
  const response = await request.get('/api/catalogs/watershed');
  expect(response.ok()).toBeTruthy();
  const snapshot: CatalogSnapshot = await response.json();
  const assembly = snapshot.catalog.extensions![assemblyKey] as {
    projectExtensions: { extensions: Record<string, unknown> }[];
  };
  const project = assembly.projectExtensions.find(({ extensions }) =>
    Object.hasOwn(extensions, discoveryKey),
  )!;
  project.extensions[discoveryKey] = { schemaVersion: 1, records: [{ target: 'wrong shape' }] };
  await page.route('**/api/catalogs/watershed', (route) => route.fulfill({ json: snapshot }));
  await page.goto(watershedUrl);
  await expect(
    page.getByText('Some publisher metadata could not be shown', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Watershed observations', exact: true }),
  ).toBeVisible();
  await expect(section(page, 'Coverage')).toContainText('Authored sample rows only');
  await expect(
    section(page, 'What each field means').locator('.field-label', { hasText: 'Nested readings' }),
  ).toBeVisible();
  await expect(page.getByText('Dataset list could not be loaded.')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'How can I connect example measurements to station names?' }),
  ).toHaveCount(0);
});
