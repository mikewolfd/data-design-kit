"""RML mappings (DDK-CATALOG-014): rows, values and links from the declarations, and match decisions."""

import json
from pathlib import Path

import pytest

from ddk.catalog import assemble_catalog
from ddk.catalog_graph import VOCAB, rml_documents, rml_mappings

COMMERCE = Path(__file__).resolve().parents[2] / "examples" / "commerce"


def _commerce(*exports):
    return assemble_catalog(COMMERCE / "project.ddk.json", metadata=COMMERCE / "catalog" / "metadata.example.json",
                            metadata_adapter="example", exports=exports)


def test_rml_maps_rows_values_and_links_from_the_declarations():
    result = _commerce("rml")
    assert result.report["decision"] == "passed" and {"catalog.rml"} <= set(result.report["coverage"]["completedProfiles"])
    mappings = {alias: document["mappings"][alias] for alias, (document, _) in rml_mappings(result.catalog).items()}
    orders = mappings["orders"]
    assert orders["s"] == "urn:example:commerce:dataset:orders:row:$(order_id)"
    assert orders["graphs"] == {"value": "urn:example:commerce:dataset:orders", "type": "iri"}  # no file is known
    by_predicate = {entry["p"]["value"]: entry["o"] for entry in orders["po"]}
    assert by_predicate["urn:example:commerce:dataset:orders:field:amount_cents"] == {
        "value": "$(amount_cents)", "datatype": "xsd:integer"}
    assert by_predicate["urn:example:commerce:relationship:customer"] == {
        "value": "urn:example:commerce:dataset:customers:row:$(customer_id)", "type": "iri"}
    assert all(entry["p"]["type"] == "iri" for mapping in mappings.values() for entry in mapping["po"])
    files = {name for name, _ in rml_documents(result.catalog).items()}
    assert files == {f"rml/{name}.yarrrml.yml" for name in ("customers", "daily-revenue", "orders")}
    assert {item["role"] for item in result.catalog["files"] if item["path"].startswith("rml/")} == {"mapping"}


def test_rml_yaml_reads_back_as_the_mapping_structure():
    yaml = pytest.importorskip("yaml")
    catalog = _commerce("dcat").catalog
    structures = rml_mappings(catalog)
    for name, data in rml_documents(catalog).items():
        alias = name.removeprefix("rml/").removesuffix(".yarrrml.yml")
        assert yaml.safe_load(data) == structures[alias][0]


def _decision_catalog(declared=True):
    string = lambda name: {"name": name, "logicalType": "string"}  # noqa: E731
    return {
        "id": "urn:ex:catalog",
        "datasets": [{"alias": "people-a", "id": "urn:ex:dataset:people-a", "role": "source_record"},
                     {"alias": "people-b", "id": "urn:ex:dataset:people-b", "role": "source_record"},
                     {"alias": "matches", "id": "urn:ex:dataset:matches", "role": "evidence"}],
        "extensions": {"urn:ddk:catalog:assembly": {"datasetDefinitions": {
            "people-a": {"properties": [string("id")]}, "people-b": {"properties": [string("id")]},
            "matches": {"properties": [string("left_id"), string("right_id"), string("decision"),
                                       {"name": "tags", "logicalType": "array", "items": {"logicalType": "array"}}],
                        **({"customProperties": [{"vendor": "ddk", "property": "matchDecisions", "value": "decision"}]}
                           if declared else {})}}}},
        "identities": [{"dataset": alias, "kind": "key", "fields": [{"path": [{"field": "id"}], "virtual": False}]}
                       for alias in ("people-a", "people-b")],
        "relationships": [
            {"id": f"urn:ex:relationship:{side}", "source": {"dataset": "matches", "paths": [[{"field": f"{side}_id"}]]},
             "target": {"dataset": f"people-{target}", "paths": [[{"field": "id"}]]}}
            for side, target in (("left", "a"), ("right", "b"))],
        "versions": [], "representations": [],
    }


def test_match_decisions_map_to_skos_matches_and_never_to_same_as():
    document, notes = rml_mappings(_decision_catalog())["matches"]
    decisions = {name.rpartition("#")[2]: mapping for name, mapping in document["mappings"].items() if "#" in name}
    assert {name: mapping["po"][0]["p"]["value"] for name, mapping in decisions.items()} == {
        "same": "http://www.w3.org/2004/02/skos/core#exactMatch",
        "undecided": "http://www.w3.org/2004/02/skos/core#closeMatch", "not_same": VOCAB + "noMatch"}
    assert all(mapping["s"] == "urn:ex:dataset:people-a:row:$(left_id)" and mapping["po"][0]["o"]["value"]
               == "urn:ex:dataset:people-b:row:$(right_id)" for mapping in decisions.values())
    assert """WHERE "decision" = 'not_same'""" in decisions["not_same"]["sources"][0]["query"]
    assert "owl#sameAs" not in json.dumps(document)
    assert any("tags is not mapped: arrays of arrays" in note for note in notes)
    # Undeclared, the same table is an ordinary dataset: no decision is guessed from its shape.
    assert not [name for name in rml_mappings(_decision_catalog(declared=False))["matches"][0]["mappings"] if "#" in name]


