---
id: dv-6ana
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-06
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-06]
---
# Put human field meaning first while preserving native identity and values

Requirements: PCR-06 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Viewer field dictionary. Delivery phase: phase-1.

Current baseline: The nested field tree already preserves native names, businessName, descriptions, types, paths and distinct empty values. Native names currently lead the presentation.

Implementation scope:
- Promote supplied human labels and meanings while keeping exact native names nearby and copyable.
- Expose supported units, scale, codes, identifier scope and missing-value guidance without deriving them from names.
- Preserve nesting, occurrence order, technical details and exact-number rendering.

Example: NYC pairs “Problem (formerly Complaint Type)” with `complaint_type`. Earth Engine's `B4` documentation supplies a meaning, scale, and pixel size. **Proposed copy for an unresolved size field:** “File size. The publisher documentation reviewed does not state the unit.” This explains the supported meaning while retaining the specific gap. [NYC field definitions](https://data.cityofnewyork.us/d/erm2-nwe9/about_data) · [Earth Engine field table](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)

## Design

Relevant implementation or evidence starting points:
- [src/components/Primitives.tsx](../viewer/src/components/Primitives.tsx)
- [src/domain/exact.ts](../viewer/src/domain/exact.ts)
- [src/lib/display.ts](../viewer/src/lib/display.ts)
- [tests/browser/copy-records.spec.ts](../viewer/tests/browser/copy-records.spec.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Nontechnical readers can explain the selected value while engineers recover its exact nested path and native name.
- Unknown units and incomplete vocabularies remain explicit; examples never imply an exhaustive code list.
- Missing, null, empty text and empty lists remain different; repeated nested occurrences remain independently addressable.
- Dictionary labels, expanded details and copy controls work by keyboard and on mobile.


## Notes

**2026-11-07T20:17:38Z**

Preparing a contained field component against existing supported CatalogField inputs in parallel with metadata mapping. Root will integrate and close only after the prerequisite and verification are satisfied.

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/fields/handoff.md, outputs/implementation-20261107/browser-review/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
