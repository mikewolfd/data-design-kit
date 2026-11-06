"""Independent declaration profiles extend catalog reasoning without data claims."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ddk.catalog import assemble_catalog, build_catalog
from ddk.catalog_semantics import RelationshipAssessment
from ddk.documents import validate_document


HERE = Path(__file__).resolve()
DETAILS = "urn:ddk:catalog:assembly"
PROFILE = "urn:test:fixture:relationship-profile"
PARSE_NUMBER = "urn:test:fixture:parse-number"
LIST_OVERLAP = "urn:test:fixture:list-overlap"
OBJECT_REFERENCE = "urn:test:fixture:object-reference"
OBJECT_STORE = "urn:test:fixture:external-object-store"
RELATIONSHIP = "urn:test:fixture:relationship"
GROUPS = ["core.documents", "core.references", "core.graph", "core.calls", "core.datasets", "core.policies",
          "catalog.relationships"]


def save(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


@pytest.fixture
def project(tmp_path):
    fields = [
        {"name": "record_id", "logicalType": "string", "required": True, "primaryKey": True},
        {"name": "number_text", "logicalType": "string"},
        {"name": "number", "logicalType": "integer"},
        {"name": "tags", "logicalType": "array", "items": {"logicalType": "string"}},
        {"name": "suffix", "logicalType": "string"},
        *({"name": f"bytes{width}", "logicalType": "string", "physicalType": f"fixed[{width}]",
           "logicalTypeOptions": {"format": "binary"}} for width in (8, 32)),
    ]
    save(tmp_path / "data.odcs.json", {
        "apiVersion": "v3.2.0", "kind": "DataContract", "id": "urn:test:fixture:definitions", "version": "1.0.0",
        "name": "Independent relationship inputs", "status": "draft", "schema": [
            {"id": name, "name": name, "logicalType": "object", "properties": deepcopy(fields)} for name in ("left", "right")
        ],
    })
    save(tmp_path / "product.odps.json", {
        "apiVersion": "v1.1.0", "kind": "DataProduct", "id": "urn:test:fixture:product", "version": "1.0.0",
        "name": "Independent relationship fixture", "status": "draft",
        "inputPorts": [{"name": "left", "contractId": "urn:test:fixture:definitions", "version": "1.0.0"}],
        "outputPorts": [{"name": "right", "contractId": "urn:test:fixture:definitions", "version": "1.0.0"}],
    })
    path = tmp_path / "project.ddk.json"
    save(path, {
        "specVersion": "0.1", "kind": "project", "id": "urn:test:fixture:project", "version": "1.0.0",
        "requiredChecks": GROUPS, "artifacts": {
            **{name: {"kind": "dataset", "path": "data.odcs.json", "object": name, "catalogId": f"urn:test:fixture:{name}"}
               for name in ("left", "right")},
            "product": {"kind": "product", "path": "product.odps.json"},
        },
        "catalog": {"id": "urn:test:fixture:catalog", "ports": [
            {"product": "product", "direction": direction, "port": name, "version": "1.0.0", "dataset": name}
            for direction, name in (("input", "left"), ("output", "right"))
        ], "relationships": [{
            "id": RELATIONSHIP, "source": {"dataset": "left", "paths": [[{"field": "bytes8"}]]},
            "target": {"dataset": "right", "paths": [[{"field": "bytes8"}]]},
            "match": "equal", "cardinality": "many_to_many", "scope": "version_pair", "nulls": "skip",
            "resolution": "unresolved_allowed", "meaning": "Independent native byte equality declaration.",
        }]},
    })
    return path


def change(project, edit):
    value = json.loads(project.read_bytes())
    edit(value["catalog"]["relationships"][0])
    save(project, value)


def field_path(name, *, each=False):
    return [{"field": name}, *([{"each": True}] if each else [])]


class FixtureProfile:
    """Fixture-owned semantics; these rule IDs are independent of any consumer."""

    identity = {"id": PROFILE, "version": "1.0.0"}
    source = HERE

    def __init__(self):
        self.requests = []

    def assess(self, relationship):
        self.requests.append(relationship)
        declaration = relationship.declaration
        if declaration["match"] == "equal":
            if relationship.target is None:
                return RelationshipAssessment("unknown", "This fixture has no external equality comparison.")
            native_pairs = [(left.definition.get("physicalType"), right.definition.get("physicalType"))
                            for left, right in zip(relationship.source, relationship.target)]
            if all(left in {"fixed[8]", "fixed[32]"} and right in {"fixed[8]", "fixed[32]"}
                   for left, right in native_pairs):
                if all(left == right for left, right in native_pairs):
                    return RelationshipAssessment("supported", "The fixture compares identical native bytes of the same fixed width.")
                return RelationshipAssessment("failed", "The fixture's fixed byte widths differ.")
            return RelationshipAssessment("unknown", "The fixture does not interpret this native type.")
        rule = declaration["rule"]
        if rule["version"] != "1.0.0":
            return RelationshipAssessment("unknown", "This exact fixture rule version is unsupported.")
        source = [key.shared_type for key in relationship.source]
        target = [key.shared_type for key in relationship.target] if relationship.target is not None else None
        if rule["id"] == PARSE_NUMBER and source == ["string"] and target == ["integer"]:
            return RelationshipAssessment("supported", "The fixture declares base-ten text to exact integer conversion.")
        if rule["id"] == LIST_OVERLAP and source == target == ["string"] and all(
            {"each": True} in key.path for key in (*relationship.source, *relationship.target)
        ):
            return RelationshipAssessment("supported", "The fixture declares shared string elements with occurrence context retained.")
        if (rule["id"] == OBJECT_REFERENCE and relationship.target is None
                and declaration["target"]["external"] == OBJECT_STORE
                and [key.definition.get("physicalType") for key in relationship.source] == ["fixed[32]", None]
                and source == [None, "string"]):
            return RelationshipAssessment("supported", "The fixture constructs a digest/suffix reference; target existence is outside its scope.")
        return RelationshipAssessment("unknown", "The fixture has no semantics for this rule, endpoint, or type.")


def assemble(project, profile=None, **kwargs):
    return assemble_catalog(project, relationship_profile=profile, permitted_roots=(HERE.parent,), **kwargs)


def relationship_check(result):
    return next(check for check in result.report["checks"] if check["subject"] == RELATIONSHIP)


def test_shared_supported_equality_does_not_call_the_selected_profile(project):
    change(project, lambda row: [row[side].update(paths=[field_path("record_id")]) for side in ("source", "target")])
    profile = FixtureProfile()
    result = assemble(project, profile)
    assert result.report["decision"] == "passed"
    assert profile.requests == []
    assert result.catalog["extensions"][DETAILS]["relationshipAssessments"] == []


def test_profile_partial_diagnostics_survive_a_later_structural_failure(project):
    value = json.loads(project.read_bytes())
    invalid = {**deepcopy(value["catalog"]["relationships"][0]), "id": "urn:test:fixture:later-invalid"}
    invalid["source"]["paths"] = [field_path("absent")]
    value["catalog"]["relationships"].append(invalid)
    save(project, value)
    profile = FixtureProfile()
    result = assemble(project, profile)
    assert result.report["decision"] == "failed" and result.catalog is None
    assessment, = result.local_report["metadata"]["relationshipAssessments"]
    assert assessment["relationship"] == RELATIONSHIP and assessment["status"] == "supported"
    assert len(profile.requests) == 1


@pytest.mark.parametrize("width", [8, 32])
def test_selected_native_width_profile_establishes_only_declared_byte_compatibility(project, width):
    change(project, lambda row: [row[side].update(paths=[field_path(f"bytes{width}")]) for side in ("source", "target")])
    missing = assemble(project)
    assert missing.report["decision"] == "incomplete"
    assert relationship_check(missing)["status"] == "unknown"
    profile = FixtureProfile()
    result = assemble(project, profile)
    assert result.report["decision"] == "passed", result.report
    check = relationship_check(result)
    assert check["status"] == "passed" and check["evidence"] == "inferred"
    assert "evidenceRecords" not in check
    assert not result.catalog["runs"] and not result.catalog["checks"] and not result.catalog["versions"]
    request, = profile.requests
    assert request.source[0].definition["physicalType"] == f"fixed[{width}]"
    assert request.target[0].definition["physicalType"] == f"fixed[{width}]"
    assert request.source[0].shared_type is None


@pytest.mark.parametrize("rule", [PARSE_NUMBER, LIST_OVERLAP])
def test_versioned_fixture_rules_use_the_resolved_ordered_types_and_list_paths(project, rule):
    def edit(row):
        row.update(match="project_rule", rule={"id": rule, "version": "1.0.0"})
        row["source"]["paths"] = [field_path("number_text")] if rule == PARSE_NUMBER else [field_path("tags", each=True)]
        row["target"]["paths"] = [field_path("number")] if rule == PARSE_NUMBER else [field_path("tags", each=True)]
    change(project, edit)
    profile = FixtureProfile()
    result = assemble(project, profile)
    assert result.report["decision"] == "passed", result.report
    request, = profile.requests
    assert request.declaration["rule"] == {"id": rule, "version": "1.0.0"}
    assert request.source[0].shared_type == "string"


def test_external_reference_construction_does_not_observe_existence_or_qualification(project):
    change(project, lambda row: row.update(
        match="project_rule", rule={"id": OBJECT_REFERENCE, "version": "1.0.0"},
        source={"dataset": "left", "paths": [field_path("bytes32"), field_path("suffix")]},
        target={"external": OBJECT_STORE}, scope="external", resolution="external",
    ))
    result = assemble(project, FixtureProfile())
    assert result.report["decision"] == "passed", result.report
    assessment, = result.catalog["extensions"][DETAILS]["relationshipAssessments"]
    assert assessment["scope"] == "declaration-support-only" and assessment["externalExistence"] == "not_assessed"
    assert result.catalog["relationships"][0]["target"] == {"external": OBJECT_STORE}
    assert not result.catalog["versions"] and not result.catalog["runs"] and not result.catalog["checks"]
    qualification = assemble(project, FixtureProfile(), required_groups=("catalog.qualification",))
    assert qualification.report["decision"] == "incomplete"
    assert any(check["group"] == "catalog.qualification" and check["status"] == "not_run" for check in qualification.report["checks"])


@pytest.mark.parametrize("unsupported", ["rule-version", "rule-id", "native-type", "external-id"])
def test_unknown_exact_rule_versions_types_and_external_meanings_remain_required_unknown(project, unsupported):
    def edit(row):
        row.update(match="project_rule", rule={"id": PARSE_NUMBER, "version": "1.0.0"})
        row["source"]["paths"] = [field_path("number_text")]
        row["target"]["paths"] = [field_path("number")]
        if unsupported == "rule-version":
            row["rule"]["version"] = "2.0.0"
        elif unsupported == "rule-id":
            row["rule"]["id"] = "urn:test:fixture:not-supported"
        elif unsupported == "native-type":
            row["source"]["paths"] = [field_path("bytes8")]
        else:
            row.update(target={"external": "urn:test:fixture:other-store"}, scope="external", resolution="external")
    change(project, edit)
    result = assemble(project, FixtureProfile())
    assert result.report["decision"] == "incomplete"
    assert relationship_check(result)["status"] == "unknown" and relationship_check(result)["required"]
    assert result.catalog is not None and not result.artifacts


@pytest.mark.parametrize("order", [[8, 32], [32, 8]])
def test_composite_native_key_order_is_preserved_for_profile_reasoning(project, order):
    change(project, lambda row: [row[side].update(paths=[field_path(f"bytes{width}") for width in order])
                                 for side in ("source", "target")])
    profile = FixtureProfile()
    result = assemble(project, profile)
    assert result.report["decision"] == "passed", result.report
    assert [key.definition["physicalType"] for key in profile.requests[0].source] == [f"fixed[{width}]" for width in order]
    change(project, lambda row: row["target"].update(paths=[field_path(f"bytes{width}") for width in reversed(order)]))
    mismatch = assemble(project, FixtureProfile())
    assert mismatch.report["decision"] == "failed" and relationship_check(mismatch)["status"] == "failed"


@pytest.mark.parametrize("guard", ["path", "full-key", "key-count", "known-type", "partial-known-type", "nulls"])
def test_ddk_owned_structural_and_null_guards_cannot_be_overridden(project, guard):
    def edit(row):
        if guard == "path":
            row["source"]["paths"] = [field_path("absent")]
        elif guard == "full-key":
            row["cardinality"] = "many_to_one"
        elif guard == "key-count":
            row["source"]["paths"] = [field_path("bytes8"), field_path("bytes32")]
        elif guard == "known-type":
            row["source"]["paths"] = [field_path("number_text")]
            row["target"]["paths"] = [field_path("number")]
        elif guard == "partial-known-type":
            row["source"]["paths"] = [field_path("number_text"), field_path("bytes8")]
            row["target"]["paths"] = [field_path("number"), field_path("bytes8")]
        else:
            row["nulls"] = "unknown"
    change(project, edit)
    profile = FixtureProfile()
    result = assemble(project, profile)
    assert result.report["decision"] == ("incomplete" if guard == "nulls" else "failed")
    assert profile.requests == []


def test_release_local_virtual_scope_remains_a_ddk_guard(project):
    value = json.loads(project.read_bytes())
    value["catalog"]["identities"] = [{
        "dataset": "left", "kind": "row_position", "scope": "release", "meaning": "Fixture release-local position.",
        "fields": [{"path": field_path("position"), "virtual": True, "physicalType": "integer"}],
    }]
    value["catalog"]["relationships"][0]["source"]["paths"] = [field_path("position")]
    save(project, value)
    profile = FixtureProfile()
    result = assemble(project, profile)
    assert result.report["decision"] == "failed" and profile.requests == []
    assert any(diagnostic["code"] == "CATALOG-RELEASE-SCOPE" for check in result.report["checks"] for diagnostic in check["diagnostics"])


@pytest.mark.parametrize("malformed", [None, {"status": "supported", "reason": "untyped"},
                                       RelationshipAssessment("passed", "Not the supported status vocabulary."),
                                       RelationshipAssessment([], "Not a scalar status."),
                                       RelationshipAssessment("supported", "")])
def test_malformed_assessments_remain_required_unknown(project, malformed):
    class Malformed(FixtureProfile):
        def assess(self, _):
            return malformed
    result = assemble(project, Malformed())
    assert result.report["decision"] == "incomplete"
    assert relationship_check(result)["status"] == "unknown" and relationship_check(result)["required"]
    assert any(item["code"] == "CATALOG-PROFILE-RESULT" for item in relationship_check(result)["diagnostics"])
    assert result.catalog is not None and not result.artifacts


@pytest.mark.parametrize("bypass", [False, True])
def test_profile_input_mutation_cannot_change_admitted_definitions_or_declarations(project, bypass):
    original = project.read_bytes()
    class Mutating(FixtureProfile):
        def assess(self, relationship):
            if bypass:
                dict.__setitem__(relationship.declaration, "meaning", "tampered declaration")
                dict.__setitem__(relationship.source[0].definition, "description", "tampered field")
                return RelationshipAssessment("supported", "Fixture mutation isolation probe.")
            relationship.declaration["meaning"] = "tampered declaration"
    result = assemble(project, Mutating())
    assert result.report["decision"] == ("passed" if bypass else "incomplete")
    assert project.read_bytes() == original
    assert result.catalog["relationships"][0]["meaning"] == "Independent native byte equality declaration."
    fields = result.catalog["extensions"][DETAILS]["datasetDefinitions"]["left"]["properties"]
    assert all(field.get("description") != "tampered field" for field in fields)


def test_profile_source_is_read_once_per_refresh_and_locked_with_original_digest(project, monkeypatch):
    import ddk.catalog_semantics as semantics

    expected = sha256(HERE.read_bytes()).hexdigest()
    source_opens = []
    original = semantics.os.open
    def observe(path, *args, **kwargs):
        if Path(path).resolve() == HERE:
            source_opens.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(semantics.os, "open", observe)
    first = assemble(project, FixtureProfile())
    second = assemble(project, FixtureProfile())
    assert first.report["decision"] == second.report["decision"] == "passed"
    assert len(source_opens) == 2
    assert dict(first.artifacts) == dict(second.artifacts)
    source, = [record for record in first.catalog["sourceInventory"] if record["role"] == "implementation"]
    assert source == {"uri": HERE.as_uri(), "sha256": expected, "role": "implementation"}
    selected = first.catalog["extensions"][DETAILS]["relationshipProfile"]
    assert selected["identity"] == FixtureProfile.identity and selected["source"]["sha256"] == expected
    lock = json.loads(first.artifacts["catalog.lock.json"])
    assert lock["tools"][PROFILE] == {"version": "1.0.0"}
    assert {"path": HERE.as_uri(), "role": "implementation", "sha256": expected} in lock["files"]
    assert not validate_document(lock, "lock")
    assert build_catalog(project, relationship_profile=FixtureProfile(), permitted_roots=(HERE.parent,))["decision"] == "passed"


@pytest.mark.parametrize("identity", [{"id": PROFILE}, {"id": PROFILE, "version": "1.0.0"},
                                      {"id": "not-an-absolute-profile-id", "version": "1.0.0", "commit": "a" * 40}])
def test_missing_or_malformed_profile_identity_and_provenance_cannot_support_claims(project, identity):
    profile = FixtureProfile()
    profile.identity = identity
    profile.source = None
    result = assemble(project, profile)
    assert result.report["decision"] == "incomplete"
    assert result.catalog is None and not result.artifacts and profile.requests == []


def test_explicit_distribution_identity_is_retained_without_source_discovery(project):
    profile = FixtureProfile()
    profile.source = None
    profile.identity = {"id": PROFILE, "version": "2.1.0", "distributionSha256": "b" * 64}
    result = assemble(project, profile)
    assert result.report["decision"] == "passed"
    assert profile.identity in result.catalog["adapters"]
    assert not any(record["role"] == "implementation" for record in result.catalog["sourceInventory"])
    assert json.loads(result.artifacts["catalog.lock.json"])["tools"][PROFILE] == {
        "version": "2.1.0", "distributionSha256": "b" * 64,
    }


def test_source_obeys_permitted_roots_and_document_limit(project, tmp_path):
    outside = FixtureProfile()
    refused = assemble_catalog(project, relationship_profile=outside)
    assert refused.report["decision"] == "failed" and outside.requests == []
    oversized = FixtureProfile()
    oversized.source = tmp_path / "profile-source.py"
    oversized.source.write_bytes(b"# explicit fixture source\n" * 500)
    limited = assemble_catalog(project, relationship_profile=oversized, limits={"maxDocumentBytes": 4096})
    assert limited.report["decision"] == "error" and oversized.requests == []
    assert limited.catalog is None and not limited.artifacts


def test_public_profile_output_withholds_the_captured_implementation_location(project):
    policy = project.parent / "disclosure.json"
    save(policy, {"identifiers": ["urn:test:fixture:catalog", "urn:test:fixture:project", "urn:test:fixture:definitions",
                                  "urn:test:fixture:product", "urn:test:fixture:left", "urn:test:fixture:right", PROFILE]})
    result = assemble(project, FixtureProfile(), disclosure_policy=policy)
    assert result.report["decision"] == "passed", result.report
    assert str(HERE).encode() not in b"".join(result.artifacts.values())
    disclosed = result.catalog["extensions"][DETAILS]
    assert disclosed["relationshipProfile"]["identity"] == FixtureProfile.identity
    assert disclosed["relationshipProfile"]["source"]["uri"].startswith("urn:ddk:sha256:")
    assert disclosed["relationshipAssessmentScope"]["status"] == "unknown"
    assert "relationshipAssessments" not in disclosed
    record, = [item for item in result.catalog["sourceInventory"] if item["role"] == "implementation"]
    assert record["uri"] == f"urn:ddk:sha256:{sha256(HERE.read_bytes()).hexdigest()}"


@pytest.mark.parametrize("grant", [False, True])
def test_private_file_profile_identity_requires_an_explicit_public_identifier_grant(project, grant):
    private_id = HERE.as_uri()
    policy = project.parent / "profile-identity-disclosure.json"
    identifiers = ["urn:test:fixture:catalog", "urn:test:fixture:project", "urn:test:fixture:definitions",
                   "urn:test:fixture:product", "urn:test:fixture:left", "urn:test:fixture:right", PROFILE]
    save(policy, {"identifiers": identifiers})
    output = project.parent / "public-output"
    previous = assemble(project, FixtureProfile(), disclosure_policy=policy, output=output)
    assert previous.report["decision"] == "passed"
    profile = FixtureProfile()
    profile.identity = {"id": private_id, "version": "1.0.0"}
    if grant:
        save(policy, {"identifiers": [*identifiers, private_id]})
    result = assemble(project, profile, disclosure_policy=policy, output=output)
    if grant:
        assert result.report["decision"] == "passed", result.report
        assert profile.identity in result.catalog["adapters"]
        lock = json.loads(result.artifacts["catalog.lock.json"])
        assert lock["tools"][private_id] == {"version": "1.0.0"}
        # Identifier disclosure does not independently permit source locations.
        source, = [item for item in result.catalog["sourceInventory"] if item["role"] == "implementation"]
        assert source["uri"].startswith("urn:ddk:sha256:")
    else:
        assert result.report["decision"] == "failed"
        assert result.catalog is None and not result.artifacts
        assert private_id not in json.dumps(result.report) and str(HERE) not in json.dumps(result.report)
        assert result.local_report["metadata"]["relationshipProfile"]["identity"]["id"] == private_id
        assert {item.relative_to(output).as_posix(): item.read_bytes() for item in output.rglob("*") if item.is_file()} == dict(previous.artifacts)
        assert any(diagnostic["code"] == "CATALOG-DISCLOSURE"
                   for check in result.report["checks"] for diagnostic in check["diagnostics"])


@pytest.mark.parametrize("descriptions", [True, False])
def test_empty_disclosure_path_grants_only_root_descriptions_and_never_native_or_child_metadata(project, descriptions):
    data = project.parent / "data.odcs.json"
    contract = json.loads(data.read_bytes())
    root = contract["schema"][1]
    root.update(description="One independent output record.", dataGranularityDescription="One row per fixture record.",
                customProperties=[{"property": "native-storage", "value": "private-native-location"}])
    root["properties"][0]["description"] = "private-unlisted-field-meaning"
    save(data, contract)
    change(project, lambda row: [row[side].update(paths=[field_path("record_id")]) for side in ("source", "target")])
    policy = project.parent / "root-disclosure.json"
    save(policy, {"identifiers": ["urn:test:fixture:catalog", "urn:test:fixture:project", "urn:test:fixture:definitions",
                                  "urn:test:fixture:product", "urn:test:fixture:left", "urn:test:fixture:right"],
                  "descriptions": descriptions, "definitionFields": {"urn:test:fixture:right": [[]]}})
    result = assemble(project, disclosure_policy=policy)
    assert result.report["decision"] == "passed", result.report
    definition, = result.catalog["extensions"][DETAILS]["datasetDefinitions"].values()
    assert "properties" not in definition and "customProperties" not in definition and "id" not in definition
    if descriptions:
        assert definition["description"] == "One independent output record."
        assert definition["dataGranularityDescription"] == "One row per fixture record."
    else:
        assert "description" not in definition and "dataGranularityDescription" not in definition
    public = b"".join(result.artifacts.values())
    assert b"private-native-location" not in public and b"private-unlisted-field-meaning" not in public
    right = next(row for row in result.catalog["datasets"] if row["id"] == "urn:test:fixture:right")
    assert result.catalog["extensions"][DETAILS]["disclosedDefinitionPaths"] == {right["alias"]: [[]]}


def test_empty_identity_and_relationship_paths_remain_invalid(project):
    change(project, lambda row: row["source"].update(paths=[[]]))
    result = assemble(project, FixtureProfile())
    assert result.report["decision"] == "failed" and result.catalog is None
    value = json.loads(project.read_bytes())
    value["catalog"]["relationships"] = []
    value["catalog"]["identities"] = [{"dataset": "left", "kind": "key", "scope": "dataset_version",
                                       "meaning": "Invalid empty fixture identity path.",
                                       "fields": [{"path": [], "virtual": True, "physicalType": "integer"}]}]
    save(project, value)
    result = assemble(project, FixtureProfile())
    assert result.report["decision"] == "failed" and result.catalog is None


def test_offline_core_does_not_import_or_select_relationship_profiles(project):
    script = """
import importlib.abc
import sys
class NoProfiles(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'ddk.catalog_semantics':
            raise AssertionError('offline core imported relationship profile code')
sys.meta_path.insert(0, NoProfiles())
from ddk.core import check_project
report = check_project(sys.argv[1])
assert report['decision'] == 'incomplete'
assert 'ddk.catalog_semantics' not in sys.modules
assert any(check['group'] == 'catalog.relationships' and check['status'] == 'not_run' for check in report['checks'])
"""
    completed = subprocess.run([sys.executable, "-B", "-c", script, str(project)], capture_output=True, text=True,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False)
    assert completed.returncode == 0, completed.stderr
