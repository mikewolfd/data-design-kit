---
id: dv-1zol
status: closed
deps: []
links: []
created: 2026-11-07T18:17:10Z
type: task
priority: 1
external-ref: PCR-20:metadata
parent: dv-lgiy
tags: [viewer, portal-content, foundation, pcr-20]
---
# Map product content requirements to supported publisher metadata

Requirements: PCR-20 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Publisher metadata and viewer integration. Delivery phase: foundation.

Current baseline: The standard catalog owns facts. The existing content guide names supported title, rowMeaning, description, businessName, scope and reason fields. New topics, former names, dates, licences and guide content need an explicit source mapping.

Implementation scope:
- Inventory each datum needed by PCR-01 through PCR-20 against the admitted schema and publisher source; identify its object scope, disclosure rules and exact source/version.
- Record supported, absent, unknown and unsupported-schema cases separately, with a concrete example for each relevant publisher.
- Define the smallest supported path for new facts or companion content. Record owner changes needed for gaps; keep external reference checkouts read-only and avoid a viewer-only metadata authority.

Example: A recorded retrieval timestamp can support “Retrieved on”; it cannot support “Data last updated.” A missing former-name field is a schema/owner gap, not permission to add a hard-coded synonym map.

## Design

Relevant implementation or evidence starting points:
- [docs/content-guide.md](../viewer/docs/content-guide.md)
- [src/domain/types.ts](../viewer/src/domain/types.ts)
- [src/server/catalog-store.ts](../viewer/src/server/catalog-store.ts)
- `outputs/public-catalog-research-20261107/product-requirements.md`

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Validate mapping completeness, source/schema references, disclosure, missing-state examples and local links. No runtime or application test run is needed for documentation-only work.

## Acceptance Criteria

- A versioned mapping covers every factual input used by the 20 content requirements, including dates, alternate names, guide links, rights and resource-specific limits.
- Each mapping cites an exact native field or supported companion route; gaps have a named owner role and precise question.
- Closed-schema examples show scope/reason for checks without inventing rule.title.
- Publisher integration and viewer tasks can consume the mapping without guessing units, completeness, authorship or canonical selection.


## Notes

**2026-11-07T21:03:46Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/metadata/metadata-map.md, outputs/implementation-20261107/metadata/metadata-map.json. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
