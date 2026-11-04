# Research, GitHub Evidence, and References

**Observed: November 4, 2026.** This document separates public documentation, source inspection, merged development, unmerged proposals, and tests still to run.

## 1. Method and limits

Research inspected official specifications, GitHub repository metadata, exact default-branch source files, selected pull-request descriptions and changes, and public release metadata. No native-tool integration or interoperability benchmark was executed for this specification.

[github-snapshot.json](github-snapshot.json) records default branches, commits, and relevant open pull requests from the first 100 open PRs per repository. This is a bounded search, not an exhaustive issue audit. [github-evidence.json](github-evidence.json) identifies source files and selected PRs actually read. Pull-request author test reports remain attributed upstream reports, not tests performed by this project.

<a id="github"></a>
## 2. GitHub findings that change the implementation plan

### 2.1 Substrait standard and validator

The standard's inspected head is [`a4d8e003`](https://github.com/substrait-io/substrait/commit/a4d8e00342d027560e3534a564a7b55ddba4b8e4), associated with release 0.108.0. The validator's development head is [`157c1391`](https://github.com/substrait-io/substrait-validator/commit/157c13913ac2e95786d86e75558d4967eabff662). Its [Rust manifest](https://github.com/substrait-io/substrait-validator/blob/157c13913ac2e95786d86e75558d4967eabff662/rs/Cargo.toml) and [Python manifest](https://github.com/substrait-io/substrait-validator/blob/157c13913ac2e95786d86e75558d4967eabff662/py/pyproject.toml) use 0.88.1 packaging dependencies. The Python package still identifies itself as 0.1.4.

Open [PR 562](https://github.com/substrait-io/substrait-validator/pull/562) and [PR 554](https://github.com/substrait-io/substrait-validator/pull/554) propose moving Rust and Python packaging to 0.106.0. These are dependency changes to evaluate, not proof that the validator understands every newer semantic feature. The released validator's older documented baseline is only one compatibility lane.

**Plan consequence:** test released, development, and selected PR candidates separately. Record source commits and wheel hashes. Keep consumer planning and independent standard validity separate.

### 2.2 DataFusion Python

Head [`878e5d3b`](https://github.com/apache/datafusion-python/commit/878e5d3b8d373bca19671af43e49dfb1890f8da2) exposes saved-byte serialization, JSON representation, and producer/consumer wrappers in [substrait.py](https://github.com/apache/datafusion-python/blob/878e5d3b8d373bca19671af43e49dfb1890f8da2/python/datafusion/substrait.py). Its [Cargo.lock](https://github.com/apache/datafusion-python/blob/878e5d3b8d373bca19671af43e49dfb1890f8da2/Cargo.lock) names `datafusion-substrait 55.2.0` and the Rust crate `substrait 0.63.0`. Crate numbering must not be mistaken for encoded plan-format numbering.

Open [PR 1733](https://github.com/apache/datafusion-python/pull/1733) isolates a foreign physical-plan workaround. Its body and changes concern process-local FFI serialization, which is a different boundary from portable Substrait logical plans.

**Plan consequence:** use the public producer/consumer path and saved bytes. Exclude opaque physical handles; determine actual plan versions through emitted artifacts and tests.

### 2.3 DuckDB Substrait extension

Head [`eb7ad419`](https://github.com/substrait-io/duckdb-substrait-extension/commit/eb7ad41970245f06be9d4ee9a4a7c8d32a3f0a34) includes recent window-frame work and a [dialect declaration](https://github.com/substrait-io/duckdb-substrait-extension/blob/eb7ad41970245f06be9d4ee9a4a7c8d32a3f0a34/duckdb_dialect.yaml). Its function-generation script references packaged 0.102.0 extension definitions.

**Plan consequence:** use the dialect as a capability input and test the shared operation subset. Producer coverage claims do not prove foreign-plan consumption or equal semantics across engines.

### 2.4 Data Contract CLI

Head [`34b12923`](https://github.com/datacontract/datacontract-cli/commit/34b12923e0366fa4004c2f90644da41769699e0f) includes merged [PR 1812](https://github.com/datacontract/datacontract-cli/pull/1812). Its resolver changes merge inherited type options per key and respect authored legacy enum locations. This is directly relevant to shared-definition maintenance.

Open [PR 1725](https://github.com/datacontract/datacontract-cli/pull/1725) proposes rejecting extra fields, and [PR 1726](https://github.com/datacontract/datacontract-cli/pull/1726) proposes declared field-order enforcement. These are not credited as shipped capabilities.

**Plan consequence:** compare 1.2.9 and the pinned development resolver before choosing a baseline. Prefer delegation to upstream implementations when they meet the required behavior. Test case-sensitive logical names separately from native backend conventions.

### 2.5 Frictionless

Head [`c08fa29c`](https://github.com/frictionlessdata/frictionless-py/commit/c08fa29cb0708427ae65bb689ded8e2691078a82) corresponds to 5.21.0. Open [PR 1827](https://github.com/frictionlessdata/frictionless-py/pull/1827) adds DPv2 composite unique-key enforcement; its description distinguishes descriptor acceptance from executed checks. Open [PR 1867](https://github.com/frictionlessdata/frictionless-py/pull/1867) addresses check errors affecting later check execution.

**Plan consequence:** require concrete composite-key and malformed-check regressions. Preserve a complete requested-check inventory even when native error reporting is incomplete.

### 2.6 dlt

The default branch is `devel`, inspected at [`ad4ec2d7`](https://github.com/dlt-hub/dlt/commit/ad4ec2d752dde7dea80506b4be2d345e3e3667ad). Open [PR 4299](https://github.com/dlt-hub/dlt/pull/4299) changes preservation of native nested values when writing Parquet.

**Plan consequence:** support flat data first and explicitly test nested preservation before advertising it. Column hints, schema-evolution policy, and physical output representation are different obligations.

### 2.7 ODCS

The development head [`448f7b93`](https://github.com/bitol-io/open-data-contract-standard/commit/448f7b93329ece7827897d7dd51e827a3e279460) includes merged [PR 360](https://github.com/bitol-io/open-data-contract-standard/pull/360). It changes the quality-operator schema composition so several valid operators can coexist. The `v3.2.0` release schema and the corrected development schema have the same ODCS API version but different bytes and behavior.

**Plan consequence:** this draft pins the corrected development schema and retains the release snapshot for comparison. Locks identify exact schema revisions and hashes; native CLI schema selection must be verified independently.

## 3. Published snapshots and licenses

These observations identify research baselines, not a tested compatible installation. License metadata was checked against public repositories; distribution and transitive notices remain a release gate.

| Project | Published observation | Repository license |
| --- | --- | --- |
| [ODCS](https://github.com/bitol-io/open-data-contract-standard) | v3.2.0, September 8, 2026; development correction also inspected | Apache-2.0 |
| [Data Contract CLI](https://github.com/datacontract/datacontract-cli) | v1.2.9, October 30, 2026; development resolver also inspected | MIT |
| [dlt](https://github.com/dlt-hub/dlt) | 1.32.0, October 29, 2026; devel inspected | Apache-2.0 |
| [Frictionless](https://github.com/frictionlessdata/frictionless-py) | v5.21.0, October 15, 2026; open correctness changes inspected | MIT |
| [Substrait](https://github.com/substrait-io/substrait) | v0.108.0, November 1, 2026 | Apache-2.0 |
| [Substrait validator](https://github.com/substrait-io/substrait-validator) | v0.1.4; development manifests differ | Apache-2.0 |
| [DataFusion Python](https://github.com/apache/datafusion-python) | Exact GitHub head inspected; no GitHub latest-release record returned | Apache-2.0 |
| [python-jsonschema](https://github.com/python-jsonschema/jsonschema) | v4.26.0 observed | MIT |
| [pytest](https://github.com/pytest-dev/pytest) | Fixture and parameterized-test documentation reviewed | MIT |
| [CUE](https://github.com/cue-lang/cue) | Optional configuration-policy candidate | Apache-2.0 |

The new project's own license cannot grant rights to restricted predecessor material. The implementation starts independently and carries the public dependency notices it actually requires.

## 4. Primary documentation

- [ODCS schema](https://bitol-io.github.io/open-data-contract-standard/v3.2.0/schema/), [quality](https://bitol-io.github.io/open-data-contract-standard/v3.2.0/data-quality/), [authoritative definitions](https://bitol-io.github.io/open-data-contract-standard/v3.2.0/authoritative-definitions/).
- [Data Contract CLI](https://cli.datacontract.com/), [definition resolution](https://cli.datacontract.com/semantics), [version comparison](https://cli.datacontract.com/compare-contract-versions), [local-file tests](https://cli.datacontract.com/testing/local).
- [Frictionless validation](https://framework.frictionlessdata.io/docs/guides/validating-data.html), [Table Schema](https://datapackage.org/standard/table-schema/).
- [dlt schema controls](https://dlthub.com/docs/general-usage/schema-contracts), [filesystem destination](https://dlthub.com/docs/dlt-ecosystem/destinations/filesystem).
- [Substrait](https://substrait.io/), [function definitions](https://substrait.io/expressions/user_defined_functions/), [producer tools](https://substrait.io/tools/producer_tools/).
- [DataFusion Substrait API](https://datafusion.apache.org/python/autoapi/datafusion/substrait/index.html), [DuckDB extension](https://duckdb.org/community_extensions/extensions/substrait).
- [JSON Schema](https://json-schema.org/draft/2020-12), [pytest fixtures and parameterization](https://docs.pytest.org/en/stable/reference/reference.html), [CUE configuration validation](https://cuelang.org/docs/concept/how-cue-enables-configuration/).
- [W3C conformance design guidance](https://www.w3.org/TR/spec-variability/), [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119), [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174), [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901), [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259).
