import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile, writeFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { encodeCongressValue, createCongressAdapter } from '../../src/server/congress-reader';
import { CatalogStore, sha256 } from '../../src/server/catalog-store';
import { CatalogAccess } from '../../src/server/access';
import {
  congressRegistration,
  congressSupportedDatasetIds,
  loadCongressInputs,
} from '../../src/server/congress-registration';
import { exactStringify } from '../../src/domain/exact';

const noMarkers = { isArchiveDateValue: () => false, isArchiveTimestampValue: () => false };
test('Congress configuration refuses omitted relative imports before executing owner code', async () => {
  await mkdir(resolve('work'), { recursive: true });
  const root = await mkdtemp(resolve('work/congress-module-test-'));
  try {
    const sources = {
      'apps/site/src/components/explorer/reader/archive.ts':
        "import './unlisted.ts'; export const openArchive = null;\n",
      'apps/site/scripts/archive-server.mjs': 'export const startArchiveServer = null;\n',
      'apps/site/package.json': '{}\n',
      'apps/site/package-lock.json': '{}\n',
    };
    const files = [];
    for (const [path, text] of Object.entries(sources)) {
      await mkdir(resolve(root, path, '..'), { recursive: true });
      await writeFile(resolve(root, path), text);
      files.push({ path, sha256: sha256(text) });
    }
    const configPath = resolve(root, 'config.json');
    const config = JSON.stringify({ root, files });
    await writeFile(configPath, config);
    await assert.rejects(
      createCongressAdapter({ configPath, configSha256: sha256(config), supportedDatasetIds: [] }),
      (error: any) => error.code === 'owner_module_unpinned',
    );
    await assert.rejects(
      createCongressAdapter({ configPath, configSha256: '0'.repeat(64), supportedDatasetIds: [] }),
      (error: any) => error.code === 'integrity_mismatch',
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
test('Congress transport preserves integers, negative zero, repeated nulls, binary and reserved source keys', () => {
  const source = {
    big: 9007199254740993n,
    negativeZero: -0,
    list: [null, [], null, 'same', 'same'],
    bytes: new Uint8Array([0, 128, 255]),
    sourceTags: { $number: 'literal source text', $object: ['literal'] },
    ordinaryDateStruct: { type: 'date', days: 42, extra: 'retained' },
  };
  const value = encodeCongressValue(source, noMarkers) as any;
  assert.deepEqual(value.big, { $number: '9007199254740993' });
  assert.deepEqual(value.negativeZero, { $number: '-0' });
  assert.deepEqual(value.list, source.list);
  assert.equal(value.bytes.value, 'AID/');
  assert.deepEqual(value.ordinaryDateStruct, {
    type: 'date',
    days: { $number: '42' },
    extra: 'retained',
  });
  assert.deepEqual(value.sourceTags.$object, [
    ['$number', 'literal source text'],
    ['$object', ['literal']],
  ]);
  assert.match(exactStringify(value), /9007199254740993/);
});
test('Congress transport uses owner temporal markers and preserves submillisecond units', () => {
  const timestamp = { type: 'timestamp', unit: 'ns', value: 1762452000000000001n };
  const date = { type: 'date', days: -719162 };
  const owner = {
    isArchiveDateValue: (value: unknown) => value === date,
    isArchiveTimestampValue: (value: unknown) => value === timestamp,
  };
  assert.deepEqual(encodeCongressValue([date, timestamp], owner), [
    { type: 'date', days: { $number: '-719162' } },
    { type: 'timestamp', unit: 'ns', value: { $number: '1762452000000000001' } },
  ]);
  for (const value of [NaN, Infinity, undefined])
    assert.throws(
      () => encodeCongressValue(value, noMarkers),
      (error: any) => error.code === 'owner_unsupported_type',
    );
});

const configPath = process.env.DDK_VIEWER_CONGRESS_OWNER_CONFIG;
const configSha256 = process.env.DDK_VIEWER_CONGRESS_OWNER_CONFIG_SHA256;
test(
  'configured Congress owner reads all retained materialized datasets with exact page evidence',
  {
    skip: !configPath || !configSha256,
  },
  async () => {
    const store = new CatalogStore([congressRegistration], 'local');
    const snapshot = await store.snapshot(congressRegistration.id);
    const inputs = await loadCongressInputs(snapshot);
    const adapter = await createCongressAdapter({
      configPath: configPath!,
      configSha256: configSha256!,
      supportedDatasetIds: congressSupportedDatasetIds(snapshot),
    });
    const access = new CatalogAccess(store, new Map([[congressRegistration.id, adapter]]));
    const admitted = await access.snapshot(congressRegistration.id);
    assert.equal(admitted.capabilities.read, true);
    assert.equal(admitted.capabilities.query, false);
    assert.deepEqual(admitted.catalog.releases, []);
    const results: any[] = [];
    for (const entry of inputs.data.values()) {
      const request = {
        catalogId: snapshot.id,
        catalogSha256: snapshot.identity.catalogSha256,
        datasetId: entry.datasetId,
        versionId: entry.versionId,
        representationId: entry.representationId,
        limit: 2,
      };
      let cursor: string | undefined;
      let position = 0;
      const rows: any[] = [];
      do {
        const page = await access.read({ ...request, ...(cursor ? { cursor } : {}) });
        assert.equal(page.status, 'ok', entry.name);
        assert.equal(page.rowOrder, 'source-row');
        assert.equal(page.total, entry.rows);
        assert.equal(page.release, undefined);
        assert.equal(page.readEvidence!.kind, 'owner');
        assert.deepEqual(page.readEvidence!.consumed, {
          datasetId: entry.datasetId,
          versionId: entry.versionId,
          representationId: entry.representationId,
        });
        const details = page.readEvidence!.details as any;
        assert.equal(details.releaseId, inputs.releaseId);
        assert.equal(details.file.sha256, entry.sha256);
        assert.equal(details.file.name, entry.name);
        assert.equal(details.ownerModule.configuration.sha256, configSha256);
        assert.ok(Array.isArray(details.schema));
        assert.deepEqual(
          page.rowPositions,
          page.rows.map((_, index) => position + index),
        );
        rows.push(...page.rows);
        position += page.returned;
        cursor = page.nextCursor;
        if (!cursor) assert.equal(page.continuation, 'complete');
      } while (cursor);
      assert.equal(rows.length, entry.rows);
      results.push({ name: entry.name, sha256: entry.sha256, rows: rows.length });
      if (entry.name === 'list.parquet') assert.equal(rows.length, 7);
      if (entry.name === 'detail.parquet') {
        assert.equal(rows.length, 7);
        assert.ok(rows.some((row) => Array.isArray(row.page_metadata)));
      }
      await assert.rejects(
        access.read({ ...request, versionId: 'wrong' }),
        (error: any) => error.code === 'binding_mismatch',
      );
      await assert.rejects(
        access.read({ ...request, releaseId: inputs.releaseId }),
        (error: any) => error.code === 'release_mismatch',
      );
      const filtered = await access.read({
        ...request,
        filter: { path: [{ field: 'key' }], equals: 'test' },
      });
      assert.equal(filtered.status, 'refused');
    }
    const controller = new AbortController();
    const reason = new Error('caller cancelled');
    controller.abort(reason);
    await assert.rejects(
      adapter.reader!.read({
        snapshot,
        binding: [...inputs.data.values()][0],
        offset: 0,
        limit: 1,
        deadline: Date.now() + 1000,
        signal: controller.signal,
      }),
      (error) => error === reason,
    );
    await mkdir(resolve('work/congress-owner-integration'), { recursive: true });
    await writeFile(
      resolve('work/congress-owner-integration/dataset-checks.json'),
      JSON.stringify(results, null, 2) + '\n',
    );
    const bytes = await readFile(configPath!);
    assert.equal(sha256(bytes), configSha256);
  },
);
