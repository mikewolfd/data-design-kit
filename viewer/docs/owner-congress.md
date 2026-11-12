# Congress saved-example reader

The optional `congress-authored` registration connects the generic viewer to the maintained Congress archive reader. It reads the original retained source20 rich example: 17 Parquet files containing 52 rows. These are authored synthetic records, not a live congressional archive.

The separate `congress` registration remains the original public, metadata-only catalog. The Commerce registration and its owner runtime are unchanged.

## Inputs and identities

The local publisher handoff contains 23 dataset definitions, 17 exact file versions and representations, one run and 160 checks. It declares no standard releases or publisher selections. The viewer retains all 20 standard control files byte for byte under `fixtures/applications/congress-authored/` and copies no Parquet payloads.

The local catalog identifies each original file through its location and SHA-256. `congress-registration.ts` checks those references against the publisher's `data-files.json`, original inventory and manifest before a read. The original archive release ID remains separate provenance; it is never inserted into the standard catalog or used as `binding.releaseId`.

The original reader consumes its original public archive controls. The viewer uses the separate local catalog for version and representation selection. This preserves each owner's existing input format.

## Optional configuration

Metadata browsing needs no external Congress checkout. To connect reads, an operator supplies a pinned configuration file through both environment variables:

```sh
DDK_VIEWER_AUDIENCE=local \
DDK_VIEWER_APPLICATIONS=congress-authored \
DDK_VIEWER_CONGRESS_OWNER_CONFIG=/absolute/path/to/owner-config.json \
DDK_VIEWER_CONGRESS_OWNER_CONFIG_SHA256=<exact-file-sha256> \
npm run preview
```

The JSON configuration contains an absolute `root` and a `files` array of `{ "path": "relative/source/path", "sha256": "..." }` entries. It must include the maintained `apps/site/src/components/explorer/reader/archive.ts`, `apps/site/scripts/archive-server.mjs`, every transitive relative source import, and `apps/site/package.json` and `package-lock.json`. Optional `sourceRevision` records repository context; the individual file hashes identify the actual loaded source bytes, including any uncommitted changes.

The JSON configuration verifies its `root` (and optional `pythonPath` or `files` allowlist) once at startup; HTTP requests cannot supply module, executable or filesystem paths. Changed source or Parquet bytes refuse until an operator supplies a reviewed configuration. Default builds and synthetic or metadata-only views require no external Congress checkout.

## Read behavior and evidence

`congress-registration.ts` delegates dataset pagination to the generic startup-pinned `DocSpecCatalogOwner` (`src/server/docspec-owner.ts` + `scripts/docspec-owner-bridge.py`) with a custom `resolveReadShards` hook that verifies each representation against the publisher's `data-files.json`, original `inventory.json` and release `manifest.json` before reading the requested `[offset, offset + limit)` slice via PyArrow (`parquet.ParquetFile`). It does not re-parse TypeScript imports per 25-row page or start producer jobs.

The adapter checks the archive release, file name, SHA-256, byte count, row count and positions, and decodes all Arrow scalar, decimal, integer, temporal, binary, list, struct and map types losslessly via `ddk-exact-json-v1` (`$number` for exact numeric/decimal lexemes, ISO-8601 strings preserving millisecond/microsecond/nanosecond precision, base64 for binary columns, and `$object` escaping for reserved keys). `readEvidence.details` holds response-bound facts: consumed binding, original file and manifest, row positions, physical schema and `ownerModule` provenance.

No generic filters, query execution, managed actions or publisher selection are connected. Available recipe descriptions remain metadata. Source20 same-runtime recovery evidence does not establish a fresh-runtime gate, a later runtime version, live archive acceptance or publication.

## Verification

Run the normal unit, type and build checks. The configured integration test in `tests/unit/congress-reader.test.ts` uses the operator variables above; without them, it explicitly skips external owner reads. It checks every materialized dataset, page boundaries, empty tables, exact identities, cancellation and refusals.

`tests/browser/congress-authored.spec.ts` requires the configured local preview. It exercises actual retained reads, explicit version selection, exact identifiers, nested occurrences and downloads. Routine Commerce tests remain replay-only unless fresh native acceptance is explicitly enabled.

The current integration report and separate review evidence are in the evidence archive's `outputs/viewer-congress-integration-20261106/` (see the README). Each report identifies the precise module configuration used; a changed owner source pin requires renewed acceptance.
