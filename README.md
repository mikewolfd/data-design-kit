# Data Design Kit

**Status: specification and implementation plan, November 4, 2026. No DDK runtime is implemented.**

Data Design Kit (DDK) is a proposed checker for reusable data designs. It checks calls to shared reader and transformation interfaces, dataset requirements, dependency relationships, project policies, and the effect of changes before implementations or an execution engine exist.

DDK uses ODCS for dataset definitions and JSON Schema for parameters. Optional integrations use Data Contract CLI, Frictionless, dlt, Substrait, DataFusion, and pytest. The new code owns connections among definitions, change impact, supported compatibility checks, and evidence reporting.

## Read the design

- [Engineering specification](docs/specification.md): normative requirements, formats, algorithms, profiles, and conformance.
- [Implementation plan](docs/implementation-plan.md): work packages, dependencies, acceptance criteria, release gates, and risks.
- [Adapter profiles](docs/adapter-profiles.md): exact boundaries for third-party integrations and proposed capability negotiation.
- [Architecture decisions](docs/architecture-decisions.md): decisions and alternatives behind the draft.
- [Research and references](docs/references.md): public sources, observed versions, licensing, and unresolved compatibility.
- [Conformance cases](conformance/cases.json): independently specified future runtime tests.
- [Delivery verification](docs/verification.md): checks actually performed and their limits.
- [Examples](examples/commerce/project.ddk.json) and [draft schemas](schemas/0.1/project.schema.json): machine-checked document examples.

The specification follows the structure of a W3C technical report. This is an independent engineering draft, not a W3C publication or standards-body endorsement. “Data Design Kit” and `ddk` are working names.

## What is present

This repository contains authored specifications, draft format schemas, examples, conformance expectations, and upstream provenance. It contains no DDK checker, compiler, ingestion runner, data-quality runtime, build tooling, or generated build directory. Example commands in the specification describe the proposed interface.

The ODCS 3.2.0 schema is vendored from a pinned public GitHub development commit that includes the combined-quality-operators correction. The published release snapshot is retained separately for comparison. Both have licenses and recorded digests. All other new project material was authored for this design. See [PROVENANCE.md](PROVENANCE.md).

## Verification

Delivery verification used separate tooling outside this repository. It checked schema syntax, example documents, local links, requirement traceability, conformance-case references, and vendored digests. It also checked the example SQL against independently authored expected rows in SQLite. These checks do not establish DDK or adapter runtime conformance. The [verification record](docs/verification.md) describes their scope.

## License

Original material is licensed under Apache-2.0. Vendored material retains the attribution recorded in [NOTICE](NOTICE) and [upstream-artifacts.json](docs/upstream-artifacts.json). The implementation plan requires version-specific dependency and notice checks before a runtime release.
