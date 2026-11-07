# Qualified local DDK package: integrated SDK2

Version `0.1.0.dev6+integrated.2` passes the complete local installed profile qualification, including DocSpec managed execution. All **265 required case/profile checks**, covering **248 distinct cases and 13 profiles**, pass. The connected commerce workflow includes ODPS/ODCS definitions, staged inputs, SQL, saved Substrait, exact-output quality checks, DCAT, OpenLineage and a bound catalog reader.

| Identity | Exact value |
| --- | --- |
| DDK source | `5086bf4cce6a6ad7314e248a6d447a4d3ee30f0e` |
| Wheel version | `0.1.0.dev6+integrated.2` |
| Wheel SHA-256 | `5a7e14211d01b46f27677874d1424b3b210fc2cce915df50a5b63972ef55f55b` |
| DocSpec implementation | `255c18489d224d095d4bd1d1edbdef5f5538bb3e` |
| DocSpec executable SHA-256 | `e2ed264617b878248b11436f061e73e748dfab9347c9ef9dd3e0b8a55565baa9` |
| Installed test platform | macOS arm64, Python 3.12.13 |
| Qualification report SHA-256 | `144dbd425a3b23b98767209b9ea47aaa3dd5909c2b376227a864b1434be685b4` |

Two independent builds produced identical [wheel bytes](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-02/build-01/wheel-a/data_design_kit-0.1.0.dev6+integrated.2-py3-none-any.whl). The [build handoff](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-02/build-01/handoff.json) records 174 frozen source files, 112 staged package members, 117 installed non-RECORD wheel members, and exact core/full dependency versions. The wheel was sealed after building; the [seal record](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-02/build-01/wheel-seal.json) records unchanged bytes and mode `0444`.

## Evidence and supported profiles

The [original installed capture](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk2-complete-release-01/run-01/incomplete-handoff.json) contains 692 passes, two skips caused by omitted harness settings, zero failures/errors and 12 RDFLib warnings. After all tests finished, its zero-skip harness correctly withheld qualification as `not_run`. The [two-test supplement](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk2-complete-release-supplement-01/run-01/handoff.json) supplies fresh native nested-read and retained-inspection passes on the same source, wheel, executable and dependency tuple. It leaves the original records unchanged and selects the new results only for the affected physical-consumer case. This is 694 passing selected test outcomes across three actual pytest processes, not a rewritten zero-skip initial run.

[Release qualification](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk2-complete-release-supplement-01/run-01/release-qualification.ddk.json) and its [execution evidence](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk2-complete-release-supplement-01/run-01/release-evidence.json) pass these profiles:

- `core`, `impact`, `catalog`, `catalog.dcat`, `lineage.openlineage`;
- `files.frictionless`, `ingest.dlt`, `odcs-cli`, `test.fixtures`;
- `plan.datafusion`, `plan.docspec-sql`, `execute.docspec-job`, `runtime.docspec-managed`.

The release claim sets `firstProductRelease` to `true`. Five generated [adapter manifests](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk2-complete-release-supplement-01/run-01/adapters) match the captured declarations and exact executed evidence. Source declarations remain `experimental-unverified`; qualification applies when the generated manifests and their admitted evidence are supplied together. Missing or changed evidence cannot establish support.

Both [independent terminal reviews](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk2-complete-release-supplement-01/run-01/terminal-review.json) closed after checking the raw results, required case set, input identities and retained files.

The current native executable separately passed [1,011 Rust and 31 Dagster tests](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-retained-job/full-gate-s3-source-final-01-closeout.json), retaining 17 explicitly ignored Rust cases. Its local all-features build includes saved Substrait. A synthetic S3 fixture and installed same-candidate replay have their own [source recovery evidence](verification.md#november-7-2026-installed-snapshot-source-and-native-replay). Native tests, installed profile qualification and application acceptance establish distinct claims.

## Use the retained installation

The [existing full installation](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-02/build-01/env-full/bin/python) already contains the qualified wheel. Run its CLI against explicit project paths; keep generated files outside the repository:

```sh
DDK_PY='/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-02/build-01/env-full/bin/python'
"$DDK_PY" -m ddk check '/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/integrated-successor-package-02/build-01/frozen-source/examples/commerce/project.ddk.json' --format json
```

DocSpec execution uses the [exact DocSpec executable](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-producer-prerequisite/runtime/docspec-managed-snapshot-s3-source-native-05) with `--docspec` and explicit `--limits`. Native intake and quality use the separately retained environment through `--tool-python`. The [capture controls](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/native-package-successor/sdk2-complete-release-supplement-01/plan.json) identify all native tools and versions, including the SQL-only negative-control executable and pinned ODCS resolver. The retained core-only installation passed API/CLI, lock creation and locked checking without optional engines.

For another environment, install the wheel through its SHA-256-qualified file URL and preserve the required versions from the build handoff; keep its ordinary installer identity. `catalog` does not impose an Arrow version. `native-metadata` explicitly selects PyArrow `26.0.1` and BLAKE3 `1.0.11`. Congress's existing Arrow `25.0.1` and PyParsing `3.2.5` checks have separate application evidence and do not inherit this complete profile result.

## Measurements and remaining work

The initial capture observer recorded 493.995 seconds, maximum sampled process-family RSS of 380,747,776 bytes and maximum sampled net owned growth of 428,871,680 bytes. The supplement recorded 4.312 seconds over four samples, 160,415,744 bytes maximum sampled RSS and 3,203,072 bytes maximum sampled net growth. Both closed without a stop or surviving owned process. Shared environments and immutable inputs lie outside the owned-growth totals. These samples establish neither true peaks, total writes nor production-scale performance; the supplemental index and handoff were written after monitoring ended.

This is a qualified local wheel and native executable on the recorded platform. A new portable SDK2 archive, relocated installation and refreshed distribution inventory have not been accepted. The [dev2 portable archive](local-release.md) retains its original scope, including its recorded software-bill-of-materials limitation. Additional platforms, actual-provider access, full Congress/SpicyRegs acceptance, large-candidate quality and external publisher activation remain separate work. No hosted deployment or publication is claimed.
