# Data Design Kit

**Status.** November 7, 2026. Package `0.1.0.dev6+integrated.3` passes installed qualification for all 13 supported profiles, including DocSpec execution, managed recovery, catalog APIs, DCAT and OpenLineage. All 266 required case/profile checks passed. The [local package guide](docs/local-release-integrated-3.md) identifies the tested source, wheel, native executable and retained results.

One fresh installed run passed 703 tests with zero failures, errors or skips. Separate offline-core API, CLI and lock checks also passed. The connected commerce workflow exercises staging, SQL, saved Substrait, output quality and a catalog-bound reader. Source declarations remain experimental. The five generated adapter manifests qualify with their admitted evidence. Earlier SDK2 results retain their original skipped outcomes and supplemental evidence.

DocSpec owns execution, durable phases, source access, retained inputs, recovery, accepted quality evidence and guarded selection. Its current native gate passed 1,011 Rust and 31 Dagster tests, with 17 explicitly ignored Rust cases retained. A separate synthetic S3 fixture proves recovery after an input-read failure and offline acceptance; installed SDK2 calls recover that same accepted candidate. [Current verification](docs/verification.md#november-7-2026-sdk3-complete-installed-qualification).

SDK3 also supports explicit host-owned process groups. Nine POSIX process probes passed both from source and installed, alongside the existing transport checks. These probes use stand-ins and preserve uncertain native execution after timeout. [Process evidence](docs/verification.md#november-7-2026-host-process-ownership).

Congress's [original eight-table source proof](docs/verification.md#november-7-2026-congress-retained-source-proof) separately passed against retained archive snapshots. Fresh official-source checks, application publication and the complete Congress and SpicyRegs replacements remain separate work. The reusable React/Astro viewer has its own acceptance record. The [dev2 portable archive](docs/local-release.md) and older package results retain their original identities; this qualification does not create a new portable archive or hosted release.

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
- [Current qualified package](docs/local-release-integrated-3.md): exact SDK3 and DocSpec identities, supported profiles, use and remaining limits. The [SDK2 guide](docs/local-release-integrated-2.md), [dev6 catalog increment](docs/local-release-dev6.md), [dev5 full-profile package](docs/local-release-dev5.md) and [dev2 portable guide](docs/local-release.md) retain their earlier results.
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
