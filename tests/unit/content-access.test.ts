import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { CatalogStore } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import { datasetRecordAccess, recordAccess } from '../../src/lib/content';
import { RequestError, requestMessage } from '../../src/lib/client';

test('record discovery requires both a connected dataset and an available version', async () => {
  const store = new CatalogStore(
    fixturePins.map((pin) => ({
      ...pin,
      directory: resolve('fixtures', pin.id),
      mode: 'fixture' as const,
    })),
  );
  const snapshot = structuredClone(await store.snapshot('watershed'));
  const dataset = snapshot.catalog.datasets[0];
  const version = snapshot.catalog.versions.find((row) => row.id.endsWith('observations:v2'))!;
  const source = structuredClone(snapshot.catalog);
  assert.equal(datasetRecordAccess(snapshot, dataset).state, 'available');
  assert.equal(recordAccess(snapshot, dataset).state, 'choose_version');
  snapshot.capabilities.readDatasetIds = [];
  assert.equal(recordAccess(snapshot, dataset, version).state, 'not_connected');
  assert.equal(datasetRecordAccess(snapshot, dataset).state, 'not_connected');
  snapshot.capabilities.readDatasetIds = [dataset.id];
  const availableFile = snapshot.catalog.representations.find((row) => row.version === version.id)!;
  snapshot.catalog.representations.unshift({
    ...availableFile,
    id: 'unavailable-alternative',
    availability: 'unavailable',
  });
  assert.equal(recordAccess(snapshot, dataset, version).state, 'available');
  assert.equal(
    recordAccess(snapshot, dataset, { ...version, retention: 'unknown' }).state,
    'unknown',
  );
  assert.equal(
    recordAccess(snapshot, dataset, { ...version, referenceDisclosure: 'withheld' }).state,
    'withheld',
  );
  assert.equal(
    recordAccess(snapshot, dataset, { ...version, retention: 'missing' }).state,
    'unavailable',
  );
  snapshot.catalog.representations = [];
  assert.equal(recordAccess(snapshot, dataset, version).state, 'unknown');
  snapshot.catalog.versions = [];
  assert.equal(datasetRecordAccess(snapshot, dataset).state, 'no_versions');
  // Discovery never manufactures a publisher selection or edits any version.
  assert.deepEqual(snapshot.catalog.selections, source.selections);
  assert.deepEqual(snapshot.catalog.currentSelection, source.currentSelection);
});

test('recovery messages preserve the diagnostic without promising unsupported actions', () => {
  const error = new RequestError('invalid_cursor', 'Cursor belongs to another process.', 409);
  assert.equal(error.code, 'invalid_cursor');
  assert.equal(error.status, 409);
  assert.equal(error.technicalMessage, 'Cursor belongs to another process.');
  assert.match(error.message, /first page/);
  assert.doesNotMatch(requestMessage('result_budget', 'Request fewer rows.'), /fewer|smaller/);
  assert.match(requestMessage('native_quota', 'Attempt quota is full.'), /operator/);
  assert.doesNotMatch(
    requestMessage('native_quota', 'Attempt quota is full.'),
    /Existing results remain available/,
  );
  assert.doesNotMatch(requestMessage('native_quota', 'Unsupported symbolic link.'), /limit/);
  assert.match(requestMessage('integrity_mismatch', 'Original diagnostic.'), /fingerprint/);
});
