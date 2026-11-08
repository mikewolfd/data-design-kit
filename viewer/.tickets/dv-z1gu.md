---
id: dv-z1gu
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-01
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-01]
---
# Show purpose, distinguishing scope and access in dataset results

Requirements: PCR-01 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Viewer discovery. Delivery phase: phase-1.

Current baseline: Search already indexes titles, descriptions, row meaning and identifiers. The list currently emphasizes title plus role/revision, and access filtering already uses registered capability.

Implementation scope:
- Add a concise supplied description or record meaning, distinguishing scope and compact access label to each result.
- Keep exact role/revision secondary and preserve independent same-title entries. Link a supplied relevant guide/example by its task, identifying guidance separately from data.
- Handle absent descriptions and long text without generating facts or loading records.

Example: NYC's `311` search distinguishes service requests, call-center inquiries, and agency response commitments. Our result cards should make equally consequential distinctions before a visitor opens a dataset. [NYC search](https://data.cityofnewyork.us/browse?q=311)

## Design

Relevant implementation or evidence starting points:
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [src/lib/content.ts](../src/lib/content.ts)
- [src/styles/workspace.css](../src/styles/workspace.css)
- [tests/browser/copy-discovery.spec.ts](../tests/browser/copy-discovery.spec.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Three similar results are distinguishable from visible supplied descriptions/scope before opening the dataset.
- Each access label agrees with the current capability-aware filter for connected, metadata-only and unknown cases.
- Result navigation, load-more, keyboard focus and 320/390px layouts remain usable; metadata discovery sends no record/query requests.
- A supplied guide link has a purpose and content-kind label; no unsupported guide is invented.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/browser-review/report.md, outputs/implementation-20261107/record-browser/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
