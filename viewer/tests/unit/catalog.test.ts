import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
  access as fileAccess,
} from 'node:fs/promises';
import { resolve, join } from 'node:path';
import {
  compareExactNumbers,
  exactObjectField,
  exactStringify,
  isEscapedObject,
  parseExactData,
  parseRequest,
} from '../../src/domain/exact';
import type { ExactBinding, QueryRequest, QueryResult, ReadRequest } from '../../src/domain/types';
import { CatalogAccess, type OwnerReader, type OwnerQuery } from '../../src/server/access';
import {
  CatalogStore,
  LIMITS,
  OUTPUT_SET,
  sha256,
  type CatalogRegistration,
} from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import { applicationRegistrations } from '../../src/server/registry';
import { body } from '../../src/server/http';

const fixtureRegistration = (id = 'watershed'): CatalogRegistration => ({
  ...fixturePins.find((row) => row.id === id)!,
  directory: resolve('fixtures', id),
  mode: 'fixture',
});
const code = (expected: string) => (error: any) => error?.code === expected;
async function context(registration = fixtureRegistration()) {
  const store = new CatalogStore([registration]),
    snapshot = await store.snapshot(registration.id),
    access = new CatalogAccess(store);
  const dataset = snapshot.catalog.datasets[0],
    version = snapshot.catalog.versions.find(
      (row) => row.dataset === dataset.alias && row.id.endsWith(':v2'),
    )!;
  const representation = snapshot.catalog.representations.find(
    (row) => row.version === version.id,
  )!;
  const binding: ExactBinding = {
    datasetId: dataset.id,
    versionId: version.id,
    representationId: representation.id,
  };
  const request: ReadRequest = {
    ...binding,
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    limit: 10,
  };
  const query: QueryRequest = {
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    recipeId: snapshot.catalog.recipes[0].id,
    bindings: { records: binding },
    parameters: { minimum_concentration: '2' },
  };
  return { store, snapshot, access, request, query, binding };
}
async function copied(
  action: (directory: string, registration: CatalogRegistration) => Promise<void>,
) {
  await mkdir(resolve('work'), { recursive: true });
  const directory = await mkdtemp(resolve('work', 'catalog-test-'));
  try {
    await cp(resolve('fixtures/watershed'), directory, { recursive: true });
    await action(directory, { ...fixtureRegistration(), directory });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}
async function repin(
  directory: string,
  mutate: (catalog: any, lock: any, report: any) => void,
): Promise<string> {
  const catalog = JSON.parse(await readFile(join(directory, 'catalog.ddk.json'), 'utf8'));
  const lock = JSON.parse(await readFile(join(directory, 'catalog.lock.json'), 'utf8'));
  const report = JSON.parse(await readFile(join(directory, 'catalog.report.json'), 'utf8'));
  mutate(catalog, lock, report);
  const reportBytes = JSON.stringify(report);
  await writeFile(join(directory, 'catalog.report.json'), reportBytes);
  for (const file of catalog.files)
    file.sha256 = sha256(await readFile(join(directory, file.path)));
  await writeFile(join(directory, 'catalog.ddk.json'), JSON.stringify(catalog));
  for (const file of lock.extensions[OUTPUT_SET])
    file.sha256 = sha256(await readFile(join(directory, file.path)));
  const bytes = JSON.stringify(lock);
  await writeFile(join(directory, 'catalog.lock.json'), bytes);
  return sha256(bytes);
}

test('exact transport preserves unsafe integers, decimal scale, lists, missing and reserved source objects', () => {
  const value = parseExactData(
    '{"id":9007199254740993,"decimal":0.100000000000000001,"scale":1.2500,"items":[null,[],["x","x"]],"nil":null,"empty":"","literal":{"$number":"source literal"},"escaped":{"$object":[["key",1]]},"__proto__":{"polluted":true},"constructor":"native field"}',
  ) as any;
  assert.deepEqual(value.id, { $number: '9007199254740993' });
  assert.deepEqual(value.decimal, { $number: '0.100000000000000001' });
  assert.deepEqual(value.scale, { $number: '1.2500' });
  assert.equal(isEscapedObject(value.literal), true);
  assert.equal(exactObjectField(value.literal, '$number'), 'source literal');
  const output = exactStringify(value, 0);
  assert.match(output, /"scale":1\.2500/);
  assert.match(output, /"literal":\{"\$number":"source literal"\}/);
  assert.equal(Object.hasOwn(value, 'missing'), false);
  assert.equal(Object.hasOwn(value, '__proto__'), true);
  assert.equal(({} as any).polluted, undefined);
  assert.equal(
    compareExactNumbers('12345678901234567890.12345678', '12345678901234567890.12345679'),
    -1,
  );
  assert.equal(compareExactNumbers('1.2500', '125e-2'), 0);
});

test('request parser refuses duplicate keys, prototype keys and unbounded exact numbers', () => {
  for (const input of [
    '{"a":1,"a":2}',
    '{"__proto__":{}}',
    '{"constructor":{}}',
    '{"prototype":{}}',
    '{"n":1e999999}',
    '{"n":{"$number":"NaN"}}',
  ])
    assert.throws(() => parseRequest(input));
  assert.deepEqual(
    parseRequest('{"limit":10,"minimum":{"$number":"0.100000000000000001"}}').minimum,
    { $number: '0.100000000000000001' },
  );
});

test('incomplete qualification is discoverable and retains unknown and not_run', async () => {
  const { store, snapshot } = await context();
  assert.equal((await store.list()).catalogs.length, 1);
  assert.equal(snapshot.report.decision, 'incomplete');
  assert.equal(
    snapshot.report.checks.find((row) => row.id === 'native-candidate')?.status,
    'unknown',
  );
  assert.equal(
    snapshot.report.checks.find((row) => row.id === 'remote-existence')?.status,
    'not_run',
  );
  assert.equal(snapshot.catalog.runs[0].inputCoverage.status, 'partial');
  assert.equal(snapshot.catalog.versions[0].sources[0], snapshot.catalog.sources[0].id);
});

test('reads preserve exact binding, physical positions, escaped rows, and signed cursor scope', async () => {
  const { access, request, snapshot } = await context();
  const first = await access.read(request);
  assert.deepEqual(first.rowPositions, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.deepEqual(exactObjectField(first.rows[0], 'id'), { $number: '9007199254740993' });
  assert.equal(first.total, 14);
  assert.ok(first.nextCursor);
  const second = await access.read({ ...request, cursor: first.nextCursor });
  assert.deepEqual(second.rowPositions, [10, 11, 12, 13]);
  assert.equal(second.nextCursor, undefined);
  assert.equal(isEscapedObject(second.rows[2]), true);
  assert.equal(exactObjectField(second.rows[2], '$number'), 'source literal');
  assert.equal(second.readEvidence?.consumed.versionId, request.versionId);
  await assert.rejects(
    access.read({ ...request, cursor: first.nextCursor, limit: 5 }),
    code('cursor_mismatch'),
  );
  await assert.rejects(
    access.read({ ...request, cursor: first.nextCursor + 'tamper' }),
    code('invalid_cursor'),
  );
  await assert.rejects(
    access.read({ ...request, catalogSha256: '0'.repeat(64) }),
    code('catalog_mismatch'),
  );
  await assert.rejects(
    access.read({
      ...request,
      representationId: snapshot.catalog.representations.find(
        (row) => row.version !== request.versionId,
      )!.id,
    }),
    code('binding_mismatch'),
  );
  await assert.rejects(access.read({ ...request, limit: 101 }), code('page_budget'));
});

test('withheld and unavailable data refuse while unknown availability remains unknown', async () => {
  const { access, request, snapshot } = await context();
  for (const [suffix, expected] of [
    ['withheld', 'refused'],
    ['unresolved', 'unknown'],
  ]) {
    const version = snapshot.catalog.versions.find((row) => row.id.endsWith(':' + suffix))!;
    const representation = snapshot.catalog.representations.find(
      (row) => row.version === version.id,
    )!;
    const result = await access.read({
      ...request,
      versionId: version.id,
      representationId: representation.id,
    });
    assert.equal(result.status, expected);
    assert.equal(result.rows.length, 0);
  }
});

test('exact filters preserve nested repetitions, null, empty, missing and typed numeric comparisons', async () => {
  const { access, request } = await context();
  const matches = await access.read({
    ...request,
    filter: {
      path: [{ field: 'readings' }, { each: true }, { field: 'flags' }, { each: true }],
      equals: 'repeat',
    },
  });
  assert.deepEqual(matches.rowPositions, [4]);
  const nil = await access.read({
    ...request,
    filter: { path: [{ field: 'note' }], equals: null },
  });
  assert.deepEqual(nil.rowPositions, [2]);
  const empty = await access.read({
    ...request,
    filter: { path: [{ field: 'readings' }], equals: [] },
  });
  assert.deepEqual(empty.rowPositions, [1, 3, 5, 8, 9, 11, 12]);
});

test('registered fixture recipe compares exact decimals and contextual links add no execution inputs', async () => {
  await copied(async (directory, registration) => {
    // A contextual lookup must never cause a lookup payload read.
    await rm(join(directory, 'data/stations-v2.json'));
    const { access, query } = await context(registration);
    const result = await access.query(query);
    assert.deepEqual(result.rowPositions, [1, 12, 13]);
    assert.deepEqual(
      result.rows.map((row) => exactObjectField(row, 'id')),
      [
        { $number: '9007199254740999' },
        { $number: '9007199254741021' },
        { $number: '9007199254741023' },
      ],
    );
    assert.deepEqual(result.execution?.inputs, ['records']);
    assert.equal(result.execution?.contextualRelationships.length, 1);
    await assert.rejects(
      access.query({ ...query, parameters: { minimum_concentration: 2.1 } }),
      code('invalid_parameters'),
    );
    await assert.rejects(
      access.query({ ...query, parameters: { minimum_concentration: '2', undeclared: 'x' } }),
      code('invalid_parameters'),
    );
    await assert.rejects(
      access.query({ ...query, bindings: { ...query.bindings, context: query.bindings.records } }),
      code('recipe_inputs'),
    );
  });
});

test('declared same_release dependencies require exact complete common membership', async () => {
  await copied(async (directory, registration) => {
    const pin = await repin(directory, (catalog) => {
      catalog.recipes[0].relationships = [catalog.relationships[0].id];
    });
    const { access, query, snapshot } = await context({ ...registration, lockSha256: pin });
    await assert.rejects(access.query(query), code('invalid_request'));
    await assert.rejects(
      access.query({ ...query, releaseId: snapshot.catalog.releases[0].id }),
      code('release_mismatch'),
    );
    const result = await access.query({ ...query, releaseId: snapshot.catalog.releases[1].id });
    assert.equal(result.status, 'ok');
    assert.equal(result.bindings.records.releaseId, snapshot.catalog.releases[1].id);
  });
});

test('required external relationships remain unknown before SQL reads or owner dispatch', async () => {
  await copied(async (directory, registration) => {
    const pin = await repin(directory, (catalog) => {
      catalog.recipes[0].relationships = [catalog.relationships[1].id];
    });
    await rm(join(directory, 'recipes/observations-minimum.sql'));
    const { store, query } = await context({
      ...registration,
      lockSha256: pin,
      mode: 'application',
    });
    let dispatched = false;
    const owner: OwnerQuery = {
      query: async () => {
        dispatched = true;
        throw new Error('Must not dispatch');
      },
    };
    const access = new CatalogAccess(store, new Map([[registration.id, { query: owner }]]));
    const result = await access.query(query);
    assert.equal(result.status, 'unknown');
    assert.match(result.reason!, /project-specific scope resolver/);
    assert.equal(dispatched, false);
    assert.equal(result.rows.length, 0);
  });
});

test('wrong releases refuse and historical exact versions remain readable with their lookup version', async () => {
  const { access, request, snapshot } = await context();
  await assert.rejects(
    access.read({ ...request, releaseId: snapshot.catalog.releases[0].id }),
    code('release_mismatch'),
  );
  const version = snapshot.catalog.versions.find(
    (row) => row.dataset === 'stations' && row.id.endsWith(':v1'),
  )!;
  const result = await access.read({
    ...request,
    datasetId: snapshot.catalog.datasets[1].id,
    versionId: version.id,
    representationId: snapshot.catalog.representations.find((row) => row.version === version.id)!
      .id,
    releaseId: snapshot.catalog.releases[0].id,
  });
  assert.equal(result.release?.selected, false);
  assert.match(String(result.rows[0].name), /historical register/);
});

test('companion tampering fails integrity and repinned changed SQL still has no executable registration', async () => {
  await copied(async (directory, registration) => {
    await writeFile(
      join(directory, 'recipes/observations-minimum.sql'),
      'SELECT * FROM arbitrary_remote;\n',
    );
    const store = new CatalogStore([registration]);
    const snapshot = await store.snapshot(registration.id);
    assert.equal(snapshot.report.decision, 'incomplete');
    await assert.rejects(
      store.companion(
        snapshot.id,
        snapshot.identity.catalogSha256,
        snapshot.catalog.recipes[0].sql,
      ),
      code('integrity_mismatch'),
    );
    const pin = await repin(directory, () => {});
    const { access, query } = await context({ ...registration, lockSha256: pin });
    await assert.rejects(access.query(query), code('unregistered_recipe'));
  });
});

test('metadata opens neither SQL companions nor row payloads; selecting SQL reads only that companion', async () => {
  await copied(async (directory, registration) => {
    const sqlPath = join(directory, 'recipes/observations-minimum.sql');
    const sqlBytes = await readFile(sqlPath);
    await rm(sqlPath);
    await rm(join(directory, 'data'), { recursive: true });
    const store = new CatalogStore([registration]);
    const snapshot = await store.snapshot(registration.id);
    assert.equal(snapshot.catalog.recipes.length, 1);
    await writeFile(sqlPath, sqlBytes);
    assert.equal(
      (
        await store.companion(
          snapshot.id,
          snapshot.identity.catalogSha256,
          snapshot.catalog.recipes[0].sql,
        )
      ).toString(),
      sqlBytes.toString(),
    );
    const listed = await store.list();
    assert.equal(listed.catalogs.length, 1);
  });
});

test('public mode refuses an internal lock before opening its catalog; failures remain per set', async () => {
  await copied(async (directory, registration) => {
    const pin = await repin(directory, (catalog, lock) => {
      catalog.audience = 'local';
      lock.catalogOptions.audience = 'local';
    });
    await rm(join(directory, 'catalog.ddk.json'));
    const store = new CatalogStore([
      { ...registration, id: 'internal', lockSha256: pin },
      fixtureRegistration('grants'),
    ]);
    await assert.rejects(store.snapshot('internal'), code('audience_refused'));
    const listing = await store.list();
    assert.deepEqual(
      listing.catalogs.map((row) => row.id),
      ['internal', 'grants'],
    );
    assert.equal(listing.unavailable[0].code, 'audience_refused');
  });
});

test('navigation listing opens no catalog bytes and marks unselected registration facts as not loaded', async () => {
  const store = new CatalogStore([
    {
      id: 'missing',
      navigationLabel: 'Unavailable source',
      directory: resolve('work/not-a-real-catalog'),
      lockSha256: '0'.repeat(64),
      mode: 'application',
    },
  ]);
  const listing = await store.list();
  assert.equal(listing.catalogs[0].title, 'Unavailable source');
  assert.equal(listing.catalogs[0].admission, 'not_loaded');
  assert.equal(listing.unavailable.length, 0);
  await assert.rejects(store.snapshot('missing'));
  assert.equal((await store.list()).unavailable[0].code, 'catalog_unavailable');
});

test('cache retirement permits three sets and a later exact reload within a two-set cache', async () => {
  const first = fixtureRegistration();
  const store = new CatalogStore([
    first,
    fixtureRegistration('grants'),
    { ...first, id: 'watershed-copy' },
  ]);
  const identity = (await store.snapshot(first.id)).identity;
  await store.snapshot('grants');
  await store.snapshot('watershed-copy');
  const reloaded = await store.snapshot(first.id);
  assert.deepEqual(reloaded.identity, identity);
  const { catalogs, unavailable } = await store.list();
  assert.equal(catalogs.length, 3);
  assert.equal(unavailable.length, 0);
});

test('one current selector can identify disjoint dataset releases without global false ambiguity', async () => {
  await copied(async (directory, registration) => {
    const pin = await repin(directory, (catalog) => {
      const selected = catalog.releases[1],
        lookup = { ...selected, id: selected.id + ':lookup', members: [selected.members[1]] };
      selected.members = [selected.members[0]];
      catalog.releases.push(lookup);
      catalog.selections.push({ ...catalog.selections[0], release: lookup.id });
    });
    const snapshot = await new CatalogStore([{ ...registration, lockSha256: pin }]).snapshot(
      registration.id,
    );
    assert.equal(snapshot.catalog.selections.length, 2);
    assert.equal(
      snapshot.catalog.selections[0].authority,
      snapshot.catalog.selections[1].authority,
    );
  });
});

test('standard inventory rejects duplicate IDs, contradictory pass and unsafe paths', async () => {
  await copied(async (directory, registration) => {
    let pin = await repin(directory, (catalog) => {
      catalog.datasets[1].id = catalog.datasets[0].id;
    });
    await assert.rejects(
      new CatalogStore([{ ...registration, lockSha256: pin }]).snapshot(registration.id),
      code('ambiguous_catalog'),
    );
    pin = await repin(directory, (catalog, _lock, report) => {
      catalog.datasets[1].id += ':fixed';
      report.decision = 'passed';
    });
    await assert.rejects(
      new CatalogStore([{ ...registration, lockSha256: pin }]).snapshot(registration.id),
      code('invalid_report'),
    );
  });
  const { store, snapshot } = await context();
  for (const path of ['../secrets', 'https://example.org/file', '/etc/passwd', '%2e%2e/file'])
    await assert.rejects(
      store.companion(snapshot.id, snapshot.identity.catalogSha256, path),
      code('invalid_path'),
    );
  const loaded = await store.load(snapshot.id);
  await assert.rejects(
    store.readPinned(
      loaded.registration,
      'catalog.ddk.json',
      snapshot.identity.catalogSha256,
      Date.now() + 1000,
      10,
    ),
    code('file_budget'),
  );
});

test('owner boundary rejects non-progressing pages, rounded values and incorrect consumption receipts', async () => {
  const registration = { ...fixtureRegistration(), mode: 'application' as const };
  const { store, request, binding } = await context(registration);
  for (const [reader, expected] of [
    [
      { read: async () => ({ rows: [], rowPositions: [], total: 1, consumed: binding }) },
      'adapter_budget',
    ],
    [
      {
        read: async () => ({
          rows: [{ value: 0.1 }],
          rowPositions: [0],
          total: 1,
          consumed: binding,
        }),
      },
      'adapter_transport',
    ],
    [
      {
        read: async () => ({
          rows: [{}],
          rowPositions: [0],
          total: 1,
          consumed: { ...binding, versionId: 'wrong' },
        }),
      },
      'adapter_binding',
    ],
    [
      { read: async () => ({ rows: [{}, {}], rowPositions: [0, 0], total: 2, consumed: binding }) },
      'adapter_budget',
    ],
  ] as const) {
    const access = new CatalogAccess(
      store,
      new Map([[registration.id, { reader: reader as OwnerReader }]]),
    );
    await assert.rejects(access.read(request), code(expected));
  }
});

test('owner query boundary enforces the requested limit, binding and SQL receipt', async () => {
  const registration = { ...fixtureRegistration(), mode: 'application' as const };
  const { store, query, binding } = await context(registration);
  const result: QueryResult = {
    status: 'ok',
    bindings: { records: binding },
    rows: [{}, {}],
    rowPositions: [0, 1],
    columns: [],
    returned: 2,
    total: 2,
    transport: 'ddk-exact-json-v1',
  };
  const access = new CatalogAccess(
    store,
    new Map([[registration.id, { query: { query: async () => result } as OwnerQuery }]]),
  );
  await assert.rejects(access.query({ ...query, limit: 1 }), code('adapter_budget'));
  await assert.rejects(access.query(query), code('adapter_receipt'));
});

test('registered owner capability appears in discovery and positive exact read uses that adapter', async () => {
  const registration = { ...fixtureRegistration(), mode: 'application' as const };
  const { store, request, binding } = await context(registration);
  const reader: OwnerReader = {
    read: async ({ signal, snapshot }) => {
      assert.equal(signal.aborted, false);
      assert.equal(snapshot.capabilities.read, true);
      return {
        rows: [{ amount: { $number: '0.100000000000000001' } }],
        rowPositions: [0],
        total: 1,
        consumed: binding,
        record: { uri: 'urn:test:owner-read:exact' },
      };
    },
  };
  const access = new CatalogAccess(store, new Map([[registration.id, { reader }]]));
  assert.deepEqual((await access.snapshot(registration.id)).capabilities, {
    read: true,
    query: false,
  });
  const result = await access.read(request);
  assert.equal(result.status, 'ok');
  assert.equal(result.readEvidence?.kind, 'owner');
  assert.deepEqual(result.rows[0].amount, { $number: '0.100000000000000001' });
});

test('bounded owner pages support large totals and late physical positions beyond fixture materialization limits', async () => {
  const registration = { ...fixtureRegistration(), mode: 'application' as const };
  const { store, request, binding } = await context(registration);
  const reader: OwnerReader = {
    read: async () => ({
      rows: [{ id: { $number: '9007199254740993' } }],
      rowPositions: [1_000_000],
      total: 1_000_001,
      consumed: binding,
    }),
  };
  const access = new CatalogAccess(store, new Map([[registration.id, { reader }]]));
  const page = await access.read({ ...request, limit: 1 });
  assert.equal(page.status, 'ok');
  assert.equal(page.total, 1_000_001);
  assert.deepEqual(page.rowPositions, [1_000_000]);
  assert.ok(page.nextCursor);
});

test('owner pages continue without a count scan when hasMore is explicit', async () => {
  const registration = { ...fixtureRegistration(), mode: 'application' as const };
  const { store, request, binding } = await context(registration);
  const offsets: number[] = [];
  const reader: OwnerReader = {
    read: async ({ offset }) => {
      offsets.push(offset);
      return offset === 0
        ? { rows: [{ label: 'first' }], rowPositions: [500_000], hasMore: true, consumed: binding }
        : {
            rows: [{ label: 'second' }],
            rowPositions: [500_002],
            hasMore: false,
            consumed: binding,
          };
    },
  };
  const access = new CatalogAccess(store, new Map([[registration.id, { reader }]]));
  const first = await access.read({ ...request, limit: 1 });
  assert.equal(first.total, undefined);
  assert.equal(first.hasMore, true);
  assert.equal(first.continuation, 'more');
  assert.ok(first.nextCursor);
  const second = await access.read({ ...request, limit: 1, cursor: first.nextCursor });
  assert.equal(second.total, undefined);
  assert.equal(second.hasMore, false);
  assert.equal(second.continuation, 'complete');
  assert.equal(second.nextCursor, undefined);
  assert.deepEqual(offsets, [0, 1]);
  assert.equal(second.rows[0].label, 'second');
});

test('missing owner continuation evidence stays unknown and empty nonfinal pages refuse', async () => {
  const registration = { ...fixtureRegistration(), mode: 'application' as const };
  const { store, request, binding } = await context(registration);
  const reader: OwnerReader = {
    read: async () => ({
      rows: [{ label: 'bounded sample' }],
      rowPositions: [20_000],
      consumed: binding,
    }),
  };
  const access = new CatalogAccess(store, new Map([[registration.id, { reader }]]));
  const result = await access.read(request);
  assert.equal(result.continuation, 'unknown');
  assert.equal(result.hasMore, undefined);
  assert.equal(result.total, undefined);
  assert.equal(result.nextCursor, undefined);
  const invalid: OwnerReader = {
    read: async () => ({ rows: [], rowPositions: [], hasMore: true, consumed: binding }),
  };
  const invalidAccess = new CatalogAccess(store, new Map([[registration.id, { reader: invalid }]]));
  await assert.rejects(invalidAccess.read(request), code('adapter_budget'));
  const contradictory: OwnerReader = {
    read: async () => ({
      rows: [{}],
      rowPositions: [0],
      total: 5,
      hasMore: false,
      consumed: binding,
    }),
  };
  const contradictoryAccess = new CatalogAccess(
    store,
    new Map([[registration.id, { reader: contradictory }]]),
  );
  await assert.rejects(contradictoryAccess.read(request), code('adapter_budget'));
});

test('unsettled owner reads time out as unknown, request cancellation and retain bounded owner slots', async () => {
  const registration = { ...fixtureRegistration(), mode: 'application' as const };
  const { store, request } = await context(registration);
  const signals: AbortSignal[] = [];
  const reader: OwnerReader = {
    read: ({ signal }) => {
      signals.push(signal);
      return new Promise(() => {});
    },
  };
  const access = new CatalogAccess(store, new Map([[registration.id, { reader }]]), {
    deadlineMs: 10,
  });
  const started = Date.now();
  const first = await access.read(request),
    second = await access.read(request),
    third = await access.read(request);
  assert.equal(first.status, 'unknown');
  assert.match(first.reason!, /completion remains unknown/);
  assert.equal(second.status, 'unknown');
  assert.equal(third.status, 'unknown');
  assert.match(third.reason!, /Two owner reads remain unsettled/);
  assert.equal(signals.length, 2);
  assert.ok(signals.every((signal) => signal.aborted));
  assert.ok(Date.now() - started < 1000);
});

test('unsettled owner query times out as unknown and receives cancellation', async () => {
  const registration = { ...fixtureRegistration(), mode: 'application' as const };
  const { store, query } = await context(registration);
  let signal: AbortSignal | undefined;
  const owner: OwnerQuery = {
    query: (input) => {
      signal = input.signal;
      return new Promise(() => {});
    },
  };
  const access = new CatalogAccess(store, new Map([[registration.id, { query: owner }]]), {
    deadlineMs: 10,
  });
  assert.equal((await access.snapshot(registration.id)).capabilities.query, true);
  const result = await access.query(query);
  assert.equal(result.status, 'unknown');
  assert.equal(signal?.aborted, true);
  assert.equal(result.returned, 0);
});

test('HTTP body streaming enforces actual bytes and exact-safe JSON', async () => {
  await assert.rejects(
    body(
      new Request('http://localhost/api/read', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: ' '.repeat(LIMITS.requestBytes + 1),
      }),
    ),
    code('request_budget'),
  );
  await assert.rejects(
    body(
      new Request('http://localhost/api/read', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{"x":1,"x":2}',
      }),
    ),
    code('invalid_json'),
  );
});

test('two real application sets admit as discovery only without reading corpus rows', async (t) => {
  for (const registration of applicationRegistrations) {
    try {
      await fileAccess(join(registration.directory, 'catalog.lock.json'));
    } catch {
      t.diagnostic(`Retained application evidence unavailable: ${registration.id}`);
      continue;
    }
    const store = new CatalogStore([registration]);
    const snapshot = await store.snapshot(registration.id);
    assert.equal(snapshot.audience, 'public');
    assert.equal(snapshot.mode, 'application');
    assert.equal(snapshot.capabilities.read, false);
    assert.equal(snapshot.capabilities.query, false);
    assert.ok(snapshot.catalog.datasets.length > 1);
    if (registration.id === 'congress') {
      assert.equal(snapshot.catalog.datasets.length, 24);
      assert.equal(snapshot.catalog.recipes.length, 16);
    }
  }
});
