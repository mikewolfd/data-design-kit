import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolve } from 'node:path';
import type { ExactObject, ReadRequest } from '../../src/domain/types';
import { exactStringify } from '../../src/domain/exact';
import { CatalogAccess, type OwnerReader } from '../../src/server/access';
import { CatalogStore, LIMITS, ViewerError } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';

async function setup() {
  const pin = fixturePins.find((row) => row.id === 'watershed')!;
  const store = new CatalogStore([
    { ...pin, directory: resolve('fixtures/watershed'), mode: 'application' },
  ]);
  const snapshot = await store.snapshot(pin.id);
  const dataset = snapshot.catalog.datasets[0];
  const version = snapshot.catalog.versions.find(
    (row) => row.dataset === dataset.alias && row.id.endsWith(':v2'),
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
  };
  return {
    async read(details?: unknown, rows: ExactObject[] = [], pageExtra: object = {}) {
      const reader: OwnerReader = {
        read: async ({ binding }) => {
          const page = {
            rows,
            rowPositions: rows.map((_, index) => index),
            total: rows.length,
            consumed: binding,
            record: { uri: 'urn:test:owner-record' },
            ...(details !== undefined ? { details: details as ExactObject } : {}),
          };
          return Object.defineProperties(page, Object.getOwnPropertyDescriptors(pageExtra));
        },
      };
      const access = new CatalogAccess(store, new Map([[snapshot.id, { reader }]]));
      return access.read(request);
    },
  };
}

const refusal = (expected: string) => (error: unknown) =>
  error instanceof ViewerError && error.code === expected;

test('owner inline details preserve exact facts, existing record, and consumed identity', async () => {
  const { read } = await setup();
  const details: ExactObject = {
    file: { uri: 'urn:test:data-file', sha256: 'a'.repeat(64) },
    rowIdentities: [{ value: { $number: '9007199254740993' } }],
    schema: { fields: ['identifier', 'amount'] },
    module: { name: 'example-reader', revision: 'retained-owner-revision' },
    exactAmount: { $number: '0.200000000000000001' },
    reservedSourceObject: { $object: [['$number', 'literal source field']] },
    unknown: null,
  };
  const result = await read(details, [{ identifier: { $number: '9007199254740993' } }]);
  assert.equal(result.status, 'ok');
  assert.equal(result.readEvidence?.kind, 'owner');
  assert.deepEqual(result.readEvidence?.consumed, result.binding);
  assert.deepEqual(result.readEvidence?.record, { uri: 'urn:test:owner-record' });
  assert.deepEqual(result.readEvidence?.details, details);
  assert.match(exactStringify(result.readEvidence?.details), /0\.200000000000000001/);
  assert.equal((await read()).readEvidence?.details, undefined);
  assert.deepEqual((await read({})).readEvidence?.details, {});
});

test('invalid inline detail values produce transport refusals', async () => {
  const { read } = await setup();
  for (const invalid of [
    null,
    [],
    'not an object',
    1,
    { $number: '12' },
    { rawNumber: 1 },
    { missing: undefined },
    { nonfinite: NaN },
    { integer: 12n },
    { callable: () => null },
    new Error('owner diagnostic'),
    { nested: new Error('diagnostic') },
    { date: new Date() },
    { map: new Map() },
    { invalidTag: { $number: 'not a number' } },
    {
      duplicateKeys: {
        $object: [
          ['key', 'a'],
          ['key', 'b'],
        ],
      },
    },
  ])
    await assert.rejects(read(invalid), refusal('adapter_transport'));
});

test('cyclic and throwing owner details refuse without leaking arbitrary errors', async () => {
  const { read } = await setup();
  const cyclic: any = {};
  cyclic.self = cyclic;
  await assert.rejects(read(cyclic), refusal('adapter_transport'));
  const getter = Object.defineProperty({}, 'value', {
    enumerable: true,
    get() {
      throw new Error('Unexpected detail getter');
    },
  });
  await assert.rejects(read(getter), refusal('adapter_transport'));
  const throwingPage = Object.defineProperty({}, 'details', {
    enumerable: true,
    get() {
      throw new Error('Unexpected page getter');
    },
  });
  await assert.rejects(read(undefined, [], throwingPage), refusal('adapter_transport'));
  const proxy = new Proxy(
    {},
    {
      getPrototypeOf() {
        throw new Error('Unexpected detail proxy');
      },
    },
  );
  await assert.rejects(read(proxy), refusal('adapter_transport'));
});

test('inline detail structures share row node/depth limits and overall response byte budget', async () => {
  const { read } = await setup();
  let deep: ExactObject = {};
  for (let depth = 0; depth < 50; depth++) deep = { child: deep };
  await assert.rejects(read(deep), refusal('adapter_budget'));
  await assert.rejects(read({ nodes: new Array(300_000).fill(null) }), refusal('adapter_budget'));
  await assert.rejects(
    read({ nodes: new Array(150_000).fill(null) }, [{ nodes: new Array(150_000).fill(null) }]),
    refusal('adapter_budget'),
  );
  await assert.rejects(read({ text: 'x'.repeat(1_000_001) }), refusal('adapter_budget'));
  await assert.rejects(read({ text: 'x'.repeat(LIMITS.resultBytes) }), refusal('result_budget'));
});
