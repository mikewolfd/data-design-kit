# Qualified catalog API increment: dev6

Version `0.1.0-dev.6` is an installed development package qualified for `core`, `catalog`, `catalog.dcat` and `lineage.openlineage`. It adds captured native-job metadata, explicit application bindings from authored field rules to accepted native reports, and scoped export-key evidence. It does not claim another complete product release or extend the [dev5 native qualification](local-release-dev5.md).

| Identity | Value |
| --- | --- |
| DDK source | `b2637279beef7f30f23aba3ca2b8f50f7dc02d3f` |
| Wheel version | `0.1.0.dev6` |
| Wheel SHA-256 | `41dbccda3367ea794f0040c165abd86f43d918ecee036cbce7307a0b98b18149` |
| Local metadata adapter | `ddk.metadata.local` version `0.2.0` |
| Tested platform | macOS arm64, Python 3.12.13 |

Use the [wheel](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/catalog-api-dev6/distribution/qualified-02/wheel-a/data_design_kit-0.1.0.dev6-py3-none-any.whl) and exact installer requirement in the [handoff](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/catalog-api-dev6/handoff.json). The `catalog` extra supplies standards outputs; `native-metadata` supplies the maintained PyArrow and BLAKE3 readers for native metadata. [Runtime constraints](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/catalog-api-dev6/distribution/dependencies/catalog-runtime.txt) and the [hash lock](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/catalog-api-dev6/distribution/dependencies/catalog-runtime.lock) retain exact versions. Existing dependencies are unchanged; the new optional dependency is `blake3==1.0.11`. Installation requires no source injection.

All **385 installed tests passed**, with zero failures, errors or skips and ten existing RDFLib warnings in 41.82 seconds. The run includes 83 managed-metadata cases and the repaired relationship/row-position cases. Two existing bounded CLI cases use the already qualified dev5 native inputs; they do not qualify a native profile in this package. [JUnit results](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/catalog-api-dev6/distribution/qualified-02/junit.xml).

[Qualification](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/catalog-api-dev6/distribution/qualified-02/release-qualification.ddk.json) passed 142 case/profile combinations for exactly the four profiles above. `firstProductRelease` is false. No adapter manifest was promoted: the five shipped source declarations remain `experimental-unverified`, and native profiles remain unclaimed.

Two builds from the exact Git archive produced identical wheel bytes. Verification matched 112 wheel members to both installations and 106 code/resource members to the committed source. It checked the archive against Git, ordinary installer identity and installed consumer behavior with checkout/capture opens refused. The package excludes concurrent viewer descriptions and streaming changes. The primary integrator separately verified both wheel hashes and all 24 handoff evidence records. [Identity and consumer verification](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/catalog-api-dev6/distribution/independent-consumer/verification.json).

The first capture remains recorded as aborted: its external consumer probe incorrectly expected OpenLineage without metadata to pass. The corrected probe verifies that missing events remain incomplete and leave no artifacts. Positive lineage behavior has separate committed metadata cases. No package source changed to accommodate the faulty expectation.

Independent greybeard review closed four metadata gaps: nested primary-key coverage, incomplete-run production attribution, physical row-position scope, and contradictory authority conditions under the original native policy ID. Thirteen independent assembler probes checked the repairs. Distinct-policy requalification remains supported. These are metadata/translation checks; they do not establish native execution or the behavior of a concrete application generator.

Native retained-job execution, original producer-proof adoption, native input custody, streaming quality, concrete application generators, publication recovery and both full replacements remain unqualified. The native ETL findings and focused development evidence are recorded separately in [verification](verification.md). No portable package, additional platform, hosted deployment or publication is claimed.
