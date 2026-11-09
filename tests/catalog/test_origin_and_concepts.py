"""Origin detail and model method records (DDK-CATALOG-003), method columns, and shared-definition concepts
(DDK-CATALOG-004, -013, -014). Expectations come from the edited declarations, not from the code under test."""

import json
from pathlib import Path
import shutil

import pytest

from ddk.catalog import assemble_catalog
from ddk.catalog_graph import VOCAB, candidate_links, rml_mappings
from ddk.core import check_project

ROOT = Path(__file__).resolve().parents[2]
LAYERED, COMMERCE = ROOT / "examples" / "layered", ROOT / "examples" / "commerce"


def _copy(source, tmp_path):
    target = tmp_path / source.name
    shutil.copytree(source, target)
    return target


def _edit(path, change):
    value = json.loads(path.read_bytes())
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def _checks(result, suffix):
    return [item for item in result.report["checks"] if item["subject"].endswith(suffix)]


def test_derived_origin_is_read_but_its_detail_stays_unknown(tmp_path):
    layered = _copy(LAYERED, tmp_path)
    _edit(layered / "product/project.ddk.json", lambda value: value["artifacts"]["station-summary"].update(origin="derived"))
    result = assemble_catalog(layered / "project.ddk.json")
    assert result.report["decision"] == "passed"
    check, = _checks(result, "product/station-summary/origin")
    assert (check["status"], check["required"], check["diagnostics"][0]["code"]) == (
        "unknown", False, "CATALOG-ORIGIN-DETAIL")


def test_model_method_record_completes_origin_evidence_and_becomes_provenance(tmp_path):
    rdflib = pytest.importorskip("rdflib")
    complete = assemble_catalog(LAYERED / "project.ddk.json", exports=("dcat", "graph"))
    check, = _checks(complete, "resolved/stations/origin")
    assert check["status"] == "passed"
    graph = rdflib.Graph().parse(data=complete.companions["discovery.graph.jsonld"], format="json-ld")
    prov = rdflib.Namespace("http://www.w3.org/ns/prov#")
    stations = rdflib.URIRef("urn:example:layered:dataset:stations")
    model = graph.value(stations, prov.wasAttributedTo)
    assert (model, rdflib.RDF.type, prov.SoftwareAgent) in graph
    sha = json.loads((LAYERED / "resolved/project.ddk.json").read_bytes())["artifacts"]["stations"]["model"]["configurationSha256"]
    assert graph.value(model, rdflib.DCTERMS.identifier) == rdflib.Literal("sha256:" + sha)
    review = graph.value(predicate=prov.used, object=stations)
    assert graph.value(review, rdflib.DCTERMS.type) == rdflib.URIRef(VOCAB + "review-spot_checked")
    assert (graph.value(review, prov.wasAssociatedWith), rdflib.RDF.type, prov.Person) in graph

    layered = _copy(LAYERED, tmp_path)
    _edit(layered / "resolved/project.ddk.json",
          lambda value: value["artifacts"]["stations"]["model"].pop("configurationSha256"))
    partial = assemble_catalog(layered / "project.ddk.json")
    check, = _checks(partial, "resolved/stations/origin")
    assert (check["status"], check["diagnostics"][0]["code"]) == ("unknown", "CATALOG-ORIGIN-METHOD")
    assert "configurationSha256" in check["diagnostics"][0]["message"]
    _edit(layered / "product/project.ddk.json", lambda value: value["artifacts"]["station-summary"].update(
        model={"id": "m", "version": "1", "review": "reviewed"}))
    assert "DOC-SCHEMA" in {d["code"] for c in check_project(layered / "project.ddk.json")["checks"] for d in c["diagnostics"]}


def _method_column(layered, values):
    def change(document):
        obj = document["schema"][0]
        obj["customProperties"] = [{"vendor": "ddk", "property": "methodColumn", "value": "method"}]
        obj["properties"].append({"name": "method", "logicalType": "string", "quality": [
            {"type": "library", "metric": "invalidValues", "arguments": {"validValues": values}, "mustBe": 0}]})
    _edit(layered / "product/summary.odcs.json", change)


def test_method_column_values_come_from_the_vocabulary_and_attribute_each_row(tmp_path):
    layered = _copy(LAYERED, tmp_path)
    _method_column(layered, ["rule", "exact_identifier", "human"])
    result = assemble_catalog(layered / "project.ddk.json", exports=("dcat", "graph", "rml"))
    assert result.report["decision"] == "passed"
    summary = next(row for row in result.catalog["datasets"] if row["alias"] == "product/station-summary")
    assert summary["methodColumn"] == "method"
    document, _ = rml_mappings(result.catalog)["product/station-summary"]
    attribution = [entry for entry in document["mappings"]["product/station-summary"]["po"]
                   if entry["p"]["value"] == "http://www.w3.org/ns/prov#wasAttributedTo"]
    assert attribution == [{"p": {"value": "http://www.w3.org/ns/prov#wasAttributedTo", "type": "iri"},
                            "o": {"value": "urn:example:layered:dataset:station-summary:agent:$(method)", "type": "iri"}}]
    text = result.companions["discovery.graph.jsonld"].decode()
    assert "ddkv:origin-exact_identifier" in text and "ddkv:methodColumn" in text

    bad = _copy(LAYERED, tmp_path / "bad")
    _method_column(bad, ["rule", "crowd"])
    check, = _checks(assemble_catalog(bad / "project.ddk.json"), "product/station-summary/method-column")
    assert (check["status"], check["diagnostics"][0]["code"]) == ("failed", "CATALOG-METHOD-COLUMN")
    assert "crowd" in check["diagnostics"][0]["message"]


