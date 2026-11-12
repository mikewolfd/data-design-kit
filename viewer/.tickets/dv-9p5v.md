---
id: dv-9p5v
status: closed
deps: [dv-75lu, dv-bpgi, dv-z1gu, dv-rlsn, dv-5181, dv-6ana, dv-2wq2, dv-jla6, dv-zbaw, dv-ffmm, dv-radn, dv-f1gy]
links: []
created: 2026-11-07T18:17:11Z
type: task
priority: 1
external-ref: PCR-21:first-pilot
parent: dv-lgiy
tags: [viewer, portal-content, phase-1-acceptance, pcr-21]
---
# Evaluate the first-encounter improvements with both audiences

Requirements: PCR-21 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Product/content research and viewer acceptance. Delivery phase: phase-1-acceptance.

Current baseline: The current baseline and new phase-1 content must be compared on the same tasks and exact catalog examples; an expert review alone cannot establish usability.

Implementation scope:
- Run the frozen pilot tasks on the phase-1 implementation using real nontechnical participants and engineers.
- Record completion, time, assistance and misunderstanding against the baseline, including a readable/exportable example using its current supported route.
- Resolve and retest critical misunderstandings and missing technical identity; preserve participant and execution-scope evidence without overclaiming sample size.

Example: A nontechnical visitor chooses between two similarly titled datasets and explains what one row means. An engineer opens the same page and recovers the exact version, native field path, and export scope. Both identify an unresolved meaning without treating it as zero or absent.

## Design

Relevant implementation or evidence starting points:
- [docs/design.md](../docs/design.md)
- [tests/browser/copy-discovery.spec.ts](../tests/browser/copy-discovery.spec.ts)
- `outputs/public-catalog-research-20261107/product-requirements.md`

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Validate participant evidence against the exact answer key and preserve scope/limitations. Use only supported, explicitly scoped data routes. No native test execution, recruitment message or production action is implied.

## Acceptance Criteria

- The report records actual participant observations and distinguishes them from automated or agent checks.
- Readers explain variant choice, record/field meaning, limits and next action; engineers recover exact identities.
- Observed errors about availability, completeness, units, duplicate counts or export scope are corrected and retested.
- If participants or required examples are unavailable, the corresponding acceptance remains open; no fabricated pass is recorded.


## Notes

**2026-11-07T21:03:47Z**

Implementation and acceptance disposition, 2026-11-07: Implemented first-encounter changes passed automated checks. Required nontechnical and engineering participant observations and any resulting retests remain open. See outputs/implementation-20261107/implementation-report.md and study/README.md. No participant results or success percentages are claimed.

**2026-11-07T21:47:54Z**

User-directed acceptance method update (2026-11-07): the user asked for blind GPT-6.1 Sol light subagents as study personas. Seven fresh GPT-6.1 Sol low agents supplied simulated observations; this explicitly replaces the original real-participant dependency for this delivery. Human usability and human improvement remain unmeasured. Original criteria, study packet and raw observations are retained. See outputs/persona-study-20261107/report.md, scored-results.json and verification.json. The revised arm has 42 supported core answers and 42 reported completions within the bound. Independent scoring and three exposed follow-ups preserve exact identities and correct scoped interpretation. Observed navigation friction was repaired and retested.
