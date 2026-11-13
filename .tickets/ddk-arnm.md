---
id: ddk-arnm
status: open
deps: []
links: []
created: 2026-11-13T19:03:49Z
type: task
priority: 1
tags: [ddk, backlog, 2026-11-13]
---
# Reconcile current application evidence before extending the shared runtime

Owner role: DDK integration coordinator, with the SpicyRegs and congressional-tech owners.

User outcome: Application work starts from the current implementations and exact retained evidence.

Reconcile the shared runtime plan and both application request inventories with current source, package, native binary and consumer identities. Separate implemented code, demonstrated mechanisms, complete application acceptance and publication. Retain historical refusals and unknown results. Track application implementation in its owning repository; this ticket owns the cross-project acceptance matrix.

Sources: [Shared owners and work](../docs/replacement-runtime-plan.md#owners-and-shared-work). WP-09A, WP-11, WP-12 and WP-13.

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Record each required source, output, rule and consumer, its owning repository, current identity, evidence reference and remaining gap.
- Credit identity-matched completed work, and mark stale or unavailable evidence explicitly instead of reopening completed mechanisms.
- Classify each residual gap as implementation, integration, execution evidence, resource admission or publisher decision; link one owner ticket for each.
- Supply the matrix to the application, publication and release tickets; do not claim full acceptance from metadata or fixture passes.
