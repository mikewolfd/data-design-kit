# Fresh SpicyGov vertical slice

The fresh application is [SpicyGov](/Users/mikewolfd/Work/spicygov/README.md), previously described in planning as the SpicyRegs replacement. It uses maintained source readers, authored definitions and SQL, native DocSpec jobs and the shared DDK catalog reader. The old SpicyGov and SpicyRegs repositories remain research and evidence sources.

The selected local journey follows one historical Regulations.gov docket, one rule and two comments through exact originals, normalized rows, native joins and quality checks, ODPS/DCAT/OpenLineage catalog output, and the existing generic DDK viewer with exploratory SQL. Independent expectations precede implementation. The [external acceptance record](/Users/mikewolfd/Work/artifacts/spicyregs-fresh-slice-20261113/ACCEPTANCE.md) owns final pins, actual test results and limits.

The new shared local capability admits an exact flat Parquet directory through `DocSpecAdapter.execute`, preserves the native inventory digest and every member in catalog observations, and exposes bounded read-only queries through `ddk.catalog_query.execute_catalog_sql`. Core checks and ordinary catalog assembly remain offline and do not scan payloads.

The independent nested-member case exposed a native limitation: the retained DocSpec reader can list nested members in its receipt while omitting their rows from a directory query. The bounded profile therefore refuses nested directories with `DOCSPEC-PARQUET-DIRECTORY-SCOPE`. This is an executed refusal, not a skipped test or nested-reading success. Preserve the original failing evidence and address complete nested/native/public reading under [ddk-citj](../.tickets/ddk-citj.md).

This scope does not close the application epic or serving ticket. Fresh acquisition and updates, complete required source families, managed selection/recovery, remote publication, remote/public HTTP and MCP disclosure, corpus-wide coverage, and measured cold-read performance remain open. Hashing every selected file still makes this bounded local path unsuitable as proof of [ddk-eu0k](../.tickets/ddk-eu0k.md).

**User-directed stop:** pause after the vertical slice and show the site. Horizontal source implementation resumes only after the user continues the work. Federal Register discovery is retained outside the application and is not an implemented second family.

## Generic viewer integration

SpicyGov supplies [theme configuration](/Users/mikewolfd/Work/spicygov/viewer/theme.json), source choices, definitions and SQL. DDK owns the shared interface: configurable branding and design tokens, page-only search, the record reading pane, source-original inspection, recipes and the SQL lab. The separate application HTTP server and web files were removed. See [viewer themes](../viewer/docs/themes.md).

Operator configuration enables the local SQL adapter explicitly. Browser requests contain SQL and exact dataset/version/representation bindings; they never choose executables or filesystem roots. The shared Python API composes maintained native schema preparation and execution. Schema-only preparation, actual input admission, execution and retained evidence remain distinct.

The bounded SQL output profile admits scalar text, integers, booleans and nulls. Native schema preparation refuses other output types before row execution: the retained native job JSON serializer can round decimals and collapse non-finite floats to null, including nested values. Explicit SQL casts to text preserve the full decimal text. Native typed row paging retains its separate exact-value transport. Complete typed SQL output remains under [ddk-citj](../.tickets/ddk-citj.md); no inaccurate value is admitted as a successful answer.

Catalog-wide original-source observations are inspectable by their exact URI and digest. They do not imply normalized-version lineage links absent from the native receipts. The UI keeps that limit visible.

## Requirement traceability

| Requirement | Independent checks |
| --- | --- |
| DDK-CATALOG-003: exact native meaning and members | `tests/test_docspec_directory_inputs.py`; directory cases in `tests/catalog/test_docspec_jobs.py` |
| DDK-CATALOG-007: pinned standard catalog artifacts | `tests/catalog/test_catalog_query.py`, including changed lock/version/root refusal |
| DDK-CATALOG-012: native job and output quality binding | `tests/catalog/test_docspec_jobs.py`; SpicyGov native build and quality checks |
| DDK-RESULT-006: uncertain execution remains distinct | Directory mutation and native receipt mismatch cases preserve unknown; known SQL failure and valid-empty cases remain distinct |

These source tests establish the listed bounded behavior. They do not restamp the historical installed package or profile evidence; current package qualification remains with the release work.
