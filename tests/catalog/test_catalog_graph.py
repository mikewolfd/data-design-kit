"""Knowledge-graph export (DDK-CATALOG-013) and RML mappings (DDK-CATALOG-014), checked against the catalog."""

import json
from pathlib import Path

import pytest

from ddk.catalog import assemble_catalog
from ddk.catalog_graph import VOCAB

rdflib = pytest.importorskip("rdflib")
isomorphic = pytest.importorskip("rdflib.compare").isomorphic
ROOT = Path(__file__).resolve().parents[2]
COMMERCE = ROOT / "examples" / "commerce"
LAYERED = ROOT / "examples" / "layered"
SCHEMAS = ROOT / "schemas" / "0.1"
SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")
DDKV = rdflib.Namespace(VOCAB)


def _commerce(*exports):
    return assemble_catalog(COMMERCE / "project.ddk.json", metadata=COMMERCE / "catalog" / "metadata.example.json",
                            metadata_adapter="example", exports=exports)


def _graph(result, name="discovery.graph.jsonld", fmt="json-ld"):
    return rdflib.Graph().parse(data=result.companions[name], format=fmt)


def _count(graph, pattern):
    return int(next(iter(graph.query(f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ {pattern} }}", initNs={
        "dcat": "http://www.w3.org/ns/dcat#", "dct": "http://purl.org/dc/terms/", "void": "http://rdfs.org/ns/void#",
        "dqv": "http://www.w3.org/ns/dqv#", "prov": "http://www.w3.org/ns/prov#"})))[0])


@pytest.mark.parametrize("example", ["commerce", "layered"])
def test_graph_holds_every_catalog_fact_once(example):
    result = _commerce("dcat", "graph") if example == "commerce" else assemble_catalog(
        LAYERED / "project.ddk.json", exports=("dcat", "graph"))
    assert result.report["decision"] == "passed"
    catalog, graph = result.catalog, _graph(result)
    assert _count(graph, f"<{catalog['id']}> dcat:dataset ?s") == len({item["id"] for item in catalog["datasets"]})
    assert _count(graph, "?s dcat:isVersionOf ?d") == len(catalog["versions"])
    assert _count(graph, "?s a void:Linkset") == len(catalog["relationships"])
    assert _count(graph, "?s a dqv:QualityMeasurement") == len(catalog["checks"])
    assert _count(graph, "?s dct:conformsTo ?standard . ?s a dcat:Resource") == len({item["id"] for item in catalog["products"]})
    assert _count(graph, "?s a prov:Plan") == len(catalog["productions"])


def test_graph_keeps_dcat_unchanged_turtle_equal_and_bytes_stable():
    with_graph, dcat_only = _commerce("dcat", "graph", "graph.ttl"), _commerce("dcat")
    assert with_graph.companions["discovery.dcat.json"] == dcat_only.companions["discovery.dcat.json"]
    assert isomorphic(_graph(with_graph), _graph(with_graph, "discovery.graph.ttl", "turtle"))
    assert _commerce("dcat", "graph", "graph.ttl").companions == with_graph.companions
    assert {item["role"] for item in with_graph.catalog["files"] if item["path"].startswith("discovery.graph")} == {"graph"}


def test_graph_states_runs_checks_links_and_origins_with_standard_terms():
    graph = _graph(_commerce("dcat", "graph"))
    prov = rdflib.Namespace("http://www.w3.org/ns/prov#")
    run, output = (rdflib.URIRef(f"urn:example:commerce:{name}") for name in ("run:revenue-fixture-01",
                                                                              "version:daily-revenue:fixture-01"))
    assert (output, prov.wasGeneratedBy, run) in graph
    assert set(graph.objects(run, prov.used)) == {rdflib.URIRef("urn:example:commerce:version:orders:fixture-01"),
                                                  rdflib.URIRef("urn:example:commerce:version:customers:fixture-01")}
    association = graph.value(run, prov.qualifiedAssociation)
    assert graph.value(graph.value(association, prov.hadPlan), rdflib.RDFS.label) == rdflib.Literal("summarize")
    # The example check did not run; the graph must not turn that into unknown, passed or executed evidence.
    measurement = next(graph.subjects(rdflib.RDF.type, rdflib.URIRef("http://www.w3.org/ns/dqv#QualityMeasurement")))
    assert graph.value(measurement, rdflib.URIRef("http://www.w3.org/ns/dqv#value")) == DDKV["outcome-not_run"]
    assert graph.value(measurement, rdflib.DCTERMS.type) == DDKV["evidence-declared"]
    linkset = rdflib.URIRef("urn:example:commerce:relationship:customer:linkset")
    assert {graph.value(linkset, rdflib.URIRef("http://rdfs.org/ns/void#" + term)) for term in
            ("subjectsTarget", "objectsTarget", "linkPredicate")} == {
        rdflib.URIRef("urn:example:commerce:dataset:orders"), rdflib.URIRef("urn:example:commerce:dataset:customers"),
        rdflib.URIRef("urn:example:commerce:relationship:customer")}
    assert {DDKV["cardinality-many_to_one"], DDKV["scope-version_pair"], DDKV["nulls-reject"],
            DDKV["match-equal"]} <= set(graph.objects(linkset, rdflib.DCTERMS.type))
    layered = _graph(assemble_catalog(LAYERED / "project.ddk.json", exports=("dcat", "graph")))
    station_files = rdflib.URIRef("urn:example:layered:dataset:station-files")
    agent = layered.value(station_files, prov.wasAttributedTo)
    assert layered.value(agent, rdflib.DCTERMS.type) == DDKV["origin-publisher"]
    layers = {str(layered.value(concept, SKOS.prefLabel)) for concept in layered.objects(None, rdflib.URIRef(
        "http://www.w3.org/ns/dcat#theme")) if str(concept).startswith("urn:example:layered:catalog:layer:")}
    assert layers == {"capture", "source", "resolved", "product"}


