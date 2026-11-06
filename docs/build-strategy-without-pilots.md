# DDK build strategy without pilots

**Date: November 5, 2026. Status: adopted implementation route; implementation and qualification are in progress.**

Build the full Data Design Kit (DDK) stack through four parallel implementation tracks, integrated through one local reference workflow. Remove pilot preparation, project-specific consumer adapters, and adoption demonstrations from the build dependencies. The scope includes core checking and impact analysis, catalogs and standards outputs, SQL and saved Substrait execution, data-quality checks, file intake, ingestion, and one managed operation/backend.

The largest scheduling change is to let execution, quality, and ingestion develop alongside impact analysis. The [adopted dependency graph](implementation-plan.md#4-dependency-order-and-milestones) lets them develop against explicit inputs and shared result types while the core checks progress. Complete prerequisite checks still gate integrated execution and qualification.

## Shared foundation

Start with document loading, resolved definitions, exact input references, result records, the decision reducer, and adapter interfaces. Reuse the existing schemas and independently authored [commerce fixtures](../examples/commerce/README.md). Begin the DocSpec feasibility work immediately alongside this foundation.

Move input inventories and evidence identities into this foundation so adapters can produce reproducible receipts before impact analysis is complete. Preserve explicit `unknown` and `not_run` outcomes as capabilities are implemented.

## Parallel implementation tracks

| Track | Deliverable | Current work packages |
| --- | --- | --- |
| Core and change analysis | Interface checks, dataset compatibility, graphs, policies, locks, and impact analysis | WP-01 through WP-06 |
| Execution and managed operations | SQL preparation, saved Substrait execution, receipts, and exact native reads; then one managed operation/backend with accepted quality evidence and recovery | WP-00B, WP-09A, WP-09B, WP-12 |
| Quality, intake, and fixtures | Data Contract CLI checks, Frictionless validation, dlt staging, and independently expected result comparisons | WP-07, WP-08, WP-10 |
| Catalog and standards | Open Data Product Standard (ODPS) resolution, catalog assembly, Data Catalog Vocabulary (DCAT) discovery, OpenLineage records, and exact-version access | WP-13, WP-14 |

For the catalog track, implement a small local metadata adapter that consumes the reference workflow's actual execution and quality receipts. This supplies an integration target without congressional-tech or SpicyRegs dependencies. Use Open Data Contract Standard (ODCS) dataset definitions across the checker, quality evaluator, and catalog.

Integrate working capabilities into the reference workflow as they become available. Shared records and explicit interfaces let each track progress without waiting for every command or diagnostic to be complete.

## Local reference workflow

1. Validate and stage local fixture inputs.
2. Check their definitions and transformation interfaces.
3. Execute SQL, save Substrait, and execute the saved bytes.
4. Compare both results with independently authored expected rows.
5. Run quality checks against the exact output.
6. Generate the catalog, DCAT, and OpenLineage records from those receipts.
7. Resolve an exact version through the generated catalog and run a checked query.
8. Change a definition and verify the resulting impact and requalification requirements.

Add a small nested-data fixture for scoped identities and relationship paths. Retain negative cases for wrong versions, incomplete keys, and missing required evidence.

Exercise managed qualification separately using one existing typed DocSpec operation. Include stale evidence, lost responses, and guarded selection. Ordinary SQL jobs retain their bounded-execution meaning. The [runtime design](runtime-integration.md#managed-quality-gated-path) defines the separate managed responsibilities and exact-native quality-access requirement.

## Adopted dependency changes

- Remove WP-00A and WP-15 from implementation and release dependencies.
- Move input inventories and evidence identities early; let impact analysis follow.
- Make WP-07, WP-08, and WP-09A depend on the shared foundation.
- Start managed integration when execution and quality interfaces are usable. Qualification still requires demonstrated exact-native access and accepted evidence.
- Replace pilot-specific acceptance with the local reference workflow and conformance evidence. Synchronize the specification, work-package registry, conformance cases, and implementation status when adopting the change.

The governing [DDK-TEST-004 requirement](specification.md#DDK-TEST-004) and work-package registry now use the connected local demonstration. The first-release profile matrix remains separate from the additional intake and managed-operation capabilities required to complete this strategy.

## Completion and schedule risks

Use JSON, structured subprocesses, and one qualified DocSpec/backend combination initially. Complete every claimed profile's conformance cases, verify clean installation and reproducibility, and retain the required failure and uncertainty behavior before declaring the stack finished. Standalone Substrait validation and second-engine portability need their own tested combinations; agreement between engines does not replace independent expected results.

Saved-plan execution and exact-native quality acceptance are the likely schedule drivers. Test both uncertainties immediately and preserve the resulting evidence for integration and qualification.
