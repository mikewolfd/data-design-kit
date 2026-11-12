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
    attribution = graph.value(stations, prov.qualifiedAttribution)
    assert set(graph.objects(attribution, rdflib.DCTERMS.type)) == {rdflib.URIRef(VOCAB + "evidence-declared")}

    layered = _copy(LAYERED, tmp_path)
    _edit(layered / "resolved/project.ddk.json",
          lambda value: value["artifacts"]["stations"]["model"].pop("configurationSha256"))
    partial = assemble_catalog(layered / "project.ddk.json", exports=("dcat", "graph"))
    check, = _checks(partial, "resolved/stations/origin")
    assert (check["status"], check["diagnostics"][0]["code"]) == ("unknown", "CATALOG-ORIGIN-METHOD")
    assert "configurationSha256" in check["diagnostics"][0]["message"]
    # The graph keeps that unknown: no configured software agent, and the attribution says why.
    graph = rdflib.Graph().parse(data=partial.companions["discovery.graph.jsonld"], format="json-ld")
    assert not set(graph.subjects(rdflib.RDF.type, prov.SoftwareAgent))
    attribution = graph.value(stations, prov.qualifiedAttribution)
    assert set(graph.objects(attribution, rdflib.DCTERMS.type)) == {
        rdflib.URIRef(VOCAB + "evidence-declared"), rdflib.URIRef(VOCAB + "outcome-unknown")}
    assert "configurationSha256" in str(graph.value(attribution, rdflib.RDFS.comment))
    _edit(layered / "product/project.ddk.json", lambda value: value["artifacts"]["station-summary"].update(
        model={"id": "m", "version": "1", "review": "reviewed"}))
    assert "DOC-SCHEMA" in {d["code"] for c in check_project(layered / "project.ddk.json")["checks"] for d in c["diagnostics"]}


def _method_column(layered, values, finer=None):
    def change(document):
        obj = document["schema"][0]
        obj["customProperties"] = [{"vendor": "ddk", "property": "methodColumn", "value": "method"}]
        prop = {"name": "method", "logicalType": "string"}
        if values is not None:
            prop["quality"] = [{"type": "library", "metric": "invalidValues",
                                "arguments": {"validValues": values}, "mustBe": 0}]
        if finer is not None:
            prop["customProperties"] = [{"vendor": "ddk", "property": "methodOrigins", "value": finer}]
        obj["properties"].append(prop)
    _edit(layered / "product/summary.odcs.json", change)


def test_method_column_values_are_origins_or_map_to_one_and_attribute_each_row(tmp_path):
    rdflib = pytest.importorskip("rdflib")
    layered = _copy(LAYERED, tmp_path)
    _method_column(layered, ["rule", "exact_identifier", "human"], finer={"exact_identifier": "rule"})
    result = assemble_catalog(layered / "project.ddk.json", exports=("dcat", "graph", "rml"))
    assert result.report["decision"] == "passed"
    summary = next(row for row in result.catalog["datasets"] if row["alias"] == "product/station-summary")
    assert summary["methodColumn"] == "method"
    document, _ = rml_mappings(result.catalog)["product/station-summary"]
    attribution = document["mappings"]["product/station-summary#method"]["po"]
    assert attribution == [{"p": {"value": "http://www.w3.org/ns/prov#wasAttributedTo", "type": "iri"},
                            "o": {"value": "urn:example:layered:dataset:station-summary:agent:$(v0)", "type": "iri"}}]
    graph = rdflib.Graph().parse(data=result.companions["discovery.graph.jsonld"], format="json-ld")
    agent = rdflib.URIRef("urn:example:layered:dataset:station-summary:agent:exact_identifier")
    # A finer method keeps its own name and is typed by the origin the column maps it to.
    assert (graph.value(agent, rdflib.RDFS.label), graph.value(agent, rdflib.DCTERMS.type)) == (
        rdflib.Literal("exact_identifier"), rdflib.URIRef(VOCAB + "origin-rule"))

    for name, values, finer, expected_token in (
        ("unmapped", ["rule", "crowd"], None, "crowd"),
        ("not-an-origin", ["crowd"], {"crowd": "magic"}, "crowd"),
        ("missing-enum", None, None, "no `enum` values"),
        ("extra-key", ["rule"], {"ghost": "rule"}, "ghost"),
        ("contradicts-builtin", ["rule"], {"rule": "human"}, "rule"),
    ):
        bad = _copy(LAYERED, tmp_path / name)
        _method_column(bad, values, finer)
        bad_result = assemble_catalog(bad / "project.ddk.json")
        check, = _checks(bad_result, "product/station-summary/method-column")
        assert (check["status"], check["diagnostics"][0]["code"]) == ("failed", "CATALOG-METHOD-COLUMN")
        assert expected_token in check["diagnostics"][0]["message"]
        if name == "missing-enum":
            # Guard RML against dangling agent IRIs even if rml_mappings is called on an unenumerated methodColumn.
            raw_cat = json.loads(json.dumps(result.catalog))
            defs = raw_cat["extensions"]["urn:ddk:catalog:assembly"]["datasetDefinitions"]["product/station-summary"]
            next(p for p in defs["properties"] if p["name"] == "method").pop("quality", None)
            assert "product/station-summary#method" not in rml_mappings(raw_cat)["product/station-summary"][0]["mappings"]


