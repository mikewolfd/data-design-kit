import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { CatalogAccess } from '../../src/server/access';
import { CatalogStore, sha256 } from '../../src/server/catalog-store';
import {
  commerceRegistration,
  commerceScope,
  createCommerceAdapter,
  readCommerceEvidence,
} from '../../src/server/commerce-native';
import type { ExactBinding, RecordRef } from '../../src/domain/types';

const code = (expected: string) => (error: any) => error?.code === expected;
const byGrain = (rows: unknown[]) =>
  (JSON.parse(JSON.stringify(rows)) as any[]).sort((a, b) =>
    `${a.order_day}\0${a.region}`.localeCompare(`${b.order_day}\0${b.region}`),
  );
async function context() {
  const store = new CatalogStore([commerceRegistration], 'local');
  const snapshot = await store.snapshot(commerceRegistration.id);
  const dataset = snapshot.catalog.datasets.find((row) => row.id === commerceScope.datasetIds[0])!;
  const version = snapshot.catalog.versions.find((row) => row.dataset === dataset.alias)!;
  const representation = snapshot.catalog.representations.find(
    (row) => row.version === version.id,
  )!;
  const binding: ExactBinding = {
    datasetId: dataset.id,
    versionId: version.id,
    representationId: representation.id,
  };
  return { store, snapshot, binding, version };
}

test('the genuine native catalog remains local and preserves unknown consumption coverage', async () => {
  await assert.rejects(
    new CatalogStore([commerceRegistration]).snapshot(commerceRegistration.id),
    code('audience_refused'),
  );
  const { snapshot } = await context();
  assert.equal(snapshot.catalog.audience, 'local');
  assert.equal(snapshot.catalog.datasets.length, 3);
  assert.equal(snapshot.catalog.checks.length, 13);
  assert.ok(snapshot.catalog.checks.every((check) => check.status === 'passed'));
  assert.equal(snapshot.catalog.runs[0].inputCoverage.status, 'unknown');
  assert.equal(snapshot.catalog.runs[0].inputs.length, 0);
  const shared = snapshot.lock.files.filter((file) => file.path === 'datasets/commerce.odcs.json');
  assert.equal(shared.length, 3);
  assert.equal(new Set(shared.map((file) => file.sha256)).size, 1);
});

test('actual owner read and checked recipe retain the original result identity and actual native receipts', async () => {
  const { store, snapshot, binding, version } = await context();
  const adapter = createCommerceAdapter();
  let attempt: RecordRef | undefined;
  const access = new CatalogAccess(
    store,
    new Map([
      [
        snapshot.id,
        {
          ...adapter,
          reader: {
            ...adapter.reader,
            read: (input) =>
              adapter.reader.read({
                ...input,
                onAttempt: (record) => {
                  attempt = record;
                  input.onAttempt?.(record);
                },
              }),
          },
          evidence: ({ record, deadline, signal }) =>
            readCommerceEvidence(record, { deadline, signal }),
        },
      ],
    ]),
  );
  const source = fileURLToPath((version.reference!.value as any).location);
  const sourceBefore = sha256(await readFile(source));
  const beforeCatalog = sha256(
    await readFile(`${commerceRegistration.directory}/catalog.ddk.json`),
  );
  const read = await access.read({
    ...binding,
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    limit: 3,
    releaseId: 'urn:test:reference:release',
  });
  assert.equal(read.status, 'ok');
  assert.equal(read.release?.id, 'urn:test:reference:release');
  assert.equal(read.release?.selected, undefined);
  assert.equal(read.rowOrder, 'query-result');
  assert.equal(read.total, 3);
  assert.equal(read.continuation, 'complete');
  assert.deepEqual(byGrain(read.rows), [
    { amount_cents: { $number: '1700' }, order_day: '2026-01-05', region: 'north' },
    { amount_cents: { $number: '500' }, order_day: '2026-01-05', region: 'south' },
    { amount_cents: { $number: '250' }, order_day: '2026-01-06', region: 'north' },
  ]);
  assert.equal(read.readEvidence?.kind, 'owner');
  assert.equal(read.readEvidence?.consumed.versionId, version.id);
  assert.ok(attempt);
  const attempted = await readCommerceEvidence(attempt);
  assert.equal(attempted.scope, 'viewer-read-attempt');
  assert.match(
    (attempted.document as any).scope,
    /Native submission and consumption are not established/,
  );
  const readRecord = read.readEvidence!.record!;
  const evidence = await readCommerceEvidence(readRecord);
  const receipt = evidence.document as any;
  assert.equal(evidence.scope, 'new-consumer-read');
  assert.equal(receipt.status, 'succeeded');
  assert.equal(
    receipt.tool.distributionSha256,
    'b89b43e2d2bf17f8d87ff1d9a779e06c3a024f2777e2327a8f048c6cb00a2532',
  );
  assert.equal(receipt.inputs[0].sha256, sourceBefore);
  assert.equal(receipt.inputs[0].path, source);
  assert.equal(receipt.operation.selection, 'not_requested');
  assert.equal(receipt.operation.reconciliation, 'unsupported');
  assert.deepEqual(receipt.operation.outputs, []);
  assert.equal(
    receipt.result.queries[0].data.find(
      (row: any) => row.order_day === '2026-01-05' && row.region === 'north',
    ).amount_cents.$number,
    '1700',
  );
  const result = await access.query({
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    recipeId: commerceScope.recipeIds[0],
    bindings: { daily_revenue: binding },
    parameters: {},
    limit: 3,
  });
  assert.equal(result.status, 'ok');
  assert.equal(result.execution?.kind, 'owner');
  assert.equal(
    result.execution?.sqlSha256,
    'ca01fbd8506181c0f7a4766c61712613a32f8882007b2a941247b13703183670',
  );
  assert.deepEqual(byGrain(result.rows), byGrain(read.rows));
  assert.notEqual(result.execution?.record?.uri, readRecord.uri);
  const queryReceipt = (await readCommerceEvidence(result.execution!.record!)).document as any;
  assert.equal(queryReceipt.operation.execution, 'succeeded');
  assert.equal(queryReceipt.inputs[0].sha256, sourceBefore);
  assert.equal(sha256(await readFile(source)), sourceBefore);
  assert.equal(
    sha256(await readFile(`${commerceRegistration.directory}/catalog.ddk.json`)),
    beforeCatalog,
  );
  const restored = await promisify(execFile)(
    process.execPath,
    [
      '--import',
      'tsx',
      '--input-type=module',
      '-e',
      `import {readCommerceEvidence} from './src/server/commerce-native.ts'; process.stdout.write(JSON.stringify(await readCommerceEvidence(${JSON.stringify(readRecord)})));`,
    ],
    { cwd: process.cwd(), maxBuffer: 128 * 1024 },
  );
  const restoredEvidence = JSON.parse(restored.stdout);
  assert.equal(restoredEvidence.record.sha256, readRecord.sha256);
  assert.equal(
    restoredEvidence.document.operation.requestIdentity.value,
    receipt.operation.requestIdentity.value,
  );
});

