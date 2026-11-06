# DDK local release — 0.1.0-dev.2

**November 6, 2026. Installed qualification and portable acceptance passed.** The installed package passed 226 tests with no failures, errors, or skips. Release qualification passed 154 case/profile combinations covering 137 cases and 13 profiles. A fresh installation from the portable bundle also passed lock verification and four selected connected-workflow cases. Publication remains incomplete while the destination is unresolved.

The Python package version is `0.1.0.dev2`; DDK documents use `0.1.0-dev.2`. The [dev1 release record](local-release-dev1.md) preserves its earlier source and evidence separately. Full DDK stack replacements for SpicyRegs and congressional-tech remain separate, incomplete delivery work.

## Package and exact source versions

| Artifact | Qualified identity |
| --- | --- |
| DDK source | `8e9a53e81ec6258f2068557ff5e4788c80c32995` |
| DDK wheel SHA-256 | `b705e81c15636522c4e0e41f202ee3717d264800cdf0984c91f76ab925b4cd0e` |
| Source inventory SHA-256 | `83f71b98105afee79194010097925fa2ee952f210cb1ea6056b53ed437fd7717` |
| DDK source archive SHA-256 | `3d1f6a6e48001dcbf9669d2c96cb3c6de24ce0c442a114cae08c001ccd81870c` |
| DocSpec source | `b1270b2e964becc5844bb6ca95ee5d605c7a3d79` |
| DocSpec executable SHA-256 | `b89b43e2d2bf17f8d87ff1d9a779e06c3a024f2777e2327a8f048c6cb00a2532` |
| DocSpec SQL-only executable SHA-256 | `f485a75b13268abdcec80680c526c34fa5d26d684a03bd9403d0e4232dd9ece8` |
| Portable checksum inventory SHA-256 | `8269d0833b5128255f4d25e8df82aa06ae6e6be167ac0b2cc783f0d937eeddbd` |
| Portable archive SHA-256 | `ff801a1892c5e3f90787e52a26c1d5b322f65bcc2be3e04bc6752cf7a2bcf628` |

Two independent builds produced identical wheel bytes. All 134 captured source files match the selected Git commit; the actual code and resource files in both installed environments match the wheel. This documentation update follows qualification and leaves the tested source snapshot unchanged.

Local tags `v0.1.0-dev.2` in DDK and `ddk-v0.1.0-dev.2` in DocSpec identify those source commits. Both tags remain local.

- [Portable archive](/Users/mikewolfd/Work/artifacts/ddk-0.1.0.dev2-macos-arm64.tar.gz) and [SHA-256 sidecar](/Users/mikewolfd/Work/artifacts/ddk-0.1.0.dev2-macos-arm64.tar.gz.sha256)
- [Expanded bundle](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2) and its [installation and verification guide](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/README.md)
- [Installable wheel](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/evidence/distribution/qualified-03/wheel-a/data_design_kit-0.1.0.dev2-py3-none-any.whl)
- [Bundle metadata](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/bundle.json) and [checksums](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/checksums.sha256)
- [DDK source archive](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/sources/ddk-source.tar.gz) and [DocSpec source archive](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/sources/docspec-source.tar.gz)
- [Build and installation capture](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-03/run.json) and [exact tool versions](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-03/tested-tools.json)

The compressed archive contains 312,921,108 bytes. Stream verification checked all 4,140 archive files against the frozen bytes: the 4,139 checksum-inventory members and the inventory itself, with no links or external members. [Archive verification](/Users/mikewolfd/Work/artifacts/ddk-release-validation-20261106/archive-verification.json).

## Qualified profiles

| Area | Profiles | Supported scope |
| --- | --- | --- |
| Offline checking and change analysis | `core`, `impact` | JSON documents, local definitions, bounded compatibility, graphs, policies, locks, and known consumers |
| Catalog and interchange | `catalog`, `catalog.dcat`, `lineage.openlineage` | ODPS and ODCS definitions, scoped identities, exact versions, owner receipts, DCAT 3, and OpenLineage |
| SQL, saved plans, and fixtures | `plan.docspec-sql`, `execute.docspec-job`, `plan.datafusion`, `test.fixtures` | Schema-only preparation, bounded execution, saved Substrait bytes, independent expected rows, and exact-output evidence |
| Data quality and intake | `odcs-cli`, `files.frictionless`, `ingest.dlt` | Pinned native quality checks, CSV validation, and flat scalar staging to local Parquet |
| Managed operation | `runtime.docspec-managed` | One typed local Build family with protected native reads, accepted quality evidence, guarded selection, and reconciliation |

The [qualification report](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-03/release-qualification.ddk.json) binds the five exact manifest digests to their captured support declarations and tested tools. Its [evidence inventory](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-03/release-evidence.json) binds maintained test selectors and expectation sources to the executed fixture and source inventory. [JUnit results](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-03/junit.xml) record 226 passes in 88.28 seconds, with 11 RDFLib deprecation warnings. [Independent review](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-03/reviews/independent-semi-formal-review.md) checked the installed files and actual output rows.

The connected workflow stages the commerce inputs, executes SQL and saved Substrait bytes, compares both outputs with authored rows, checks each output against 13 required quality checks, generates discovery and lineage, and runs a catalog-bound query against the exact saved-plan output. Managed selection and recovery use separate typed-operation evidence.

