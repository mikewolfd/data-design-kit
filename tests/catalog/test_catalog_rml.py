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
    structures = rml_mappings(result.catalog)
    orders_mappings = structures["orders"][0]["mappings"]
    amount = orders_mappings["orders#field:amount_cents"]
    assert amount["s"] == "urn:example:commerce:dataset:orders:row:$(k0)"
    assert "graphs" not in amount  # no file is known, so the document is a template that claims no version
    assert 'WHERE "order_id" IS NOT NULL AND "amount_cents" IS NOT NULL' in amount["sources"][0]["query"]
    assert amount["po"] == [{"p": {"value": "urn:example:commerce:dataset:orders:field:amount_cents", "type": "iri"},
                             "o": {"value": "$(v0)", "datatype": "xsd:long"}}]
    customer_link = orders_mappings["orders#urn:example:commerce:relationship:customer"]
    assert customer_link["po"] == [{"p": {"value": "urn:example:commerce:relationship:customer", "type": "iri"},
                                    "o": {"value": "urn:example:commerce:dataset:customers:row:$(t0)", "type": "iri"}}]
    assert all(entry["p"]["type"] == "iri"
               for doc, _ in structures.values() for mapping in doc["mappings"].values() for entry in mapping["po"])
    files, limits = rml_documents(result.catalog)
    assert set(files) == {f"rml/{name}.yarrrml.yml" for name in ("customers", "daily-revenue", "orders")}
    assert {item["role"] for item in result.catalog["files"] if item["path"].startswith("rml/")} == {"mapping"}
    assert files["rml/orders.yarrrml.yml"].startswith(b"# YARRRML for urn:example:commerce:dataset:orders")
    assert b"# A template: it names no exact version" in files["rml/orders.yarrrml.yml"]
    assert b"na_values = \\uffff" in files["rml/orders.yarrrml.yml"]
    # Only daily-revenue's exact version has an available file; the other two are templates.
    revenue = structures["daily-revenue"][0]["mappings"]["daily-revenue#field:amount_cents"]
    assert revenue["graphs"] == {"value": "urn:example:commerce:version:daily-revenue:fixture-01", "type": "iri"}
    assert limits <= set(result.report["coverage"]["mappingLimits"]) and "2 of 3 RML documents" in next(iter(limits))


def test_rml_yaml_reads_back_as_the_mapping_structure():
    yaml = pytest.importorskip("yaml")
    catalog = _commerce("dcat").catalog
    structures = rml_mappings(catalog)
    for name, data in rml_documents(catalog)[0].items():
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
        "versions": [], "representations": [], "releases": [],
    }


def test_match_decisions_map_to_skos_matches_and_never_to_same_as():
    document, notes = rml_mappings(_decision_catalog())["matches"]
    decisions = {name.rpartition("#")[2]: mapping for name, mapping in document["mappings"].items()
                 if name.rpartition("#")[2] in {"same", "undecided", "not_same"}}
    assert {name: mapping["po"][0]["p"]["value"] for name, mapping in decisions.items()} == {
        "same": "http://www.w3.org/2004/02/skos/core#exactMatch",
        "undecided": "http://www.w3.org/2004/02/skos/core#closeMatch", "not_same": VOCAB + "noMatch"}
    assert all(mapping["s"] == {"value": "urn:ex:dataset:people-a:row:$(s0)", "type": "iri"}
               and mapping["po"][0]["o"] == {"value": "urn:ex:dataset:people-b:row:$(o0)", "type": "iri"}
               for mapping in decisions.values())
    assert """WHERE "decision" = 'not_same' AND "left_id" IS NOT NULL AND "right_id" IS NOT NULL""" in (
        decisions["not_same"]["sources"][0]["query"])
    assert "owl#sameAs" not in json.dumps(document)
    assert any("tags is not mapped: arrays of arrays" in note for note in notes)
    # Undeclared, the same table is an ordinary dataset: no decision is guessed from its shape.
    assert not [name for name in rml_mappings(_decision_catalog(declared=False))["matches"][0]["mappings"]
                if name.rpartition("#")[2] in {"same", "undecided", "not_same"}]


