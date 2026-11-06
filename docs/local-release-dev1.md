# DDK local release — 0.1.0-dev.1

**Qualified November 5, 2026, on macOS 26.6 arm64 and Python 3.12.13.** The complete local build strategy passed qualification: 169 installed-package tests, no skips, 137 applicable conformance cases, and 154 case/profile combinations across 13 profiles. The release decision is `passed`. The package remains an unpublished prerelease; pilots are deferred.

The package, build environments, source archives, and generated evidence are retained outside this repository in [the qualified release directory](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02). The Python package version is `0.1.0.dev1`; DDK documents use `0.1.0-dev.1`.

## Package and exact source versions

| Artifact | Tested identity |
| --- | --- |
| DDK source | `d86a3384ff7fe17101f34f92dda5422bb986864e` |
| DDK wheel SHA-256 | `36c79a8baf5c3d33f1db5ba047448ede76b38f0d2ceca85a40648a4f4c08c5de` |
| Source inventory SHA-256 | `2fb9890533d13f935b245c90c535899b09bea39bb28d6bc3c343e4f4f5557c84` |
| DocSpec source | `b1270b2e964becc5844bb6ca95ee5d605c7a3d79` |
| DocSpec executable SHA-256 | `b89b43e2d2bf17f8d87ff1d9a779e06c3a024f2777e2327a8f048c6cb00a2532` |
| DocSpec SQL-only executable SHA-256 | `f485a75b13268abdcec80680c526c34fa5d26d684a03bd9403d0e4232dd9ece8` |

Two independent package builds produced identical wheel bytes. Source, native executables, and captured external inputs remained unchanged during testing. The final documentation update records these results separately from the tested implementation commit.

- [Installable wheel](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/wheel-a/data_design_kit-0.1.0.dev1-py3-none-any.whl)
- [DDK source archive](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/ddk-source.tar.gz) and [DocSpec source archive](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/docspec-source.tar.gz)
- [Build and installation capture](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/run.json)
- [Complete tested tool versions](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/tested-tools.json)
- [Release artifact checksums](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/checksums.sha256)

## Qualified profiles

| Area | Profiles | Supported scope |
| --- | --- | --- |
| Offline checking and change analysis | `core`, `impact` | JSON documents, local definitions, bounded compatibility, graphs, policies, locks, and known consumers |
| Catalog and interchange | `catalog`, `catalog.dcat`, `lineage.openlineage` | ODPS and ODCS definitions, scoped identities, exact versions, owner receipts, DCAT 3, and OpenLineage |
| SQL, saved plans, and fixtures | `plan.docspec-sql`, `execute.docspec-job`, `plan.datafusion`, `test.fixtures` | Schema-only preparation, bounded execution, saved Substrait bytes, independent expected rows, and exact-output evidence |
| Data quality and intake | `odcs-cli`, `files.frictionless`, `ingest.dlt` | Pinned native quality checks, CSV validation, and flat scalar staging to local Parquet |
| Managed operation | `runtime.docspec-managed` | One typed local Build family with protected native reads, accepted quality evidence, guarded selection, and reconciliation |

The [release qualification report](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/release-qualification.ddk.json) has no unresolved required case/profile pairs. Its [evidence inventory](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/release-evidence.json) binds the case results to passed pytest outcomes, source and tool identities, independently authored expectations, and the connected workflow. [JUnit results](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/junit.xml) record 169 tests in 96.6 seconds.

Five [adapter manifests](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/adapters) identify their operations, limits, and evidence. [Core-only discovery](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/adapter-discovery.ddk.json) verified all five against the release report without importing native tools. Discovery does not activate an adapter.

The connected commerce workflow uses the staged files as actual SQL and saved-plan inputs, compares both exported results with independently authored rows, checks the exact output, generates discovery and lineage, and runs a catalog-bound query. A shared quality-definition change identifies the affected consumer and requalification obligations. [Connected workflow evidence](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/test-artifacts/test_connected_staged_saved_pl0/workflow-verification.json).

## Run the package