def test_concepts_list_every_field_that_inherits_a_definition_and_reach_graph_and_mappings():
    rdflib = pytest.importorskip("rdflib")
    result = assemble_catalog(COMMERCE / "project.ddk.json", exports=("dcat", "graph", "rml"))
    concept, = result.catalog["concepts"]
    assert concept["definition"] == "amount-cents" and concept["concept"] == "urn:example:commerce:catalog:concept:amount-cents"
    assert sorted(field["dataset"] for field in concept["fields"]) == ["daily-revenue", "orders"]
    graph = rdflib.Graph().parse(data=result.companions["discovery.graph.jsonld"], format="json-ld")
    iri = rdflib.URIRef(concept["concept"])
    assert (iri, rdflib.RDF.type, rdflib.URIRef("http://www.w3.org/2004/02/skos/core#Concept")) in graph
    assert set(graph.subjects(rdflib.RDFS.subPropertyOf, iri)) == {
        rdflib.URIRef(f"urn:example:commerce:dataset:{alias}:field:amount_cents") for alias in ("orders", "daily-revenue")}
    orders, _ = rml_mappings(result.catalog)["orders"]
    assert [entry["o"] for entry in orders["mappings"]["orders"]["po"] if entry["p"]["value"] == concept["concept"]] == [
        {"value": "$(amount_cents)", "datatype": "xsd:integer"}]


def _definitions_on_customer_ids(commerce, *, customer="customer-key", region="region-key"):
    for name, text in ((customer, "A customer identifier."), (region, "A region code.")):
        (commerce / f"definitions/{name}.json").write_text(json.dumps({"logicalType": "string", "description": text}))
        _edit(commerce / "project.ddk.json", lambda value, name=name: value["artifacts"].update(
            {name: {"kind": "definition", "path": f"definitions/{name}.json"}}))

    def attach(document):
        for obj, name in (("orders", customer), ("customers", region)):
            prop = next(p for o in document["schema"] if o["name"] == obj for p in o["properties"] if p["name"] == "customer_id")
            prop["authoritativeDefinitions"] = [{"type": "definition", "url": f"../definitions/{name}.json"}]
    _edit(commerce / "datasets/commerce.odcs.json", attach)


def test_a_join_between_different_definitions_warns_and_a_policy_can_make_it_an_error(tmp_path):
    commerce = _copy(COMMERCE, tmp_path)
    _definitions_on_customer_ids(commerce)
    warned = assemble_catalog(commerce / "project.ddk.json")
    check, = _checks(warned, "urn:example:commerce:relationship:customer/concepts")
    assert (warned.report["decision"], check["status"], check["required"]) == ("passed", "unknown", False)
    assert check["diagnostics"][0]["code"] == "CATALOG-RELATIONSHIP-CONCEPT"

    policy = commerce / "policies"
    policy.mkdir(exist_ok=True)
    rule = {"id": "joins", "check": "concept-joins", "severity": "error"}
    (policy / "joins.ddk.json").write_text(json.dumps({"specVersion": "0.1", "kind": "policy", "id": "urn:test:joins",
                                                     "version": "1.0.0", "rules": [rule]}))
    _edit(commerce / "project.ddk.json", lambda value: value["artifacts"].update(
        joins={"kind": "policy", "path": "policies/joins.ddk.json"}))
    failed = assemble_catalog(commerce / "project.ddk.json")
    check, = _checks(failed, "urn:example:commerce:relationship:customer/concepts")
    assert (failed.report["decision"], check["status"], check["required"]) == ("failed", "failed", True)

    rule["compatible"] = [["customer-key", "region-key"]]
    (policy / "joins.ddk.json").write_text(json.dumps({"specVersion": "0.1", "kind": "policy", "id": "urn:test:joins",
                                                     "version": "1.0.0", "rules": [rule]}))
    allowed = assemble_catalog(commerce / "project.ddk.json")
    check, = _checks(allowed, "urn:example:commerce:relationship:customer/concepts")
    assert (allowed.report["decision"], check["status"]) == ("passed", "passed")


def test_public_concepts_keep_only_granted_fields():
    result = assemble_catalog(COMMERCE / "project.ddk.json")
    catalog = json.loads(json.dumps(result.catalog))
    from ddk.catalog_output import _public_concepts

    public = _public_concepts(catalog["concepts"], {"orders": "orders"}, {"orders": [[{"field": "amount_cents"}]]},
                              {"aliases": [], "descriptions": False, "locations": []})
    assert public == [{"concept": "urn:example:commerce:catalog:concept:amount-cents",
                       "definition": public[0]["definition"], "fields": [{"dataset": "orders", "path": [{"field": "amount_cents"}]}]}]
    assert public[0]["definition"].startswith("public-")
    assert not _public_concepts(catalog["concepts"], {"orders": "orders"}, {"orders": [[{"field": "order_id"}]]},
                                {"aliases": [], "descriptions": False, "locations": []})


def test_candidate_links_anchor_on_keys_and_skip_declared_joins():
    concept = "urn:ex:concept:committee"
    catalog = {
        "concepts": [{"concept": concept, "definition": "committee", "fields": [
            {"dataset": alias, "path": [{"field": "committee_id"}]} for alias in ("committees", "filings", "loans", "joined")]}],
        "identities": [{"dataset": "committees", "kind": "key", "fields": [{"path": [{"field": "committee_id"}]}]},
                       {"dataset": "filings", "kind": "key", "fields": [{"path": [{"field": "filing_id"}]}]}],
        "relationships": [{"source": {"dataset": "joined"}, "target": {"dataset": "committees"}}],
    }
    assert candidate_links(catalog) == [("filings", "committees", concept), ("loans", "committees", concept)]
