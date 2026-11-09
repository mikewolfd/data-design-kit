import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolve } from 'node:path';
import { CatalogStore } from '../../src/server/catalog-store';
import { CatalogAccess, type OwnerAdapters } from '../../src/server/access';
import { fixturePins } from '../../src/server/fixture-pins';

async function setup() {
  const pin = fixturePins.find((p) => p.id === 'watershed')!;
  const store = new CatalogStore([
    { ...pin, directory: resolve('fixtures/watershed'), mode: 'application' },
  ]);
  const snapshot = await store.snapshot(pin.id);
  const dataset = snapshot.catalog.datasets[0];
  const version = snapshot.catalog.versions.find(
    (v) => v.dataset === dataset.alias && v.id.endsWith(':v2'),
  )!;
  const representation = snapshot.catalog.representations.find((r) => r.version === version.id)!;
  return {
    store,
    snapshot,
    binding: { datasetId: dataset.id, versionId: version.id, representationId: representation.id },
  };
}

test('owner capability scope refuses unsupported dataset and recipe before dispatch', async () => {
  const { store, snapshot, binding } = await setup();
  let calls = 0;
  const owner: OwnerAdapters = {
    reader: {
      supportedDatasetIds: [],
      description: 'Only explicitly supported inputs.',
      read: async () => {
        calls++;
        throw new Error('Unexpected owner read');
      },
    },
    query: {
      supportedRecipeIds: [],
      query: async () => {
        calls++;
        throw new Error('Unexpected owner query');
      },
    },
  };
  const access = new CatalogAccess(store, new Map([[snapshot.id, owner]]));
  const capabilities = (await access.snapshot(snapshot.id)).capabilities;
  assert.deepEqual(capabilities.readDatasetIds, []);
  assert.deepEqual(capabilities.queryRecipeIds, []);
  const context = { catalogId: snapshot.id, catalogSha256: snapshot.identity.catalogSha256 };
  assert.equal((await access.read({ ...context, ...binding })).status, 'refused');
  assert.equal(
    (
      await access.query({
        ...context,
        recipeId: snapshot.catalog.recipes[0].id,
        bindings: {},
        parameters: {},
      })
    ).status,
    'refused',
  );
  assert.equal(calls, 0);
});

test('owner evidence retains exact identity and rejects stale catalogs or mismatched receipts', async () => {
  const { store, snapshot } = await setup();
  const record = { uri: 'urn:test:owner:evidence', sha256: 'a'.repeat(64) };
  let calls = 0,
    mismatch = false;
  const access = new CatalogAccess(
    store,
    new Map([
      [
        snapshot.id,
        {
          evidence: async ({ record: received, signal }) => {
            calls++;
            assert.equal(signal.aborted, false);
            return {
              record: mismatch ? { ...received, sha256: 'b'.repeat(64) } : received,
              document: { exact: { $number: '9007199254740993' } },
              scope: 'One exact retained owner record.',
            };
          },
        },
      ],
    ]),
  );
  assert.equal((await access.snapshot(snapshot.id)).capabilities.evidence, true);
  const request = {
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    record,
  };
  await assert.rejects(
    access.evidence({ ...request, catalogSha256: '0'.repeat(64) }),
    /exact selected catalog/,
  );
  assert.equal(calls, 0);
  assert.deepEqual((await access.evidence(request)).record, record);
  mismatch = true;
  await assert.rejects(access.evidence(request), /does not match the requested record/);
});

test('owner timeout preserves a submitted attempt without claiming input consumption', async () => {
  const { store, snapshot, binding } = await setup();
  const attempt = { uri: 'urn:test:owner:attempt', sha256: 'c'.repeat(64) };
  const access = new CatalogAccess(
    store,
    new Map([
      [
        snapshot.id,
        {
          reader: {
            read: async ({ onAttempt }) => {
              onAttempt?.(attempt);
              await new Promise((resolve) => setTimeout(resolve, 80));
              return { rows: [], rowPositions: [], total: 0, consumed: binding };
            },
          },
        },
      ],
    ]),
    { deadlineMs: 25 },
  );
  const result = await access.read({
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    ...binding,
  });
  assert.equal(result.status, 'unknown');
  assert.deepEqual(result.attempt, attempt);
  assert.equal(result.readEvidence, undefined);
});
