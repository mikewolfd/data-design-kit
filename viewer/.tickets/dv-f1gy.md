---
id: dv-f1gy
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-19
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-19]
---
# Explain recorded corrections and changes without inventing version authority

Requirements: PCR-19 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Publisher change records and viewer history. Delivery phase: phase-1.

Current baseline: History already presents recorded events, explicit selections and a separately bound definition-change report. The addition explains consequences of supplied changes.

Implementation scope:
- Summarize documented renames, corrections, coverage changes and compatibility issues in visitor terms.
- Distinguish source events, metadata revisions, data versions and publisher selection/acceptance records.
- Retain original timestamps and exact old/current references with explicit mismatch handling.

Example: NYC explains changed field labels; UK road-safety documentation distinguishes provisional figures, final figures, and revisions. **Proposed copy:** “This publisher note changes the field label; the original field identifier remains available.” State that identifiers are unchanged only when verified. [NYC changes](https://www.nyc.gov/opendata/news/all-news/311-Service-Requests-Updates) · [UK revisions](https://www.gov.uk/government/statistical-data-sets/road-safety-open-data)

## Design

Relevant implementation or evidence starting points:
- [src/components/MetadataPanels.tsx](../src/components/MetadataPanels.tsx)
- [src/components/ImpactPanel.tsx](../src/components/ImpactPanel.tsx)
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [tests/unit/copy-checks-history.test.ts](../tests/unit/copy-checks-history.test.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- An old exact link identifies its recorded copy or explains why that copy is unavailable; it never silently opens a different version.
- A newer timestamp or label never selects the canonical version.
- A fixed definition report does not claim to compare arbitrary selected data versions; zero/one-version states remain accurate.
- A rename preserves identifier continuity only when the recorded evidence establishes it.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/record-browser/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
