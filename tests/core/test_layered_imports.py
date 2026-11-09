"""Independent layered-map expectations: aggregator roots, shared imports, layers and stored views."""

import json
from pathlib import Path
import shutil

import pytest

from ddk.core import load_project

from test_core import check, codes, edit

LAYERED = Path(__file__).resolve().parents[2] / "examples" / "layered"
READINGS = "source/readings.odcs.json"


@pytest.fixture
def layered(tmp_path):
    target = tmp_path / "layered"
    shutil.copytree(LAYERED, target)
    return target


def _check(report, subject):
    return next(item for item in report["checks"] if item["subject"] == subject)


def _property(document, name):
    return next(item for item in document["schema"][0]["properties"] if item["name"] == name)


def test_aggregator_root_loads_each_layer_once_at_its_shortest_import_path(layered):
    report = check(layered, "passed")
    inventory = load_project(layered / "project.ddk.json")
    assert set(inventory.projects) == {"", "capture", "governance", "product", "resolved", "source"}
    # Depth-first traversal would first reach source at product/resolved/source.
    aliases = {"product/resolved": "resolved", "resolved/source": "source", "source/capture": "capture"}
    assert inventory.import_aliases == aliases
    assert report["metadata"]["importAliases"] == aliases
    assert sorted(alias for alias, item in inventory.artifacts.items() if item.kind == "dataset") == [
        "capture/station-files", "product/station-summary", "resolved/stations", "source/readings",
    ]
    assert inventory.resolve("resolved/source/readings", "product").alias == "source/readings"
    assert inventory.resolve("source/capture/station-files", "resolved").alias == "capture/station-files"
    assert "resolved/resolve-stations -> source/readings" in report["scope"]["followedReferences"]


def test_project_needs_an_artifact_or_an_import(layered):
    edit(layered / "project.ddk.json", lambda project: project.update(imports={}))
    report = check(layered, "failed")
    assert "DOC-SCHEMA" in codes(report)
    assert _check(report, "project:/")["requirement"] == "DDK-SYNTAX-002"


def test_equal_length_paths_choose_the_first_namespace_in_segment_order(layered):
    edit(layered / "project.ddk.json", lambda project: project["imports"].update({"zz-capture": {"path": "capture/project.ddk.json"}}))
    inventory = load_project(layered / "project.ddk.json")
    assert inventory.import_aliases["zz-capture"] == "capture"
    assert inventory.resolve("/zz-capture/station-files").alias == "capture/station-files"
    check(layered, "passed")


@pytest.mark.parametrize(("suffix", "code"), [(b" ", "REF-IDENTITY-CONFLICT"), (b"", "REF-IMPORT-LOCATION-CONFLICT")])
def test_same_project_identity_from_another_file_still_fails(layered, suffix, code):
    copy = layered / "capture-copy"
    copy.mkdir()
    for name in ("project.ddk.json", "captures.odcs.json", "captures.odps.json"):
        (copy / name).write_bytes((layered / "capture" / name).read_bytes() + (suffix if name == "project.ddk.json" else b""))
    edit(layered / "source/project.ddk.json", lambda project: project["imports"].update(
        capture={"path": "../capture-copy/project.ddk.json"}))
    report = check(layered, "failed")
    failure, = [item for item in report["checks"] if code in {entry["code"] for entry in item["diagnostics"]}]
    assert failure["subject"] == "project:source/capture"
    # The copy is reported once and contributes no second set of datasets.
    datasets = [alias for alias, item in load_project(layered / "project.ddk.json").artifacts.items() if item.kind == "dataset"]
    assert len(datasets) == 4


def test_cycle_between_aliased_imports_is_still_reported(layered):
    edit(layered / "capture/project.ddk.json", lambda project: project["imports"].update(
        upper={"path": "../source/project.ddk.json"}))
    report = check(layered, "failed")
    failure, = [entry for item in report["checks"] for entry in item["diagnostics"] if entry["code"] == "REF-IMPORT-CYCLE"]
    assert "capture/project.ddk.json -> source/project.ddk.json -> capture/project.ddk.json" in failure["message"]


def test_layer_order_checks_every_declared_dependency(layered):
    report = check(layered, "passed")
    rule = _check(report, "governance/layers/rule/layer-order")
    assert rule["requirement"] == "DDK-POLICY-006" and rule["status"] == "passed"
    assert report["metadata"]["layerOrder"]["governance/layers/rule/layer-order"] == {
        "layers": ["capture", "source", "resolved", "product"], "checkedEdges": 12,
    }


def _upward_port(root):
    edit(root / "capture/captures.odps.json", lambda product: product.setdefault("inputPorts", []).append(
        {"name": "readings", "contractId": "urn:example:layered:contract:readings", "version": "1.0.0"}))
    return "capture/captures.odps.json", "/inputPorts/0"


def _upward_relationship(root):
    edit(root / "source/project.ddk.json", lambda project: project["catalog"]["relationships"].append({
        "id": "urn:test:upward", "source": {"dataset": "readings", "paths": [[{"field": "station_code"}]]},
        "target": {"dataset": "/resolved/stations", "paths": [[{"field": "station_code"}]]}, "match": "equal",
        "cardinality": "many_to_one", "scope": "version_pair", "resolution": "unresolved_allowed", "nulls": "skip",
        "meaning": "Declared in the wrong direction for the layers."}))
    return "source/project.ddk.json", "/catalog/relationships/1"