The retained core-only environment can run the checker immediately:

```sh
/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/env-core/bin/ddk check \
  /Users/mikewolfd/Work/data-design-kit/examples/commerce/project.ddk.json --format json
```

For a fresh core installation outside the repository, choose a new environment path and use the captured dependency lock:

```sh
ddk_release=/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02
ddk_environment=/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/ddk-user-env
uv venv --python 3.12 "$ddk_environment"
uv pip install --python "$ddk_environment/bin/python" --require-hashes \
  -r "$ddk_release/core-dependencies.lock"
uv pip install --python "$ddk_environment/bin/python" --no-deps \
  "$ddk_release/wheel-a/data_design_kit-0.1.0.dev1-py3-none-any.whl"
```

Catalog interchange and the full test runner are installed in `qualified-02/env-full`. The native Python tools run separately through `/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/envs/quality/bin/python`. Execution explicitly selects `/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/runtime/docspec-ddk-final` and a limits file. The [implementation status](implementation-status.md#commands) explains the CLI boundaries; the retained build capture records the exact verification commands and environment.

## Dependencies and notices

| Component | Tested version |
| --- | --- |
| Python / JSON Schema / reference registry | 3.12.13 / `jsonschema` 4.26.0 / `referencing` 0.37.0 |
| RDFLib | 7.2.1 |
| Data Contract CLI / ODCS Python model | 1.2.9 / 3.2.0 |
| Frictionless / dlt | 5.21.0 / 1.32.0 |
| DuckDB / PyArrow / Ibis | 1.5.6 / 26.0.1 / 12.0.0 |
| Rust / DataFusion / datafusion-substrait | 1.94.0 / 53.1.0 / 53.1.0 |
| Arrow Rust / Substrait Rust / Iceberg Rust | 58.4.0 / 0.62.2 / 0.10.1 |

The maintained ODCS definition resolver comparison also uses development source `34b12923e0366fa4004c2f90644da41769699e0f`, with its archive digest captured in the tested tool inventory. DDK's local resolver remains independent and offline. [Schema provenance](../PROVENANCE.md) records the exact vendored ODCS, ODPS, and OpenLineage revisions.

The release directory retains `core-dependencies.lock`, `full-dependencies.lock`, `native-tools.lock`, and `docspec-Cargo.lock`. CycloneDX software bills of materials are provided as `core-install.cdx.json`, `test-install.cdx.json`, `native-tools.cdx.json`, and `docspec.cdx.json`; all four passed schema validation. [Native dependency notices](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/NATIVE-DEPENDENCY-NOTICES.md) identify the selected distributions and their recorded licenses. Build scripts and installations remain outside the repository.

## Measured resources

These are measurements of the small independently authored commerce fixture on the qualified machine, with three repetitions. They establish local behavior, not large-scale capacity.

| Measurement | Result |
| --- | --- |
| Core check, median | 35 ms |
| Impact analysis, median | 74 ms |
| Metadata refresh, median | 95 ms |
| Peak process resident memory | 49 MiB |
| Data-payload opens during metadata refresh | 0 |

[Raw measurements and repetitions](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/resources/measurements.json). The proposed 1,000-artifact performance target remains unmeasured.

## Unclaimed capabilities

Four optional cases remain outside this release: independent Substrait validation (`CASE-ADAPTER-006`, `CASE-GITHUB-VALIDATOR-TUPLE`), second-engine execution of identical plan bytes (`CASE-PORTABILITY-SAME-BYTES`), and nested dlt ingestion (`CASE-GITHUB-DLT-NESTED`). Standalone plan validity remains `unknown`; portability remains `not_run`. Nested catalog identities are covered separately and passed.

The initial intake requires flat scalar names that native normalization preserves. Managed execution covers a trusted local Build and its tested Iceberg/SQLite backend. Public OpenLineage disclosure, arbitrary managed operations, remote evaluator authentication, general schema reasoning, production deployment, and pilot adoption are outside the qualified scope. Required unsupported checks continue to prevent a passing result.
