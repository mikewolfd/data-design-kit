# Connected commerce: one actual owner-backed read

The optional `commerce-native` catalog proves a bounded consumer journey through existing Data Design Kit (DDK) and DocSpec interfaces. The data comes from DDK's authored commerce example. Execution and evidence are real native outputs; the viewer does not substitute its synthetic row reader.

## Use the flow

```sh
npm run build
DDK_VIEWER_AUDIENCE=local DDK_VIEWER_APPLICATIONS=spicy-regs,congress,commerce-native npm run preview
```

Choose Connected commerce, then `daily_revenue`, and explicitly select the recorded version. The catalog retains its publisher selection, but requests no `currentSelection` selector. The viewer therefore leaves current-selection assessment unknown and requires an explicit version choice. Open Data to read all three rows. Open Connections, choose the complete `urn:test:reference:release` for `checked-revenue`, and run the query. Exports preserve the exact binding, tagged numeric values and new native receipt reference.

Evidence shows 13 retained quality observations bound to this version. Inspect their exact owner record from the Evidence view. Activity opens the original saved-plan execution receipt; Data and Connections open receipts from the new consumer calls. Coverage and run input coverage remain unknown where the source says unknown. Managed native acceptance remains unestablished.

This is a local catalog with local file paths. Public mode refuses it. The other commerce datasets and transformation recipe remain visible as definitions but have no connected execution controls.

## Inputs and processing

The integration uses the unchanged catalog, report, lock and SQL from the qualified dev4 connected-workflow case, plus its retained `run/substrait-result.parquet`: 877 bytes and three rows, with SHA-256 `ff0efd8f35eb3b64e23a2f195cbfd2c9989173020b4681ae783bc0f2301ba4c6`.

The original version is `urn:ddk:file-version:737bacee2ec6b3ada9d212f8206e4905647dc155ff71433646a645054d6a8e50`. Catalog SHA-256 is `c323123b5bfc65c23c2fd2710dcbf6c02fdd5ae1f0f351fc9ba30d31e958ae83`; lock SHA-256 is `b36d8196f9eefa332f2580bcfd3684bbf7f94506fab0e2cc2064e4f23ef34c2d`.

The Python bridge calls maintained `ddk.catalog_access.run_checked_query`, then `DocSpecAdapter.execute`, with the exact checked SQL and sole retained Parquet input. The native request has no transformation steps or data outputs and requests no selection or publication. It uses the qualified dev4 installed package and unchanged dev2-qualified native executable from the supplied handoff. Native tool and result paths remain pinned; no dependency rebuild, source update, staging, transformation or quality rerun occurs.

The existing recipe has no `ORDER BY`. This integration returns the complete three-row result and refuses offsets or limits below three. Record numbers describe returned query positions, not physical Parquet ordinals or a stable pagination promise. Generic filtering is unsupported.

Capture receipts under `fixtures/applications/commerce-native/` retain original metadata locations and byte identities. Native data and binaries remain at their owner locations. The source archive contains references and small metadata/evidence copies, not a new native installation.

## Results and checks

| Order day | Region | Amount in cents |
| --- | --- | ---: |
| 2026-01-05 | north | 1700 |
| 2026-01-05 | south | 500 |
| 2026-01-06 | north | 250 |

The viewer preserves the original dataset, version, representation, release, SQL digest and result-file digest. Each new consumer call has its own DocSpec request identity and receipt. The receipt identifies the exact consumed file, native tool and execution outcome. It does not replace the original result version or quality evidence.

The retained DDK workflow compared its real native consumer result with independently authored expected rows. New integration tests check actual reads and recipe execution, identities, numeric transport, out-of-scope refusal, local audience enforcement, incorrect evidence references and retained evidence lookup. Browser tests exercise the same actual flow, exports, quality inspection and all six views at desktop and mobile widths.

Admission also supports multiple legitimate lock entries selecting different objects from one source file. It requires a consistent digest for that path and preserves every selection. This removes a false refusal without rewriting the owner's lock or catalog.

## Limits and retained evidence

The viewer permits one commerce bridge at a time, at most 32 retained attempts, and a 16 MiB retained-evidence admission budget with post-operation accounting. Native scratch and configured native memory limits are separate; these are not whole-process memory or disk guarantees. Stdout, stderr, evidence and API results have separate byte limits. The maintained adapter hashes its approximately 395 MB executable on initialization, so an 877-byte payload does not imply 877 bytes of total I/O.

Attempts and receipts stay under `work/native-consumer/`. The adapter refuses more work when its finite quotas are reached and preserves success and failure evidence. A submitted-attempt record identifies the viewer request before execution and makes no consumption claim. Timeouts retain that reference, request cooperative cancellation and allow bounded cleanup time. A hard stop leaves the native outcome unresolved and prevents another bridge in that process. Browser “Stop waiting” ends the response wait and does not establish that native work stopped. No lifecycle or recovery controller is added.

The completed scope is one exact local-file consumer flow. It does not qualify managed-table access, managed Update, streaming quality, retained multi-output execution, complete native candidate acceptance or publication recovery. Those remain with the actual owners.
