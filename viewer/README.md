# DDK viewer

A data catalog for finding datasets, understanding their fields and limits, and exploring available records. The React interface is served by Astro and reads standard Data Design Kit catalogs. Engineers can inspect exact identifiers, source definitions, checks and publisher selections in technical details.

**November 13, 2026 verification:** 112 unit tests, 65 browser tests and two additional historical replay checks passed with zero skips; type checking and build passed. [Exact source and native identities](../docs/verification.md#november-13-2026-zero-skip-installed-and-viewer-checks). Work is tracked in the repository-root [.tickets](../.tickets/) store and [prioritized backlog](../docs/work-backlog.md); `tk` finds that store from this directory. Historical owner-guide details are being reconciled through the [current portable handoff](../.tickets/ddk-c7v1.md).

## Run locally

```sh
npm ci
npm run dev
```

Open http://127.0.0.1:4321. npm scripts use the pinned project-local Node 22.23.4; no system Node change is required. Install dependencies with a working Node/npm installation. `npm run build` checks TypeScript and produces the Astro Node build. Stop the development server with Ctrl+C before using `npm run preview` on the same local port.

The two default configurations are independently authored synthetic catalogs: watershed observations and public-service grants. Both include exact versions, scoped relationships, recipes, unknown/missing qualification, and unavailable evidence. Their data is labelled as demonstration data. They do not establish DDK assembly acceptance or native runtime qualification.

To include the read-only application catalogs captured for this task:

```sh
DDK_VIEWER_APPLICATIONS=spicy-regs,congress npm run dev
# or after building:
DDK_VIEWER_APPLICATIONS=spicy-regs,congress npm run preview
```

The allowlist in `src/server/registry.ts` pins each local directory and lock digest. Missing or changed sources refuse safely; no “latest” discovery or fallback data is used. These optional registrations use retained public metadata under `fixtures/applications/`. SpicyRegs is a public definition-only catalog regenerated from its maintained publisher definitions. Congress is a public application metadata fixture with 24 datasets and 16 recipes; its tiny physical reader fixtures do not establish full native candidate quality. The viewer opens neither application's row files. Their live data/query capabilities remain unavailable until an explicit owner adapter is registered.

To register any local or paired DDK catalog and optional startup-pinned `DocSpecCatalogOwner` without editing code, point `DDK_VIEWER_OWNER_CONFIG` at an operator JSON file:

```sh
DDK_VIEWER_AUDIENCE=local \
DDK_VIEWER_OWNER_CONFIG=/absolute/path/to/viewer-owners.json \
DDK_VIEWER_APPLICATIONS=spicy-slice \
npm run preview
```

Each entry in `DDK_VIEWER_OWNER_CONFIG` pins `id`, `directory`, `lockSha256` (plus optional `pairedLocalDirectory` and `pairedLocalLockSha256` when `DDK_VIEWER_AUDIENCE=local`), optional `docspecBinary` + `docspecSha256` + `docspecLimits`, and `permittedRoots`. `createDocSpecCatalogOwner` (`src/server/docspec-owner.ts` + native Rust `docspec owner-worker`) verifies the catalog lock and `docspec` binary SHA-256 once at server startup, paginates single-file or multi-shard `members[]` Parquet representations via bounded Rust Arrow row-group slice reads, executes checked DataFusion SQL recipes directly in Rust without Python subprocesses, and serves digest-verified `RecordRef` evidence records.

One retained owner-backed journey is also available from the pinned qualified commerce example:

```sh
DDK_VIEWER_AUDIENCE=local DDK_VIEWER_APPLICATIONS=spicy-regs,congress,commerce-native npm run preview
```

This routes `commerce-native` through `DocSpecCatalogOwner` to call the maintained DDK checked-query and DocSpec interfaces against the existing three-row Parquet result. The publisher copy refresh assigned a new definition-bound version, `667e1cdb…`, while preserving the original Parquet bytes and earlier `737bacee…` evidence. Current Commerce metadata uses DDK catalog dev5 and local metadata adapter 0.1.1; the bounded reader still uses the qualified dev4 package and dev2 native executable verified once at adapter startup. Select the explicit `daily-revenue` version, then use View data, the `checked-revenue` query under Related data, and Checks & sources. See [the connected commerce guide](docs/owner-commerce.md) for exact identities and limits.

The separate `congress-authored` local registration exposes a saved Congress example with 23 dataset definitions and 17 exact file versions. An optional, operator-pinned configuration connects its 52 retained authored records through `DocSpecCatalogOwner` (with `congress-registration.ts` verifying the publisher's `data-files.json`, inventory, and manifest); queries remain unavailable because the catalog declares `same_release` relationships with `releases: []`. Default builds and metadata browsing do not require external checkouts. See [the Congress reader guide](docs/owner-congress.md) for configuration, exact-value handling and qualification limits.

## What works

- Search dataset titles, descriptions and identifiers in the selected catalog. Filter by whether records can be opened here, and inspect collections and nested field definitions.
- Choose an exact version and representation, read bounded pages, filter exact scalar values, inspect ordered nested occurrences, and export the page with its request and visible-column context.
- Inspect ordered relationship keys, scope, null handling, unresolved-key reasons, observed join metrics, cross-catalog peer imports (`target.catalog` jump links when the peer catalog is registered), shared semantic `concepts`, external target details, and navigate exact same-release endpoints when resolvable. Other links explicitly open definitions.
- Inspect and run only registered recipes; exact SQL, parameters, real inputs (including cross-catalog input declarations), engine provenance receipts (`id`, `version`, `binarySha256`, `elapsedMs`), explanatory relationships, release and result identity remain visible.
- Inspect report and exact-version checks without converting declared, unknown, or not_run outcomes into passes. Inspect source occurrences, core dataset origin/model/method/contract metadata, version dates and coverage bounds, representation byte size/row count/shard `members[]`, runs, `job`/`component`/`design` production steps, release membership and publisher selections.
- Compare recorded versions and inspect a genuine `ddk.catalog_impact.compare_catalogs` report bound to exact base/candidate/report bytes. Metadata obligations, computation reuse, and qualification reuse stay distinct.
- Share a link bound to a catalog copy, dataset and selected version and export exact references, bounded pages, query results and impact evidence.

The shared runtime has no universal data-reader service in the qualified dev4 package. The connected commerce integration qualifies one bounded local-file consumer flow through existing owner APIs. Broader native binary/timestamp decoding, managed actions, streaming quality, retained multi-output execution, complete candidate accepted-evidence mapping and publication recovery require their actual owners' qualified adapters. This app does not implement an execution engine, scheduler, recovery journal or selection authority.

## Reuse and integration

The React UI in `src/components/` consumes `CatalogSnapshot` and the bounded interfaces in `src/domain/types.ts`. Astro routes are thin transport adapters. `src/server/registry.ts` is the composition root; it chooses permitted sources and optional owner adapters. Domain code contains no congressional or regulatory table registries.

Read [the adapter guide](docs/adapters.md) before registering an owner. Actual producer definitions and standard output files remain authoritative. Adapter capability disclosure must match the concrete registered adapter. An available representation does not imply a configured reader, and a reader result does not establish data qualification.

Exact numeric transport uses `ddk-exact-json-v1`. Every data number is represented as `{"$number":"original JSON lexeme"}`; source objects containing reserved tag fields are escaped as `{"$object":[["field",value],...]}`. `src/domain/exact.ts` supplies lossless parsing, numeric comparison, rendering and reconstruction. Missing fields, `null`, empty text, empty lists, ordering and duplicate list occurrences remain distinct. Use `exactStringify` to reconstruct ordinary JSON with exact numeric tokens; native timestamps and binary values must retain owner-defined type interpretation.

The UI uses semantic HTML, manual-activation keyboard tabs, a skip link, live status messages, visible focus, local table scrolling and reduced motion. The task hypotheses and information architecture are in [docs/design.md](docs/design.md). No user research or screen-reader certification is claimed.

## Verification

```sh
npm test
npm run check
npm run build
npm run test:browser
```

The browser suite expects a running local preview and uses installed Google Chrome. It tests desktop and 390px/320px mobile layouts, keyboard interaction, exact values, pagination, filter retry, refusal, response races, historical relationships, impact, exports and automated accessibility. Enable the two application registrations to include their browser check; otherwise that one test is explicitly skipped.

The Commerce checks replay the retained, previously verified Commerce responses without issuing another native read or query. That journey is evidence, kept in the evidence archive; point the suites at it explicitly, otherwise they skip those checks:

```sh
DDK_VIEWER_REPLAY_COMMERCE=<archive>/outputs/publisher-commerce-journey.json npm test
DDK_VIEWER_REPLAY_COMMERCE=<archive>/outputs/publisher-commerce-journey.json npm run test:browser
```

Replay checks the interface and exported identities; it does not requalify native execution. The unit check also reads the original owner Parquet and the receipt files under `work/native-consumer/`, which the runtime matches by absolute path, so it passes only from the archive checkout. The default synthetic and metadata views do not need those files.

Set `DDK_VIEWER_RUN_NATIVE_ACCEPTANCE=1` only when deliberately testing fresh native execution with available request capacity; it enables fresh native reads and queries in both suites, consuming the finite request budget. Browser screenshots go to `work/browser-captures/` by default; set `DDK_VIEWER_CAPTURE_DIR` for a different output directory.

The [content guide](docs/content-guide.md) defines visitor-facing terms and publisher responsibilities. The original content review (`outputs/content-review.md`) and the record of its completed publisher changes (`outputs/publisher-copy-update.md`) are in the evidence archive. The portal loads catalogs regenerated from the maintained publisher definitions. Earlier proposal files remain as review history.

The SpicyRegs field-meaning research is in the evidence archive. Its latest ledger, `outputs/spicy-layer1-open-fields-20261108/field-decisions.json`, covers the 384 traced fields: 362 meanings are supported at the cited source versions, 17 remain partial and five remain unknown. Of the 260 Layer 1 fields, 251 are supported, four partial and five unknown. Supported meanings can still have historical or validation limits. `outputs/spicy-official-docs-20261106/remaining-unknowns.md` identifies the earlier unresolved facts; unknown descriptions stay visibly absent in the viewer. The regenerated SpicyRegs catalog contains 389 dataset definitions and no data versions.

Fixtures were checked against the schemas inside the qualified installed dev4 wheel. `fixtures/validation.json` records that limited shape check. They are authored format examples; schema validity is not executed quality or native acceptance. The impact fixture is generated by `scripts/build-impact.py` with the qualified Python environment named in the shared handoff. Rebuilding fixtures requires regenerating the impact receipt afterwards. The default synthetic catalogs and application metadata views need no Python/native runtime. The optional commerce reader requires the pinned qualified Python environment, DocSpec executable and retained result.

In the evidence archive, `outputs/handoff.md` links exact source/catalog identities and separate reviews, and the Congress integration report (`outputs/viewer-congress-integration-20261106/report.md`) records 60 unit passes, one intentional native-execution skip, clean type checking/building, nine focused browser passes, 33 default-viewer browser passes and five preserved-application browser passes. Its independent comparison matches all 52 retained Congress rows across 17 files. The earlier SpicyRegs closeout, `outputs/verification.json` and the source ZIPs there remain evidence for their recorded milestones; use the current Git checkout for current state. Local commits and preview do not imply publication or deployment.

## Evidence archive

This viewer was built in a standalone repository and moved into the Data Design Kit without its `outputs/` folder, because the kit keeps generated research and run evidence outside the repository. The original repository at `~/Documents/Codex/2026-11-06/ddk-viewer` is the evidence archive. `outputs/` paths in these docs refer to it, and historical commit IDs in the `dv-*` tickets now under root `.tickets/` resolve there; the import commit maps them to their new IDs. Retained captures under `fixtures/applications/` record absolute paths into it as provenance. Ticket IDs, closed status and historical notes survived the November 13 consolidation.
