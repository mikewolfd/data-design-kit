# DDK verification

## November 5, 2026 local release qualification

The [local release](local-release.md) passed qualification on macOS 26.6 arm64, Python 3.12.13, DDK commit `d86a3384ff7fe17101f34f92dda5422bb986864e`, and DocSpec commit `b1270b2e964becc5844bb6ca95ee5d605c7a3d79`. These results qualify the recorded local prerelease and supported operations.

- All 169 tests passed against the installed wheel outside the checkout: zero failures, errors, or skips. The run includes 137 applicable registered cases and all 154 required case/profile combinations for the 13 claimed profiles. Eleven RDFLib deprecation warnings remain visible in the test log.
- Two independent package builds produced identical wheel bytes. Captured source and external inputs remained unchanged throughout the run. A separate core-only installation passed without native engines, RDFLib, PyArrow, or pytest installed.
- The connected workflow binds actual staged inputs to SQL and saved-plan execution, checks exported files against independent expected rows, evaluates output quality, generates DCAT and OpenLineage, and runs a catalog-bound query against the checked saved-plan output. A same-project shared-definition change identifies the affected consumer and required requalification.
- Managed cases verify protected native field and version identity, complete required quality coverage, native evidence acceptance, guarded selection, rule-only reuse, stale and wrong-candidate refusals, timeout identity preservation, and reconciliation after a lost response. Bounded-job results remain separate.
- The final native runtime passed formatting, strict Clippy, and 17 focused tests. The retained runtime record identifies earlier broader library, integration, and Dagster checks separately from this final-source verification.
- Five qualified capability manifests passed schema validation and core-only discovery against the actual release report without native imports. Four CycloneDX software bills of materials passed schema validation; dependency locks and notices are retained with the package.
- Three repetitions of the small commerce fixture measured median core, impact, and metadata-refresh times of 35, 74, and 95 ms, with 49 MiB peak resident memory and zero instrumented metadata data-payload opens. Larger synthetic-library performance targets remain unmeasured.

The [qualification report](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/release-qualification.ddk.json), [execution evidence](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/release-evidence.json), and [JUnit results](/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/distribution/qualified-02/junit.xml) retain the actual claims and checks. The earlier `qualified-01` capture had two skips caused by a missing test-runner dependency; `qualified-02` supplies the complete final evidence.

The case registry specifies expectations; the [core](../conformance/core-evidence.json), [catalog](../conformance/catalog-evidence.json), [runtime](../conformance/runtime-evidence.json), and [integration](../conformance/integration-evidence.json) ledgers map cases to maintained tests. The final release inventory binds those tests to this installed run. Four optional cases remain outside the claim: independent Substrait validation, its separately pinned validator combination, second-engine portability, and nested dlt staging. Required `unknown` or `not_run` results still prevent an overall pass.

## November 5, 2026 final documentation audit

- Validated all 12 DDK schema shapes and checked all 27 JSON examples. This includes the nested ODCS dataset, ODPS product, DDK project, and independently authored expected citation matches. Validated the three illustrative OpenLineage events and five version facets against the pinned schemas. RDFLib 7.2.1 independently followed the illustrative DCAT catalog through the selected version to its distribution and download.
- Checked all 193 local Markdown links and anchors across 18 documents, all nine vendored artifacts against their recorded SHA-256 digests and Git blob identities, and the illustrative catalog's 13 input digests and five companion digests. The bundled revenue query matches the authored SQL byte for byte.
- Traced all 94 normative requirements to a single primary owner and at least one of the 141 registered cases. Verified the titles and required dependencies for all 17 work packages. The 24 required and three optional dependency edges form an acyclic graph. The dependency diagram preserves the registry's required dependency closure.
- Verified that the first-release profile list agrees with the specification. The full build also requires the intake and managed-operation work packages. The adopted scope excludes both pilot work packages. [Specification](specification.md#DDK-VERSION-003) · [Work-package registry](../implementation/work-packages.json)

The commerce catalog receipt, release, and lineage events under `examples/` remain illustrative. These document checks establish schema and reference consistency and byte identity. The [catalog evidence ledger](../conformance/catalog-evidence.json) records executed catalog cases. The [core evidence ledger](../conformance/core-evidence.json) records executed offline checker and impact cases; the final release inventory supplies their captured results.

Three catalog-related cases belong to broader release coverage. `CASE-VERSION-003` concerns missing saved-plan execution coverage. `CASE-TEST-004` requires the connected local demonstration. `CASE-TEST-005` requires an incomplete decision when separate passing checks omit a reader bound to the checked output of that same saved plan. All three passed in the final release run. [Conformance case registry](../conformance/cases.json)

## Earlier documentation deliveries

The earlier specification deliveries verified the document shapes then present, source and companion digests, local links, requirements traceability, and the rendered reading edition. They also compared the example commerce SQL with three independently authored expected rows using SQLite. The earlier 19-package plan included pilot dependencies. The November 5 audit reflects the adopted no-pilot build strategy and 17-package registry.

Verification tooling and generated build files are retained outside the repository.
