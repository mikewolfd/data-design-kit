"""Direct consumers use one admitted view while preserving its evidence status."""

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from ddk.catalog import CatalogResult, assemble_catalog, build_catalog, resolve_query
from ddk.documents import read_json, validate_document


COMMERCE = Path(__file__).resolve().parents[2] / "examples" / "commerce"
DETAILS = "urn:ddk:catalog:assembly"
RECIPE = "urn:example:commerce:recipe:checked-revenue"
LINK = "urn:example:commerce:relationship:customer"
REVENUE = "urn:example:commerce:version:daily-revenue:fixture-01"
DOMAIN = "urn:test:catalog:upstream-relations"


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    shutil.copytree(COMMERCE, root)
    return root


def _save(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _project(source):
    return deepcopy(read_json(source / "project.ddk.json").value)


def _recipe(project):
    return next(row for row in project["catalog"]["recipes"] if row["id"] == RECIPE)


def _files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_result_reads_each_recipe_once_and_retains_exact_standard_outputs(source, tmp_path, monkeypatch):
    project = _project(source)
    expected = {row["id"]: (source / row["sql"]).read_bytes() for row in project["catalog"]["recipes"]}
    paths = {(source / row["sql"]).resolve() for row in project["catalog"]["recipes"]}
    opened = Counter()
    original = Path.open

    def observe(path, *args, **kwargs):
        if path.resolve() in paths:
            opened[path.resolve()] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe)
    output = tmp_path / "output"
    result = assemble_catalog(source / "project.ddk.json", output=output)
    assert isinstance(result, CatalogResult)
    assert result.report["decision"] == "passed"
    assert opened == Counter({path: 1 for path in paths})
    assert result.catalog is not None
    assert not validate_document(result.catalog, "catalog")
    for row in result.catalog["recipes"]:
        data = result.companions[row["sql"]]
        assert data == expected[row["id"]]
        entry, = [item for item in result.catalog["files"] if item["path"] == row["sql"]]
        assert entry["sha256"] == sha256(data).hexdigest()
    assert dict(result.artifacts) == _files(output)
    assert json.loads(result.artifacts["catalog.ddk.json"]) == result.catalog
    saved_report = json.loads(result.artifacts["catalog.report.json"])
    assert saved_report["decision"] == result.report["decision"]
    assert saved_report["checks"] == result.report["checks"]
    lock = json.loads(result.artifacts["catalog.lock.json"])
    assert not validate_document(lock, "lock")
    for item in lock["extensions"]["urn:ddk:catalog:output-set"]:
        assert sha256(result.artifacts[item["path"]]).hexdigest() == item["sha256"]
    with pytest.raises(TypeError):
        result.companions["other.sql"] = b"SELECT 1"


@pytest.mark.parametrize("status", ["not_run", "unknown", "failed"])
def test_admitted_view_preserves_required_quality_status_without_publishing(source, tmp_path, status):
    output = tmp_path / "output"
    assert build_catalog(source / "project.ddk.json", output=output)["decision"] == "passed"
    previous = _files(output)
    metadata = deepcopy(read_json(source / "catalog" / "metadata.example.json").value)
    metadata.pop("illustrative")
    check, = metadata["checks"]
    check["status"] = status
    if status == "failed":
        check.pop("reason", None)
        receipt = tmp_path / "quality-failed.json"
        _save(receipt, {"subject": REVENUE, "status": "failed", "violations": ["independent expected count differs"]})
        check["record"] = {"uri": receipt.as_uri(), "sha256": sha256(receipt.read_bytes()).hexdigest()}
    metadata["qualification"] = [{key: check[key] for key in ("subject", "rule", "evaluator", "scope")}]
    path = source / "metadata.json"
    _save(path, metadata)
    result = assemble_catalog(source / "project.ddk.json", metadata=path, metadata_adapter="local", output=output)
    assert result.report["decision"] == ("failed" if status == "failed" else "incomplete")
    assert result.catalog is not None
    assert result.companions
    assert not result.artifacts
    assert _files(output) == previous
    observed, = result.catalog["checks"]
    assert observed["status"] == status
    assert any(row["group"] == "catalog.qualification" and row["required"] and row["status"] == status
               for row in result.report["checks"])


