import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Connections } from '../../src/components/Connections';
import { Activity, Overview } from '../../src/components/MetadataPanels';
import { exactStringify } from '../../src/domain/exact';
import type { Catalog } from '../../src/domain/types';
import { CoverageContext, DateContext } from '../../src/features/dataset-context/CoverageDates';
import { ProvenanceContext } from '../../src/features/dataset-context/Sources';
import { publisherMetadata } from '../../src/features/publisher-metadata';
import { ResourceDetails } from '../../src/features/resource-details/ResourceDetails';
import { datasetIntroduction } from '../../src/lib/content';
import { CatalogStore, LIMITS, sha256, type CatalogRegistration } from '../../src/server/catalog-store';
import { loadImpact, MAX_ARTIFACT_BYTES } from '../../src/server/impact';

async function buildCatalogDir(
  dir: string,
  catalogWithoutFiles: Omit<Catalog, 'files' | 'runs'> & { runs?: Catalog['runs'] },
  opts: {
    companions?: Record<string, string>;
    extraLockInputCount?: number;
  } = {},
): Promise<{ lockSha256: string; catalogSha256: string }> {
  await mkdir(dir, { recursive: true });
  const report = {
    specVersion: '0.1',
    kind: 'report',
    id: `${catalogWithoutFiles.id}:report`,
    version: catalogWithoutFiles.version,
    decision: 'passed',
    checks: [
      {
        id: 'core-check',
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
  };
  const reportBytes = Buffer.from(JSON.stringify(report) + '\n');
  const reportSha = sha256(reportBytes);
  await writeFile(join(dir, 'catalog.report.json'), reportBytes);

  const companionFiles: { path: string; sha256: string; role: string }[] = [
    { path: 'catalog.report.json', sha256: reportSha, role: 'report' },
  ];
  for (const [relPath, content] of Object.entries(opts.companions ?? {})) {
    const full = join(dir, relPath);
    await mkdir(dirname(full), { recursive: true });
    const buf = Buffer.from(content, 'utf8');
    await writeFile(full, buf);
    companionFiles.push({
      path: relPath,
      sha256: sha256(buf),
      role: relPath.endsWith('.sql') ? 'recipe' : 'metadata',
    });
  }

  const fullCatalog: Catalog = {
    ...catalogWithoutFiles,
    runs: catalogWithoutFiles.runs ?? [],
    files: companionFiles,
  };
  const catalogBytes = Buffer.from(exactStringify(fullCatalog) + '\n');
  const catalogSha = sha256(catalogBytes);
  await writeFile(join(dir, 'catalog.ddk.json'), catalogBytes);

  const lockInputs = [...companionFiles];
  const extraInputs = opts.extraLockInputCount ?? 0;
  for (let i = 0; i < extraInputs; i++) {
    lockInputs.push({
      path: `inputs/definition-${String(i).padStart(4, '0')}.json`,
      sha256: sha256(Buffer.from(`input-${i}`)),
      role: 'definition',
    });
  }

  const lock = {
    specVersion: '0.1',
    kind: 'lock',
    id: `${fullCatalog.id}:lock`,
    version: fullCatalog.version,
    project: fullCatalog.project.id,
    catalogOptions: { audience: fullCatalog.audience, exports: [] },
    files: lockInputs,
    extensions: {
      'urn:ddk:catalog:output-set': [
        { path: 'catalog.ddk.json', sha256: catalogSha, role: 'catalog' },
        ...companionFiles,
      ],
    },
  };
  const lockBytes = Buffer.from(JSON.stringify(lock) + '\n');
  const lockSha = sha256(lockBytes);
  await writeFile(join(dir, 'catalog.lock.json'), lockBytes);
  return { lockSha256: lockSha, catalogSha256: catalogSha };
}

test('RG-2 lifts toy diorama caps: admits 350+ lock files / 220+ companions and compares >3.8 MiB impact catalogs without 413', async () => {
  assert.equal(LIMITS.files, 2048);
  assert.equal(LIMITS.fileBytes, 16 * 1024 * 1024);
  assert.equal(LIMITS.retainedBytes, 128 * 1024 * 1024);
  assert.equal(LIMITS.lockBytes, 4 * 1024 * 1024);
  assert.equal(MAX_ARTIFACT_BYTES, 16 * 1024 * 1024);

  const tmp = await mkdtemp(join(tmpdir(), 'ddk-rg2-scale-'));
  try {
    const catDir = join(tmp, 'spicy-scale');
    const impactDir = join(tmp, 'impact');
    await mkdir(impactDir, { recursive: true });

    const companions: Record<string, string> = {};
    for (let i = 0; i < 220; i++) {
      companions[`companions/item-${String(i).padStart(4, '0')}.sql`] =
        `SELECT ${i} AS idx;\n`;
    }

    // Pad description strings so catalog.ddk.json exceeds 3.9 MiB (matching real 3.8 MB SpicyRegs)
    const largePad = 'Federal docket regulatory summary block. '.repeat(2600); // ~106 KB
    const datasets = Array.from({ length: 40 }, (_, idx) => ({
      id: `urn:test:spicy:dataset:ds-${idx}`,
      alias: `ds-${idx}`,
      title: `Regulatory Dataset ${idx}`,
      role: 'derived',
      origin: 'derived' as const,
      rowMeaning: `One regulatory docket row (${idx}).`,
      description: `Dataset ${idx}: ${largePad}`,
      definition: {
        contractId: `urn:test:spicy:contract:${idx}`,
        object: `ds_${idx}`,
        version: '1.0.0',
        source: { uri: `urn:test:def:${idx}`, sha256: 'a'.repeat(64) },
      },
    }));

    const baseCatalogShape: Omit<Catalog, 'files'> = {
      specVersion: '0.1',
      kind: 'catalog',
      id: 'urn:test:spicy:catalog',
      version: '1.0.0',
      audience: 'public',
      project: { id: 'urn:test:spicy:project', version: '1.0.0' },
      sourceInventory: [{ uri: 'urn:test:src', sha256: '1'.repeat(64), role: 'project' }],
      adapters: [{ id: 'ddk.catalog', version: '0.1.0' }],
      products: [],
      datasets,
      identities: [],
      relationships: [],
      recipes: [],
      versions: [],
      sources: [],
      representations: [],
      releases: [],
      selections: [],
      productions: [],
      runs: [],
      checks: [],
    };

    const { lockSha256, catalogSha256 } = await buildCatalogDir(catDir, baseCatalogShape, {
      companions,
      extraLockInputCount: 150, // 221 companions + 150 extra lock inputs = 371 lock files (> 64!)
    });

    const reg: CatalogRegistration = {
      id: 'spicy-scale',
      mode: 'application',
      navigationLabel: 'Spicy Scale',
      navigationDescription: '371 lock files + >3.9 MiB catalog.ddk.json',
      directory: catDir,
      lockSha256,
    };
    const store = new CatalogStore([reg], 'public');
    const snap = await store.snapshot('spicy-scale');
    assert.equal(snap.catalog.datasets.length, 40);
    assert.equal(snap.catalog.files.length, 221);

    // Write >3.9 MiB base.catalog.ddk.json and impact.report.json and verify loadImpact succeeds without 413
    const baseCatalogDoc = {
      ...baseCatalogShape,
      version: '0.9.0',
      files: [],
    };
    const baseBytes = Buffer.from(JSON.stringify(baseCatalogDoc) + '\n');
    assert.ok(baseBytes.byteLength > 3.8 * 1024 * 1024, `Expected >3.8 MiB, got ${baseBytes.byteLength}`);
    const baseSha = sha256(baseBytes);
    await writeFile(join(impactDir, 'base.catalog.ddk.json'), baseBytes);

    const impactReportDoc = {
      specVersion: '0.1',
      kind: 'report',
      summary: 'Comparison across 40 regulatory tables.',
    };
    const impactReportBytes = Buffer.from(JSON.stringify(impactReportDoc) + '\n');
    const impactReportSha = sha256(impactReportBytes);
    await writeFile(join(impactDir, 'impact.report.json'), impactReportBytes);

    const bindingDoc = {
      baseCatalogSha256: baseSha,
      candidateCatalogSha256: catalogSha256,
      reportSha256: impactReportSha,
    };
    const bindingBytes = Buffer.from(JSON.stringify(bindingDoc) + '\n');
    const bindingSha = sha256(bindingBytes);
    await writeFile(join(impactDir, 'binding.json'), bindingBytes);

    const impactResult = await loadImpact(
      store,
      [{ catalogId: 'spicy-scale', directory: impactDir, bindingSha256: bindingSha }],
      'spicy-scale',
      catalogSha256,
    );
    assert.equal(impactResult.available, true);
    if (impactResult.available) {
      assert.equal(impactResult.base.version, '0.9.0');
    }
  } finally {
    await rm(tmp, { recursive: true, force: true });
  }
});

test('T3.1 & T2.2 core-first metadata, cross-catalog jump links, unresolvedReason, joinMetrics and shared concepts render cleanly', async () => {
  const tmp = await mkdtemp(join(tmpdir(), 'ddk-core-sync-fed-'));
  try {
    const congressDir = join(tmp, 'congress-peer');
    const spicyDir = join(tmp, 'spicy-peer');

    // 1. Register peer Congress catalog
    const congressCatalog: Omit<Catalog, 'files'> = {
      specVersion: '0.1',
      kind: 'catalog',
      id: 'urn:congressional-tech:archive:catalog',
      version: '2026.11.11',
      audience: 'public',
      project: { id: 'urn:congressional-tech:archive:project', version: '1.0.0' },
      sourceInventory: [{ uri: 'urn:congress:src', sha256: '1'.repeat(64), role: 'project' }],
      adapters: [{ id: 'ddk.catalog', version: '0.1.0' }],
      products: [],
      datasets: [
        {
          id: 'urn:congressional-tech:archive:dataset:bills',
          alias: 'bills',
          title: 'Congressional Bills',
          origin: 'publisher',
          rowMeaning: 'One congressional bill.',
          definition: {
            contractId: 'urn:congress:contract:bills',
            object: 'bills',
            version: '1.0.0',
            source: { uri: 'urn:congress:def:bills', sha256: '2'.repeat(64) },
          },
        },
      ],
      identities: [],
      relationships: [],
      recipes: [],
      versions: [],
      sources: [],
      representations: [],
      releases: [],
      selections: [],
      productions: [],
      runs: [],
      checks: [],
    };
    const congressPins = await buildCatalogDir(congressDir, congressCatalog);

    // 2. Register SpicyRegs catalog with T3.1 core metadata + T2.2 cross-catalog imports, relationships & concepts (NO urn:ddk:publisher:discovery extension!)
    const spicyCatalog: Omit<Catalog, 'files'> = {
      specVersion: '0.1',
      kind: 'catalog',
      id: 'urn:spicyregs:catalog',
      version: '2026.11.11',
      audience: 'public',
      project: { id: 'urn:spicyregs:project', version: '1.0.0' },
      imports: {
        congress: {
          id: 'urn:congressional-tech:archive:catalog',
          audience: 'public',
          lockSha256: congressPins.lockSha256,
        },
      },
      concepts: [
        {
          concept: 'urn:ddk:concept:us-congress-bill-id',
          definition: 'urn:ddk:def:bill-id',
          conceptKind: 'identifier',
          iriTemplate: 'https://www.congress.gov/bill/{value}',
          description: 'Canonical Congress-number-prefixed bill identifier (e.g. 119-hr-1).',
          exactMatch: ['https://schema.org/legislationIdentifier'],
          closeMatch: ['https://wikidata.org/entity/Q686822'],
          fields: [
            { dataset: 'docket-bills', path: [{ field: 'bill_id' }] },
            { catalog: 'congress', dataset: 'bills', path: [{ field: 'bill_id' }] },
          ],
        },
      ],
      sourceInventory: [{ uri: 'urn:spicy:src', sha256: '4'.repeat(64), role: 'project' }],
      adapters: [{ id: 'ddk.catalog', version: '0.1.0' }],
      products: [],
      datasets: [
        {
          id: 'urn:spicyregs:dataset:docket-bills',
          alias: 'docket-bills',
          title: 'Docket-to-Bill Citations',
          role: 'derived',
          origin: 'derived',
          status: 'published',
          model: { id: 'urn:spicyregs:model:bill-extractor', version: '2.3.0' },
          methodColumn: 'extraction_method',
          rowMeaning: 'One extracted citation from a rulemaking docket to a congressional bill.',
          description: 'Connects federal rulemaking dockets to cited congressional legislation.',
          tags: ['rulemaking', 'legislation'],
          context: {
            instructions: 'Extracted from Federal Register preambles and comment attachments.',
          },
          contract: {
            description: {
              purpose: 'Connects federal rulemaking dockets to cited congressional legislation.',
              limitations: 'Heuristic regex extraction may miss unnumbered popular-name bill citations.',
              usage: 'Join on normalized bill_id against Congress bills.',
            },
            slaProperties: [
              { property: 'freshness', value: 'daily' },
              { property: 'uptime_target', value: { $number: '99.95' } },
            ],
            canonicalUrls: ['https://spicyregs.example.org/docs/docket-bills'],
          },
          definition: {
            contractId: 'urn:spicyregs:contract:docket-bills',
            object: 'docket_bills',
            version: '1.2.0',
            source: { uri: 'urn:spicy:def:docket-bills', sha256: '5'.repeat(64) },
          },
        },
      ],
      identities: [
        {
          dataset: 'docket-bills',
          kind: 'key',
          scope: 'dataset_version',
          meaning: 'Composite docket + bill citation key.',
          fields: [
            { path: [{ field: 'docket_id' }], virtual: false, physicalType: 'string' },
            { path: [{ field: 'bill_id' }], virtual: false, physicalType: 'string' },
          ],
        },
      ],
      relationships: [
        {
          id: 'urn:spicyregs:rel:docket-to-congress-bill',
          source: { dataset: 'docket-bills', paths: [[{ field: 'bill_id' }]] },
          target: {
            catalog: 'congress',
            dataset: 'bills',
            paths: [[{ field: 'bill_id' }]],
          },
          match: 'equal',
          cardinality: 'many_to_one',
          scope: 'version_pair',
          resolution: 'unresolved_allowed',
          unresolvedReason: 'scope_boundary',
          joinMetrics: {
            matchedRows: 842,
            totalSourceRows: 1000,
            floorPct: { $number: '84.20' },
            basis: 'Measured against 118th–119th Congress archive; pre-118th bills are out of scope.',
            record: { uri: 'urn:spicy:metrics:bill-join', sha256: '6'.repeat(64) },
          },
          meaning: 'Matches cited bill_id to its Congressional Bills record in the Congress catalog.',
          nulls: 'reject',
        },
        {
          id: 'urn:spicyregs:rel:docket-to-regs-gov',
          source: { dataset: 'docket-bills', paths: [[{ field: 'docket_id' }]] },
          target: {
            external: 'https://www.regulations.gov',
            externalDataset: 'Regulations.gov Dockets API v4',
            externalKeyFields: ['docketId'],
            limitations: 'Withdrawn dockets return HTTP 404 in the upstream API.',
          },
          match: 'equal',
          cardinality: 'many_to_one',
          scope: 'external',
          resolution: 'external',
          meaning: 'Links each docket_id to the upstream Regulations.gov docket.',
          nulls: 'reject',
        },
      ],
      recipes: [
        {
          id: 'urn:spicyregs:recipe:cross-bill-summary',
          title: 'Cross-catalog docket bill join preview',
          sql: 'recipes/cross_bill_summary.sql',
          dialect: 'datafusion',
          inputs: {
            docket_bills: 'docket-bills',
            congress_bills: { catalog: 'congress', dataset: 'bills' },
          },
          relationships: ['urn:spicyregs:rel:docket-to-congress-bill'],
          parameters: { type: 'object', properties: {}, additionalProperties: false },
          resultGrain: 'One row per cited congressional bill.',
        },
      ],
      versions: [
        {
          id: 'urn:spicyregs:version:docket-bills:2026-11-11',
          dataset: 'docket-bills',
          referenceDisclosure: 'withheld',
          retention: 'present',
          scope: 'Published rulemaking citations through 2026-11-10.',
          record: { uri: 'urn:spicy:version-record', sha256: 'a'.repeat(64) },
          sources: [],
          dates: {
            publishedAt: '2026-11-11T08:00:00Z',
            retrievedAt: '2026-11-11T06:30:00Z',
            sourceUpdatedAt: '2026-11-10T23:59:59Z',
          },
          coverage: [
            {
              scope: 'Published rulemaking citations.',
              status: 'complete',
              kind: 'true_range',
              stage: 'published',
              observed: 1000,
              expected: 1000,
              unit: 'rows',
              bounds: {
                field: 'published_date',
                min: '2023-01-03',
                max: '2026-11-10',
              },
              record: { uri: 'urn:spicy:coverage-record', sha256: 'b'.repeat(64) },
            },
          ],
        },
      ],
      sources: [],
      representations: [
        {
          id: 'urn:spicyregs:rep:docket-bills:parquet',
          version: 'urn:spicyregs:version:docket-bills:2026-11-11',
          kind: 'file',
          availability: 'unavailable',
          mediaType: 'application/vnd.apache.parquet',
          byteSize: 4_194_304,
          rowCount: 1000,
          record: { uri: 'urn:spicy:rep-record', sha256: 'c'.repeat(64) },
          members: [
            {
              path: 'shards/part-0000.parquet',
              sha256: '7'.repeat(64),
              byteSize: 2_097_152,
              rowCount: 500,
              rowRange: [0, 500],
            },
            {
              path: 'shards/part-0001.parquet',
              sha256: '8'.repeat(64),
              byteSize: 2_097_152,
              rowCount: 500,
              rowRange: [500, 1000],
            },
          ],
        },
      ],
      releases: [],
      selections: [],
      productions: [
        {
          alias: 'build-docket-bills-job',
          kind: 'job',
          identity: { id: 'urn:spicyregs:job:docket-bills', version: '2.3.0' },
          definition: { uri: 'urn:spicy:job-def', sha256: '9'.repeat(64) },
          inputs: [],
          outputs: ['docket-bills'],
          steps: [
            { id: 'extract_citations', kind: 'sql', sqlSha256: 'a'.repeat(64) },
            { id: 'export_docket_bills', kind: 'export' },
          ],
        },
      ],
      runs: [],
      checks: [],
    };

    const spicyPins = await buildCatalogDir(spicyDir, spicyCatalog, {
      companions: {
        'recipes/cross_bill_summary.sql':
          'SELECT d.docket_id, b.bill_id FROM docket_bills d JOIN congress_bills b ON d.bill_id = b.bill_id;\n',
      },
    });

    const store = new CatalogStore(
      [
        {
          id: 'spicy-fed',
          mode: 'application',
          navigationLabel: 'SpicyRegs',
          navigationDescription: 'Federal rulemaking catalog',
          directory: spicyDir,
          lockSha256: spicyPins.lockSha256,
        },
        {
          id: 'congress-fed',
          mode: 'application',
          navigationLabel: 'Congress Explorer',
          navigationDescription: 'Congressional archive catalog',
          directory: congressDir,
          lockSha256: congressPins.lockSha256,
        },
      ],
      'public',
    );

    // Load both snapshots so store.list() populates catalogId on both CatalogSummary entries
    const spicySnap = await store.snapshot('spicy-fed');
    await store.snapshot('congress-fed');
    const { catalogs: summaries } = await store.list();

    const dataset = spicySnap.catalog.datasets[0];
    const version = spicySnap.catalog.versions[0];
    const representation = spicySnap.catalog.representations[0];

    // Core metadata synthesis without urn:ddk:publisher:discovery
    const pubMeta = publisherMetadata(spicySnap);
    assert.deepEqual(pubMeta.refusals, []);
    const intro = datasetIntroduction(spicySnap, dataset);
    assert.equal(
      intro.purpose,
      'Connects federal rulemaking dockets to cited congressional legislation.',
    );
    assert.equal(
      intro.coverageNote,
      'Heuristic regex extraction may miss unnumbered popular-name bill citations.',
    );
    assert.equal(intro.usage, 'Join on normalized bill_id against Congress bills.');

    // Render Overview and verify origin, status, model, methodColumn, tags, context, SLA, canonical URL
    const overviewHtml = renderToStaticMarkup(
      createElement(Overview, { snapshot: spicySnap, dataset, version }),
    );
    assert.match(overviewHtml, /Derived/);
    assert.match(overviewHtml, /urn:spicyregs:model:bill-extractor/);
    assert.match(overviewHtml, /extraction_method/);
    assert.match(overviewHtml, /rulemaking, legislation/);
    assert.match(overviewHtml, /freshness/);
    assert.match(overviewHtml, /https:\/\/spicyregs\.example\.org\/docs\/docket-bills/);

    // Render CoverageContext & DateContext and verify version.dates + coverage.{kind, stage, bounds}
    const coverageHtml = renderToStaticMarkup(
      createElement(CoverageContext, { snapshot: spicySnap, dataset, version, representation }),
    );
    assert.match(coverageHtml, /published_date/);
    assert.match(coverageHtml, /2023-01-03/);
    assert.match(coverageHtml, /2026-11-10/);
    assert.match(coverageHtml, /True range/i);
    assert.match(coverageHtml, /Published/i);

    const dateHtml = renderToStaticMarkup(
      createElement(DateContext, { snapshot: spicySnap, dataset, version, representation }),
    );
    assert.match(dateHtml, /2026-11-11T08:00:00Z/);
    assert.match(dateHtml, /2026-11-11T06:30:00Z/);
    assert.match(dateHtml, /2026-11-10T23:59:59Z/);
    assert.match(dateHtml, /99\.95/);

    // Render ProvenanceContext & Activity and verify origin + kind: 'job' production steps
    const provHtml = renderToStaticMarkup(
      createElement(ProvenanceContext, { snapshot: spicySnap, dataset, version, representation }),
    );
    assert.match(provHtml, /Derived/);
    assert.match(provHtml, /urn:spicyregs:model:bill-extractor/);

    const activityHtml = renderToStaticMarkup(
      createElement(Activity, { snapshot: spicySnap, dataset, version }),
    );
    assert.match(activityHtml, /build-docket-bills-job/);
    assert.match(activityHtml, /extract_citations/);
    assert.match(activityHtml, /export_docket_bills/);

    // Render ResourceDetails and verify byteSize, rowCount, and Shard inventory members[]
    const resourceHtml = renderToStaticMarkup(
      createElement(ResourceDetails, { snapshot: spicySnap, dataset, version }),
    );
    assert.match(resourceHtml, /1,000/);
    assert.match(resourceHtml, /Shard inventory \(2\)/);
    assert.match(resourceHtml, /shards\/part-0000\.parquet/);
    assert.match(resourceHtml, /range \[0, 500\)/);
    assert.match(resourceHtml, /range \[500, 1000\)/);

    // Render Connections with peer catalog summaries and verify cross-catalog badge + jump link + unresolvedReason + joinMetrics + externalTarget + concepts!
    const connectionsHtml = renderToStaticMarkup(
      createElement(Connections, {
        snapshot: spicySnap,
        dataset,
        version,
        catalogs: summaries,
        onNavigate: () => {},
      }),
    );
    assert.match(connectionsHtml, /Peer catalog: congress · public/);
    assert.match(
      connectionsHtml,
      /href="\/\?catalog=congress-fed&amp;dataset=bills&amp;tab=Overview"/,
    );
    assert.match(connectionsHtml, /Open in Congress Explorer · bills ↗/);
    assert.match(connectionsHtml, /Scope boundary/i);
    assert.match(connectionsHtml, /84\.20%/);
    assert.match(connectionsHtml, /842 matched of 1,000 source rows/);
    assert.match(
      connectionsHtml,
      /Measured against 118th–119th Congress archive; pre-118th bills are out of scope\./,
    );
    assert.match(connectionsHtml, /Regulations\.gov Dockets API v4/);
    assert.match(connectionsHtml, /docketId/);
    assert.match(connectionsHtml, /Withdrawn dockets return HTTP 404 in the upstream API\./);
    assert.match(connectionsHtml, /urn:ddk:concept:us-congress-bill-id/);
    assert.match(connectionsHtml, /https:\/\/www\.congress\.gov\/bill\/\{value\}/);
    assert.match(connectionsHtml, /https:\/\/schema\.org\/legislationIdentifier/);
    assert.match(connectionsHtml, /Congress Explorer · bills ↗/);

    // Also verify graceful fallback when peer catalog is not registered in this portal instance
    const isolatedHtml = renderToStaticMarkup(
      createElement(Connections, {
        snapshot: spicySnap,
        dataset,
        version,
        catalogs: summaries.filter((entry) => entry.id === 'spicy-fed'),
        onNavigate: () => {},
      }),
    );
    assert.match(isolatedHtml, /congress:bills/);
    assert.match(
      isolatedHtml,
      /Declared peer catalog <code>urn:congressional-tech:archive:catalog<\/code> is not registered/,
    );
  } finally {
    await rm(tmp, { recursive: true, force: true });
  }
});
