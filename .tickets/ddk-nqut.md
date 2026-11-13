---
id: ddk-nqut
status: open
deps: []
links: []
created: 2026-11-13T19:03:50Z
type: feature
priority: 2
tags: [ddk, backlog, 2026-11-13]
---
# Qualify designed data maps without claiming materialized or checked data

Owner role: DDK catalog owner.

User outcome: Authors can pass a definitions-only check before data has been built.

Implement WP-15 item 6 as an explicit qualification profile covering core and catalog definitions. Preserve existing runtime-backed catalog qualification and uncertainty. Add the profile to the maintained specification, schemas/registries and conformance inventory only as needed.

Sources: [WP-15 item 6](../docs/implementation-plan.md#wp-15--layered-data-map-extensions-specified-not-implemented).

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- A valid unbuilt layered map passes the explicit definitions-only requirement.
- Malformed definitions, references, policies and declared relationships still fail their applicable checks.
- Missing version-bound execution/quality evidence stays unknown or not_run under existing qualification; the new profile creates no data availability, acceptance or publication claim.
- Independent positive/negative examples, installed CLI/API checks and profile documentation distinguish design validity from data qualification.
## Reconciliation

November 13, 2026: Greenfield reprioritization: working data paths and meaningful quality/coverage come first. This task preserves its ID and acceptance scope; it is not an application-build prerequisite.
