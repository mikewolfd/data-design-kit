import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';
import { exactObjectField } from '../../src/domain/exact';
import type { Catalog, CatalogSnapshot } from '../../src/domain/types';
import { CatalogAccess } from '../../src/server/access';
import { CatalogStore, sha256, type CatalogRegistration } from '../../src/server/catalog-store';
import {
  DEFAULT_DOCSPEC_BINARY,
  DEFAULT_DOCSPEC_SHA256,
} from '../../src/server/commerce-native';
import {
  congressRegistration,
  createCongressAdapter,
} from '../../src/server/congress-registration';
import {
  createDocSpecCatalogOwner,
  loadOperatorOwnerConfig,
} from '../../src/server/docspec-owner';

const TEST_PARQUET_WRITER_PYTHON =
  [
    '/Users/mikewolfd/Work/artifacts/ddk-sdk4-20261111/env-sdk4/bin/python',
    '/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/env-full/bin/python',
    '/Users/mikewolfd/Work/congressional-tech/.venv/bin/python',
  ].find((candidate) => existsSync(candidate)) ?? '';
const HAS_RUNTIME = existsSync(DEFAULT_DOCSPEC_BINARY) && Boolean(TEST_PARQUET_WRITER_PYTHON);

async function writeCatalogArtifacts(
  dir: string,
  catalogWithoutFiles: Omit<Catalog, 'files' | 'runs'> & { runs?: Catalog['runs'] },
  extraCompanions: Record<string, string> = {},
): Promise<{ lockSha256: string; catalogSha256: string }> {
  const report = {
    specVersion: '0.1',
    kind: 'report',
    id: `${catalogWithoutFiles.id}:report`,
    version: catalogWithoutFiles.version,
    decision: 'passed',
    scope: {
      projects: [catalogWithoutFiles.project.id],
      artifacts: [],
      followedReferences: [],
      excludedConsumers: [],
    },
    coverage: {
      requestedGroups: ['catalog.qualification'],
      completedProfiles: [],
      availableCapabilities: [],
      missingCapabilities: [],
      mappingLimits: [],
    },
    lock: { verified: true, path: 'catalog.lock.json' },
    tools: { 'test-author': { version: '1.0.0' } },
    checks: [
      {
        id: 'synthetic-declaration',
        requirement: 'DDK-CATALOG-001',
        group: 'catalog.qualification',
        subject: catalogWithoutFiles.project.id,
        status: 'passed',
        required: true,
        applicable: true,
        evidence: 'declared',
        reason: 'Synthetic test catalog.',
        diagnostics: [],
      },
    ],
    operationalErrors: [],
  };
  const reportBytes = Buffer.from(JSON.stringify(report, null, 2) + '\n');
  const reportSha = sha256(reportBytes);
  await writeFile(join(dir, 'catalog.report.json'), reportBytes);

  const companionFiles: { path: string; sha256: string; role: string }[] = [
    { path: 'catalog.report.json', sha256: reportSha, role: 'report' },
  ];
  for (const [relPath, text] of Object.entries(extraCompanions)) {
    const fullPath = join(dir, relPath);
    execFileSync('mkdir', ['-p', resolve(fullPath, '..')]);
    const buf = Buffer.from(text, 'utf8');
    await writeFile(fullPath, buf);
    companionFiles.push({
      path: relPath,
      sha256: sha256(buf),
      role: relPath.endsWith('.sql') ? 'recipe' : 'companion',
    });
  }

  const normalizedDatasets = catalogWithoutFiles.datasets.map((ds) => ({
    role: ds.role ?? 'source_record',
    rowMeaning: ds.rowMeaning ?? 'One synthetic test row.',
    title: ds.title ?? ds.alias,
    ...ds,
  }));
  const normalizedRecipes = catalogWithoutFiles.recipes.map((rec) => ({
    resultGrain: rec.resultGrain ?? 'One matching result row.',
    ...rec,
  }));

  const fullCatalog: Catalog = {
    ...catalogWithoutFiles,
    runs: catalogWithoutFiles.runs ?? [],
    sourceInventory:
      catalogWithoutFiles.sourceInventory.length > 0
        ? catalogWithoutFiles.sourceInventory
        : [{ uri: 'urn:test:project-def', sha256: '5'.repeat(64), role: 'project' }],
    adapters:
      catalogWithoutFiles.adapters.length > 0
        ? catalogWithoutFiles.adapters
        : [{ id: 'ddk.test', version: '0.1.0' }],
    products:
      catalogWithoutFiles.products.length > 0
        ? catalogWithoutFiles.products
        : [
            {
              alias: 'test-product',
              id: `${catalogWithoutFiles.id}:product`,
              version: '1.0.0',
              definition: { uri: 'urn:test:product-def', sha256: '6'.repeat(64) },
              ports: normalizedDatasets.map((d) => ({
                product: 'test-product',
                direction: 'output',
                port: d.alias,
                version: '1.0.0',
                dataset: d.alias,
              })),
            },
          ],
    datasets: normalizedDatasets,
    recipes: normalizedRecipes,
    files: companionFiles,
  };
  const catalogBytes = Buffer.from(JSON.stringify(fullCatalog, null, 2) + '\n');
  const catalogSha = sha256(catalogBytes);
  await writeFile(join(dir, 'catalog.ddk.json'), catalogBytes);

  const outputSet = [
    { path: 'catalog.ddk.json', sha256: catalogSha, role: 'catalog' },
    ...companionFiles,
  ];
  const lock = {
    specVersion: '0.1',
    kind: 'lock',
    id: `${fullCatalog.id}:lock`,
    version: fullCatalog.version,
    project: fullCatalog.project.id,
    tools: { 'test-author': { version: '1.0.0' } },
    standards: { ddk: '0.1' },
    catalogOptions: { audience: fullCatalog.audience, exports: [] },
    files: companionFiles.map((f) => ({
      path: f.path,
      sha256: f.sha256,
      role: f.role,
    })),
    extensions: {
      'urn:ddk:catalog:output-set': outputSet,
    },
  };
  const lockBytes = Buffer.from(JSON.stringify(lock, null, 2) + '\n');
  const lockSha = sha256(lockBytes);
  await writeFile(join(dir, 'catalog.lock.json'), lockBytes);
  return { lockSha256: lockSha, catalogSha256: catalogSha };
}