def test_unknown_supported_reasoning_keeps_admitted_catalog_and_sql(source):
    project = _project(source)
    project["catalog"]["relationships"][0]["nulls"] = "unknown"
    _save(source / "project.ddk.json", project)
    result = assemble_catalog(source / "project.ddk.json", required_groups=("catalog.relationships",))
    assert result.report["decision"] == "incomplete"
    assert result.catalog is not None and result.companions
    assert not result.artifacts
    assert any(row["status"] == "unknown" and row["group"] == "catalog.relationships"
               for row in result.report["checks"])


@pytest.mark.parametrize("failure", ["missing-context", "unbound-execution", "missing-field"])
def test_invalid_structure_has_no_admitted_view_or_companions(source, failure):
    project = _project(source)
    recipe = _recipe(project)
    if failure == "missing-context":
        recipe["contextualRelationships"] = ["urn:test:missing-relationship"]
    elif failure == "unbound-execution":
        recipe["relationships"] = [LINK]
    else:
        project["catalog"]["relationships"][0]["source"]["paths"] = [[{"field": "absent"}]]
    _save(source / "project.ddk.json", project)
    result = assemble_catalog(source / "project.ddk.json")
    assert result.report["decision"] == "failed"
    assert result.catalog is None
    assert not result.companions and not result.artifacts
    if failure == "missing-context":
        assert any(item["code"] == "CATALOG-RECIPE-RELATIONSHIP"
                   for check in result.report["checks"] for item in check["diagnostics"])


def test_contextual_relationships_preserve_notes_without_binding_unread_tables(source):
    project = _project(source)
    recipe = _recipe(project)
    recipe.update(title="Read qualified revenue", notes=["The customer link explains the upstream calculation."],
                  contextualRelationships=[LINK])
    _save(source / "project.ddk.json", project)
    result = assemble_catalog(source / "project.ddk.json", metadata=source / "catalog" / "metadata.example.json",
                              metadata_adapter="example")
    assert result.report["decision"] == "passed"
    admitted, = [row for row in result.catalog["recipes"] if row["id"] == RECIPE]
    assert admitted["title"] == "Read qualified revenue"
    assert admitted["notes"] == ["The customer link explains the upstream calculation."]
    assert admitted["contextualRelationships"] == [LINK]
    binding = resolve_query(result.catalog, RECIPE, versions={"daily_revenue": REVENUE})
    assert set(binding["inputs"]) == {"daily_revenue"}
    assert admitted["relationships"] == []


def test_project_extensions_keep_each_declaring_scope_without_semantic_interpretation(source):
    project = _project(source)
    project["extensions"] = {DOMAIN: {"upstream_relations": ["origin"]}}
    project["imports"]["other"] = {"path": "other.ddk.json"}
    _save(source / "project.ddk.json", project)
    imported = {
        "specVersion": "0.1", "kind": "project", "id": "urn:test:other-project", "version": "2.0.0",
        "requiredChecks": project["requiredChecks"],
        "artifacts": {"imported": {"kind": "dataset", "path": "datasets/commerce.odcs.json", "object": "orders"}},
        "extensions": {DOMAIN: {"upstream_relations": ["other-origin"]}},
    }
    _save(source / "other.ddk.json", imported)
    result = assemble_catalog(source / "project.ddk.json")
    assert result.report["decision"] == "passed"
    records = result.catalog["extensions"][DETAILS]["projectExtensions"]
    assert {(row["project"]["id"], row["namespace"]) for row in records} == {
        ("urn:example:commerce-project", ""), ("urn:test:other-project", "other"),
    }
    assert {row["project"]["id"]: row["extensions"][DOMAIN]["upstream_relations"] for row in records} == {
        "urn:example:commerce-project": ["origin"], "urn:test:other-project": ["other-origin"],
    }


