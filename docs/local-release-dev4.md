# Qualified relationship-profile increment: dev4

Version `0.1.0-dev.4` is available as a locally qualified wheel. It adds explicitly supplied application relationship profiles, root-only description grants, and impact analysis for profile provenance and assessments. Public output requires an explicit profile-ID grant, preserves redacted provenance, and keeps withheld assessment and consumer scope unknown. See the [catalog API](catalog-api.md).

| Identity | Value |
| --- | --- |
| DDK source | `fb70ab825243235b4ecf77c5ebb8c636d0d06e2d` |
| Wheel version | `0.1.0.dev4` |
| Wheel SHA-256 | `7c4c6bb481316c95e13c5518089f90c71664ca7387c09eb1ae0f94219fe267b8` |
| Native source | `b1270b2e964becc5844bb6ca95ee5d605c7a3d79` |
| Native executable SHA-256 | `b89b43e2d2bf17f8d87ff1d9a779e06c3a024f2777e2327a8f048c6cb00a2532` |

Install the [wheel](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/wheel-a/data_design_kit-0.1.0.dev4-py3-none-any.whl) using the exact hash-qualified requirement in the [handoff](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/handoff.json). Keep the recorded dependency pins and installation identity. The existing [dev2 portable archive](local-release.md) and [dev3 catalog capture](local-release-dev3.md) remain unchanged; no dev4 portable archive is claimed.

All **320 installed tests passed**, with zero failures, errors or skips and 11 existing RDFLib warnings in 122.83 seconds. The [qualification report](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/release-qualification.ddk.json) passes **177 case/profile combinations**, covering 160 cases and 13 declared profiles plus the implicit product-release gate. The core-only installation passed separately without native engines or catalog dependencies.

Two independent wheel builds produced identical bytes. The [identity verification](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/identity-verification.json) checks all 144 source files against the commit, all 108 non-RECORD wheel members against both installations, 102 code/resource members against source, and installer/build identities. Source and external inputs remained unchanged. Separate greybeard and ETL source reviews closed the profile disclosure, impact and resource findings; installed execution is recorded in [JUnit](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/junit.xml).

Small-fixture [measurements](/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/resources/measurements.json) recorded median core, impact and catalog-refresh times of 43, 89 and 116 ms, with 51.3 MiB peak process memory and zero instrumented data-payload opens. These values describe this fixture and machine, not whole-application performance.

Static profile support establishes declared reasoning only. Each application's rules still need their own review and consumer checks; observed matches, cardinality, remote existence and data quality require separate evidence. Both greenfield replacement teams received this package. Their full native execution, qualification, recovery and reader acceptance remain incomplete.

Managed Update, the isolated streaming-reader helper, richer native types/views, complete multi-output evidence mapping and publication recovery are not included. Native runtime and source-only managed Build capability remain on the qualified dev2 tuple. Managed historical replay through lifecycle compaction is outside that retained qualification; current native work repairs its retention and decode-budget boundaries.