test(
  'DocSpecCatalogOwner paginates multi-row-group and multi-shard Parquet preserving exact 64-bit ints, decimals, -0.0, timestamps and reserved keys',
  { skip: !HAS_RUNTIME && 'Python/DocSpec runtime unavailable' },
  async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'ddk-docspec-owner-parquet-'));
    try {
      const dataDir = join(tmp, 'data');
      const catalogDir = join(tmp, 'catalog');
      execFileSync('mkdir', ['-p', dataDir, catalogDir]);

      // Write single multi-row-group Parquet + 3 multi-shard Parquet files for test fixture setup
      execFileSync(
        TEST_PARQUET_WRITER_PYTHON,
        [
          '-c',
          `
import json, sys
from decimal import Decimal
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

data_dir = Path(sys.argv[1])

schema = pa.schema([
    ("id", pa.int64()),
    ("amount", pa.decimal128(18, 4)),
    ("ratio", pa.float64()),
    ("event_ts", pa.timestamp("ns", tz="UTC")),
    ("payload", pa.binary()),
    ("tags", pa.list_(pa.string())),
    ("nested", pa.struct([("$number", pa.string()), ("label", pa.string())])),
])

rows = [
    {"id": 9007199254740993, "amount": Decimal("12345.6700"), "ratio": -0.0, "event_ts": 1794406516123456789, "payload": b"alpha", "tags": ["a", None], "nested": {"$number": "raw-escape", "label": "row0"}},
    {"id": -9007199254740995, "amount": Decimal("-0.0050"), "ratio": 1.5, "event_ts": 1794406517000000000, "payload": b"beta", "tags": [], "nested": {"$number": "second", "label": "row1"}},
    {"id": 42, "amount": Decimal("100.0000"), "ratio": 0.0, "event_ts": 1794406518000000000, "payload": None, "tags": ["x"], "nested": None},
    {"id": 9007199254740999, "amount": Decimal("999999.9999"), "ratio": 2.25, "event_ts": 1794406519000000001, "payload": b"delta", "tags": ["y", "z"], "nested": {"$number": "fourth", "label": "row3"}},
    {"id": 7, "amount": Decimal("0.1000"), "ratio": -3.5, "event_ts": 1794406520000000000, "payload": b"eps", "tags": None, "nested": {"$number": "fifth", "label": "row4"}},
]

table = pa.Table.from_pylist(rows, schema=schema)
single_path = data_dir / "single.parquet"
pq.write_table(table, single_path, row_group_size=2)

# Write 3 shards with [0..2), [2..4), [4..5)
shard_specs = [(0, 2), (2, 4), (4, 5)]
shards_meta = []
for idx, (lo, hi) in enumerate(shard_specs):
    sp = data_dir / f"shard-{idx}.parquet"
    pq.write_table(table.slice(lo, hi - lo), sp, row_group_size=1)
    raw = sp.read_bytes()
    shards_meta.append({
        "path": sp.name,
        "sha256": sha256(raw).hexdigest(),
        "byteSize": len(raw),
        "rowCount": hi - lo,
        "rowRange": [lo, hi],
    })

single_bytes = single_path.read_bytes()
(data_dir / "meta.json").write_text(json.dumps({
    "single": {
        "path": str(single_path),
        "sha256": sha256(single_bytes).hexdigest(),
        "byteSize": len(single_bytes),
        "rowCount": 5,
    },
    "shards": shards_meta,
}))
`,
          dataDir,
        ],
        { stdio: 'pipe' },
      );

      const meta = JSON.parse(await readFile(join(dataDir, 'meta.json'), 'utf8'));
      const evidenceDoc = JSON.stringify({ check: 'ok', rowsVerified: 5 }) + '\n';
      const evidencePath = join(dataDir, 'check-evidence.json');
      await writeFile(evidencePath, evidenceDoc, 'utf8');
      const evidenceRef = {
        uri: pathToFileURL(evidencePath).href,
        sha256: sha256(Buffer.from(evidenceDoc, 'utf8')),
      };

      const catalogBase: Omit<Catalog, 'files' | 'runs'> = {
        specVersion: '0.1',
        kind: 'catalog',
        id: 'urn:test:owner:catalog',
        version: '1.0.0',
        audience: 'local',
        project: { id: 'urn:test:owner:project', version: '1.0.0' },
        sourceInventory: [],
        adapters: [],
        products: [],
        datasets: [
          {
            id: 'urn:test:owner:dataset:single',
            alias: 'single',
            origin: 'publisher',
            definition: {
              contractId: 'urn:test:contract:single',
              object: 'single',
              version: '1.0.0',
              source: { uri: 'urn:test:def:single', sha256: 'a'.repeat(64) },
            },
          },
          {
            id: 'urn:test:owner:dataset:sharded',
            alias: 'sharded',
            origin: 'derived',
            definition: {
              contractId: 'urn:test:contract:sharded',
              object: 'sharded',
              version: '1.0.0',
              source: { uri: 'urn:test:def:sharded', sha256: 'b'.repeat(64) },
            },
          },
          {
            id: 'urn:test:owner:dataset:withheld',
            alias: 'withheld_ds',
            definition: {
              contractId: 'urn:test:contract:withheld',
              object: 'withheld_ds',
              version: '1.0.0',
              source: { uri: 'urn:test:def:withheld', sha256: 'c'.repeat(64) },
            },
          },
        ],
        identities: [],
        relationships: [],
        recipes: [],
        versions: [
          {
            id: 'urn:test:version:single:1',
            dataset: 'single',
            reference: {
              scheme: 'urn:ddk:version:local-file-sha256',
              authority: 'urn:ddk:local-file',
              value: {
                location: pathToFileURL(meta.single.path).href,
                sha256: meta.single.sha256,
              },
            },
            retention: 'present',
            scope: 'Exact synthetic test file.',
            record: { uri: 'urn:test:version-record', sha256: '7'.repeat(64) },
            sources: [],
            coverage: [],
          },
          {
            id: 'urn:test:version:sharded:1',
            dataset: 'sharded',
            reference: {
              scheme: 'urn:ddk:version:local-dir',
              authority: 'urn:ddk:local-file',
              value: { directory: pathToFileURL(dataDir).href },
            },
            retention: 'present',
            scope: 'Exact synthetic test shards.',
            record: { uri: 'urn:test:version-record', sha256: '7'.repeat(64) },
            sources: [],
            coverage: [],
          },
          {
            id: 'urn:test:version:withheld:1',
            dataset: 'withheld_ds',
            referenceDisclosure: 'withheld',
            retention: 'present',
            scope: 'Withheld synthetic test file.',
            record: { uri: 'urn:test:version-record', sha256: '7'.repeat(64) },
            sources: [],
            coverage: [],
          },
        ],
        sources: [],
        representations: [
          {
            id: 'urn:test:rep:single:1',
            version: 'urn:test:version:single:1',
            kind: 'file',
            availability: 'available',
            mediaType: 'application/vnd.apache.parquet',
            location: pathToFileURL(meta.single.path).href,
            byteSize: meta.single.byteSize,
            rowCount: meta.single.rowCount,
            record: { uri: 'urn:test:rep-record', sha256: '7'.repeat(64) },
          },
          {
            id: 'urn:test:rep:sharded:1',
            version: 'urn:test:version:sharded:1',
            kind: 'file',
            availability: 'available',
            mediaType: 'application/vnd.apache.parquet',
            location: pathToFileURL(dataDir).href,
            rowCount: 5,
            members: meta.shards,
            record: { uri: 'urn:test:rep-record', sha256: '7'.repeat(64) },
          },
          {
            id: 'urn:test:rep:withheld:1',
            version: 'urn:test:version:withheld:1',
            kind: 'file',
            availability: 'unavailable',
            mediaType: 'application/vnd.apache.parquet',
            record: { uri: 'urn:test:rep-record', sha256: '7'.repeat(64) },
          },
        ],
        releases: [],
        selections: [],
        productions: [],
        checks: [
          {
            subject: 'urn:test:owner:dataset:single',
            rule: { id: 'urn:ddk:rule:row-count', version: '1.0' },
            evaluator: { id: 'urn:ddk:eval:test', version: '1.0' },
            scope: 'dataset',
            status: 'passed',
            record: evidenceRef,
          },
        ],
      };

      const { lockSha256 } = await writeCatalogArtifacts(catalogDir, catalogBase);
      const reg: CatalogRegistration = {
        id: 'synthetic-owner',
        mode: 'application',
        navigationLabel: 'Synthetic Owner',
        navigationDescription: 'Parquet pagination & shard test.',
        directory: catalogDir,
        lockSha256,
      };
      const store = new CatalogStore([reg], 'local');
      const snapshot: CatalogSnapshot = await store.snapshot('synthetic-owner');

      const owner = await createDocSpecCatalogOwner({
        directory: catalogDir,
        lockSha256,
        permittedRoots: [catalogDir, dataDir],
      });
      try {
        assert.equal(owner.startup.runtime, 'docspec-native-rust');
        assert.equal(owner.startup.docspecBinary, DEFAULT_DOCSPEC_BINARY);
        const access = new CatalogAccess(store, new Map([['synthetic-owner', owner]]));

        // 1. Single-file pagination across row groups (limit 2)
        const page1 = await access.read({
          catalogId: 'synthetic-owner',
          catalogSha256: snapshot.identity.catalogSha256,
          datasetId: 'urn:test:owner:dataset:single',
          versionId: 'urn:test:version:single:1',
          representationId: 'urn:test:rep:single:1',
          limit: 2,
        });
        assert.equal(page1.status, 'ok');
        assert.equal(page1.total, 5);
        assert.equal(page1.returned, 2);
        assert.equal(page1.hasMore, true);
        assert.ok(page1.nextCursor);
        assert.deepEqual(page1.rowPositions, [0, 1]);

        const row0 = page1.rows[0];
        assert.deepEqual(exactObjectField(row0, 'id'), { $number: '9007199254740993' });
        assert.deepEqual(exactObjectField(row0, 'amount'), { $number: '12345.6700' });
        assert.deepEqual(exactObjectField(row0, 'ratio'), { $number: '-0' });
        assert.equal(exactObjectField(row0, 'event_ts'), '2026-11-11T14:15:16.123456789Z');
        const bin0 = exactObjectField(row0, 'payload') as any;
        assert.equal(exactObjectField(bin0, 'encoding'), 'base64');
        assert.equal(
          Buffer.from(exactObjectField(bin0, 'value') as string, 'base64').toString('utf8'),
          'alpha',
        );
        // Reserved $number key inside struct must be escaped via $object
        const nested0 = exactObjectField(row0, 'nested') as any;
        assert.ok(Array.isArray(nested0.$object));
        assert.equal(exactObjectField(nested0, '$number'), 'raw-escape');

        const page2 = await access.read({
          catalogId: 'synthetic-owner',
          catalogSha256: snapshot.identity.catalogSha256,
          datasetId: 'urn:test:owner:dataset:single',
          versionId: 'urn:test:version:single:1',
          representationId: 'urn:test:rep:single:1',
          limit: 2,
          cursor: page1.nextCursor,
        });
        assert.equal(page2.status, 'ok');
        assert.deepEqual(page2.rowPositions, [2, 3]);
        assert.equal(page2.hasMore, true);
        assert.deepEqual(exactObjectField(page2.rows[1], 'id'), {
          $number: '9007199254740999',
        });

        const page3 = await access.read({
          catalogId: 'synthetic-owner',
          catalogSha256: snapshot.identity.catalogSha256,
          datasetId: 'urn:test:owner:dataset:single',
          versionId: 'urn:test:version:single:1',
          representationId: 'urn:test:rep:single:1',
          limit: 2,
          cursor: page2.nextCursor,
        });
        assert.equal(page3.status, 'ok');
        assert.deepEqual(page3.rowPositions, [4]);
        assert.equal(page3.hasMore, false);

        // 2. Multi-shard members[] pagination spanning shard-0 [0..2), shard-1 [2..4), shard-2 [4..5)
        const shardPage1 = await access.read({
          catalogId: 'synthetic-owner',
          catalogSha256: snapshot.identity.catalogSha256,
          datasetId: 'urn:test:owner:dataset:sharded',
          versionId: 'urn:test:version:sharded:1',
          representationId: 'urn:test:rep:sharded:1',
          limit: 3,
        });
        assert.equal(shardPage1.status, 'ok');
        assert.equal(shardPage1.total, 5);
        assert.deepEqual(shardPage1.rowPositions, [0, 1, 2]);
        assert.deepEqual(
          shardPage1.rows.map((r) => exactObjectField(r, 'id')),
          [
            { $number: '9007199254740993' },
            { $number: '-9007199254740995' },
            { $number: '42' },
          ],
        );
        const shardPage2 = await access.read({
          catalogId: 'synthetic-owner',
          catalogSha256: snapshot.identity.catalogSha256,
          datasetId: 'urn:test:owner:dataset:sharded',
          versionId: 'urn:test:version:sharded:1',
          representationId: 'urn:test:rep:sharded:1',
          limit: 3,
          cursor: shardPage1.nextCursor,
        });
        assert.equal(shardPage2.status, 'ok');
        assert.equal(shardPage2.hasMore, false);
        // Spans index 3 (in shard-1) and index 4 (in shard-2)
        assert.deepEqual(shardPage2.rowPositions, [3, 4]);
        assert.deepEqual(
          shardPage2.rows.map((r) => exactObjectField(r, 'id')),
          [{ $number: '9007199254740999' }, { $number: '7' }],
        );

        // 3. Evidence reader verifies sha256 + permittedRoots and refuses binary .parquet or tampered sha256
        const ev = await access.evidence({
          catalogId: 'synthetic-owner',
          catalogSha256: snapshot.identity.catalogSha256,
          record: evidenceRef,
        });
        assert.equal(ev.scope, 'owner-evidence');
        assert.equal(exactObjectField(ev.document as any, 'check'), 'ok');
        assert.deepEqual(exactObjectField(ev.document as any, 'rowsVerified'), { $number: '5' });

        await assert.rejects(
          () =>
            owner.evidence!({
              record: {
                uri: pathToFileURL(meta.single.path).href,
                sha256: meta.single.sha256,
              },
              deadline: Date.now() + 5000,
              signal: new AbortController().signal,
            }),
          (err: any) => err?.code === 'evidence_refused',
        );

        await assert.rejects(
          () =>
            owner.evidence!({
              record: {
                uri: evidenceRef.uri,
                sha256: 'f'.repeat(64),
              },
              deadline: Date.now() + 5000,
              signal: new AbortController().signal,
            }),
          (err: any) => err?.code === 'integrity_mismatch',
        );

        // 3b. Unreferenced JSON and CSV files inside permittedRoots are refused by default allowlist + extension guard
        const unreferencedJsonPath = join(dataDir, 'unreferenced-secret.json');
        const unreferencedJsonBytes = Buffer.from('{"secret":"not-in-catalog"}\n', 'utf8');
        await writeFile(unreferencedJsonPath, unreferencedJsonBytes);
        await assert.rejects(
          () =>
            owner.evidence!({
              record: {
                uri: pathToFileURL(unreferencedJsonPath).href,
                sha256: sha256(unreferencedJsonBytes),
              },
              deadline: Date.now() + 5000,
              signal: new AbortController().signal,
            }),
          (err: any) => err?.code === 'evidence_refused',
        );

        const unreferencedCsvPath = join(dataDir, 'raw-dump.csv');
        const unreferencedCsvBytes = Buffer.from('id,amount\n1,100\n', 'utf8');
        await writeFile(unreferencedCsvPath, unreferencedCsvBytes);
        await assert.rejects(
          () =>
            owner.evidence!({
              record: {
                uri: pathToFileURL(unreferencedCsvPath).href,
                sha256: sha256(unreferencedCsvBytes),
              },
              deadline: Date.now() + 5000,
              signal: new AbortController().signal,
            }),
          (err: any) => err?.code === 'evidence_refused',
        );

        // 4. Withheld dataset refuses before touching disk
        const withheldRead = await access.read({
          catalogId: 'synthetic-owner',
          catalogSha256: snapshot.identity.catalogSha256,
          datasetId: 'urn:test:owner:dataset:withheld',
          versionId: 'urn:test:version:withheld:1',
          representationId: 'urn:test:rep:withheld:1',
          limit: 5,
        });
        assert.equal(withheldRead.status, 'refused');

        // 5. Tampering Parquet shard bytes on disk triggers integrity_mismatch
        const shard0Path = join(dataDir, 'shard-0.parquet');
        const originalBytes = await readFile(shard0Path);
        await writeFile(shard0Path, Buffer.concat([originalBytes, Buffer.from([0x00])]));
        await assert.rejects(
          () =>
            access.read({
              catalogId: 'synthetic-owner',
              catalogSha256: snapshot.identity.catalogSha256,
              datasetId: 'urn:test:owner:dataset:sharded',
              versionId: 'urn:test:version:sharded:1',
              representationId: 'urn:test:rep:sharded:1',
              limit: 2,
            }),
          (err: any) => err?.code === 'integrity_mismatch',
        );
      } finally {
        await owner.close();
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  },
);

