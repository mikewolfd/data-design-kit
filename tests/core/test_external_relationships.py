"""External catalog targets retain their meaning without becoming local aliases."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import socket

import pytest

from ddk.catalog import build_catalog
from ddk.core import check_project, load_project
from ddk.documents import validate_document

COMMERCE = Path(__file__).resolve().parents[2] / "examples" / "commerce"
RELATIONSHIP = "urn:test:relationship:external-customer"
EXTERNAL = "https://records.example.org/customer"


def external_project(tmp_path):
    folder = tmp_path / "commerce"
    shutil.copytree(COMMERCE, folder)
    path = folder / "project.ddk.json"
    project = json.loads(path.read_text())
    relationship = {
        "id": RELATIONSHIP,
        "source": {"dataset": "customers", "paths": [[{"field": "customer_id"}]]},
        "target": {"external": EXTERNAL},
        "match": "equal",
        "cardinality": "many_to_one",
        "scope": "external",
        "resolution": "external",
        "meaning": "The publisher identifies the external customer record.",
        "nulls": "reject",
    }
    project["catalog"]["relationships"].append(relationship)
    path.write_text(json.dumps(project) + "\n")
    return path, project, relationship


def test_external_target_keeps_only_local_dependency_and_core_stays_offline(tmp_path, monkeypatch):
    path, _, _ = external_project(tmp_path)
    (path.parent / "transforms" / "revenue.sql").unlink()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("external identifier was fetched"))
    inventory = load_project(path)
    assert inventory.dependencies[RELATIONSHIP] == {"customers"}
    assert EXTERNAL not in inventory.registrations
    report = check_project(path)
    assert report["decision"] == "passed"
    assert not validate_document(report, "report")


@pytest.mark.parametrize(("required", "decision"), [(False, "passed"), (True, "incomplete")])
def test_external_relationship_is_retained_with_unknown_resolution(tmp_path, required, decision):
    path, _, expected = external_project(tmp_path)
    report = build_catalog(path, required_groups=("catalog.relationships",) if required else ())
    assert report["decision"] == decision
    assert not validate_document(report, "report")
    catalog = report["metadata"]["catalog"]
    assert not validate_document(catalog, "catalog")
    actual, = [row for row in catalog["relationships"] if row["id"] == RELATIONSHIP]
    assert actual == expected
    check, = [row for row in report["checks"] if row["subject"] == RELATIONSHIP]
    assert check["status"] == "unknown"
    assert check["required"] is required
    assert check["diagnostics"][0]["code"] == "CATALOG-MATCH-UNSUPPORTED"


def test_malformed_external_target_is_a_document_failure(tmp_path):
    path, project, _ = external_project(tmp_path)
    project["catalog"]["relationships"][-1]["target"]["dataset"] = "customers"
    path.write_text(json.dumps(project) + "\n")
    report = build_catalog(path)
    assert report["decision"] == "failed"
    assert not validate_document(report, "report")
    assert "catalog" not in report.get("metadata", {})


def test_imported_external_relationship_keeps_its_local_namespace(tmp_path):
    path, project, _ = external_project(tmp_path)
    root = tmp_path / "root.ddk.json"
    root.write_text(json.dumps({
        "specVersion": "0.1", "kind": "project", "id": "urn:test:external-import",
        "version": "1.0.0", "artifacts": {
            "anchor": {"kind": "dataset", "path": "commerce/datasets/commerce.odcs.json", "object": "customers"},
        }, "requiredChecks": project["requiredChecks"],
        "imports": {"shared": {"path": str(path.relative_to(tmp_path))}},
    }) + "\n")
    inventory = load_project(root)
    assert inventory.dependencies[RELATIONSHIP] == {"shared/customers"}
    assert check_project(root)["decision"] == "passed"


def test_contextual_external_relationship_retains_dependency_without_new_recipe_input(tmp_path):
    path, project, _ = external_project(tmp_path)
    recipe = project["catalog"]["recipes"][0]
    original_inputs = deepcopy(recipe["inputs"])
    recipe["contextualRelationships"] = [RELATIONSHIP]
    path.write_text(json.dumps(project) + "\n")
    inventory = load_project(path)
    assert RELATIONSHIP in inventory.dependencies[recipe["id"]]
    assert EXTERNAL not in inventory.dependencies[recipe["id"]]
    report = build_catalog(path)
    assert report["decision"] == "passed"
    actual, = [row for row in report["metadata"]["catalog"]["recipes"] if row["id"] == recipe["id"]]
    assert actual["inputs"] == original_inputs
    assert actual["contextualRelationships"] == [RELATIONSHIP]