def test_concepts_list_every_field_that_inherits_a_definition_and_reach_graph_and_mappings():
    rdflib = pytest.importorskip("rdflib")
    result = assemble_catalog(COMMERCE / "project.ddk.json", exports=("dcat", "graph", "rml"))
    concept, = result.catalog["concepts"]
    assert concept["definition"] == "amount-cents" and concept["concept"] == "urn:example:commerce:catalog:concept:amount-cents"
    assert concept["conceptKind"] == "attribute"
    assert sorted(field["dataset"] for field in concept["fields"]) == ["daily-revenue", "orders"]
    graph = rdflib.Graph().parse(data=result.companions["discovery.graph.jsonld"], format="json-ld")
    iri = rdflib.URIRef(concept["concept"])
    assert (iri, rdflib.RDF.type, rdflib.URIRef("http://www.w3.org/2004/02/skos/core#Concept")) in graph
    assert (iri, rdflib.DCTERMS.type, rdflib.URIRef(VOCAB + "concept-kind-attribute")) in graph
    assert set(graph.subjects(rdflib.RDFS.subPropertyOf, iri)) == {
        rdflib.URIRef(f"urn:example:commerce:dataset:{alias}:field:amount_cents") for alias in ("orders", "daily-revenue")}
    orders, _ = rml_mappings(result.catalog)["orders"]
    # Rows keep only the field's own predicate; one statement per field links it to the concept.
    assert not [entry for mapping in orders["mappings"].values() for entry in mapping["po"]
                if entry["p"]["value"] == concept["concept"]]
    assert orders["mappings"]["orders#concept:amount_cents"]["s"]["value"] == (
        "urn:example:commerce:dataset:orders:field:amount_cents")
    assert orders["mappings"]["orders#concept:amount_cents"]["po"] == [
        {"p": {"value": str(rdflib.RDFS.subPropertyOf), "type": "iri"}, "o": {"value": concept["concept"], "type": "iri"}}]


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
    assert (warned.report["decision"], check["status"], check["required"]) == ("passed", "failed", False)
    assert [(item["code"], item["severity"]) for item in check["diagnostics"]] == [("CATALOG-RELATIONSHIP-CONCEPT", "warning")]

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


