---
id: dv-dnke
status: open
deps: []
links: [ddk-eu0k, ddk-p3mc]
created: 2026-11-13T15:23:34Z
type: bug
priority: 1
assignee: mikewolfd
tags: [viewer, owner, review, regression]
---
# Default owner query capability from the resolved docspec binary

SDK4 final review P3-1: createDocSpecCatalogOwner computes enableQuery = config.enableQuery ?? Boolean(config.docspecBinary), so callers relying on DDK_VIEWER_DOCSPEC_BINARY or the default binary get no owner.query even though the worker starts. Use the resolved binary.

Owner role: viewer native-adapter owner. User outcome: the default supported configuration exposes working queries. Keep native startup validation and explicit capability choices intact. Priority 1 in the [consolidated backlog](../docs/work-backlog.md).

Use the resolved, startup-verified runtime state already owned by [DocSpecCatalogOwner](../viewer/src/server/docspec-owner.ts). Preserve the historical review finding above; this ticket does not grant query support to an unverified or disabled adapter.

## Acceptance Criteria

- A caller that omits `docspecBinary` and `enableQuery` gets `owner.query` after successful startup with the default executable.
- Environment-configured and explicitly configured executables follow the same capability rule; `enableQuery: false` still disables queries.
- Missing or digest-mismatched executables retain their existing startup refusals.
- Maintained unit/native consumer tests verify capability disclosure, actual query execution and exact consumed bindings with the pinned executable. Supply prerequisites and run the required tests without skips.

## Notes

November 13, 2026: retained the existing ID, assignee and original finding; classified it as a bug and raised delivery priority to P1. Implementation remains open.
## Reconciliation

November 13, 2026: Greenfield reprioritization: working data paths and meaningful quality/coverage come first. This task preserves its ID and acceptance scope; it is not an application-build prerequisite.