def test_public_result_never_exposes_withheld_recipe_bytes_or_context_ids(source, tmp_path):
    project = _project(source)
    _recipe(project).update(title="Private title", notes=["Private note"], contextualRelationships=[LINK])
    project["extensions"] = {DOMAIN: {"private": "private-upstream"}}
    _save(source / "project.ddk.json", project)
    policy = tmp_path / "public.json"
    _save(policy, {"identifiers": ["urn:example:commerce:catalog", "urn:example:commerce-project",
                                   "urn:example:commerce:product", "urn:example:commerce-datasets",
                                   "urn:example:commerce:dataset:daily-revenue", RECIPE],
                   "recipes": [RECIPE]})
    result = assemble_catalog(source / "project.ddk.json", disclosure_policy=policy)
    assert result.report["decision"] == "passed"
    assert result.catalog["audience"] == "public"
    recipe, = result.catalog["recipes"]
    assert recipe["id"] == RECIPE
    assert recipe["contextualRelationships"] == []
    assert "title" not in recipe and "notes" not in recipe
    assert set(result.companions) == {recipe["sql"]}
    public = b"".join(result.artifacts.values())
    assert b"Private title" not in public and b"Private note" not in public
    assert b"private-upstream" not in public and LINK.encode() not in public
    assert "datasetDefinitions" not in result.catalog["extensions"][DETAILS]
    assert "projectExtensions" not in result.catalog["extensions"][DETAILS]
    assert result.report == json.loads(result.artifacts["catalog.report.json"])
    assert str(source) not in json.dumps(result.report)
    assert "daily-revenue" in json.dumps(result.local_report)


def test_public_definition_paths_keep_selected_meaning_and_shape_without_private_siblings(source, tmp_path):
    project = _project(source)
    project["artifacts"] = {alias: row for alias, row in project["artifacts"].items() if row["kind"] in {"dataset", "product"}}
    _save(source / "project.ddk.json", project)
    dataset_path = source / "datasets" / "commerce.odcs.json"
    contract = deepcopy(read_json(dataset_path).value)
    definition = next(row for row in contract["schema"] if row["name"] == "daily_revenue")
    definition["properties"].append({
        "name": "groups", "logicalType": "array", "physicalType": "private-composite-spelling", "required": False,
        "description": "private-parent-description", "customProperties": [{"property": "private", "value": "private-value"}],
        "items": {"logicalType": "object", "properties": [
            {"name": "visible", "logicalType": "string", "physicalType": "Utf8", "required": True,
             "businessName": "Public group name", "description": "The declared group name.",
             "id": "private-native-field-id", "customProperties": [{"property": "native-ref", "value": "urn:test:private-native-ref"}]},
            {"name": "private_sibling", "logicalType": "string", "description": "private-sibling-description"},
        ]},
    })
    _save(dataset_path, contract)
    path = [{"field": "groups"}, {"each": True}, {"field": "visible"}]
    policy = tmp_path / "public-definitions.json"
    _save(policy, {"identifiers": ["urn:example:commerce:catalog", "urn:example:commerce-project",
                                   "urn:example:commerce:product", "urn:example:commerce-datasets",
                                   "urn:example:commerce:dataset:daily-revenue"],
                   "aliases": ["daily-revenue"], "descriptions": True,
                   "definitionFields": {"urn:example:commerce:dataset:daily-revenue": [path]}})
    result = assemble_catalog(source / "project.ddk.json", disclosure_policy=policy)
    assert result.report["decision"] == "passed", result.report
    details = result.catalog["extensions"][DETAILS]
    assert details["disclosedDefinitionPaths"] == {"daily-revenue": [path]}
    [group] = details["datasetDefinitions"]["daily-revenue"]["properties"]
    assert group == {"name": "groups", "logicalType": "array", "required": False, "items": {
        "logicalType": "object", "properties": [{
            "name": "visible", "logicalType": "string", "physicalType": "Utf8", "required": True,
            "businessName": "Public group name", "description": "The declared group name.",
        }],
    }}
    public = b"".join(result.artifacts.values())
    assert b"private_sibling" not in public and b"private-sibling-description" not in public
    assert b"private-composite-spelling" not in public and b"private-parent-description" not in public
    assert b"private-native-field-id" not in public and b"private-native-ref" not in public
    assert b"private-value" not in public


@pytest.mark.parametrize("paths", [[[ {"field": "missing"} ]], [[{"field": "region"}, {"each": True}]]])
def test_public_definition_grants_must_resolve_to_declared_paths(source, tmp_path, paths):
    policy = tmp_path / "public-definitions.json"
    _save(policy, {"identifiers": ["urn:example:commerce:catalog", "urn:example:commerce-project",
                                   "urn:example:commerce:product", "urn:example:commerce-datasets",
                                   "urn:example:commerce:dataset:daily-revenue"],
                   "definitionFields": {"urn:example:commerce:dataset:daily-revenue": paths}})
    result = assemble_catalog(source / "project.ddk.json", disclosure_policy=policy)
    assert result.report["decision"] == "failed"
    assert result.catalog is None and not result.companions and not result.artifacts


