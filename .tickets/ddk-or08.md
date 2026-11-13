---
id: ddk-or08
status: open
deps: [ddk-c7v1]
links: []
created: 2026-11-13T19:03:50Z
type: task
priority: 1
tags: [ddk, backlog, 2026-11-13]
---
# Choose the public package destination and publish the qualified release

Owner role: Product/package release owner.

User outcome: Users can obtain a named, supported release through a maintained distribution channel.

Resolve public package/executable naming and the release destination, then use the owner-controlled publishing workflow. This is package distribution; each application publisher retains its separate activation authority.

Sources: [WP-11 release workflow](../docs/implementation-plan.md#wp-11--release-qualification-and-handoff) and [deferred naming decision](../docs/implementation-plan.md#10-decisions-intentionally-deferred).

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Record the selected destination, available package/executable names and release owner.
- Publish the exact qualified artifacts, inventories, notices, supported-profile manifest and installation guide through that owner workflow.
- Verify a clean consumer install from the published destination against the expected digests and supported commands.
- Keep package publication, application publication and hosted-service deployment as separate recorded outcomes.
