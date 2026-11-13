# DDK work backlog

Updated November 13, 2026, after the [shared-stack review](/Users/mikewolfd/Work/artifacts/ddk-lessons-review-2026-11-13/REVIEW.md) and [assessment](/Users/mikewolfd/Work/artifacts/ddk-lessons-response-20261113/ASSESSMENT.md). Delivery priority is **performance, quality, then transparency**. Build a useful fresh application alongside the shared capabilities it needs, beginning with a real question and source family and expanding to the complete required scope.

Repository-root [.tickets](../.tickets/) files own status, dependencies, assignees and acceptance criteria. This page owns delivery order and parked decisions. The [implementation plan](implementation-plan.md), [specification](specification.md) and [work-package registry](../implementation/work-packages.json) retain normative requirements and historical qualification. Reprioritizing a ticket changes neither a requirement nor a runtime qualification claim.

## Greenfield delivery

This is all greenfield. Current user needs, source meaning and actual consumers determine what to build. Old applications, APIs, table inventories, intermediate formats and stopped branches supply research and evidence; they impose no automatic compatibility or migration requirement. Retain useful originals, independently expected results and demonstrated shared capabilities. Select keep, replace or intentional-drop decisions explicitly, including the final required source and consumer inventory.

Use maintained source libraries for acquisition, DocSpec for execution, durable recovery, protection and guarded selection, and DDK for definitions, catalog meaning and evidence mapping. Shared publication and serving adapters consume those owners. Products supply source scope, domain SQL, definitions and configuration. Measure total application-plus-shared-system cost: moving custom infrastructure into another repository does not establish simplification.

The two application epics can start now. Links to shared tasks describe completion obligations; they do not require finishing the platform before building the applications. Ticket dependencies represent actual final-acceptance prerequisites. Shared tasks can use bounded independent cases while the real consumer develops. Final application acceptance still covers every selected source mode, required behavior and consumer.

Owner roles identify responsibility; an unassigned role does not mean a person accepted the task. Coordinate implementation in its owning repository and link its concrete task here. Do not create a second implementation ticket for the same gap.

## Active work in user-value order

P1 covers working data paths and dependable delivery, P2 covers release simplification and adoption, and P3 covers optional metadata and maintenance. This order is more precise than those broad priorities; required meaning, quality and disclosure accompany each working path.

| Order | User outcome and remaining work | Canonical work items |
| --- | --- | --- |
| 1 | Build the first complete, useful journey and define final product scope and measurable workloads. | [ddk-arnm](../.tickets/ddk-arnm.md): questions, source families/modes and keep/replace/drop decisions; [ddk-z8mp](../.tickets/ddk-z8mp.md): fresh SpicyRegs epic; [ddk-h9l3](../.tickets/ddk-h9l3.md): fresh Congress epic; [ddk-zxlb](../.tickets/ddk-zxlb.md): numerical latency, freshness, I/O, memory and disk budgets. These proceed together. |
| 2 | Open large admitted data predictably and keep unrelated data usable when one owner fails. | [ddk-eu0k](../.tickets/ddk-eu0k.md): cold-read identity and shard work; [ddk-p3mc](../.tickets/ddk-p3mc.md): owner failure isolation; [dv-dnke](../.tickets/dv-dnke.md): default/environment runtime query capability. Coordinate the native page, decimal and bounded-witness tasks below. |
| 3 | Acquire and refresh real sources with shared readers and recovery. | [ddk-p6kl](../.tickets/ddk-p6kl.md): retained acquisition to DocSpec jobs across selected bulk/API/document modes, including empty, partial, deleted and failed outcomes. |
| 4 | Publish one coherent remote data-and-catalog release and recover safely. | [ddk-5svu](../.tickets/ddk-5svu.md): shared accepted-job publication, one selection authority, immutable transfer, lost-response reconciliation and actual remote readback. |
| 5 | Discover and query configured products through shared consumers. | [ddk-citj](../.tickets/ddk-citj.md): HTTP/MCP/viewer discovery, required bounded queries and evidence access using real remote representations. Supported datasets must not require table-specific server branches. |
| 6 | Know what an answer means, what is missing and where its records came from. | [ddk-251s](../.tickets/ddk-251s.md): expected sources with zero acquired versions, gaps and assessment limits; [ddk-pi9u](../.tickets/ddk-pi9u.md): actual answer to records to retained originals; [ddk-v2x8](../.tickets/ddk-v2x8.md): supported field meanings and scoped shared keys. Required meanings belong in the initial journey; broader research can follow. |
| 7 | Accept complete application releases through shared publication and actual consumers. | [ddk-x3uy](../.tickets/ddk-x3uy.md): SpicyRegs release acceptance; [ddk-8ror](../.tickets/ddk-8ror.md): Congress release acceptance. Both depend on shared publication and serving, and contribute to their application epic. Neither requires a product-specific publisher. |
| 8 | Obtain a smaller, clearly supported and reproducible package. | [ddk-aw0v](../.tickets/ddk-aw0v.md): choose the greenfield release surface and revise superseded requirements together; [ddk-w3df](../.tickets/ddk-w3df.md): independent job-input layer-order case and traceability; then [ddk-b2tk](../.tickets/ddk-b2tk.md): exact current qualification, [ddk-c7v1](../.tickets/ddk-c7v1.md): portable handoff/inventories/guides, and [ddk-or08](../.tickets/ddk-or08.md): naming, destination and package publication. Full application completion is not a package-release prerequisite. |
| 9 | Validate a designed but unbuilt map without implying executed quality. | [ddk-nqut](../.tickets/ddk-nqut.md): explicit definitions-only qualification, WP-15 item 6. |
| 10 | Add useful metadata after working data delivery. | [ddk-ucoh](../.tickets/ddk-ucoh.md): edition series; [ddk-i3g8](../.tickets/ddk-i3g8.md): status vocabulary with optional enforcement; [ddk-sf5m](../.tickets/ddk-sf5m.md): ODCS schema deduplication. Publisher-native values and distinctions remain intact. |

