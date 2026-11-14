# Publisher discovery extension v1

Use the publisher's existing DDK project `extensions` entry to supply approved discovery content that the standard catalog does not carry. The viewer validates and reads this content from the same pinned catalog as the dataset and version records. SpicyRegs and Congress already publish project extensions using this route. The new profile uses key `urn:ddk:publisher:discovery` and leaves the core DDK 0.1 schema unchanged. Metadata map (evidence archive `outputs/implementation-20261107/metadata/metadata-map.md`) · [DDK project schema](../../schemas/0.1/project.schema.json) · [DDK catalog API](../../docs/catalog-api.md)

## Publisher source and public disclosure

1. Put the typed value in the root publisher project's maintained `project.ddk.json` under `extensions["urn:ddk:publisher:discovery"]`. Keep native ODCS and ODPS facts in those standard documents. For example, write the dataset title, description, grain and field description there. Use standard relationships, recipes, representations, and checks for the facts those structures support. Use the extension for a separate guide or a fact the admitted catalog cannot otherwise carry. A value projected from another maintained standard field must preserve that field's source and scope.
2. For a public set, grant the source project ID in the disclosure policy's `identifiers` and include the extension URI in the existing exact `projectExtensions` row. Keep one row per project/version. For example, the policy fragment below shows the shape. Other existing grants still apply.
3. DDK copies a granted extension value in full. It does not redact extension fields or resolve references within the payload. The publisher must prepare a public-only value, verify the full text and links for public disclosure, and validate against the generated public catalog. Keep restricted evidence, private file paths and credentials in the local publisher inputs. Use the public hash-only identity where that is what the generated catalog discloses.
4. The viewer reads exactly one declaration from the generated `catalog.extensions["urn:ddk:catalog:assembly"].projectExtensions[]` where the row's `project` exactly matches `catalog.project` and `namespace` is the empty string. Imported projects and unrelated extension keys have no authority for this profile.

```json
{
  "identifiers": ["urn:example:publisher-project"],
  "projectExtensions": [
    {
      "project": {"id": "urn:example:publisher-project", "version": "1.0.0"},
      "extensions": ["urn:ddk:publisher:discovery"]
    }
  ]
}
```

The native grant also requires the correct base DDK disclosure of each referenced dataset and object, recipe, version, representation, or evidence record. The example identifies a shape only. Use the real publisher's existing project ID, project version, and allowlist.

## Payload and binding

The [runtime schema](../src/features/publisher-metadata/schema.ts) is the executable v1 profile. The top-level object has `schemaVersion:1` and optional `records`, `guides`, and `workflows`. It accepts up to 512 KiB of UTF-8 JSON, 1,024 records, 32 guides, and 16 workflows. Nested lists are bounded to 20 by default. The schema closes every object. Each supported field is optional unless explicitly required in its type. Dates and timestamps retain the supplied value, including time zone and fractional seconds. External links are absolute HTTP(S) URLs with no embedded credentials. Support may also specify one plain `mailto:` address without headers.

| Target | Required identity |
| --- | --- |
| `dataset` | `datasetId` and `definition:{contractId,version,object,sourceSha256}` match the exact disclosed definition. A definition-only change that keeps the same version string still changes the digest and requires review. |
| `version` | `datasetId,versionId` match an admitted version belonging to that dataset. |
| `representation` | `datasetId,versionId,representationId` match the entire admitted chain. Availability still comes from the representation, retention, and adapter. |
| `recipe` | `recipeId` matches a disclosed catalog recipe. Execution support still comes from the adapter. |
| `external` | `url` passes safe-link validation. Valid only as a guide or reuse link target. A link does not enable a local capability. |

Records use `target` plus the following supplied facts:

