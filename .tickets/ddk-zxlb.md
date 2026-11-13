---
id: ddk-zxlb
status: open
deps: []
links: []
created: 2026-11-13T19:03:50Z
type: task
priority: 1
tags: [ddk, backlog, 2026-11-13]
---
# Measure catalog and quality workloads at useful scale within explicit limits

Owner role: DDK performance owner, with DocSpec and application owners for native workloads.

User outcome: Users can choose safe catalog and dataset sizes with predictable time, memory and disk costs.

Reconcile the original performance targets with ADR-015, preserving frozen impact behavior. Measure a representative 1,000-artifact/10,000-relationship library and required actual quality paths. Keep the five-second/256-MiB cold target explicitly proposed until measured; extend no frozen capability through a benchmark task.

Sources: [Performance and resource acceptance](../docs/implementation-plan.md#8-performance-and-resource-acceptance).

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Record input identities, machine/runtime tuple, wall time, parsing/schema/reference phases, aggregate process memory, scratch and total retained/output demand.
- Verify parse-once behavior by byte identity, unchanged-input reuse, bounded logs, cancellation, oversized graphs and per-document limits.
- Increase native quality population at fixed limits; include a last-batch violation, complete row/check coverage and refusal of truncated or wrong-candidate evidence.
- Report measured failures and supported limits; revise proposed targets with evidence instead of counting small-fixture tests as scale acceptance.
- Retain the controls and results outside the repository; reuse unchanged source and immutable inputs.
