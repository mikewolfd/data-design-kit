---
id: dv-2wq2
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-07
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-07]
---
# Present population, period and geographic coverage at the correct scope

Requirements: PCR-07 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Viewer coverage and publisher metadata. Delivery phase: phase-1.

Current baseline: CoverageFacts already separates observed and expected counts and preserves unknown. The addition organizes inclusion/exclusion and collection/version/resource scope.

Implementation scope:
- Present supplied time, place, population, inclusion rules and exclusions as distinct facts.
- Bind each claim to its actual collection, version or resource instead of inheriting broad collection claims.
- Keep conflicting statements attributable and completeness unestablished when its expected population is missing.

Example: GBIF's indexed eBird description combines broad geographic coverage with uneven-sampling and detection limits. Canada's bulk-record description and a comments filename suggest different starting years; the interface should preserve the conflict for investigation, not silently choose one. [eBird description](https://www.gbif.org/dataset/4fa7b334-ce0d-4e88-aaae-2e0c138d049e) · [Canada resource record](https://open.canada.ca/data/en/dataset/40e01423-7728-429c-ac9d-2954385ccdfb?wbdisable=true)

## Design

Relevant implementation or evidence starting points:
- [src/components/MetadataPanels.tsx](../src/components/MetadataPanels.tsx)
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [src/domain/types.ts](../src/domain/types.ts)
- [tests/unit/copy-checks-history.test.ts](../tests/unit/copy-checks-history.test.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Worldwide extent with uneven sampling never renders as complete worldwide coverage.
- Observed date extrema do not become continuous or complete period coverage; missing expected totals remain unknown.
- A resource-specific period stays distinct from its collection period, and conflicting supplied periods remain traceable.
- Counts retain their original unit and precision.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/context/handoff.md, outputs/implementation-20261107/browser-review/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
