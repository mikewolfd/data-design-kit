---
id: dv-ffmm
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-10
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-10]
---
# Explain source, processing and confirmed authorship in plain language

Requirements: PCR-10 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Publisher provenance and viewer evidence. Delivery phase: phase-1.

Current baseline: Recorded sources, runs, evidence and original definitions are already inspectable. This task adds a readable account without changing authority or disclosure.

Implementation scope:
- Show the supplied producer/source edition and the documented transformations that affect interpretation.
- Distinguish source values, standardization, calculation and inference only when the record supports it.
- Keep exact inputs and processing identifiers reachable; confirm AI/synthetic authorship before labelling it.

Example: Our World in Data explains source changes across historical periods. GBIF documents values altered or inferred during indexing. A displayed calculation should identify its input scope and method; a title containing “model” alone must not establish AI authorship. [OWID processing notes](https://ourworldindata.org/grapher/life-expectancy) · [GBIF flags](https://training.gbif.org/en/data-use/dq-issues-and-flags)

## Design

Relevant implementation or evidence starting points:
- [src/components/MetadataPanels.tsx](../viewer/src/components/MetadataPanels.tsx)
- [src/components/EvidenceRecord.tsx](../viewer/src/components/EvidenceRecord.tsx)
- [src/components/Primitives.tsx](../viewer/src/components/Primitives.tsx)
- [tests/browser/recorded-producer-evidence.spec.ts](../viewer/tests/browser/recorded-producer-evidence.spec.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- A displayed transformation is traceable to its recorded method and exact relevant inputs.
- Unknown processing remains unknown; a model name alone does not establish AI authorship.
- Public views expose only admitted public facts; raw/derived values are never silently substituted.
- Readable provenance leaves the original source record and identifiers inspectable.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/context/handoff.md, outputs/implementation-20261107/retained-owner-checks.log. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
