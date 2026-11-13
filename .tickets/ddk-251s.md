---
id: ddk-251s
status: open
deps: []
links: [ddk-arnm, ddk-zxlb, ddk-citj]
created: 2026-11-13T19:44:54Z
type: task
priority: 1
tags: [ddk, greenfield, lessons-review]
---
# Expose source gaps and release-wide date and field availability

Owner role: Source-inventory owners supply expectations and observations; publisher SQL/DocSpec owners compute summaries; DDK catalog/viewer owners expose the retained results.

User outcome: A researcher can decide which sources, periods and fields support an analysis and explain what is missing or unassessed.

Publish the source owner's disclosed inventory and acquisition/processing/publication observations as ordinary DDK datasets with checked queries. Use existing guides, recipes and catalog companions; extend shared discovery only where a real task remains unsupported. Sources with no acquired version remain inventory rows without a fabricated source version. Acquisition and reconciliation stay with their maintained owners.

Bring the date/category and field-availability portion of ss-u3v6 into active P1 delivery. Publisher SQL computes small summaries bound to exact selected versions. General distribution/statistics features remain in the optional register. Observed distributions alone cannot establish source completeness.

Sources: [Source-gap approach](/Users/mikewolfd/Work/artifacts/ddk-user-value-review-2026-11-13/REPORT.md#4-explain-what-we-lack-including-sources-with-no-published-dataset), [availability summaries](/Users/mikewolfd/Work/artifacts/ddk-user-value-review-2026-11-13/REPORT.md#3-make-missing-dates-and-fields-visible-without-scanning-on-page-open), [original proposal](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-u3v6.md), [source owner](/Users/mikewolfd/Work/spicy-stack/spicy-regs/docs/shared-source-catalog.md).

## Acceptance Criteria

- Discover a required source/period with zero acquired or published versions through the ordinary inventory and its checked query. Show observation time, expectation source, scope, units, evidence and next route; keep bulk file inventories out of the initial catalog response.
- Distinguish a known acquisition gap from retained-but-unpublished content, narrowing processing/publication causes only when evidence permits. Preserve source not selected, failed/incomplete acquisition, publisher omission/null, not requested, unread and withheld states where supported.
- Answer which months/categories contain usable records and how often selected fields are present across the whole selected version. Use declared axes, units and tests; retain missing fields, nulls, empty text, unsaved/unread content and records unplaceable at the requested date precision as distinct states.
- Bind summaries to exact source versions, measured fields, scope, observation time and counted/uncountable rows. For exclusive buckets verify placed plus unplaced equals the population; overlapping counts must declare their meaning and cannot silently become percentages of distinct records.
- Detect known holes only against explicit expected identities/periods. Minimum/maximum dates and the current page cannot establish continuous or release-wide coverage. Unknown denominators remain unknown; verified empty requires a complete defined request.
- Load bounded retained summaries and inventory answers without scanning the corpus or recrawling sources on page open. Core metadata checks remain offline and read no data payloads; DocSpec executes the publisher's summary SQL.
- Use the same owner facts and applicable disclosure in API/MCP/viewer results. Independently check a missing edition, failed download, parser omission, unpublished output, unavailable relationship, missing date/field, valid empty and unknown denominator; include stale-version and withheld-evidence cases.
- Measure summary build/refresh cost, page-open requests/bytes and bounded response size under [ddk-zxlb](ddk-zxlb.md). Preserve original facts and historical evidence; creating a summary does not qualify its input data.

Priority and greenfield scope: [work backlog](../docs/work-backlog.md#greenfield-delivery).
