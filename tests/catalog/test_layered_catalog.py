"""Independent catalog expectations for a layered map with shared imports."""

import json
from pathlib import Path
import shutil

import pytest
from rdflib import Graph, Namespace, RDF

from ddk.catalog import assemble_catalog
from ddk.core import check_project
from ddk.documents import validate_document

LAYERED = Path(__file__).resolve().parents[2] / "examples" / "layered"
DETAILS = "urn:ddk:catalog:assembly"
DCAT = Namespace("http://www.w3.org/ns/dcat#")
DATASETS = {
    "urn:example:layered:dataset:station-files": "urn:example:layered:contract:captures",
    "urn:example:layered:dataset:readings": "urn:example:layered:contract:readings",
    "urn:example:layered:dataset:stations": "urn:example:layered:contract:stations",
    "urn:example:layered:dataset:station-summary": "urn:example:layered:contract:summary",
}
PRODUCTS = ["urn:example:layered:product:captures", "urn:example:layered:product:readings",
            "urn:example:layered:product:stations", "urn:example:layered:product:summary"]
CANONICAL = "https://data.example.org/contracts/readings"


@pytest.fixture
def layered(tmp_path):
    target = tmp_path / "layered"
    shutil.copytree(LAYERED, target)
    return target


def _edit(path, change):
    value = json.loads(path.read_bytes())
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def _row(rows, alias):
    return next(row for row in rows if row["alias"] == alias)


def _public(layered, tmp_path, **grants):
    policy = {"identifiers": ["urn:example:layered:catalog", "urn:example:layered:map", *PRODUCTS,
                              *DATASETS, *DATASETS.values()], **grants}
    path = tmp_path / "public.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return assemble_catalog(layered / "project.ddk.json", disclosure_policy=path)


def test_shared_imports_list_each_dataset_product_and_relationship_once(layered, tmp_path):
    result = assemble_catalog(layered / "project.ddk.json", exports=("dcat",), output=tmp_path / "out")
    assert result.report["decision"] == "passed", result.report
    catalog = result.catalog
    assert not validate_document(catalog, "catalog")
    assert sorted(row["id"] for row in catalog["datasets"]) == sorted(DATASETS)
    assert sorted(row["id"] for row in catalog["products"]) == PRODUCTS
    assert sorted(row["id"] for row in catalog["relationships"]) == [
        "urn:example:layered:relationship:reading-file", "urn:example:layered:relationship:station-readings",
    ]
    stations = _row(catalog["products"], "resolved/stations-product")
    assert [(port["direction"], port["dataset"]) for port in stations["ports"]] == [
        ("input", "source/readings"), ("output", "resolved/stations"),
    ]
    recipe, = catalog["recipes"]
    assert recipe["inputs"] == {"readings": "source/readings", "stations": "resolved/stations"}
    assert catalog["extensions"][DETAILS]["importAliases"] == {
        "product/resolved": "resolved", "resolved/source": "source", "source/capture": "capture",
    }
    graph = Graph().parse(tmp_path / "out" / "discovery.dcat.json", format="json-ld")
    assert len(set(graph.subjects(RDF.type, DCAT.Dataset))) == 4


def test_products_carry_odps_type_status_and_descriptions(layered):
    catalog = assemble_catalog(layered / "project.ddk.json").catalog
    summary = _row(catalog["products"], "product/summary-product")
    assert {key: summary[key] for key in ("name", "type", "domain", "status", "description", "context")} == {
        "name": "Station summary", "type": "consumerAligned", "domain": "weather observations", "status": "proposed",
        "description": {"purpose": "Answer how many readings each station has reported.", "usage": "Read one row per station."},
        "context": {"instructions": "Counts include unresolved stations only after resolution."},
    }
    captures = _row(catalog["products"], "capture/capture-product")
    assert (captures["type"], captures["status"]) == ("sourceAligned", "active")
    assert "description" not in captures and "context" not in captures


def test_datasets_carry_their_contract_values_and_only_applicable_sla(layered):
    catalog = assemble_catalog(layered / "project.ddk.json").catalog
    readings = _row(catalog["datasets"], "source/readings")
    assert readings["status"] == "active"
    assert readings["origin"] == "publisher"
    assert readings["tags"] == ["observations"]
    assert readings["description"] == "Station readings parsed from retained files."
    assert readings["context"] == {"instructions": "Temperatures are derived from the stored payload."}
    assert readings["contract"] == {
        "description": {"purpose": "Readings as each station reported them.", "usage": "Join to retained files by file_sha256.",
                        "limitations": "Stations report in local units; values are not corrected."},
        "context": {"instructions": "Quote station codes exactly as reported.",
                    "verifiedStatements": [{"question": "Which file holds a reading?",
                                            "answer": "The file named by file_sha256."}]},
        # The retention entry names another object of the same contract.
        "slaProperties": [{"property": "frequency", "value": 1, "unit": "d"},
                          {"property": "latency", "value": 6, "unit": "h", "element": "readings"}],
        "tags": ["network:example"], "canonicalUrls": [CANONICAL],
    }
    stations = _row(catalog["datasets"], "resolved/stations")
    assert (stations["origin"], stations["status"]) == ("model", "draft")
    assert _row(catalog["datasets"], "product/station-summary")["origin"] == "derived"


