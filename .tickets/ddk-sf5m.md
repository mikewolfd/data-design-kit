---
id: ddk-sf5m
status: open
deps: []
links: []
created: 2026-11-13T19:03:50Z
type: chore
priority: 3
tags: [ddk, backlog, 2026-11-13]
---
# Maintain one ODCS 3.2.0 schema with its exact published-revision difference

Owner role: DDK schema/provenance owner.

User outcome: Maintainers avoid duplicate-schema drift while retaining exact upstream interpretation.

Implement WP-15 item 7: replace the duplicate 3.2.0-release copy with a recorded reconstruction/difference for DataQualityOperators oneOf versus anyOf. Reuse maintained schema/provenance mechanisms and preserve the comparison test.

Sources: [WP-15 item 7](../docs/implementation-plan.md#wp-15--layered-data-map-extensions-specified-not-implemented), [upstream inventory](../docs/upstream-artifacts.json).

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Retain exactly one maintained full schema and a documented exact difference reproducing both original revisions.
- Verify reconstructed bytes/identities against the recorded upstream digests and update affected references/provenance atomically.
- Independent cases keep the release-tag versus pinned-revision behavior distinct, including the affected quality-operator case.
- Run shape, resolver/comparison, provenance, link and requirement-traceability checks; keep the declared ODCS API version unchanged.
