# Fresh SpicyGov vertical slice

The fresh application is [SpicyGov](/Users/mikewolfd/Work/spicygov/README.md), previously described in planning as the SpicyRegs replacement. It uses maintained source readers, authored definitions and SQL, native DocSpec jobs and the shared DDK catalog reader. The old SpicyGov and SpicyRegs repositories remain research and evidence sources.

The selected local journey follows one historical Regulations.gov docket, one rule and two comments through exact originals, normalized rows, native joins and quality checks, ODPS/DCAT/OpenLineage catalog output, and the existing generic DDK viewer with exploratory SQL. Independent expectations precede implementation. The [original vertical acceptance record](/Users/mikewolfd/Work/artifacts/spicyregs-fresh-slice-20261113/ACCEPTANCE.md) retains its pins, test results and limits. The [workflow repair acceptance record](/Users/mikewolfd/Work/artifacts/spicygov-workflow-fixes-20261113/ACCEPTANCE.md) separately records the repaired source/catalog identities, combined validation and user journeys; its evidence does not restamp the earlier installed package.

The new shared local capability admits an exact flat Parquet directory through `DocSpecAdapter.execute`, preserves the native inventory digest and every member in catalog observations, and exposes bounded read-only queries through `ddk.catalog_query.execute_catalog_sql`. Core checks and ordinary catalog assembly remain offline and do not scan payloads.

The independent nested-member case exposed a native limitation: the retained DocSpec reader can list nested members in its receipt while omitting their rows from a directory query. The bounded profile therefore refuses nested directories with `DOCSPEC-PARQUET-DIRECTORY-SCOPE`. This is an executed refusal, not a skipped test or nested-reading success. Preserve the original failing evidence and address complete nested/native/public reading under [ddk-citj](../.tickets/ddk-citj.md).

This scope does not close the application epic or serving ticket. Fresh acquisition and updates, complete required source families, managed selection/recovery, remote publication, remote/public HTTP and MCP disclosure, corpus-wide coverage, and measured cold-read performance remain open. Hashing every selected file still makes this bounded local path unsuitable as proof of [ddk-eu0k](../.tickets/ddk-eu0k.md).

**User-directed stop:** pause after the vertical slice and show the site. Horizontal source implementation resumes only after the user continues the work. Federal Register discovery is retained outside the application and is not an implemented second family.

## Generic viewer integration

SpicyGov supplies [theme configuration](/Users/mikewolfd/Work/spicygov/viewer/theme.json), source choices, definitions, SQL, guides and publisher workflow/action metadata. DDK owns the shared interface: configurable branding and design tokens, task entry, page-only search, the record reading pane, source-original inspection, recipes and the SQL lab. The separate application HTTP server and web files were removed. See [viewer themes](../viewer/docs/themes.md) and the [publisher extension profile](../viewer/docs/publisher-extension.md#record-lookups-and-follow-up-actions).

The root now starts with a publisher-defined docket lookup instead of the first internal table. Its exact retained inputs and text parameters come from the maintained catalog recipe and workflow declaration. Catalog-search misses lead to the supported record lookup; the user explicitly copies a searched identifier into the form. A no-match describes this selected cohort, and refused or unknown outcomes stay separate. Useful dataset and field descriptions, the collection guide and readable comment text remain publisher-owned metadata and normalization outputs.

Configured row actions carry the comment's complete declared text keys into the related rule lookup and match its original by publisher URI, native source version and retained-content digest. Missing or ambiguous source matches disable the action. A changed dataset version does not inherit another version's actions. This implemented text-key subset does not close arbitrary typed compound keys, other product journeys or full source-to-derived lineage under [ddk-pi9u](../.tickets/ddk-pi9u.md). The viewer renders readable fields as inert text and keeps the original source text available.

The workspace preserves drafts, input choices, returned pages, page search and selected records across tabs and dataset round trips. It keeps six recent data/query/related-data views in memory; catalog entry separately keeps six recent publisher lookups. Eviction is explained, refresh clears the session, and a changed catalog ID or catalog/report/lock identity clears incompatible tasks. Leaving a pending operation stops waiting without treating an unknown native outcome as non-execution.

Query lab separates non-destructive **Insert table name** from explicit **Start query** or **Replace with new query**, with undo for the replacement. It carries an explicitly selected compatible version/resource or requests one. The bounded, collapsible picker no longer pushes completed answers below all unused tables; result status and keyboard focus stay with completion below the editor.

Operator configuration enables the local SQL adapter explicitly. Browser requests contain SQL and exact dataset/version/representation bindings; they never choose executables or filesystem roots. The shared Python API composes maintained native schema preparation and execution. Schema-only preparation, actual input admission, execution and retained evidence remain distinct.

The bounded SQL output profile admits scalar text, integers, booleans and nulls. Native schema preparation refuses other output types before row execution: the retained native job JSON serializer can round decimals and collapse non-finite floats to null, including nested values. Explicit SQL casts to text preserve the full decimal text. Native typed row paging retains its separate exact-value transport. Complete typed SQL output remains under [ddk-citj](../.tickets/ddk-citj.md); no inaccurate value is admitted as a successful answer.

Catalog-wide original-source observations are inspectable by their exact URI and digest. They do not imply normalized-version lineage links absent from the native receipts. The UI keeps that limit visible.

Operator `retainReceiptsDir` retains native recipe receipts for inspection through the current owner's evidence access. Each owner instance uses a fresh subdirectory so worker-local counter names cannot overwrite prior receipt bytes after restart. Preserving those bytes does not automatically admit prior-owner receipts to a new owner's evidence allowlist. This is bounded evidence retention and current-owner access, not durable execution phases, reconciliation, managed selection or recovery.

## Requirement traceability

| Requirement | Independent checks |
| --- | --- |
| DDK-CATALOG-003: exact native meaning and members | `tests/test_docspec_directory_inputs.py`; directory cases in `tests/catalog/test_docspec_jobs.py` |
| DDK-CATALOG-007: pinned standard catalog artifacts | `tests/catalog/test_catalog_query.py`, including changed lock/version/root refusal |
| DDK-CATALOG-012: native job and output quality binding | `tests/catalog/test_docspec_jobs.py`; SpicyGov native build and quality checks |
| DDK-RESULT-006: uncertain execution remains distinct | Directory mutation and native receipt mismatch cases preserve unknown; known SQL failure and valid-empty cases remain distinct |

Shared-viewer workflow checks are maintained in [workflow-state.spec.ts](../viewer/tests/browser/workflow-state.spec.ts) and [publisher-workflows.spec.ts](../viewer/tests/browser/publisher-workflows.spec.ts). They cover bounded retention, SQL edits, completion, exact lookup keys, scoped empty/refused/unknown outcomes, inert text and missing/ambiguous/changed-version action targets. Their synthetic examples test the shared UI; the workflow acceptance record separately identifies actual SpicyGov/native journeys and receipt-retention checks. Final counts belong in that record.

These source tests establish the listed bounded behavior. They do not restamp the historical installed package or profile evidence; current package qualification remains with the release work.