def test_a_concept_joins_rule_governs_only_the_relationships_its_own_project_declares(tmp_path):
    layered = _copy(LAYERED, tmp_path)
    for name in ("hash-a", "hash-b"):
        (layered / f"source/{name}.json").write_text(json.dumps({"logicalType": "string", "description": f"A {name}."}))
    _edit(layered / "source/project.ddk.json", lambda value: value["artifacts"].update(
        {name: {"kind": "definition", "path": f"{name}.json"} for name in ("hash-a", "hash-b")}))

    def attach(document, url):
        prop = next(p for p in document["schema"][0]["properties"] if p["name"] == "file_sha256")
        prop["authoritativeDefinitions"] = [{"type": "definition", "url": url}]
    _edit(layered / "source/readings.odcs.json", lambda document: attach(document, "hash-a.json"))
    _edit(layered / "capture/captures.odcs.json", lambda document: attach(document, "../source/hash-b.json"))

    def require(project):
        (layered / project / "joins.ddk.json").write_text(json.dumps({
            "specVersion": "0.1", "kind": "policy", "id": f"urn:test:joins:{project}", "version": "1.0.0",
            "rules": [{"id": "joins", "check": "concept-joins", "severity": "error"}]}))
        _edit(layered / project / "project.ddk.json", lambda value: value["artifacts"].update(
            joins={"kind": "policy", "path": "joins.ddk.json"}))

    subject = "urn:example:layered:relationship:reading-file/concepts"
    require("resolved")  # another layer's rule leaves the source layer's join a warning
    check, = _checks(assemble_catalog(layered / "project.ddk.json"), subject)
    assert (check["status"], check["required"]) == ("failed", False)
    require("source")
    result = assemble_catalog(layered / "project.ddk.json")
    check, = _checks(result, subject)
    assert (check["status"], check["required"], result.report["decision"]) == ("failed", True, "failed")


def test_public_concepts_keep_only_granted_fields():
    result = assemble_catalog(COMMERCE / "project.ddk.json")
    catalog = json.loads(json.dumps(result.catalog))
    from ddk.catalog_output import _public_concepts

    policy = {"aliases": [], "descriptions": False, "locations": [], "identifiers": []}
    public = _public_concepts(catalog["concepts"], {"orders": "orders"}, {"orders": [[{"field": "amount_cents"}]]},
                              policy, catalog["id"])
    definition = public[0]["definition"]
    assert definition.startswith("public-")
    # The minted IRI named the private definition alias; the public view mints it again from the public alias.
    assert public == [{"concept": f"urn:example:commerce:catalog:concept:{definition}", "definition": definition,
                       "conceptKind": "attribute",
                       "fields": [{"dataset": "orders", "path": [{"field": "amount_cents"}]}]}]
    assert not _public_concepts(catalog["concepts"], {"orders": "orders"}, {"orders": [[{"field": "order_id"}]]},
                                policy, catalog["id"])


def test_candidate_links_anchor_on_keys_and_skip_declared_joins():
    concept = "urn:ex:concept:committee"
    catalog = {
        "concepts": [{"concept": concept, "definition": "committee", "fields": [
            {"dataset": alias, "path": [{"field": "committee_id"}]} for alias in ("committees", "filings", "loans", "joined")]}],
        "identities": [{"dataset": "committees", "kind": "key", "fields": [{"path": [{"field": "committee_id"}], "virtual": False}]},
                       {"dataset": "filings", "kind": "key", "fields": [{"path": [{"field": "filing_id"}], "virtual": False}]}],
        "relationships": [{"source": {"dataset": "joined", "paths": [[{"field": "committee_id"}]]},
                           "target": {"dataset": "committees", "paths": [[{"field": "committee_id"}]]}}],
    }
    assert candidate_links(catalog) == [("filings", "committees", concept), ("loans", "committees", concept)]
    # A concept no declared relationship joins on, such as a shared date format, offers no candidates.
    catalog["relationships"] = []
    assert candidate_links(catalog) == []


def test_public_view_withholds_model_records_and_method_columns(tmp_path):
    """The model record names a reviewer and the method column names a field; neither has a disclosure grant."""
    layered = _copy(LAYERED, tmp_path)
    _method_column(layered, ["rule", "human"])
    datasets = {f"urn:example:layered:dataset:{name}": f"urn:example:layered:contract:{contract}" for name, contract in (
        ("captures", "captures"), ("readings", "readings"), ("stations", "stations"), ("station-summary", "summary"))}
    products = [f"urn:example:layered:product:{name}" for name in ("captures", "readings", "stations", "summary")]
    policy = tmp_path / "public.json"
    policy.write_text(json.dumps({"identifiers": ["urn:example:layered:catalog", "urn:example:layered:map", *products,
                                                  *datasets, *datasets.values()]}))
    result = assemble_catalog(layered / "project.ddk.json", disclosure_policy=policy, exports=("graph", "rml"),
                              output=tmp_path / "out")
    assert result.report["decision"] == "passed"
    assert not [row for row in result.catalog["datasets"] if "model" in row or "methodColumn" in row]
    written = b"".join(path.read_bytes() for path in (tmp_path / "out").rglob("*") if path.is_file())
    assert b"Example reviewer" not in written and b"example-site-matcher" not in written
    assert b"outcome-unknown" not in written


