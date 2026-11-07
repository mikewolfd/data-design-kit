"""Explicit native types and logical options from one admitted definition snapshot."""

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ddk.catalog import assemble_catalog
from ddk.documents import validate_document


DETAILS = "urn:ddk:catalog:assembly"
DATASET = "urn:test:physical-types:dataset"
NATIVE = 'STRUCT(id BIGINT, "name" VARCHAR, raw_name VARCHAR, parent_id BIGINT, slug VARCHAR)[]'
NAMES = ["id", "name", "raw_name", "parent_id", "slug"]
AGENCIES = [{"field": "agencies"}]
ELEMENT = [*AGENCIES, {"each": True}]
FULL = [[], AGENCIES, ELEMENT, *[[*ELEMENT, {"field": name}] for name in NAMES]]


def save(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


@pytest.fixture
def inputs(tmp_path):
    contract = {
        "apiVersion": "v3.2.0", "kind": "DataContract", "id": "urn:test:physical-types:contract", "version": "1.0.0",
        "name": "Independent native type disclosure", "status": "draft", "schema": [{
            "id": "records", "name": "private_native_object", "logicalType": "object", "businessName": "Public records",
            "description": "One retained metadata record.", "physicalType": "STRUCT(private_root_native VARCHAR)",
            "properties": [
                {"name": "agencies", "logicalType": "array", "physicalType": NATIVE, "required": False,
                 "items": {"logicalType": "object", "properties": [
                     {"name": "id", "logicalType": "integer"}, {"name": "name", "logicalType": "string"},
                     {"name": "raw_name", "logicalType": "string"}, {"name": "parent_id", "logicalType": "integer"},
                     {"name": "slug", "logicalType": "string"},
                 ]}},
                {"name": "details", "logicalType": "object", "physicalType": 'STRUCT("visible" VARCHAR, codes SMALLINT[])',
                 "properties": [{"name": "visible", "logicalType": "string", "physicalType": "VARCHAR"},
                                {"name": "codes", "logicalType": "array", "physicalType": "SMALLINT[]",
                                 "items": {"logicalType": "integer", "physicalType": "SMALLINT"}}]},
                {"name": "bare_object", "logicalType": "object", "physicalType": "STRUCT(native_only_object VARCHAR)"},
                {"name": "bare_array", "logicalType": "array", "physicalType": "STRUCT(native_only_array VARCHAR)[]"},
                {"name": "scalar", "logicalType": "string", "physicalType": "VARCHAR(9)", "required": True},
                {"name": "private_sibling", "logicalType": "string", "description": "private-sibling-meaning"},
            ],
        }],
    }
    save(tmp_path / "schema.odcs.json", contract)
    save(tmp_path / "product.odps.json", {
        "apiVersion": "v1.1.0", "kind": "DataProduct", "id": "urn:test:physical-types:product", "version": "1.0.0",
        "name": "Native metadata fixture", "status": "draft", "outputPorts": [{
            "name": "records", "contractId": "urn:test:physical-types:contract", "version": "1.0.0",
        }],
    })
    save(tmp_path / "project.ddk.json", {
        "specVersion": "0.1", "kind": "project", "id": "urn:test:physical-types:project", "version": "1.0.0",
        "requiredChecks": ["core.documents", "core.references", "core.graph", "core.calls", "core.datasets", "core.policies"],
        "artifacts": {"records": {"kind": "dataset", "path": "schema.odcs.json", "object": "records", "catalogId": DATASET},
                      "product": {"kind": "product", "path": "product.odps.json"}},
        "catalog": {"id": "urn:test:physical-types:catalog"},
    })
    save(tmp_path / "metadata.json", {})
    return tmp_path


def policy(root, fields, types=None, logical_options=None):
    value = {"identifiers": ["urn:test:physical-types:catalog", "urn:test:physical-types:project",
                             "urn:test:physical-types:product", "urn:test:physical-types:contract", DATASET],
             "aliases": ["records"], "descriptions": True, "definitionFields": {DATASET: fields}}
    if types is not None:
        value["definitionPhysicalTypes"] = {DATASET: types}
    if logical_options is not None:
        value["definitionLogicalTypeOptions"] = {DATASET: logical_options}
    save(root / "disclosure.json", value)
    return value


def assemble(root, **kwargs):
    return assemble_catalog(root / "project.ddk.json", disclosure_policy=root / "disclosure.json",
                            metadata=root / "metadata.json", metadata_adapter="local", **kwargs)


def definition(result, *, local=False):
    catalog = result.local_catalog if local else result.catalog
    return catalog["extensions"][DETAILS]["datasetDefinitions"]["records"]


def field(result, name="agencies", *, local=False):
    return next(row for row in definition(result, local=local)["properties"] if row["name"] == name)


@pytest.mark.parametrize("logical_type,options", [
    ("integer", {"format": "i64", "minimum": -9223372036854775808, "maximum": 9223372036854775807}),
    ("string", {"format": "binary", "pattern": "^private-format-[0-9]+$", "minLength": 0}),
    ("timestamp", {"format": "yyyy-MM-dd HH:mm:ss.SSSSSSXXX", "timezone": True, "defaultTimezone": "Etc/UTC"}),
    ("integer", {}),
])
def test_logical_options_require_explicit_permission_and_preserve_exact_values(inputs, logical_type, options):
    source = inputs / "schema.odcs.json"
    contract = json.loads(source.read_bytes())
    scalar = contract["schema"][0]["properties"][4]
    scalar.pop("physicalType")
    scalar.update(logicalType=logical_type, logicalTypeOptions=options)
    save(source, contract)
    path = [{"field": "scalar"}]
    policy(inputs, [path])
    withheld = assemble(inputs)
    assert withheld.report["decision"] == "passed", withheld.local_report
    assert "logicalTypeOptions" not in field(withheld, "scalar")
    assert field(withheld, "scalar", local=True)["logicalTypeOptions"] == options

    policy(inputs, [path], logical_options=[path])
    allowed = assemble(inputs)
    assert allowed.report["decision"] == "passed", allowed.local_report
    assert field(allowed, "scalar")["logicalTypeOptions"] == options
    assert not validate_document(allowed.catalog, "catalog")
    captured = dict(allowed.artifacts)
    field(allowed, "scalar")["logicalTypeOptions"]["changed_after_assembly"] = True
    assert field(allowed, "scalar", local=True)["logicalTypeOptions"] == options
    assert dict(allowed.artifacts) == captured


def test_options_permission_is_path_specific_and_does_not_grant_descendants(inputs):
    source = inputs / "schema.odcs.json"
    contract = json.loads(source.read_bytes())
    agencies = contract["schema"][0]["properties"][0]
    agencies["logicalTypeOptions"] = {"minItems": 0, "maxItems": 5, "uniqueItems": False}
    agencies["items"]["properties"][0]["logicalTypeOptions"] = {"format": "i64"}
    save(source, contract)
    policy(inputs, FULL, [AGENCIES], logical_options=[AGENCIES])
    parent = assemble(inputs)
    assert parent.report["decision"] == "passed", parent.local_report
    assert field(parent)["logicalTypeOptions"] == {"minItems": 0, "maxItems": 5, "uniqueItems": False}
    assert "logicalTypeOptions" not in field(parent)["items"]["properties"][0]
    leaf = [*ELEMENT, {"field": "id"}]
    policy(inputs, FULL, [AGENCIES], logical_options=[AGENCIES, leaf])
    both = assemble(inputs)
    assert both.report["decision"] == "passed", both.local_report
    assert field(both)["items"]["properties"][0]["logicalTypeOptions"] == {"format": "i64"}


def test_object_options_are_withheld_from_partial_views_and_preserve_prior_output(inputs):
    source = inputs / "schema.odcs.json"
    contract = json.loads(source.read_bytes())
    options = {"required": ["id", "private_unmodeled_name"], "minProperties": 2}
    contract["schema"][0]["properties"][0]["items"]["logicalTypeOptions"] = options
    save(source, contract)
    policy(inputs, FULL, logical_options=[ELEMENT])
    output = inputs / "published"
    previous = assemble(inputs, output=output)
    assert previous.report["decision"] == "passed", previous.local_report
    assert field(previous)["items"]["logicalTypeOptions"] == options
    assert [row["name"] for row in field(previous)["items"]["properties"]] == NAMES
    field(previous)["items"]["logicalTypeOptions"]["required"].append("changed_after_assembly")
    assert field(previous, local=True)["items"]["logicalTypeOptions"] == options
    partial = [[*ELEMENT, {"field": "id"}]]
    policy(inputs, partial)
    hidden = assemble(inputs)
    assert hidden.report["decision"] == "passed", hidden.local_report
    assert b"private_unmodeled_name" not in b"".join(hidden.artifacts.values())
    policy(inputs, partial, logical_options=[ELEMENT])
    refused = assemble(inputs, output=output)
    assert refused.report["decision"] == "failed" and not refused.artifacts
    assert {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()} == dict(previous.artifacts)


@pytest.mark.parametrize("grant", [[], [{"field": "missing"}], [{"field": "scalar"}]])
def test_logical_option_grants_refuse_root_missing_field_and_missing_options(inputs, grant):
    policy(inputs, FULL, logical_options=[grant])
    result = assemble(inputs)
    assert result.report["decision"] == "failed" and not result.artifacts
    assert (result.local_catalog is not None) == bool(grant)
    assert any(item["code"] == "CATALOG-DISCLOSURE" for check in result.report["checks"] for item in check["diagnostics"])
    policy(inputs, FULL)
    hidden = assemble(inputs)
    assert hidden.report["decision"] == "passed", hidden.local_report
    assert "logicalTypeOptions" not in definition(hidden)
    assert b"private_sibling" not in b"".join(hidden.artifacts.values())


def test_logical_options_grant_uses_original_dataset_identity_when_alias_is_private(inputs):
    source = inputs / "schema.odcs.json"
    contract = json.loads(source.read_bytes())
    contract["schema"][0]["properties"][4]["logicalTypeOptions"] = {"maxLength": 9}
    save(source, contract)
    path = [{"field": "scalar"}]
    value = policy(inputs, [path], logical_options=[path])
    value["aliases"] = []
    save(inputs / "disclosure.json", value)
    result = assemble(inputs)
    assert result.report["decision"] == "passed", result.local_report
    definitions = result.catalog["extensions"][DETAILS]["datasetDefinitions"]
    assert "records" not in definitions
    assert next(iter(definitions.values()))["properties"][0]["logicalTypeOptions"] == {"maxLength": 9}


@pytest.mark.parametrize("reversed_grants", [False, True])
def test_complete_modeled_fields_and_explicit_grant_preserve_the_independent_native_string(inputs, reversed_grants):
    policy(inputs, list(reversed(FULL)) if reversed_grants else FULL, [AGENCIES])
    result = assemble(inputs)
    assert result.report["decision"] == "passed", result.local_report
    assert field(result)["physicalType"] == 'STRUCT(id BIGINT, "name" VARCHAR, raw_name VARCHAR, parent_id BIGINT, slug VARCHAR)[]'
    assert [row["name"] for row in field(result)["items"]["properties"]] == NAMES
    assert field(result)["required"] is False
    assert "private_sibling" not in json.dumps(result.catalog)
    assert not validate_document(result.catalog, "catalog")


def test_complete_modeled_fields_without_type_permission_still_withhold_the_opaque_type(inputs):
    policy(inputs, FULL)
    result = assemble(inputs)
    assert result.report["decision"] == "passed"
    assert "physicalType" not in field(result)
    assert field(result, local=True)["physicalType"] == NATIVE


def test_partial_type_grant_fails_safely_and_preserves_the_previous_output_set(inputs):
    policy(inputs, FULL, [AGENCIES])
    output = inputs / "published"
    previous = assemble(inputs, output=output)
    assert previous.report["decision"] == "passed"
    policy(inputs, [[*ELEMENT, {"field": "id"}]])
    partial = assemble(inputs)
    assert partial.report["decision"] == "passed"
    assert [row["name"] for row in field(partial)["items"]["properties"]] == ["id"]
    public = b"".join(partial.artifacts.values())
    assert b"physicalType" not in public and b"raw_name" not in public and b"parent_id" not in public
    policy(inputs, [[*ELEMENT, {"field": "id"}]], [AGENCIES])
    refused = assemble(inputs, output=output)
    assert refused.report["decision"] == "failed" and refused.catalog is None and not refused.artifacts
    assert refused.local_catalog is not None and field(refused, local=True)["physicalType"] == NATIVE
    assert {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()} == dict(previous.artifacts)
    assert any(item["code"] == "CATALOG-DISCLOSURE" for check in refused.report["checks"] for item in check["diagnostics"])


def test_native_only_names_require_explicit_opaque_permission_and_never_create_logical_children(inputs):
    source = inputs / "schema.odcs.json"
    contract = json.loads(source.read_bytes())
    opaque = 'STRUCT(id BIGINT, "name" VARCHAR, raw_name VARCHAR, parent_id BIGINT, slug VARCHAR, private_native_only BLOB)[]'
    contract["schema"][0]["properties"][0]["physicalType"] = opaque
    save(source, contract)
    policy(inputs, FULL)
    withheld = assemble(inputs)
    assert withheld.report["decision"] == "passed"
    assert b"private_native_only" not in b"".join(withheld.artifacts.values())
    policy(inputs, FULL, [AGENCIES])
    allowed = assemble(inputs)
    assert allowed.report["decision"] == "passed"
    assert field(allowed)["physicalType"] == opaque
    assert [row["name"] for row in field(allowed)["items"]["properties"]] == NAMES


@pytest.mark.parametrize("name", ["bare_object", "bare_array"])
@pytest.mark.parametrize("grant", [False, True])
def test_declared_composites_without_modeled_children_still_need_explicit_permission(inputs, name, grant):
    path = [{"field": name}]
    policy(inputs, [path], [path] if grant else None)
    result = assemble(inputs)
    assert result.report["decision"] == "passed", result.local_report
    selected = field(result, name)
    if grant:
        assert selected["physicalType"] == ("STRUCT(native_only_object VARCHAR)" if name == "bare_object" else "STRUCT(native_only_array VARCHAR)[]")
    else:
        assert "physicalType" not in selected
        assert (b"native_only_object" if name == "bare_object" else b"native_only_array") not in b"".join(result.artifacts.values())
    assert "items" not in selected and "properties" not in selected


def test_nested_object_and_array_permissions_preserve_only_their_exact_native_values(inputs):
    node = [{"field": "details"}]
    array = [*node, {"field": "codes"}]
    policy(inputs, [[*node, {"field": "visible"}], [*array, {"each": True}]], [node, array])
    result = assemble(inputs)
    assert result.report["decision"] == "passed"
    assert field(result, "details")["physicalType"] == 'STRUCT("visible" VARCHAR, codes SMALLINT[])'
    assert field(result, "details")["properties"][1]["physicalType"] == "SMALLINT[]"
    assert field(result, "details")["properties"][1]["items"]["physicalType"] == "SMALLINT"


@pytest.mark.parametrize("invalid", ["dataset", "hidden-dataset", "path", "missing-type", "blank-type", "root"])
def test_incoherent_native_type_permissions_refuse_public_output(inputs, invalid):
    value = policy(inputs, FULL, [AGENCIES])
    if invalid == "dataset":
        value["definitionPhysicalTypes"] = {"urn:test:physical-types:absent": [AGENCIES]}
    elif invalid == "hidden-dataset":
        value["identifiers"].remove(DATASET)
    elif invalid == "path":
        value["definitionPhysicalTypes"][DATASET] = [[{"field": "absent"}]]
    elif invalid == "missing-type":
        value["definitionPhysicalTypes"][DATASET] = [ELEMENT]
    elif invalid == "blank-type":
        source = inputs / "schema.odcs.json"
        contract = json.loads(source.read_bytes())
        contract["schema"][0]["properties"][0]["physicalType"] = "   "
        save(source, contract)
    else:
        value["definitionPhysicalTypes"][DATASET] = [[]]
    save(inputs / "disclosure.json", value)
    result = assemble(inputs)
    assert result.report["decision"] == "failed" and result.catalog is None and not result.artifacts
    assert "private_native_object" not in json.dumps(result.report)


def test_root_metadata_and_existing_scalar_disclosure_do_not_grant_root_native_type(inputs):
    policy(inputs, [[], [{"field": "scalar"}]])
    result = assemble(inputs)
    assert result.report["decision"] == "passed"
    assert definition(result)["description"] == "One retained metadata record."
    assert "physicalType" not in definition(result)
    assert field(result, "scalar")["physicalType"] == "VARCHAR(9)" and field(result, "scalar")["required"] is True
    assert b"private_root_native" not in b"".join(result.artifacts.values())


def test_private_and_public_views_use_one_captured_source_and_one_metadata_read(inputs, monkeypatch):
    import ddk.inventory as inventory

    policy(inputs, FULL, [AGENCIES])
    schema = inputs / "schema.odcs.json"
    original_digest = sha256(schema.read_bytes()).hexdigest()
    opened = Counter()
    original_read = inventory.read_json

    def capture(path, **kwargs):
        path = Path(path).resolve()
        opened[path] += 1
        document = original_read(path, **kwargs)
        if path == schema:
            changed = deepcopy(document.value)
            changed["schema"][0]["properties"][0]["physicalType"] = "STRUCT(changed_after_admission BLOB)[]"
            save(path, changed)
        return document

    monkeypatch.setattr(inventory, "read_json", capture)
    result = assemble(inputs)
    assert result.report["decision"] == "passed", result.local_report
    assert opened[schema] == opened[inputs / "metadata.json"] == 1
    assert field(result)["physicalType"] == field(result, local=True)["physicalType"] == NATIVE
    local_record, = [row for row in result.local_catalog["sourceInventory"] if row["uri"] == schema.as_uri()]
    public_record, = [row for row in result.catalog["sourceInventory"] if row["uri"] == f"urn:ddk:sha256:{original_digest}"]
    assert local_record["sha256"] == public_record["sha256"] == original_digest
    assert sha256(schema.read_bytes()).hexdigest() != original_digest
    assert result.local_catalog["audience"] == "local" and result.catalog["audience"] == "public"
    assert field(result, "private_sibling", local=True)["description"] == "private-sibling-meaning"
    assert b"private-sibling-meaning" not in b"".join(result.artifacts.values())
    result.local_catalog["datasets"][0]["title"] = "local-only-mutated-title"
    assert result.catalog["datasets"][0]["title"] == "Public records"
    assert b"local-only-mutated-title" not in result.artifacts["catalog.ddk.json"]


def test_private_catalog_keeps_unresolved_qualification_and_rejects_structural_failure(inputs):
    policy(inputs, FULL, [AGENCIES])
    incomplete = assemble(inputs, required_groups=("catalog.qualification",))
    assert incomplete.report["decision"] == "incomplete" and incomplete.local_catalog is not None
    assert incomplete.catalog is not None and not incomplete.artifacts
    assert any(row["required"] and row["status"] == "not_run" for row in incomplete.report["checks"])
    source = inputs / "project.ddk.json"
    project = json.loads(source.read_bytes())
    project["catalog"]["identities"] = [{"dataset": "records", "kind": "key", "scope": "dataset_version",
                                          "meaning": "Invalid independent identity path.", "fields": [{
                                              "path": [{"field": "absent"}], "virtual": False, "physicalType": "string",
                                          }]}]
    save(source, project)
    failed = assemble(inputs)
    assert failed.report["decision"] == "failed" and failed.local_catalog is None and failed.catalog is None


def test_permitted_profile_source_is_isolated_between_private_and_public_views(inputs):
    source = Path(__file__).resolve()
    identity = {"id": "urn:test:physical-types:profile", "version": "1.0.0"}

    class Profile:
        def assess(self, _):
            raise AssertionError("The fixture has no relationships requiring profile reasoning.")

    profile = Profile()
    profile.identity, profile.source = identity, source
    value = policy(inputs, FULL, [AGENCIES])
    value["identifiers"].append(identity["id"])
    value["evidence"] = [source.as_uri()]
    save(inputs / "disclosure.json", value)
    result = assemble(inputs, relationship_profile=profile, permitted_roots=(source.parent,))
    assert result.report["decision"] == "passed", result.local_report
    private_source = result.local_catalog["extensions"][DETAILS]["relationshipProfile"]["source"]
    public_source = result.catalog["extensions"][DETAILS]["relationshipProfile"]["source"]
    assert private_source == public_source == {"uri": source.as_uri(), "sha256": sha256(source.read_bytes()).hexdigest()}
    captured_catalog = deepcopy(result.catalog)
    captured_artifacts = dict(result.artifacts)
    private_source.update(uri="file:///private/post-admission-source", sha256="0" * 64)
    assert public_source == captured_catalog["extensions"][DETAILS]["relationshipProfile"]["source"]
    assert result.catalog == captured_catalog
    assert dict(result.artifacts) == captured_artifacts
    assert json.loads(result.artifacts["catalog.ddk.json"]) == result.catalog
