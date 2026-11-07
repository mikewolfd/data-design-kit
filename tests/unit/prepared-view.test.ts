import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parseExactData } from '../../src/domain/exact';
import type { CatalogSnapshot, ExactObject, ReadRequest, ReadResult } from '../../src/domain/types';
import { PUBLISHER_DISCOVERY } from '../../src/features/publisher-metadata';
import { preparedCounts } from '../../src/features/prepared-view/counts';

function fixture(withView = true) {
  const catalog = JSON.parse(
    readFileSync(new URL('../../fixtures/watershed/catalog.ddk.json', import.meta.url), 'utf8'),
  );
  const assembly = catalog.extensions['urn:ddk:catalog:assembly'];
  const dataset = catalog.datasets.find(({ alias }: { alias: string }) => alias === 'observations');
  const version = catalog.versions.find(
    ({
      dataset: alias,
      retention,
      referenceDisclosure,
    }: {
      dataset: string;
      retention: string;
      referenceDisclosure?: string;
    }) => alias === dataset.alias && retention === 'present' && referenceDisclosure !== 'withheld',
  );
  const representation = catalog.representations.find(
    ({ version: id, availability }: { version: string; availability: string }) =>
      id === version.id && availability === 'available',
  );
  for (const row of assembly.projectExtensions) delete row.extensions[PUBLISHER_DISCOVERY];
  if (withView)
    assembly.projectExtensions.push({
      project: catalog.project,
      namespace: '',
      extensions: {
        [PUBLISHER_DISCOVERY]: {
          schemaVersion: 1,
          records: [
            {
              target: {
                kind: 'dataset',
                datasetId: dataset.id,
                definition: {
                  contractId: dataset.definition.contractId,
                  version: dataset.definition.version,
                  object: dataset.definition.object,
                  sourceSha256: dataset.definition.source.sha256,
                },
              },
              preparedViews: [
                {
                  id: 'counts-by-station',
                  kind: 'valueCounts',
                  question: 'How many returned observations refer to each station code?',
                  field: [{ field: 'station_code' }],
                },
              ],
            },
          ],
        },
      },
    });
  const snapshot = {
    id: 'watershed',
    catalog,
    identity: { catalogSha256: 'f'.repeat(64) },
    definitions: assembly.datasetDefinitions,
    capabilities: { read: true, query: false },
  } as CatalogSnapshot;
  const binding = {
    datasetId: dataset.id,
    versionId: version.id,
    representationId: representation.id,
  };
  const request: ReadRequest = {
    ...binding,
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
  };
  const result: ReadResult = {
    status: 'ok',
    binding,
    rows: [],
    columns: ['station_code'],
    returned: 0,
    transport: 'ddk-exact-json-v1',
    rowOrder: 'source-row',
    readEvidence: { kind: 'fixture', consumed: binding },
  };
  return { snapshot, dataset, request, result };
}

test('prepared counts reconcile the returned page and preserve missing, empty, null, and exact value types', () => {
  const { snapshot, dataset, request, result } = fixture();
  const rows = parseExactData(`[
    {"station_code":"NORTH"}, {"station_code":"NORTH"}, {},
    {"station_code":null}, {"station_code":""}, {"station_code":"Null"},
    {"station_code":9007199254740993}, {"station_code":9007199254740992},
    {"station_code":"9007199254740993"}, {"station_code":true}, {"station_code":"true"},
    {"station_code":["NORTH"]}, {"station_code":{"value":"NORTH"}},
    {"station_code":{"$number":"9007199254740993"}}, {"station_code":1}, {"station_code":1.0}
  ]`) as ExactObject[];
  const [counts] = preparedCounts(
    snapshot,
    dataset,
    { ...request, limit: rows.length },
    {
      ...result,
      rows,
      returned: rows.length,
      total: 48,
      continuation: 'more',
    },
  );
  assert.equal(counts.returned, rows.length);
  assert.equal(counts.excludedArrays, 1);
  assert.equal(counts.excludedObjects, 2);
  assert.equal(
    counts.categories.reduce((total, group) => total + group.count, 0) +
      counts.excludedArrays +
      counts.excludedObjects,
    rows.length,
  );
  assert.deepEqual(
    counts.categories.map(({ label, count }) => [label, count]),
    [
      ['"NORTH"', 2],
      ['Field absent', 1],
      ['Null', 1],
      ['Empty text', 1],
      ['"Null"', 1],
      ['9007199254740993', 1],
      ['9007199254740992', 1],
      ['"9007199254740993"', 1],
      ['true', 1],
      ['"true"', 1],
      ['1', 1],
      ['1.0', 1],
    ],
  );
});

test('prepared counts require a publisher declaration and an exact successful readable page', () => {
  const { snapshot, dataset, request, result } = fixture();
  assert.equal(preparedCounts(snapshot, dataset, request, result).length, 1);
  const wrongRequests = [
    { catalogId: 'grants' },
    { catalogSha256: '0'.repeat(64) },
    { datasetId: 'urn:other' },
    { versionId: 'urn:other' },
    { representationId: 'urn:other' },
    { releaseId: 'urn:other' },
  ];
  for (const patch of wrongRequests) {
    assert.deepEqual(preparedCounts(snapshot, dataset, { ...request, ...patch }, result), []);
  }
  const wrongResults: Partial<ReadResult>[] = [
    { status: 'unknown' },
    { status: 'refused' },
    { returned: 1 },
    { binding: { ...result.binding, versionId: 'urn:other' } },
    {
      readEvidence: {
        kind: 'fixture',
        consumed: { ...result.binding, representationId: 'urn:other' },
      },
    },
  ];
  for (const patch of wrongResults) {
    assert.deepEqual(preparedCounts(snapshot, dataset, request, { ...result, ...patch }), []);
  }
  assert.deepEqual(
    preparedCounts(
      {
        ...snapshot,
        capabilities: { ...snapshot.capabilities, read: false },
      },
      dataset,
      request,
      result,
    ),
    [],
  );
  assert.deepEqual(
    preparedCounts(
      {
        ...snapshot,
        capabilities: { ...snapshot.capabilities, readDatasetIds: ['urn:other'] },
      },
      dataset,
      request,
      result,
    ),
    [],
  );
  const absent = fixture(false);
  assert.deepEqual(
    preparedCounts(absent.snapshot, absent.dataset, absent.request, absent.result),
    [],
  );
});

test('prepared counts distinguish an empty returned page from pages with excluded values', () => {
  const { snapshot, dataset, request, result } = fixture();
  const [empty] = preparedCounts(snapshot, dataset, request, result);
  assert.equal(empty.returned, 0);
  assert.deepEqual(empty.categories, []);
  const [excluded] = preparedCounts(snapshot, dataset, request, {
    ...result,
    returned: 1,
    rows: [{ station_code: [] }],
  });
  assert.equal(excluded.excludedArrays, 1);
  assert.equal(excluded.returned, 1);
  assert.deepEqual(excluded.categories, []);
});
