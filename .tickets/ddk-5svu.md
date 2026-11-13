---
id: ddk-5svu
status: open
deps: []
links: [ddk-arnm, ddk-zxlb]
created: 2026-11-13T19:44:54Z
type: task
priority: 1
tags: [ddk, greenfield, lessons-review]
---
# Publish accepted job outputs and catalog artifacts through one shared remote release path

Owner role: DocSpec publication owner; DDK supplies catalog metadata and the product supplies destination/authority configuration.

User outcome: A fresh application publishes a coherent remote release without a product-specific publisher.

F1: connect accepted whole-job outputs, frozen catalog artifacts, immutable remote transfer, guarded selection, recovery and readback. Reuse existing DocSpec storage and lifecycle capabilities. Define one authoritative selection; do not maintain competing native and object-store latest pointers. Retain original attempt identity and separate later publication observations from frozen catalog bytes.

Sources: [F1](/Users/mikewolfd/Work/artifacts/ddk-lessons-review-2026-11-13/REVIEW.md#f1--blocker-whole-job-publication-stops-at-a-local-intent), [native API](/Users/mikewolfd/Work/spicy-stack/docspec-rs/src/engine/managed_job/publication.rs).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- A configured fresh product publishes complete related-table membership to the intended R2/storage-and-catalog combination; local intent alone does not pass.
- Bind exact candidate acceptance, output/catalog bytes, destination, expected authority token and original attempt before effects.
- Faults before/after transfer and selection, lost acknowledgement and cold recovery reuse completed work without re-uploading unchanged objects.
- An intervening successor survives stale retries; uncertain historical outcomes stay unknown. An intentional restore is a new guarded operation against current authority.
- Actual shared readers return the selected data/catalog combination; retain independent wrong-member, wrong-token and readback checks plus measured transfer/resource costs.