def test_rml_without_dataset_definitions_is_not_run():
    catalog = _decision_catalog()
    catalog["extensions"] = {}
    with pytest.raises(Exception) as error:
        rml_mappings(catalog)
    assert getattr(error.value, "status", None) == "not_run"


def _nested_catalog():
    """Stations with nested fields and arrays, keyless logs, and joins that are not on the target key.

    Each dataset has one exact version with a Parquet file, and all four share one release.
    """
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
    link = lambda name, source, sp, target, tp, match="equal", scope="same_release": {  # noqa: E731
        "id": f"urn:ex:relationship:{name}", "match": match, "scope": scope, "source": {"dataset": source, "paths": sp},
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
                link("log-station", "logs", [[{"field": "station_code"}]], "stations", [[{"field": "station_code"}]],
                     scope="version_pair"),
                link("ruled", "visits", [[{"field": "region"}]], "stations", [[{"field": "station_code"}]], "project_rule")],
            "concepts": [{"concept": "urn:ex:concept:region", "definition": "region", "fields": [
                {"dataset": alias, "path": [{"field": "region"}]} for alias in ("stations", "visits")]}],
            "versions": [{"id": f"urn:ex:version:{alias}:1", "dataset": alias} for alias in definitions],
            "representations": [{"id": f"urn:ex:file:{alias}:1", "version": f"urn:ex:version:{alias}:1", "kind": "file",
                                 "availability": "available", "mediaType": "application/vnd.apache.parquet",
                                 "location": f"file:///data/{alias}.parquet"} for alias in definitions],
            "releases": [{"id": "urn:ex:release:1", "members": [f"urn:ex:version:{alias}:1" for alias in definitions]}],
            "selections": []}


def test_views_map_nested_fields_array_items_keyless_rows_and_non_key_joins():
    documents = rml_mappings(_nested_catalog())
    stations, notes = documents["stations"]
    city = stations["mappings"]["stations#field:site:address:city"]
    latitude = stations["mappings"]["stations#field:site:latitude"]
    assert city["graphs"] == {"value": "urn:ex:version:stations:1", "type": "iri"}
    assert "read_parquet('/data/stations.parquet')" in city["sources"][0]["query"]
    assert "\"site\"['address']['city'] AS v0" in city["sources"][0]["query"]
    assert city["po"][0]["p"]["value"] == "urn:ex:dataset:stations:field:site:address:city"
    assert latitude["po"][0]["p"]["value"] == "urn:ex:dataset:stations:field:site:latitude"
    tags = stations["mappings"]["stations#array:tags"]
    assert 'UNNEST("tags") AS v0' in tags["sources"][0]["query"] and "WHERE v0 IS NOT NULL" in tags["sources"][0]["query"]
    sensors_rel = stations["mappings"]["stations#array:sensors"]
    assert "WHERE __ddk_item IS NOT NULL" in sensors_rel["sources"][0]["query"]
    # The row-to-item link filters null elements and never unpacks item leaf fields.
    assert "'kind'" not in sensors_rel["sources"][0]["query"]
    sensor_kind = stations["mappings"]["stations#item:sensors:kind"]
    assert sensor_kind["s"] == {"value": "urn:ex:dataset:stations:row:$(k0):sensors:$(i0)", "type": "iri"}
    assert "__ddk_item" in sensor_kind["sources"][0]["query"]
    link = stations["mappings"]["stations#array:tag_ids"]["po"][1]
    assert link == {"p": {"value": "urn:ex:relationship:station-tags", "type": "iri"},
                    "o": {"value": "urn:ex:dataset:tags:row:$(v0)", "type": "iri"}}
    visits, visit_notes = documents["visits"]
    join = visits["mappings"]["visits#urn:ex:relationship:visit-station"]["sources"][0]["query"]
    assert 'c."station_name" = p."name"' in join and 'c."region" = p."region"' in join
    assert "read_parquet('/data/visits.parquet')" in join and "read_parquet('/data/stations.parquet')" in join
    assert any("ruled is not mapped: a project rule" in note for note in visit_notes)
    assert visits["mappings"]["visits#concept:region"] == {
        "sources": [{"query": "SELECT 1 AS one"}], "s": {"value": "urn:ex:dataset:visits:field:region", "type": "iri"},
        "po": [{"p": {"value": "http://www.w3.org/2000/01/rdf-schema#subPropertyOf", "type": "iri"},
                "o": {"value": "urn:ex:concept:region", "type": "iri"}}], "graphs": {"value": "urn:ex:version:visits:1", "type": "iri"}}
    logs, _ = documents["logs"]
    log_msg = logs["mappings"]["logs#field:message"]
    assert "file_row_number = true" in log_msg["sources"][0]["query"]
    subject = log_msg["s"]
    assert subject["type"] == "blanknode" and subject["value"].endswith("_$(k0)")
    assert logs["mappings"]["logs#array:levels"]["s"] == subject  # one blank node per row across the document
    assert subject != documents["visits"][0]["mappings"]["visits#field:visit_id"]["s"]
    # Numbers are rendered as text by DuckDB, so a nullable integer key never becomes "5.0" in a template.
    assert 'CAST("site"[\'latitude\'] AS VARCHAR) AS v0' in latitude["sources"][0]["query"]
    log_link = logs["mappings"]["logs#urn:ex:relationship:log-station"]
    assert log_link["po"][0]["p"]["value"] == "urn:ex:relationship:log-station"
    assert log_link["s"] == subject