@pytest.mark.parametrize("descriptions", [False, True])
def test_public_field_grants_do_not_disclose_original_object_name(source, tmp_path, descriptions):
    dataset_path = source / "datasets" / "commerce.odcs.json"
    contract = deepcopy(read_json(dataset_path).value)
    definition = next(row for row in contract["schema"] if row["name"] == "daily_revenue")
    definition["name"] = "private-object-name"
    _save(dataset_path, contract)
    policy = tmp_path / "public-definition.json"
    _save(policy, {"identifiers": ["urn:example:commerce:catalog", "urn:example:commerce-project",
                                   "urn:example:commerce:product", "urn:example:commerce-datasets",
                                   "urn:example:commerce:dataset:daily-revenue"],
                   "descriptions": descriptions,
                   "definitionFields": {"urn:example:commerce:dataset:daily-revenue": [[{"field": "region"}]]}})
    result = assemble_catalog(source / "project.ddk.json", disclosure_policy=policy)
    assert result.report["decision"] == "passed", result.report
    assert b"private-object-name" not in b"".join(result.artifacts.values())
    dataset, = result.catalog["datasets"]
    reduced, = result.catalog["extensions"][DETAILS]["datasetDefinitions"].values()
    assert reduced["name"] == dataset["definition"]["object"]


def test_incomplete_public_result_has_a_safe_report_and_no_publishable_controls(source, tmp_path):
    policy = tmp_path / "public.json"
    _save(policy, {"identifiers": ["urn:example:commerce:catalog", "urn:example:commerce-project",
                                   "urn:example:commerce:product", "urn:example:commerce-datasets",
                                   "urn:example:commerce:dataset:daily-revenue"]})
    result = assemble_catalog(source / "project.ddk.json", disclosure_policy=policy,
                              required_groups=("catalog.qualification",))
    assert result.report["decision"] == result.local_report["decision"] == "incomplete"
    assert result.catalog is not None
    assert not result.artifacts
    assert result.report["scope"]["artifacts"] == [row["alias"] for row in result.catalog["datasets"]]
    assert "metadata" not in result.report
    assert str(source) not in json.dumps(result.report)
    assert "daily-revenue" not in json.dumps(result.report)
    assert not validate_document(result.report, "report")


@pytest.mark.parametrize("failure", ["missing-policy", "invalid-policy", "missing-project"])
def test_early_public_failure_keeps_internal_diagnostics_out_of_report(source, tmp_path, failure):
    options = {"audience": "public"}
    project = source / "project.ddk.json"
    if failure == "invalid-policy":
        policy = tmp_path / "private-policy.json"
        _save(policy, {"unknown-private-setting": "private-domain-value"})
        options["disclosure_policy"] = policy
    elif failure == "missing-project":
        project = source / "private-missing-project.json"
    result = assemble_catalog(project, **options)
    assert result.report["decision"] in {"failed", "error"}
    assert result.catalog is None and not result.companions and not result.artifacts
    public = json.dumps(result.report)
    assert str(source) not in public and str(tmp_path) not in public
    assert "private-domain-value" not in public and "daily-revenue" not in public
    assert result.report["scope"]["projects"] == ["urn:ddk:project:withheld"]
    assert not validate_document(result.report, "report")


