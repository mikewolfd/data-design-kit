---
id: ddk-i3g8
status: open
deps: []
links: []
created: 2026-11-13T19:03:50Z
type: feature
priority: 3
tags: [ddk, backlog, 2026-11-13]
---
# Define comparable dataset and product statuses with optional enforcement

Owner role: DDK definitions and policy owner.

User outcome: Users can interpret proposed, draft, active, deprecated and retired consistently.

Implement WP-15 item 5 with documented meanings and an optional pinned-set policy. Preserve custom publisher values and source occurrences. Status must not establish availability, current selection, quality acceptance or publication.

Sources: [WP-15 item 5](../docs/implementation-plan.md#wp-15--layered-data-map-extensions-specified-not-implemented).

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Define each pinned value and preserve it consistently for ODCS datasets and ODPS products.
- Without enforcement, custom and absent values remain preserved and distinguishable; with enforcement, unsupported values yield the documented policy result.
- Independent cases demonstrate that active status alone grants no read/query/selection or qualification capability.
- Update the normative definitions/policy shape, examples and traceability without rewriting publisher facts.
## Reconciliation

November 13, 2026: Greenfield reprioritization: working data paths and meaningful quality/coverage come first. This task preserves its ID and acceptance scope; it is not an application-build prerequisite.
