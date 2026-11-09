import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type {
  CatalogSnapshot,
  QueryRequest,
  QueryResult,
  ReadRequest,
} from '../../src/domain/types';
import { PUBLISHER_DISCOVERY, type PublisherRecord } from '../../src/features/publisher-metadata';
import {
  ResourceDetails,
  ResultContext,
  localReadExample,
  pageExport,
  queryExport,
  queryResultMatches,
  readResultMatches,
  resourceRecordAccess,
  resultCaption,
  resultReadme,
  sameReadRequest,
  type ResultContextProps,
} from '../../src/features/resource-details';
import { CatalogAccess } from '../../src/server/access';
import { CatalogStore } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';

async function setup() {
  const pin = fixturePins.find((row) => row.id === 'grants')!;
  const store = new CatalogStore([
    { ...pin, directory: resolve('fixtures/grants'), mode: 'fixture' },
  ]);
  const snapshot = await store.snapshot(pin.id);
  const dataset = snapshot.catalog.datasets[0];
  const version = snapshot.catalog.versions.find(
    (row) => row.dataset === dataset.alias && row.id.endsWith(':v1'),
  )!;
  const representation = snapshot.catalog.representations.find(
    (row) => row.version === version.id,
  )!;
  const request: ReadRequest = {
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    datasetId: dataset.id,
    versionId: version.id,
    representationId: representation.id,
    limit: 10,
    filter: { path: [{ field: 'program_code' }], equals: 'NEIGHBOR' },
  };
  const result = await new CatalogAccess(store).read(request);
  const context: ResultContextProps = { kind: 'page', snapshot, dataset, request, result };
  return { snapshot, dataset, version, representation, request, result, context };
}

function publisherResource(snapshot: CatalogSnapshot, record: PublisherRecord): CatalogSnapshot {
  const catalog = structuredClone(snapshot.catalog);
  const assembly = catalog.extensions!['urn:ddk:catalog:assembly'] as {
    projectExtensions: {
      project: typeof catalog.project;
      namespace: string;
      extensions: Record<string, unknown>;
    }[];
  };
  for (const row of assembly.projectExtensions) delete row.extensions[PUBLISHER_DISCOVERY];
  assembly.projectExtensions.push({
    project: catalog.project,
    namespace: '',
    extensions: { [PUBLISHER_DISCOVERY]: { schemaVersion: 1, records: [record] } },
  });
  return { ...snapshot, catalog };
}

test('resource facts stay bound to the exact representation and a notification is not readable', async () => {
  const { snapshot, dataset, version, representation } = await setup();
  const scoped = publisherResource(snapshot, {
    target: {
      kind: 'representation',
      datasetId: dataset.id,
      versionId: version.id,
      representationId: representation.id,
    },
    resource: {
      kind: 'notification',
      purpose: 'Announces data updates',
      byteSize: 0,
      destination: { kind: 'notification', url: 'https://publisher.example/updates' },
    },
    coverage: { period: { start: '2026-01-01', end: '2026-01-31' } },
    dates: [{ kind: 'dataUpdated', value: '2026-02-01' }],
    terms: [{ label: 'Notice reuse terms', scope: 'data' }],
  });
  assert.equal(resourceRecordAccess(scoped, dataset, version, representation), 'not_records');
  const view = renderToStaticMarkup(
    createElement(ResourceDetails, { snapshot: scoped, dataset, version }),
  );
  assert.match(view, /Notification service/);
  assert.match(view, /Announces data updates/);
  assert.match(view, /0 bytes/);
  assert.match(view, /2026-01-01 to 2026-01-31/);
  assert.match(view, /2026-02-01/);
  assert.match(view, /Notice reuse terms/);
  assert.match(view, /Open notification service · publisher\.example/);
  assert.doesNotMatch(view, /Download|A reader is connected here/);
  const otherVersion = snapshot.catalog.versions.find(
    (row) => row.dataset === dataset.alias && row.id.endsWith(':v2'),
  )!;
  const other = renderToStaticMarkup(
    createElement(ResourceDetails, { snapshot: scoped, dataset, version: otherVersion }),
  );
  assert.match(other, /Size not supplied/);
  assert.doesNotMatch(other, /publisher\.example|Notice reuse terms|2026-01-31/);
});

test('availability and local record capability are independent; withheld and unsafe destinations are inert', async () => {
  const { snapshot, dataset, version, representation } = await setup();
  const noReader = { ...snapshot, capabilities: { read: true, query: false, readDatasetIds: [] } };
  assert.equal(resourceRecordAccess(noReader, dataset, version, representation), 'not_connected');
  assert.equal(
    resourceRecordAccess(snapshot, dataset, version, { ...representation, kind: 'service' }),
    'available',
  );
  assert.equal(
    resourceRecordAccess(snapshot, dataset, version, {
      ...representation,
      availability: 'unknown',
    }),
    'unknown',
  );
  assert.equal(
    resourceRecordAccess(
      snapshot,
      dataset,
      { ...version, referenceDisclosure: 'withheld' },
      representation,
    ),
    'withheld',
  );
  const scoped = publisherResource(snapshot, {
    target: {
      kind: 'representation',
      datasetId: dataset.id,
      versionId: version.id,
      representationId: representation.id,
    },
    resource: { destination: { kind: 'directFile', url: 'https://publisher.example/file' } },
  });
  const withheld = renderToStaticMarkup(
    createElement(ResourceDetails, {
      snapshot: scoped,
      dataset,
      version: { ...version, referenceDisclosure: 'withheld' },
    }),
  );
  assert.doesNotMatch(withheld, /publisher\.example/);
  const unsafe = structuredClone(snapshot);
  unsafe.catalog.representations.find((row) => row.id === representation.id)!.location =
    'https://someone:secret@publisher.example/file';
  const view = renderToStaticMarkup(
    createElement(ResourceDetails, { snapshot: unsafe, dataset, version }),
  );
  assert.doesNotMatch(view, /publisher\.example|secret/);
});

