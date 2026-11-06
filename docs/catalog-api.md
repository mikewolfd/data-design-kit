# Using an assembled catalog

`ddk.catalog.assemble_catalog` gives an application the catalog, check report, and exact companion bytes from one assembly. It lets discovery and preparation use supported definitions while preserving unresolved qualification. It also supplies complete output files when the requested checks pass.

```python
from ddk.catalog import assemble_catalog

result = assemble_catalog(
    project_path,
    required_groups=("catalog.relationships", "catalog.qualification"),
)
```

| Result | Meaning |
| --- | --- |
| `report` | Check outcomes and diagnostics safe for the requested audience |
| `local_report` | Full internal diagnostics; keep these local |
| `local_catalog` | Full admitted metadata from the same assembly, before disclosure; keep this private |
| `catalog` | Structurally admitted, audience-filtered catalog, or `None` when admission failed |
| `companions` | Immutable mapping of catalog-relative paths to exact admitted SQL and other companion bytes |
| `artifacts` | Immutable mapping containing the complete standard output set, populated only when the report passes |
| `local_artifacts` | Explicitly requested private standard output set from the same assembly; never deliver through public artifact routes |

An admitted catalog can accompany `failed`, `unknown`, or `not_run` qualification. Check the report before treating data as qualified. `artifacts` includes `catalog.ddk.json`, `catalog.report.json`, `catalog.lock.json`, and the requested companions. Passing these files to a publisher does not replace that publisher's authority or DocSpec's guarded selection.

The existing `build_catalog` function delegates to the same assembly and returns `local_report` for compatibility. Supplying `output` uses the existing atomic directory writer and the same prepared bytes. A missing required result leaves the prior output set intact. Callers do not need to rebuild source definitions or reopen SQL to construct discovery metadata.

Use `local_catalog` for private writer validation that needs complete definitions while `catalog` supplies the public view. Both come from the same captured source snapshot. A public disclosure failure can leave the admitted private metadata available; structural admission failure leaves it `None`. This private field does not prepare another output set, and its presence does not establish qualification. `companions` and `artifacts` continue to follow the requested audience.

For a service that must keep native storage references private, request `include_private_artifacts=True` on an explicit public assembly. A passing result then supplies `local_artifacts` as a second standard set, using the same admitted definitions, metadata and original SQL bytes. The private lock records `urn:ddk:catalog:paired-public-view:1`: the exact public lock SHA-256, catalog ID, and explicit public/local aliases for each disclosed dataset ID. The public set contains neither that mapping nor the private lock. No second source load or data scan occurs. This option does not write the private set; stage each immutable set and configure both externally selected lock pins before starting a reader.

`ddk.catalog_delivery.load_catalog_artifacts` captures a complete standard set under byte and file limits, checks its schemas and digests, and rejects mixed, missing, extra, linked or special files. It never follows source-inventory locations or reads data payloads. `verify_catalog_pair(public, local)` requires both external pins and the private lock's exact public association; it also checks version, representation, recipe-input and SQL meaning. It returns the assembly's explicit alias mapping. Consumers must authorize client IDs from the public view and compare the observed native field tree against the public disclosed definition. The full private definition does not grant access to withheld fields. Partial field disclosure requires provider-level projection before unrestricted SQL can be offered.

## Recipes and definitions

Recipes preserve `title`, ordered `notes`, and explicit `parameterOrder`. The order must name each parameter property once. `contextualRelationships` links explanatory relationships without adding their endpoints to the query's actual inputs. Consumers can show the context without claiming that the query read those datasets.

The assembly details at `extensions["urn:ddk:catalog:assembly"]` retain resolved `datasetDefinitions`. Their `projectExtensions` records keep each source project's identifier, version, import namespace, and extension values separate. DDK preserves these values without interpreting application rules. Applications should read these admitted definitions directly rather than reconstructing a legacy metadata format from them.

## Application relationship reasoning

The [qualified dev4 package](local-release-dev4.md) adds an explicit `relationship_profile` argument to `assemble_catalog` and `build_catalog`. A profile supplies `identity`, an optional local `source` file, and `assess(ResolvedRelationship) -> RelationshipAssessment` from `ddk.catalog_semantics`.

The identity uses the existing tool-identity shape: an absolute `id`, exact `version`, and optional `commit` or `distributionSha256`. Supply a source file or an exact source/distribution pin. A source file must be within the permitted roots and document byte limit; the assembler reads its original bytes once for provenance. This records the supplied source, not a verified callable-to-source binding or its complete dependencies.

`ResolvedRelationship` contains the immutable declaration, ordered source keys, and ordered target keys, or `None` for an external target. Each `ResolvedKey` retains its path, native definition, shared comparison type when supported, and virtual scope. Return `RelationshipAssessment("supported", reason)`, `"failed"`, or `"unknown"`. Unsupported exact versions, types, and meanings must remain unknown.

