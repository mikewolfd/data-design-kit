---
id: dv-r0fd
status: closed
deps: [dv-9p5v, dv-k2k4, dv-h4ce]
links: []
created: 2026-11-07T18:17:11Z
type: feature
priority: 2
external-ref: PCR-04
parent: dv-lgiy
tags: [viewer, portal-content, phase-3, pcr-04]
---
# Publish one supported topic guide connecting a visitor question to datasets

Requirements: PCR-04 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Product/content, publisher metadata and viewer navigation. Delivery phase: phase-3.

Current baseline: Collections exist, but a maintained question-led guide is an additional capability. The viewer must not become a separate publisher fact store.

Implementation scope:
- Select one pilot-backed visitor question and two or three verified dataset destinations.
- Use the mapped supported publisher/companion mechanism for the guide; define owner schema work first if that mechanism is missing.
- Explain topic, scope, choice, next action and limits; label guidance as different from dataset results and link it from relevant results.

Example: The UK's road-safety guide describes the covered countries, incidents, publisher, and access route. AWS pairs climate data with named tutorials. A proposed guide titled “Find material about a congressional hearing” could distinguish meeting records, documents, and witness appearances once their exact relationships are established. [UK guide](https://www.data.gov.uk/collections/transport/road-safety) · [AWS climate examples](https://registry.opendata.aws/tag/climate/)

## Design

Relevant implementation or evidence starting points:
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [src/components/Connections.tsx](../src/components/Connections.tsx)
- [src/pages/api/companion.ts](../src/pages/api/companion.ts)
- [docs/content-guide.md](../docs/content-guide.md)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Every link has a useful purpose label, exact destination and accurate access expectation, including metadata-only destinations.
- The guide records author, supporting catalog references and review date, with a review trigger for consequential source changes.
- Any required source-owned schema/companion work is implemented and admitted before runtime use; no hard-coded viewer fact registry is introduced.
- The guide is usable by keyboard/mobile and a pilot participant can select the appropriate dataset for the question.


## Notes

**2026-11-07T21:03:47Z**

Implementation and acceptance disposition, 2026-11-07: Source-owned example guides, exact destinations, authorship, review dates/triggers and keyboard/mobile behavior are implemented. A real pilot-backed question and participant task success remain unestablished. See outputs/implementation-20261107/implementation-report.md and study/README.md. No participant results or success percentages are claimed.

**2026-11-07T21:47:54Z**

User-directed acceptance method update (2026-11-07): the user asked for blind GPT-6.1 Sol light subagents as study personas. Seven fresh GPT-6.1 Sol low agents supplied simulated observations; this explicitly replaces the original real-participant dependency for this delivery. Human usability and human improvement remain unmeasured. Original criteria, study packet and raw observations are retained. See outputs/persona-study-20261107/report.md, scored-results.json and verification.json. All seven personas used a source-owned synthetic guide, followed an appropriate exact dataset destination and correctly limited its claims. Grant-program and station-lookup questions were exercised. Authors, review dates/triggers, evidence and synthetic scope remain explicit. No real-person demand or real-world dataset coverage is claimed.
