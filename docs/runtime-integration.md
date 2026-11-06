# Runtime Integration Design

**Status: implemented local profiles under conformance qualification, November 5, 2026.** Normative requirements remain in the [specification](specification.md#integrations).

## Responsibility and ownership

DDK receives designs, dataset descriptions, parameters, and explicit bindings. It checks declarations offline. When requested, it asks an injected runtime to prepare or execute a calculation and asks a quality evaluator to check its exact output. It returns evidence with explicit coverage and uncertainty.

DocSpec owns calculation execution, native read views, protection of retained work, managed-operation recovery, and guarded dataset selection. DDK retains receipts and references. It does not maintain another lifecycle or mutable latest pointer.

DocSpec is team-owned and unreleased. Its public API can change to make this boundary simple. Preserve required behavior and retained identities; do not build compatibility shims for an unreleased interface merely because it exists today. The isolated DocSpec implementation supplies the required preparation, saved-plan, protected-read, and managed-qualification paths.

## Domain, application, and adapters

| Boundary | Owns | Dependencies |
| --- | --- | --- |
| Domain | Interfaces, declared datasets, compatibility, relationships, policies, check results | Standard concepts and simple typed records; no native implementation types |
| Application | Check a project, compare designs, prepare execution, run tests | Domain plus injected services needed by that use case |
| Adapters | Document parsing, CLI input/output, native validators, DocSpec transport | Their selected maintained tools |
| Composition root | Construct the requested use case and its concrete services | Explicit caller configuration and manifests |

Pass dependencies through constructors or function arguments. A general dependency container, plugin registry, universal plan representation, or empty package hierarchy adds no required behavior. Installed manifests remain data until a profile is selected.

## Application ports

| Port | What goes in | What happens | What comes out | How we check it |
| --- | --- | --- | --- | --- |
| `PlanService` | Implementation artifact, semantic profile, logical input schemas, effective parameters | Prepare through the chosen runtime without production rows | Supported/unsupported inventory, inferred output schemas, prepared artifacts and identities | Independent schema expectations; zero production scans |
| `JobExecutor` | Prepared calculation, exact bindings, limits, output destinations | Run a bounded job | Known outputs, native diagnostics, partial-failure information, execution receipt | Failure after one output; unknown outcome after process loss |
| `QualityEvaluator` | Exact dataset view, resolved rules, evaluator/mapping profile | Execute requested supported checks | Required-check inventory, individual outcomes, native evidence | Missing checks and unsupported rules cannot pass |
| `DatasetRuntime` | Supported managed request with stable operation ID and policy requirements | Admit, prepare, retain, inspect, reconcile, accept qualification, select under native authority | Candidate/operation references, accepted qualification reference, selection outcome | Cold recovery, lost response, mismatched evidence, authority races |

Implement the first three ports with the SQL/fixture milestone. Introduce `DatasetRuntime` with a concrete managed workflow. A single DocSpec adapter can implement preparation, bounded execution, and managed operations. The Data Contract CLI adapter implements quality evaluation for its supported access paths.

Start with structured subprocess requests and machine-readable responses. Add only the DocSpec preparation/receipt commands actually needed. Do not add a server, network protocol, or Python extension merely to establish injection. A subprocess is a transport boundary, not proof of durable operation tracking.

## Implementation meaning and execution settings

Component `implementation` identifies `format`, `path` or `entrypoint`, optional format-specific dialect, and `semantics: {id, revision}`. SQL requires a dialect. The semantic profile defines relevant function, null, overflow, collation, temporal, and type-mapping behavior.

Binding `execution` selects `runtime`, `adapter`, and `mode`; `connection` and `limits` are adapter-owned operational settings validated only on explicit invocation. Managed mode additionally records `operationId`, `requestKind`, and `qualificationRequired`, with a resolved `rules` artifact when qualification is required. Preserve the original request artifact or equivalent native protocol state before submission so caller restart can recover the identity without a DDK lifecycle database. Credentials come from an explicit runtime source and never enter published artifacts. Unknown semantic profiles do not prevent structural core checks, but cannot establish runtime semantic support.

An endpoint move can preserve meaning only when the same immutable inputs and qualified semantics remain established. A changed engine or function build remains a computation dependency until equivalence is established. Package version numbers alone neither prove a semantic change nor prove equivalence.

## File and native inputs

File bindings use `kind: files`, format, and an explicit SHA-256 file inventory. Native bindings use `kind: native` and `nativeVersion`. These alternatives are mutually exclusive.

The native wrapper identifies runtime, scheme, scheme version, namespace, native digest algorithm, and the original native reference. The selected profile owns that reference's schema. Core checks the wrapper without dereferencing it. This avoids inventing a universal replacement for native dataset manifests.

The adapter resolves a native reference to an exact read view. `nativeReads` records its version, schema identity, field identities, names, order, types, and nullability. The DocSpec adapter must preserve complete dataset-version interpretation, not select one convenient underlying table and call it the whole dataset. Missing or ambiguous group mappings are unsupported.

`DocSpecAdapter.inspect_version(workspace, nativeVersion)` checks an exact protected source version through the maintained native job input-admission path, with no steps, queries or exports. It returns the same receipt and `nativeReads` schema observation as a bounded query. The explicitly selected `urn:ddk:docspec:source-arrow:2` profile preserves recursive Arrow types and native field paths. This metadata observation does not establish a complete row read, quality, permanent availability or a lease across calls; each later query passes native protection checks again. `prepare` remains schema-only inference over supplied `{name, schema}` inputs and does not silently resolve native versions.

The initial proposed DocSpec reference scheme wraps its existing version reference, including the manifest identity. Its native object digests use BLAKE3; DDK artifact digests remain SHA-256. The scheme must reject a contradictory algorithm declaration. The [native examples](../examples/native/README.md) use fictional references and do not demonstrate resolution.

Protect inputs and candidates through DocSpec's existing native protection ownership. An immutable identifier does not promise future availability. Expiration or missing protection causes an explicit unavailable outcome, never a fallback to latest. No export/reimport is required merely to pass a reference through DDK. An explicitly requested export is its own file artifact.

## Bounded SQL path

1. DDK performs offline checks and selects the explicit SQL profile.
2. DocSpec prepares SQL against schema-only inputs and reports output inference.
3. DDK supplies exact file/native bindings and fixture expectations.
4. DocSpec executes the bounded job under its runtime limits and input/function checks.
5. The fixture runner compares outputs with independent expected rows.
6. Data Contract CLI evaluates supported output rules against the exact identified output.
7. DDK reports check coverage and the native execution outcome separately.

This path does not select a managed dataset release. Returned partial output identities are useful evidence but do not establish process-loss recovery. A timeout records what is known; it does not create a new operation or declare that nothing ran.

Current ordinary DocSpec inputs include Parquet, explicitly schematized JSON Lines, and native table references. They do not establish direct CSV support. The fixture runner materializes authored rows as explicitly typed temporary Parquet. The bound commerce workflow validates CSV with Frictionless and stages it with dlt, then passes the exact completed Parquet inventory to DocSpec. Receipts preserve this conversion and mark the declared reader output as injected data.

## Managed quality-gated path

The dev2 release qualifies the independent, unbased typed Build operation. Dev5 adds `prepare_update` with a native `UpdateSpec` for a selected independent, source-only local base. Both use DocSpec's existing native lifecycle and quality gate. The [dev5 package](local-release-dev5.md) qualifies this bounded scope; [implementation status](implementation-status.md) separates broader pending work.

1. Record the stable operation ID and native request identity before submission. Capture required rules and applicable policy preconditions.
2. DocSpec admits and prepares a retained candidate through its native lifecycle.
3. Inspect that candidate through an exact, protected read view.
4. The configured evaluator checks the resolved rule-set artifact, including inherited definitions and effective parameters.
5. DocSpec accepts the evidence only after validating candidate identity, evaluator identity, semantics, and complete required-check coverage.
6. DocSpec checks accepted qualification and current authority conditions in its guarded selection decision.
7. On a lost response, reconcile the original operation. Never create a replacement merely because the caller timed out.

Keep accepted qualification records separate from the candidate's computation identity. A new rule set can qualify already computed values. It must not silently change an admitted request; it needs an explicit qualification request with its own policy binding. Missing, duplicate, stale, wrong-candidate, or incomplete required results cannot qualify selection.

The native command remains `managed-build`; `prepare_update` is a distinct action carrying `update` and `policy`. DDK preserves the original dataset, operation, and native request identity on retry. Native Update owns correction, replacement, explicit deletion, and inherited-row behavior. A completed historical retry returns its original result without selecting it over a successor. A changed base refuses selection. Computed or related groups, Refresh, Backfill, and arbitrary managed SQL require separate profiles and tests.

The quality bridge is an implementation gate. File-backed CLI testing does not prove that the CLI can read an unselected DocSpec candidate directly. First demonstrate a supported exact-version query/view path without an unnecessary export. If unavailable, keep native quality-gated selection unqualified and ship the bounded file-backed path independently. Do not recreate a general quality language in DDK.

## Reuse, provenance, and uncertainty

`reuseRecords` references runtime-issued computation and qualification keys. DDK does not calculate an alternative native phase key. Locks and reports retain full provenance independently of the keys relevant to reuse.

`operations` reports `execution` independently from `selection` and check status. For example, a caller timeout can produce an error report, an unknown execution/selection outcome, and a not-run quality check. The original native operation ID remains available for reconciliation. An empty output list under uncertainty means no outputs were observed, not proof that no outputs exist.

The runtime accepts qualification; a caller cannot establish acceptance by writing a valid report or supplying a boolean. A selected quality-gated operation records the accepted native qualification identity. Same-ID resubmission is allowed only under native idempotency guarantees; a different request under that identity must be refused.

## Saved Substrait in the first product release

The qualified local DocSpec source pins DataFusion and datafusion-substrait 53.1.0 and supports the bounded saved-plan path. The earlier DataFusion Python GitHub snapshot remains research evidence for a separate candidate.

Run the bounded WP-00B compatibility experiment alongside early core and catalog development to choose a tested Rust DataFusion baseline in DocSpec. WP-09B integrates saved-plan production/consumption through DocSpec's existing context after SQL integration and verifies the final dependency tuple. Reuse applicable experiment evidence and update the baseline when tests justify the change. Apply normalized-plan function and input checks after decoding, and preserve admitted memory/spill/concurrency limits. Parsing a different format must not bypass execution restrictions.

The first product release requires saved-plan consumption and fixture correctness on the qualified DocSpec path. Keep compiler success, consumer support, standalone standard validity, output inference, and fixture correctness independent. A second engine must consume the same bytes and match independently authored expectations before portability is claimed.

## Records for catalog and lineage

The catalog consumes exact native metadata through a separate adapter. Link the execution receipt, original operation reference, input and output versions, and check evidence. Generate OpenLineage run events from supported observed lifecycle records and retain the native identity mapping. Declared production definitions supply separate job events. Metadata assembly reads existing records and preserves unknown outcomes and custody assumptions. The native runtime owns recovery and retained version protection.

## Evidence and next decision

The [local source inventory](docspec-evidence.json) records the DocSpec revision and owning code inspected for this design. It establishes source observations, not new runtime qualification. The [implementation plan](implementation-plan.md) assigns proposed changes to DDK and DocSpec separately. No optional capability is qualified by this document.
