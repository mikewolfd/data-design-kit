# Connecting a catalog owner

The application composition root selects local catalog registrations and explicitly supported owner readers. A registration supplies a stable navigation ID, an allowlisted directory, an exact external `catalog.lock.json` SHA-256, and fixture/application mode. It does not supply replacement dataset definitions. Never accept directories, URLs, SQL, or a runtime executable from an HTTP request.

Application metadata snapshots under `fixtures/applications/` retain their exact standard bytes and capture receipts; no application payload files are included. The navigation list reads no catalog bytes. The top-level snapshot API omits a duplicate copy of effective definitions: React resolves those directly from the assembly extension.

The standard lock output inventory binds `catalog.ddk.json`, `catalog.report.json` and all admitted companions. The loader verifies catalog and report bytes, matching inventories, audience and supported structural invariants. Other companions are fetched and verified when requested. Full DDK semantic admission remains the producer's responsibility. A self-consistent digest proves byte identity, not meaning, source completeness or qualification.

Public mode refuses internal catalogs. It does not try to reconstruct disclosure by deleting a few fields. The source must already be an admitted public result, including audience-safe diagnostics. The public view may contain partial field definitions or withheld assessments. Preserve those limits. Public report fields are safe to display only under the producer's disclosure guarantees.

## Data and query boundary

`CatalogAccess` accepts explicitly injected `OwnerReader` and `OwnerQuery` adapters. The adapter receives the admitted snapshot, exact dataset/version/representation/release binding, row limit, bounded offset or exact recipe parameters and verified SQL bytes. Resolve native scheme, authority, opaque version, view/group/table, schema interpretation and field identities before reading. Do not export/reimport a native dataset just to return browser rows.

An owner can provide `hasMore` without a total. The viewer issues the next bound cursor without demanding a count scan. If both total and continuation evidence are absent, it displays continuation as unknown instead of asserting the dataset ended.

Return exact typed values using the transport helpers. A read result must identify the exact consumed binding and owner evidence record, retain physical row positions, obey the requested limit and byte budget, and make progress on every non-final page. Query results must retain exact bindings and a receipt naming the recipe and consumed SQL digest. The viewer validates these at the transport boundary; it cannot establish that an untrusted adapter physically read the claimed inputs.

A new adapter must qualify its native mappings with independent expected values, including unsafe integers, decimal scale, timestamp units/timezones, binary widths, nullability, nested/list occurrence context, schema/field IDs, exact version mismatch, last-page failure and cancellation. Metadata-only admission does not meet that requirement. Generic filtering is explicitly refused for owner adapters until supported; the synthetic reader implements the tested scalar/list equality subset.

Owner adapters receive an AbortSignal and an absolute deadline. A timeout returns unknown and requests cancellation. Two outstanding owner slots bound uncooperative asynchronous adapters; a timed-out slot stays occupied until its work settles. The viewer cannot prove that external/native work stopped. Generic owner totals and physical offsets support nonnegative safe integers; the 10,000-row materialization cap applies only to the fixture reader.

Owner operations remain read-only here. A later operator action must call the actual owner under its original operation identity and retain uncertain outcomes. It must not create a second journal, select a release, infer a completed operation after a timeout, or retry a side effect under a new identity.

## Endpoints

| Route | Purpose |
| --- | --- |
| `GET /api/catalogs` | Configured catalog choices and scoped unavailable-source diagnostics |
| `GET /api/catalogs/:id` | One exact admitted snapshot with definitions, report, lock and explicit reader capabilities |
| `POST /api/read` | Bounded page for exact catalog/dataset/version/representation and optional release/filter/cursor |
| `POST /api/query` | Explicit recipe, exact execution inputs, parameter values and optional complete release |
| `GET /api/companion` | Requested admitted companion bytes, verified against exact inventory; no arbitrary path traversal |
| `GET /api/impact` | Registered owner analysis bound to exact base/candidate/report; explicit unavailable otherwise |

POST input/output types are exported from `src/domain/types.ts`. Numeric parameter values use exact numeric tags or the declared string type. The recipe form supports either one complete release or explicit exact versions, and asks for a representation when more than one is available. Unsupported required external/declared relationship resolution remains unknown before owner execution. `parameterOrder` determines presentation order; never infer positional order from `required`. `contextualRelationships` remain explanatory and never add unread endpoints to `bindings`.

Selection records are not sorted by time to choose “latest.” Only one applicable authority/purpose selection and one dataset version permit an automatic default. Explicit historical versions retain their original release context. Same-release relationships and queries resolve complete exact membership before use. Disjoint selections under one selector are valid; competing selections for the same dataset are ambiguous.

## Work and retention limits

The implementation declares separate limits: 8 MiB per catalog control file, 64 listed output files, 8 configured sources, at most 2 retained parsed catalog sets and 32 MiB of retained wire/serialized-metadata accounting, 64 KiB request bodies, 256 KiB read/query results, at most 100 requested rows, and 8 concurrent API requests. Control/row reads and request bodies have deadlines. The fixture reader alone may parse up to 10,000 rows from a small pinned JSON file; it is not the native scalability path.

These accounting limits are not a measured JavaScript heap or whole-process RSS guarantee. Parsed objects, active responses and concurrent calls add overhead. Native adapters own their own memory, read, scan, timeout and cancellation budgets. A row limit alone does not bound scanned bytes or guarantee streaming.

The browser retains only the active snapshot and task state, with no localStorage, IndexedDB, service worker, persistent row cache or automatic prefetch. Incoming catalog responses are capped at 16 MiB, SQL previews at 1 MiB, and page/reference downloads at 1 MiB. Blob URLs are revoked. Switching exact contexts aborts requests, stale responses cannot overwrite the new task, and failures retain filters/parameters for retry. Server catalog cache retirement releases both raw bytes and parsed metadata. Disposable build and test files stay in this application workspace.

## Impact reports

`src/server/impact.ts` consumes a registration binding an exact report and base snapshot to the current candidate digest. It verifies every selected artifact within one deadline and under 1 MiB each. The included example was produced by the supplied qualified DDK wheel; it is not a custom dependency algorithm. The report's `metadata.catalogChanges`, `catalogAffectedObligations`, `runtimeReuse` and unresolved scope are displayed without turning them into scheduler commands. Register another owner's immutable report through the same boundary.
