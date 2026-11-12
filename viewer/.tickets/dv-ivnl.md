---
id: dv-ivnl
status: closed
deps: [dv-bvgl]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-14
parent: dv-lgiy
tags: [viewer, portal-content, phase-2, pcr-14]
---
# Keep exact version, filter and page scope visible with record previews

Requirements: PCR-14 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Viewer records and reader integration. Delivery phase: phase-2.

Current baseline: Counts already appear only after successful reads, and bounded pages retain exact request context. The addition makes that context consistently visible in preview captions.

Implementation scope:
- Identify dataset, exact version/resource, filter, page count and known continuation/truncation state beside each preview.
- Distinguish an ordinary page, an ordered first set and a publisher-documented sample.
- Preserve the selected context after navigation/filtering and discard late responses for superseded selections.

Example: The UK preview explicitly identifies the first four rows of a named 2009 file. **Illustrative copy:** “25 records on this page from the selected version · Filter: region = North · More records may be available.” [UK preview](https://www.data.gov.uk/dataset/b483ed79-65f2-4809-8fc2-e61f7bbfad11/road-traffic-collisions/datafile/10c2fe7f-f684-47d6-bb2f-f40dd20b74f1/preview)

## Design

Relevant implementation or evidence starting points:
- [src/components/DataPanel.tsx](../src/components/DataPanel.tsx)
- [src/lib/client.ts](../src/lib/client.ts)
- [tests/unit/read-details.test.ts](../tests/unit/read-details.test.ts)
- [tests/browser/copy-records.spec.ts](../tests/browser/copy-records.spec.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Preview captions and expanded identity details match the returned request and selected resource.
- Unknown continuation remains unknown; a failed read has no zero-record success count.
- Changing version/filter cannot show stale records under the new caption.
- Examples stay visibly labelled and no automatic prefetch or representativeness claim is introduced.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/resources/integration.md, outputs/implementation-20261107/record-browser/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
