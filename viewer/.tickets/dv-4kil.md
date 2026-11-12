---
id: dv-4kil
status: closed
deps: [dv-bvgl]
links: []
created: 2026-11-07T18:17:10Z
type: feature
priority: 1
external-ref: PCR-13
parent: dv-lgiy
tags: [viewer, portal-content, phase-2, pcr-13]
---
# Explain supported next actions, destinations and access requirements

Requirements: PCR-13 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Viewer access and adapter integration. Delivery phase: phase-2.

Current baseline: Capability-aware access states and refusal/error distinctions already exist. The addition makes the next available action and its requirements easy to understand.

Implementation scope:
- Use actual registered scope to offer records, fields, a query, a supplied download or a publisher destination.
- Show relevant account, permission, reader, size and request-limit facts before the action.
- Preserve loading, cancellation, refusal, failure and successful-empty states with recovery through real controls.

Example: AWS identifies a particular command that requires no account; Earth Engine identifies access registration for execution. **Proposed metadata-only copy:** “Explore the field definitions here. Open the publisher's dataset page for its access options,” when that URL is supplied. [AWS access instructions](https://registry.opendata.aws/noaa-ghcn/) · [Earth Engine access](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)

## Design

Relevant implementation or evidence starting points:
- [src/lib/content.ts](../src/lib/content.ts)
- [src/components/DataPanel.tsx](../src/components/DataPanel.tsx)
- [src/components/Connections.tsx](../src/components/Connections.tsx)
- [src/server/access.ts](../src/server/access.ts)
- [tests/unit/content-access.test.ts](../tests/unit/content-access.test.ts)

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Run npm test, npm run check, npm run build and the focused browser cases relevant to the changed behavior. Include meaningful unknown/refusal/empty/disclosure cases and desktop/mobile keyboard use. Preserve native integration opt-ins; a fixture or replay pass must retain that scope.

## Acceptance Criteria

- Browsing descriptions does not issue record/query requests, and no-version datasets offer no impossible choice.
- External actions name their destination and supplied requirements; conditions from one resource do not generalize to others.
- Recovery text points to controls that exist and preserves version/filter context.
- Withheld, unavailable, unknown, failed and successful-empty states remain behaviorally and visually distinct.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/record-browser/report.md, outputs/implementation-20261107/resource-dates-browser.json. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