def test_rml_without_dataset_definitions_is_not_run():
    catalog = _decision_catalog()
    catalog["extensions"] = {}
    with pytest.raises(Exception) as error:
        rml_mappings(catalog)
    assert getattr(error.value, "status", None) == "not_run"


def _nested_catalog():
    """Stations with nested fields and arrays, keyless logs, and joins that are not on the target key."""
    s = lambda name, kind="string", **more: {"name": name, "logicalType": kind, **more}  # noqa: E731
    definitions = {
        "stations": {"properties": [
            s("station_code"), s("name"), s("region"),
            s("site", "object", properties=[s("latitude", "number"), s("address", "object", properties=[s("city")])]),
            s("tags", "array", items={"logicalType": "string"}),
            s("sensors", "array", items={"logicalType": "object", "properties": [s("kind"), s("serial")]}),
            s("tag_ids", "array", items={"logicalType": "string"})]},
        "tags": {"properties": [s("tag_id")]},
        "visits": {"properties": [s("visit_id"), s("station_name"), s("region")]},
        "logs": {"properties": [s("message"), s("station_code"), s("levels", "array", items={"logicalType": "string"})]},
    }
    keys = {"stations": ["station_code"], "tags": ["tag_id"], "visits": ["visit_id"]}
    link = lambda name, source, sp, target, tp, match="equal": {  # noqa: E731
        "id": f"urn:ex:relationship:{name}", "match": match, "source": {"dataset": source, "paths": sp},
        "target": {"dataset": target, "paths": tp}}
    return {"id": "urn:ex:catalog",
            "datasets": [{"alias": alias, "id": f"urn:ex:dataset:{alias}", "role": "source_record"} for alias in definitions],
            "extensions": {"urn:ddk:catalog:assembly": {"datasetDefinitions": definitions}},
            "identities": [{"dataset": alias, "kind": "key", "fields": [{"path": [{"field": f}], "virtual": False} for f in key]}
                           for alias, key in keys.items()],
            "relationships": [
                link("station-tags", "stations", [[{"field": "tag_ids"}, {"each": True}]], "tags", [[{"field": "tag_id"}]]),
                link("visit-station", "visits", [[{"field": "station_name"}], [{"field": "region"}]],
                     "stations", [[{"field": "name"}], [{"field": "region"}]]),
                link("log-station", "logs", [[{"field": "station_code"}]], "stations", [[{"field": "station_code"}]]),
                link("ruled", "visits", [[{"field": "region"}]], "stations", [[{"field": "station_code"}]], "project_rule")],
            "versions": [], "representations": []}


def test_views_map_nested_fields_array_items_keyless_rows_and_non_key_joins():
    documents = rml_mappings(_nested_catalog())
    stations, notes = documents["stations"]
    fields = stations["mappings"]["stations#fields"]
    assert "\"site\"['address']['city'] AS \"site.address.city\"" in fields["sources"][0]["query"]
    assert {entry["p"]["value"] for entry in fields["po"]} == {
        "urn:ex:dataset:stations:field:site:latitude", "urn:ex:dataset:stations:field:site:address:city"}
    tags = stations["mappings"]["stations#tags"]
    assert 'UNNEST("tags") AS "tags"' in tags["sources"][0]["query"]
    items = stations["mappings"]["stations#sensors.items"]
    assert items["s"] == "urn:ex:dataset:stations:row:$(station_code):sensors:$(sensors.__index)"
    link = stations["mappings"]["stations#tag_ids"]["po"][1]
    assert link == {"p": {"value": "urn:ex:relationship:station-tags", "type": "iri"},
                    "o": {"value": "urn:ex:dataset:tags:row:$(tag_ids)", "type": "iri"}}
    visits, visit_notes = documents["visits"]
    join = visits["mappings"]["visits#urn:ex:relationship:visit-station"]["sources"][0]["query"]
    assert 'c."station_name" = p."name"' in join and 'c."region" = p."region"' in join
    assert any("ruled is not mapped: a project rule" in note for note in visit_notes)
    logs, _ = documents["logs"]
    assert logs["mappings"]["logs"]["sources"][0]["query"].startswith('SELECT * FROM (SELECT row_number() OVER ()')
    assert logs["mappings"]["logs"]["s"] == {"value": "logs_$(__ddk_row)", "type": "blanknode"}
    assert logs["mappings"]["logs#levels"]["s"] == logs["mappings"]["logs"]["s"]
    assert logs["mappings"]["logs"]["po"][-1]["p"]["value"] == "urn:ex:relationship:log-station"
