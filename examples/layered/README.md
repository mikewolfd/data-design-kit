# Layered map example

An independently authored map of weather-station data in four layers. Each layer is its own DDK project:

| Layer | Project | Holds |
| --- | --- | --- |
| capture | `capture/` | Retained station files, role `original` |
| source | `source/` | One table per publisher record type, role `source_record` |
| resolved | `resolved/` | Stations matched across networks, role `derived` |
| product | `product/` | A summary that answers one user question, role `application` |

The root `project.ddk.json` has no artifacts of its own. It imports every layer, and each layer imports the one below it, so `source` is reachable both as `source` and as `resolved/source`. DDK loads each project once, at its shortest import path, and records the longer paths as import aliases ([DDK-REF-002](../../docs/specification.md#DDK-REF-002)).

The `governance` project holds a `layer-order` policy over the root namespaces ([DDK-POLICY-006](../../docs/specification.md#DDK-POLICY-006)). It is meaningful only when loaded from the root.

Other behaviour shown here:

- `source/readings.odcs.json` marks `temperature_c` as a view over the stored `payload` property ([DDK-DATA-006](../../docs/specification.md#DDK-DATA-006)). Its `station_code` links to a remote glossary page, which stays a documentation reference ([DDK-REF-004](../../docs/specification.md#DDK-REF-004)).
- Dataset registrations declare `attribution`. `resolved/stations` lists a `model` derivation, so its values must not be presented as a publisher's assertion ([DDK-CATALOG-003](../../docs/specification.md#DDK-CATALOG-003)).
- The catalog carries each product's ODPS type, status and descriptions, and each dataset's contract description, context, tags, canonical URL and applicable SLA entries. The `retention` SLA entry names another object and is not attached to `readings`.

```sh
ddk check examples/layered/project.ddk.json --format json
ddk catalog examples/layered/project.ddk.json --format json --export dcat --output /outside/repository/layered-catalog
```

The tests in `tests/core/test_layered_imports.py` and `tests/catalog/test_layered_catalog.py` state the expected results independently.
