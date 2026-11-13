---
id: ddk-c7v1
status: open
deps: [ddk-b2tk]
links: []
created: 2026-11-13T19:03:50Z
type: task
priority: 2
tags: [ddk, backlog, 2026-11-13]
---
# Complete the current portable handoff, inventories and operator guides

Owner role: DDK release and documentation owners.

User outcome: A user can install and operate the supported stack without this developer workspace.

Package the qualified current tuple using maintained external build controls. Reconcile installation, native-owner configuration and evidence-reading instructions with the current Rust reader and retained-replay behavior. Keep generated archives, environments and build scripts outside this deliverables repository.

Sources: [WP-11](../docs/implementation-plan.md#wp-11--release-qualification-and-handoff), [viewer adapter guide](../viewer/docs/adapters.md), [historical portable evidence](../docs/local-release-integrated-3.md#portable-package).

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Verify archive member digests, modes, fresh installation, relocation and a real connected workflow with original workspace access unavailable.
- Supply exact dependency locks, upstream provenance, notices and validated software bills of materials, including the missing SQL-only feature inventory.
- Test installation and invocation instructions against the actual current package/runtime; update README, release and Commerce/Congress owner guides.
- Publish a capability/limitation manifest and evidence index that distinguish this portable result from SDK3 and earlier native tuples.
## Reconciliation

November 13, 2026: Greenfield reprioritization: working data paths and meaningful quality/coverage come first. This task preserves its ID and acceptance scope; it is not an application-build prerequisite.
