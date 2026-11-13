---
id: ddk-ucoh
status: open
deps: []
links: []
created: 2026-11-13T19:03:50Z
type: feature
priority: 2
tags: [ddk, backlog, 2026-11-13]
---
# Represent periodic dataset editions as ordered DCAT series

Owner role: DDK catalog/interchange owner.

User outcome: Users can discover the latest declared edition and follow its predecessors.

Implement WP-15 item 2 using DCAT 3 DatasetSeries, inSeries and the appropriate predecessor/version relationships. Establish one maintained source for series membership and edition order. Observation time and array order confer no latest-edition authority.

Sources: [WP-15 item 2](../docs/implementation-plan.md#wp-15--layered-data-map-extensions-specified-not-implemented) and DDK-CATALOG-008.

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Independently authored annual and biennial examples preserve series identity, member identity and declared ordering in catalog/DCAT outputs.
- Missing, tied or contradictory edition metadata does not invent an order or publisher selection.
- Independent graph-reader checks verify membership and predecessor links, including disclosed/public views.
- Update normative shape/semantics, case traceability and user documentation together.
