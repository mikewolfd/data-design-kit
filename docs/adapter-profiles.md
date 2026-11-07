# Adapter Profiles

**Draft, November 4, 2026.** This document elaborates [Section 15 of the specification](specification.md#integrations). Numbered DDK requirements in that specification are normative. Local integrations are implemented and undergoing conformance qualification; [implementation status](implementation-status.md) separates tested behavior from remaining claims.

## 1. Adapter boundary

An adapter receives validated source artifacts, a requested check inventory, an offline registry, explicit parameters, and optional runtime bindings. It returns check results, mapping coverage, native evidence locations, generated artifacts, and runtime outcomes where applicable. It owns its native-tool interpretation. The DDK result reducer owns the overall decision. Application use cases receive adapters through dependency injection at the composition root; the domain does not import their native implementation types.

The [runtime integration design](runtime-integration.md) defines preparation, bounded jobs, quality evaluation, and managed operations as separate responsibilities. DocSpec is the first execution adapter. Data Contract CLI is the first quality evaluator for supported file-backed cases. Exact-native access and quality-gated selection require additional evidence.

Capabilities are read from JSON manifests. Discovering a manifest does not import its implementation. A manifest lists the exact dependency tuple that passed cases, including Git commits and distribution digests for unreleased builds.

### Common execution sequence

1. Verify requested capability and version tuple.
2. Verify prerequisite checks and input inventory.
3. Determine mapping coverage before claiming complete translation.
4. Invoke a public API or structured subprocess with explicit arguments.
5. Preserve native statuses, errors, skipped controls, and relevant logs.
6. Associate evidence with exact inputs and output snapshot.
7. Return DDK results without changing unrelated files or publishing output.

## 2. ODCS and Data Contract CLI

**Responsibilities:** official document validation, property-definition resolution, dataset-version classification, and actual-data schema/quality tests.

**Input:** ODCS 3.2.0 documents, local references, pinned schema revision, exact identified dataset view, resolved rule set, and requested comparison perspective.

**Output:** native lint/version/test reports and generated configurations where supported.

The DDK schema baseline is the public development correction at `448f7b93329ece7827897d7dd51e827a3e279460`. The release-tag schema is preserved separately because their combined-operator behavior differs. A native CLI run must identify the schema bytes it used; a `v3.2.0` label alone is insufficient.

GitHub CLI commit `34b12923e0366fa4004c2f90644da41769699e0f` includes PR 1812, which changes inherited `logicalTypeOptions` merging and legacy enum precedence. Use independent tests for an inherited pattern plus inline maximum length, and an inherited enum plus an explicitly authored legacy enum. Compare with 1.2.9 before selecting the production pin.

Open PRs 1725 and 1726 propose extra-field and order checks. They are candidates for delegation, not current guaranteed features. Their reported case-insensitive name comparison also requires an explicit bridge to DDK's case-sensitive logical field matching.

**Failure cases:** unresolved definition, schema mismatch, unsupported quality engine, unavailable local file, native process failure, differing native/DDK schema revisions.

File-backed quality support and native-candidate quality support are separate claims. The initial path tests identified local Parquet or DuckDB output. A native path must prove that the selected CLI backend reads the exact protected DocSpec candidate without resolving latest or requiring an unnecessary export. The local bridge streams the protected version through Arrow IPC into a bounded DuckDB view and records native field identities. Its tested tuple appears in the implementation status. Preserve evaluator versions, mapping semantics, complete requested checks, and unsupported outcomes. A CLI report is evaluation evidence; DocSpec must accept it before it can gate managed selection.

## 3. Frictionless

**Responsibilities:** incoming file parsing, headers, tabular field constraints, and supported key relationships.

**Input:** selected files plus an explicitly generated Table Schema descriptor and dialect/missing-value configuration.

**Output:** native validation report, read/checked inventory, mapping coverage, and file digests.

| ODCS facet | Required treatment |
| --- | --- |
| Field names and presence | Explicit Table Schema fields; account for exact/partial field matching |
| Scalar logical types | Versioned type mapping, with invalid lexical values exercised |
| Nullability | Translate together with missing-value semantics, not just a required flag |
| Enums | Preserve typed values and test false, zero, and empty strings |
| Unique fields/composite keys | Prove the selected implementation executes the declared check |
| Decimal precision/time zones/nested fields | Report unsupported or unknown unless an exact mapping is demonstrated |

GitHub PR 1827 proposes DPv2 composite `uniqueKeys` enforcement and documents null-bearing key semantics. PR 1867 addresses error inventory when a misconfigured check affects later checks. Both are unmerged in the snapshot. A descriptor accepted by the package is insufficient evidence of enforced constraints.

Frictionless transformations are outside this adapter's initial role. A project that chooses them later must define how their result schema and execution evidence enter DDK rather than silently splitting transformation ownership.

## 4. dlt

**Responsibilities:** extraction and loading, explicit schema-evolution policy, and a staged-snapshot receipt.

**Input:** an explicitly invoked reader implementation, parameters, destination configuration, column hints, and table/column/type evolution policy.

**Output:** load identifiers, normalized dataset/name mapping, exact staged file inventory, counts available from the selected API, and schema observations.

The initial handoff is local Parquet. The production workflow may use dlt's native API directly and submit its receipt to DDK. Core design checks only validate the reader declaration and calls; they do not import it.

| Concern | Treatment |
| --- | --- |
| Source schema versus staging schema | Distinct dataset definitions, with explicit normalization mappings |
| `freeze` | Verify where enforcement occurs and report the failed load accurately |
| Discard modes | Record available counts; saving rejected rows requires explicit implementation |
| dlt system columns | Declare their presence and downstream inclusion/exclusion |
| Incremental state | Record the load/snapshot identity; do not infer it from the newest filename |
| Nested Parquet | Disabled in the initial flat profile pending tests; open PR 4299 is relevant |

## 5. DocSpec SQL and saved Substrait execution

**Responsibilities.** Prepare SQL against explicit input schemas, infer outputs, and execute bounded SQL and saved Substrait jobs for the first product release. Qualify managed operations separately. See the [runtime integration design](runtime-integration.md).

**Initial scope:** one SQL transform component at a time, flat input tables, explicit named bindings, projection, filter, equi-join, and aggregation through DocSpec. More operations require capability evidence. dlt readers and publication steps remain outside the calculation. Native input support preserves exact versions, schema interpretation, and native field identities.

### SQL sequence

1. Map ODCS fields to explicit Arrow/DataFusion types; stop when precision or semantics are unspecified.
2. Prepare through DocSpec's schema-only context and confirm no production-row scan.
3. Record the SQL artifact, dialect, semantic profile, effective parameters, runtime tuple, and inferred output schema.
4. Bind fixtures or exact file/native inputs and execute a bounded DocSpec job.
5. Preserve known committed outputs on returned failure; report process-loss uncertainty separately.
6. Compare independently expected rows and evaluate supported output quality checks.

No saved Substrait intermediate is required for this path. Bounded jobs do not imply durable lifecycle tracking. Managed claims name request kind/backend and use native operation identity, reconciliation, protection, candidate qualification, and guarded selection. Ordinary jobs cannot select a managed release merely because they used a catalog.

### Substrait sequence

Run the bounded WP-00B producer/consumer experiment alongside early core and catalog work. After SQL integration, WP-09B uses that evidence to qualify the integrated DocSpec path on its final dependency tuple. Save binary plan bytes and extension identities, consume those bytes through the same admitted context, and apply normalized-plan function/input restrictions and budgets. Return separate compile, consumer, standard-validation, output, and fixture results. The isolated DocSpec implementation uses matching DataFusion and datafusion-substrait 53.1.0 libraries. It preserves standalone validity as unknown.

DocSpec's inspected local revision pins Rust DataFusion 53.1.0. It is team-owned and unreleased; that pin and its API can change after testing. The earlier Python repository head `878e5d3b8d373bca19671af43e49dfb1890f8da2` names `datafusion-substrait 55.2.0` and Rust crate `substrait 0.63.0`. It remains a separate research candidate, not a mandatory second engine in DDK. Those package numbers do not establish the encoded Substrait standard version. WP-00B and WP-09B must inspect emitted plans and upstream definitions.

An open DataFusion FFI PR about a process-local foreign-plan workaround concerns a different physical serialization boundary. It must not be presented as general portable Substrait support. The initial DDK profile excludes opaque process-local handles and custom physical execution-plan payloads.

## 6. Standalone Substrait validator

**Responsibility:** independent plan validity evidence within supported format and operation coverage.

**Input:** the same saved plan bytes plus pinned extension definitions and an explicit validator build.

**Output:** validity decision, native diagnostics, unresolved/unsupported inventory, validator commit/distribution hash, and an optional annotated report.

Published validator 0.1.4 documents a 0.57.x standard baseline. GitHub main at `157c13913ac2e95786d86e75558d4967eabff662` uses 0.88.1 packaging dependencies; open PRs 562 and 554 propose 0.106.0. Main and release can share the same Python package version string, making source commit and built artifact digest essential.

Default loose-mode acceptance does not prove full validity. DDK must preserve unresolved validity as unknown. A missing compatible validator affects `plan.standard`, independently of DataFusion consumer acceptance. There is no automatic downgrade to an older plan format.

## 7. Fixture runner and second engine

**Responsibility:** execute independently specified cases using the identified implementation artifact. SQL cases can execute SQL through DocSpec; Substrait cases consume saved plan bytes.

Fixtures use the [fixture schema](../schemas/0.1/fixture.schema.json), with explicit input rows, expected rows, and comparison settings. The default comparison is an unordered multiset, not a set: duplicate rows matter. Optional numeric tolerances are zero unless explicitly configured. Time zones and date semantics must be stated in type mappings.

The opt-in [Arrow declaration profile](arrow-declaration-profile.md) supplies exact
integer widths, explicit float and temporal formats, and recursive object/list
fixture mappings. Its coverage keeps actual-data constraints pending. Existing
scalar preparation remains a separate profile; fixture materialization alone
does not qualify native execution or whole-data validation.

DuckDB's Substrait community extension is the first second-engine candidate. Its GitHub head `eb7ad41970245f06be9d4ee9a4a7c8d32a3f0a34` includes a dialect declaration and recent window-frame work. Its extension generator references 0.102.0 definitions. This is useful capability evidence to investigate, not proof that arbitrary DataFusion plans run unchanged.

The portability suite must execute the same plan bytes through both consumers and check each output against expected business rows. If extensions or semantics differ, record the unsupported operation and keep the claim scoped. Compiling the SQL separately for each engine is a different test and cannot satisfy saved-plan portability.

## 8. Optional CUE policy adapter

CUE can validate relationships among configured values and definitions. It is a possible later policy mechanism. It is not required to author a component, run the core checker, or install the first release. Its executable policy boundary would need the same explicit selection, versioning, result completeness, and execution isolation as other adapters.

## 9. Support declaration template

Every shipped adapter should publish a table with:

- DDK profile and check groups.
- Source standard and exact revision.
- Native tool version, source commit, and distribution digest where applicable.
- Supported operations and field facets.
- Artifact formats and semantic profiles; execution mode and operation/backend pairs.
- Native reference schemes, direct quality-access paths, and reconciliation guarantees.
- Conformance cases actually executed.
- Known unsupported and indeterminate cases.
- Data/plan inputs and expected native error translations.

The [example adapter manifest](../examples/adapter-manifest.ddk.json) deliberately declares `experimental-unverified` status and no passing evidence. Its valid document shape is not a support claim.

## 10. Product catalog and standards outputs

The `catalog` profile reads ODPS 1.1.0 product documents and resolves participating ports to the project's ODCS definitions. Load native publication manifests, version records, and run or check receipts through an explicitly selected metadata adapter. Emit the resolved catalog and preserve source inventory, exact reference schemes, scope, and disclosure policy. Profile discovery stays separate from adapter invocation.

The `catalog.dcat` profile writes DCAT 3 JSON-LD. Preserve a dataset's stable identity and exact version relationships. Emit an available distribution or service only for an observed supported representation. Derive a current-version link only from an unambiguous publisher selection for the requested authority and purpose. Validate the resulting graph independently.

The `lineage.openlineage` profile writes validated job and run events. Preserve existing OpenLineage identities and use the pinned mapping consistently in definitions and run events. Link event run IDs and dataset version facets back to exact native evidence. Preserve input coverage, unobserved outcomes, and scoped qualification in DDK records.

Initial exports use local files. Record the event schema and facet versions, DCAT mapping version, ODPS schema revision, and every native adapter's supported input scheme. The [catalog profile requirements](specification.md#catalog) and [example](../examples/commerce/catalog/README.md) define the connection points.