def test_vocabulary_restates_the_schema_enums_and_defines_every_term_the_graph_uses():
    vocabulary = rdflib.Graph().parse(ROOT / "vocab" / "ddk.ttl")
    catalog_schema = json.loads((SCHEMAS / "catalog.schema.json").read_text())["$defs"]
    common = json.loads((SCHEMAS / "common.schema.json").read_text())["$defs"]
    project = json.loads((SCHEMAS / "project.schema.json").read_text())
    role = project["properties"]["artifacts"]["additionalProperties"]["oneOf"][0]["properties"]["role"]["enum"]
    relationship = catalog_schema["relationship"]["properties"]
    expected = {"CheckOutcome": ("outcome", catalog_schema["check"]["properties"]["status"]["enum"]),
                "EvidenceStrength": ("evidence", ["declared", "inferred", "executed"]),
                "DatasetRole": ("role", role), "DatasetOrigin": ("origin", common["datasetOrigin"]["enum"]),
                **{scheme: (key, relationship[key]["enum"]) for scheme, key in (
                    ("LinkCardinality", "cardinality"), ("LinkScope", "scope"), ("LinkNulls", "nulls"),
                    ("LinkMatch", "match"))}}
    for scheme, (prefix, values) in expected.items():
        assert set(vocabulary.subjects(SKOS.inScheme, DDKV[scheme])) == {DDKV[f"{prefix}-{value}"] for value in values}
    defined = set(vocabulary.subjects())
    for result in (_commerce("dcat", "graph"), assemble_catalog(LAYERED / "project.ddk.json", exports=("dcat", "graph"))):
        used = {term for triple in _graph(result) for term in triple if str(term).startswith(VOCAB)}
        assert used and used <= defined


def test_executed_evidence_needs_a_retained_report_and_missing_edges_fail_the_export(monkeypatch):
    from ddk import catalog_graph
    from ddk.documents import json_dumps

    catalog = json.loads(json_dumps(_commerce("dcat").catalog))
    check = catalog["checks"][0]
    check.update(status="passed", record={"uri": "https://data.example.org/report.json", "sha256": "0" * 64})
    catalog["checks"].append({**check, "rule": {**check["rule"], "id": "urn:example:commerce:rule:declared-only"},
                              "record": {"uri": "https://data.example.org/claim.json"}})
    _, graph = catalog_graph.graph_document(catalog)
    strengths = {str(graph.value(m, rdflib.URIRef("http://www.w3.org/ns/dqv#isMeasurementOf"))): graph.value(m, rdflib.DCTERMS.type)
                 for m in graph.subjects(rdflib.RDF.type, rdflib.URIRef("http://www.w3.org/ns/dqv#QualityMeasurement"))}
    assert strengths == {"urn:example:commerce:rule:fixture-expected-revenue": DDKV["evidence-executed"],
                         "urn:example:commerce:rule:declared-only": DDKV["evidence-declared"]}
    real = catalog_graph.graph_edges
    monkeypatch.setattr(catalog_graph, "graph_edges", lambda item: [*real(item), ("urn:ex:a", "prov:used", "urn:ex:b")])
    with pytest.raises(Exception) as error:
        catalog_graph.graph_document(catalog)
    assert getattr(error.value, "code", "") == "CATALOG-GRAPH-VALIDATION"


def test_fields_keep_dataset_predicates_and_point_to_canonical_urls():
    from ddk import catalog_graph
    from ddk.documents import json_dumps

    catalog = json.loads(json_dumps(_commerce("dcat").catalog))
    definitions = catalog["extensions"]["urn:ddk:catalog:assembly"]["datasetDefinitions"]
    for alias in ("orders", "customers"):
        next(p for p in definitions[alias]["properties"] if p["name"] == "customer_id").setdefault(
            "authoritativeDefinitions", []).append({"type": "canonicalUrl", "url": "https://example.org/customer-id"})
    _, graph = catalog_graph.graph_document(catalog)
    canonical = rdflib.URIRef("https://example.org/customer-id")
    assert set(graph.subjects(rdflib.RDFS.seeAlso, canonical)) == {
        rdflib.URIRef(f"urn:example:commerce:dataset:{alias}:field:customer_id") for alias in ("orders", "customers")}
    assert not set(graph.predicate_objects(canonical))  # nothing is said about someone else's IRI
