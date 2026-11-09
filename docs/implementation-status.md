# DDK implementation status

**November 7, 2026. The integrated SDK3 package passes the complete local installed profile qualification.** All 266 required case/profile checks passed across 249 distinct cases and 13 supported profiles. One fresh installed run passed 703 tests with zero failures, errors or skips. Earlier SDK2 skips and supplemental results remain unchanged. [Package identities, evidence and use](local-release-integrated-3.md).

The connected workflow passes ODPS/ODCS resolution, file staging, SQL and saved Substrait execution, exact-output quality checks, DCAT/OpenLineage generation and a catalog-bound read. Five generated adapter manifests match the exact captured support declarations. The offline core remains separately installed and checked. The [portable SDK3 package](local-release-integrated-3.md#portable-package) also passes fresh installations, evidence relocation and four fresh workflow cases on macOS arm64. Its copied 703-test qualification remains distinct from these new distribution checks; the dev2 archive retains its earlier scope.

## Layered data-map source work

A November 8 source branch lets a capture → source → resolved → product map live in pure DDK. Aggregator roots, shared imports, `layer-order`, `view-sources`, primary-key row identity, dataset origin, remote definition references, recipe SQL binding and catalog descriptive fields pass source-checkout tests, the [layered example](../examples/layered/README.md) and a copy of the 194-dataset SpicyRegs map. They have no installed qualification. [WP-15](implementation-plan.md#wp-15--layered-data-map-extensions-specified-not-implemented) lists the specified but unimplemented requirements. [Source checks](verification.md#november-8-2026-layered-data-map-source-checks). The proposed [ADR-015](architecture-decisions.md#adr-015--keep-ddk-to-the-evidence-bound-catalog) keeps DDK to that catalog and freezes components, designs, impact, file intake, saved plans and fixtures; three decisions remain open.

## Successor work

SDK3, from source `cc9c44297fb78a6b061951462cd42541e98182bf`, combines captured catalog queries, recursive native types, public release membership, retained jobs, native input custody, producer proof/model prerequisites and publication-intent recovery. It adds optional host-owned process groups, covered by nine installed POSIX stand-in probes. The unchanged DocSpec implementation `255c18489d224d095d4bd1d1edbdef5f5538bb3e` passed 1,011 Rust and 31 Dagster tests; 17 ignored Rust cases remain explicit. Both installed and native results retain their exact source and dependency identities. [Complete local qualification](verification.md#november-7-2026-sdk3-complete-installed-qualification).

The optional `managed_job(..., snapshot_source=path)` forwards a private source configuration to DocSpec. Native code owns credentials, source reads and custody. A synthetic S3 provider exercises first reading, recovery after an input-read failure and offline acceptance; two installed SDK2 calls recover the same accepted candidate after the provider stops. This is separate evidence from access to an actual provider. [Source and replay evidence](verification.md#november-7-2026-installed-snapshot-source-and-native-replay).

The qualified native paths preserve original operation and version identities across lost responses and cold recovery. Accepted proof-to-model bindings preserve source order, field identities, exact custody and required acceptance. A verified empty proof can produce an evidence catalog without claiming output data. Publication-intent recovery preserves the saved decision and audit; an external publisher still owns activation and destination-specific checks.

Congress installed SDK3 and passed seven retained-proof metadata checks plus five application factory/source checks. Its other 131 installed dependency versions stayed unchanged. Native producer adoption and the original eight-table provider proof then passed; the earlier capacity refusal and separate credential preflight failure remain retained. All nine required proof counters are zero. This verifies the selected retained archive snapshots; fresh official-source checks and the complete model/reader journey remain open. [Congress source proof](verification.md#november-7-2026-congress-retained-source-proof). SpicyRegs retains SDK2 and passed four local imports, complete typed readback of 1,772 rows, native proof/model acceptance, cold model recovery and paired catalog checks bound to all four accepted output versions. Native acceptance covers the required counters; the original application policy separately validates the actual files. These are scoped [application results](verification.md#november-7-2026-application-catalog-and-adoption-continuation). Installed readers, complete application acceptance and publication remain separate work.

Congress's selected recovery policy requires verified recovered originals and continued official-source checks. Historical recovery evidence and each actual source-check time must remain distinct; missing observations remain unknown.

Congress's retained-rules fix passed all 18 focused metadata cases and is committed as `3a7657a870ca945df88397ed89b3ea413c72532a`. It preserves the original rules bytes used by the adopted definition. SpicyRegs's corrected application package passes build, isolated installation, identity verification, lint and type checking. These [latest application checks](verification.md#november-7-2026-application-and-viewer-follow-up) leave the complete Congress model and both applications' full reader journeys open.

The separate React/Astro viewer reads maintained catalog and receipt interfaces and displays processing acceptance separately from producer evidence and publisher selection. Its latest display correction passed six unit cases, type checking, build and desktop/mobile browser checks. Its retained local metadata/browser checks do not establish current source availability or production publication. [Latest viewer evidence](verification.md#november-7-2026-application-and-viewer-follow-up).

Separate greybeard and ETL reviewers cover this runtime, the viewer and both applications. The [verification record](verification.md) preserves earlier source-only checks, failed or interrupted captures and older package results under their original identities. No historical result has been restamped as SDK3 evidence.

## Working paths

| Capability | What is implemented | Evidence boundary |
| --- | --- | --- |
| Offline checker | Strict JSON, local definitions, interfaces, dataset checks, graphs, policies, locks, and directional impact | Imports no native engines and reads no production rows |
| Catalog | ODPS and ODCS resolution, scoped relationships, native receipts, DCAT 3, OpenLineage, exact-version queries, and atomic refresh | A binding is separate from observed physical input consumption |
| Bounded execution | Schema-only SQL preparation, saved Substrait production and consumption, and identified Parquet outputs | DataFusion 53.1.0 through the isolated DocSpec build; standalone standard validity remains unknown |
| Quality | Pinned Data Contract CLI lint, version comparison, and actual native checks | Explicit resolved rules, required outcomes, source identities, and restricted data access |
| Intake and staging | Frictionless CSV validation and flat dlt filesystem/Parquet staging | Exact completed native load inventory; nested staging is unavailable |
| Managed operation | Local typed Build and based Update; retained local-file jobs with multiple outputs; local native snapshot custody; protected candidate access, native quality acceptance, guarded selection and same-ID reconciliation | SDK3 qualifies the exercised local paths with the exact current native executable. Actual-provider inputs, production scale and application publication require separate evidence |

The commerce workflow validates and stages the CSV inputs, executes SQL and the saved Substrait bytes, compares the exact exported files with independently authored expected rows, checks quality, generates discovery and lineage, and runs a catalog-bound query against the checked saved-plan output. Changing a shared quality definition identifies the affected consumer and its requalification requirements. The independent nested fixture exercises scoped identities and relationship paths. Native managed tests use a separate retained candidate.

The current [SDK3 guide](local-release-integrated-3.md) binds the installed claims to source `cc9c442`, wheel `bd3218fb…` and native executable `e2ed2646…`. The [SDK2 guide](local-release-integrated-2.md) and [dev5 guide](local-release-dev5.md) retain their earlier source and runtime tuples. Documentation updates do not rebuild these packages or expand their recorded tests.

## Commands

The CLI exposes `check`, `impact`, `lock`, `build`, `test`, and `catalog`. The additional `files`, `stage`, `quality`, and `managed` commands require explicit requests and tool selection. `--format json` returns one report; exit codes are 0 passed, 1 failed, 2 incomplete, 3 operational error, and 64 invalid usage.

Invoke the source checkout with its `src` directory on `PYTHONPATH`, or use the independently built local wheel. The offline environment needs the pinned JSON Schema libraries. Development lock creation additionally requires the installed source commit and wheel digest: a checkout or installation without those records returns incomplete without writing a lock. Ordinary unlocked checks remain available. Native tools run in a separately selected environment through `--tool-python`; DocSpec requires `--docspec` and an explicit `--limits` file.

The [current portable instructions](local-release-integrated-3.md#portable-package) use the bundled installer, captured dependency locks and a separate verified wheelhouse. The installer retains the wheel identity needed by development locks. The bundled native executables are qualified on macOS arm64 with Python 3.12.13; other platforms require separate builds and qualification.

```sh
ddk check examples/commerce/project.ddk.json --format json
ddk lock examples/commerce/project.ddk.json --output /outside/repository/project.lock.json
ddk check examples/commerce/project.ddk.json --lock /outside/repository/project.lock.json --locked
ddk impact --base /baseline/project.ddk.json --candidate /candidate/project.ddk.json
```

`test --fixture` materializes independent fixture rows as typed Parquet. `test --bindings` checks the selected local file bindings, validates and stages CSV, and records injected reader outputs. Use `--output` to retain the entire run outside the repository. Successful default fixture runs remove their own temporary files; failed runs retain evidence and report its location.

`build --component summarize` prepares declared schemas and produces an identified SQL/Substrait bundle without running the transformation. `catalog --metadata ... --metadata-adapter local` reads owner receipts and generates the explicitly requested `dcat` and `openlineage` exports. Catalog refresh does not open data payloads.

Portable evidence rechecking requires disjoint captured and copied roots and preserves the original receipt bytes. The acceptance check opened zero files from the original tree and regenerated an identical qualification report. Use `ddk.documents.read_json` for programmatic evidence loading so exact JSON numbers retain their values. This historical recheck and the fresh four-case native replay establish separate results.

## Native quality boundary

Data Contract CLI 1.2.9's public file path casts columns before checking types, and its database path does not use the supplied in-memory connection. The adapter therefore pins and calls the maintained native check compiler and executor against an explicitly bound DuckDB view. It implements no replacement quality language. Native diagnostic reports, omitted rules, and per-check outcomes remain visible.

File checks bind exact Parquet paths and digests. Native checks use DocSpec's protected Arrow IPC reader, with the original version, schema identity, and native field IDs. DuckDB can access only the admitted files, or only the registered native view. Explicit parameters replace environment lookup. A complete local native read and a passing evaluator report remain separate from DocSpec's accepted qualification.

## Measured behavior and limits

On the dev5 small commerce fixture, three repetitions produced median times of 53 ms for core checking, 99 ms for impact analysis and 112 ms for metadata refresh. Peak process memory was 52.8 MiB. Instrumented metadata refresh opened zero data payloads. These measurements apply to macOS 26.6 arm64 and Python 3.12.13; the larger synthetic-library performance targets remain unmeasured.

File intake and fixture bindings remain bounded to flat scalar staging and one exact Parquet file per fixture input. Bounded SQL components expose one output; retained native jobs support multiple named outputs. Managed Build, based source-only Update, input reuse and producer prerequisites retain their explicit tested scope. Unsupported required mappings, missing checks, and unavailable adapters prevent a passing result. Extra Substrait consumers and independent standalone validation remain separate optional profiles. Public OpenLineage disclosure is unavailable in the initial adapter.

Recorded tests establish the named cases on their exact source and dependency tuple. Production publication, remote evaluator authentication, arbitrary managed operations, and organization-wide consumer discovery remain unqualified. The SQL-only native executable has its own exact binary identity and Cargo dependency tree; a separate feature-specific software bill of materials remains `not_run`. The full SpicyRegs and congressional-tech replacements retain their separate requested scope and remain incomplete.
