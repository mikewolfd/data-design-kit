# Architecture Decisions

**Status:** decisions proposed by the November 4, 2026 engineering draft. They guide implementation and remain subject to review before a conforming release.

## ADR-001 — Make implementation-free design checking the core

**Problem:** replacing an early design checker with a transformation engine loses the ability to validate interfaces before code exists.

**Decision:** component implementations are optional. Core evaluates declarations, bindings, compatibility, dependencies, and explicit policies offline. Optional profiles add inferred and executed evidence.

**Alternatives:** require every component to be executable; use only a dataset-quality CLI; compile every design to Substrait immediately.

**Reason:** the shared-reader maintenance workflow is independently useful. Forcing execution details into every proposal would change the user's authoring task.

**Consequence:** core results remain conditional on declarations. Reports and documentation must preserve that boundary.

**Requirement links:** [DDK-CONF-002](specification.md#DDK-CONF-002), [DDK-CALL-001](specification.md#DDK-CALL-001), [DDK-MODEL-002](specification.md#DDK-MODEL-002).

## ADR-002 — Reuse standards and keep the new format narrow

**Problem:** a new checker could recreate field vocabularies, quality syntax, parameter validators, and transformation operators.

**Decision:** use ODCS datasets, JSON Schema parameter constraints, and optional Substrait calculation plans. New documents connect named interfaces, project namespaces, calls, policies, locks, and results.

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

## ADR-005 — Generate Substrait through an existing producer

**Problem:** adopting a plan standard does not supply an authoring experience or execution engine.

**Decision:** start with DataFusion SQL and its Substrait producer/consumer. Save a plan and consume those same bytes for plan tests. Readers remain dlt/native execution outside the calculation plan.

**Alternatives:** write a new YAML-to-Substrait compiler; use Ibis as a mandatory core language; require the DuckDB extension as the only runtime.

**Reason:** a maintained producer minimizes new transformation semantics. DataFusion's public API exposes both directions. A second engine tests interoperability later.

**Consequence:** supported dialects, extensions, encoded versions, and physical types must be measured for the chosen tuple. No universal portability claim follows from the format name.

**Requirement links:** [DDK-ADAPTER-005](specification.md#DDK-ADAPTER-005), [DDK-ADAPTER-006](specification.md#DDK-ADAPTER-006), [DDK-ADAPTER-007](specification.md#DDK-ADAPTER-007).

## ADR-006 — Inspect GitHub development and pin evidence

**Problem:** release metadata misses merged correctness fixes and active interoperability work; branch names and package versions can also conceal changing source.

**Decision:** research published releases, exact default-branch commits, and selected relevant pull requests. Ship only tested tuples. Record commit and distribution digests for development builds. Treat unmerged work as an experiment candidate.

**Evidence:** the ODCS schema has a combined-operator correction under the same API version; CLI main fixes inherited constraint merging; validator main uses newer bindings than its release; open Frictionless fixes affect constraint enforcement and error completeness.

**Consequence:** the draft intentionally pins a public ODCS development schema revision and retains the release snapshot for comparison. Optional engine tuples remain unqualified until built and tested.

**Requirement links:** [DDK-LOCK-001](specification.md#DDK-LOCK-001), [DDK-VERSION-003](specification.md#DDK-VERSION-003). See [GitHub research](references.md#github).

## ADR-007 — Keep runtime adapters optional

**Problem:** mandatory engine and ingestion dependencies increase installation cost and can trigger imports or network behavior during basic checking.

**Decision:** discover manifests as data; install and import runtime integrations separately. Native tools own their runtime behaviors and are invoked only for explicit profiles.

**Consequence:** manifest presence alone never counts as capability proof. Missing optional required coverage produces incomplete results. The core can release independently of experimental adapters.

**Requirement links:** [DDK-ADAPTER-001](specification.md#DDK-ADAPTER-001), [DDK-ADAPTER-008](specification.md#DDK-ADAPTER-008), [DDK-VERSION-002](specification.md#DDK-VERSION-002).

## ADR-008 — Independent implementation and public provenance

**Problem:** the user cannot use the predecessor implementation because of licensing constraints.

**Decision:** write the new implementation, examples, schemas for new formats, tests, and documentation from independently specified requirements and public standards. Preserve public upstream material with source, revision, digest, and notices. Do not import predecessor artifacts.

**Consequence:** prior discussion supplies functional goals, not permission to reuse source. This authorship record is not a claim of a formal isolated clean-room process. Upstream dependency licensing must be rechecked on the actual distributions selected for release.

**References:** [PROVENANCE.md](../PROVENANCE.md), [NOTICE](../NOTICE), [upstream inventory](upstream-artifacts.json).