@pytest.mark.parametrize(("entry", "applies"), [
    ({"element": "schema/readings"}, True),
    ({"element": "schema/readings/properties/payload"}, True),
    ({"element": "calibrations, readings.payload"}, True),
    ({"element": "schema/calibrations"}, False),
    ({"element": "Readings"}, False),
])
def test_sla_elements_apply_by_object_name_or_stable_id(layered, entry, applies):
    _edit(layered / "source/readings.odcs.json", lambda contract: contract.update(
        slaProperties=[{"property": "availability", "value": "99%", **entry}]))
    readings = _row(assemble_catalog(layered / "project.ddk.json").catalog["datasets"], "source/readings")
    assert readings["contract"].get("slaProperties") == ([{"property": "availability", "value": "99%", **entry}]
                                                          if applies else None)


def test_deprecated_default_element_scopes_entries_without_their_own(layered):
    _edit(layered / "source/readings.odcs.json", lambda contract: contract.update(
        slaDefaultElement="calibrations", slaProperties=[{"property": "frequency", "value": 1, "unit": "d"}]))
    readings = _row(assemble_catalog(layered / "project.ddk.json").catalog["datasets"], "source/readings")
    assert "slaProperties" not in readings["contract"]


def test_uninterpretable_sla_element_stays_visible_and_attached_to_no_dataset(layered):
    _edit(layered / "source/readings.odcs.json", lambda contract: contract["slaProperties"].append(
        {"property": "endOfLife", "value": "2031-01-01", "element": "other.yaml#schema/readings"}))
    result = assemble_catalog(layered / "project.ddk.json")
    assert result.report["decision"] == "passed"
    unknown, = [item for item in result.report["checks"] if item["status"] == "unknown"]
    assert unknown["required"] is False and unknown["requirement"] == "DDK-CATALOG-003"
    assert unknown["diagnostics"][0]["code"] == "CATALOG-SLA-ELEMENT-UNKNOWN"
    assert unknown["diagnostics"][0]["location"]["pointer"] == "/slaProperties/3"
    sla = _row(result.catalog["datasets"], "source/readings")["contract"]["slaProperties"]
    assert all(entry["property"] != "endOfLife" for entry in sla)


def test_public_view_keeps_vocabulary_and_withholds_text_without_a_grant(layered, tmp_path):
    result = _public(layered, tmp_path)
    assert result.report["decision"] == "passed", result.local_report
    product = next(row for row in result.catalog["products"] if row["id"] == "urn:example:layered:product:summary")
    assert (product["type"], product["status"]) == ("consumerAligned", "proposed")
    assert not {"name", "domain", "description", "context"} & product.keys()
    readings = next(row for row in result.catalog["datasets"] if row["id"] == "urn:example:layered:dataset:readings")
    assert (readings["status"], readings["origin"]) == ("active", "publisher")
    assert not {"description", "tags", "context", "contract"} & readings.keys()
    public = b"".join(result.artifacts.values())
    assert b"Quote station codes" not in public and CANONICAL.encode() not in public


@pytest.mark.parametrize(("locations", "urls"), [([], None), ([CANONICAL], [CANONICAL])])
def test_public_descriptions_keep_canonical_urls_only_as_granted_locations(layered, tmp_path, locations, urls):
    result = _public(layered, tmp_path, descriptions=True, locations=locations)
    assert result.report["decision"] == "passed", result.local_report
    product = next(row for row in result.catalog["products"] if row["id"] == "urn:example:layered:product:summary")
    assert product["description"]["purpose"] == "Answer how many readings each station has reported."
    readings = next(row for row in result.catalog["datasets"] if row["id"] == "urn:example:layered:dataset:readings")
    assert readings["contract"]["context"]["instructions"] == "Quote station codes exactly as reported."
    assert readings["contract"].get("canonicalUrls") == urls


