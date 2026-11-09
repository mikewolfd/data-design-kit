import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolve } from 'node:path';
import { CatalogStore } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import { datasetIntroduction, datasetRecordAccess, formatLabel } from '../../src/lib/content';
import { discoveryItems, facetOptions, matchesFacets, missingFacet } from '../../src/lib/discovery';

async function snapshot() {
  const pin = fixturePins.find((row) => row.id === 'watershed')!;
  return structuredClone(
    await new CatalogStore([
      { ...pin, mode: 'fixture', directory: resolve('fixtures/watershed') },
    ]).snapshot(pin.id),
  );
}

test('discovery finds supplied alternate names and exact IDs without indexing fields or implying former names', async () => {
  const source = await snapshot();
  const rows = discoveryItems(source);
  assert.equal(rows[0].searchRank('Example water measurements'), 1);
  assert.equal(rows[0].searchRank(rows[0].dataset.id), 0);
  assert.equal(rows[0].searchRank('station_code'), -1);
  assert.ok(rows[0].alternateNames.every((name) => name.kind === 'alternate'));
  assert.equal(rows[0].access.state, 'available');
  assert.deepEqual(source.catalog.currentSelection, {
    authority: 'urn:ddk-viewer:fixture:watershed:publisher',
    purpose: 'fixture-demo',
  });
});

test('facets count distinct datasets across versions and retain unknown and active zero-count choices', async () => {
  const rows = discoveryItems(await snapshot());
  const formats = facetOptions(rows, {}, 'format');
  assert.equal(formats.find((option) => option.label === 'JSON file')?.count, 2);
  assert.equal(
    facetOptions(rows, {}, 'period').find((option) => option.value === missingFacet)?.count,
    2,
  );
  assert.equal(rows.filter((row) => matchesFacets(row, { period: missingFacet })).length, 2);
  assert.deepEqual(facetOptions([], { topic: 'value:Water-quality examples' }, 'topic'), [
    { value: 'value:Water-quality examples', label: 'Water-quality examples', count: 0 },
    { value: missingFacet, label: 'Unknown or not supplied', count: 0 },
  ]);
});

test('notification-only resources cannot advertise connected records in search or introduction', async () => {
  const source = await snapshot();
  const assembly = source.catalog.extensions!['urn:ddk:catalog:assembly'] as any;
  const guidance = assembly.projectExtensions[0].extensions['urn:ddk:publisher:discovery'];
  for (const row of guidance.records)
    if (row.target.kind === 'representation') row.resource.kind = 'notification';
  assert.notEqual(datasetRecordAccess(source, source.catalog.datasets[0]).state, 'available');
  assert.ok(discoveryItems(source).every((row) => row.access.state !== 'available'));
  assert.equal(formatLabel('text/csv', 'service'), 'CSV');
  assert.equal(formatLabel('application/json', 'table'), 'JSON');
  assert.equal(formatLabel('application/json', 'file'), 'JSON file');
});

test('introduction separates only explicitly marked publisher purpose and preserves original prose', async () => {
  const source = await snapshot();
  const dataset = source.catalog.datasets[0];
  source.definitions[dataset.alias].description =
    'One source observation.\n\nDefinition purpose: retained source interpretation.';
  const content = datasetIntroduction(source, dataset);
  assert.equal(content.purpose, 'Definition purpose: retained source interpretation.');
  assert.equal(
    content.description,
    'One source observation.\n\nDefinition purpose: retained source interpretation.',
  );
  source.definitions[dataset.alias].description =
    'Unstructured publisher purpose and scope stay intact.';
  assert.equal(
    datasetIntroduction(source, dataset).purpose,
    source.definitions[dataset.alias].description,
  );
});