def _upward_recipe(root):
    edit(root / "source/project.ddk.json", lambda project: project["catalog"].update(recipes=[{
        "id": "urn:test:upward-recipe", "sql": "../product/readings-per-station.sql", "dialect": "datafusion",
        "inputs": {"stations": "/resolved/stations"}, "relationships": [], "resultDataset": "readings",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}]))
    return "source/project.ddk.json", "/catalog/recipes/0/inputs/stations"


def _upward_production(root):
    component = json.loads((root / "resolved/resolve-stations.ddk.json").read_bytes())
    component.update(id="urn:test:upward-component", inputs={"summary": {"dataset": "/product/station-summary"}},
                     outputs={"files": {"dataset": "station-files"}})
    (root / "capture/upward.ddk.json").write_text(json.dumps(component))
    edit(root / "capture/project.ddk.json", lambda project: project["artifacts"].update(
        upward={"kind": "component", "path": "upward.ddk.json"}))
    return "capture/upward.ddk.json", "/inputs/summary"


@pytest.mark.parametrize("mutate", [_upward_port, _upward_relationship, _upward_recipe, _upward_production])
def test_layer_order_fails_each_dependency_kind_that_points_upward(layered, mutate):
    path, pointer = mutate(layered)
    report = check(layered, "failed")
    rule = _check(report, "governance/layers/rule/layer-order")
    failure, = [item for item in rule["diagnostics"] if item["code"] == "POLICY-LAYER-ORDER"]
    assert failure["related"] == [{"path": path, "pointer": pointer}]


def test_layer_order_keeps_unassigned_dependencies_unknown(layered):
    edit(layered / "governance/layers.ddk.json", lambda policy: policy["rules"][0]["layers"].pop())
    report = check(layered, "incomplete")
    rule = _check(report, "governance/layers/rule/layer-order")
    assert rule["status"] == "unknown" and rule["reason"]
    assert {item["code"] for item in rule["diagnostics"]} == {"POLICY-LAYER-UNASSIGNED"}


@pytest.mark.parametrize("namespaces", [["/missing"], ["/capture"]])
def test_layer_order_rejects_unknown_or_repeated_namespaces(layered, namespaces):
    edit(layered / "governance/layers.ddk.json", lambda policy: policy["rules"][0]["layers"][3].update(namespaces=namespaces))
    rule = _check(check(layered, "failed"), "governance/layers/rule/layer-order")
    assert {item["code"] for item in rule["diagnostics"]} == {"POLICY-LAYER-INVALID"}


def test_view_property_reads_a_stored_property_of_the_same_object(layered):
    report = check(layered, "passed")
    assert _check(report, "source/readings/storage")["requirement"] == "DDK-DATA-006"


@pytest.mark.parametrize(("change", "code"), [
    (lambda view, payload: view.update(transformSourceObjects=["missing"]), "DATA-VIEW-SOURCE-MISSING"),
    (lambda view, payload: payload["customProperties"][0].update(value="view"), "DATA-VIEW-SOURCE-MISSING"),
    (lambda view, payload: view.pop("transformLogic"), "DATA-VIEW-SOURCE-MISSING"),
    (lambda view, payload: view["customProperties"][0].update(value="virtual"), "DATA-STORAGE-INVALID"),
    (lambda view, payload: view["customProperties"].append({"vendor": "ddk", "property": "storage", "value": "view"}),
     "DATA-STORAGE-INVALID"),
])
def test_view_property_without_a_stored_source_fails(layered, change, code):
    def mutate(contract):
        change(_property(contract, "temperature_c"), _property(contract, "payload"))
    edit(layered / READINGS, mutate)
    report = check(layered, "failed")
    assert code in {item["code"] for item in _check(report, "source/readings/storage")["diagnostics"]}


def test_storage_annotations_of_other_vendors_are_not_interpreted(layered):
    def mutate(contract):
        for name in ("payload", "temperature_c"):
            _property(contract, name)["customProperties"] = [{"property": "storage", "value": "view"}]
        _property(contract, "temperature_c")["transformSourceObjects"] = ["captured_files"]
    edit(layered / READINGS, mutate)
    report = check(layered, "passed")
    assert not any(item["subject"] == "source/readings/storage" for item in report["checks"])


@pytest.mark.parametrize(("project", "alias", "attribution"), [
    ("resolved/project.ddk.json", "stations", {"assertedBy": "project"}),
    ("capture/project.ddk.json", "station-files", {"assertedBy": "publisher", "derivation": ["deterministic"]}),
    ("source/project.ddk.json", "readings", {"assertedBy": "crowd"}),
])
def test_attribution_names_derivation_for_derived_data_and_none_for_originals(layered, project, alias, attribution):
    edit(layered / project, lambda value: value["artifacts"][alias].update(attribution=attribution))
    assert "DOC-SCHEMA" in codes(check(layered, "failed"))
