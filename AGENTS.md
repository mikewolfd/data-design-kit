# Project instructions

- This is a new implementation effort based on public standards and independently written requirements. Do not copy or import dcval/CareSet code, schemas, tests, examples, or documentation.
- Read `docs/specification.md` and the relevant implementation-plan work package before implementation.
- Keep document validation, declared compatibility, inferred plan properties, and executed tests distinct. A declaration is an assumption until stronger evidence exists.
- Preserve explicit `unknown` and `not_run` results. Required checks without sufficient evidence must prevent an overall passing result.
- Core checks must work offline without importing implementation modules, reading production rows, or selecting an execution engine.
- Reuse maintained upstream formats and libraries. Keep new formats limited to composition, interface bindings, policies, and reporting.
- Schema files are normative for document shape; the specification owns algorithms and semantics. Resolve inconsistencies before claiming conformance.
- Add independent conformance examples for new behavior. Never derive expected business results from the transformation under test.
- Keep `README.md` implementation status accurate. Documentation checks are not runtime tests.
- Keep this repository limited to deliverables. Keep build scripts, environments, dependency installations, workflows, and generated builds outside it.
- Verify schema shapes, links, provenance digests, and requirement traceability after document changes; record actual verification separately from planned runtime conformance.
- Keep changes within the current task. No publication, dependency upgrade, or production operation is implied by local implementation work.
