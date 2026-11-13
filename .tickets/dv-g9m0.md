---
id: dv-g9m0
status: closed
deps: [dv-ivnl]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-15:exports
parent: dv-lgiy
tags: [viewer, portal-content, phase-2, pcr-15]
---
# Show count, selection and exact identity before bounded exports

Requirements: PCR-15 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Viewer exports. Delivery phase: phase-2.

Current baseline: The page download already says Download this page (JSON), includes hidden returned fields and retains exact context. Reference and query-result downloads are distinct.

Implementation scope:
- Add the actual record count, active selection/filter, version label and row bound next to the relevant download.
- Keep metadata-only references, pages, query results and supplied full resources clearly distinct.
- Preserve exact numbers, nested occurrences and complete request identity in the artifact and supported size-failure recovery.

Example: Our World in Data separates complete chart data from displayed countries and years and supplies metadata and reuse instructions. Our baseline already says “Download this page (JSON)” and explains that hidden returned fields are included. **Proposed addition, for an actual matching result:** “25 records · region = North · selected version: [version label].” Keep the separate dataset-reference download explicit that it contains metadata rather than records. [OWID download choices](https://ourworldindata.org/grapher/life-expectancy)

## Design

Relevant implementation or evidence starting points:
- [src/components/DataPanel.tsx](../viewer/src/components/DataPanel.tsx)
- [src/components/Connections.tsx](../viewer/src/components/Connections.tsx)
- [src/components/Workspace.tsx](../viewer/src/components/Workspace.tsx)
- [src/domain/exact.ts](../viewer/src/domain/exact.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- A filtered 25-record page advertises its actual count/filter/version and exports the same returned scope.
- Hidden returned fields remain disclosed and preserved; metadata references never claim to contain data records.
- Large integers and repeated nested values survive export without rounding or flattening.
- No new CSV/full-dataset/API capability is advertised as part of this existing-export improvement.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/resources/integration.md, outputs/implementation-20261107/record-browser/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