test('conflicting bytes for one locked source path refuse while distinct same-file selections remain intact', async () => {
  await mkdir(resolve('work'), { recursive: true });
  const directory = await mkdtemp(resolve('work/native-lock-test-'));
  try {
    await cp(commerceRegistration.directory, directory, { recursive: true });
    const path = resolve(directory, 'catalog.lock.json');
    const lock = JSON.parse(await readFile(path, 'utf8'));
    const repeated = lock.files.filter((file: any) => file.path === 'datasets/commerce.odcs.json');
    repeated[1].sha256 = '0'.repeat(64);
    const bytes = JSON.stringify(lock);
    await writeFile(path, bytes);
    await assert.rejects(
      new CatalogStore(
        [{ ...commerceRegistration, directory, lockSha256: sha256(bytes) }],
        'local',
      ).snapshot(commerceRegistration.id),
      code('ambiguous_catalog'),
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('original quality evidence stays bounded-file qualification, separate from managed candidate acceptance', async () => {
  const { snapshot } = await context();
  const record = snapshot.catalog.checks[0].record!;
  const quality = (await readCommerceEvidence(record)).document as any;
  assert.equal(quality.status, 'passed');
  assert.equal(quality.checks.length, 13);
  assert.equal(quality.nativeRead, null);
  assert.equal(quality.fixtureComparison.status, 'passed');
  assert.equal(
    quality.target.files[0].sha256,
    'ff0efd8f35eb3b64e23a2f195cbfd2c9989173020b4681ae783bc0f2301ba4c6',
  );
});

test('tampered SQL, wrong version, unsupported scope and unordered pagination refuse before native submission', async () => {
  const { snapshot, binding } = await context();
  const adapter = createCommerceAdapter();
  let attempt: RecordRef | undefined;
  const input = {
    snapshot,
    binding,
    offset: 0,
    limit: 3,
    deadline: Date.now() + 5000,
    signal: new AbortController().signal,
    onAttempt: (record: RecordRef) => {
      attempt = record;
    },
  };
  await assert.rejects(adapter.reader.read({ ...input, limit: 2 }), code('native_page_refused'));
  await assert.rejects(adapter.reader.read({ ...input, offset: 1 }), code('native_page_refused'));
  await assert.rejects(
    adapter.reader.read({ ...input, binding: { ...binding, versionId: 'urn:wrong' } }),
    code('native_scope_refused'),
  );
  await assert.rejects(
    adapter.query.query({
      snapshot,
      recipeId: commerceScope.recipeIds[0],
      bindings: { daily_revenue: binding },
      parameters: {},
      sql: Buffer.from('SELECT * FROM a_different_file'),
      limit: 3,
      deadline: Date.now() + 5000,
      signal: input.signal,
      onAttempt: input.onAttempt,
    }),
    code('native_scope_refused'),
  );
  assert.equal(attempt, undefined);
  const original = snapshot.catalog.checks[0].record!;
  await assert.rejects(
    readCommerceEvidence({ ...original, sha256: '0'.repeat(64) }),
    code('evidence_refused'),
  );
  await assert.rejects(
    readCommerceEvidence({ uri: 'file:///etc/passwd', sha256: '0'.repeat(64) }),
    code('evidence_refused'),
  );
});
