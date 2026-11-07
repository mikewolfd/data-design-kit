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

When the native response supplies `native_versions[].physical_snapshot`, the adapter validates its exact selector, canonical table UUID, stored metadata SHA-256 and byte length before returning the original fields in `result`. The physical schema ID and snapshot may differ from the logical version after compaction; neither replaces the original `VersionRef` or observed Arrow schema. An absent observation remains compatible with older receipts but supplies no physical pin for producer admission. Malformed observations and duplicate or mismatched input identities produce `unknown`, with raw evidence retained as `unverifiedResult` and admitted results withheld. Later native producer admission must independently verify and protect the observed bytes. This metadata check grants no custody, producer authority, acceptance or selection.

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

The native command remains `managed-build`; `prepare_update` is a distinct action carrying `update` and `policy`. DDK preserves the original dataset, operation, and native request identity on retry. Native Update owns correction, replacement, explicit deletion, and inherited-row behavior. A completed historical retry returns its original result without selecting it over a successor. A changed base refuses selection. Computed or related groups, Refresh, Backfill, and arbitrary managed SQL require separately qualified capabilities, request kinds and tests.

The quality bridge is an implementation gate. File-backed CLI testing does not prove that the CLI can read an unselected DocSpec candidate directly. First demonstrate a supported exact-version query/view path without an unnecessary export. If unavailable, keep native quality-gated selection unqualified and ship the bounded file-backed path independently. Do not recreate a general quality language in DDK.

The successor `managed_job` caller uses a separate native whole-job candidate scheme. It retains the exact original prepare request and any requested native identity through response loss, verifies native original-byte witnesses, and preserves confirmed historical selection separately from the latest command outcome. Admitted computation that has not started remains `pending`. The caller owns bounded transport and metadata translation; DocSpec owns input custody, durable phases, native counter acceptance and selection. The four preparation and two-output examples passed through the installed dev6 package against immutable native source25, including rule-only requalification, caller-file loss and a nonzero counter refusal. Source25 also passed the complete native gate. These results do not extend dev6's native profile qualification. Schema-only `prepare_job` evidence establishes inference without input admission or execution.

