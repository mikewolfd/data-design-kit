import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import type { Catalog, CatalogSnapshot, FieldPath } from '../../src/domain/types';
import {
  PUBLISHER_DISCOVERY,
  publisherMetadata,
  type PublisherTarget,
} from '../../src/features/publisher-metadata';

const ASSEMBLY = 'urn:ddk:catalog:assembly';
function snapshot(path: string): CatalogSnapshot {
  const catalog = JSON.parse(
    readFileSync(new URL(`../../fixtures/${path}/catalog.ddk.json`, import.meta.url), 'utf8'),
  );
  const assembly = catalog.extensions[ASSEMBLY];
  for (const row of assembly.projectExtensions) delete row.extensions[PUBLISHER_DISCOVERY];
  return { catalog, definitions: assembly.datasetDefinitions } as CatalogSnapshot;
}
function addExtension(snap: CatalogSnapshot, extension: unknown, namespace = '') {
  const assembly = snap.catalog.extensions![ASSEMBLY] as { projectExtensions: unknown[] };
  assembly.projectExtensions.push({
    project: snap.catalog.project,
    namespace,
    extensions: { [PUBLISHER_DISCOVERY]: extension },
  });
}
function datasetTarget(dataset: Catalog['datasets'][number]): PublisherTarget {
  return {
    kind: 'dataset',
    datasetId: dataset.id,
    definition: {
      contractId: dataset.definition.contractId,
      version: dataset.definition.version,
      object: dataset.definition.object,
      sourceSha256: dataset.definition.source.sha256,
    },
  };
}

test('retained public Spicy discovery resolves topics, publisher attribution and exact code occurrences', () => {
  const snap = snapshot('applications/spicy-regs');
  const result = publisherMetadata(snap);
  assert.equal(result, publisherMetadata(snap));
  assert.equal(result.datasets.size, 389);
  assert.deepEqual(result.refusals, []);
  const cftc = result.datasets.get('urn:spicy-regs:definition:current-cftc-comments');
  assert.equal(cftc?.subject, 'rulemaking');
  assert.equal(cftc?.observationDate, '2026-10-13');
  assert.equal(cftc?.declaredPublishers?.[0].id, 'cftc-comments');
  assert.equal(cftc?.retainedInputReason?.kind, 'maintained-native-output');
  const comments = result.datasets.get('urn:spicy-regs:definition:current-comments');
  assert.equal(comments?.declaredPublishers, undefined);
  assert.equal(comments?.documentedValues?.[0].observedOffList?.[0].value, 'Public Submission');
  assert.equal(result.guides.length, 0);
  const agenda = result.datasets.get('urn:spicy-regs:definition:current-unified-agenda');
  assert.ok(
    agenda?.documentedValues?.some(
      ({ path }) =>
        JSON.stringify(path) ===
        JSON.stringify([{ field: 'related_rins' }, { each: true }, { field: 'rin_relation' }]),
    ),
  );
});

test('Congress contextual metadata remains independent of local datasets and query capabilities', () => {
  for (const app of ['congress', 'congress-authored']) {
    const result = publisherMetadata(snapshot(`applications/${app}`));
    assert.deepEqual(result.refusals, []);
    assert.equal(result.datasets.size, 0);
    assert.equal(result.contextualRelations.length, 7);
    assert.deepEqual(result.contextualRelations[0].joins, [{ field: 'bill_id', table: 'bills' }]);
    assert.match(result.contextualRelations[0].limits, /latest action/);
  }
});

test('publisher v1 retains scoped names, explicit unknowns, and a guide with admitted record evidence', () => {
  const snap = snapshot('grants');
  const target = datasetTarget(snap.catalog.datasets[0]);
  const recipe = snap.catalog.recipes[0];
  const version = snap.catalog.versions.find(
    ({ dataset }) => dataset === snap.catalog.datasets[0].alias,
  )!;
  const representation = snap.catalog.representations.find((row) => row.version === version.id)!;
  const resourceTarget = {
    kind: 'representation',
    datasetId: snap.catalog.datasets[0].id,
    versionId: version.id,
    representationId: representation.id,
  };
  const guide = {
    id: 'fixture-guide',
    title: 'Find fixture awards',
    question: 'Which fixture shows awards?',
    summary: 'This guide describes the synthetic awards fixture.',
    author: { name: 'Fixture author' },
    reviewedOn: '2026-11-07',
    links: [{ label: 'Find awards', purpose: 'Inspect the synthetic award definitions', target }],
    evidence: [{ label: 'Award definition', record: snap.catalog.datasets[0].definition.source }],
  };
  addExtension(snap, {
    schemaVersion: 1,
    guides: [guide],
    records: [
      {
        target,
        alternateNames: [{ kind: 'former', name: 'Fixture awards' }],
        dates: [{ kind: 'metadataUpdated', value: '2026-11-07T10:42:00.123456-05:00' }],
        unknowns: [{ fact: 'dataUpdated', reason: 'The fixture records no update event.' }],
      },
      { target: { kind: 'recipe', recipeId: recipe.id }, reuse: guide.links },
      { target: resourceTarget, resource: { byteSize: 0, kind: 'data' } },
    ],
  });
  const result = publisherMetadata(snap);
  assert.deepEqual(result.refusals, []);
  assert.deepEqual(result.guides, [guide]);
  const data = result.datasets.get(snap.catalog.datasets[0].id);
  assert.equal(data?.alternateNames?.[0].name, 'Fixture awards');
  assert.equal(data?.unknowns?.[0].fact, 'dataUpdated');
  assert.equal(data?.dates?.[0].value, '2026-11-07T10:42:00.123456-05:00');
  assert.equal(result.representations.get(representation.id)?.resource?.byteSize, 0);
  assert.equal(result.recipes.get(recipe.id)?.reuse?.[0].label, 'Find awards');
});

