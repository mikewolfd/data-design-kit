# Qualified catalog and managed Update increment: dev5

Version `0.1.0-dev.5` is a locally qualified wheel. It adds explicit permission for exact native type strings, separate private and public catalog views from one assembly, and native source-only managed Update. It also bounds subprocess cleanup and preserves uncertain outcomes after transport failure.

| Identity | Value |
| --- | --- |
| DDK source | `5e90d70f74ef88053a75b8d991caf262ad74bbd0` |
| Wheel version | `0.1.0.dev5` |
| Wheel SHA-256 | `b5b64cf8e670b9fb9a1546d4f3bc5aead70e47124f2acfb51cec9028286007eb` |
| Full native source | `d96e00172d7d4be26da4532cda35aa05f2a3709e` |
| Full native executable SHA-256 | `72f3aea76d102809b18c3cbc2187b4e4a1136966030b82296ab5043c3f50ed83` |

Install the [wheel](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/managed-public-dev5/distribution/qualified-02/wheel-a/data_design_kit-0.1.0.dev5-py3-none-any.whl) with the hash-qualified requirement and native executable in the [handoff](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/managed-public-dev5/handoff.json). Preserve the recorded dependency pins and installation identity. The SQL-only executable keeps its separately identified dev2 source and capability; it does not acquire managed Update support. The earlier [dev4 wheel](local-release-dev4.md) and [dev2 portable archive](local-release.md) remain unchanged. No dev5 portable archive is claimed.

All **358 installed tests passed**, with zero failures, errors or skips and 11 existing RDFLib warnings in 187.88 seconds. [Qualification](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/managed-public-dev5/distribution/qualified-02/release-qualification.ddk.json) passed **187 case/profile combinations**, covering 170 cases and 13 declared profiles plus the implicit product-release gate. [Identity verification](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/managed-public-dev5/distribution/qualified-02/identity-verification.json) matches 149 source files to the commit, 108 wheel members to both installations, and 102 code/resource members to source. Both builds produced identical wheel bytes; source and external inputs remained unchanged.

The core-only installation passed checking, lock creation and verification. It [recognized all five exact qualified manifests](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/managed-public-dev5/distribution/qualified-02/core-qualified-discovery.json) without importing native engines or catalog dependencies. The first capture's process-loss failure remains [recorded separately](verification.md#november-6-2026-process-cleanup-repair); the second capture exercises the repaired owner. Separate greybeard and ETL reviewers closed the public-disclosure, private-view isolation and process-cleanup findings.

Public type strings require explicit `definitionPhysicalTypes` grants and complete disclosure of modeled children. Invalid grants preserve prior output. `CatalogResult.local_catalog` retains the admitted private view; `catalog` remains the requested audience's view. Both come from one captured source and one metadata read. See the [catalog API](catalog-api.md).

Managed Update uses the existing DocSpec lifecycle for an independent source-only local base. Installed checks cover correction, explicit deletion, null and empty semantics, stale-base refusal, exact-candidate quality, rule-only reuse, original-ID recovery and historical replay. Runtime completion and protection determine payload lifetime. Retained audit metadata grants no new protection or retention promise. The [native handoff](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-update/final-handoff.json) retains the required compiler-pinned full gate separately.

Small-fixture [measurements](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/managed-public-dev5/distribution/qualified-02/resources/measurements.json) recorded median core, impact and metadata-refresh times of 53, 99 and 112 ms, with 52.8 MiB peak process memory and zero instrumented data-payload opens. These observations describe this fixture and machine, not whole-application performance or a measured speed improvement.

Streaming quality revision 2, whole-job schema preparation, richer native value mapping, complete multi-output quality acceptance, retained whole-job execution and publication recovery remain separate work. Public disclosure of a nested native type does not implement its execution or quality mapping. Full SpicyRegs and congressional-tech replacement acceptance remains incomplete.
