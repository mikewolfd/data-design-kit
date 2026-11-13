---
id: dv-jmev
status: closed
deps: [dv-9p5v, dv-ivnl, dv-g9m0]
links: []
created: 2026-11-07T18:17:11Z
type: feature
priority: 2
external-ref: PCR-17
parent: dv-lgiy
tags: [viewer, portal-content, phase-3, pcr-17]
---
# Add one useful prepared chart or map with exact scope and a table alternative

Requirements: PCR-17 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Viewer visualization and publisher interpretation. Delivery phase: phase-3.

Current baseline: Tables and bounded data access exist. Charts/maps are a new presentation capability and must use a real supported result, not metadata-derived example values.

Implementation scope:
- Choose one question justified by pilot findings and one qualified data route; inspect maintained visualization components before adding custom infrastructure.
- Show measure, unit, denominator/population, aggregation, period, version and sample scope, including omitted values.
- Keep an accessible table and downloadable underlying scope; record transformation and publisher/community/example authorship.
- Treat any missing reader or computation as explicit owner work before enabling the view; do not add a scheduler or native runtime.

Example: World Bank and Our World in Data pair visual exploration with data tables and context. A map of reported observations should say that it shows observation locations, not imply complete geographic coverage. NYC separately identifies community-created views. [World Bank](https://data.worldbank.org/indicator/EG.ELC.ACCS.ZS) · [OWID](https://ourworldindata.org/grapher/life-expectancy) · [NYC community example](https://data.cityofnewyork.us/Social-Services/311-calls-by-year/sxrf-xcxa)

## Design

Relevant implementation or evidence starting points:
- [src/components/DataPanel.tsx](../viewer/src/components/DataPanel.tsx)
- [src/components/Primitives.tsx](../viewer/src/components/Primitives.tsx)
- [src/domain/exact.ts](../viewer/src/domain/exact.ts)
- [src/styles/workspace.css](../viewer/src/styles/workspace.css)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- The chart/map reconciles to identified input values and explains missing/excluded data and any aggregation.
- Metadata-only datasets show no simulated chart; maps of observations do not imply complete geographic coverage.
- Table and export retain exact values; values that cannot be plotted faithfully are handled explicitly instead of silently rounded.
- Keyboard/nonvisual and mobile access work, and the pilot user can answer the intended question with correct scope.


## Notes

**2026-11-07T21:03:47Z**

Implementation and acceptance disposition, 2026-11-07: The publisher-authored example count view uses actual returned records, reconciles exclusions and exact values, and preserves table/export scope. A pilot-backed question and participant interpretation remain unestablished. See outputs/implementation-20261107/implementation-report.md and study/README.md. No participant results or success percentages are claimed.

**2026-11-07T21:47:54Z**

User-directed acceptance method update (2026-11-07): the user asked for blind GPT-6.1 Sol light subagents as study personas. Seven fresh GPT-6.1 Sol low agents supplied simulated observations; this explicitly replaces the original real-participant dependency for this delivery. Human usability and human improvement remain unmeasured. Original criteria, study packet and raw observations are retained. See outputs/persona-study-20261107/report.md, scored-results.json and verification.json. All seven personas interpreted the actual returned-page station counts, exclusions, unspecified period and underlying download. The exposed mobile retest reproduced 5 ALDER, 4 BIRCH and 1 null from 10 returned rows and used the new keyboard summary shortcut. The full 14-row resource and real-world population remain distinct.