def test_public_sla_and_context_entries_withhold_names_links_and_custom_properties(layered, tmp_path):
    secret_link = "https://internal.example.org/runbooks/readings"

    def change(contract):
        contract["slaProperties"].append({"property": "latency", "value": 2, "unit": "h", "element": "readings.secret_column",
                                          "customProperties": [{"property": "pager", "value": "private-pager"}]})
        contract["slaProperties"][0]["authoritativeDefinitions"] = [{"type": "runbook", "url": secret_link}]
        contract["context"]["verifiedStatements"][0]["customProperties"] = [{"property": "reviewer", "value": "private-reviewer"}]
        contract["schema"][0]["properties"].append({"name": "secret_column", "logicalType": "string"})
    _edit(layered / "source/readings.odcs.json", change)
    local = _row(assemble_catalog(layered / "project.ddk.json").catalog["datasets"], "source/readings")
    assert len(local["contract"]["slaProperties"]) == 3
    result = _public(layered, tmp_path, descriptions=True)
    assert result.report["decision"] == "passed", result.local_report
    readings = next(row for row in result.catalog["datasets"] if row["id"] == "urn:example:layered:dataset:readings")
    # The readings-level latency entry keeps its value without naming the withheld object.
    assert readings["contract"]["slaProperties"] == [{"property": "frequency", "value": 1, "unit": "d"},
                                                     {"property": "latency", "value": 6, "unit": "h"}]
    assert readings["contract"]["context"]["verifiedStatements"] == [
        {"question": "Which file holds a reading?", "answer": "The file named by file_sha256."}]
    public = b"".join(result.artifacts.values())
    for secret in (b"secret_column", b"private-pager", b"private-reviewer", secret_link.encode(), b'"element"'):
        assert secret not in public


def test_public_extension_naming_a_withheld_namespace_is_refused(layered, tmp_path):
    grant = {"projectExtensions": [{"project": {"id": "urn:example:layered:capture", "version": "1.0.0"},
                                    "extensions": ["urn:example:layered:map-notes"]}]}
    ids = ["urn:example:layered:capture"]
    refused = _public(layered, tmp_path, **grant, identifiers=["urn:example:layered:catalog", "urn:example:layered:map",
                                                               *PRODUCTS, *DATASETS, *DATASETS.values(), *ids])
    assert refused.report["decision"] == "failed"
    assert any(entry["code"] == "CATALOG-DISCLOSURE" and "withheld" in entry["message"]
               for item in refused.local_report["checks"] for entry in item["diagnostics"])
    assert not refused.artifacts
    disclosed = _public(layered, tmp_path, **grant, aliases=["capture"], identifiers=[
        "urn:example:layered:catalog", "urn:example:layered:map", *PRODUCTS, *DATASETS, *DATASETS.values(), *ids])
    assert disclosed.report["decision"] == "passed", disclosed.local_report
    extension, = disclosed.catalog["extensions"][DETAILS]["projectExtensions"]
    assert extension["namespace"] == "capture"
    assert extension["extensions"] == {"urn:example:layered:map-notes": {"layer": "capture", "reviewed": True}}


@pytest.mark.parametrize(("value", "decision"), [
    ("see capture/station-files", "failed"),
    ("parsed from station_files", "failed"),
    ("urn:example:layered:dataset:readings", "passed"),
    ("reviewed weekly", "passed"),
])
def test_public_extension_values_are_checked_by_their_path_like_parts(layered, tmp_path, value, decision):
    _edit(layered / "capture/project.ddk.json", lambda project: project["extensions"].update(
        {"urn:example:layered:map-notes": {"note": value}}))
    result = _public(layered, tmp_path, projectExtensions=[{"project": {"id": "urn:example:layered:capture", "version": "1.0.0"},
                                                            "extensions": ["urn:example:layered:map-notes"]}],
                     identifiers=["urn:example:layered:catalog", "urn:example:layered:map", *PRODUCTS, *DATASETS,
                                  *DATASETS.values(), "urn:example:layered:capture"])
    assert result.report["decision"] == decision, result.local_report


def test_catalog_only_map_needs_no_component_or_design(layered):
    """DDK-CONF-005: catalog, policy, reference and result checks run without the frozen artifact kinds."""
    _edit(layered / "resolved" / "project.ddk.json", lambda value: value["artifacts"].pop("resolve-stations"))
    (layered / "resolved" / "resolve-stations.ddk.json").unlink()
    report = check_project(layered / "project.ddk.json")
    assert report["decision"] == "passed"
    frozen = {"core.calls", "core.graph"}
    assert frozen <= set(report["coverage"]["requestedGroups"])
    assert not [item for item in report["checks"] if item["group"] in frozen]
    assert {"core.documents", "core.policies"} <= {item["group"] for item in report["checks"]}
    result = assemble_catalog(layered / "project.ddk.json", exports=("dcat",), required_groups=("catalog.dcat",))
    assert result.report["decision"] == "passed" and not result.catalog["productions"]
