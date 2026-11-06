# DDK implementation status

**November 6, 2026. Local implementation complete; release qualification pending for `0.1.0-dev.2`.** The current source binds development identity to local installation records, qualifies exact capability manifests against captured declarations, binds expectations to executed sources, preserves unsuccessful case outcomes, and admits relocated evidence without changing captured bytes. The changed package needs a fresh installed run and portable release bundle.

The earlier `0.1.0-dev.1` package passed 169 installed tests with no skips and all 154 required case/profile combinations across 13 profiles. Those results apply to its recorded source. The [local release record](local-release.md) preserves the package, exact source versions, dependency locks, and evidence. The prerelease remains unpublished.

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

The tested DDK implementation is commit `d86a3384ff7fe17101f34f92dda5422bb986864e`; DocSpec is commit `b1270b2e964becc5844bb6ca95ee5d605c7a3d79`. Two independent package builds produced identical bytes. A separate core-only installation passed without native engines, RDFLib, PyArrow, or pytest installed. Five qualified adapter manifests were also discovered without importing those modules.

## Commands

The CLI exposes `check`, `impact`, `lock`, `build`, `test`, and `catalog`. The additional `files`, `stage`, `quality`, and `managed` commands require explicit requests and tool selection. `--format json` returns one report; exit codes are 0 passed, 1 failed, 2 incomplete, 3 operational error, and 64 invalid usage.

Invoke the source checkout with its `src` directory on `PYTHONPATH`, or use the independently built local wheel. The offline environment needs the pinned JSON Schema libraries. Development lock creation additionally requires the installed source commit and wheel digest: a checkout or installation without those records returns incomplete without writing a lock. Ordinary unlocked checks remain available. Native tools run in a separately selected environment through `--tool-python`; DocSpec requires `--docspec` and an explicit `--limits` file.

The [local release instructions](local-release.md#run-the-package) provide the retained executable and a clean installation command using the captured dependency lock.

```sh
ddk check examples/commerce/project.ddk.json --format json
ddk lock examples/commerce/project.ddk.json --output /outside/repository/project.lock.json
ddk check examples/commerce/project.ddk.json --lock /outside/repository/project.lock.json --locked
ddk impact --base /baseline/project.ddk.json --candidate /candidate/project.ddk.json
```

`test --fixture` materializes independent fixture rows as typed Parquet. `test --bindings` checks the selected local file bindings, validates and stages CSV, and records injected reader outputs. Use `--output` to retain the entire run outside the repository. Successful default fixture runs remove their own temporary files; failed runs retain evidence and report its location.

`build --component summarize` prepares declared schemas and produces an identified SQL/Substrait bundle without running the transformation. `catalog --metadata ... --metadata-adapter local` reads owner receipts and generates the explicitly requested `dcat` and `openlineage` exports. Catalog refresh does not open data payloads.

## Native quality boundary

Data Contract CLI 1.2.9's public file path casts columns before checking types, and its database path does not use the supplied in-memory connection. The adapter therefore pins and calls the maintained native check compiler and executor against an explicitly bound DuckDB view. It implements no replacement quality language. Native diagnostic reports, omitted rules, and per-check outcomes remain visible.

File checks bind exact Parquet paths and digests. Native checks use DocSpec's protected Arrow IPC reader, with the original version, schema identity, and native field IDs. DuckDB can access only the admitted files, or only the registered native view. Explicit parameters replace environment lookup. A complete local native read and a passing evaluator report remain separate from DocSpec's accepted qualification.

## Measured behavior and limits

On the small commerce fixture, three repetitions produced median times of 35 ms for core checking, 74 ms for impact analysis, and 95 ms for metadata refresh. Peak process memory was 49 MiB. Instrumented metadata refresh opened zero data payloads. These measurements apply to macOS 26.6 arm64 and Python 3.12.13; the larger synthetic-library performance targets remain unmeasured.

The initial mappings are intentionally bounded: flat scalar intake, one exact Parquet file per fixture input, one output per SQL component, and one local independent Build family. Unsupported required mappings, missing checks, and unavailable adapters prevent a passing result. Extra Substrait consumers and independent standalone validation remain separate optional profiles. Public OpenLineage disclosure is unavailable in the initial adapter.

Recorded tests establish the named cases on their exact source and dependency tuple. They do not establish production publication, remote evaluator authentication, arbitrary managed operations, or organization-wide consumer discovery. Pilot adoption remains outside this build.
