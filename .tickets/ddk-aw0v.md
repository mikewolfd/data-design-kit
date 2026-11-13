---
id: ddk-aw0v
status: open
deps: []
links: [ddk-b2tk]
created: 2026-11-13T19:44:54Z
type: task
priority: 2
tags: [ddk, greenfield, lessons-review]
---
# Define the greenfield release surface and remove superseded framework requirements together

Owner role: DDK specification and release owner with DocSpec capability owners.

User outcome: The supported package contains the capabilities the fresh products need without obsolete framework obligations.

F7 is a product-scope and implementation task, not a legacy migration. Decide keep/replace/drop from current user outcomes, qualify needed replacements and remove superseded commands/formats from the ordinary path. Preserve historical evidence separately. Until an explicit normative revision lands, DDK-CONF-005 and DDK-VERSION-003 remain the current conformance rules.

Sources: [F7](/Users/mikewolfd/Work/artifacts/ddk-lessons-review-2026-11-13/REVIEW.md#f7--concern-the-frozen-framework-remains-part-of-the-release-burden), [boundary](../docs/specification.md#DDK-CONF-005), [release profiles](../docs/specification.md#DDK-VERSION-003).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- Map frozen components/designs, compatibility/impact, intake, locks, fixtures, saved plans, bundles/bindings and commands to retained user behavior, a replacement, or a documented dropped requirement.
- Preserve the currently required ODPS, DCAT 3, OpenLineage and saved-Substrait behaviors through the supported path unless the requirements are explicitly revised; old wrapper APIs are not compatibility obligations.
- Update specification, schema references, work-package ownership, case inventory, CLI/API support and release profile matrix atomically with removals.
- Run independent fresh-install consumer and negative/refusal cases for the new surface; archive old qualification without restamping it.
- Measure the reduction in maintained concepts/dependencies or explain remaining cost. Application construction proceeds while this release-surface work is open.
