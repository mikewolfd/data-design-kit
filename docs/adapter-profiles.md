# Adapter Profiles

**Draft, November 4, 2026.** This document elaborates [Section 15 of the specification](specification.md#integrations). Numbered DDK requirements in that specification are normative. The integration designs and examples here are proposed; no adapter has been implemented or qualified.

## 1. Adapter boundary

An adapter receives validated source artifacts, a requested check inventory, an offline registry, explicit parameters, and optional runtime bindings. It returns check results, mapping coverage, native evidence locations, and generated artifacts. It owns its native-tool interpretation. The DDK result reducer owns the overall decision.

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

**Input:** ODCS 3.2.0 documents, local references, pinned schema revision, explicit data location, requested comparison perspective.

**Output:** native lint/version/test reports and generated configurations where supported.

The DDK schema baseline is the public development correction at `448f7b93329ece7827897d7dd51e827a3e279460`. The release-tag schema is preserved separately because their combined-operator behavior differs. A native CLI run must identify the schema bytes it used; a `v3.2.0` label alone is insufficient.

GitHub CLI commit `34b12923e0366fa4004c2f90644da41769699e0f` includes PR 1812, which changes inherited `logicalTypeOptions` merging and legacy enum precedence. Use independent tests for an inherited pattern plus inline maximum length, and an inherited enum plus an explicitly authored legacy enum. Compare with 1.2.9 before selecting the production pin.

Open PRs 1725 and 1726 propose extra-field and order checks. They are candidates for delegation, not current guaranteed features. Their reported case-insensitive name comparison also requires an explicit bridge to DDK's case-sensitive logical field matching.

**Failure cases:** unresolved definition, schema mismatch, unsupported quality engine, unavailable local file, native process failure, differing native/DDK schema revisions.

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

## 5. DataFusion and Substrait

**Responsibilities:** compile supported authored SQL into a saved Substrait plan, consume that plan, derive output schema, and execute selected fixtures.

**Initial scope:** one transform component at a time, flat input tables, explicit named bindings, projection, filter, equi-join, and aggregation. More operations require capability evidence. dlt readers and publication steps remain outside the calculation plan.

### Build sequence

1. Map ODCS fields to explicit Arrow/DataFusion types; stop when precision or semantics are unspecified.
2. Register schema-only inputs and confirm planning does not scan production rows.
3. Compile authored SQL using the selected DataFusion version.
4. Save binary plan bytes and an upstream-generated JSON view.
5. Record the actual encoded format version, extension identifiers, and source/configuration hashes.
6. Re-import the saved bytes with named input bindings.
7. Derive the consumer's output schema and compare each requested export.
8. Return separate compile, consumer, and output results.

The Python repository head inspected is `878e5d3b8d373bca19671af43e49dfb1890f8da2`. Its lock names `datafusion-substrait 55.2.0` and the Rust crate `substrait 0.63.0`. Those package numbers do not establish the encoded Substrait standard version. WP-00 must inspect emitted plans and upstream definitions.

An open DataFusion FFI PR about a process-local foreign-plan workaround concerns a different physical serialization boundary. It must not be presented as general portable Substrait support. The initial DDK profile excludes opaque process-local handles and custom physical execution-plan payloads.

## 6. Standalone Substrait validator

**Responsibility:** independent plan validity evidence within supported format and operation coverage.

**Input:** the same saved plan bytes plus pinned extension definitions and an explicit validator build.

**Output:** validity decision, native diagnostics, unresolved/unsupported inventory, validator commit/distribution hash, and an optional annotated report.

Published validator 0.1.4 documents a 0.57.x standard baseline. GitHub main at `157c13913ac2e95786d86e75558d4967eabff662` uses 0.88.1 packaging dependencies; open PRs 562 and 554 propose 0.106.0. Main and release can share the same Python package version string, making source commit and built artifact digest essential.

Default loose-mode acceptance does not prove full validity. DDK must preserve unresolved validity as unknown. A missing compatible validator affects `plan.standard`, independently of DataFusion consumer acceptance. There is no automatic downgrade to an older plan format.

## 7. Fixture runner and second engine

**Responsibility:** execute independently specified cases using saved plan bytes.

Fixtures use the [fixture schema](../schemas/0.1/fixture.schema.json), with explicit input rows, expected rows, and comparison settings. The default comparison is an unordered multiset, not a set: duplicate rows matter. Optional numeric tolerances are zero unless explicitly configured. Time zones and date semantics must be stated in type mappings.

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
- Conformance cases actually executed.
- Known unsupported and indeterminate cases.
- Data/plan inputs and expected native error translations.

The [example adapter manifest](../examples/adapter-manifest.ddk.json) deliberately declares `experimental-unverified` status and no passing evidence. Its valid document shape is not a support claim.