- Dataset only. `alternateNames:[{name,kind:"former"|"alternate"}]`, `variantDescription`, `topics:[{id,label}]`, and `updateFrequency`. Use “former” only when the publisher documents the rename. Keep native aliases and dataset identities in the core catalog.
- Dataset, version, representation, or recipe. `coverage:{period?:{start?,end?},geography?,population?,inclusion?,exclusions?}`, with dates as `YYYY-MM-DD`. `dates:[{kind,value}]` distinguishes `sourcePublished`, `dataUpdated`, `metadataUpdated`, `retrieved`, `nextExpectedUpdate`, and `coverageObserved`. Supply the actual date for this object and event. Never substitute a run, capture-custody, or approval clock. `cautions:[{summary,details?,evidence?}]` and `history:[{kind,description,date?,evidence?}]` retain their exact subject. History kinds are `correction`, `renamedField`, `coverage`, `compatibility`, and `note`.
- Attribution and use. `publishers:[{name,url?}]`, `terms:[{label,scope:"data"|"portalText"|"derivedView",url?}]`, `support:[{label,url}]`, `citation:{text,originalIdentifier?}`, and `reuse:[{label,purpose,target}]`. Show resource-level rights at the resource. A dataset-wide term does not override an exact resource term or describe rights in a derived view. A copyable citation should carry the selected version's exact identifier separately if the supplied citation does not contain it.
- Dataset prepared views. `preparedViews:[{id,question,kind:"valueCounts",field:[{field}]}]` names a publisher question and a single top-level disclosed scalar field. Each ID is unique per dataset. Reject virtual, nested, composite and missing field definitions. The viewer counts one value per returned parent record and keeps absent, null and empty values distinct. The display and download state the page scope, with no full-population inference.
- Representation only. `resource:{kind?,purpose?,byteSize?,accessRequirements?,requestLimits?,destination?}` adds absent purpose and exact file or service metadata. Kind is `data`, `documentation`, `metadata`, or `notification`. Destination is `{kind,url}` with `publisherPage`, `documentation`, `externalApi`, `directFile`, or `notification`. A notification cannot declare an API or direct file destination. Byte size is a nonnegative exact safe integer. Zero is a value. Native kind, location, media type and availability stay in the standard representation; adapters own the limits for portal requests.
- `unknowns:[{fact,reason?}]` records publisher uncertainty. Use the field or facet name in `fact`, such as `dataUpdated` or `resource.byteSize`. An omitted optional value with no entry is absent. Invalid values produce a typed refusal.

A guide requires `id`, `title`, `question`, `summary`, `author:{name,url?}`, `reviewedOn`, `links:[{label,purpose,target}]`, and `evidence`. It may supply structured coverage and a `reviewTrigger` describing consequential changes that require a new review. Evidence takes `{label,url,sourceVersion?}` or `{label,record:{uri,sha256},sourceVersion?}`. A record must exactly match a disclosed source inventory, dataset/product/production definition, or standard evidence record. Display a record URI as a technical reference and use existing allowlisted evidence readers if available. Give each link a task and disclose what can be done at its destination. A recipe link requires at least one disclosed dataset context where the viewer can show that recipe. The pilot guide should give two or three useful data choices.

Reject duplicate root declarations, target records, guide IDs, workflow IDs, dates of the same kind, topic IDs per record, unknown fact keys per record, wrong cross-record bindings, invalid date periods, unsafe links, and unadmitted record evidence. A malformed or unsupported extension refuses the whole value. The viewer keeps the standard catalog available and shows the distinct refusal. An absent key, omitted optional fact, explicit unknown, valid zero, and valid empty list remain separate. The viewer caches the parsed result by its immutable snapshot object. [Typed extraction](../src/features/publisher-metadata/index.ts) · [Focused tests](../tests/unit/publisher-metadata.test.ts)

## Record lookups and follow-up actions

`workflows` presents publisher-authored questions at the catalog entry. Each workflow requires `id`, `title`, `summary`, `recipeId`, and `bindings`. The recipe remains the maintained owner of SQL, parameter meaning and matching rules. Each binding is keyed by the recipe's input name and contains exactly `datasetId`, `versionId`, and `representationId`; it must match a disclosed input and the complete dataset/version/resource chain. One to sixteen inputs are supported. This profile does not accept `releaseId`, choose a latest version, or establish publisher selection.

The small lookup form supports recipes whose declared parameter properties all have JSON Schema `type:"string"`. Optional `defaults` maps up to sixteen declared parameter names to strings of at most 4,096 characters; optional `emptyMessage` describes a completed no-match within these exact inputs. A missing required key prevents submission. Other parameter types retain their existing recipe UI and API; this profile does not convert numeric or compound native identities into text. The connected owner must support the recipe before the viewer enables execution. A catalog-search miss can lead to these lookups and explicitly copy the searched identifier into a single-key form; catalog search itself still searches metadata.

Version-targeted records may supply up to eight `rowActions` and eight unique `readableFields`. Every referenced row field must resolve to one top-level disclosed ODCS field with `logicalType:"string"`, without nested properties or array items. Action IDs are unique within the record.

| Action | Required configuration | Runtime meaning |
| --- | --- | --- |
| `kind:"recipe"` | `id`, `label`, `workflowId`, and `parameters:{parameterName:rowFieldName}` | Fill the referenced workflow from the selected row. Map every required recipe parameter and use only declared names, with one to sixteen mappings. Every mapped row value must be a nonblank string. Missing keys disable the action; the viewer never broadens the query. Multiple text keys are supported, but arbitrary typed or nested compound-key actions remain outside this profile. |
| `kind:"original"` | `id`, `label`, `fields:{uri,sha256,version}`, and `sourceReference:{scheme,uriPath,versionPath}` | Read the publisher URI, retained-content digest and source version from the named row fields. Match the exact source-reference scheme and the two paths within `source.reference.value`, plus the digest of its supported retained content. Each path has one to eight object-field steps. Exactly one catalog source observation must match; missing, ambiguous or changed keys disable the action. |

