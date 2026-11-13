---
id: ddk-b2tk
status: open
deps: [ddk-aw0v, ddk-w3df, dv-dnke, ddk-p3mc]
links: []
created: 2026-11-13T19:03:50Z
type: task
priority: 2
tags: [ddk, backlog, 2026-11-13]
---
# Qualify the selected greenfield package surface against exact current runtime identities

Owner role: DDK release owner, with the DocSpec release owner.

User outcome: Users know exactly which installed features and dependency combinations are supported.

Select the supported greenfield surface after the normative scope reconciliation. Reuse SDK4 and later evidence only where byte identity, requirements and scope match; rebuild changed deliverables as needed. Reconcile the current source/resources, package, native binary, profile/case matrix and adapter manifests. The SDK3 profile claim and SDK4 test counts retain their original identities; registered profiles are not automatically qualified profiles.

Sources: [Latest test evidence](../docs/verification.md#november-13-2026-zero-skip-installed-and-viewer-checks), [WP-11](../docs/implementation-plan.md#wp-11--release-qualification-and-handoff), DDK-VERSION-003.

Priority order and deferred scope: [work backlog](../docs/work-backlog.md).

## Acceptance Criteria

- Produce an explicit requested-profile and required-case inventory for the exact release tuple, including the first-release standards together.
- Reuse matching evidence and run only changed or uncovered required cases; required skips, unknown or not_run outcomes prevent an overall qualification pass.
- Verify the core-only and full installations outside the source checkout, keeping native capability and SQL-only negative-control identities separate.
- Record the exact wheel/native/dependency digests, supported limits, completed profiles and remaining exclusions without rewriting older evidence.
- Confirm the default-runtime query fix through its maintained regression and actual registered consumer.
## Reconciliation

November 13, 2026: Release closure depends on the chosen normative surface and applicable regressions, not on completing every optional feature or both application replacements.
