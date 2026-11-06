"""Explicit managed type selections bind original definitions, never retrofit evidence."""
from copy import deepcopy
from hashlib import sha256
import inspect

import pytest

from ddk.arrow_observation import MANAGED_SCHEMA_V2
from ddk.catalog import assemble_catalog
from ddk.catalog_managed_jobs import managed_job_definition
from ddk.catalog_managed_jobs import _key_obligations
from ddk.catalog_native_rules import native_rule_artifact
from ddk.documents import read_json

from test_managed_jobs import (  # reuse metadata construction, not expected type semantics
    native_job, _authored_project, _mapping_kwargs, _metadata, _raw, _with_output_schema,
    _original_job, _retarget_original_job, _FixtureRuleProfile,
)

pa = pytest.importorskip("pyarrow")
PROFILES = {"daily-revenue": MANAGED_SCHEMA_V2}


def authored(tmp_path, *, minimum=None):
    project = _authored_project(tmp_path)
    path = project.parent / "definitions.json"
    value = deepcopy(read_json(path).value)
    field = value["schema"][1]["properties"][0]
    field["physicalType"] = "Int64"
    field["logicalTypeOptions"] = {"format": "i64", **({"minimum": minimum} if minimum is not None else {})}
    path.write_bytes(_raw(value))
    return project


def trace(result):
    return result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]


def test_explicit_profile_changes_definition_and_old_evidence_cannot_be_reinterpreted(native_job, tmp_path):
    project = authored(tmp_path)
    old = assemble_catalog(project)
    explicit = assemble_catalog(project, managed_schema_profiles=PROFILES)
    old_definition = managed_job_definition(old, **_mapping_kwargs())
    new_definition = managed_job_definition(explicit, **_mapping_kwargs())
    assert old_definition != new_definition
    assert managed_job_definition(assemble_catalog(project, managed_schema_profiles={}), **_mapping_kwargs()) == old_definition
    # Selecting an input interpretation cannot change this output's definition.
    assert managed_job_definition(assemble_catalog(project, managed_schema_profiles={"orders": MANAGED_SCHEMA_V2}), **_mapping_kwargs()) == old_definition
    schema = pa.schema([pa.field("id", pa.int64(), nullable=False)])
    metadata, _, _ = _metadata(tmp_path, _with_output_schema(native_job, schema, definition=old_definition))
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", managed_schema_profiles=PROFILES)
    assert result.report["decision"] != "passed" and not result.artifacts
    check = next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-definition-capture:1")
    assert check["status"] == "unknown"
    metadata, _, _ = _metadata(tmp_path, _with_output_schema(native_job, schema, definition=new_definition))
    current = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", managed_schema_profiles=PROFILES)
    assert current.report["decision"] == "passed", current.report
    observation = trace(current)
    assert observation["profile"]["version"] == "2"
    assert observation["declarationProfile"] == "urn:ddk:odcs:arrow-declaration:2"
    assert observation["rowObligations"] == []


@pytest.mark.parametrize("profiles", [{"typo": MANAGED_SCHEMA_V2}, {"daily-revenue": "guessed"}, [], True])
def test_unknown_selection_refuses_without_outputs(tmp_path, profiles):
    result = assemble_catalog(authored(tmp_path), managed_schema_profiles=profiles)
    assert result.report["decision"] != "passed" and not result.artifacts


class SelectedProfile(_FixtureRuleProfile):
    def bindings(self, context, original_job):
        assert context.schema_profiles == PROFILES
        with pytest.raises(TypeError):
            context.schema_profiles["daily-revenue"] = "guessed"
        return super().bindings(context, original_job)


