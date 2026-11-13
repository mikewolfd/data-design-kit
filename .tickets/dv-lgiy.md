---
id: dv-lgiy
status: closed
deps: [dv-dkgk, dv-f3h7, dv-r0fd, dv-jmev]
links: []
created: 2026-11-07T18:17:10Z
type: epic
priority: 1
external-ref: PCR-01-21
tags: [viewer, portal-content, product-requirements]
---
# Make the data catalog usable for nontechnical visitors and engineers

Implement the public-catalog product requirements so nontechnical visitors can choose useful data, understand its limits, take a supported next step, and cite or revisit it while engineers retain exact identity and evidence.

Source: 21 product requirements (`outputs/public-catalog-research-20261107/product-requirements.md`) and eight-catalog research (`outputs/public-catalog-research-20261107/report.md`).

The baseline is da6214e plus the retained local catalog changes. Existing access states, scope-first checks, exact references, publisher selection, numeric precision, nested occurrences and public/private disclosure are behavior to preserve. Already shipped copy fixes are not new implementation work.

Work is divided into metadata mapping and baseline research, phase-1 first-encounter improvements, phase-2 resource/reuse/attribution improvements, and phase-3 evidence-backed facets, a topic guide and a prepared visual view. Each child identifies the incremental scope, example, file pointers and acceptance. Tickets remain unassigned until an owner accepts them.

## Design

Publisher-owned standard metadata is authoritative; the viewer owns presentation and capability-derived actions. External publisher/shared checkouts remain read-only references. Use supported owner integration or explicit owner handoff for missing metadata. Do not create a shadow metadata registry, automatic fixture fallback, runtime, scheduler or selection mutation.

Root owns shared src/components, src/lib and src/styles integration. Coordinate edits to those files even when ticket dependencies allow parallel investigation. Dependencies represent required inputs/evidence; parent membership is organizational. Partial and unknown field meanings remain specific questions rather than inferred descriptions.

No deployment, publication, external messaging, unrestricted full export or new native run is authorized by this planning epic. New capabilities require their own supported implementation and acceptance before being advertised.

## Acceptance Criteria

- All PCR-01 through PCR-21 requirements map to implemented child work and explicit acceptance evidence.
- All P1 work passes the final exact-code/catalog integration and mixed-audience task checks; unresolved publisher facts remain honest unknowns.
- P2 facets, one guide and one useful chart/map are supported by source metadata, actual capability and pilot evidence.
- The metadata-only and readable/exportable journeys preserve identity, precision, occurrence, disclosure and publisher authority.
- Optional/unavailable participant, publisher or native integration dependencies remain open; an expert review or draft is not a substitute for acceptance.
- Every child is complete with evidence before this epic closes; no production/publication claim is inferred from local checks.


## Notes

**2026-11-07T21:03:47Z**

Engineering implementation is integrated and verified. 19 child tickets are closed; six retain required participant/pilot acceptance. The epic stays in progress. See outputs/implementation-20261107/implementation-report.md. No deployment or publication performed.

**2026-11-07T21:47:54Z**

User-directed acceptance method update (2026-11-07): the user asked for blind GPT-6.1 Sol light subagents as study personas. Seven fresh GPT-6.1 Sol low agents supplied simulated observations; this explicitly replaces the original real-participant dependency for this delivery. Human usability and human improvement remain unmeasured. Original criteria, study packet and raw observations are retained. See outputs/persona-study-20261107/report.md, scored-results.json and verification.json. All 25 child tickets are closed with implementation and simulated-acceptance evidence. Final source and catalog identities, retained skip scopes, unresolved source facts and remaining UX limits are documented in the final report. No deployment or publication was performed.
