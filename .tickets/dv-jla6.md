---
id: dv-jla6
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-08
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-08]
---
# Label observation, update, retrieval and expected-update dates separately

Requirements: PCR-08 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Publisher date semantics and viewer presentation. Delivery phase: phase-1.

Current baseline: History has readable timestamps with originals, but the new opening facts need explicit date semantics at the relevant object scope.

Implementation scope:
- Use the metadata mapping to distinguish observation period, source publication, data update, metadata update, retrieval and next expected update.
- Display only applicable supported dates with original values/timezone details available.
- Treat schedule as an expectation and retain unknowns instead of synthesizing a freshness score.

Example: NYC separates data and metadata updates; Our World in Data shows the period covered and the next expected update. **Illustrative copy:** “Records cover 2020–2024 · Metadata revised November 7 · Next data update not supplied.” [NYC dataset](https://data.cityofnewyork.us/d/erm2-nwe9/about_data) · [OWID data page](https://ourworldindata.org/grapher/life-expectancy)

## Design

Relevant implementation or evidence starting points:
- [src/components/MetadataPanels.tsx](../src/components/MetadataPanels.tsx)
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [src/lib/display.ts](../src/lib/display.ts)
- [src/domain/types.ts](../src/domain/types.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- A metadata-only change does not alter the shown data-update date.
- A daily schedule without evidence of a recent refresh never produces “up to date.”
- Missing dates identify which fact is absent; ambiguous timezone/calendar meaning remains unknown.
- Each rendered date can be traced to the exact admitted object and original value.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/context/handoff.md, outputs/implementation-20261107/resource-dates-browser.json. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
