---
id: ddk-citj
status: open
deps: []
links: [ddk-arnm, ddk-zxlb, ddk-eu0k, ddk-p3mc, ddk-251s, ddk-pi9u]
created: 2026-11-13T19:44:54Z
type: task
priority: 0
tags: [ddk, greenfield, lessons-review]
---
# Browse and query complete public tables through shared serving

Owner role: DDK serving/viewer owner, with the DocSpec owner for native table binding, selective reading and execution.

User outcome: A researcher can find a record, page filtered results and ask a new cross-table question across the selected public release.

Extend the shared HTTP/MCP/viewer path over maintained DocSpec readers. The current viewer owner accepts local catalogs, rejects generic native-preview filters and restricts each recipe input to one Parquet file; the native recipe request also binds one path and digest per input. Both sides need a coherent whole-table binding. Multi-file previews and existing remote/key-reader primitives receive credit for their actual scope. Keep DDK core offline and native execution in DocSpec.

Delivery order: work alongside cold-read fixes and the first real application journey, before optional metadata extensions. Use exact retained/published inputs while acquisition and shared publication develop. Final acceptance requires real remote selected data and complete membership.

Sources: [User-value recommendations](/Users/mikewolfd/Work/artifacts/ddk-user-value-review-2026-11-13/REPORT.md#1-make-public-data-usable-before-adding-more-metadata), [viewer binding](../viewer/src/server/docspec-owner.ts), [native binding](/Users/mikewolfd/Work/spicy-stack/docspec-rs/src/owner_worker.rs), [disclosure boundary](../docs/catalog-api.md).

## Acceptance Criteria

- Register products by configuration with dataset/schema/relationship discovery, prepared queries, evidence access and exact selected-release identities. Adding a supported dataset needs definitions and configuration rather than table-specific server branches.
- Bind a logical table's complete selected partition/member set in the viewer and native worker. Query across partitions without requiring a combined local file; missing, duplicate or mismatched required members cannot yield a complete-success claim.
- On actual remote data, exercise exact compound-key lookup, typed filters, column selection, useful ordering and paging. Bind continuations to exact data, filters, ordering and disclosure; verify ties, page boundaries, changed requests and changed selections. Distinguish exhausted-empty, ambiguous, incomplete and interrupted lookups.
- Offer bounded read-only analyst-authored SELECT through shared access alongside prepared questions. Verify one unprepared cross-table question with independent expected results and exact consumed versions. Enforce disclosed tables/columns in providers before planning, and byte/time/memory/scratch/concurrency limits during execution; a result-row limit alone does not bound a join or aggregate. A browser SQL editor is a separate optional convenience.
- Preserve exact numeric/nested values, visible truncation and immutable anonymous downloads for disclosed public data. Shared service and downloads identify the same selected members; private columns or references remain withheld.
- Verify existing lock/report/companion artifacts and retain unavailable, refused, empty and truncated outcomes. Cover changed companions, stale selections, missing members, cancellation and an unrelated unavailable owner in maintained native/consumer tests with zero required skips.
- Meet the workloads and numerical targets in [ddk-zxlb](ddk-zxlb.md), including cold/warm point lookup, filtered paging and cross-partition analysis. Record actual requests and bytes read, not only returned rows.
- [ddk-251s](ddk-251s.md) owns source-gap and availability views; [ddk-pi9u](ddk-pi9u.md) owns row-context navigation. Reuse their shared access path. Optional agent.md/WebMCP helpers remain deferred.

Priority and greenfield scope: [work backlog](../docs/work-backlog.md#greenfield-delivery).

## November 13 bounded vertical progress

Implemented the bounded local flat-file/directory path in `ddk.catalog_query.execute_catalog_sql` and exercised it through a real local SpicyGov browser. Exact member binding, joins, filtering/order/paging, valid-empty and changed-member refusals are covered. Nested directories now refuse explicitly after an independent case showed the retained native reader omitting nested rows. Complete nested/native/remote/public HTTP/MCP/viewer behavior and the performance criteria remain open. [Scope and evidence](../docs/local-spicygov-slice.md).