From the repository or `viewer/`, use `tk ready`, `tk blocked` and `tk dep cycle` to inspect the graph. Ready means work can start; it does not prove acceptance. Close implementation work with its promised checks and exact source/input/tool identities. Required missing evidence, skipped checks, `unknown` and `not_run` prevent an overall passing claim. Reuse unchanged evidence only when identity and scope match. Keep build controls, environments and generated evidence outside this repository.

## Shared native work

These DocSpec tickets own native implementation. DDK coordination and consumer acceptance link to them without creating another native owner.

| Priority | Native work | Relationship to DDK |
| --- | --- | --- |
| P1 | [dr-agq0](/Users/mikewolfd/Work/spicy-stack/docspec-rs/.tickets/dr-agq0.md): decode selected Parquet pages rather than all preceding rows. | Separate file identity verification, shard selection and page decoding; returned row count alone does not prove bounded I/O. |
| P1 | [dr-rtdp](/Users/mikewolfd/Work/spicy-stack/docspec-rs/.tickets/dr-rtdp.md): exact decimal query parameters. | Split from reader performance because numerical correctness has an independent failure and acceptance test. |
| P1 | [dr-y2qm](/Users/mikewolfd/Work/spicy-stack/docspec-rs/.tickets/dr-y2qm.md): bounded references for large retained job witnesses. | Bind the exact native result without duplicating oversized inline data. Measure response and memory costs through the DDK consumer. |

## Review-to-work mapping

