---
id: dv-k2k4
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-16
parent: dv-lgiy
tags: [viewer, portal-content, phase-2, pcr-16]
---
# Label related datasets and queries by purpose, inputs and result unit

Requirements: PCR-16 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Publisher relationships and viewer queries. Delivery phase: phase-2.

Current baseline: Related data, matching rules, explicit bindings and the Commerce saved-result title already exist. Recent relationship fixes preserve disclosed assessments.

Implementation scope:
- Explain why each link is useful and whether it opens a definition, historical coverage, another measure, source material or matching records.
- Put question, expected result unit, required inputs and meaningful parameter labels before SQL details.
- Retain explicit version/release choices and exact ordered keys, null policies and matching assessment.

Example: The World Bank links rural and urban measures; Earth Engine links cloud-detection data for a stated use. Those links help navigation without establishing a join. Our Commerce baseline already names its query “Read the saved daily revenue result.” The additional requirement is a consistently purpose-labelled route with the result unit, required choices, and action scope visible for every supported recipe and connection. [World Bank related indicators](https://data.worldbank.org/indicator/EG.ELC.ACCS.ZS) · [Earth Engine related data](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)

## Design

Relevant implementation or evidence starting points:
- [src/components/Connections.tsx](../viewer/src/components/Connections.tsx)
- [src/lib/choice-labels.ts](../viewer/src/lib/choice-labels.ts)
- [tests/unit/copy-relationships.test.ts](../viewer/tests/unit/copy-relationships.test.ts)
- [tests/browser/choice-labels.spec.ts](../viewer/tests/browser/choice-labels.spec.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- A visitor distinguishes browsing, a declared relationship and an executable query before activating it.
- A related indicator never implies a validated join; unknown/withheld assessments remain unchanged.
- Saved-result reads are not labelled as recalculation or rerunning checks.
- Required parameter labels/help are accessible, and the exact SQL/input identities remain inspectable.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/record-browser/report.md, outputs/implementation-20261107/gap-review/final-disposition.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
