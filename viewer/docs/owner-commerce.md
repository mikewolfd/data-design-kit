# Connected commerce: one actual owner-backed read

The optional `commerce-native` catalog proves a bounded consumer journey through existing Data Design Kit (DDK) and DocSpec interfaces. The data comes from DDK's authored commerce example. Execution and evidence are real native outputs; the viewer does not substitute its synthetic row reader.

## Use the flow

```sh
npm run build
DDK_VIEWER_AUDIENCE=local DDK_VIEWER_APPLICATIONS=spicy-regs,congress,commerce-native npm run preview
```

Choose Commerce example, then Daily revenue by date and region, and explicitly select the recorded version. The catalog retains its publisher selection, but requests no `currentSelection` selector. The viewer therefore leaves current-selection assessment unknown and requires an explicit version choice. Open View data to read all three rows. Open Related data, choose the complete `urn:example:commerce:release:copy-refresh-20261106` for Read the saved daily revenue result, and run the query. Exports preserve the exact binding, tagged numeric values and new native receipt reference.

Checks & sources shows 13 retained quality observations bound to the current definition-bound version. History opens the original saved-plan execution receipt; View data and Related data open receipts from individual consumer calls. Coverage and run input coverage remain unknown where the source says unknown. Managed native acceptance remains unestablished.

This is a local catalog with local file paths. Public mode refuses it. The other commerce datasets and transformation recipe remain visible as definitions but have no connected execution controls.

## Preserved original evidence

The current metadata uses version `urn:ddk:file-version:667e1cdb71e36ebef8639a894100bcc50d3ab83bc4c02f18ab2e3f9a6f71eb24` and release `urn:example:commerce:release:copy-refresh-20261106`. Its catalog SHA-256 is `932e5d622d142f36d25d00f3b2ed8597fc10056a7818d8ab5e6c56c7283d0cfe`; its lock SHA-256 is `efd61cc7f5de0fec81fec7f4750805030e21dbfa6d6ffeb7393dc56bc4504f82`. This refreshed metadata was assembled with DDK catalog dev5 and local metadata adapter 0.1.1. It does not change the reader's qualified dev4/dev2 execution tuple.

The original integration used the catalog, report and lock from the qualified dev4 connected-workflow case. Those controls remain archived. The current integration retains its SQL and `run/substrait-result.parquet`: 877 bytes and three rows, with SHA-256 `ff0efd8f35eb3b64e23a2f195cbfd2c9989173020b4681ae783bc0f2301ba4c6`.

The original version is `urn:ddk:file-version:737bacee2ec6b3ada9d212f8206e4905647dc155ff71433646a645054d6a8e50`. Catalog SHA-256 is `c323123b5bfc65c23c2fd2710dcbf6c02fdd5ae1f0f351fc9ba30d31e958ae83`; lock SHA-256 is `b36d8196f9eefa332f2580bcfd3684bbf7f94506fab0e2cc2064e4f23ef34c2d`.

The Python bridge calls maintained `ddk.catalog_access.run_checked_query`, then `DocSpecAdapter.execute`, with the exact checked SQL and sole retained Parquet input. The native request has no transformation steps or data outputs and requests no selection or publication. It uses the qualified dev4 installed package and unchanged dev2-qualified native executable from the supplied handoff. Native tool and result paths remain pinned; no dependency rebuild, source update, staging, transformation or quality rerun occurs.

The existing recipe has no `ORDER BY`. This integration returns the complete three-row result and refuses offsets or limits below three. Record numbers describe returned query positions, not physical Parquet ordinals or a stable pagination promise. Generic filtering is unsupported.

Capture receipts under `fixtures/applications/commerce-native/` retain original metadata locations and byte identities. Native data and binaries remain at their owner locations. The source archive contains references and small metadata/evidence copies, not a new native installation.

## Results and checks

| Order day | Region | `amount_cents` (stored integer) |
| --- | --- | ---: |
| 2026-01-05 | north | 1700 |
| 2026-01-05 | south | 500 |
| 2026-01-06 | north | 250 |

The publisher does not establish currency or scale for these stored values. The viewer preserves the selected catalog's dataset, version, representation and release, together with the unchanged SQL and result-file digests. Each new consumer call has its own DocSpec request identity and receipt. The receipt identifies the exact consumed file, native tool and execution outcome. Current and original definition-bound versions remain separately recorded.

The retained DDK workflow compared its real native consumer result with independently authored expected rows. Recorded native acceptance covers actual reads and recipe execution. Routine tests now check retained identities, exact numeric transport, refusal, audience enforcement and evidence lookup; browser tests replay the retained responses for interface, export and responsive checks. Fresh native acceptance is opt-in through `DDK_VIEWER_RUN_NATIVE_ACCEPTANCE=1` and was not run during this handoff.

The retained Commerce tests still need the original owner Parquet at its pinned path and receipt files under `work/native-consumer/`. Small copies in the evidence archive's `outputs/publisher-commerce-evidence/` preserve custody, but the runtime does not load them as a replacement allowlist. A fresh checkout alone therefore does not reproduce the complete Commerce test environment.

Admission also supports multiple legitimate lock entries selecting different objects from one source file. It requires a consistent digest for that path and preserves every selection. This removes a false refusal without rewriting the owner's lock or catalog.

## Limits and retained evidence

The viewer permits one commerce bridge at a time, at most 36 retained attempts, and a 16 MiB retained-evidence admission budget with post-operation accounting. The content update increased the attempt limit from 32 to 36 to retain four additional test receipts and restore the four request slots those tests consumed. At that adjustment, 32 attempts occupied 229,132 bytes across 256 files; no evidence was deleted. Native scratch and configured native memory limits are separate; these are not whole-process memory or disk guarantees. Stdout, stderr, evidence and API results have separate byte limits. The maintained adapter hashes its approximately 395 MB executable on initialization, so an 877-byte payload does not imply 877 bytes of total I/O.

Attempts and receipts stay under `work/native-consumer/`. The adapter refuses more work when its finite quotas are reached and preserves success and failure evidence. A submitted-attempt record identifies the viewer request before execution and makes no consumption claim. Timeouts retain that reference, request cooperative cancellation and allow bounded cleanup time. A hard stop leaves the native outcome unresolved and prevents another bridge in that process. Browser “Stop waiting” ends the response wait and does not establish that native work stopped. No lifecycle or recovery controller is added.

The completed scope is one exact local-file consumer flow. It does not qualify managed-table access, managed Update, streaming quality, retained multi-output execution, complete native candidate acceptance or publication recovery. Those remain with the actual owners.

## Publisher copy refresh

The publisher-copy refresh regenerates Commerce metadata from the maintained example definitions. It preserves the original 877-byte revenue Parquet, SQL and saved-plan bytes, original execution receipts, and earlier viewer receipts. Source staging and quality receipts were refreshed against the revised definition bytes; the revenue calculation was not rerun. The revised catalog uses a new definition-bound version identifier and a separate local copy-refresh release. Original consumption coverage remains unknown: the newer staged files are not claimed as historical run inputs.

The evidence archive records the current capture and binding in `outputs/publisher-commerce-binding.json` and keeps the earlier complete capture under `outputs/publisher-original-captures/commerce-native`. The current retained read/query journey is `outputs/publisher-commerce-journey.json`; tests replay it without fresh native calls when `DDK_VIEWER_REPLAY_COMMERCE` points to it. This is local file evidence, not managed candidate acceptance or live publication.
