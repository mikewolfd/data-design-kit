---
id: dv-radn
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-11
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-11]
---
# Summarize check results by subject and retain scope-first check cards

Requirements: PCR-11 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Viewer checks and evidence. Delivery phase: phase-1.

Current baseline: Commit da6214e already leads version-check cards with exact scope and shows reason separately. This is a regression baseline, not an unimplemented title feature.

Implementation scope:
- Improve the overview of what was checked and what is still unknown for the selected subject.
- Keep catalog checks, version checks, fingerprint verification, data qualification and recorded acceptance visibly distinct.
- Reuse scope and reason; preserve rule/evaluator/evidence references and public disclosure.

Example: “File fingerprint matches the recorded reference” supports identity, while “Amounts are zero or greater” concerns a specific value condition. Neither statement establishes complete source coverage. GBIF's record-level quality flags likewise describe particular findings. [GBIF quality guidance](https://training.gbif.org/en/data-use/data-quality)

## Design

Relevant implementation or evidence starting points:
- [src/components/MetadataPanels.tsx](../viewer/src/components/MetadataPanels.tsx)
- [src/components/EvidenceRecord.tsx](../viewer/src/components/EvidenceRecord.tsx)
- [tests/unit/check-scopes.test.ts](../viewer/tests/unit/check-scopes.test.ts)
- [tests/browser/check-scopes.spec.ts](../viewer/tests/browser/check-scopes.spec.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Missing results are not counted as passes; passed, failed, unknown and not_run remain distinct.
- A fingerprint match makes only a file-identity claim; no summary turns passed checks into general reliability or complete coverage.
- Exact long scopes wrap in full, optional reasons remain separate, and identifiers remain unchanged.
- The existing public/private pair and generic check tests retain their audience boundaries; no unsupported rule.title requirement is introduced.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/retained-owner-checks.log, outputs/implementation-20261107/record-browser/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
