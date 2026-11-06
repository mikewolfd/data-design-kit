# DDK implementation status

**November 6, 2026. Version `0.1.0-dev.3` passed installed qualification.** All 266 installed tests passed, with zero failures, errors, or skips. Release qualification passed 165 case/profile combinations covering 148 cases and 13 declared profiles. This catalog increment keeps the qualified dev2 native runtime. The separate dev2 portable archive retains its earlier acceptance. Publication remains incomplete while the destination is unresolved.

The [local release record](local-release.md) identifies the package, exact sources, dependencies, and evidence. Development identity comes from local build and installer records; exact manifest qualification, expectation-source binding, case outcomes, and relocation now have installed regression coverage. The [dev1 record](local-release-dev1.md) preserves the earlier capture separately. Full DDK stack replacements for SpicyRegs and congressional-tech remain separate, incomplete work. Their [shared runtime plan](replacement-runtime-plan.md) covers broader managed operations, exact nested views, bounded quality, retained multi-table work, migration, and publication recovery. Those extensions are planned and unqualified; dev2 remains available for independent application work.

## Successor work

The [catalog API](catalog-api.md) exposes admitted definitions and exact companion bytes from one assembly. Public reports remain audience-safe on early and incomplete failures; complete controls require a passing result. Recipes retain titles, ordered notes, contextual links, and explicit parameter order. Public definitions use field-path grants, and extensions retain each declaring project's scope. External targets remain external; required unsupported relationship reasoning stays unknown. The focused source run passed 71 catalog, impact, and external-reference tests. Three separate reducer tests passed for unsupported operations and a changed Update base.

Separate pending work adds a distinct `prepare_update` action using native Update for local, independent source-only bases. It is not included in the dev3 wheel. It reuses native computation, exact candidate access, quality acceptance, selection, and historical reconciliation. Final compiler-pinned execution and installed-package qualification remain in progress. Earlier small native and wrapper runs remain evidence for their recorded binary; a toolchain-path mismatch prevents attributing those earlier runs to the intended Rust compiler.

Both replacements are greenfield: producers and readers update together. Remaining work includes bounded quality over larger candidates, richer native types and views, retained multi-output execution, native accepted-evidence catalog mapping, exact consumer membership, and publication recovery. Old-reader compatibility and legacy-controller migration are outside scope. Separate greybeard and ETL reviewers are active in the shared-runtime, SpicyRegs, and congressional-tech sessions. Their findings feed the responsible implementation owner and remain distinct from executed acceptance.

## Working paths

| Capability | What is implemented | Evidence boundary |
| --- | --- | --- |
| Offline checker | Strict JSON, local definitions, interfaces, dataset checks, graphs, policies, locks, and directional impact | Imports no native engines and reads no production rows |
| Catalog | ODPS and ODCS resolution, scoped relationships, native receipts, DCAT 3, OpenLineage, exact-version queries, and atomic refresh | A binding is separate from observed physical input consumption |
| Bounded execution | Schema-only SQL preparation, saved Substrait production and consumption, and identified Parquet outputs | DataFusion 53.1.0 through the isolated DocSpec build; standalone standard validity remains unknown |
| Quality | Pinned Data Contract CLI lint, version comparison, and actual native checks | Explicit resolved rules, required outcomes, source identities, and restricted data access |
| Intake and staging | Frictionless CSV validation and flat dlt filesystem/Parquet staging | Exact completed native load inventory; nested staging is unavailable |
| Managed operation | Local typed Build, protected candidate access, native quality acceptance, guarded selection, and same-ID reconciliation | Trusted local workspace; one named operation/backend tuple |

The commerce workflow validates and stages the CSV inputs, executes SQL and the saved Substrait bytes, compares the exact exported files with independently authored expected rows, checks quality, generates discovery and lineage, and runs a catalog-bound query against the checked saved-plan output. Changing a shared quality definition identifies the affected consumer and its requalification requirements. The independent nested fixture exercises scoped identities and relationship paths. Native managed tests use a separate retained candidate.

The tested dev3 DDK implementation is commit `3823b24c2fff08da4da3ad7f6c6b79903ef2b372`; DocSpec remains commit `b1270b2e964becc5844bb6ca95ee5d605c7a3d79`. Two independent package builds produced identical bytes. A separate core-only installation passed without native engines, RDFLib, PyArrow, or pytest installed. Five exact adapter manifests qualified against their captured support declarations and were discovered without native imports. The [dev3 record](local-release-dev3.md) binds these claims to the installed wheel. Later documentation and pending implementation changes do not expand that snapshot.

## Commands

The CLI exposes `check`, `impact`, `lock`, `build`, `test`, and `catalog`. The additional `files`, `stage`, `quality`, and `managed` commands require explicit requests and tool selection. `--format json` returns one report; exit codes are 0 passed, 1 failed, 2 incomplete, 3 operational error, and 64 invalid usage.

Invoke the source checkout with its `src` directory on `PYTHONPATH`, or use the independently built local wheel. The offline environment needs the pinned JSON Schema libraries. Development lock creation additionally requires the installed source commit and wheel digest: a checkout or installation without those records returns incomplete without writing a lock. Ordinary unlocked checks remain available. Native tools run in a separately selected environment through `--tool-python`; DocSpec requires `--docspec` and an explicit `--limits` file.

The [portable release instructions](local-release.md#run-the-package) use the bundled installer and captured dependency locks. Installation downloads Python dependencies from an index or matching wheelhouse. Use the hash-qualified pip installation path to retain the wheel identity needed by development locks. The bundled native executables are qualified on macOS 26.6 arm64; other platforms require separate builds and qualification.

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

On the small commerce fixture, three repetitions produced median times of 60 ms for core checking, 82 ms for impact analysis, and 98 ms for metadata refresh. Peak process memory was 49.6 MiB. Instrumented metadata refresh opened zero data payloads. These measurements apply to macOS 26.6 arm64 and Python 3.12.13; the larger synthetic-library performance targets remain unmeasured.

The initial mappings are intentionally bounded: flat scalar intake, one exact Parquet file per fixture input, one output per SQL component, and one local independent Build family. Unsupported required mappings, missing checks, and unavailable adapters prevent a passing result. Extra Substrait consumers and independent standalone validation remain separate optional profiles. Public OpenLineage disclosure is unavailable in the initial adapter.

Recorded tests establish the named cases on their exact source and dependency tuple. Production publication, remote evaluator authentication, arbitrary managed operations, and organization-wide consumer discovery remain unqualified. The SQL-only native executable has its own exact binary identity and Cargo dependency tree; a separate feature-specific software bill of materials remains `not_run`. The full SpicyRegs and congressional-tech replacements retain their separate requested scope and remain incomplete.