@pytest.mark.parametrize("minimum", [None, 10])
def test_native_required_evidence_closes_only_its_facet_with_selected_type_profile(native_job, tmp_path, minimum):
    project = authored(tmp_path, minimum=minimum)
    capture = assemble_catalog(project, managed_schema_profiles=PROFILES)
    source = tmp_path / "rule.py"
    source.write_text(inspect.getsource(SelectedProfile) + inspect.getsource(_FixtureRuleProfile))
    profile = SelectedProfile(source)
    job = _original_job(tmp_path)
    value = native_rule_artifact(capture, _raw(job), native_rule_profile=profile, **_mapping_kwargs())
    path = tmp_path / "rules.json"
    path.write_bytes(_raw(value))
    pin = {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
    definition = managed_job_definition(capture, native_rules=pin, native_rule_profile=profile, **_mapping_kwargs())
    row = _with_output_schema(_retarget_original_job(native_job, job), pa.schema([pa.field("id", pa.int64(), nullable=True)]), definition=definition)
    metadata, entry, _ = _metadata(tmp_path, row)
    entry["nativeRules"] = pin
    metadata.document.path.write_bytes(_raw({"managedExecutions": [entry]}))
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local",
                              native_rule_profile=profile, managed_schema_profiles=PROFILES, permitted_roots=(tmp_path,))
    assert result.report["decision"] == ("passed" if minimum is None else "incomplete"), result.report
    observed = trace(result)
    assert observed["status"] == "passed" and observed["fields"][0]["nullable"] is True
    rows = {row["facet"]: row for row in observed["rowObligations"]}
    assert rows["required"]["status"] == "passed"
    assert rows["required"]["nativeCounter"]["column"] == "orphan_count"
    assert "logicalTypeOptions/format" not in rows
    if minimum is not None:
        assert rows["logicalTypeOptions/minimum"]["status"] == "unknown"


def row_identity_project(tmp_path, properties):
    project = authored(tmp_path)
    path = project.parent / "definitions.json"
    document = deepcopy(read_json(path).value)
    definition = document["schema"][1]
    definition["properties"].append({"name": "original_id", "logicalType": "string", "required": True})
    definition["customProperties"] = properties
    path.write_bytes(_raw(document))
    value = deepcopy(read_json(project).value)
    value["catalog"]["identities"] = [{"dataset": "daily-revenue", "kind": "key", "scope": "dataset_version",
        "meaning": "An independent alternate key", "fields": [{"path": [{"field": "id"}], "virtual": False, "physicalType": "Int64"}]}]
    project.write_bytes(_raw(value))
    return project, definition


def test_root_row_identity_survives_a_distinct_project_key(native_job, tmp_path):
    project, declaration = row_identity_project(tmp_path, [{"vendor": "ddk", "property": "rowIdentity", "value": ["original_id"]}])
    capture = assemble_catalog(project, managed_schema_profiles=PROFILES)
    assert capture.report["decision"] == "passed", capture.report
    definition = managed_job_definition(capture, **_mapping_kwargs())
    actual = pa.schema([pa.field("id", pa.int64(), nullable=False), pa.field("original_id", pa.string(), nullable=False)])
    metadata, _, _ = _metadata(tmp_path, _with_output_schema(native_job, actual, definition=definition))
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", managed_schema_profiles=PROFILES)
    observed = trace(result)
    assert observed["status"] == "passed"
    keys = [row for row in observed["rowObligations"] if row["facet"] == "key_unique"]
    assert {row["paths"][0][0]["field"] for row in keys} == {"id", "original_id"}
    assert all(row["status"] == "unknown" for row in keys)
    assert result.report["decision"] == "incomplete"
    # Typed native generators can bind that separate authored facet too.
    obligations = _key_obligations(declaration, [], "daily-revenue", [])
    assert {row["facet"] for row in obligations} == {"key_unique", "key_not_null"}


@pytest.mark.parametrize("properties", [
    [{"vendor": "ddk", "property": "rowIdentity", "value": "original_id"}],
    [{"vendor": "ddk", "property": "rowIdentity", "value": ["original_id", "original_id"]}],
    [{"vendor": "ddk", "property": "rowIdentity", "value": ["absent"]}],
    [{"vendor": "ddk", "property": "rowIdentity", "value": []}],
    [{"vendor": "ddk", "property": "rowIdentity", "value": ["original_id"]}] * 2,
])
def test_project_key_cannot_hide_malformed_or_repeated_row_identity(tmp_path, properties):
    project, _ = row_identity_project(tmp_path, properties)
    result = assemble_catalog(project, managed_schema_profiles=PROFILES)
    assert result.report["decision"] == "failed" and not result.artifacts
