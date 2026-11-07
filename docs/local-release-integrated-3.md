# Qualified local DDK package: integrated SDK3

Version `0.1.0.dev6+integrated.3` passes all **266 required case/profile checks**, covering **249 distinct cases and 13 supported profiles**. One fresh installed run passed **703 tests with zero failures, errors or skips**. Separate offline-core API, CLI, lock creation and locked checks also passed. The connected commerce workflow includes ODPS/ODCS definitions, staged inputs, SQL, saved Substrait, exact-output quality checks, DCAT, OpenLineage and a catalog-bound reader.

| Identity | Exact value |
| --- | --- |
| DDK source | `cc9c44297fb78a6b061951462cd42541e98182bf` |
| Wheel version | `0.1.0.dev6+integrated.3` |
| Wheel SHA-256 | `bd3218fb8c95e54fbbb54711ba2913fc1a5ac27ca3473757065da7d1858f4486` |
| DocSpec implementation | `255c18489d224d095d4bd1d1edbdef5f5538bb3e` |
| DocSpec executable SHA-256 | `e2ed264617b878248b11436f061e73e748dfab9347c9ef9dd3e0b8a55565baa9` |
| Installed test platform | macOS arm64, Python 3.12.13 |
| Qualification report SHA-256 | `cc87f4f5f6b050faba37a0c7e960f045e0f29df0faaafd541de27bcead40e755` |

Two independent builds produced identical [wheel bytes](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-03/build-01/wheel-a/data_design_kit-0.1.0.dev6+integrated.3-py3-none-any.whl), sealed as mode `0444` before installation. The [build handoff](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-03/build-01/handoff.json) records 176 frozen source files, 112 staged package members, 117 installed non-RECORD wheel members, and unchanged core/full dependency versions. No native rebuild or dependency upgrade accompanies SDK3.

## What changed

Applications with a process supervisor can use `DocSpecAdapter(..., new_process_group=False)` to keep structured commands and buffered native reads in their supervisor's process group. Standalone behavior stays enabled by default. The supervisor owns group-wide termination; an SDK timeout stops and reaps the direct child. Original operation identities and uncertain execution outcomes remain available for reconciliation through DocSpec.

Nine actual POSIX process probes cover host TERM/KILL, SDK timeout cleanup and an explicit read override. They passed from source and in this installed capture. These probes use harmless stand-ins; actual native execution has separate cases in the same capture. They do not establish cancellation or rollback of durable work. [Process behavior and limits](runtime-integration.md#host-process-ownership).

## Evidence and supported profiles

The [installed handoff](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk3-complete-release-01/run-01/handoff.json), [qualification report](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk3-complete-release-01/run-01/release-qualification.ddk.json) and [execution evidence](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk3-complete-release-01/run-01/release-evidence.json) bind all results to the recorded source, installation and tools. The fresh nested native read completed before retained-version inspection. Both used the exact runtime and owned fixture namespace. All 703 outcomes came from SDK3; the [SDK2 result](local-release-integrated-2.md), including its original skipped outcomes and later supplement, remains unchanged.

Supported profiles are:

- `core`, `impact`, `catalog`, `catalog.dcat`, `lineage.openlineage`;
- `files.frictionless`, `ingest.dlt`, `odcs-cli`, `test.fixtures`;
- `plan.datafusion`, `plan.docspec-sql`, `execute.docspec-job`, `runtime.docspec-managed`.

The release claim sets `firstProductRelease` to `true`. Five generated [adapter manifests](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk3-complete-release-01/run-01/adapters) qualify together with their admitted evidence. Source declarations remain `experimental-unverified`; missing or changed evidence cannot establish support. The 12 recorded RDFLib deprecation warnings remain visible.

Both [independent terminal reviews](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk3-complete-release-01/run-01/terminal-review.json) passed. They reconstructed the required case set, checked exact source and installation identities, traced the connected workflow and reconciled the resource samples. A fresh targeted census found none of the 113 previously observed owned process identities.

The unchanged native executable separately passed [1,011 Rust and 31 Dagster tests](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-retained-job/full-gate-s3-source-final-01-closeout.json), retaining 17 explicitly ignored Rust cases. Synthetic S3 recovery and the installed SDK2 same-candidate replay retain their separate [source recovery evidence](verification.md#november-7-2026-installed-snapshot-source-and-native-replay). Native tests, installed profile qualification and application acceptance establish distinct claims.

## Use the retained installation

The [full installation](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-03/build-01/env-full/bin/python) contains the qualified wheel. Keep generated files outside the repository:

```sh
DDK_PY='/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-03/build-01/env-full/bin/python'
"$DDK_PY" -m ddk check '/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-03/build-01/frozen-source/examples/commerce/project.ddk.json' --format json
```

DocSpec execution requires the [exact executable](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-producer-prerequisite/runtime/docspec-managed-snapshot-s3-source-native-05) through `--docspec` and explicit `--limits`. Native intake and quality use the separately retained environment through `--tool-python`. The [capture controls](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk3-complete-release-01/plan.json) identify the tools, dependency versions, SQL-only negative control and pinned ODCS resolver.

For another environment, install the wheel through its SHA-256-qualified file URL, preserve the required dependency versions and retain the installer's ordinary identity records. `catalog` imposes no Arrow version. `native-metadata` selects PyArrow `26.0.1` and BLAKE3 `1.0.11`. An application's different dependency tuple needs its own checks.

## Measurements and remaining work

The [observer](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk3-complete-release-01/run-01/observer.json) recorded 492.977 seconds over 446 samples, maximum sampled family RSS of 365,412,352 bytes and maximum sampled net owned growth of 429,858,816 bytes. It recorded no stop, error or surviving owned process. The growth includes the fixture's executable copy and excludes shared installations and immutable inputs. These samples establish neither true peaks, total writes nor production-scale performance. The 11,278-file index and handoff were written after monitoring ended.

This qualifies the recorded local wheel and native executable. A new portable SDK3 archive, relocated installation and refreshed distribution inventory remain unaccepted. The [dev2 portable archive](local-release.md) retains its original scope and recorded software-bill-of-materials limitation. Congress's [original eight-table source proof](verification.md#november-7-2026-congress-retained-source-proof) separately passed against its retained S3 archive snapshots. Other provider workloads, complete Congress/SpicyRegs acceptance, large-candidate quality, additional platforms and external publication remain separate work. The local DDK release does not depend on either application replacement.
