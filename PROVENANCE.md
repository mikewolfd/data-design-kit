# Authorship and upstream provenance

## Scope

This repository began on November 4, 2026 as a new specification effort. Its functional goals come from the user's requirements: reusable data designs, shared interface maintenance, explicit validation coverage, standards interoperability, and optional transformation execution.

The repository includes no copied dcval/CareSet implementation, schemas, tests, examples, or documentation. The new examples use independently specified commerce data. Requirement identifiers, document formats, algorithms, diagnostics, and conformance cases were authored for this project. Prior discussion is requirements context, not a source license. Build and verification tooling is maintained outside this deliverables repository.

This record describes the materials included here. It does not claim that the authors followed a formal isolated clean-room process.

## Public upstream material included

`vendor/odcs/3.2.0/odcs-json-schema.json` and its sibling `LICENSE` come from Bitol's public Open Data Contract Standard development commit `448f7b93329ece7827897d7dd51e827a3e279460`. This revision fixes combined quality operators in the 3.2.0 schema. The original `v3.2.0` release files remain in `vendor/odcs/3.2.0-release/` as comparison evidence. Exact source URLs, upstream Git blob identifiers, retrieval date, and SHA-256 digests are in `docs/upstream-artifacts.json`.

The root `LICENSE` contains the standard Apache License 2.0 text. The original public license text is not a project-specific implementation.

## Requirements for future contributions

New contributions must identify the public standard or independently written requirement that motivates behavior. Copied third-party material must have an identified source, version, permitted license, and required notices. A change of filename, package name, or license header is not independent authorship.

Dependency metadata is preliminary evidence. A runtime release must inspect the actual pinned distributions, bundled files, transitive dependencies, and required notices. Unimplemented integration plans do not imply compatibility or redistribution permission for arbitrary versions.
