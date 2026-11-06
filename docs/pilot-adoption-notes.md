# Deferred DDK pilot adoption notes

These prior pilot preparations and replacement demonstrations are retained for future adoption work. They are outside the active local stack build and release dependencies. Native publisher and project owners retain their existing authority.

### WP-00A — Pilot baselines and independent expectations

**Dependencies:** WP-00. **Owners:** DDK and the pilot project maintainers. **Output:** a retained comparison record for each pilot before its metadata adapter is built.

- Use the two slices in the [pilot plan](#pilot-plan). Pin the authoring revision, exact native data versions, publisher controls, incumbent reader revision, and available evidence. Reference retained artifacts through their original identities and record their availability.
- Record one user task, the maintained declaration or check targeted for replacement, and independently expected results. Capture incumbent behavior on the same pinned scope and identify where an independent reference must cover additional candidate behavior.
- Record the existing metadata export, maintained mappings and checks, and observed setup and refresh work. Use that baseline to compare the DDK adapter with a thin export from the existing registry before expanding the format.
- Identify the project owner and preview selection/rollback controls for each replacement. Keep the incumbent selection serving users while candidates are developed in separate preview locations.

**Acceptance.** Each comparison record identifies retrievable inputs, source revisions, expected rows, incumbent behavior, scope differences, and the maintenance targeted for removal. Expected results exist before the candidate implementation. Missing comparison inputs remain explicit and must be resolved before accepting the affected pilot baseline. WP-13 consumes these records; WP-15 owns the final comparison, cutover, rollback, and demonstrated maintenance removal.

<a id="pilot-plan"></a>
### WP-15 — Parallel catalog replacements and full-stack pilot

**Dependencies:** WP-00A, WP-06, WP-10, and WP-14. **Owners:** DDK, SpicyGov, SpicyRegs/SpicyDocs, and congressional-tech maintainers. **Output:** two preview replacements and evidence of what each can retire.

#### Use the frozen comparison

Use the comparison records captured in WP-00A before adapter development. Verify that their retained inputs and incumbent evidence remain available. Any change to scope or source revision needs an explicit baseline revision and comparable results for both paths; preserve the prior record. Both paths read the same authoritative facts. The DDK candidate generates its own metadata for the replacement boundary. Incumbent-generated metadata supplies the baseline comparison. The incumbent selection continues serving users while candidates run in separate preview locations.

| Pilot | Replacement boundary | Existing authority |
| --- | --- | --- |
| Federal Register | DDK design and checks, DocSpec transformation, catalog generation, and a SpicyGov preview that reads the DDK catalog directly | SpicyDocs and SpicyRegs supply retained pages, typed source tables, and capture/build receipts. DocSpec owns execution and output identity. SpicyGov owns preview selection and bounded data reads. |
| Congressional documents and meetings | DDK relationship checks and generation of the selected slice of `schema.json` for the existing archive and MCP readers | The congressional release registry owns authored facts. The publisher owns file membership, native file checks, release identity, and selection. |

#### Full DDK stack for the Federal Register

1. Use the bounded retained input set pinned in WP-00A: `federal_register_documents`, `federal_register_docket_candidates`, and their SpicyRegs `inputs.json`. Trace records through `source_sha256` and `source_locator` to the retained API pages. Preserve the distinction between a candidate parsed from source text and a confirmed docket link.
2. Maintain the slice's ODPS product, ODCS dataset definitions, and one declared dated relationship. Check the design and assess the impact of a proposed key or rule change. Build a document-to-docket-candidate table using `(document_number, publication_date)` and selected scalar columns. Use independently expected rows with a document number repeated across dates, unmatched keys, and repeated occurrences.
3. Execute the SQL and replay the saved Substrait bytes through DocSpec on the same inputs. Compare each result independently. Run Data Contract CLI against the exact saved-plan output. Retain the plan digest, execution identity, exact input and output versions, and check results. Make that output eligible for the preview publisher after the required checks pass.
4. Generate the DDK catalog, DCAT 3 discovery, and OpenLineage records. Use the DDK catalog directly in the SpicyGov preview to find the product and bind its saved-plan output to the existing bounded data reader. Follow a docket candidate to the document and its retained source. Verify that the displayed output version, check subject, and run output agree.
5. Compare the existing explorer flow for the overlapping dated relationship on a common pinned input scope. Use the independent expected rows for typed candidates beyond the incumbent's scope and label that difference. Retire one maintained relationship mapping or overlapping structural check only for behavior covered by the comparison.

#### Existing archive and MCP readers for congressional-tech

1. Use the retained release and registry revision pinned in WP-00A. Keep the existing registry as the authoring source. Use the meetings-to-documents slice, including `meeting_transcript_documents` from `meetings.transcripts[].list_row` to the document list in the same release.
2. Check the nested endpoint in DDK and generate the compatible `schema.json` for the slice. Keep the rest of the release schema available to the readers. Use the native metadata-only release path and the same Parquet members. Changed metadata receives a new release identity through the existing writer.
3. Open both the base release and the candidate with the archive and MCP readers. Verify the transcript reaches the same document, binary identifiers keep their values, and missing tables appear as unavailable. Check that the DDK binding rejects a position tied to the wrong release before the query runs. Generate the standards outputs from the same definitions and records. Replace the redundant nested-endpoint check for the pilot after parity. Retain native file and release validation.

#### Preview cutover, rollback, and acceptance

| Gate | Evidence required |
| --- | --- |
| Correctness | Both candidates match independently expected rows and the incumbent behavior within the pinned overlap. Record any scope differences. Plant an incomplete dated key, a cross-release position, and wrong-version or missing required check evidence. The candidate must report the failure or unresolved check. A candidate with a failed or unresolved required check is ineligible for preview selection. |
| Refresh and change | Change one definition in each pilot and record the affected reader output and check obligations. In a fresh process, verify that an unchanged catalog refresh produces identical bytes with zero data-payload opens, copies, or repeated data checks. |
| Select and restore | Keep the prior preview selection and exact artifacts available. Select the candidate through the project-owned preview control and verify the version served by a new reader session. Restore the prior selection and verify its readback. During both switches, retained run and release references still resolve to their original inputs. |
| Maintenance | Record the declaration or check removed in each replacement path, the adapters and compatibility outputs retained, and the setup and refresh work observed. Keep the evidence with the release record. |

**Acceptance.** Both pilots must meet [DDK-TEST-004](specification.md#DDK-TEST-004). The Federal Register proof follows one saved-plan output from retained sources to the preview reader. The congressional proof exercises catalog replacement through the existing consumer formats. Record any external adoption trial separately from these two project pilots.

