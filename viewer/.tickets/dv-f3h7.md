---
id: dv-f3h7
status: closed
deps: [dv-9p5v]
links: []
created: 2026-11-07T18:17:11Z
type: feature
priority: 2
external-ref: PCR-03
parent: dv-lgiy
tags: [viewer, portal-content, phase-3, pcr-03]
---
# Add publisher-backed discovery facets with explicit unknown values

Requirements: PCR-03 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Publisher metadata and viewer discovery. Delivery phase: phase-3.

Current baseline: Access and source-capture filters already exist. Additional topic/publisher/place/period/format facets must answer observed visitor needs and use comparable admitted facts.

Implementation scope:
- Choose the smallest useful facet set using the source mapping and pilot findings.
- Define whether each facet applies to definitions, versions or resources and keep unknown values reachable.
- Implement accurate counts, combined filters and clear-filter recovery while preserving metadata-only discovery.

Example: Canada's portal offers organization, subject, format, and update-frequency filters. A proposed “CSV available” filter here must mean an actual disclosed comma-separated values file, not that a CSV export might be built later. [Canada search](https://search.open.canada.ca/opendata/)

## Design

Relevant implementation or evidence starting points:
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [src/server/catalog-store.ts](../src/server/catalog-store.ts)
- [src/domain/types.ts](../src/domain/types.ts)
- [tests/browser/copy-discovery.spec.ts](../tests/browser/copy-discovery.spec.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Every facet value maps to a reviewed supplied field and declared scope.
- Combined counts match the actual result set; unknown values and explicitly unclassified entries are discoverable.
- CSV availability refers to a real disclosed resource, and publisher/source-capture concepts stay distinct.
- No topic is guessed from an identifier; keyboard/mobile controls remain usable and search scope is accurately described.


## Notes

**2026-11-07T21:03:47Z**

Implementation and acceptance disposition, 2026-11-07: Structured facets and unknown buckets are implemented and verified. The first pilot dependency remains open; use its observations before accepting the expanded discovery routes. See outputs/implementation-20261107/implementation-report.md and study/README.md. No participant results or success percentages are claimed.

**2026-11-07T21:47:54Z**

User-directed acceptance method update (2026-11-07): the user asked for blind GPT-6.1 Sol light subagents as study personas. Seven fresh GPT-6.1 Sol low agents supplied simulated observations; this explicitly replaces the original real-participant dependency for this delivery. Human usability and human improvement remain unmeasured. Original criteria, study packet and raw observations are retained. See outputs/persona-study-20261107/report.md, scored-results.json and verification.json. All seven personas applied supplied facets, preserved unknown classifications and recovered from empty results. The repaired viewer explains when the retained open dataset is outside the result set. Focused browser checks verify unchanged selection and no data request.
