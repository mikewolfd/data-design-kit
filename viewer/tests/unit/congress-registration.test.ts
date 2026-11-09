import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { CatalogStore, sha256, ViewerError } from '../../src/server/catalog-store';
import {
  bindCongressInput,
  congressRegistration,
  congressSupportedDatasetIds,
  loadCongressInputs,
} from '../../src/server/congress-registration';

const store = () => new CatalogStore([congressRegistration], 'local');
const mismatch = (error: unknown) =>
  error instanceof ViewerError && error.code === 'binding_mismatch';
test('Congress LOCAL capture retains all 20 exact standard controls without payload copies', async () => {
  const capture = JSON.parse(
    await readFile(resolve(congressRegistration.directory, 'capture.json'), 'utf8'),
  );
  assert.equal(capture.files.length, 20);
  for (const entry of capture.files) {
    const bytes = await readFile(resolve(congressRegistration.directory, entry.path));
    assert.equal(sha256(bytes), entry.sha256);
    assert.equal(bytes.length, entry.bytes);
  }
  assert.ok(
    !(await readdir(congressRegistration.directory, { recursive: true })).some((name) =>
      name.endsWith('.parquet'),
    ),
  );
  const snapshot = await store().snapshot(congressRegistration.id);
  assert.equal(snapshot.catalog.datasets.length, 23);
  assert.equal(snapshot.catalog.versions.length, 17);
  assert.equal(snapshot.catalog.runs.length, 1);
  assert.equal(snapshot.catalog.checks.length, 160);
  assert.deepEqual(snapshot.catalog.releases, []);
  assert.deepEqual(snapshot.catalog.selections, []);
  assert.equal(snapshot.capabilities.read, false);
  assert.equal(snapshot.exampleData, 'authored');
  await assert.rejects(new CatalogStore([congressRegistration]).snapshot(congressRegistration.id));
});
test('Congress input indexes bind original owner files and keep native release as provenance', async () => {
  const snapshot = await store().snapshot(congressRegistration.id);
  const inputs = await loadCongressInputs(snapshot);
  assert.equal(inputs.data.size, 17);
  assert.deepEqual(new Set(congressSupportedDatasetIds(snapshot)), new Set(inputs.data.keys()));
  assert.equal(
    inputs.releaseId,
    '0ed378bde1c3dfbf218d1b3be9b067551dbc522f3b00bc854fe8b9f9a664b311',
  );
  for (const entry of inputs.data.values()) {
    assert.equal(bindCongressInput(inputs, snapshot, entry), entry);
    assert.equal(inputs.files[entry.name], entry.path);
    assert.ok(entry.path.includes('/Work/congressional-tech/'));
  }
  assert.ok(inputs.handoffRecord.sha256);
  assert.ok(inputs.originalManifestRecord.sha256);
});
test('Congress binding refuses another snapshot, version, dataset, location, SHA and standard release', async () => {
  const snapshot = await store().snapshot(congressRegistration.id);
  const inputs = await loadCongressInputs(snapshot);
  const entry = [...inputs.data.values()][0];
  assert.throws(
    () =>
      bindCongressInput(
        inputs,
        { ...snapshot, identity: { ...snapshot.identity, catalogSha256: '0'.repeat(64) } },
        entry,
      ),
    mismatch,
  );
  assert.throws(
    () => bindCongressInput(inputs, snapshot, { ...entry, versionId: 'other' }),
    mismatch,
  );
  assert.throws(
    () => bindCongressInput(inputs, snapshot, { ...entry, datasetId: 'other' }),
    mismatch,
  );
  assert.throws(
    () => bindCongressInput(inputs, snapshot, { ...entry, representationId: 'other' }),
    mismatch,
  );
  for (const releaseId of [inputs.releaseId, '', 'invented'])
    assert.throws(
      () => bindCongressInput(inputs, snapshot, { ...entry, releaseId }),
      (error) => error instanceof ViewerError && error.code === 'release_mismatch',
    );
  for (const change of ['location', 'sha256', 'scheme', 'authority']) {
    const changed = structuredClone(snapshot);
    const version = changed.catalog.versions.find((row) => row.id === entry.versionId)!;
    if (change === 'scheme' || change === 'authority') version.reference![change] = 'wrong';
    else (version.reference!.value as Record<string, unknown>)[change] = 'wrong';
    assert.throws(() => bindCongressInput(inputs, changed, entry), mismatch);
  }
  const changed = structuredClone(snapshot);
  changed.catalog.representations.find((row) => row.id === entry.representationId)!.location =
    'file:///wrong.parquet';
  assert.throws(() => bindCongressInput(inputs, changed, entry), mismatch);
});
test('Congress input loading obeys caller cancellation and one elapsed deadline', async () => {
  const snapshot = await store().snapshot(congressRegistration.id);
  await assert.rejects(
    loadCongressInputs(snapshot, { deadline: Date.now() - 1 }),
    (error) => error instanceof ViewerError && error.code === 'deadline',
  );
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    loadCongressInputs(snapshot, { signal: controller.signal }),
    (error) => error instanceof ViewerError && error.code === 'deadline',
  );
});
