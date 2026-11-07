---
id: dv-khs1
status: closed
deps: [dv-g9m0]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-15:reuse
parent: dv-lgiy
tags: [viewer, portal-content, phase-2, pcr-15]
---
# Link matching metadata companions and accurate reuse instructions

Requirements: PCR-15 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Publisher access documentation and viewer reuse. Delivery phase: phase-2.

Current baseline: Catalog companions and registered paths exist. Metadata packages and spreadsheet/programming instructions are additional conditional content, not an existing public data API.

Implementation scope:
- Offer a supplied README/metadata companion beside the resource it actually describes, with a clear purpose.
- Add a short applicable spreadsheet or programming example for an actually supported download/API route; identify external destinations.
- Document version/selection, authentication and default row limits. Treat a new ZIP/package, exporter or endpoint as separately qualified capability work.

Example: Our World in Data separates complete chart data from displayed countries and years and supplies metadata and reuse instructions. Our baseline already says “Download this page (JSON)” and explains that hidden returned fields are included. **Proposed addition, for an actual matching result:** “25 records · region = North · selected version: [version label].” Keep the separate dataset-reference download explicit that it contains metadata rather than records. [OWID download choices](https://ourworldindata.org/grapher/life-expectancy)

## Design

Relevant implementation or evidence starting points:
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [src/components/DataPanel.tsx](../src/components/DataPanel.tsx)
- [src/components/Connections.tsx](../src/components/Connections.tsx)
- [src/pages/api/companion.ts](../src/pages/api/companion.ts)
- [docs/adapters.md](../docs/adapters.md)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Each companion resolves through an admitted existing path and describes the same resource/version.
- Each offered example is checked against its actual supported route and yields the documented bounded scope.
- Unavailable companions or unimplemented APIs have honest missing states, with no placeholder download/action.
- Code examples disclose limits and preserve exact-value expectations; data-query validation uses an explicitly qualified test route, not an unsolicited native run.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/gap-review/api-reuse.json, outputs/implementation-20261107/record-browser/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
