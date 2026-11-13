import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { QueryResult, SqlRequest } from '../../src/domain/types';
import { CatalogStore } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import {
  adHocSqlId,
  quotedSqlTable,
  sqlResultExport,
  sqlResultMatches,
} from '../../src/lib/sql-results';
import { QueryLab } from '../../src/components/QueryLab';
import {
  CapturedSources,
  originalSourceRecord,
} from '../../src/features/dataset-context/CapturedSources';
import { ProvenanceContext } from '../../src/features/dataset-context/Sources';

async function context() {
  const pin = fixturePins.find((item) => item.id === 'watershed')!;
  const snapshot = structuredClone(
    await new CatalogStore([
      { ...pin, mode: 'fixture', directory: resolve('fixtures/watershed') },
    ]).snapshot(pin.id),
  );
  const version = snapshot.catalog.versions[0];
  const dataset = snapshot.catalog.datasets.find((item) => item.alias === version.dataset)!;
  const resource = snapshot.catalog.representations.find((item) => item.version === version.id)!;
  const request: SqlRequest = {
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    sql: 'SELECT * FROM observations LIMIT 2',
    limit: 2,
    bindings: {
      observations: { datasetId: dataset.id, versionId: version.id, representationId: resource.id },
    },
  };
  const hash = createHash('sha256').update(request.sql).digest('hex');
  const result: QueryResult = {
    status: 'ok',
    columns: ['count'],
    rows: [{ count: { $number: '9007199254740993' } }],
    returned: 1,
    bindings: structuredClone(request.bindings),
    transport: 'ddk-exact-json-v1',
    execution: {
      kind: 'owner',
      recipeId: adHocSqlId,
      sqlSha256: hash,
      inputs: ['observations'],
      contextualRelationships: [],
    },
  };
  return { snapshot, dataset, version, request, result, hash };
}

test('SQL results bind original SQL and every explicit input; exports retain exact values and identities', async () => {
  const { snapshot, request, result, hash } = await context();
  assert.equal(sqlResultMatches(snapshot, request, result, hash), true);
  const exported = sqlResultExport(snapshot, request, result, hash);
  assert.equal(exported.request.sql, 'SELECT * FROM observations LIMIT 2');
  assert.deepEqual(exported.request.bindings, request.bindings);
  assert.deepEqual(exported.result.rows, [{ count: { $number: '9007199254740993' } }]);
  assert.deepEqual(exported.catalog, snapshot.identity);
  for (const wrong of [
    { ...result, execution: { ...result.execution!, sqlSha256: '0'.repeat(64) } },
    { ...result, execution: undefined },
    { ...result, bindings: {} },
    {
      ...result,
      bindings: {
        observations: { ...request.bindings.observations, versionId: 'another-version' },
      },
    },
    { ...result, bindings: { ...request.bindings, extra: request.bindings.observations } },
    { ...result, returned: 3 },
  ]) {
    assert.equal(sqlResultMatches(snapshot, request, wrong, hash), false);
    assert.throws(() => sqlResultExport(snapshot, request, wrong, hash), /Run this query again/);
  }
  assert.equal(quotedSqlTable('source"table'), '"source""table"');
});

test('empty, refused and unknown SQL outcomes stay distinct; unavailable catalogs have no SQL action', async () => {
  const { snapshot, request, result, hash } = await context();
  for (const status of ['ok', 'refused', 'unknown'] as const) {
    const outcome = { ...result, status, rows: [], returned: 0 };
    assert.equal(sqlResultMatches(snapshot, request, outcome, hash), true);
    if (status !== 'ok') assert.throws(() => sqlResultExport(snapshot, request, outcome, hash));
  }
  const unavailable = renderToStaticMarkup(createElement(QueryLab, { snapshot }));
  assert.match(unavailable, /Query lab is not connected/);
  assert.doesNotMatch(unavailable, /<textarea|Run SQL query/);
  snapshot.capabilities.sql = true;
  const connected = renderToStaticMarkup(createElement(QueryLab, { snapshot }));
  assert.match(connected, /Not included/);
  assert.match(connected, /0 tables selected/);
  assert.match(connected, /disabled=""[^>]*>Run SQL query/);
});

test('catalog source originals require the supported native scheme and digest; inventory does not imply selected-version lineage', async () => {
  const { snapshot, dataset, version } = await context();
  const content = {
    scheme: 'urn:ddk:version:local-file-sha256',
    authority: 'urn:test:publisher',
    value: { location: 'file:///retained/original.json', sha256: 'a'.repeat(64) },
  };
  assert.deepEqual(originalSourceRecord(content), {
    uri: 'file:///retained/original.json',
    sha256: 'a'.repeat(64),
  });
  for (const reference of [
    undefined,
    { ...content, scheme: 'urn:other' },
    { ...content, value: null },
    { ...content, value: { location: 'https://example.test/data', sha256: 'a'.repeat(64) } },
    { ...content, value: { location: 'file:///retained/original.json' } },
    { ...content, value: { ...content.value, sha256: 'invalid' } },
  ])
    assert.equal(originalSourceRecord(reference), undefined);
  snapshot.catalog.sources = [
    {
      id: 'urn:test:capture',
      reference: content,
      content,
      scope: 'One retained original',
      outcome: 'ok',
      record: { uri: 'urn:test:receipt' },
    },
  ];
  snapshot.capabilities.evidence = true;
  version.sources = [];
  const inventory = renderToStaticMarkup(createElement(CapturedSources, { snapshot }));
  assert.match(inventory, /Inspect retained original/);
  assert.match(
    inventory,
    /does not establish publisher-wide completeness or a link to the selected data version/,
  );
  const provenance = renderToStaticMarkup(
    createElement(ProvenanceContext, { snapshot, dataset, version }),
  );
  assert.match(provenance, /No source observations are linked to this version/);
});
