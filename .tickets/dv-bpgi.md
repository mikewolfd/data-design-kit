---
id: dv-bpgi
status: closed
deps: [dv-1zol]
links: []
created: 2026-11-07T18:17:10Z
type: task
priority: 1
external-ref: PCR-20:publisher
parent: dv-lgiy
tags: [viewer, portal-content, foundation, pcr-20]
---
# Integrate supported pilot metadata and retain unresolved publisher questions

Requirements: PCR-20 — product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`).

Owner role: Publisher content and viewer catalog integration. Delivery phase: foundation.

Current baseline: Earlier publisher work and regenerated captures already exist. The current SpicyRegs record retains 19 partial meanings and five unknown meanings; those counts are a dated baseline, not permission to fill gaps by inference.

Implementation scope:
- Using the source mapping, supply or prepare publisher-owned title, variant, purpose, field and caution changes for the selected pilot datasets.
- Keep the pre-change baseline snapshots available for the separate usability study. Integrate regenerated artifacts only through the established pinned-catalog path.
- For read-only external publisher checkouts, produce the exact proposed source patch and record the owner handoff; do not mutate those references. Integrate returned supported artifacts when available.
- Update the exact-occurrence evidence ledger, retaining unknown facts and historical scope. Additional source facts remain owner dependencies.

Example: The latest SpicyRegs review leaves 19 partial meanings and five unknown meanings. For `related_docs[].congressReceived`, a top-level treaty definition does not establish the meaning of the nested field. Keep that exact question open until an applicable source resolves it. Current remaining questions (`outputs/spicy-resume-20261106/remaining-unknowns.md`)

## Design

Relevant implementation or evidence starting points:
- [docs/content-guide.md](../viewer/docs/content-guide.md)
- [fixtures/applications/spicy-regs/catalog.ddk.json](../viewer/fixtures/applications/spicy-regs/catalog.ddk.json)
- [fixtures/applications/spicy-regs/catalog.lock.json](../viewer/fixtures/applications/spicy-regs/catalog.lock.json)
- [src/server/registry.ts](../viewer/src/server/registry.ts)
- `outputs/spicy-resume-20261106/remaining-unknowns.md`

Preserve the parent epic's source ownership, explicit unknowns, exact values/identities, nested occurrences, disclosure and selection boundaries. Root coordinates shared component/lib/style edits. The listed paths are starting points, not permission to edit external read-only sources.

Validation: Verify source-to-generated-artifact parity and deterministic regeneration, then run npm test, npm run check, npm run build and the focused publisher/content browser cases for the integrated catalog changes. Preserve optional/native qualification limits; do not start fresh native execution implicitly.

## Acceptance Criteria

- Each changed factual statement has applicable official-source evidence and a maintained source location, or remains explicitly unknown.
- Regeneration and reassembly preserve identities, exact numbers, nesting, public disclosure and publisher selections; artifact changes are explained and pins updated together.
- Pilot descriptions distinguish useful variants without treating current/curated prefixes as selection authority.
- Previous evidence and baseline captures remain retrievable. An owner patch alone is not reported as an integrated catalog change.


## Notes

**2026-11-07T21:03:47Z**

Implemented and locally verified, 2026-11-07. See outputs/implementation-20261107/implementation-report.md and verification.json. Focused evidence: outputs/implementation-20261107/metadata/publisher-extension.md, outputs/implementation-20261107/gap-review/fixture-preservation.json. Standard metadata, explicit unknowns, exact numbers/identities/nesting, disclosure and publisher selections are preserved. Participant validation remains tracked separately by PCR-21 and its dependent tickets.
