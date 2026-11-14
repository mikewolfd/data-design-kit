import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import type { CatalogSnapshot, ExactObject } from '../../src/domain/types';
import {
  publisherMetadata,
  PUBLISHER_DISCOVERY,
  type PublisherRowAction,
} from '../../src/features/publisher-metadata';
import {
  recordMetadata,
  resolveRowAction,
} from '../../src/features/publisher-metadata/row-actions';

function fixture() {
  const catalog = JSON.parse(
    readFileSync(new URL('../../fixtures/grants/catalog.ddk.json', import.meta.url), 'utf8'),
  );
  const assembly = catalog.extensions['urn:ddk:catalog:assembly'];
  for (const project of assembly.projectExtensions) delete project.extensions[PUBLISHER_DISCOVERY];
  const dataset = catalog.datasets[0];
  const version = catalog.versions.find(
    (entry: { dataset: string }) => entry.dataset === dataset.alias,
  );
  const resource = catalog.representations.find(
    (entry: { version: string }) => entry.version === version.id,
  );
  assembly.datasetDefinitions[dataset.alias].properties = [
    'key',
    'parent',
    'source_uri',
    'source_sha256',
    'source_version',
    'readable',
  ].map((name) => ({ name, logicalType: 'string' }));
  catalog.recipes.push({
    id: 'urn:test:lookup',
    inputs: { records: dataset.alias },
    relationships: [],
    parameters: {
      type: 'object',
      properties: { key: { type: 'string' }, parent: { type: 'string' } },
      required: ['key', 'parent'],
      additionalProperties: false,
    },
    sql: 'lookup.sql',
    dialect: 'datafusion',
    resultDataset: dataset.alias,
  });
  const binding = { datasetId: dataset.id, versionId: version.id, representationId: resource.id };
  const lookup: PublisherRowAction = {
    id: 'related',
    label: 'Find related record',
    kind: 'recipe',
    workflowId: 'lookup',
    parameters: { key: 'key', parent: 'parent' },
  };
  const original: PublisherRowAction = {
    id: 'original',
    label: 'Inspect original',
    kind: 'original',
    fields: { uri: 'source_uri', sha256: 'source_sha256', version: 'source_version' },
    sourceReference: { scheme: 'urn:test:source', uriPath: ['uri'], versionPath: ['version'] },
  };
  const extension = {
    schemaVersion: 1,
    workflows: [
      {
        id: 'lookup',
        title: 'Find records',
        summary: 'Fixture keys only.',
        recipeId: 'urn:test:lookup',
        bindings: { records: binding },
        defaults: { key: 'fixture-key', parent: 'fixture-parent' },
      },
    ],
    records: [
      {
        target: { kind: 'version', datasetId: dataset.id, versionId: version.id },
        readableFields: ['readable'],
        rowActions: [lookup, original],
      },
    ],
  };
  assembly.projectExtensions.push({
    project: catalog.project,
    namespace: '',
    extensions: { [PUBLISHER_DISCOVERY]: extension },
  });
  const digest = 'a'.repeat(64);
  catalog.sources.push({
    id: 'urn:test:original',
    outcome: 'retained',
    reference: {
      scheme: 'urn:test:source',
      value: { uri: 'https://example.test/record', version: 'native-v1' },
    },
    content: {
      scheme: 'urn:ddk:version:local-file-sha256',
      value: { location: 'file:///fixture/original.json', sha256: digest },
    },
  });
  const row: ExactObject = {
    key: 'K',
    parent: 'P',
    source_uri: 'https://example.test/record',
    source_version: 'native-v1',
    source_sha256: digest,
    readable: '<script>not executable</script>',
  };
  return {
    snapshot: { catalog, definitions: assembly.datasetDefinitions } as CatalogSnapshot,
    extension,
    binding,
    row,
    lookup,
    original,
  };
}

test('publisher tasks bind every exact input and version-scoped reading action', () => {
  const { snapshot, binding } = fixture();
  const metadata = publisherMetadata(snapshot);
  assert.deepEqual(metadata.refusals, []);
  assert.equal(metadata.workflows.length, 1);
  assert.equal(recordMetadata(snapshot, binding)?.rowActions?.length, 2);
  assert.equal(
    recordMetadata(snapshot, { ...binding, representationId: 'wrong-resource' }),
    undefined,
  );
});

test('malformed workflow and action bindings refuse the entire publisher extension', () => {
  const variants = [
    (x: ReturnType<typeof fixture>) => {
      x.extension.workflows[0].bindings.records.versionId = 'wrong-version';
    },
    (x: ReturnType<typeof fixture>) => {
      x.extension.workflows[0].bindings.records.representationId = 'wrong-resource';
    },
    (x: ReturnType<typeof fixture>) => {
      x.extension.workflows.push(x.extension.workflows[0]);
    },
    (x: ReturnType<typeof fixture>) => {
      x.extension.records[0].readableFields = ['missing'];
    },
    (x: ReturnType<typeof fixture>) => {
      x.extension.records[0].rowActions.push(x.lookup);
    },
    (x: ReturnType<typeof fixture>) => {
      if (x.lookup.kind === 'recipe') delete x.lookup.parameters.parent;
    },
    (x: ReturnType<typeof fixture>) => {
      if (x.lookup.kind === 'recipe') x.lookup.workflowId = 'missing';
    },
  ];
  for (const change of variants) {
    const item = fixture();
    change(item);
    const metadata = publisherMetadata(item.snapshot);
    assert.equal(metadata.refusals[0]?.code, 'malformed');
    assert.equal(metadata.workflows.length, 0);
    assert.equal(metadata.versions.size, 0);
  }
});

test('related lookup keeps every key and treats SQL-looking values as literal parameters', () => {
  const { snapshot, row, lookup } = fixture();
  const result = resolveRowAction(snapshot, { ...row, key: "' OR 1=1 --" }, lookup);
  assert.equal(result.kind, 'recipe');
  if (result.kind === 'recipe')
    assert.deepEqual(result.parameters, { key: "' OR 1=1 --", parent: 'P' });
  for (const missing of [undefined, null, '', '   ']) {
    const changed = { ...row, parent: missing } as ExactObject;
    assert.equal(resolveRowAction(snapshot, changed, lookup).kind, 'unavailable');
  }
});

test('an original requires one matching URI, digest, and native version', () => {
  const { snapshot, row, original } = fixture();
  const found = resolveRowAction(snapshot, row, original);
  assert.deepEqual(found, {
    kind: 'original',
    record: { uri: 'file:///fixture/original.json', sha256: 'a'.repeat(64) },
  });
  for (const field of ['source_uri', 'source_sha256', 'source_version'])
    assert.equal(
      resolveRowAction(snapshot, { ...row, [field]: 'changed' }, original).kind,
      'unavailable',
    );
  snapshot.catalog.sources.push({ ...snapshot.catalog.sources.at(-1)!, id: 'urn:test:duplicate' });
  const ambiguous = resolveRowAction(snapshot, row, original);
  assert.equal(ambiguous.kind, 'unavailable');
  if (ambiguous.kind === 'unavailable') assert.match(ambiguous.reason, /More than one/);
});