DDK checks paths, complete keys, scopes and null policy before calling the profile. The shared `equal` rule also requires equal key counts and compatible known comparison types. A `project_rule` profile owns its matching shape, including different source and target component counts; complete unique endpoint keys still apply. DDK calls the profile only when additional declaration reasoning is needed. Exceptions and malformed results preserve unknown outcomes. The offline core neither loads nor invokes the profile; the application supplies it at catalog assembly.

Assembly details retain `relationshipProfile` and `relationshipAssessments`, with the selected identity also in adapter and lock provenance. Support describes expected comparison or reference construction. It establishes no actual matches, cardinality, data quality, or remote existence; external construction records `externalExistence: "not_assessed"`. Profile or assessment changes require metadata and applicable reader review, with unresolved domain effects kept separate from computation changes.

## Public views

Select a public view with an explicit disclosure policy. Its shape is defined in the [catalog schema](../schemas/0.1/catalog.schema.json). Existing identifier, alias, description, recipe, access, and evidence rules still apply. Definitions and project extensions remain withheld unless granted:

```json
{
  "definitionFields": {
    "urn:example:dataset": [[{"field": "groups"}, {"each": true}, {"field": "name"}]]
  },
  "projectExtensions": [{
    "project": {"id": "urn:example:project", "version": "1.0.0"},
    "extensions": ["urn:example:upstream-relations"]
  }]
}
```

This fragment adds grants to the ordinary policy. A field grant keeps selected fields and necessary structure, with supported types and nullability. Descriptions require `descriptions: true`. `disclosedDefinitionPaths` identifies the partial scope. Public output uses the disclosed object name and withholds unlisted siblings and private native properties. An extension grant permits its complete value, so its owner must decide whether that value belongs in the public view.

Use `definitionFields: {"urn:example:dataset": [[]]}` to grant root metadata only. With `descriptions: true`, this includes the root description without granting any child field or native/custom property. Empty paths remain invalid for identities and relationships.

Composite native type strings require a separate explicit grant:

```json
{
  "definitionPhysicalTypes": {
    "urn:example:dataset": [[{"field": "agencies"}]]
  }
}
```

Each nonempty path must resolve to an existing, nonblank `physicalType` in a disclosed dataset definition. Its complete modeled subtree must already appear through `definitionFields`; a parent field grant alone does not grant its children. An incoherent grant fails disclosure and preserves prior output. DDK copies the original type string exactly, without parsing or rewriting it.

This grant permits the entire opaque string, including any native-only names absent from the logical definition. The publisher must review that text. Modeled child coverage alone never permits it or establishes logical/native completeness. Object and array nodes remain composite even when their children are not modeled. Root `[]` grants no native type. Existing scalar type disclosure remains unchanged.

Logical-type options, such as integer bounds, timestamp formats and array limits, also require a separate explicit grant:

```json
{
  "definitionLogicalTypeOptions": {
    "urn:example:dataset": [[{"field": "agencies"}]]
  }
}
```

Each nonempty path must resolve to an existing `logicalTypeOptions` object, including an empty object, in a disclosed dataset definition. Its complete modeled subtree must already appear through `definitionFields`. DDK copies the entire options object exactly, including names in object `required` lists that have no modeled child. The publisher must review the complete value before granting it. Root, description, physical-type and parent-field grants do not grant these options or options on descendant fields. Invalid grants fail disclosure and preserve prior output. Publishing these declarations does not establish that a native reader supports them or that data passed their checks.

A public view using a relationship profile must explicitly grant the profile's exact identity ID in `identifiers`. Otherwise public assembly refuses output and preserves the full reason in `local_report`. This applies even when the ID is a `file://` URI: allowing its source record alone does not disclose its tool identity. Ordinary evidence policy still governs captured source locations.

Public output retains the granted profile identity and redacted source provenance so impact analysis can detect changes. Individual assessments and reasons stay withheld, with `relationshipAssessmentScope` explicitly unknown. Public consumer coverage also remains unknown; the comparison cannot infer private relationship or reader dependencies.

Use `report` for public responses, including early and incomplete failures. `local_report` and `local_catalog` can contain paths and private details and must stay internal.

## Required candidate integration

Use admitted definitions and companions to prepare the native request. Execute through DocSpec and retain its exact candidate and diagnostics. Accept the required evidence against that candidate, then assemble the qualified catalog from the accepted owner records. Finalize complete controls and select or publish through the existing authorities.

That complete managed sequence still needs a metadata profile. The current local adapter reads bounded-job output receipts and quality results for one exact file. It does not yet translate a managed candidate's accepted qualification or complete multi-output membership. Finalization must compare catalog versions and representations with the exact native candidate and output set; a passing definition-only catalog does not qualify unrelated files.

Static relationship support and executed data checks answer different questions. A native invariant does not make an unsupported comparison rule interpretable. Missing rule support and missing candidate evidence remain separate incomplete results. The [replacement plan](replacement-runtime-plan.md) tracks the additional relationship and multi-output profiles needed by the applications.