Source-level version 2 witness checks additionally preserve exact `native_table` selectors, pinned metadata identities, original member locations, native ownership and original operation IDs. They compare the complete input and view records without opening payloads, reject malformed or mismatched copies, and distinguish an empty selected snapshot from missing evidence. Version 1 file evidence remains separate. These authored metadata cases do not prove the native read closure, delete processing, cross-operation reuse or prerequisite acceptance. The successor catalog maps these exact source observations through its [catalog-only native-table scheme](catalog-api.md#native-table-catalog-observations), while preserving unknown current availability and explicit reader support boundaries. See the [metadata verification record](verification.md#november-6-2026-native-snapshot-metadata-checks).

Separate native and public DDK adapter tests now exercise exact local selected-snapshot custody and same-operation recovery. They preserve actual values, nulls and field IDs, recover an incomplete operation after original metadata removal, refuse wrong pins, and replay native acceptance before selection. Fixture creation uses the public DocSpec CLI; DDK's ordinary calculation profile still excludes catalog writes. These focused source results do not qualify cross-operation reuse, producer prerequisites, deletes, remote inputs or an installed successor. See the [native consumer evidence](verification.md#november-6-2026-local-native-snapshot-custody).

The source version 3 verifier binds the same `producer_evidence` in completion and view-set records to one exact retained witness. It checks the common native profile, original operation and request, adoption identity and model prerequisite. Every repeated identity receives native type checks; digest equality does not erase integer-token distinctions. The model must name the complete same-name native scope and its proof custody. Its adopted prerequisite order remains distinct from current JobSpec ordinals. A proof has original producer records and no file inputs, exports or selected-model claim. Earlier profiles cannot acquire producer authority through extra fields. Private static checks, definition interpretation, accepted-proof resolution and availability remain DocSpec responsibilities; DDK opens no referenced artifacts and introduces no adoption authority port. [Metadata evidence](verification.md#november-7-2026-native-producer-evidence-metadata) is separate from native producer qualification.

The source native interface uses `reuse_from` to request an already retained input. DDK's source verifier checks the exact native-issued reference, including the lifecycle table UUID and record generation, while preserving its opaque admission digest. New complete observations must bind `custody_reference` in both witnesses and the receipt; reuse also requires a `custody_grant` matching the original request. All current references and each same-owner grant use the same lifecycle table identity. Historical candidates retain their old witnesses and cannot acquire unbound new handles. A handle on an incomplete operation establishes no catalog input binding or accepted qualification. DocSpec remains responsible for resolving the reference, protecting transferred copies and recovering after the original operation retires. [Metadata tests](verification.md#november-6-2026-input-custody-reference-checks) cover the DDK checks; they do not establish that native transfer behavior.

The local catalog's [producer evidence trace](catalog-api.md#native-producer-evidence-in-local-catalogs) preserves the verified native role, adoption and original prerequisite references without copying private witness payloads. Accepted qualification remains a separate observation. Its eleven focused metadata checks establish mapping and disclosure behavior, not new native execution or current proof availability.

The local source09 runtime and public DDK consumer now exercise same-owner reuse, including chained and renamed inputs after original source and caller-file removal. Native units separately verify receiving custody through donor retirement before input sealing and preserve original provenance under result retention. Fifteen public cases pass at unchanged limits. These results qualify neither original producer prerequisites nor an installed successor. See the [reuse execution evidence](verification.md#november-6-2026-native-input-reuse-through-ddk).

The later native producer source05 and six public DDK source cases exercise original-record proof admission, actual accepted-proof prerequisites, fixed model file/policy identity and same-operation cold recovery. DDK preserves the exact native proof, custody and acceptance references; DocSpec performs the checks and guards model selection. The proof itself cannot be selected. The separate [producer execution evidence](verification.md#november-7-2026-producer-prerequisites-through-ddk) records the immutable executable and source tuple. It does not establish historical writer execution, production source acceptance or installed successor qualification.

The pure `producer_model_bindings(proof, prerequisite_inputs=adopted_input_names)` helper accepts the immutable result of `verify_completed_job` only when it records an accepted version 3 producer proof. It returns independent `inputs`, `schemas` and `request` values. The request contains the original adoption, same-name snapshot reuse from the proof's current custody references, and its accepted prerequisite. It opens no artifacts and resolves no native authority.

The supplied prerequisite order must be a unique complete set of proof input names in the adopted definition's order. That order may differ from the proof's input order, which remains unchanged in returned selectors, schemas and snapshot handles. The caller verifies its complete model inventory, original adopted definition and receiving owner/operation and supplies its own epoch and selection conditions. Native admission independently validates the adopted order, original identities, availability and custody. [Metadata and retained-model comparison](verification.md#november-7-2026-accepted-proof-model-bindings).

The source `publication_intent` method calls DocSpec's concrete freeze/inspect command. Its local-fixture scope saves a decision for an accepted whole-job candidate; it does not contact a publisher. DDK preserves the original private freeze request and translates the native response into a separate `publicationIntent` observation. It checks repeated identities and inline control pins without opening output objects. Native intent digests, inventory digests, and lifecycle references remain owner-issued identities; DDK does not recompute them or own retention. Two focused public DDK/DocSpec consumer cases now verify local freeze, refusal, cold replay, historical selection and retired-audit observation. Installed and provider qualification remain separate. See the [actual native evidence](verification.md#november-7-2026-native-publication-intent-through-ddk).

Keep the private evidence directory for cold recovery. After a lost first freeze response, replay the exact saved freeze request, including its original caller paths; native replay resolves the saved decision before opening those paths. An unbound inspect can observe another request that won under the same producing operation. Once a full native intent reference is verified, subsequent inspection must match its immutable audit. A missing response or refusal preserves that historical reference with current payload state `unknown`; a verified retirement keeps the audit and reports `retired`. A fresh inspect can report explicit `not_found`. Neither a native saved decision nor a successful transport response establishes external authorization or publication.

Publication stdout capture and private recovery metadata each default to 8 MiB. `capture_bytes` bounds the native reply; `metadata_bytes` separately bounds requests eligible for submission, compact receipts and their later reads. The compact receipt pins the raw native reply rather than copying its inline controls. An oversized request refuses before submission; its retained refusal artifact may exceed that submission limit. A final receipt that cannot fit raises an error and leaves the original request and raw native reply in place; it cannot return a saved-success response. After prior evidence is checked, only its immutable audit and state remain live during the next call.

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
