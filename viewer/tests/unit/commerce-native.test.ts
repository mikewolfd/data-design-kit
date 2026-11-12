import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { CatalogAccess } from '../../src/server/access';
import { CatalogStore, sha256 } from '../../src/server/catalog-store';
import {
  commerceRegistration,
  commerceScope,
  createCommerceAdapter,
  DEFAULT_DOCSPEC_SHA256,
  readCommerceEvidence,
} from '../../src/server/commerce-native';
import type { ExactBinding } from '../../src/domain/types';

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

const retainedJourney = process.env.DDK_VIEWER_REPLAY_COMMERCE;
test(
  'retained owner journey matches the immutable source and evidence without fresh native acceptance',
  {
    skip:
      !retainedJourney &&
      'The retained Commerce journey is evidence kept outside the repository; set DDK_VIEWER_REPLAY_COMMERCE to it (see README, Evidence archive).',
  },
  async () => {
    const { snapshot, binding, version } = await context();
    const journey = JSON.parse(await readFile(resolve(retainedJourney!), 'utf8'));
    for (const key of ['catalogSha256', 'reportSha256', 'lockSha256'] as const)
      assert.equal(journey.catalog[key], snapshot.identity[key]);
    assert.equal(journey.sourceVersionId, version.id);
    const source = fileURLToPath((version.reference!.value as any).location);
    assert.equal(sha256(await readFile(source)), journey.sourceResultSha256);
    const expectedRows = [
      { amount_cents: { $number: '1700' }, order_day: '2026-01-05', region: 'north' },
      { amount_cents: { $number: '500' }, order_day: '2026-01-05', region: 'south' },
      { amount_cents: { $number: '250' }, order_day: '2026-01-06', region: 'north' },
    ];
    for (const result of [journey.read, journey.query]) {
      assert.equal(result.status, 'ok');
      assert.equal(result.returned, 3);
      assert.equal(result.total, 3);
      assert.equal(result.continuation, 'complete');
      assert.deepEqual(byGrain(result.rows), expectedRows);
    }
    assert.deepEqual(journey.read.binding, { ...binding, releaseId: journey.read.release.id });
    assert.deepEqual(journey.read.readEvidence.consumed, journey.read.binding);
    assert.equal(journey.read.readEvidence.kind, 'owner');
    const original = await readCommerceEvidence(snapshot.catalog.runs[0].record);
    assert.equal(original.scope, 'original-execution');
    const qualityEvidence = await readCommerceEvidence(journey.qualityEvidence);
    assert.equal(qualityEvidence.scope, 'refreshed-quality');
  },
);

test('DocSpecCatalogOwner commerce adapter reads paginated Parquet and executes checked-revenue recipe with provenance receipt', async () => {
  const { store, snapshot, binding, version } = await context();
  const adapter = await createCommerceAdapter();
  try {
    assert.equal(adapter.startup.engine?.id, 'docspec');
    assert.equal(adapter.startup.engine?.binarySha256, DEFAULT_DOCSPEC_SHA256);

    const access = new CatalogAccess(
      store,
      new Map([
        [
          snapshot.id,
          {
            ...adapter,
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
      releaseId: 'urn:example:commerce:release:copy-refresh-20261106',
    });
    assert.equal(read.status, 'ok');
    assert.equal(read.release?.id, 'urn:example:commerce:release:copy-refresh-20261106');
    assert.equal(read.release?.selected, undefined);
    assert.equal(read.rowOrder, 'source-row');
    assert.equal(read.total, 3);
    assert.equal(read.continuation, 'complete');
    assert.deepEqual(byGrain(read.rows), [
      { amount_cents: { $number: '1700' }, order_day: '2026-01-05', region: 'north' },
      { amount_cents: { $number: '500' }, order_day: '2026-01-05', region: 'south' },
      { amount_cents: { $number: '250' }, order_day: '2026-01-06', region: 'north' },
    ]);
    assert.equal(read.readEvidence?.kind, 'owner');
    assert.equal(read.readEvidence?.consumed.versionId, version.id);

    // Verify true slice pagination works (limit=2 -> cursor -> remaining 1 row)
    const firstPage = await access.read({
      ...binding,
      catalogId: snapshot.id,
      catalogSha256: snapshot.identity.catalogSha256,
      limit: 2,
    });
    assert.equal(firstPage.status, 'ok');
    assert.equal(firstPage.returned, 2);
    assert.equal(firstPage.total, 3);
    assert.equal(firstPage.continuation, 'more');
    assert.ok(firstPage.nextCursor);
    const secondPage = await access.read({
      ...binding,
      catalogId: snapshot.id,
      catalogSha256: snapshot.identity.catalogSha256,
      limit: 2,
      cursor: firstPage.nextCursor,
    });
    assert.equal(secondPage.status, 'ok');
    assert.equal(secondPage.returned, 1);
    assert.equal(secondPage.continuation, 'complete');
    assert.deepEqual(byGrain([...firstPage.rows, ...secondPage.rows]), byGrain(read.rows));

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
    assert.equal(result.execution?.engine?.id, 'docspec');
    assert.equal(result.execution?.engine?.binarySha256, DEFAULT_DOCSPEC_SHA256);
    assert.deepEqual(result.execution?.consumedBindings, { daily_revenue: binding });
    assert.equal(typeof result.execution?.elapsedMs, 'number');
    assert.deepEqual(byGrain(result.rows), byGrain(read.rows));

    assert.equal(sha256(await readFile(source)), sourceBefore);
    assert.equal(
      sha256(await readFile(`${commerceRegistration.directory}/catalog.ddk.json`)),
      beforeCatalog,
    );
  } finally {
    await adapter.close();
  }
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

test('tampered SQL, wrong version, unsupported scope and unallowlisted evidence refuse before native submission', async () => {
  const { snapshot, binding } = await context();
  const adapter = await createCommerceAdapter();
  try {
    const input = {
      snapshot,
      binding,
      offset: 0,
      limit: 3,
      deadline: Date.now() + 5000,
      signal: new AbortController().signal,
    };
    await assert.rejects(
      adapter.reader!.read({ ...input, binding: { ...binding, versionId: 'urn:wrong' } }),
      code('binding_mismatch'),
    );
    await assert.rejects(
      adapter.reader!.read({
        ...input,
        binding: { ...binding, datasetId: 'urn:example:commerce:dataset:customers' },
      }),
      code('native_scope_refused'),
    );
    await assert.rejects(
      adapter.query!.query({
        snapshot,
        recipeId: commerceScope.recipeIds[0],
        bindings: { daily_revenue: binding },
        parameters: {},
        sql: Buffer.from('SELECT * FROM a_different_file'),
        limit: 3,
        deadline: Date.now() + 5000,
        signal: input.signal,
      }),
      code('native_scope_refused'),
    );
    const original = snapshot.catalog.checks[0].record!;
    await assert.rejects(
      readCommerceEvidence({ ...original, sha256: '0'.repeat(64) }),
      code('evidence_refused'),
    );
    await assert.rejects(
      readCommerceEvidence({ uri: 'file:///etc/passwd', sha256: '0'.repeat(64) }),
      code('evidence_refused'),
    );
  } finally {
    await adapter.close();
  }
});