test('v1 rejects unsafe links, unbound evidence, invalid dates, wrong resource bindings, and duplicate targets atomically', () => {
  const variations = [
    { support: [{ label: 'Unsafe', url: 'javascript:alert(0)' }] },
    { dates: [{ kind: 'retrieved', value: '2026-02-30' }] },
    {
      cautions: [
        {
          summary: 'No match',
          evidence: [{ label: 'No match', record: { uri: 'urn:unknown', sha256: 'a'.repeat(64) } }],
        },
      ],
    },
    { coverage: { period: { start: '2026-11-02', end: '2026-11-01' } } },
    { resource: { byteSize: 1 } },
  ];
  for (const fields of variations) {
    const snap = snapshot('grants');
    const target = datasetTarget(snap.catalog.datasets[0]);
    addExtension(snap, { schemaVersion: 1, records: [{ target, ...fields }] });
    const result = publisherMetadata(snap);
    assert.equal(result.refusals[0]?.code, 'malformed');
    assert.equal(result.datasets.size, 0);
    assert.equal(snap.catalog.datasets.length, 2);
  }
  const snap = snapshot('grants');
  const target = datasetTarget(snap.catalog.datasets[0]);
  addExtension(snap, { schemaVersion: 1, records: [{ target }, { target }] });
  assert.equal(publisherMetadata(snap).refusals[0]?.code, 'malformed');
  const wrong = snapshot('grants');
  const representation = wrong.catalog.representations.find(
    ({ version }) => version !== wrong.catalog.versions[0].id,
  )!;
  addExtension(wrong, {
    schemaVersion: 1,
    records: [
      {
        target: {
          kind: 'representation',
          datasetId: wrong.catalog.datasets[0].id,
          versionId: wrong.catalog.versions[0].id,
          representationId: representation.id,
        },
        resource: { byteSize: 1 },
      },
    ],
  });
  assert.equal(publisherMetadata(wrong).refusals[0]?.code, 'malformed');
});

test('v1 absent, imported, unsupported, and malformed publisher metadata remain distinct', () => {
  const noExtension = snapshot('grants');
  assert.deepEqual(publisherMetadata(noExtension).refusals, []);
  const imported = snapshot('grants');
  addExtension(imported, { schemaVersion: 2 }, 'imported');
  assert.deepEqual(publisherMetadata(imported).refusals, []);
  const unsupported = snapshot('grants');
  addExtension(unsupported, { schemaVersion: 2 });
  assert.equal(publisherMetadata(unsupported).refusals[0]?.code, 'unsupported_version');
  const malformed = snapshot('grants');
  addExtension(malformed, { schemaVersion: '1' });
  assert.equal(publisherMetadata(malformed).refusals[0]?.code, 'malformed');
});

test('prepared view requires one disclosed nonvirtual scalar field at the exact dataset definition', () => {
  const candidate = (field: FieldPath) => ({
    id: 'station-counts',
    question: 'How many returned observations refer to each station code?',
    kind: 'valueCounts',
    field,
  });
  const supplied = snapshot('watershed');
  const target = datasetTarget(supplied.catalog.datasets[0]);
  const preparedViews = [candidate([{ field: 'station_code' }])];
  addExtension(supplied, { schemaVersion: 1, records: [{ target, preparedViews }] });
  const result = publisherMetadata(supplied);
  assert.deepEqual(result.refusals, []);
  assert.deepEqual(
    result.datasets.get(supplied.catalog.datasets[0].id)?.preparedViews,
    preparedViews,
  );

  for (const field of ['missing', 'readings']) {
    const snap = snapshot('watershed');
    addExtension(snap, {
      schemaVersion: 1,
      records: [{ target, preparedViews: [candidate([{ field }])] }],
    });
    assert.equal(publisherMetadata(snap).refusals[0]?.code, 'malformed');
  }
  const virtual = snapshot('watershed');
  virtual.catalog.identities.push({
    dataset: virtual.catalog.datasets[0].alias,
    kind: 'key',
    scope: 'dataset_version',
    meaning: 'Synthetic virtual identifier control',
    fields: [{ path: [{ field: 'station_code' }], virtual: true, physicalType: 'string' }],
  });
  addExtension(virtual, { schemaVersion: 1, records: [{ target, preparedViews }] });
  assert.equal(publisherMetadata(virtual).refusals[0]?.code, 'malformed');
});
