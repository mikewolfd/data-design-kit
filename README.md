# Data Design Kit

**Status.** Engineering specification and implementation plan, November 5, 2026. Runtime implementation remains planned.

Data Design Kit (DDK) uses maintained data definitions to check designs, test transformations, and generate a catalog of exact versions, access methods, relationships, and evidence. Maintainers can use the same definitions to assess changes and supply documentation and consumer metadata.

The first product release requires ODPS product definitions, ODCS dataset definitions, DCAT 3 discovery, OpenLineage job and run events, and a qualified Substrait execution path through DocSpec. It also includes SQL and fixture tests, supported ODCS output checks, and change analysis. Native systems supply the records of capture, computation, retention, and publication.

## Read the design

- [Engineering specification](docs/specification.md): normative requirements, formats, algorithms, profiles, and conformance.
- [Implementation plan](docs/implementation-plan.md): work packages, dependencies, acceptance criteria, release gates, and risks.
- [Adapter profiles](docs/adapter-profiles.md): exact boundaries for third-party integrations and proposed capability negotiation.
- [Runtime integration](docs/runtime-integration.md): injected services, bounded versus managed execution, native bindings, and quality-gated selection.
- [Architecture decisions](docs/architecture-decisions.md): decisions and alternatives behind the draft.
- [Research and references](docs/references.md): public sources, observed versions, licensing, and unresolved compatibility.
- [Conformance cases](conformance/cases.json): independently specified future runtime tests.
- [Delivery verification](docs/verification.md): checks actually performed and their limits.
- [Commerce catalog example](examples/commerce/catalog/README.md) and [draft catalog schema](schemas/0.1/catalog.schema.json) show the product, discovery, lineage, and evidence formats.

The specification follows the structure of a W3C technical report. This is an independent engineering draft, not a W3C publication or standards-body endorsement. “Data Design Kit” and `ddk` are working names.

## What is present

This repository contains authored specifications, draft format schemas, examples, conformance expectations, and upstream provenance. It contains no DDK checker, compiler, ingestion runner, data-quality runtime, build tooling, or generated build directory. Example commands in the specification describe the proposed interface.

The integrated architecture separates domain rules, application use cases, and adapters. Native references preserve their original identity schemes. Check outcomes remain separate from uncertain runtime outcomes. Managed quality-gated selection and Substrait support are proposed work, not existing integration guarantees. DocSpec is team-owned and unreleased; its API may change to support the design.

The repository pins the ODCS schema correction and retains its published comparison snapshot. It also vendors the released ODPS and OpenLineage schemas used by the examples. Exact revisions, licenses, and digests are recorded in [PROVENANCE.md](PROVENANCE.md).

## Verification

Delivery verification used separate tooling outside this repository. It checked schema syntax, example documents, local links, requirement traceability, conformance-case references, and vendored digests. It also checked the example SQL against independently authored expected rows in SQLite. These checks do not establish DDK or adapter runtime conformance. The [verification record](docs/verification.md) describes their scope.

## License

Original material is licensed under Apache-2.0. Vendored material retains the attribution recorded in [NOTICE](NOTICE) and [upstream-artifacts.json](docs/upstream-artifacts.json). The implementation plan requires version-specific dependency and notice checks before a runtime release.