def test_joins_pair_bound_versions_only_within_their_scope():
    join = "visits#urn:ex:relationship:visit-station"
    apart = _nested_catalog()  # visits leaves the shared release, so a same-release join has no pair
    apart["releases"][0]["members"].remove("urn:ex:version:visits:1")
    apart["releases"].append({"id": "urn:ex:release:2", "members": ["urn:ex:version:visits:1"]})
    document, notes = rml_mappings(apart)["visits"]
    assert join not in document["mappings"] and any("share none" in note for note in notes)
    apart["relationships"][1]["scope"] = "version_pair"  # an explicit version pair accepts the bound versions
    assert join in rml_mappings(apart)["visits"][0]["mappings"]
    apart["relationships"][1]["scope"] = "declared"
    document, notes = rml_mappings(apart)["visits"]
    assert join not in document["mappings"] and any("declared scope" in note for note in notes)

    unbound = _nested_catalog()  # without a file, visits is a template: rows map, a join reading its file does not
    unbound["representations"] = [item for item in unbound["representations"] if "visits" not in item["id"]]
    document, notes = rml_mappings(unbound)["visits"]
    assert "graphs" not in document["mappings"]["visits#field:visit_id"] and join not in document["mappings"]
    assert notes[0].startswith("Template: Its exact version urn:ex:version:visits:1 has no available Parquet")
    assert any("one side is a template" in note for note in notes)
    assert "logs#urn:ex:relationship:log-station" in rml_mappings(unbound)["logs"][0]["mappings"]


