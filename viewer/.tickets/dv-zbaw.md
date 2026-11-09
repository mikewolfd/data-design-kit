---
id: dv-zbaw
status: closed
deps: [dv-1zol, dv-5181, dv-2wq2]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-09
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-09]
---
# Place interpretation cautions beside the affected field, result or action

Requirements: PCR-09 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Publisher interpretation and viewer context. Delivery phase: phase-1.

Current baseline: Coverage notes already exist. The addition places concise relevant cautions at the decision point while retaining the complete explanation.

Implementation scope:
- Map each supplied caution or unresolved question to its affected dataset, field, resource or query.
- Show the likely interpretation mistake beside that action/result; retain the full source qualification in expandable detail.
- Separate established limits from unresolved questions, avoiding blanket warning text on unrelated data.

Example: Canada's pollutant guidance explains how transfers and releases can count the same quantity twice. **Proposed copy beside an applicable query:** “Transfers and releases may count the same material at two facilities. Review the aggregation guidance before adding them.” [Interpretation guidance](https://www.canada.ca/en/environment-climate-change/services/national-pollutant-release-inventory/using-interpreting-data.html)

## Design

Relevant implementation or evidence starting points:
- [src/components/MetadataPanels.tsx](../src/components/MetadataPanels.tsx)
- [src/components/DataPanel.tsx](../src/components/DataPanel.tsx)
- [src/components/Connections.tsx](../src/components/Connections.tsx)
- [src/components/Primitives.tsx](../src/components/Primitives.tsx)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- A double-counting caution is visible beside its affected total/query, including on mobile.
- An unknown timezone or unit stays a question instead of becoming a factual rule.
- Cautions retain their subject and source and do not spread to unrelated records or resources.
- Action placement preserves accessible labels, keyboard order and existing controls.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/context/handoff.md, outputs/implementation-20261107/browser-review/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
