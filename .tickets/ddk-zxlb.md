---
id: ddk-zxlb
status: open
deps: []
links: [ddk-arnm, ddk-eu0k, ddk-5svu, ddk-citj, ddk-p6kl, ddk-251s, ddk-pi9u]
created: 2026-11-13T19:03:50Z
type: task
priority: 1
tags: [ddk, backlog, 2026-11-13]
---
# Set and measure greenfield workload budgets from acquisition through user queries

Owner role: Product/performance owner with DDK, DocSpec, source and serving owners.

User outcome: Users get predictable query latency, refresh freshness and resource costs at the selected product scale.

Choose workloads and numerical targets before consequential experiments; measure the real fresh application while it is built. Cover acquisition, unchanged/small/full refresh, native checks, remote transfer, startup and cold/warm queries. Keep the old 1,000-artifact/10,000-relationship and five-second/256-MiB catalog targets as historical proposals until selected and measured. They do not stand in for data-serving performance.

Sources: [Review priorities](/Users/mikewolfd/Work/artifacts/ddk-lessons-review-2026-11-13/REVIEW.md#governing-intent-performance-quality-transparency), [performance acceptance](../docs/implementation-plan.md#8-performance-and-resource-acceptance).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- Record target first-page/query latency (including p95 where a repeated workload supports it), freshness lag, bytes/requests, aggregate memory, peak scratch/output/retained disk and allowed concurrency with the chosen machine/storage tuple.
- At fixed update size, grow population, files and history; measure unchanged refresh, corrections/deletions, backfill, rebuild and interruption/resume. Admit available capacity before running.
- Measure cold and warm file/shard/page reads through the actual serving adapter, separating digest, metadata, decode, query and network costs.
- Measure required quality paths with complete rule/row coverage, a last-batch violation and wrong-candidate/truncation refusals; correctness and uncertainty remain explicit.
- Investigate incidental evaluator fingerprint invalidation from ss-sv2r only against measured repeated work. Any semantic reuse key still binds exact candidate, effective rules, relevant implementation/runtime dependencies and accepted evidence; unchanged semantic labels alone cannot authorize reuse.
- Retain raw measurements, failed attempts and source/input/tool identities outside the repository; report unsupported limits and total shared-plus-application cost without claiming a speedup from deleted code alone.

- Benchmark exact compound-key lookup, filtered/ordered paging, whole-table queries across partitions and an unprepared cross-table question on exact remote release members. Include ties, empty results, missing members and interruption; separate returned rows from files/pages/bytes scanned and enforce planning/execution limits.
- Measure compact availability/inventory reads and summary computation/refresh against a page-open corpus scan. For repeatedly consumed answers such as docket/day comment counts, compare a small SQL-derived output before adding stored layouts or indexes.
- For selected record-content search, compare a bounded SQL route with the maintained search owner using independently selected relevance examples, exact hit identities, cold/warm latency, client bytes, indexing/refresh time and retained disk. Record actual evidence before selecting infrastructure.

Integrated [user-value review](/Users/mikewolfd/Work/artifacts/ddk-user-value-review-2026-11-13/REPORT.md) on November 13, 2026. These are planned acceptance requirements; the static review supplies no runtime or performance qualification.

## November 13 bounded vertical progress

The local SpicyGov probe uses explicit source/member/native/result limits and records source/receipt bytes, retained bytes and stage timings. These are measured small-cohort costs and chosen probe limits; production p95, physical I/O, aggregate process memory, freshness and remote costs remain unmeasured. See the vertical evidence; do not close performance acceptance from the local result. [Scope and evidence](../docs/local-spicygov-slice.md).
