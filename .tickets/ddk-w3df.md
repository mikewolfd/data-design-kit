---
id: ddk-w3df
status: open
deps: []
links: [ddk-b2tk]
created: 2026-11-13T19:44:54Z
type: task
priority: 2
tags: [ddk, greenfield, lessons-review]
---
# Retain independent conformance cases for layer order on DocSpec job inputs

Owner role: DDK core policy and conformance owner.

User outcome: A fresh job-based map cannot silently read a forbidden later layer.

The production-input edge implementation already exists in policies.py. Supersede ss-uss0 as a feature request and close the remaining maintained-case/traceability gap. Current layered-map tests exercise components, recipes and relationships but do not name a job-specific layer-order case; confirm coverage before adding a duplicate.

Sources: [Existing edge traversal](../src/ddk/policies.py), [layered cases](../tests/core/test_layered_imports.py).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- Identify existing job-specific coverage or add an independently authored lower/same/forbidden-later-layer job example to the maintained suite.
- Assert the actual decision and policy diagnostic, including unknown/unassigned layer handling and imported aliases.
- Bind the case to DDK-POLICY-006 and its maintained test selector; run it without a selected execution engine or data reads.
- Credit the existing implementation; do not invent a new dependency model or reopen completed job-production work.