test(
  'DocSpecCatalogOwner executes parameterized SQL recipes via unified docspec binary and survives 50+ clicks with zero quota bricking',
  { skip: !HAS_RUNTIME && 'Python/DocSpec runtime unavailable' },
  async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'ddk-docspec-param-query-'));
    try {
      const dataDir = join(tmp, 'data');
      const catDir = join(tmp, 'catalog');
      execFileSync('mkdir', ['-p', dataDir, catDir]);

      const ordersPath = join(dataDir, 'orders.parquet');
      execFileSync(
        TEST_PARQUET_WRITER_PYTHON,
        [
          '-c',
          `
import sys
from decimal import Decimal
import pyarrow as pa
import pyarrow.parquet as pq

schema = pa.schema([
    ("order_id", pa.int64()),
    ("region", pa.string()),
    ("total", pa.decimal128(24, 4)),
])
rows = [
    {"order_id": 1001, "region": "us-east", "total": Decimal("250.7500")},
    {"order_id": 1002, "region": "us-west", "total": Decimal("80.0000")},
    {"order_id": 9007199254740992, "region": "us-east", "total": Decimal("1234567890123456.7890")},
    {"order_id": 9007199254740993, "region": "us-east", "total": Decimal("1234567890123456.7891")},
]
pq.write_table(pa.Table.from_pylist(rows, schema=schema), sys.argv[1])
`,
          ordersPath,
        ],
        { stdio: 'pipe' },
      );
      const ordersSha = sha256(await readFile(ordersPath));

      const positionalSql =
        'SELECT order_id, region, total, CAST(total AS VARCHAR) AS total_lexeme FROM orders WHERE region = ? AND order_id >= ? AND total >= ? ORDER BY order_id;\n';

      const catBase: Omit<Catalog, 'files' | 'runs'> = {
        specVersion: '0.1',
        kind: 'catalog',
        id: 'urn:test:docspec:param-catalog',
        version: '1.0.0',
        audience: 'local',
        project: { id: 'urn:test:docspec:project', version: '1.0.0' },
        sourceInventory: [],
        adapters: [],
        products: [],
        datasets: [
          {
            id: 'urn:test:docspec:dataset:orders',
            alias: 'orders',
            definition: {
              contractId: 'urn:test:docspec:contract:orders',
              object: 'orders',
              version: '1.0.0',
              source: { uri: 'urn:test:def:orders', sha256: '2'.repeat(64) },
            },
          },
        ],
        identities: [],
        relationships: [],
        recipes: [
          {
            id: 'urn:test:docspec:recipe:orders_by_region',
            sql: 'recipes/orders_by_region.sql',
            dialect: 'datafusion',
            inputs: { orders: 'orders' },
            relationships: [],
            parameterOrder: ['region', 'min_order_id', 'min_total'],
            parameters: {
              type: 'object',
              required: ['region', 'min_order_id', 'min_total'],
              additionalProperties: false,
              properties: {
                region: { type: 'string' },
                min_order_id: { type: 'integer' },
                min_total: { type: 'number' },
              },
            },
          },
        ],
        versions: [
          {
            id: 'urn:test:docspec:version:orders:1',
            dataset: 'orders',
            reference: {
              scheme: 'urn:ddk:version:local-file-sha256',
              authority: 'urn:ddk:local-file',
              value: { location: pathToFileURL(ordersPath).href, sha256: ordersSha },
            },
            retention: 'present',
            scope: 'Exact synthetic test file.',
            record: { uri: 'urn:test:version-record', sha256: '7'.repeat(64) },
            sources: [],
            coverage: [],
          },
        ],
        sources: [],
        representations: [
          {
            id: 'urn:test:docspec:rep:orders:1',
            version: 'urn:test:docspec:version:orders:1',
            kind: 'file',
            availability: 'available',
            mediaType: 'application/vnd.apache.parquet',
            location: pathToFileURL(ordersPath).href,
            record: { uri: 'urn:test:rep-record', sha256: '7'.repeat(64) },
          },
        ],
        releases: [
          {
            id: 'urn:test:docspec:release:r1',
            reference: {
              authority: 'urn:test:publisher',
              scheme: 'urn:ddk:local-release',
              value: 'urn:test:docspec:release:r1',
            },
            membership: 'complete',
            members: ['urn:test:docspec:version:orders:1'],
            record: { uri: 'urn:test:release-record', sha256: '4'.repeat(64) },
          },
        ],
        selections: [],
        productions: [],
        checks: [],
      };

      const { lockSha256 } = await writeCatalogArtifacts(catDir, catBase, {
        'recipes/orders_by_region.sql': positionalSql,
      });

      const paramStore = new CatalogStore(
        [
          {
            id: 'param-docspec',
            mode: 'application',
            navigationLabel: 'Param DocSpec',
            navigationDescription: 'Parameterized DocSpec test',
            directory: catDir,
            lockSha256,
          },
        ],
        'local',
      );
      const paramSnap = await paramStore.snapshot('param-docspec');
      const paramOwner = await createDocSpecCatalogOwner({
        directory: catDir,
        lockSha256,
        docspecBinary: DEFAULT_DOCSPEC_BINARY,
        docspecSha256: DEFAULT_DOCSPEC_SHA256,
        permittedRoots: [catDir, dataDir],
      });

      try {
        const paramAccess = new CatalogAccess(
          paramStore,
          new Map([['param-docspec', paramOwner]]),
        );
        const queryRes = await paramAccess.query({
          catalogId: 'param-docspec',
          catalogSha256: paramSnap.identity.catalogSha256,
          recipeId: 'urn:test:docspec:recipe:orders_by_region',
          bindings: {
            orders: {
              datasetId: 'urn:test:docspec:dataset:orders',
              versionId: 'urn:test:docspec:version:orders:1',
              representationId: 'urn:test:docspec:rep:orders:1',
              releaseId: 'urn:test:docspec:release:r1',
            },
          },
          parameters: {
            region: 'us-east',
            min_order_id: { $number: '9007199254740993' },
            min_total: { $number: '1234567890123456.7891' },
          },
          limit: 10,
        });

        assert.equal(queryRes.status, 'ok');
        assert.equal(queryRes.returned, 1);
        assert.deepEqual(exactObjectField(queryRes.rows[0], 'order_id'), {
          $number: '9007199254740993',
        });
        assert.deepEqual(exactObjectField(queryRes.rows[0], 'total'), {
          $number: '1234567890123456.7891',
        });
        assert.equal(exactObjectField(queryRes.rows[0], 'total_lexeme'), '1234567890123456.7891');
        assert.ok(queryRes.execution);
        assert.equal(queryRes.execution.kind, 'owner');
        assert.equal(queryRes.execution.recipeId, 'urn:test:docspec:recipe:orders_by_region');
        assert.equal(
          queryRes.execution.sqlSha256,
          sha256(Buffer.from(positionalSql, 'utf8')),
        );
        assert.deepEqual(queryRes.execution.engine, {
          id: 'docspec',
          version: '0.1.0',
          binarySha256: DEFAULT_DOCSPEC_SHA256,
        });
        assert.equal(typeof queryRes.execution.elapsedMs, 'number');
        assert.equal(queryRes.execution.record, undefined);
      } finally {
        await paramOwner.close();
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }

    // Run 50 sequential Congress read operations (> old 36-click self-bricking quota!)
    const store = new CatalogStore([congressRegistration], 'local');
    const snapshot = await store.snapshot(congressRegistration.id);
    const owner = await createCongressAdapter({
      snapshot,
      docspecBinary: DEFAULT_DOCSPEC_BINARY,
      docspecSha256: DEFAULT_DOCSPEC_SHA256,
    });

    try {
      const access = new CatalogAccess(store, new Map([[congressRegistration.id, owner]]));
      const listDataset = snapshot.catalog.datasets.find((d) => d.alias === 'list')!;
      const listVersion = snapshot.catalog.versions.find((v) => v.dataset === 'list')!;
      const listRep = snapshot.catalog.representations.find((r) => r.version === listVersion.id)!;

      const started = Date.now();
      for (let i = 0; i < 50; i++) {
        const res = await access.read({
          catalogId: congressRegistration.id,
          catalogSha256: snapshot.identity.catalogSha256,
          datasetId: listDataset.id,
          versionId: listVersion.id,
          representationId: listRep.id,
          limit: 5,
        });
        assert.equal(res.status, 'ok');
        assert.equal(res.returned, 5);
        assert.equal(res.total, 7);
      }
      const totalElapsedMs = Date.now() - started;
      assert.ok(
        totalElapsedMs < 5000,
        `Expected 50 reads to finish rapidly without re-hashing binary, took ${totalElapsedMs}ms`,
      );
    } finally {
      await owner.close();
    }
  },
);