def test_versions_bind_by_current_selection_and_never_by_order():
    catalog = _nested_catalog()
    catalog["versions"].append({"id": "urn:ex:version:stations:2", "dataset": "stations"})
    catalog["representations"].append({**catalog["representations"][0], "id": "urn:ex:file:stations:2",
                                       "version": "urn:ex:version:stations:2", "location": "file:///data/stations-2.parquet"})
    catalog["releases"].append({"id": "urn:ex:release:2", "members": ["urn:ex:version:stations:2"]})
    document, notes = rml_mappings(catalog)["stations"]
    assert "graphs" not in document["mappings"]["stations#field:station_code"]
    assert notes[0].startswith("Template: The catalog holds 2 versions of it; choose one with a current selection.")
    catalog["selections"] = [{"authority": "urn:ex:publisher", "purpose": "public", "release": "urn:ex:release:2"}]
    catalog["currentSelection"] = {"authority": "urn:ex:publisher", "purpose": "public"}
    documents = rml_mappings(catalog)
    station_field = documents["stations"][0]["mappings"]["stations#field:station_code"]
    assert station_field["graphs"]["value"] == "urn:ex:version:stations:2"
    assert "read_parquet('/data/stations-2.parquet')" in station_field["sources"][0]["query"]
    assert documents["tags"][1][0] == "Template: The current selection names no version of it. Every source reads " \
        "tags.parquet; point them at one exact version's file."


def test_integer_bounds_select_xsd_integer_only_within_32_bits_and_xsd_long_otherwise():
    catalog = {
        "id": "urn:ex:catalog",
        "datasets": [{"alias": "nums", "id": "urn:ex:dataset:nums", "role": "source_record"}],
        "extensions": {"urn:ddk:catalog:assembly": {"datasetDefinitions": {"nums": {"properties": [
            {"name": "id", "logicalType": "string"},
            {"name": "unbounded", "logicalType": "integer"},
            {"name": "bigint_col", "logicalType": "integer", "physicalType": "BIGINT"},
            {"name": "small_phys", "logicalType": "integer", "physicalType": "int32"},
            {"name": "u16_phys", "logicalType": "integer", "physicalType": "uint16"},
            {"name": "bounded_32", "logicalType": "integer",
             "logicalTypeOptions": {"minimum": -2147483648, "maximum": 4294967295}},
            {"name": "bounded_64", "logicalType": "integer",
             "logicalTypeOptions": {"minimum": 0, "maximum": 9007199254740993}},
        ]}}}},
        "identities": [{"dataset": "nums", "kind": "key", "fields": [{"path": [{"field": "id"}], "virtual": False}]}],
        "relationships": [], "versions": [], "representations": [], "releases": [],
    }
    mappings = rml_mappings(catalog)["nums"][0]["mappings"]
    datatypes = {
        name.rpartition("field:")[2]: (mapping["po"][0]["o"].get("datatype")
                                       if isinstance(mapping["po"][0]["o"], dict) else None)
        for name, mapping in mappings.items() if "#field:" in name
    }
    assert datatypes == {
        "id": None,
        "unbounded": "xsd:long",
        "bigint_col": "xsd:long",
        "small_phys": "xsd:integer",
        "u16_phys": "xsd:integer",
        "bounded_32": "xsd:integer",
        "bounded_64": "xsd:long",
    }


