---
id: dv-h4ce
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-18
parent: dv-lgiy
tags: [viewer, portal-content, phase-2, pcr-18]
---
# Show resource-specific attribution, reuse terms and support links

Requirements: PCR-18 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Publisher rights/contact metadata and viewer. Delivery phase: phase-2.

Current baseline: Exact references already exist. Human attribution, terms and contact must come from supported publisher metadata rather than being inferred from public availability.

Implementation scope:
- Display publisher, original source, supplied citation, resource-specific licence/terms and a useful supplied support destination.
- Offer a copyable citation that retains the selected edition/version and original identifier alongside exact-reference downloads.
- Separate data, portal-copy and derived-view rights and make missing terms/contact explicit.

Example: GBIF supplies a dataset citation identifier; AWS supplies maintainer and contact information; Our World in Data distinguishes original-provider attribution from its own work. **Proposed missing state:** “Reuse terms not supplied for this resource.” [GBIF citation](https://www.gbif.org/dataset/4fa7b334-ce0d-4e88-aaae-2e0c138d049e) · [AWS maintainer](https://registry.opendata.aws/noaa-ghcn/) · [OWID attribution](https://ourworldindata.org/grapher/life-expectancy)

## Design

Relevant implementation or evidence starting points:
- [src/components/MetadataPanels.tsx](../src/components/MetadataPanels.tsx)
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [src/components/DataPanel.tsx](../src/components/DataPanel.tsx)
- [src/domain/types.ts](../src/domain/types.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- A visitor can identify whom to credit and which supplied route handles data questions.
- A portal licence never overrides resource-specific terms; public access does not become unrestricted-reuse permission.
- Copied citations preserve supplied identifiers and selection; no DOI, licence, person or contact is invented.
- Opening/copying support information does not send a message or imply one was sent.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/context/handoff.md, outputs/implementation-20261107/browser-review/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
