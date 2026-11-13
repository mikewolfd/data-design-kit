# DDK work backlog

Updated November 13, 2026, against source `93bfd2e`. This is the user-value order for DDK, its viewer, and the application acceptance coordinated by DDK. Working data access comes first, followed by dependable delivery, adoption, metadata and maintenance. Dependencies determine execution order within those priorities.

Tickets in the repository-root [.tickets](../.tickets/) directory own work status, dependencies, assignees and completion criteria. This page owns the priority order and deferred decisions. The [implementation plan](implementation-plan.md) and [work-package registry](../implementation/work-packages.json) retain requirement ownership and historical qualification. A new backlog item changes neither a normative requirement nor a release claim.

Owner roles identify responsibility; an unassigned ticket does not imply that a person has accepted it. Application tickets coordinate existing owner work and acceptance rather than creating a second application backlog. The first application task reconciles current owner evidence before scheduling implementation.

## Active work in user-value order

P1 covers access and delivery; P2 covers catalog meaning; P3 covers maintenance. The numbered order below is more precise than those broad ticket priorities. Each ticket defines scope and independent completion evidence.

| Order | User outcome and remaining work | Canonical work items |
| --- | --- | --- |
| 1 | Queries work with the default or environment-configured runtime. | [dv-dnke](../.tickets/dv-dnke.md): fix default query capability while preserving explicit disable and startup validation. |
| 2 | Real SpicyRegs and Congress data completes the producer-to-consumer journey. | [ddk-arnm](../.tickets/ddk-arnm.md): reconcile evidence and owners; [ddk-z8mp](../.tickets/ddk-z8mp.md): SpicyRegs acceptance; [ddk-h9l3](../.tickets/ddk-h9l3.md): Congress acceptance. |
| 3 | Application updates remain coherent through publication failures and retries. | [ddk-x3uy](../.tickets/ddk-x3uy.md): SpicyRegs publisher; [ddk-8ror](../.tickets/ddk-8ror.md): Congress publisher. Each depends on its own application's acceptance. |
| 4 | Users can obtain, install and operate an identified supported release. | [ddk-b2tk](../.tickets/ddk-b2tk.md): current profile qualification; [ddk-c7v1](../.tickets/ddk-c7v1.md): portable handoff, inventories and guides; [ddk-or08](../.tickets/ddk-or08.md): destination, naming and package publication. Application replacement is not a first-package-release prerequisite. |
| 5 | Authors can validate a designed but unbuilt map. | [ddk-nqut](../.tickets/ddk-nqut.md): definitions-only qualification, WP-15 item 6. |
| 6 | Users know practical size, time, memory and disk limits. | [ddk-zxlb](../.tickets/ddk-zxlb.md): catalog and native-quality measurements, cancellation and bounded failure behavior. |
| 7 | Fields have supported meanings and precise remaining questions. | [ddk-v2x8](../.tickets/ddk-v2x8.md): owner-maintained field research and regenerated catalogs. Closed viewer presentation work stays closed. |
| 8 | Consumers can follow periodic editions and declared predecessors. | [ddk-ucoh](../.tickets/ddk-ucoh.md): DCAT edition series, WP-15 item 2. |
| 9 | Dataset and product statuses have comparable meanings. | [ddk-i3g8](../.tickets/ddk-i3g8.md): pinned status vocabulary and optional enforcement, WP-15 item 5. |
| 14 | Maintainers keep one schema without losing upstream distinctions. | [ddk-sf5m](../.tickets/ddk-sf5m.md): ODCS 3.2.0 deduplication, WP-15 item 7. |

Orders 10–13 are deferred extensions below, preserving the priority review's numbering. They are not in `tk ready`. From the repository or `viewer/`, use `tk ready`, `tk blocked` and `tk dep cycle` to inspect the active dependency graph.

Close implementation work only with its promised checks and exact source/input/tool identities. Required missing evidence, skipped checks, `unknown` and `not_run` prevent an overall passing claim. Reuse unchanged evidence when identities and scope match. Keep build controls, environments and generated evidence outside the repository.

## Deferred extensions in the priority review

These entries own the parked decision. Promote one to a scoped ticket when its stated need is selected; then replace its entry with the ticket link. None changes the current release requirements by being listed here.

| Order | Capability and owner | Promotion condition and completion evidence |
| --- | --- | --- |
| 10 | Property-level origin — DDK catalog and definition owners. | A consumer needs field-level attribution beyond dataset origin. Specify one maintained source for field origin; preserve paths and native IDs; verify independent examples and disclosure. |
| 11a | New descriptive fields in DCAT — DDK interchange owner. | A downstream catalog needs the fields already retained by DDK. Define exact standard mappings and omissions, then verify them with an independent graph reader. |
| 11b | Output-port `context` — DDK product/catalog owner. | A product consumer needs the publisher's port context. Define its source, meaning and propagation without creating another source of truth; exercise multiple ports and omitted context. |
| 12 | Additional graph/RML shapes and links — DDK graph owner, with application rule owners. | A concrete consumer needs arrays of arrays, nested array-item structures, paths crossing multiple arrays, external targets or `project_rule` links. Establish exact semantics first; update specification, mappings and independent materialization cases together. Missing definitions, withheld keys, unknown null rules and unresolved scope remain explicit limits. |
| 13 | Public OpenLineage export — DDK interchange and disclosure owners. | A publisher requires public lineage. Define disclosure for identities, paths and events; verify granted fields, withheld data, deterministic output and atomic failure. Current public export remains `not_run`. |