def test_public_rml_maps_only_disclosed_keyed_datasets_and_granted_paths(tmp_path):
    import shutil

    rdflib = pytest.importorskip("rdflib")
    root = tmp_path / "commerce"
    shutil.copytree(COMMERCE, root)
    baseline = assemble_catalog(root / "project.ddk.json", metadata=root / "catalog/metadata.example.json",
                                metadata_adapter="example")
    catalog = baseline.catalog
    identifiers = {catalog["id"], catalog["project"]["id"],
                   *(row["id"] for section in ("datasets", "products", "relationships", "versions", "representations")
                     for row in catalog[section]),
                   *(row["definition"]["contractId"] for row in catalog["datasets"])}

    # Case A: descriptions=True, orders discloses PK + amount_cents (withholding FK customer_id);
    # customers withholds PK customer_id; daily-revenue has no field grants at all.
    partial_policy = tmp_path / "partial.json"
    partial_policy.write_text(json.dumps({
        "identifiers": sorted(identifiers),
        "descriptions": True,
        "definitionFields": {
            "urn:example:commerce:dataset:orders": [[{"field": "order_id"}], [{"field": "amount_cents"}]],
            "urn:example:commerce:dataset:customers": [[{"field": "region"}]],
        },
    }), encoding="utf-8")
    partial = assemble_catalog(root / "project.ddk.json", metadata=root / "catalog/metadata.example.json",
                               metadata_adapter="example", disclosure_policy=partial_policy, exports=("rml",))
    assert partial.report["decision"] == "passed"
    rml_files = [name for name in partial.companions if name.startswith("rml/")]
    assert len(rml_files) == 1
    assert b"urn:example:commerce:dataset:orders" in partial.companions[rml_files[0]]
    all_bytes = b"".join(partial.artifacts.values())
    assert b"customer_id" not in all_bytes  # withheld PK/FK never leaks into identities, relationships or RML
    assert partial.report["coverage"]["mappingLimits"] == [
        "Mapping and evidence limits are retained in the local report."]
    assert any("urn:example:commerce:dataset:customers is not mapped in public RML" in limit
               for limit in partial.local_report["coverage"]["mappingLimits"])
    assert any("urn:example:commerce:dataset:daily-revenue is not mapped in public RML" in limit
               for limit in partial.local_report["coverage"]["mappingLimits"])

    # Case B: descriptions=False with granted keys + fields preserves non-virtual keys, row IRIs and candidate links.
    granted_policy = tmp_path / "granted.json"
    granted_policy.write_text(json.dumps({
        "identifiers": sorted(identifiers),
        "descriptions": False,
        "definitionFields": {
            "urn:example:commerce:dataset:orders": [[{"field": "order_id"}], [{"field": "customer_id"}], [{"field": "amount_cents"}]],
            "urn:example:commerce:dataset:customers": [[{"field": "customer_id"}], [{"field": "region"}]],
            "urn:example:commerce:dataset:daily-revenue": [[{"field": "order_day"}], [{"field": "region"}], [{"field": "amount_cents"}]],
        },
    }), encoding="utf-8")
    granted = assemble_catalog(root / "project.ddk.json", metadata=root / "catalog/metadata.example.json",
                               metadata_adapter="example", disclosure_policy=granted_policy, exports=("graph", "rml"))
    assert granted.report["decision"] == "passed"
    assert len(granted.catalog["identities"]) == 3
    public_rml = rml_mappings(granted.catalog)
    assert len(public_rml) == 3
    for doc, _ in public_rml.values():
        for mapping in doc["mappings"].values():
            if isinstance(mapping["s"], str):
                assert ":row:" in mapping["s"] and "$(k0)" in mapping["s"]
    graph = rdflib.Graph().parse(data=granted.companions["discovery.graph.jsonld"], format="json-ld")
    assert len(set(graph.subjects(rdflib.RDF.type, rdflib.URIRef("http://rdfs.org/ns/void#Linkset")))) == 0


