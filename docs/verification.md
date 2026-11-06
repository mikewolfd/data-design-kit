# DDK verification

## November 5, 2026 documentation audit

- Validated all 12 DDK schema shapes and checked all 27 JSON examples. This includes the nested ODCS dataset, ODPS product, DDK project, and independently authored expected citation matches. Validated the three illustrative OpenLineage events and five version facets against the pinned schemas. RDFLib 7.2.1 independently followed the illustrative DCAT catalog through the selected version to its distribution and download.
- Checked all 160 local Markdown links and anchors, all nine vendored artifacts against their recorded SHA-256 digests and Git blob identities, and the illustrative catalog's 13 input digests and five companion digests. The bundled revenue query matches the authored SQL byte for byte.
- Traced all 94 normative requirements to a single primary owner and at least one of the 141 registered cases. Verified the titles and required dependencies for all 17 work packages. The 24 required and three optional dependency edges form an acyclic graph. The dependency diagram preserves the registry's required dependency closure.
- Verified that the first-release profile list agrees with the specification. The full build also requires the intake and managed-operation work packages. The adopted scope excludes both pilot work packages. [Specification](specification.md#DDK-VERSION-003) · [Work-package registry](../implementation/work-packages.json)

The commerce catalog receipt, release, and lineage events remain illustrative. These document checks establish schema and reference consistency and byte identity. The [catalog evidence ledger](../conformance/catalog-evidence.json) records executed catalog cases. The [core evidence ledger](../conformance/core-evidence.json) records executed cases and unresolved coverage for the offline checker and impact analyzer.

Three catalog-related cases belong to broader release coverage. `CASE-VERSION-003` concerns missing saved-plan execution coverage. `CASE-TEST-004` requires the connected local demonstration. `CASE-TEST-005` requires an incomplete decision when separate passing checks omit a reader bound to the checked output of that same saved plan. Track these cases with release evidence. [Conformance case registry](../conformance/cases.json)

## Earlier documentation deliveries

The earlier specification deliveries verified the document shapes then present, source and companion digests, local links, requirements traceability, and the rendered reading edition. They also compared the example commerce SQL with three independently authored expected rows using SQLite. The earlier 19-package plan included pilot dependencies. The November 5 audit reflects the adopted no-pilot build strategy and 17-package registry.

Verification tooling and generated build files are retained outside the repository.