def test_concept_kind_warns_when_missing_on_concept_definition_and_refuses_invalid_or_duplicate(tmp_path):
    rdflib = pytest.importorskip("rdflib")
    commerce = _copy(COMMERCE, tmp_path / "missing-kind")
    def_path = commerce / "definitions" / "customer-id.json"
    def_path.write_text(json.dumps({
        "logicalType": "string",
        "description": "A customer identifier.",
        "customProperties": [{"vendor": "ddk", "property": "concept", "value": "urn:ex:concept:customer"}],
    }), encoding="utf-8")
    _edit(commerce / "project.ddk.json", lambda value: value["artifacts"].update(
        {"customer-id": {"kind": "definition", "path": "definitions/customer-id.json"}}))

    def attach_customer(document):
        for obj in ("orders", "customers"):
            prop = next(p for o in document["schema"] if o["name"] == obj
                        for p in o["properties"] if p["name"] == "customer_id")
            prop["authoritativeDefinitions"] = [{"type": "definition", "url": "../definitions/customer-id.json"}]
        # Add an unjoined carrier on daily-revenue so CandidateLinkset is emitted too.
        rev = next(o for o in document["schema"] if o["name"] == "daily_revenue")
        rev["properties"].append({"name": "customer_id", "logicalType": "string",
                                  "authoritativeDefinitions": [{"type": "definition", "url": "../definitions/customer-id.json"}]})
    _edit(commerce / "datasets/commerce.odcs.json", attach_customer)

    warned = assemble_catalog(commerce / "project.ddk.json", exports=("graph",))
    assert warned.report["decision"] == "passed"
    kind_checks = _checks(warned, "customer-id/concept-kind")
    assert len(kind_checks) == 1
    assert (kind_checks[0]["status"], kind_checks[0]["required"],
            kind_checks[0]["diagnostics"][0]["code"], kind_checks[0]["diagnostics"][0]["severity"]) == (
        "unknown", False, "CATALOG-CONCEPT-KIND-MISSING", "warning")
    customer_concept = next(row for row in warned.catalog["concepts"] if row["definition"] == "customer-id")
    assert customer_concept["conceptKind"] == "attribute"
    graph = rdflib.Graph().parse(data=warned.companions["discovery.graph.jsonld"], format="json-ld")
    cand, = graph.subjects(rdflib.RDF.type, rdflib.URIRef(VOCAB + "CandidateLinkset"))
    assert (cand, rdflib.DCTERMS.type, rdflib.URIRef(VOCAB + "concept-kind-attribute")) in graph

    # Setting conceptKind="identifier" clears the warning and types both skos:Concept and CandidateLinkset.
    def_path.write_text(json.dumps({
        "logicalType": "string",
        "description": "A customer identifier.",
        "customProperties": [
            {"vendor": "ddk", "property": "concept", "value": "urn:ex:concept:customer"},
            {"vendor": "ddk", "property": "conceptKind", "value": "identifier"},
        ],
    }), encoding="utf-8")
    identified = assemble_catalog(commerce / "project.ddk.json", exports=("graph",))
    assert identified.report["decision"] == "passed"
    id_check, = _checks(identified, "customer-id/concept-kind")
    assert id_check["status"] == "passed" and not id_check["diagnostics"]
    graph = rdflib.Graph().parse(data=identified.companions["discovery.graph.jsonld"], format="json-ld")
    assert (rdflib.URIRef("urn:ex:concept:customer"), rdflib.DCTERMS.type,
            rdflib.URIRef(VOCAB + "concept-kind-identifier")) in graph
    cand, = graph.subjects(rdflib.RDF.type, rdflib.URIRef(VOCAB + "CandidateLinkset"))
    assert (cand, rdflib.DCTERMS.type, rdflib.URIRef(VOCAB + "concept-kind-identifier")) in graph

    # Invalid conceptKind fails CATALOG-CONCEPT-KIND.
    def_path.write_text(json.dumps({
        "logicalType": "string",
        "customProperties": [
            {"vendor": "ddk", "property": "concept", "value": "urn:ex:concept:customer"},
            {"vendor": "ddk", "property": "conceptKind", "value": "id"},
        ],
    }), encoding="utf-8")
    invalid = assemble_catalog(commerce / "project.ddk.json")
    assert invalid.report["decision"] == "failed"
    bad_check, = _checks(invalid, "customer-id/concept-kind")
    assert bad_check["diagnostics"][0]["code"] == "CATALOG-CONCEPT-KIND"

    # Duplicate concept IRI across two definitions fails CATALOG-AUTHORITY-CONFLICT.
    def_path.write_text(json.dumps({
        "logicalType": "string",
        "customProperties": [
            {"vendor": "ddk", "property": "concept", "value": "urn:ex:concept:customer"},
            {"vendor": "ddk", "property": "conceptKind", "value": "identifier"},
        ],
    }), encoding="utf-8")
    (commerce / "definitions/dup-id.json").write_text(json.dumps({
        "logicalType": "string",
        "customProperties": [
            {"vendor": "ddk", "property": "concept", "value": "urn:ex:concept:customer"},
            {"vendor": "ddk", "property": "conceptKind", "value": "attribute"},
        ],
    }), encoding="utf-8")
    _edit(commerce / "project.ddk.json", lambda value: value["artifacts"].update(
        {"dup-id": {"kind": "definition", "path": "definitions/dup-id.json"}}))
    _edit(commerce / "datasets/commerce.odcs.json", lambda doc: next(
        o for o in doc["schema"] if o["name"] == "orders"
    )["properties"].append({"name": "dup_customer", "logicalType": "string",
                            "authoritativeDefinitions": [{"type": "definition", "url": "../definitions/dup-id.json"}]}))
    duplicate = assemble_catalog(commerce / "project.ddk.json")
    assert duplicate.report["decision"] == "failed"
    dup_check, = _checks(duplicate, "urn:ex:concept:customer")
    assert dup_check["diagnostics"][0]["code"] == "CATALOG-AUTHORITY-CONFLICT"


