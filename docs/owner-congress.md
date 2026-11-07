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

The viewer verifies all listed files and uses the installed TypeScript scanner to check the relative import list before loading owner code. HTTP requests cannot supply module, executable or filesystem paths. Changed source bytes refuse until an operator supplies a reviewed configuration. Node package dependencies remain installed and owned by the Congress checkout; their package files are pinned, not repackaged by the viewer.

This is a local source adapter. It requires the retained original input paths, configured Congress checkout with its installed dependencies, and the viewer's installed `tsx` and TypeScript packages. A portable owner-module distribution remains separate work. Default builds and synthetic or metadata-only views do not load the external module.

## Read behavior and evidence

Each read binds the requested catalog, dataset, version and representation. It starts the maintained read-only archive transport over the original inventory, opens `openArchive(..., { mode: 'rows' })`, calls `readRows` for the requested original file range, and closes the transport in `finally`. It does not start native computation or producer jobs.

The adapter checks the returned archive release, file name, SHA-256, byte count, row count and positions. The viewer receives every original column. Integer and floating-point values use exact numeric transport; bigint values never pass through JavaScript numbers. Owner-marked dates and timestamps retain days or their original millisecond, microsecond or nanosecond unit. Actual binary values use base64. The original physical schema travels with each page so those encodings remain distinguishable from source structs with similar field names. Reserved source keys use the existing exact JSON escape form.

`readEvidence.details` holds response-bound facts: consumed binding, original file and manifest, row positions, physical schema, module configuration and source pins. It is not a persisted read receipt, a new release, or a publication claim. Page downloads retain this evidence.

The generic viewer limits pages to 100 rows and the complete response to 256 KiB. The local adapter limits the retained release and total source allowlist to 16 MiB each, owner working allocation to 32 MiB, and each owner page budget to 16 MiB. That page budget admits compressed Parquet files up to 1 MiB under the owner's allocation checks. The generic deadline and two-read concurrency limits also apply. Owner admission can refuse sooner when a row group or schema metadata does not fit; a small returned page is not a promise that its source file can be decoded within those limits.

The owner refuses unsupported lossy annotations such as DECIMAL, MAP, JSON and INT96 before decoding. The viewer also refuses non-finite numbers instead of converting them to null. Budget, schema and identity failures remain explicit errors. This example does not establish support for every Parquet type or arbitrary production-sized files.

The maintained transport verifies the whole retained release for each page. For this example that is 39 assets totaling 357,621 bytes, plus the manifest and configured source checks. This behavior is bounded for the saved example; it is not a scalable service or streaming-read qualification.

No generic filters, query execution, managed actions or publisher selection are connected. Available recipe descriptions remain metadata. Source20 same-runtime recovery evidence does not establish a fresh-runtime gate, a later runtime version, live archive acceptance or publication.

## Verification

Run the normal unit, type and build checks. The configured integration test in `tests/unit/congress-reader.test.ts` uses the operator variables above; without them, it explicitly skips external owner reads. It checks every materialized dataset, page boundaries, empty tables, exact identities, cancellation and refusals.

`tests/browser/congress-authored.spec.ts` requires the configured local preview. It exercises actual retained reads, explicit version selection, exact identifiers, nested occurrences and downloads. Routine Commerce tests remain replay-only unless fresh native acceptance is explicitly enabled.

The current integration report and separate review evidence are in `outputs/viewer-congress-integration-20261106/`. Each report identifies the precise module configuration used; a changed owner source pin requires renewed acceptance.