| Feedback | Integrated decision and owner |
| --- | --- |
| F1: whole-job remote publication | Shared implementation in [ddk-5svu](../.tickets/ddk-5svu.md); fresh-application acceptance in [ddk-x3uy](../.tickets/ddk-x3uy.md) and [ddk-8ror](../.tickets/ddk-8ror.md). Credit existing remote-storage mechanisms; local intent alone does not establish complete publication. |
| F2: generic serving | [ddk-citj](../.tickets/ddk-citj.md) absorbs the prior inspector/MCP task. Select required named-query and bounded ad-hoc behavior from user questions. Keep DDK core offline. |
| F3: cold-read work | [ddk-eu0k](../.tickets/ddk-eu0k.md) coordinates admitted immutable reads; [dr-agq0](/Users/mikewolfd/Work/spicy-stack/docspec-rs/.tickets/dr-agq0.md) owns page decoding; [ddk-zxlb](../.tickets/ddk-zxlb.md) owns workload targets. |
| F4: owner startup isolation | [ddk-p3mc](../.tickets/ddk-p3mc.md) owns the reproduced registry failure, with malformed-configuration and public-mode controls. |
| F5: acquisition and refresh | [ddk-p6kl](../.tickets/ddk-p6kl.md) connects maintained source readers and native jobs. Application scope identifies required modes; use existing scheduling and recovery. |
| F6: answer-to-original proof | [ddk-pi9u](../.tickets/ddk-pi9u.md) keeps existing artifact pins, the independent one-vote expectation and direct original pointers. No new citation format or retired receipt dependency is prescribed. |
| F7: frozen release burden | [ddk-aw0v](../.tickets/ddk-aw0v.md) reconciles requirements, implementation and profiles together. Historical qualification stays historical; retiring a wrapper does not silently remove required saved-Substrait or standards behavior. |
| Missing/unassessed source coverage | [ddk-251s](../.tickets/ddk-251s.md) includes required sources with no acquired versions, matching denominators and affected questions. |
| Avoid platform-first delivery | [ddk-arnm](../.tickets/ddk-arnm.md) and the application epics start real consumer work alongside shared development. Whole-product acceptance remains distinct from the first useful journey. |

<a id="deferred-extensions-in-the-priority-review"></a>

## Deferred extensions

These entries own parked decisions. Promote one to a scoped ticket when its need is selected, then replace the entry with its ticket link. They add no release requirement. The earlier [metadata proposal](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-ya7w.md) redirects here.

| Capability and owner | Promotion condition and completion evidence |
| --- | --- |
| Property-level origin — DDK catalog and definition owners. | A consumer needs field attribution beyond dataset origin. Specify one maintained source; preserve paths/native IDs; verify independent examples and disclosure. |
| New descriptive DCAT mappings — DDK interchange owner. | A downstream catalog needs fields already retained by DDK. Define standard mappings and omissions; verify with an independent graph reader. |
| Output-port `context` — DDK product/catalog owner. | A consumer needs publisher port context. Define its source and propagation; exercise multiple ports and omitted context. |
| Additional graph/RML shapes and links — DDK graph owner with application rule owners. | A consumer needs arrays of arrays, nested array-item structures, paths crossing arrays, external targets or `project_rule` links. Update semantics, mappings and independent cases together. Missing definitions, withheld keys, unknown null rules and unresolved scope remain explicit limits. |
| Public OpenLineage export — DDK interchange and disclosure owners. | A publisher requires public lineage. Define disclosure of identities, paths and events; verify allowed fields, withheld data, deterministic output and atomic failure. Current public export remains `not_run`. |