test('a page and README preserve exact filter, hidden fields and repeated values', async () => {
  const { snapshot, request, result, context } = await setup();
  assert.equal(result.status, 'ok');
  assert.equal(result.returned, 1);
  const artifact = pageExport(snapshot, request, result, ['id']);
  assert.equal(artifact.request.filter?.equals, 'NEIGHBOR');
  assert.deepEqual(artifact.display.columns, ['id']);
  assert.equal(artifact.result.rows[0].program_code, 'NEIGHBOR');
  assert.equal(
    JSON.stringify(artifact.result.rows[0].amount),
    '{"$number":"12345678901234567890.12345678"}',
  );
  assert.match(JSON.stringify(artifact.result.rows[0].payments), /"scheduled","scheduled"/);
  assert.match(resultCaption(context)!, /Public-service grants.+JSON file.+1 record on this page/);
  const readme = resultReadme(context, 'http://127.0.0.1:4322')!;
  assert.match(readme, /Synthetic example/);
  assert.match(readme, /program_code = "NEIGHBOR"/);
  assert.match(readme, /10 requested. 1 matching record/);
  assert.match(readme, /http:\/\/127\.0\.0\.1:4322\/api\/read/);
  assert.match(readme, /defaults to 25 rows and accepts 1–100 rows/);
  assert.match(readme, /uses no API key/);
  assert.equal(
    localReadExample(
      snapshot,
      { ...request, cursor: 'only-this-process' },
      'http://127.0.0.1:4322',
    ),
    undefined,
  );
  assert.equal(localReadExample(snapshot, request, 'https://publisher.example'), undefined);
  assert.equal(localReadExample(snapshot, request, 'http://user@localhost'), undefined);
});

test('mismatched or refused results have no success count, and unknown continuation remains visible', async () => {
  const { snapshot, request, result, context } = await setup();
  assert.equal(sameReadRequest(request, { ...request }), true);
  assert.equal(sameReadRequest(request, { ...request, cursor: 'changed' }), false);
  assert.equal(
    sameReadRequest(request, { ...request, filter: { ...request.filter!, equals: 'LIBRARY' } }),
    false,
  );
  assert.throws(() => pageExport(snapshot, { ...request, versionId: 'different' }, result));
  assert.equal(readResultMatches(snapshot, request, { ...result, binding: undefined! }), false);
  assert.equal(
    readResultMatches(snapshot, request, { ...result, returned: result.returned + 1 }),
    false,
  );
  const refused = { ...result, status: 'refused' as const, returned: 0, rows: [] };
  assert.throws(() => pageExport(snapshot, request, refused));
  assert.equal(resultCaption({ ...context, result: refused }), undefined);
  const empty = {
    ...result,
    rows: [],
    returned: 0,
    total: undefined,
    continuation: 'unknown' as const,
  };
  const view = renderToStaticMarkup(createElement(ResultContext, { ...context, result: empty }));
  assert.match(view, /0 records/);
  assert.match(view, /Whether more matching records are available is unknown/);
  assert.doesNotMatch(view, /0 matching records/);
});

test('a query export binds recipe, input resource, exact parameters and result scope', async () => {
  const { snapshot, dataset, request: read, result: page } = await setup();
  const recipe = snapshot.catalog.recipes[0];
  const releaseId = 'urn:ddk-viewer:fixture:grants:release:1';
  const request: QueryRequest = {
    catalogId: read.catalogId,
    catalogSha256: read.catalogSha256,
    recipeId: recipe.id,
    limit: 25,
    releaseId,
    bindings: { awards: page.binding },
    parameters: { amount: { $number: '0.00000001' } },
  };
  const result: QueryResult = {
    status: 'ok',
    rows: page.rows,
    returned: page.returned,
    columns: page.columns,
    transport: page.transport,
    continuation: 'more',
    bindings: { awards: { ...page.binding, releaseId } },
  };
  assert.equal(queryResultMatches(snapshot, request, { ...result, bindings: undefined! }), false);
  assert.equal(
    queryResultMatches(snapshot, request, { ...result, returned: result.returned + 1 }),
    false,
  );
  const exported = queryExport(snapshot, request, result);
  assert.match(exported.scope, /Up to 25 returned query rows/);
  assert.deepEqual(exported.request.parameters.amount, { $number: '0.00000001' });
  assert.throws(() => queryExport(snapshot, { ...request, releaseId: 'wrong' }, result));
  const view = renderToStaticMarkup(
    createElement(ResultContext, { kind: 'query', snapshot, dataset, recipe, request, result }),
  );
  assert.match(view, /More matching records exist beyond this query result/);
  assert.match(view, /amount = 0\.00000001/);
  assert.doesNotMatch(view, /Repeat this bounded local read/);
});
