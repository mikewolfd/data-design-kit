---
id: dv-dkgk
status: closed
deps: [dv-9p5v, dv-4kil, dv-khs1, dv-k2k4, dv-h4ce]
links: []
created: 2026-11-07T18:17:11Z
type: task
priority: 1
external-ref: PCR-21:final-acceptance
parent: dv-lgiy
tags: [viewer, portal-content, phase-2-acceptance, pcr-21]
---
# Verify the complete P1 discovery-to-reuse journey and evidence

Requirements: PCR-21 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Viewer integration and product/content acceptance. Delivery phase: phase-2-acceptance.

Current baseline: Individual component passes and metadata readability do not establish the complete visitor journey. Phase-2 changes must retain the phase-1 usability and identity outcomes.

Implementation scope:
- Run the exact final code/catalog combination through discovery, interpretation, access, related data, preview, export and citation.
- Exercise refusal, unknown, metadata-only, successful-empty and exact-number/nested cases, with keyboard and mobile access.
- Repeat affected participant tasks after phase-2 changes and record the actual route used: fixture, retained replay, owner integration or publication.

Example: A nontechnical visitor chooses between two similarly titled datasets and explains what one row means. An engineer opens the same page and recovers the exact version, native field path, and export scope. Both identify an unresolved meaning without treating it as zero or absent.

## Design

Relevant implementation or evidence starting points:
- [tests/browser/workspace.spec.ts](../tests/browser/workspace.spec.ts)
- [tests/browser/copy-records.spec.ts](../tests/browser/copy-records.spec.ts)
- [tests/browser/publisher-copy.spec.ts](../tests/browser/publisher-copy.spec.ts)
- [docs/design.md](../docs/design.md)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- All P1 requirement mappings have evidence at the final changed source/catalog identity, with unresolved publisher facts still explicit.
- Required unit/type/build and focused browser checks pass; optional integrations retain their exact skipped/unqualified disposition.
- Downloads/citations carry exact selection and scope, and public views disclose no private fields or locations.
- Affected participant tasks meet baseline-derived targets after critical misunderstandings are corrected; missing observations remain open.
- No claim upgrades a metadata/replay check into native execution or hosted publication; owned acceptance processes are closed when finished.


## Notes

**2026-11-07T21:03:47Z**

Implementation and acceptance disposition, 2026-11-07: Engineering verification is recorded. The required human baseline/follow-up comparison and correction/retest decisions remain open. See outputs/implementation-20261107/implementation-report.md and study/README.md. No participant results or success percentages are claimed.

**2026-11-07T21:47:54Z**

User-directed acceptance method update (2026-11-07): the user asked for blind GPT-6.1 Sol light subagents as study personas. Seven fresh GPT-6.1 Sol low agents supplied simulated observations; this explicitly replaces the original real-participant dependency for this delivery. Human usability and human improvement remain unmeasured. Original criteria, study packet and raw observations are retained. See outputs/persona-study-20261107/report.md, scored-results.json and verification.json. Final repair verification: npm test 102 passed/4 optional skipped; npm run check and build zero errors/warnings/hints; 53 focused browser cases passed. All 14 initial grant download pairs preserve exact values, request context, hidden fields and repeated occurrences. Three exposed retests passed. The 19 partial and 5 unknown source meanings remain flagged.
