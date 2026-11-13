---
id: ddk-251s
status: open
deps: []
links: [ddk-arnm, ddk-zxlb]
created: 2026-11-13T19:44:54Z
type: task
priority: 1
tags: [ddk, greenfield, lessons-review]
---
# Show missing and unassessed source coverage even before any version is acquired

Owner role: Source-inventory owner supplies expectations; DDK catalog and shared serving owners expose observations and limits.

User outcome: Users can tell what data is missing, stale, failed, unlinked or never assessed for their question.

Keep expected publisher populations separate from observed version facts. Reuse maintained source inventories and native acquisition/run records, with one owner for each expectation. Sources with no acquired version must remain visible. Derive gap views outside ordinary queries and preserve explicit scope, units, assessment time and evidence.

Sources: [Coverage findings](/Users/mikewolfd/Work/artifacts/ddk-lessons-review-2026-11-13/REVIEW.md#knowing-what-we-do-not-have-or-know), [version coverage](../schemas/0.1/catalog.schema.json), [source inventory](/Users/mikewolfd/Work/spicy-stack/spicy-regs/docs/shared-source-catalog.md).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- A required source and period with zero acquired versions remain discoverable as not collected or unassessed, without fabricating a version or empty success.
- Independent examples distinguish known missing editions, failed downloads, parser omissions, publisher-null fields, unpublished outputs and unavailable relationships.
- Detect holes against explicit expected identities/periods; minimum/maximum dates alone never establish continuity.
- Completeness percentages use matching population, scope and units; unknown denominators stay unknown. Show the last assessment and affected questions.
- Verify public/local disclosure and API/MCP/viewer presentation from the same owner facts; ordinary queries read retained findings rather than recrawling or auditing payloads.
