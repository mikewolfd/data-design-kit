# Data Design Kit

**Status.** November 6, 2026. The local stack is implemented. Source version `0.1.0-dev.2` corrects installation identity, capability qualification, fixture evidence, and release relocation; its installed-package qualification is pending. The earlier `0.1.0-dev.1` capture passed 169 tests and 13 profiles on its recorded source and dependencies. Both versions remain unpublished. [Release status and retained evidence](docs/local-release.md).

Data Design Kit (DDK) uses maintained data definitions to check designs, test transformations, and generate a catalog of exact versions, access methods, relationships, and evidence. Maintainers can use the same definitions to assess changes and supply documentation and consumer metadata. The adopted [build strategy](docs/build-strategy-without-pilots.md) connects local commerce inputs, real execution and quality receipts, and a generated catalog reader. Nested/scoped identities and one typed managed operation have separate acceptance cases. Project pilots remain deferred.

The first product release requires ODPS product definitions, ODCS dataset definitions, DCAT 3 discovery, OpenLineage job and run events, and a qualified Substrait execution path through DocSpec. It also includes SQL and fixture tests, supported ODCS output checks, and change analysis. Native systems supply the records of capture, computation, retention, and publication.

## Read the design

- [Engineering specification](docs/specification.md): normative requirements, formats, algorithms, profiles, and conformance.
- [Implementation plan](docs/implementation-plan.md): work packages, dependencies, acceptance criteria, release gates, and risks.
- [Build strategy without pilots](docs/build-strategy-without-pilots.md): adopted parallel implementation route using a local reference workflow.
- [Adapter profiles](docs/adapter-profiles.md): exact boundaries for third-party integrations and proposed capability negotiation.
- [Runtime integration](docs/runtime-integration.md): injected services, bounded versus managed execution, native bindings, and quality-gated selection.
- [Architecture decisions](docs/architecture-decisions.md): decisions and alternatives behind the draft.
- [Research and references](docs/references.md): public sources, observed versions, licensing, and unresolved compatibility.
- [Conformance cases](conformance/cases.json): independently specified runtime cases and their evidence.
- [Delivery verification](docs/verification.md): checks actually performed and their limits.
- [Local release](docs/local-release.md): tested package, exact source versions, installation, dependency records, and supported limits.
- [Commerce catalog example](examples/commerce/catalog/README.md) and [draft catalog schema](schemas/0.1/catalog.schema.json) show the product, discovery, lineage, and evidence formats.

The specification follows the structure of a W3C technical report. This is an independent engineering draft, not a W3C publication or standards-body endorsement. “Data Design Kit” and `ddk` are working names.

## What is present

This repository contains specifications, format schemas, independently authored examples and tests, upstream provenance, and the DDK source implementation. Build tooling, environments, dependency installations, and generated outputs remain outside the repository. The verification record identifies the exact code and dependencies covered by each qualification claim.

The integrated architecture separates domain rules, application use cases, and adapters. Native references preserve their original identity schemes. Check outcomes remain separate from uncertain runtime outcomes. The local demonstrations execute saved Substrait and exercise one typed managed quality gate; each claim remains bound to its tested dependency tuple. DocSpec is team-owned and unreleased; its API may change to support the design.

The repository pins the ODCS schema correction and retains its published comparison snapshot. It also vendors the released ODPS and OpenLineage schemas used by the examples. Exact revisions, licenses, and digests are recorded in [PROVENANCE.md](PROVENANCE.md).

## Verification

The [implementation status](docs/implementation-status.md) documents the commands and current runtime evidence. The [verification record](docs/verification.md) separates earlier documentation checks from native execution and conformance tests. Build environments, test outputs, and local distributions remain outside the repository.

## License

Original material is licensed under Apache-2.0. Vendored material retains the attribution recorded in [NOTICE](NOTICE) and [upstream-artifacts.json](docs/upstream-artifacts.json). The local release includes dependency locks, software bills of materials, and native dependency notices.
