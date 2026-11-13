---
id: ddk-pi9u
status: open
deps: []
links: [ddk-arnm, ddk-zxlb, ddk-citj, ddk-v2x8]
created: 2026-11-13T19:44:54Z
type: task
priority: 1
tags: [ddk, greenfield, lessons-review]
---
# Follow a record to related records and exact retained originals

Owner role: DDK viewer/serving owner for configured row actions; source mapping and domain SQL owners for lookup semantics and source locators.

User outcome: A user can move from an answer or selected row to the relevant related records and original evidence without hand-copying keys.

Keep existing native references, artifact digests, relationships, parameterized recipes and publisher locators. Add a shared configured row action that fills an approved recipe from the current record's complete identity and selected release. Domain SQL owns actual matching; shared concepts alone do not establish record matches. This absorbs ordinary navigation into the existing lineage task, without reviving the deferred synonym/facet system or prescribing a new citation format.

Sources: [Record actions](/Users/mikewolfd/Work/artifacts/ddk-user-value-review-2026-11-13/REPORT.md#5-carry-the-current-record-into-the-next-useful-action), [one-vote proof](/Users/mikewolfd/Work/artifacts/one-vote-proof-20261113/PROOF.json), [existing relationship links](../viewer/src/components/Connections.tsx). Earlier ss-3u5d and ss-abun requests remain merged here; their original evidence stays retained.

## Acceptance Criteria

- From an actual HTTP/MCP/viewer answer, follow the selected release and contributing record IDs to normalized rows and the exact retained original plus supported page, section or other locator, without undocumented lookup.
- Configure and exercise comment-to-document, bill-printing-to-section and record-to-original actions for the selected products. Populate approved recipe parameters using complete typed compound keys and exact release context; preserve large integers and exact values. A selected category value carries required scope, such as Congress with session.
- Verify singular, multiple, missing, unresolved and interrupted target outcomes. Missing key/context or changed release must not broaden a query or silently choose a target. Reuse parameter binding and disclosure checks rather than constructing SQL from row text.
- For House roll 99 of Congress 119/session 2 and member P000197, follow recorded pointers to the retained Clerk original and independently confirm No; preserve original capture identity and ambiguity.
- For an inferred cross-source relationship, expose contributing records and the matching rule or explicit decision. A source hash or shared field concept alone does not explain the join.
- Changed content, missing originals and withheld evidence produce explicit refusal or gaps; scoped keys preserve publisher-native IDs. Exact quoted-span replay is a separately selected need: any such claim must bind the rendition/content and supported locator semantics, since PDF text offsets are not PDF-byte offsets.
- Verify the fresh consumer directly, including key/parameter binding and stale-context negatives. Historical proof and existing artifact pins receive credit only for their demonstrated scope.

Delivery order: source identity and locator mapping accompany the first real journey; shared row actions follow the working table/query path in [ddk-citj](ddk-citj.md). This task stays ready for that independent work. [Work backlog](../docs/work-backlog.md#greenfield-delivery).

## November 13 bounded vertical progress

The local SpicyGov cohort now follows each selected comment through exact rule/docket keys and original JSON, preserving source version, digest and receipt pointer. Independent review added changed-version, changed-receipt and changed-inventory refusals. Generic configured row actions and the other selected application journeys remain open. [Scope and evidence](../docs/local-spicygov-slice.md).

## Generic viewer handoff

Retained original inspection moved into the generic viewer and admits only catalog-pinned URI/digest pairs under permitted roots. Source versions and receipt locators remain visible. Catalog-wide originals and selected-version lineage remain distinct; raw observations are not yet linked to normalized versions. Configured row actions and complete source-to-derived lineage remain open.