def test_key_and_array_links_respect_scope_and_joins_handle_null_match_unknown_and_typed_arrays():
    catalog = _nested_catalog()
    # Direct-key link logs -> stations and array "each" link stations.tag_ids -> tags must obey declared/same_release scope.
    catalog["relationships"][0]["scope"] = "declared"
    catalog["relationships"][2]["scope"] = "declared"
    docs = rml_mappings(catalog)
    assert len(docs["stations"][0]["mappings"]["stations#array:tag_ids"]["po"]) == 1
    assert any("station-tags is not mapped: its declared scope" in n for n in docs["stations"][1])
    assert "logs#urn:ex:relationship:log-station" not in docs["logs"][0]["mappings"]
    assert any("log-station is not mapped: its declared scope" in n for n in docs["logs"][1])

    # Disjoint releases block bound same_release direct-key and array links too.
    disjoint = _nested_catalog()
    disjoint["relationships"][2]["scope"] = "same_release"
    disjoint["releases"] = [{"id": "urn:ex:release:a", "members": ["urn:ex:version:stations:1", "urn:ex:version:logs:1"]},
                            {"id": "urn:ex:release:b", "members": ["urn:ex:version:tags:1", "urn:ex:version:visits:1"]}]
    # Move logs into release:b so logs->stations is disjoint, and stations->tags is disjoint.
    disjoint["releases"][0]["members"].remove("urn:ex:version:logs:1")
    disjoint["releases"][1]["members"].append("urn:ex:version:logs:1")
    disjoint_docs = rml_mappings(disjoint)
    assert len(disjoint_docs["stations"][0]["mappings"]["stations#array:tag_ids"]["po"]) == 1
    assert "logs#urn:ex:relationship:log-station" not in disjoint_docs["logs"][0]["mappings"]

    # nulls="match" uses IS NOT DISTINCT FROM; nulls="unknown" skips with a note; integer array join casts elements.
    rich = _nested_catalog()
    rich["relationships"][1]["nulls"] = "match"
    rich["relationships"].append({
        "id": "urn:ex:relationship:unknown-nulls", "match": "equal", "scope": "same_release", "nulls": "unknown",
        "source": {"dataset": "visits", "paths": [[{"field": "region"}]]},
        "target": {"dataset": "stations", "paths": [[{"field": "region"}]]},
    })
    rich["extensions"]["urn:ddk:catalog:assembly"]["datasetDefinitions"]["visits"]["properties"].append(
        {"name": "codes", "logicalType": "array", "items": {"logicalType": "integer"}})
    rich["extensions"]["urn:ddk:catalog:assembly"]["datasetDefinitions"]["stations"]["properties"].append(
        {"name": "code", "logicalType": "integer"})
    rich["relationships"].append({
        "id": "urn:ex:relationship:visit-codes", "match": "equal", "scope": "same_release",
        "source": {"dataset": "visits", "paths": [[{"field": "codes"}, {"each": True}]]},
        "target": {"dataset": "stations", "paths": [[{"field": "code"}]]},
    })
    visits_doc, visits_notes = rml_mappings(rich)["visits"]
    match_sql = visits_doc["mappings"]["visits#urn:ex:relationship:visit-station"]["sources"][0]["query"]
    assert "IS NOT DISTINCT FROM" in match_sql
    assert "visits#urn:ex:relationship:unknown-nulls" not in visits_doc["mappings"]
    assert any("unknown-nulls is not mapped: its null handling is unknown" in n for n in visits_notes)
    code_sql = visits_doc["mappings"]["visits#urn:ex:relationship:visit-codes"]["sources"][0]["query"]
    assert 'CAST(UNNEST("codes") AS VARCHAR) AS __ddk_each' in code_sql
    assert 'c."__ddk_each" = CAST(p."code" AS VARCHAR)' in code_sql


