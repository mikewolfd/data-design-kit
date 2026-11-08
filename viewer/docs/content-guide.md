# Catalog content guide

Write descriptions in the maintained standard metadata, then regenerate the catalog. The portal uses those artifacts; publisher proposals in the evidence archive's `outputs/` are review material and must never become a runtime metadata source. Captured application catalogs remain immutable evidence.

Answer four questions for each dataset: What is it about? What does one record represent? What can a visitor do here? What should they know before using it? Publishers own the first two answers and the data limits. The portal derives actions from the current reader/query capabilities, recorded versions and file availability.

| Content        | Publisher responsibility                                                                                     | Portal responsibility                                                                     |
| -------------- | ------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| Human title    | Name the subject; distinguish meaningful variants. Keep the identifier separate.                             | Display supplied titles and exact identifiers; use a clear missing-title fallback.        |
| Purpose        | Explain the useful information in one sentence.                                                              | Lead with the introduction and keep technical notes available.                            |
| Record meaning | State the grain: one person, occurrence, document edition, event, aggregate or other precisely defined unit. | Preserve repeated occurrences and nested positions.                                       |
| Fields         | Define meaning, units, identifier scope, value codes and relevant limits.                                    | Preserve original names/types, exact values and missing/null/empty distinctions.          |
| Coverage       | State time, geography and population scope; name the expected population if known.                           | Keep observed and expected counts separate; preserve unknown.                             |
| Check names    | Explain the tested condition, expected outcome and examined scope; retain rule/evaluator identities.         | Show the named result without turning a pass into a general endorsement.                  |
| Source capture | Explain the recorded retrieval or observation using supplied source facts.                                   | Preserve its exact identity and outcome; distinguish a capture from source-wide coverage. |
| Query          | Name the question or actual action, inputs and result grain.                                                 | Expose supported actions and explicit version/release choices.                            |

Use the existing dataset `title`, `rowMeaning`, maintained definition `description`, field `description` and `businessName`, query `title`/`notes`, and supported publisher-source metadata. Verify each publisher's native schema before adding a field. The captured `datasetDefinitions` view shows generated content; it is not permission to edit a capture or introduce an unsupported metadata field. Original schemas and technical documentation retain schema rationale and constraints.

For a human title, prefer “Document details” to a sentence explaining storage and joins. Retain the exact dataset identity in technical details. For repeated titles, explain the collection or variant's purpose from maintained publisher facts; names such as `current`, `curated`, role codes and revision numbers alone do not establish which is canonical or suitable for the visitor.

Write record meaning independently from purpose. “Find meeting materials” explains a use; “One aspect of one meeting: recording, transcript, documents, witnesses or captions” explains a record. Describe repeated observations as observations rather than deduplicated people unless the source establishes that equivalence.

Describe amounts without guessing. “Integer minor currency units” does not identify a currency, decimal scale, gross/net treatment or whether a value includes tax. Supply those facts from the authoritative amount definition. Never turn a field named `amount_cents` into dollars without evidence. Dates need their supplied calendar/timezone meaning; regions need their supplied geographic definitions. Where a fact is missing, record a publisher question rather than a fabricated description.

Keep coverage limits visible with the introduction. A minimum and maximum observed date describe the included records; they do not prove complete coverage between those dates. “Unknown” and “not stated” do not mean absent. A missing expected population total cannot become a 100% coverage claim. A complete saved-file read describes that file, not every upstream record.

State the subject of each result. Passed/failed apply to the named check. `not_run` means the check was not run; `unknown` means the outcome is not established. Required/optional and applicable/not applicable are separate facts. A file fingerprint match confirms the file's identity; it does not validate every claim in its contents. Acceptance by the publishing system is a separate recorded decision.

Use “publisher” for responsibility for published metadata, “source” for where information came from, and “this portal” for interface capabilities. Expand unfamiliar acronyms on first use. Put exact names such as `source_record`, `same_release`, SHA-256 and native identifiers in technical details while preserving them unchanged. Define SQL as Structured Query Language when it first appears.

Label synthetic examples in titles or introductions, and label AI authorship when the publisher confirms it. “Model” alone does not establish artificial intelligence authorship. Preserve generation/review provenance when supplied. A documented calculation and a query that reads an already saved result need different titles; neither title should imply quality checks rerun unless they do.

Before delivering a regenerated catalog, compare the new artifact with its source and retained baseline. Check that identities, nesting, numeric values, disclosure limits, unknown states and publisher selections survived unchanged. Confirm every description against source evidence and every proposed field against the native schema. Run the viewer's required validation for the integrated change. Finally, test the wording with representative visitors; editorial review alone does not establish usability improvement.


## Publisher guides and prepared views

Additional guidance uses the versioned `urn:ddk:publisher:discovery` extension in the publisher's project metadata, copied through the standard DDK assembly and disclosure route. The viewer validates its exact dataset definitions, versions, resource and recipe targets. It refuses unsupported or malformed guidance visibly while preserving the base catalog. See [the profile](publisher-extension.md) for the supported shape and bounds.

Every maintained guide should name an author, review date, evidence and a `reviewTrigger`. Review it when a referenced definition, relationship, version, resource, or access capability changes. Regenerate the publisher artifacts and verify every destination after review. A valid link does not establish that guidance still answers a visitor's question; participant evidence is a separate acceptance step.

Prepared value-count views declare a question and one disclosed scalar field in publisher metadata. The viewer counts the actual returned page and preserves exact values, missing and null distinctions, exclusions, version identity and filter context. These counts do not establish source completeness, a time range for the returned records, or statistical representativeness. The synthetic Watershed example demonstrates this capability; it is not a chart of real environmental conditions.
