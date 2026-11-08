---
id: dv-bvgl
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-12
parent: dv-lgiy
tags: [viewer, portal-content, phase-2, pcr-12]
---
# Describe each file, table and service in the resource chooser

Requirements: PCR-12 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Viewer resources and publisher metadata. Delivery phase: phase-2.

Current baseline: The viewer already supports exact representation choice. The addition explains purpose, format, scope and destination for each admitted resource.

Implementation scope:
- Show readable resource purpose/format and supported size, period, update date and terms at resource scope.
- Differentiate data, documentation, metadata and notification services.
- Preserve exact representation identity and availability rather than copying broad collection descriptions.

Example: Canada's pollutant record distinguishes releases, transfers, comments, and locations. AWS distinguishes a storage bucket from a notification service. **Proposed copy:** “Facility locations — geographic file” and “Reporting comments — CSV,” only where those meanings and formats are supplied. [Canada resources](https://open.canada.ca/data/en/dataset/40e01423-7728-429c-ac9d-2954385ccdfb?wbdisable=true) · [AWS resource types](https://registry.opendata.aws/noaa-ghcn/)

## Design

Relevant implementation or evidence starting points:
- [src/components/DataPanel.tsx](../src/components/DataPanel.tsx)
- [src/components/MetadataPanels.tsx](../src/components/MetadataPanels.tsx)
- [src/server/access.ts](../src/server/access.ts)
- [src/domain/types.ts](../src/domain/types.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Every offered resource names what it opens; unknown size or scope stays unknown.
- A file-specific period and licence remain distinct from those of the collection.
- A notification endpoint is never presented as a record preview or data table.
- Selection retains exact version/resource identity and does not trigger an automatic read.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/resources/integration.md, outputs/implementation-20261107/record-browser/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
