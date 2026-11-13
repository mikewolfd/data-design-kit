---
id: ddk-p3mc
status: open
deps: []
links: [ddk-arnm, ddk-zxlb]
created: 2026-11-13T19:44:54Z
type: bug
priority: 1
tags: [ddk, greenfield, lessons-review]
---
# Keep independent catalogs usable when a configured local owner is unavailable

Owner role: DDK viewer registration owner.

User outcome: One unavailable dataset owner does not disable unrelated discovery and queries.

F4 is reproduced in local owner-enabled startup. Resolve owners on demand or retain per-owner availability through the maintained registry. Preserve configuration validation and accurate unavailable outcomes; add no fallback data or parallel registry.

Sources: [Reproduction](/Users/mikewolfd/Work/artifacts/ddk-lessons-response-20261113/registry-result.json), [registry](../viewer/src/server/registry.ts).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- Independent catalog metadata and a working query owner remain usable when a different owner has a missing executable, a changed catalog or a startup failure.
- The affected catalog exposes an actionable unavailable/refused result without claiming successful empty data.
- Malformed configuration, duplicate identities and invalid authority declarations still fail their applicable configuration checks.
- Run maintained registry/consumer regression tests, including local and public modes, with prerequisites supplied and zero skips.