These entries retain [WP-14 mapping limits](implementation-plan.md#wp-14--dcat-and-openlineage-interchange), [WP-15 deferred metadata](implementation-plan.md#wp-15--layered-data-map-extensions-specified-not-implemented) and the [public-lineage boundary](../src/ddk/catalog.py).

## Optional product extensions

| Capability and original proposal | Entry condition and evidence |
| --- | --- |
| Value synonyms and concept facets — [ss-j0xx](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-j0xx.md). | A fresh consumer needs them. Use one maintained definition source and preserve distinct publisher meanings; no competing synonym authority. |
| Successor relationships and former names — [ss-djaw](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-djaw.md). | A publisher-backed use case needs explicit relationships and stable identity. This metadata deferral does not defer correction/deletion semantics in acquisition and publication. |
| Precomputed distribution summaries — [ss-u3v6](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-u3v6.md). | A consumer needs summaries with measurable value. Bind exact inputs and computation, retain missing/unknown states, and do not treat distributions as proof of source completeness. |
| `agent.md`/WebMCP helpers — original [ss-alp4](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-alp4.md). | A consumer needs an additional access convention. Required shared HTTP/MCP/catalog access is already active in ddk-citj. |

## Other optional or frozen work

These decisions need concrete consumers; they are not promised delivery or missing required tests.

| Work and responsible owner | Entry condition and evidence needed |
| --- | --- |
| Human usability study — product research owner. | Choose participant validation. Use retained tasks and answer key, record observations and retest misunderstandings. The accepted simulated study and closed tickets remain complete; human improvement is unmeasured. |
| Additional operating systems, architectures or Python versions — release owner. | An adopter needs a platform outside the qualified tuple. Supply exact package/native builds, dependency inventories, clean install and consumer acceptance. |
| Remote evaluator authentication — evaluator/application owner. | A required evaluator uses a remote service. Keep credentials with its owner; prove exact candidate identity, complete rule coverage, refusals and bounded execution. |
| Nested staging — ingestion owner. | A workflow requires it and ADR-015 scope is reconsidered explicitly. Preserve missing/null/empty, field identity and exact values through the maintained adapter. |
| Independent saved-Substrait validation — plan adapter owner. | A consumer needs standalone standard validity. Qualify the exact validator/extensions and independent invalid/unknown cases. Saved-plan execution remains a separate claim. |
| Second-engine portability — plan adapter owner. | A consumer needs another engine. Execute the same saved bytes and inputs against independent expected rows; separately compiled SQL does not establish portability. |
| Hosted registry, remote dependency fetching and organization-wide discovery — platform owner. | Select a multi-project discovery need. Define identity, authority, disclosure, failure and offline behavior. Required configured-product serving is already active. |
| Generic quality templates — definitions/policy owner. | ODCS definitions cannot express a required reuse need. Reuse the maintained language; prove expansion, identity and rule coverage. |
| General nested compatibility, generic SQL dependency inference and arbitrary schema containment — architecture owner. | Reconsider ADR-015 for a concrete need. Define a sound subset and independent refusal/unknown cases. |
| CUE policy execution and non-Python implementations — adapter owner. | Select an adopter and run the same independent conformance cases for the claimed subset. |
| New scheduling, deployment and credential frameworks — platform owners. | Existing maintained services cannot meet a selected operating need. Shared acquisition, remote publication and serving are already active; this deferral concerns additional infrastructure. Keep lifecycle in DocSpec and one selection authority. |
| Arbitrary managed SQL, automatic incremental planning, broader backends and a general quality-rule framework — native/evaluator owners. | Show a required operation outside current typed paths. Define evidence, limits, reuse and recovery before extending the maintained owner. |
| Additional bindings, speculative plugins and universal calculation formats — architecture owner. | Show a need beyond selected shared CLI/library/HTTP/MCP/viewer paths. Prefer maintained interfaces and require consumer evidence for a new boundary. |

The [implementation-plan deferrals](implementation-plan.md#10-decisions-intentionally-deferred) and [ADR-015](architecture-decisions.md#adr-015--keep-ddk-to-the-evidence-bound-catalog) govern these decisions. This register adds no approval requirement to authorized work.

## Reconciliation and preserved completion

- The earlier viewer-to-root move retained ticket identities and history. All 26 closed viewer tickets stay closed and unchanged by this reconciliation; the runtime bug remains the same `dv-dnke`.
- Existing coordination tickets now define fresh product outcomes. Stopped application/runtime continuation tickets redirect as **superseded**, not completed. Retained branches and evidence receive no deletion or resumption instruction.
- Duplicate inspector, metadata, lineage, key-meaning, performance and job-policy requests redirect to one canonical owner as **merged**. Optional proposals redirect to the parked register as **deferred**. Original requests and notes remain in the closed tickets; closure establishes no implementation or acceptance claim.
- Job-input layer traversal already exists. Its independent job-specific example and traceability remain in `ddk-w3df`; the earlier feature request is not falsely marked implemented-and-qualified. Native page selection and decimal accuracy now have separate tasks.
- Recipe gates, job productions and ODCS zero-counter SQL remain implemented. Edition series, status vocabulary, definitions-only qualification and ODCS schema deduplication retain one active ticket each. Judgement crosswalks stay dropped.
- [November 13 test evidence](verification.md#november-13-2026-zero-skip-installed-and-viewer-checks) retains 1,242 Python, 112 viewer unit, 65 browser and two historical replay passes, all zero-skip. It does not qualify planned work. [Greenfield reconciliation checks](verification.md#november-13-2026-greenfield-feedback-integration) separately record fresh document, ticket and focused test checks.
