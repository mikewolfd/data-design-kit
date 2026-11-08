---
id: dv-rlsn
status: closed
deps: [dv-bpgi, dv-z1gu]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-02
parent: dv-lgiy
tags: [viewer, portal-content, phase-1, pcr-02]
---
# Distinguish dataset variants and search supplied former dataset names

Requirements: PCR-02 — [product requirements](../outputs/public-catalog-research-20261107/product-requirements.md).

Owner role: Publisher content and viewer discovery. Delivery phase: phase-1.

Current baseline: Exact aliases already distinguish repeated titles and search scope is catalog-local. Field-definition and cross-catalog search are not implemented.

Implementation scope:
- Show publisher-supplied variant purpose, period/population or collection context where it helps distinguish an entry.
- Index supported dataset-level alternate/former names while retaining exact ID/alias matching.
- Update help to match actual search coverage and preserve errors separately from a legitimate empty result.

Example: For two entries called “Public comments,” show their supplied distinction; retain the exact alias when that distinction remains unknown. **Illustrative rename:** if a publisher renames a dataset from “Service requests” to “311 service requests,” a supplied former dataset name should still find it. NYC's former field-label pattern is a separate precedent for the dictionary in PCR-06.

## Design

Relevant implementation or evidence starting points:
- [src/components/Workspace.tsx](../src/components/Workspace.tsx)
- [src/lib/display.ts](../src/lib/display.ts)
- [src/server/catalog-store.ts](../src/server/catalog-store.ts)
- [tests/browser/copy-discovery.spec.ts](../tests/browser/copy-discovery.spec.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- A supplied former dataset name and its exact ID find the same independently addressable entry.
- Same-title entries stay separate, and order or current/curated prefixes do not select a preferred version.
- Missing variant meaning retains the exact alias and an honest unknown; no UI synonym registry becomes authoritative.
- Field-label and record-content searches are not advertised unless separately implemented; failed catalog loads do not become “no matches.”


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/browser-review/report.md, outputs/implementation-20261107/record-browser/report.md. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