An original action opens the matched source's digest-pinned `urn:ddk:version:local-file-sha256` content through the existing evidence reader. Publisher-native URI/version identity and the retained file's URI/digest serve different purposes. The source owner supplies their mapping. Matching these explicit keys enables the action; it does not create normalized-version lineage or establish source completeness.

For query results, row actions apply only when the recipe declares `resultDataset` and that dataset has exactly one matching exact input binding in the workflow. The viewer does not infer a result's origin from its column names. Related lookups retain the starting record, offer a return action, and stop opening further nested lookups after four levels.

`readableFields` lists the publisher's plain-text presentation fields. The viewer renders their values as text, uses an ODCS business name when supplied, and keeps every returned field available under **All fields, including original source text**. Publishers own decoding and normalization and must retain original text separately when they derive a readable field. The declaration never authorizes HTML execution or replacement of the source value.

This example shows the profile shape. Its recipes, field names and exact identities must exist in the generated catalog before it can be admitted:

```json
{
  "schemaVersion": 1,
  "workflows": [
    {
      "id": "rule-by-key",
      "title": "Find the related rule",
      "summary": "Find a rule by its complete docket and rule identifiers in the retained version.",
      "recipeId": "urn:example:recipe:rule-by-key",
      "bindings": {
        "rules": {
          "datasetId": "urn:example:dataset:rules",
          "versionId": "urn:example:version:rules:1",
          "representationId": "urn:example:resource:rules:1"
        }
      },
      "emptyMessage": "No rule matches these keys in the selected retained version."
    }
  ],
  "records": [
    {
      "target": {
        "kind": "version",
        "datasetId": "urn:example:dataset:comments",
        "versionId": "urn:example:version:comments:1"
      },
      "readableFields": ["comment_text"],
      "rowActions": [
        {
          "id": "related-rule",
          "label": "View the related rule",
          "kind": "recipe",
          "workflowId": "rule-by-key",
          "parameters": {"docket_id": "docket_id", "rule_id": "document_id"}
        },
        {
          "id": "original",
          "label": "Inspect this comment's original",
          "kind": "original",
          "fields": {"uri": "source_uri", "sha256": "source_sha256", "version": "source_version"},
          "sourceReference": {
            "scheme": "urn:example:publisher-source-version",
            "uriPath": ["uri"],
            "versionPath": ["version"]
          }
        }
      ]
    }
  ]
}
```

The workspace retains the six most recent data/query/related-data views for the current session, including drafts, exact input choices, returned pages, page search and selected records. Metadata tabs do not consume that budget. Catalog entry separately retains six recent publisher lookups. Eviction is explained; page refresh clears this in-memory state. A catalog ID or catalog/report/lock digest change invalidates the retained tasks. Leaving an active request stops waiting and rejects late replies; native completion may remain unknown.

In Query lab, **Insert table name** preserves the authored draft and prior bindings. **Start query**, or **Replace with new query** for a nonempty draft, replaces it explicitly and offers **Undo query edit**. A relevant explicitly chosen version/resource is retained; otherwise the viewer requests an exact choice. Results sit below the editor, the table picker is bounded and collapsible, and completion receives focus. [Workflow regressions](../tests/browser/workflow-state.spec.ts) · [Publisher journey examples](../tests/browser/publisher-workflows.spec.ts) · [SpicyGov workflow acceptance](/Users/mikewolfd/Work/artifacts/spicygov-workflow-fixes-20261113/ACCEPTANCE.md)

## Regeneration and review

- Freeze the owner project source and its existing dependency pins, disclosure policy, ODCS/ODPS, extension, and any source evidence. Use an owner-approved staging copy of the publisher inputs and record the source commit, input digests, and exact changed files. Keep the shared and publisher reference checkouts read-only. Existing captures are historical evidence. SpicyRegs staging precedent (evidence archive `outputs/spicy-resume-20261106/source-update.json`) · Congress source receipt (evidence archive `outputs/publisher-congress-result.json`)
- Validate the owner profile, then assemble the standard public set with the pinned DDK metadata builder and the reviewed disclosure policy. No provider reads, new native runs or publication are required for this source-only step. Use a fresh output directory, compare catalog/report/lock inventory and exact companions, and retain the prior artifacts.
- On the generated public set, revalidate payload shape, target and evidence bindings, bounds, safe links, and actual visible disclosures. Check changes against the publisher source and prior catalog. Preserve exact identities, values, nested paths, and selection/acceptance facts. Point the viewer registration to the new approved lock digest. Capture and publication remain separate decisions.
- Review guides when a referenced definition digest, version, resource, recipe meaning, or evidence source changes. Exact bindings stop stale definition claims from silently resolving. Review the maintained guide date and context alongside the regenerated artifacts.
