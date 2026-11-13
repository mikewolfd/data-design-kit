# Data Design Kit

**Status. November 13, 2026.** Main includes the layered catalog, knowledge graph/RML exports, DocSpec recipe gates, job productions and ODCS SQL counters. The latest verification passed 1,242 installed Python tests, 112 viewer unit tests, 65 browser tests and two additional historical replay checks, all with zero skips. Type checking and the viewer build also passed. [Exact source, package, native identities and evidence limits](docs/verification.md#november-13-2026-zero-skip-installed-and-viewer-checks).

The fresh [SpicyGov vertical slice](docs/local-spicygov-slice.md) adds exact flat multi-file Parquet admission and a bounded local SQL consumer over pinned catalog versions. Its source and real browser checks have their own evidence; the installed SDK4 results above remain tied to their original source. Public/remote serving, native recovery and production cold-read acceptance remain open. SpicyGov now uses the generic DDK viewer through theme and operator configuration. Horizontal work is paused for user review.

The [prioritized work backlog](docs/work-backlog.md) owns the remaining delivery order and canonical tickets. All new application work is greenfield, driven by real consumers alongside shared development, with performance, quality and transparency first. The review's cold-read, isolation, acquisition, publication, serving, coverage and lineage gaps now have explicit owners. Frozen release requirements need an explicit scope revision before removal. The tested SDK4 wheel exists; current qualification, portable handoff and publication remain separate tasks. Earlier SDK3 claims retain their identities.

**Historical SDK3 qualification, November 7, 2026.** Package `0.1.0.dev6+integrated.3` passed all 13 supported profiles, including DocSpec execution, managed recovery, catalog APIs, DCAT and OpenLineage. All 266 required case/profile checks passed. The [SDK3 package guide](docs/local-release-integrated-3.md) identifies that source, wheel, native executable and retained results. The following SDK3 paragraphs preserve that historical scope.

One fresh installed run passed 703 tests with zero failures, errors or skips. Separate offline-core API, CLI and lock checks also passed. The connected commerce workflow exercises staging, SQL, saved Substrait, output quality and a catalog-bound reader. Source declarations remain experimental. The five generated adapter manifests qualify with their admitted evidence. Earlier SDK2 results retain their original skipped outcomes and supplemental evidence.

The [portable SDK3 archive](docs/local-release-integrated-3.md#portable-package) also passes fresh core/full/native installation, evidence relocation and four fresh connected-workflow cases on macOS arm64. The original 703-test qualification travels with the package unchanged.

DocSpec owns execution, durable phases, source access, retained inputs, recovery, accepted quality evidence and guarded selection. The SDK3 native tuple passed 1,011 Rust and 31 Dagster tests, with 17 explicitly ignored Rust cases retained. A separate synthetic S3 fixture proves recovery after an input-read failure and offline acceptance; installed SDK2 calls recover that same accepted candidate. [SDK3 verification](docs/verification.md#november-7-2026-sdk3-complete-installed-qualification).

SDK3 also supports explicit host-owned process groups. Nine POSIX process probes passed both from source and installed, alongside the existing transport checks. These probes use stand-ins and preserve uncertain native execution after timeout. [Process evidence](docs/verification.md#november-7-2026-host-process-ownership).

Congress's [original eight-table source proof](docs/verification.md#november-7-2026-congress-retained-source-proof) separately passed against retained archive snapshots. Fresh official-source checks, application publication and the complete Congress and SpicyRegs replacements remain separate work. The reusable React/Astro viewer has its own acceptance record. The [dev2 portable archive](docs/local-release.md) and older package results retain their original identities. No hosted release has been published.

**Layered data maps, integrated on main.** Aggregator projects, shared imports loaded once, `layer-order` and `view-sources` policies, ODCS primary-key row identity, dataset origin, remote definition references and descriptive catalog fields are implemented. Recipe checks now use DocSpec preparation and zero-row execution; the earlier sqlglot/signature-table binder is retired. DocSpec job productions are implemented. [ADR-015](docs/architecture-decisions.md#adr-015--keep-ddk-to-the-evidence-bound-catalog) defines the catalog boundary, and `ddk catalog` refuses `--lock` and `--locked`. The [November 8 checks](docs/verification.md#november-8-2026-layered-data-map-source-checks) retain their original results; the November 13 installed checks cover the current code without expanding SDK3's qualification.

**Knowledge graph, integrated on main.** Both exports are implemented and covered by the current installed suite; the original [November 9 evidence](docs/verification.md#november-9-2026-knowledge-graph-and-rml-exports) remains historical.

- `--export graph` (DDK-CATALOG-013) writes the catalog as one JSON-LD graph, or Turtle with `graph.ttl`: DCAT 3 plus PROV-O, DQV, VoID and SKOS, using the small vocabulary in [vocab/ddk.ttl](vocab/ddk.ttl). Its run and check sections show only what the metadata records: a definition-only build such as SpicyRegs today has datasets, fields, links and concepts, but no versions, runs or checks.
- `--export rml` (DDK-CATALOG-014) writes YARRRML mappings that Morph-KGC 2.10.0 runs on the commerce example and on real SpicyRegs slices. Each document binds one exact version, chosen by `--current-selection` or because it is the dataset's only one; otherwise it is a template that claims no version. DuckDB views cover nested fields, array items, rows without a key, composite and non-key joins within their release scope, and declared match-decision tables.
- Not yet mapped: arrays of arrays, arrays inside array items, external targets and `project_rule` relationships.
- Origins split `derived` into `rule` and `human`; `derived` is still read but reported as unknown detail. Model datasets carry a method record, which DDK states as a declaration and does not verify. A declared method column attributes each row; its values are origins or finer methods mapped to one.
- Shared definitions become concepts. They are listed in the catalog, checked across relationship joins (a warning by default, an error by the declaring project's policy), unified in the graph and mappings through `rdfs:subPropertyOf`, and offered as inferred candidate joins kept apart from declared links.
- Implemented in source (November 11, 2026): the single-engine `DocSpec` recipe SQL gate (DDK-CATALOG-011, WP-15 item 3, retiring `sqlglot`), `kind: "job"` catalog productions and run binding (DDK-CATALOG-012, WP-15 item 8), ODCS zero-counter SQL lowering (`odcs_sql_counters.py`), and `256 MiB` DuckDB quality scratch with batched `odcs-lint`. Remaining specified-only items in [WP-15](docs/implementation-plan.md#wp-15--layered-data-map-extensions-specified-not-implemented): edition series, pinned status vocabulary, definitions-only qualification, and deduplicating the vendored ODCS 3.2.0 schema.

Data Design Kit (DDK) generates an evidence-bound catalog from maintained ODCS and ODPS definitions: exact versions, access methods, relationships, origin and check evidence, with `unknown` and `not_run` kept explicit. Transformations are SQL files that run as DocSpec job steps; DDK reads their declarations and run records ([ADR-015](docs/architecture-decisions.md#adr-015--keep-ddk-to-the-evidence-bound-catalog)). Its earlier design, transformation-test and change-impact checks remain available but frozen. The adopted [build strategy](docs/build-strategy-without-pilots.md) connects local commerce inputs, real execution and quality receipts, and a generated catalog reader. Nested/scoped identities and one typed managed operation have separate acceptance cases. Full DDK stack replacements for SpicyRegs and congressional-tech remain separate, incomplete delivery work.

The first product release requires ODPS product definitions, ODCS dataset definitions, DCAT 3 discovery, OpenLineage job and run events, and a qualified Substrait execution path through DocSpec. It also includes SQL and fixture tests, supported ODCS output checks, and change analysis. Native systems supply the records of capture, computation, retention, and publication.

## Read the design

- [Engineering specification](docs/specification.md): normative requirements, formats, algorithms, profiles, and conformance.
- [Implementation plan](docs/implementation-plan.md): work packages, dependencies, acceptance criteria, release gates, and risks.
- [Prioritized work backlog](docs/work-backlog.md): active owner tickets, delivery dependencies, deferred decisions and preserved completion.
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
- [Historical qualified SDK3 package](docs/local-release-integrated-3.md): exact SDK3 and DocSpec identities, supported profiles, use and remaining limits. The [SDK2 guide](docs/local-release-integrated-2.md), [dev6 catalog increment](docs/local-release-dev6.md), [dev5 full-profile package](docs/local-release-dev5.md) and [dev2 portable guide](docs/local-release.md) retain their earlier results. Current release work is tracked in the backlog.
- [Commerce catalog example](examples/commerce/catalog/README.md) and [draft catalog schema](schemas/0.1/catalog.schema.json) show the product, discovery, lineage, and evidence formats.

The specification follows the structure of a W3C technical report. This is an independent engineering draft, not a W3C publication or standards-body endorsement. “Data Design Kit” and `ddk` are working names.

## What is present

This repository contains specifications, format schemas, independently authored examples and tests, upstream provenance, and the DDK source implementation. Build tooling, environments, dependency installations, and generated outputs remain outside the repository. The verification record identifies the exact code and dependencies covered by each qualification claim.

The integrated architecture separates domain rules, application use cases, and adapters. Native references preserve their original identity schemes. Check outcomes remain separate from uncertain runtime outcomes. The local demonstrations execute saved Substrait and exercise one typed managed quality gate; each claim remains bound to its tested dependency tuple. DocSpec is team-owned and unreleased; its API may change to support the design.

[`viewer/`](viewer/README.md) holds a React/Astro catalog viewer that reads any DDK catalog. It is a separate application with its own pinned Node toolchain, not part of the Python package.

The repository pins the ODCS schema correction and retains its published comparison snapshot. It also vendors the released ODPS and OpenLineage schemas used by the examples. Exact revisions, licenses, and digests are recorded in [PROVENANCE.md](PROVENANCE.md).

## Verification

The [implementation status](docs/implementation-status.md) documents the commands and current runtime evidence. The [verification record](docs/verification.md) separates earlier documentation checks from native execution and conformance tests. Build environments, test outputs, and local distributions remain outside the repository.

The [current portable package guide](docs/local-release-integrated-3.md#portable-package) links the archive, pinned dependency material, installation instructions and platform limits. The [dev2 portable guide](docs/local-release.md) and [dev1 record](docs/local-release-dev1.md) preserve earlier captures separately.

## License

Original material is licensed under Apache-2.0. Vendored material retains the attribution recorded in [NOTICE](NOTICE) and [upstream-artifacts.json](docs/upstream-artifacts.json). The local release includes dependency locks, software bills of materials, and native dependency notices.