These entries consolidate [WP-14's mapping limits](implementation-plan.md#wp-14--dcat-and-openlineage-interchange), [WP-15's deferred metadata](implementation-plan.md#wp-15--layered-data-map-extensions-specified-not-implemented), and the [current public-lineage boundary](../src/ddk/catalog.py).

## Other optional or frozen work

The order below follows user value when there is a concrete consumer. These are decisions to revisit, not promised delivery or an incomplete test suite.

| Order | Work and responsible owner | Entry condition and evidence needed |
| --- | --- | --- |
| 15 | Human usability study — product research owner. | Choose actual participant validation. Use the retained tasks and answer key, record observations and retest misunderstandings. The user-accepted simulated study and its closed tickets remain complete; human improvement is unmeasured. |
| 16a | Additional operating systems, architectures or Python versions — release owner. | An adopter needs a platform outside the qualified tuple. Provide the exact package/native build, dependency inventory, clean install and consumer acceptance. |
| 16b | Remote evaluator authentication — evaluator/application owner. | A required evaluator uses a remote service. Keep credentials with its owner and prove exact candidate identity, complete rule coverage, refusals and bounded execution. |
| 16c | Nested staging — ingestion owner. | A concrete workflow requires it and the ADR-015 scope is explicitly reconsidered. Preserve missing/null/empty distinctions, field identities and exact values through the maintained staging adapter. |
| 17a | Independent saved-Substrait validation — plan adapter owner. | A consumer requests a standalone standard-validity claim. Qualify the exact validator/extension tuple and independent invalid/unknown cases. Existing saved-plan execution remains a separate completed claim. |
| 17b | Second-engine portability — plan adapter owner. | A consumer needs another engine. Execute the same saved plan bytes and inputs in both consumers against independent expected rows; separately compiled SQL does not establish portability. |
| 18 | Hosted registry, remote dependency fetching and organization-wide discovery — product/platform owner. | Select a real multi-project discovery need. Specify identity, authority, disclosure, failure and offline behavior before extending the local-file catalog model. |
| 19a | Generic reusable quality templates — definitions/policy owner. | Existing ODCS definitions cannot express a concrete reuse need. Reuse the maintained quality language and prove rule expansion, identity and coverage. |
| 19b | General nested compatibility, generic SQL dependency inference and arbitrary schema containment — architecture owner. | Reconsider ADR-015 for an identified consumer. Define a sound supported subset and independent refusal/unknown cases; do not extend frozen design/impact paths indirectly. |
| 19c | CUE policy execution and non-Python implementations — adapter/implementation owner. | Select a concrete adopter. Reuse maintained formats and run the same independently authored conformance cases for the claimed subset. |
| 20a | Scheduling, deployment, automatic publication and credential services — platform and publisher owners. | Select a production operating model. Keep native lifecycle with DocSpec and selection with existing publishers; qualify recovery, authority and credential boundaries for that service. |
| 20b | Arbitrary managed SQL, automatic incremental planning, broader backends and a general quality-rule framework — DocSpec/runtime and evaluator owners. | Demonstrate a required operation outside current typed paths. Define composition, exact evidence, limits, reuse and recovery before extending the responsible maintained system. |
| 20c | Additional servers/bindings, speculative plugins and universal calculation formats — architecture owner. | Show a use case not served by the existing CLI, library or viewer. Prefer a maintained interface; any new boundary needs its own consumer and conformance evidence. |

The [implementation plan's deferrals](implementation-plan.md#10-decisions-intentionally-deferred) and [ADR-015](architecture-decisions.md#adr-015--keep-ddk-to-the-evidence-bound-catalog) govern these decisions. This register adds no approval requirement to work already authorized by the user.

## Reconciliation and preserved completion

- The 27 viewer tickets moved from `viewer/.tickets/` to root `.tickets/`, retaining IDs, parent/dependency relationships, dates and notes. Relative Markdown links now point to their original viewer targets. Historical inline paths and commit references retain their original viewer/archive context.
- `dv-dnke` is the same open bug, refined and raised from P3 to P1. The other 26 viewer tickets remain closed. The optional human study is separate from the accepted simulated study.
- The four specified-only WP-15 items each have one active ticket. Recipe gates, job productions, ODCS zero-counter SQL and the zero-skip test repairs remain implemented; they are not new feature tickets.
- The application/runtime plan supplies acceptance requirements and historical evidence. The three application coordination tickets own current reconciliation and acceptance; the two publisher tickets own the separate activation/recovery gaps. Already implemented native mechanisms are credited before creating additional owner work.
- Release qualification, portable delivery and package publication are separate dependent tickets. The SQL-only software bill of materials and operator-guide refresh are merged into the portable handoff. Public naming is merged into the publication decision.
- [November 13 test evidence](verification.md#november-13-2026-zero-skip-installed-and-viewer-checks) records 1,242 Python tests, 112 viewer unit tests, 65 browser tests and two additional historical replay checks, all passing with zero skips, plus clean type checking and build. These results do not restamp the older SDK3 profile or portable claims.
- Judgement crosswalks were dropped. The older interface, design, compatibility, impact, intake, saved-plan, fixture, bundle and binding scope stays frozen under ADR-015; ordinary jobs do not become managed recovery.
