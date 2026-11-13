---
id: dv-dnke
status: open
deps: []
links: []
created: 2026-11-13T15:23:34Z
type: task
priority: 3
assignee: mikewolfd
tags: [owner, review]
---
# Default owner query capability from the resolved docspec binary

SDK4 final review P3-1: createDocSpecCatalogOwner computes enableQuery = config.enableQuery ?? Boolean(config.docspecBinary), so callers relying on DDK_VIEWER_DOCSPEC_BINARY or the default binary get no owner.query even though the worker starts. Use the resolved binary.

## Acceptance Criteria

A caller that omits docspecBinary and enableQuery gets owner.query; unit test covers it.

