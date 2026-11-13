---
id: ddk-citj
status: open
deps: []
links: [ddk-arnm, ddk-zxlb]
created: 2026-11-13T19:44:54Z
type: task
priority: 1
tags: [ddk, greenfield, lessons-review]
---
# Serve configured products through shared discovery, bounded queries and evidence access

Owner role: DDK catalog/serving adapter owner with DocSpec query/read owners.

User outcome: A product exposes usable HTTP, MCP and viewer access without table-specific server branches.

F2: build the smallest shared consumer surface required by the selected fresh applications. Consolidate CatalogInspector and MCP discovery work from ss-alp4 here. Decide the required bounded ad-hoc SQL and named-query behavior from user questions; named queries do not silently substitute for an explicitly required ad-hoc capability. Keep DDK core offline and native execution in DocSpec.

Sources: [F2](/Users/mikewolfd/Work/artifacts/ddk-lessons-review-2026-11-13/REVIEW.md#f2--blocker-generic-catalog-and-query-serving-is-incomplete-for-the-replacement), [former inspector ticket](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-alp4.md).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- Registration by configuration supplies dataset/relationship inspection, required queries, exact selected-release identities and allowed evidence access.
- Exercise real remote published representations with explicit disclosure and byte/time/row/concurrency limits; local-only owner support is insufficient.
- Catalog inspection verifies existing lock/report/companion artifacts, preserves exact numeric/nested values and distinguishes unavailable, refused, empty and truncated results.
- Adding a supported dataset requires definitions and configuration rather than server branches; tests cover changed companions, stale selections and unavailable unrelated owners.
- Domain citation interpretation remains in declared relationships or domain SQL. Optional agent.md/WebMCP helpers stay deferred until a consumer needs them.
