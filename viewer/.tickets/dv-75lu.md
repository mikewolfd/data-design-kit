---
id: dv-75lu
status: closed
deps: []
links: []
created: 2026-11-07T18:17:10Z
type: task
priority: 1
external-ref: PCR-21:baseline
parent: dv-lgiy
tags: [viewer, portal-content, foundation, pcr-21]
---
# Prepare the mixed-audience pilot and measure the current viewer

Requirements: PCR-21 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Product/content research. Delivery phase: foundation.

Current baseline: The requirements propose five to eight nontechnical participants and two or three engineers. No usability improvement has yet been measured.

Implementation scope:
- Select three comparable datasets with supplied distinctions, including a metadata-only example, an unresolved field and at least one readable/exportable result.
- Freeze an answer key to the exact catalog copies, versions and resource scopes. Document fixture versus retained application evidence.
- Prepare the six product tasks and record current-viewer completion, timing, assistance and misunderstandings with actual participants when available. Recruitment or external messaging needs separate authorization.

Example: Ask a visitor whether two “Public comments” entries represent interchangeable data. Ask an engineer to recover the exact dataset and selected version from the same page.

## Design

Relevant implementation or evidence starting points:
- [docs/design.md](../docs/design.md)
- `outputs/public-catalog-research-20261107/product-requirements.md`

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Validate participant evidence against the exact answer key and preserve scope/limitations. Use only supported, explicitly scoped data routes. No native test execution, recruitment message or production action is implied.

## Acceptance Criteria

- The protocol, selected references and answer key cover dataset choice, record/field meaning, check/coverage interpretation, next action, export scope and technical identity.
- The baseline contains actual participant observations and consent-appropriate de-identified notes; expert or agent walkthroughs are labelled separately.
- Success targets are derived from the baseline rather than invented in advance; safety-critical misinterpretations are identified explicitly.
- If participants are unavailable, report that dependency and leave the measurement open rather than claiming the baseline was conducted.


## Notes

**2026-11-07T21:03:47Z**

Implementation and acceptance disposition, 2026-11-07: Actual participant observations and baseline-derived targets are not yet available. The original source and answer key are preserved; the study packet is prepared. See outputs/implementation-20261107/implementation-report.md and study/README.md. No participant results or success percentages are claimed.

**2026-11-07T21:47:54Z**

User-directed acceptance method update (2026-11-07): the user asked for blind GPT-6.1 Sol light subagents as study personas. Seven fresh GPT-6.1 Sol low agents supplied simulated observations; this explicitly replaces the original real-participant dependency for this delivery. Human usability and human improvement remain unmeasured. Original criteria, study packet and raw observations are retained. See outputs/persona-study-20261107/report.md, scored-results.json and verification.json. The original arm has 42 supported answers; 41 attempts were reported within the task bound. The one API-persona download overrun remains partial. Baseline findings drove the seven explicit repair targets; no human timing or fabricated percentage was substituted.
