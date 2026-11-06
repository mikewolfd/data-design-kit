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
| `catalog` | Structurally admitted, audience-filtered catalog, or `None` when admission failed |
| `companions` | Immutable mapping of catalog-relative paths to exact admitted SQL and other companion bytes |
| `artifacts` | Immutable mapping containing the complete standard output set, populated only when the report passes |

An admitted catalog can accompany `failed`, `unknown`, or `not_run` qualification. Check the report before treating data as qualified. `artifacts` includes `catalog.ddk.json`, `catalog.report.json`, `catalog.lock.json`, and the requested companions. Passing these files to a publisher does not replace that publisher's authority or DocSpec's guarded selection.

The existing `build_catalog` function delegates to the same assembly and returns `local_report` for compatibility. Supplying `output` uses the existing atomic directory writer and the same prepared bytes. A missing required result leaves the prior output set intact. Callers do not need to rebuild source definitions or reopen SQL to construct discovery metadata.

## Recipes and definitions

Recipes preserve `title`, ordered `notes`, and explicit `parameterOrder`. The order must name each parameter property once. `contextualRelationships` links explanatory relationships without adding their endpoints to the query's actual inputs. Consumers can show the context without claiming that the query read those datasets.

The assembly details at `extensions["urn:ddk:catalog:assembly"]` retain resolved `datasetDefinitions`. Their `projectExtensions` records keep each source project's identifier, version, import namespace, and extension values separate. DDK preserves these values without interpreting application rules. Applications should read these admitted definitions directly rather than reconstructing a legacy metadata format from them.

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

Use `report` for public responses, including early and incomplete failures. `local_report` can contain paths and private diagnostic details and must stay internal.

## Required candidate integration

Use admitted definitions and companions to prepare the native request. Execute through DocSpec and retain its exact candidate and diagnostics. Accept the required evidence against that candidate, then assemble the qualified catalog from the accepted owner records. Finalize complete controls and select or publish through the existing authorities.

That complete managed sequence still needs a metadata profile. The current local adapter reads bounded-job output receipts and quality results for one exact file. It does not yet translate a managed candidate's accepted qualification or complete multi-output membership. Finalization must compare catalog versions and representations with the exact native candidate and output set; a passing definition-only catalog does not qualify unrelated files.

Static relationship support and executed data checks answer different questions. A native invariant does not make an unsupported comparison rule interpretable. Missing rule support and missing candidate evidence remain separate incomplete results. The [replacement plan](replacement-runtime-plan.md) tracks the additional relationship and multi-output profiles needed by the applications.