def test_public_extensions_require_an_exact_source_project_and_namespace_grant(source, tmp_path):
    project = _project(source)
    project["extensions"] = {DOMAIN: {"upstream_relations": ["declared-source"]},
                             "urn:test:private-extension": {"private": "private-domain-detail"}}
    _save(source / "project.ddk.json", project)
    policy = tmp_path / "public-extensions.json"
    disclosure = {"identifiers": ["urn:example:commerce:catalog", "urn:example:commerce-project",
                                   "urn:example:commerce:product", "urn:example:commerce-datasets",
                                   "urn:example:commerce:dataset:daily-revenue"],
                  "projectExtensions": [{"project": {"id": "urn:example:commerce-project", "version": "1.0.0"},
                                         "extensions": [DOMAIN]}]}
    _save(policy, disclosure)
    result = assemble_catalog(source / "project.ddk.json", disclosure_policy=policy)
    assert result.report["decision"] == "passed"
    [scoped] = result.catalog["extensions"][DETAILS]["projectExtensions"]
    assert scoped == {"project": {"id": "urn:example:commerce-project", "version": "1.0.0"}, "namespace": "",
                      "extensions": {DOMAIN: {"upstream_relations": ["declared-source"]}}}
    assert b"private-domain-detail" not in b"".join(result.artifacts.values())
    disclosure["projectExtensions"][0]["project"]["version"] = "2.0.0"
    _save(policy, disclosure)
    wrong_scope = assemble_catalog(source / "project.ddk.json", disclosure_policy=policy)
    assert wrong_scope.report["decision"] == "failed" and wrong_scope.catalog is None


def test_positional_parameter_order_is_authored_and_survives_binding(source):
    project = _project(source)
    recipe = _recipe(project)
    recipe["parameters"] = {"type": "object", "properties": {
        "congress": {"type": "integer"}, "system_code": {"type": "string"},
    }, "required": ["congress", "system_code"], "additionalProperties": False}
    recipe["parameterOrder"] = ["system_code", "congress"]
    (source / recipe["sql"]).write_bytes(b"SELECT ? AS system_code, ? AS congress\n")
    _save(source / "project.ddk.json", project)
    result = assemble_catalog(source / "project.ddk.json", metadata=source / "catalog" / "metadata.example.json",
                              metadata_adapter="example")
    assert result.report["decision"] == "passed"
    binding = resolve_query(result.catalog, RECIPE, parameters={"congress": 119, "system_code": "HSAG"},
                            versions={"daily_revenue": REVENUE})
    assert binding["parameterOrder"] == ["system_code", "congress"]
    assert [binding["parameters"][name] for name in binding["parameterOrder"]] == ["HSAG", 119]


@pytest.mark.parametrize("order", [["congress"], ["congress", "system_code", "other"],
                                  ["congress", "congress"], ["congress", "system_code", "system_code"]])
def test_positional_parameter_order_rejects_missing_extra_and_duplicate_names(source, order):
    project = _project(source)
    recipe = _recipe(project)
    recipe["parameters"] = {"type": "object", "properties": {
        "congress": {"type": "integer"}, "system_code": {"type": "string"},
    }}
    recipe["parameterOrder"] = order
    _save(source / "project.ddk.json", project)
    result = assemble_catalog(source / "project.ddk.json")
    assert result.report["decision"] == "failed"
    assert result.catalog is None and not result.companions


@pytest.mark.parametrize("conflict", [None, "scope", "type"])
def test_one_virtual_field_can_support_row_position_and_an_additional_unique_key(tmp_path, conflict):
    source = tmp_path / "virtual"
    shutil.copytree(COMMERCE.parent / "nested", source)
    project = _project(source)
    position = deepcopy(project["catalog"]["identities"][1])
    position["kind"] = "key"
    position["meaning"] = "The same release-local row position is also a unique candidate key."
    if conflict == "scope":
        position["scope"] = "dataset_version"
    elif conflict == "type":
        position["fields"][0]["physicalType"] = "string"
    project["catalog"]["identities"].append(position)
    project["catalog"]["relationships"][1]["cardinality"] = "many_to_one"
    _save(source / "project.ddk.json", project)
    result = assemble_catalog(source / "project.ddk.json")
    if conflict:
        assert result.report["decision"] == "failed" and result.catalog is None
        assert any(diagnostic["code"] == "CATALOG-AUTHORITY-CONFLICT"
                   for check in result.report["checks"] for diagnostic in check["diagnostics"])
    else:
        assert result.report["decision"] == "passed", result.report
        assert len(result.catalog["identities"]) == 3
        assert any(row["kind"] == "key" and row["fields"][0]["path"] == [{"field": "record.id"}]
                   for row in result.catalog["identities"])
        assert all(row["name"] != "$position"
                   for row in result.catalog["extensions"][DETAILS]["datasetDefinitions"]["register"]["properties"])