def test_physical_names_special_field_characters_null_items_multi_fk_decisions_and_glob_paths():
    yaml = pytest.importorskip("yaml")
    catalog = {
        "id": "urn:ex:catalog",
        "datasets": [
            {"alias": "people-a", "id": "urn:ex:dataset:people-a", "role": "source_record"},
            {"alias": "people-b", "id": "urn:ex:dataset:people-b", "role": "source_record"},
            {"alias": "reviewers", "id": "urn:ex:dataset:reviewers", "role": "reference"},
            {"alias": "matches", "id": "urn:ex:dataset:matches", "role": "evidence"},
        ],
        "extensions": {"urn:ddk:catalog:assembly": {"datasetDefinitions": {
            "people-a": {"properties": [
                {"name": "id", "physicalName": "RAW_ID", "logicalType": "string"},
                {"name": "a.b", "logicalType": "string"},
                {"name": "a", "logicalType": "object", "properties": [{"name": "b", "logicalType": "string"}]},
                {"name": "weird{col}$name", "logicalType": "string"},
                {"name": "untyped_arr", "logicalType": "array"},
            ]},
            "people-b": {"properties": [{"name": "id", "logicalType": "string"}]},
            "reviewers": {"properties": [{"name": "id", "logicalType": "string"}]},
            "matches": {
                "properties": [
                    {"name": "match_id", "logicalType": "string"},
                    {"name": "left_id", "logicalType": "string"},
                    {"name": "right_id", "logicalType": "string"},
                    {"name": "reviewer_id", "logicalType": "string"},
                    {"name": "decision", "physicalName": "DECISION_COL", "logicalType": "string"},
                ],
                "customProperties": [{"vendor": "ddk", "property": "matchDecisions", "value": "decision"}],
            },
        }}},
        "identities": [{"dataset": alias, "kind": "key", "fields": [{"path": [{"field": field}], "virtual": False}]}
                       for alias, field in (("people-a", "id"), ("people-b", "id"),
                                            ("reviewers", "id"), ("matches", "match_id"))],
        "relationships": [
            {"id": "urn:ex:relationship:left", "source": {"dataset": "matches", "paths": [[{"field": "left_id"}]]},
             "target": {"dataset": "people-a", "paths": [[{"field": "id"}]]}},
            {"id": "urn:ex:relationship:right", "source": {"dataset": "matches", "paths": [[{"field": "right_id"}]]},
             "target": {"dataset": "people-b", "paths": [[{"field": "id"}]]}},
            {"id": "urn:ex:relationship:reviewer", "source": {"dataset": "matches", "paths": [[{"field": "reviewer_id"}]]},
             "target": {"dataset": "reviewers", "paths": [[{"field": "id"}]]}},
        ],
        "versions": [{"id": "urn:ex:version:people-a:1", "dataset": "people-a"}],
        "representations": [{"id": "urn:ex:file:people-a:1", "version": "urn:ex:version:people-a:1", "kind": "file",
                             "availability": "available", "mediaType": "application/vnd.apache.parquet",
                             "location": "file:///data/people[1].parquet"}],
        "releases": [],
    }
    docs = rml_mappings(catalog)
    pa_doc, pa_notes = docs["people-a"]
    # Glob character `[` in path prevents unsafe exact-version binding.
    assert "graphs" not in pa_doc["mappings"]["people-a#field:id"]
    assert any("glob characters" in note for note in pa_notes)
    # Physical column name RAW_ID is queried in SQL while logical `id` stays in the predicate IRI.
    id_map = pa_doc["mappings"]["people-a#field:id"]
    assert '"RAW_ID"' in id_map["sources"][0]["query"]
    assert id_map["po"][0]["p"]["value"] == "urn:ex:dataset:people-a:field:id"
    # Dotted top-level `a.b` and nested `a` -> `b` produce distinct mapping keys, and `{`/`$` names use `$(v0)`.
    assert "people-a#field:a.b" in pa_doc["mappings"] and "people-a#field:a:b" in pa_doc["mappings"]
    weird = pa_doc["mappings"]["people-a#field:weird%7Bcol%7D%24name"]
    assert weird["po"][0]["o"] == "$(v0)"
    assert any("untyped_arr is not mapped: its array element definition is absent" in n for n in pa_notes)

    # With 3 outgoing FKs, string shorthand refuses ambiguity; explicit {column, left, right} maps cleanly.
    _, match_notes = docs["matches"]
    assert "matches#same" not in docs["matches"][0]["mappings"]
    assert any("Match decisions are declared" in n for n in match_notes)
    catalog["extensions"]["urn:ddk:catalog:assembly"]["datasetDefinitions"]["matches"]["customProperties"] = [{
        "vendor": "ddk", "property": "matchDecisions",
        "value": {"column": "decision", "left": "urn:ex:relationship:left", "right": "urn:ex:relationship:right"},
    }]
    files, _ = rml_documents(catalog)
    for name, body in files.items():
        parsed = yaml.safe_load(body)
        assert "mappings" in parsed
    same = yaml.safe_load(files["rml/matches.yarrrml.yml"])["mappings"]["matches#same"]
    assert same["s"] == {"value": "urn:ex:dataset:people-a:row:$(s0)", "type": "iri"}
    assert '"DECISION_COL" = \'same\'' in same["sources"][0]["query"]

