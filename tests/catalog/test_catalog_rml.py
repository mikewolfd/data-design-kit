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
    assert orders["graphs"] == {"value": "$(_version)", "type": "iri"}
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


def _decision_catalog(role="evidence"):
    string = lambda name: {"name": name, "logicalType": "string"}  # noqa: E731
    return {
        "id": "urn:ex:catalog",
        "datasets": [{"alias": "people-a", "id": "urn:ex:dataset:people-a", "role": "source_record"},
                     {"alias": "people-b", "id": "urn:ex:dataset:people-b", "role": "source_record"},
                     {"alias": "matches", "id": "urn:ex:dataset:matches", "role": role}],
        "extensions": {"urn:ddk:catalog:assembly": {"datasetDefinitions": {
            "people-a": {"properties": [string("id")]}, "people-b": {"properties": [string("id")]},
            "matches": {"properties": [string("left_id"), string("right_id"), string("decision"),
                                       {"name": "tags", "logicalType": "array"}]}}}},
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
    assert "WHERE decision = 'not_same'" in decisions["not_same"]["sources"][0]["query"]
    assert "owl#sameAs" not in json.dumps(document)
    assert any("tags (array) is not mapped" in note for note in notes)
    assert len(rml_mappings(_decision_catalog(role="derived"))["matches"][0]["mappings"]) == 1


def test_rml_without_dataset_definitions_is_not_run():
    catalog = _decision_catalog()
    catalog["extensions"] = {}
    with pytest.raises(Exception) as error:
        rml_mappings(catalog)
    assert getattr(error.value, "status", None) == "not_run"
