import assert from 'node:assert/strict';
import test from 'node:test';
import { resolve } from 'node:path';
import { CatalogAccess, type OwnerSql } from '../../src/server/access';
import { CatalogStore, sha256 } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import type { QueryResult } from '../../src/domain/types';
import { parquetMemberInventorySha256 } from '../../src/server/docspec-owner';

test('directory identity preserves native UTF-8 ordering across Unicode planes', () => {
  assert.equal(parquetMemberInventorySha256([
    ['😀.parquet', 'b'.repeat(64), 456], ['\uE000.parquet', 'a'.repeat(64), 123],
  ]), 'dedc3551d4719a4b5ea3c89578544b71b783cf5ebc03d5fa69bea3c23150dc3c');
});

async function setup(owner?: OwnerSql, deadlineMs?: number) {
  const pin = fixturePins.find(row => row.id === 'watershed')!;
  const store = new CatalogStore([{ ...pin, directory: resolve('fixtures/watershed'), mode: 'application' }]);
  const snapshot = await store.snapshot(pin.id);
  const dataset = snapshot.catalog.datasets[0];
  const version = snapshot.catalog.versions.find(row => row.dataset === dataset.alias && row.id.endsWith(':v2'))!;
  const representation = snapshot.catalog.representations.find(row => row.version === version.id)!;
  const access = new CatalogAccess(store, new Map([[pin.id, owner ? { sql: owner } : {}]]), { deadlineMs });
  return { access, snapshot, request: { catalogId: pin.id, catalogSha256: snapshot.identity.catalogSha256,
    sql: 'SELECT id FROM records ORDER BY id', limit: 10,
    bindings: { records: { datasetId: dataset.id, versionId: version.id, representationId: representation.id } } } };
}

test('SQL requires registered capability and exact explicit bindings before dispatch', async () => {
  const { access, snapshot, request } = await setup();
  assert.equal(Boolean((await access.snapshot(snapshot.id)).capabilities.sql), false);
  assert.equal((await access.sql(request)).status, 'refused');
  await assert.rejects(access.sql({ ...request, catalogSha256: '0'.repeat(64) }), /exact selected catalog/);
  await assert.rejects(access.sql({ ...request, bindings: {} }), /Bind between/);
  await assert.rejects(access.sql({ ...request, bindings: { records: { ...request.bindings.records, versionId: 'absent' } } }), /same catalog fact/);
});

test('SQL preserves owner order and exact values and refuses forged receipts', async () => {
  let fault = '';
  const owner: OwnerSql = { query: async input => {
    const rows = [{ id: { $number: '9007199254740993' } }, { id: { $number: '2' } }];
    const result: QueryResult = { status: 'ok', bindings: input.bindings, rows, columns: ['id'],
      returned: rows.length, rowPositions: [0, 1], rowOrder: 'query-result', transport: 'ddk-exact-json-v1',
      execution: { kind: 'owner', recipeId: 'urn:ddk:ad-hoc-sql', sqlSha256: sha256(input.sql), inputs: ['records'], contextualRelationships: [] } };
    if (fault === 'sql') result.execution!.sqlSha256 = '0'.repeat(64);
    if (fault === 'binding') result.bindings = {};
    if (fault === 'refusal') result.status = 'refused';
    return result;
  } };
  const { access, snapshot, request } = await setup(owner);
  assert.equal((await access.snapshot(snapshot.id)).capabilities.sql, true);
  assert.deepEqual((await access.sql(request)).rows, [{ id: { $number: '9007199254740993' } }, { id: { $number: '2' } }]);
  for (fault of ['sql', 'binding', 'refusal']) await assert.rejects(access.sql(request), /receipt|selected inputs/);
});

test('SQL deadline preserves the original submitted attempt as unknown', async () => {
  const attempt = { uri: 'urn:test:sql-attempt', sha256: 'b'.repeat(64) };
  const { access, request } = await setup({ query: async input => {
    input.onAttempt?.(attempt);
    await new Promise<void>(resolve => input.signal.addEventListener('abort', () => resolve(), { once: true }));
    throw new Error('Owner stopped after cancellation');
  } }, 100);
  const answer = await access.sql(request);
  assert.equal(answer.status, 'unknown');
  assert.deepEqual(answer.attempt, attempt);
  assert.deepEqual(answer.rows, []);
});
