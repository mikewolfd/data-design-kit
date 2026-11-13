---
id: ddk-x3uy
status: open
deps: [ddk-z8mp]
links: []
created: 2026-11-13T19:03:49Z
type: task
priority: 1
tags: [ddk, backlog, 2026-11-13]
---
# Qualify SpicyRegs publisher activation and recovery without replacing newer releases

Owner role: SpicyRegs publisher owner, with DocSpec lifecycle and DDK evidence owners.

User outcome: Regulatory updates remain readable and recoverable through interrupted publication.

Use the existing publisher authority with accepted native intent and a frozen release inventory. Reuse already-qualified local intent mechanisms; close actual publisher and consumer acceptance. Execute external activation through the publisher-owned release workflow.

Sources: [Publication and readback obligations](../docs/replacement-runtime-plan.md#independent-acceptance-examples). WP-11, WP-12 and WP-13.

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Bind the accepted candidate, exact release members, destination, expected publisher token and original attempt before effects.
- Exercise failure before/after activation, lost acknowledgement and an intervening successor publication.
- Reconcile the original attempt from durable evidence; unresolved history stays unknown and an old attempt never overwrites a successor.
- Verify actual consumer readback, prior-release readability and any required restore fence; preserve frozen catalog bytes and separate publication observations.