## Run the package

The bundle includes the wheel, source archives, both native executables, dependency hash locks, notices, software bills of materials, and retained evidence. Python dependency archives and build-tool distributions must come from an index or matching local wheelhouse. Python 3.12.13 and pip 24.3.1 were tested.

Set the bundle path and choose a new environment outside the repository:

```sh
ddk_bundle=/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2
ddk_environment=/absolute/path/to/ddk-user-env
python3 -B "$ddk_bundle/build-tooling/verify_portable_bundle.py" --root "$ddk_bundle"
python3.12 -m venv "$ddk_environment"
python3 -B "$ddk_bundle/build-tooling/install_portable_bundle.py" \
  --root "$ddk_bundle" --python "$ddk_environment/bin/python" --profile core
"$ddk_environment/bin/python" -I -B -m ddk --help
```

Use `--profile full` for catalog support and the qualified test dependencies. The helper uses pip's hash-qualified wheel URL so the installer records the exact wheel identity required by development locks. DDK ignores `DDK_SOURCE_COMMIT` and `DDK_DISTRIBUTION_SHA256`. An existing target environment without pip can use `--installer-python /path/to/python-with-pip`. Native Python tools use a separate environment installed from `dependencies/native-tools.lock`; execution requires explicit adapters, bindings, and limits.

The bundled native executables are the qualified macOS arm64 builds and depend on macOS system libraries. Other operating systems, architectures, and macOS versions require separate qualification.

## Portable acceptance and evidence relocation

Fresh full and native environments reproduced all 14 and 91 recorded dependency versions. The portable installer identified the exact wheel, ordinary lock creation and verification passed, and all 4,139 listed files passed checksum verification. The [release acceptance summary](/Users/mikewolfd/Work/artifacts/ddk-release-validation-20261106/release-acceptance.json) binds these checks to their retained evidence hashes.

Historical receipts preserve their original absolute paths. DDK maps those paths to copied evidence without rewriting the captured bytes:

| Root | Location |
| --- | --- |
| Original captured root | `/Users/mikewolfd/Work/artifacts/ddk-stack-20261105` |
| Copied evidence root | `/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/evidence` |

Place a copied bundle outside its recorded `capturedRoot`; this release requires disjoint original and copied roots. After installation, the following command rechecks the historical qualification:

```sh
"$ddk_environment/bin/python" -I -B "$ddk_bundle/build-tooling/verify_portable_bundle.py" \
  --root "$ddk_bundle" --qualify
```

The [denied-original-path check](/Users/mikewolfd/Work/artifacts/ddk-release-validation-20261106/denied-original-relocation.json) opened zero original-tree files, regenerated the qualification report identically, and retained all five qualified manifests. This validates copied historical evidence. A separate [fresh connected replay](/Users/mikewolfd/Work/artifacts/ddk-release-validation-20261106/connected-junit.xml) executed four cases from two selectors, including three parameterized boundary cases, with the bundled DocSpec executable and fresh native environment: four passes, one RDFLib warning, 37.56 seconds.

Programmatic evidence readers must preserve exact JSON numbers with `ddk.documents.read_json`. Binary floating-point parsing can change measurement values and prevent exact evidence matching. Source records, installer identity, captured tests, fresh execution, and runtime protection establish separate facts.

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

The bundle retains Python dependency hash locks, `docspec-Cargo.lock`, the exact development ODCS comparison source, and [dependency notices](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/notices/NATIVE-DEPENDENCY-NOTICES.md). [Schema provenance](../PROVENANCE.md) records vendored revisions and digests. Source archives contain the selected source; rebuilding also needs build tools, dependencies, and a Git repository containing the selected commit for the Git-backed capture entry point.

Fresh core/full CycloneDX software bills of materials were generated and schema-validated for dev2. The native Python inventory was reused after its package versions matched the qualified environment. The full-feature DocSpec inventory identifies its source commit and Cargo lock. The SQL-only executable has an exact binary identity and Cargo dependency tree; its separate feature-specific software bill of materials remains `not_run`. [Inventory records](/Users/mikewolfd/Work/artifacts/portable-ddk-0.1.0.dev2/sbom).

## Measured resources

Three repetitions of the small commerce fixture on macOS 26.6 arm64 and Python 3.12.13 measured:

| Measurement | Result |
| --- | --- |
| Core check, median | 60 ms |
| Impact analysis, median | 82 ms |
| Metadata refresh, median | 98 ms |
| Peak process resident memory | 49.6 MiB |
| Data-payload opens during metadata refresh | 0 |

[Raw measurements](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-03/resources/measurements.json) apply to this fixture. The proposed 1,000-artifact performance target remains unmeasured.

## Remaining release and capability work

Publication awaits a destination. Full SpicyRegs and congressional-tech replacements remain separate, incomplete work with their requested scope intact.

Independent Substrait validation, its separately pinned validator combination, second-engine portability, and nested dlt staging remain outside the qualified capability set. Standalone plan validity remains `unknown`; portability remains `not_run`. Managed execution covers the documented trusted local Build and Iceberg/SQLite backend. Public OpenLineage disclosure, arbitrary managed operations, remote evaluator authentication, and general schema reasoning remain unavailable. Required unsupported checks prevent a passing result.