test(
  'loadOperatorOwnerConfig handles public/paired-local switching and executes named-parameter DataFusion SQL via pure-Rust docspec owner-worker',
  { skip: !HAS_RUNTIME && 'DocSpec runtime unavailable' },
  async () => {
    const tmp = await mkdtemp(join(tmpdir(), 'ddk-owner-config-'));
    try {
      const dataDir = join(tmp, 'data');
      const pubDir = join(tmp, 'pub-catalog');
      const locDir = join(tmp, 'loc-catalog');
      execFileSync('mkdir', ['-p', dataDir, pubDir, locDir]);

      const parquetPath = join(dataDir, 'items.parquet');
      execFileSync(
        TEST_PARQUET_WRITER_PYTHON,
        [
          '-c',
          `
import sys
from decimal import Decimal
import pyarrow as pa
import pyarrow.parquet as pq

schema = pa.schema([("code", pa.string()), ("amount", pa.decimal128(12, 2))])
table = pa.Table.from_pylist([
    {"code": "A1", "amount": Decimal("42.50")},
    {"code": "B2", "amount": Decimal("10.00")},
], schema=schema)
pq.write_table(table, sys.argv[1])
`,
          parquetPath,
        ],
        { stdio: 'pipe' },
      );
      const parquetSha = sha256(await readFile(parquetPath));

      const sqlText = 'SELECT code, amount FROM items WHERE code = $target_code;\n';

      const makeCatalog = (audience: 'public' | 'local'): Omit<Catalog, 'files' | 'runs'> => ({
        specVersion: '0.1',
        kind: 'catalog',
        id: 'urn:test:paired:catalog',
        version: '1.0.0',
        audience,
        project: { id: 'urn:test:paired:project', version: '1.0.0' },
        sourceInventory: [],
        adapters: [],
        products: [],
        datasets: [
          {
            id: 'urn:test:paired:dataset:items',
            alias: 'items',
            definition: {
              contractId: 'urn:test:paired:contract:items',
              object: 'items',
              version: '1.0.0',
              source: { uri: 'urn:test:def:items', sha256: '1'.repeat(64) },
            },
          },
        ],
        identities: [],
        relationships: [],
        recipes:
          audience === 'local'
            ? [
                {
                  id: 'urn:test:paired:recipe:by_code',
                  sql: 'recipes/by_code.sql',
                  dialect: 'datafusion',
                  inputs: { items: 'items' },
                  relationships: [],
                  parameters: {
                    type: 'object',
                    required: ['target_code'],
                    additionalProperties: false,
                    properties: { target_code: { type: 'string' } },
                  },
                },
              ]
            : [],
        versions: [
          {
            id: 'urn:test:paired:version:items:1',
            dataset: 'items',
            ...(audience === 'local'
              ? {
                  reference: {
                    scheme: 'urn:ddk:version:local-file-sha256',
                    authority: 'urn:ddk:local-file',
                    value: { location: pathToFileURL(parquetPath).href, sha256: parquetSha },
                  },
                }
              : {
                  referenceDisclosure: 'withheld' as const,
                }),
            retention: 'present',
            scope: 'Synthetic paired test version.',
            record: { uri: 'urn:test:version-record', sha256: '7'.repeat(64) },
            sources: [],
            coverage: [],
          },
        ],
        sources: [],
        representations: [
          {
            id: 'urn:test:paired:rep:items:1',
            version: 'urn:test:paired:version:items:1',
            kind: 'file',
            availability: audience === 'local' ? 'available' : 'unavailable',
            mediaType: 'application/vnd.apache.parquet',
            ...(audience === 'local' ? { location: pathToFileURL(parquetPath).href } : {}),
            record: { uri: 'urn:test:rep-record', sha256: '7'.repeat(64) },
          },
        ],
        releases: [],
        selections: [],
        productions: [],
        checks: [],
      });

      const pubLocks = await writeCatalogArtifacts(pubDir, makeCatalog('public'));
      const locLocks = await writeCatalogArtifacts(locDir, makeCatalog('local'), {
        'recipes/by_code.sql': sqlText,
      });

      const configPath = join(tmp, 'owners.json');
      await writeFile(
        configPath,
        JSON.stringify({
          catalogs: [
            {
              id: 'paired-stack',
              navigationLabel: 'Paired Stack',
              navigationDescription: 'Zero-edit operator config test.',
              directory: pubDir,
              lockSha256: pubLocks.lockSha256,
              pairedLocalDirectory: locDir,
              pairedLocalLockSha256: locLocks.lockSha256,
              docspecBinary: DEFAULT_DOCSPEC_BINARY,
              docspecSha256: DEFAULT_DOCSPEC_SHA256,
              permittedRoots: [pubDir, locDir, dataDir],
            },
          ],
        }),
        'utf8',
      );

      // Public mode attaches no owner adapter and auto-populates catalogId from catalog.ddk.json
      const pubLoaded = await loadOperatorOwnerConfig(configPath, 'public');
      assert.equal(pubLoaded.registrations.length, 1);
      assert.equal(pubLoaded.registrations[0].directory, pubDir);
      assert.equal(pubLoaded.registrations[0].catalogId, 'urn:test:paired:catalog');
      assert.equal(pubLoaded.owners.size, 0);

      // Local mode switches to pairedLocalDirectory + pairedLocalLockSha256 and attaches pure-Rust owner
      const locLoaded = await loadOperatorOwnerConfig(configPath, 'local');
      try {
        assert.equal(locLoaded.registrations[0].directory, locDir);
        assert.equal(locLoaded.registrations[0].catalogId, 'urn:test:paired:catalog');
        assert.equal(locLoaded.owners.size, 1);

        const store = new CatalogStore(locLoaded.registrations, 'local');
        const snap = await store.snapshot('paired-stack');
        const access = new CatalogAccess(store, locLoaded.owners);
        const queryRes = await access.query({
          catalogId: 'paired-stack',
          catalogSha256: snap.identity.catalogSha256,
          recipeId: 'urn:test:paired:recipe:by_code',
          bindings: {
            items: {
              datasetId: 'urn:test:paired:dataset:items',
              versionId: 'urn:test:paired:version:items:1',
              representationId: 'urn:test:paired:rep:items:1',
            },
          },
          parameters: { target_code: 'A1' },
          limit: 10,
        });
        assert.equal(queryRes.status, 'ok');
        assert.equal(queryRes.returned, 1);
        assert.deepEqual(exactObjectField(queryRes.rows[0], 'code'), 'A1');
        assert.deepEqual(exactObjectField(queryRes.rows[0], 'amount'), { $number: '42.50' });
        assert.equal(queryRes.execution?.engine?.id, 'docspec');
        assert.equal(queryRes.execution?.engine?.binarySha256, DEFAULT_DOCSPEC_SHA256);
      } finally {
        for (const owner of locLoaded.owners.values()) {
          await owner.close();
        }
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  },
);

test('DocSpecCatalogOwner refuses missing docspecBinary with owner_unavailable', async () => {
  await assert.rejects(
    createDocSpecCatalogOwner({
      directory: congressRegistration.directory,
      lockSha256: congressRegistration.lockSha256,
      docspecBinary: '/nonexistent/docspec-binary',
      permittedRoots: [congressRegistration.directory],
    }),
    (err: any) => err?.code === 'owner_unavailable',
  );
});
