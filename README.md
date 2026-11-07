# Data Design Kit

**Status.** November 6, 2026. The [dev6 catalog API package](docs/local-release-dev6.md) passed 385 installed tests and 142 case/profile combinations for core, catalog, DCAT and OpenLineage. It was built from source `b2637279`. Native execution and full replacement qualification remain separate.

The [dev5 package](docs/local-release-dev5.md) retains its earlier complete supported profile set, including source-only native managed Update. Dev6 does not extend that native qualification or claim another complete product release; its source adapter declarations remain `experimental-unverified`. The [dev2 portable archive](docs/local-release.md) remains unchanged. Publication awaits a destination.

The catalog API provides admitted definitions, exact companion bytes, scoped public disclosure, recipe context and parameter order, and external-reference loading. Application profiles preserve declared reasoning, unknown outcomes and separate executed evidence. DocSpec owns managed execution, native quality acceptance, protection, recovery and guarded selection. Dev6 qualifies the captured-definition metadata and explicit rule-binding APIs. Native whole-job preparation, recovery and fresh rich-fixture execution have focused development evidence. The successor's complete native gate currently fails resource-bound integration cases; broader native qualification and streaming quality remain open. Both application replacements are greenfield, with coordinated producer and reader updates. [Current work](docs/implementation-status.md#successor-work).

Data Design Kit (DDK) uses maintained data definitions to check designs, test transformations, and generate a catalog of exact versions, access methods, relationships, and evidence. Maintainers can use the same definitions to assess changes and supply documentation and consumer metadata. The adopted [build strategy](docs/build-strategy-without-pilots.md) connects local commerce inputs, real execution and quality receipts, and a generated catalog reader. Nested/scoped identities and one typed managed operation have separate acceptance cases. Full DDK stack replacements for SpicyRegs and congressional-tech remain separate, incomplete delivery work.

The first product release requires ODPS product definitions, ODCS dataset definitions, DCAT 3 discovery, OpenLineage job and run events, and a qualified Substrait execution path through DocSpec. It also includes SQL and fixture tests, supported ODCS output checks, and change analysis. Native systems supply the records of capture, computation, retention, and publication.

## Read the design

- [Engineering specification](docs/specification.md): normative requirements, formats, algorithms, profiles, and conformance.
- [Implementation plan](docs/implementation-plan.md): work packages, dependencies, acceptance criteria, release gates, and risks.
- [Full replacement runtime plan](docs/replacement-runtime-plan.md): shared DDK/DocSpec work required by SpicyRegs and congressional-tech, with owners and planned acceptance cases.
- [Build strategy without pilots](docs/build-strategy-without-pilots.md): adopted parallel implementation route using a local reference workflow.
- [Adapter profiles](docs/adapter-profiles.md): exact boundaries for third-party integrations and proposed capability negotiation.
- [Runtime integration](docs/runtime-integration.md): injected services, bounded versus managed execution, native bindings, and quality-gated selection.
- [Catalog API](docs/catalog-api.md): admitted definitions, exact companion bytes, public disclosure, and qualification boundaries.
- [Reusable React/Astro viewer](docs/verification.md#november-6-2026-reusable-reactastro-viewer): separate local application, maintained owner readers, exact-value verification and remaining connection limits.
- [Architecture decisions](docs/architecture-decisions.md): decisions and alternatives behind the draft.
- [Research and references](docs/references.md): public sources, observed versions, licensing, and unresolved compatibility.
- [Conformance cases](conformance/cases.json): independently specified runtime cases and their evidence.
- [Delivery verification](docs/verification.md): checks actually performed and their limits.
- [Latest complete profile package](docs/local-release-dev5.md): tested package, exact source versions, installation and supported limits. The [newer catalog package](docs/local-release-dev6.md) has a narrower qualification; the [dev2 portable guide](docs/local-release.md) retains dependency and archive instructions.
- [Commerce catalog example](examples/commerce/catalog/README.md) and [draft catalog schema](schemas/0.1/catalog.schema.json) show the product, discovery, lineage, and evidence formats.

The specification follows the structure of a W3C technical report. This is an independent engineering draft, not a W3C publication or standards-body endorsement. “Data Design Kit” and `ddk` are working names.

## What is present

This repository contains specifications, format schemas, independently authored examples and tests, upstream provenance, and the DDK source implementation. Build tooling, environments, dependency installations, and generated outputs remain outside the repository. The verification record identifies the exact code and dependencies covered by each qualification claim.

The integrated architecture separates domain rules, application use cases, and adapters. Native references preserve their original identity schemes. Check outcomes remain separate from uncertain runtime outcomes. The local demonstrations execute saved Substrait and exercise one typed managed quality gate; each claim remains bound to its tested dependency tuple. DocSpec is team-owned and unreleased; its API may change to support the design.

The repository pins the ODCS schema correction and retains its published comparison snapshot. It also vendors the released ODPS and OpenLineage schemas used by the examples. Exact revisions, licenses, and digests are recorded in [PROVENANCE.md](PROVENANCE.md).

## Verification

The [implementation status](docs/implementation-status.md) documents the commands and current runtime evidence. The [verification record](docs/verification.md) separates earlier documentation checks from native execution and conformance tests. Build environments, test outputs, and local distributions remain outside the repository.

The [portable release guide](docs/local-release.md#run-the-package) explains dependency downloads, native platform limits, and evidence relocation. The [dev1 record](docs/local-release-dev1.md) preserves the earlier capture separately.

## License

Original material is licensed under Apache-2.0. Vendored material retains the attribution recorded in [NOTICE](NOTICE) and [upstream-artifacts.json](docs/upstream-artifacts.json). The local release includes dependency locks, software bills of materials, and native dependency notices.