def test_concept_policy_fails_on_unresolved_compatible_definition_without_core_policies(tmp_path):
    from ddk.catalog import Assembly
    from ddk.core import load_project

    commerce = _copy(COMMERCE, tmp_path)
    policy = commerce / "policies"
    policy.mkdir(exist_ok=True)
    (policy / "bad-joins.ddk.json").write_text(json.dumps({
        "specVersion": "0.1", "kind": "policy", "id": "urn:test:bad-joins", "version": "1.0.0",
        "rules": [{"id": "joins", "check": "concept-joins", "severity": "error",
                   "compatible": [["amount-cents", "missing-definition"]]}],
    }), encoding="utf-8")
    _edit(commerce / "project.ddk.json", lambda value: value["artifacts"].update(
        {"bad-joins": {"kind": "policy", "path": "policies/bad-joins.ddk.json"}}))
    # Direct Assembly.concept_policy call (bypassing check_policies) still records a required failure instead of swallowing DocumentError.
    inventory = load_project(commerce / "project.ddk.json")
    assembly = Assembly(inventory, ())
    assembly.concept_policy("")
    report = inventory.report.build()
    assert report["decision"] == "failed"
    assert any(item["subject"].endswith("bad-joins/rule/joins/0") and item["status"] == "failed"
               for item in report["checks"])
    # And full assemble_catalog fails too.
    assert assemble_catalog(commerce / "project.ddk.json", required_groups=("catalog",)).report["decision"] == "failed"


def test_project_recipes_may_carry_a_title_notes_and_parameter_order(tmp_path):
    """DDK-CATALOG-006 recipe fields, so a map with titled, ordered saved queries checks and assembles."""
    layered = _copy(LAYERED, tmp_path)

    def describe(project):
        recipe = project["catalog"]["recipes"][0]
        recipe["parameters"] = {"type": "object", "properties": {"station": {"type": "string"}},
                                "additionalProperties": False}
        recipe.update(title="Readings per station", notes=["One row per station."], parameterOrder=["station"])
    _edit(layered / "product/project.ddk.json", describe)
    assert check_project(layered / "project.ddk.json")["decision"] == "passed"
    assert assemble_catalog(layered / "project.ddk.json").report["decision"] == "passed"
