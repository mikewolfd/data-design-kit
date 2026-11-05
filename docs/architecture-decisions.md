# Architecture Decisions

**Status:** decisions proposed by the November 5, 2026 engineering draft. They guide implementation and remain subject to review before a conforming release.

## ADR-001 — Keep the shared checker and catalog core offline

**Problem:** replacing an early design checker with a transformation engine loses the ability to validate interfaces before code exists.

**Decision:** component implementations are optional. Core evaluates declarations, bindings, compatibility, dependencies, and explicit policies offline. Optional profiles add inferred and executed evidence.

**Alternatives:** require every component to be executable; use only a dataset-quality CLI; compile every design to Substrait immediately.

**Reason.** Maintainers can review a shared interface before execution. Consumers can discover already available data from definitions and admitted metadata. An explicit test request runs the relevant tools and adds version-bound evidence.

**Consequence:** core results remain conditional on declarations. Reports and documentation must preserve that boundary.

**Requirement links:** [DDK-CONF-002](specification.md#DDK-CONF-002), [DDK-CALL-001](specification.md#DDK-CALL-001), [DDK-MODEL-002](specification.md#DDK-MODEL-002).

## ADR-002 — Reuse standards and keep the new format narrow

**Problem:** a new checker could recreate field vocabularies, quality syntax, parameter validators, and transformation operators.

**Decision.** Use ODPS product definitions, ODCS datasets, JSON Schema parameters, DCAT 3 discovery, OpenLineage events, and supported Substrait plans. DDK documents connect these to exact native records, project interfaces, policies, and results.

**Alternatives:** invent a full unified data language; put all interfaces inside ODCS custom properties; use Substrait as the sole authoring format.

**Reason:** the proposed connections are not all dataset properties or relational calculations. Keeping them explicit avoids overloading another standard while preserving maintained vocabularies.

**Consequence:** the small composition format still has a maintenance cost. Every new field needs a concrete user task and conformance case.

**Requirement links:** [DDK-SYNTAX-002](specification.md#DDK-SYNTAX-002), [DDK-CALL-004](specification.md#DDK-CALL-004), [DDK-GRAPH-003](specification.md#DDK-GRAPH-003).

## ADR-003 — Treat unknown coverage as an explicit outcome

**Problem:** unsupported inference and unavailable adapters can produce a misleading green report if skipped work is indistinguishable from success.

**Decision:** check statuses are passed, failed, unknown, and not-run. Required indeterminate or unexecuted checks make the overall report incomplete. Operational errors remain separate.

**Alternative:** warnings plus a boolean pass/fail result.

**Reason:** users need to know which promises were checked and at what evidence level. Required coverage must survive output filtering and integration boundaries.

**Consequence:** callers must handle exit code 2 and review their required groups. The default core profile does not implicitly promise execution validation.

**Requirement links:** [DDK-RESULT-001](specification.md#DDK-RESULT-001), [DDK-RESULT-002](specification.md#DDK-RESULT-002), [DDK-CLI-002](specification.md#DDK-CLI-002).

## ADR-004 — Use a sound bounded compatibility model

**Problem:** arbitrary JSON Schema containment, physical-type compatibility, and business semantics are too broad for a dependable first implementation.

**Decision:** implement the specified scalar and parameter subset with explicit direction, exact numeric reasoning, and unknown results outside supported coverage.

**Alternatives:** compare type names only; claim full generic type compatibility; add operation-specific column guessing.

**Reason:** false confidence would undermine the tool's purpose. Meaningful bounded checks are preferable to broad undocumented approximations.

**Consequence:** some valid projects require more information or a plan/runtime profile. Unsupportedness is a product result, not an exception to hide.

**Requirement links:** [DDK-CALL-005](specification.md#DDK-CALL-005), [DDK-DATA-003](specification.md#DDK-DATA-003), [DDK-IMPACT-003](specification.md#DDK-IMPACT-003).

## ADR-005 — Execute SQL and saved Substrait through DocSpec

**Problem:** adopting a plan standard does not supply an authoring experience or execution engine.

**Decision.** Qualify SQL and saved Substrait through the same DocSpec context for the first product release. Saved-plan tests consume the exact plan bytes. Readers remain dlt or native acquisition and preparation outside the calculation.

**Alternatives:** write a new YAML-to-Substrait compiler; use Ibis as a mandatory core language; require the DuckDB extension as the only runtime.

**Reason:** DocSpec already owns maintained execution, native readers, limits, and function checks. Sharing that path avoids a mandatory second Python engine and does not make Substrait compatibility a prerequisite for useful SQL tests. DocSpec is team-owned and unreleased; its API and dependency baseline can change after testing.

**Consequence:** supported dialects, extensions, encoded versions, and physical types must be measured for the chosen tuple. Decoded plans must preserve applicable runtime guards. No universal portability claim follows from the format name. Ordinary jobs do not acquire managed lifecycle guarantees.

**Requirement links:** [DDK-ADAPTER-005](specification.md#DDK-ADAPTER-005), [DDK-ADAPTER-006](specification.md#DDK-ADAPTER-006), [DDK-ADAPTER-007](specification.md#DDK-ADAPTER-007), [DDK-ADAPTER-014](specification.md#DDK-ADAPTER-014).

## ADR-006 — Inspect GitHub development and pin evidence

**Problem:** release metadata misses merged correctness fixes and active interoperability work; branch names and package versions can also conceal changing source.

**Decision:** research published releases, exact default-branch commits, and selected relevant pull requests. Ship only tested tuples. Record commit and distribution digests for development builds. Treat unmerged work as an experiment candidate.

**Evidence:** the ODCS schema has a combined-operator correction under the same API version; CLI main fixes inherited constraint merging; validator main uses newer bindings than its release; open Frictionless fixes affect constraint enforcement and error completeness.

**Consequence:** the draft intentionally pins a public ODCS development schema revision and retains the release snapshot for comparison. Optional engine tuples remain unqualified until built and tested.

**Requirement links:** [DDK-LOCK-001](specification.md#DDK-LOCK-001), [DDK-VERSION-003](specification.md#DDK-VERSION-003). See [GitHub research](references.md#github).

## ADR-007 — Keep runtime adapters optional

**Problem:** mandatory engine and ingestion dependencies increase installation cost and can trigger imports or network behavior during basic checking.

**Decision:** discover manifests as data; install and import runtime integrations separately. Native tools own their runtime behaviors and are invoked only for explicit profiles.

**Consequence.** Qualification depends on evidence for the requested capability. A core-only installation supports offline checks. The first product release qualifies the standard catalog outputs, the bounded SQL and Substrait execution paths, and their tests together.

**Requirement links:** [DDK-ADAPTER-001](specification.md#DDK-ADAPTER-001), [DDK-ADAPTER-008](specification.md#DDK-ADAPTER-008), [DDK-VERSION-002](specification.md#DDK-VERSION-002).

## ADR-008 — Independent implementation and public provenance

**Problem:** the user cannot use the predecessor implementation because of licensing constraints.

**Decision:** write the new implementation, examples, schemas for new formats, tests, and documentation from independently specified requirements and public standards. Preserve public upstream material with source, revision, digest, and notices. Do not import predecessor artifacts.

**Consequence:** prior discussion supplies functional goals, not permission to reuse source. This authorship record is not a claim of a formal isolated clean-room process. Upstream dependency licensing must be rechecked on the actual distributions selected for release.

**References:** [PROVENANCE.md](../PROVENANCE.md), [NOTICE](../NOTICE), [upstream inventory](upstream-artifacts.json).

## ADR-009 — Inject services at useful application boundaries

**Decision:** separate domain rules, application use cases, and external adapters. The composition root explicitly constructs services. Implement `PlanService`, `JobExecutor`, and `QualityEvaluator` with the first SQL path; introduce `DatasetRuntime` with a concrete managed workflow. A single adapter may implement several ports.

**Reason:** offline design checking needs no engine implementation types. Preparation, bounded execution, managed selection, and quality evaluation have distinct guarantees and independent tests.

**Consequence:** no generic plugin registry, dependency container, universal plan model, or separate server is required. Use simple typed records and structured process communication first.

**Requirement links:** [DDK-ARCH-001](specification.md#DDK-ARCH-001), [DDK-ADAPTER-011](specification.md#DDK-ADAPTER-011).

## ADR-010 — Separate implementation semantics from placement

**Decision:** components identify artifact format, dialect where applicable, and a versioned semantic profile. Bindings/caller configuration select runtime, adapter, mode, connections, and limits.

**Reason:** moving an endpoint need not change calculation meaning. Function, overflow, null, collation, temporal, or mapping changes can change it even when SQL bytes stay the same.

**Consequence:** reuse requires established semantic equivalence and exact inputs. Full provenance remains available independently. Unverified equivalence prevents reuse.

**Requirement links:** [DDK-CALL-007](specification.md#DDK-CALL-007), [DDK-LOCK-005](specification.md#DDK-LOCK-005).

## ADR-011 — Preserve native identities and runtime protection

**Decision:** support mutually exclusive file and native-version bindings. Preserve native reference scheme/version, namespace, digest algorithm, schema interpretation, and field identities. Let the runtime validate and protect native data.

**Reason:** crossing the DDK boundary should not require copying a dataset into files. Native identities are not interchangeable with DDK artifact hashes, and immutable reference metadata alone does not promise availability.

**Consequence:** core validates a native wrapper without dereferencing it. Selected runtime profiles validate the native reference and record exact read observations. Missing data does not fall back to latest. DDK does not replicate native object inventories or retention decisions.

**Requirement links:** [DDK-ADAPTER-012](specification.md#DDK-ADAPTER-012), [DDK-RESULT-004](specification.md#DDK-RESULT-004).

## ADR-012 — Qualify retained candidates before managed selection

**Decision:** keep native computation identity, qualification identity, and full provenance distinct. Add a bounded DocSpec extension to accept exact-candidate quality evidence and check it within guarded selection for one supported operation/backend family.

**Reason:** changed rules should requalify unchanged values. Built-in native routine validation does not establish external quality-rule acceptance. A post-selection test supplies audit evidence.

**Consequence:** complete required-rule coverage, evaluator identity, and evaluation semantics bind the evidence. A report or success boolean cannot establish runtime acceptance. Direct native CLI access remains an experiment; file-backed success does not qualify a native gate. Do not add a general quality-rule framework.

**Requirement links:** [DDK-LOCK-005](specification.md#DDK-LOCK-005), [DDK-ADAPTER-013](specification.md#DDK-ADAPTER-013).

## ADR-013 — Preserve uncertain native execution outcomes

**Decision:** report check status, execution outcome, and selection outcome separately. Preserve the original managed operation ID and request identity before submission and after response loss. Reconcile through the native runtime.

**Reason:** an admitted worker can continue after the caller stops waiting. Ordinary returned partial outputs provide less recovery evidence than a managed lifecycle.

**Consequence:** no replacement operation is created automatically on uncertainty. Bounded jobs advertise only their demonstrated tracking guarantees. Report errors can coexist with unknown execution. Cleanup remains limited to runner-owned temporary files.

**Requirement links:** [DDK-RESULT-006](specification.md#DDK-RESULT-006), [DDK-ADAPTER-011](specification.md#DDK-ADAPTER-011), [DDK-SAFE-003](specification.md#DDK-SAFE-003).

## ADR-014 — Generate catalogs from authoritative definitions and native records

**Decision.** Maintain each intended fact once. The catalog resolves product and dataset definitions, native version records, check results, and publisher selections. It generates DCAT, OpenLineage, and existing reader metadata from that resolved view.

**Reason.** SpicyRegs can consolidate repeated schema and relationship declarations. Congressional-tech already generates metadata from a maintained release registry. Both need exact identities, scoped keys, and separately observable access and confidence. A shared checker and generated catalog allow each project to preserve these semantics and replace duplicate authoring.

**Consequence.** Qualification requires two representative project products, one maintained owner per migrated fact, and proof that a refresh reuses admitted metadata. The first product release includes all required standards and the tested execution path defined in [DDK-VERSION-003](specification.md#DDK-VERSION-003).
