"""Independent shared-definition, lock and impact scenarios."""

import shutil
from hashlib import sha256

import pytest

from ddk.core import load_project
from ddk.documents import validate_document
from ddk.impact import impact_projects
from ddk.locks import lock_project

from test_core import check, codes, commerce, edit, selected_development_identity

PROJECT = "project.ddk.json"
DATASET = "datasets/commerce.odcs.json"
READER = "components/read-orders.ddk.json"
DEFINITION = "definitions/amount-cents.json"


def _inherit_definition(path, reference, field=None):
    def change(document):
        prop = document["schema"][0]["properties"][0]
        for inline in ("businessName", "description"):  # inline values would win over the inherited ones under test
            prop.pop(inline, None)
        prop["authoritativeDefinitions"] = [{"type": "definition", "url": reference}]
        if field:
            prop.update(field)
    edit(path / DATASET, change)


def test_inheritance_merges_keys_and_respects_explicit_legacy_enum(commerce):
    definition = commerce / "definitions" / "base-code.json"
    definition.write_text('{"logicalType":"string","logicalTypeOptions":{"pattern":"^A","maxLength":20},"enum":[{"value":"A01"}]}')
    _inherit_definition(commerce, "../definitions/base-code.json", {
        "logicalTypeOptions": {"maxLength": 8},
        "customProperties": [{"property": "enum", "value": ["A02"]}],
    })
    inventory = load_project(commerce / PROJECT)
    orders = inventory.artifacts["orders"]
    original = orders.selected["properties"][0]
    resolved = orders.effective["properties"][0]
    assert original["logicalTypeOptions"] == {"maxLength": 8}
    assert resolved["logicalTypeOptions"] == {"pattern": "^A", "maxLength": 8}
    assert resolved["customProperties"] == [{"property": "enum", "value": ["A02"]}]
    assert "enum" not in resolved
    pattern = orders.provenance[("properties", 0, "logicalTypeOptions", "pattern")]
    maximum = orders.provenance[("properties", 0, "logicalTypeOptions", "maxLength")]
    assert pattern["source"]["path"].endswith("definitions/base-code.json")
    assert maximum["source"]["pointer"] == "/schema/0/properties/0/logicalTypeOptions/maxLength"
    assert maximum["overrides"]["path"].endswith("definitions/base-code.json")
    with pytest.raises(TypeError):
        orders.effective["properties"][0]["logicalTypeOptions"]["maxLength"] = 99


def test_named_fragment_matches_stable_id_before_name(commerce):
    target = commerce / "datasets" / "dictionary.json"
    target.write_text('''{
      "apiVersion":"v3.2.0", "kind":"DataContract", "id":"urn:test:dictionary",
      "version":"1.0.0", "status":"active", "schema":[
        {"id":"expected-object","name":"codes","properties":[
          {"id":"expected-field","name":"code","logicalType":"string","description":"From stable IDs"}]},
        {"id":"other","name":"expected-object","properties":[
          {"name":"expected-field","logicalType":"string","description":"Wrong fallback"}]}
      ]
    }''')
    _inherit_definition(commerce, "dictionary.json#schema/expected-object/properties/expected-field")
    inventory = load_project(commerce / PROJECT)
    field = inventory.artifacts["orders"].effective["properties"][0]
    assert field["description"] == "From stable IDs"
    assert any(entry.path == "datasets/dictionary.json" and
               entry.selection == "schema/expected-object/properties/expected-field" for entry in inventory.files)
    admitted, = [source for source in inventory.artifacts["orders"].definition_sources if source.path == target]
    assert admitted.pointer == "/schema/0/properties/0"
    assert admitted.sha256 == sha256(target.read_bytes()).hexdigest()
    target.write_text("changed after admission")
    assert admitted.sha256 != sha256(target.read_bytes()).hexdigest()
    assert field["description"] == "From stable IDs"


@pytest.mark.parametrize(("mode", "expected", "code"), [
    ("missing", "failed", "REF-DEFINITION-MISSING"),
    ("cycle", "failed", "REF-DEFINITION-CYCLE"),
    ("fragment", "failed", "REF-DEFINITION-FRAGMENT-MISSING"),
    ("remote", "incomplete", "REF-DEFINITION-REMOTE"),
])
def test_definition_failures_keep_dependent_comparison_not_run(commerce, mode, expected, code):
    if mode == "missing":
        reference = "../definitions/absent.json"
    elif mode == "cycle":
        reference = "../definitions/one.json"
        (commerce / "definitions" / "one.json").write_text(
            '{"authoritativeDefinitions":[{"type":"definition","url":"two.json"}]}'
        )
        (commerce / "definitions" / "two.json").write_text(
            '{"authoritativeDefinitions":[{"type":"definition","url":"one.json"}]}'
        )
    elif mode == "fragment":
        reference = "commerce.odcs.json#schema/absent/properties/nonexistent"
    else:
        reference = "https://example.invalid/definition.json"
    _inherit_definition(commerce, reference)
    report = check(commerce, expected)
    assert code in codes(report)
    assert any(item["subject"] == "order-preview-design/export/orders" and item["status"] == "not_run"
               for item in report["checks"])


def test_unused_quality_definition_warns_without_fake_execution(commerce):
    target = commerce / "definitions" / "unused.json"
    target.write_bytes((commerce / DEFINITION).read_bytes())
    edit(commerce / PROJECT, lambda p: p["artifacts"].update(
        unused={"kind": "definition", "path": "definitions/unused.json"}
    ))
    report = check(commerce, "passed")
    record = next(item for item in report["checks"] if item["subject"] == "unused" and item["group"] == "core.policies")
    assert record["status"] == "not_run" and not record["applicable"]
    assert "POLICY-DEFINITION-UNUSED" in codes(report)


def test_lock_pins_selected_objects_and_followed_bytes(commerce, tmp_path, selected_development_identity):
    lock_path = tmp_path / "locked.json"
    result, lock = lock_project(commerce / PROJECT, lock_path)
    assert result["decision"] == "passed"
    assert not validate_document(lock)
    selected = [item for item in lock["files"] if item["path"] == DATASET]
    assert {item["selection"] for item in selected} == {"orders", "customers", "daily_revenue"}
    assert len({item["sha256"] for item in selected}) == 1
    assert lock["standards"]["odcs"].startswith("3.2.0@448f7b9")
    assert lock["tools"]["ddk-local-definition-resolver"]["distributionSha256"]
    initial = lock_path.read_bytes()
    first = check(commerce, "passed", locked=True, lock=lock_path)
    second = check(commerce, "passed", locked=True, lock=lock_path)
    assert first["lock"]["verified"] and first == second
    file = commerce / DEFINITION
    file.write_bytes(file.read_bytes() + b" ")
    invalid = check(commerce, "failed", locked=True, lock=lock_path)
    assert "LOCK-DIGEST-MISMATCH" in codes(invalid)
    assert lock_path.read_bytes() == initial


def test_failed_lock_build_does_not_replace_prior_file(commerce, tmp_path):
    lock_path = tmp_path / "locked.json"
    lock_path.write_text("previous successful artifact")
    (commerce / READER).write_text("malformed")
    report, lock = lock_project(commerce / PROJECT, lock_path)
    assert report["decision"] == "failed" and lock is None
    assert lock_path.read_text() == "previous successful artifact"


def test_local_schema_reference_fragments_enter_lock(commerce):
    schema = commerce / "components" / "limits.json"
    schema.write_text('{"$defs":{"year":{"type":"integer","minimum":1900},"month":{"type":"integer","minimum":1}}}')
    def change(component):
        props = component["parameters"]["properties"]
        props["year"] = {"$ref": "limits.json#/$defs/year"}
        props["month"] = {"$ref": "limits.json#/$defs/month"}
    edit(commerce / READER, change)
    report = check(commerce, "incomplete")
    assert "CALL-PARAMETER-CONTAINMENT-UNKNOWN" in codes(report)
    # A literal-only selection can validate and lock both fragments.
    inventory = load_project(commerce / PROJECT)
    from ddk.core import check_inventory
    from ddk.locks import build_lock

    check_inventory(inventory, selection="order-preview-design")
    lock = build_lock(inventory)
    fragments = {item.get("selection") for item in lock["files"] if item["path"] == "components/limits.json"}
    assert fragments == {"/$defs/year", "/$defs/month"}


@pytest.fixture
def snapshots(commerce, tmp_path):
    candidate = tmp_path / "candidate"
    shutil.copytree(commerce, candidate)
    return commerce, candidate


def test_impact_reader_change_lists_three_consumers_and_direction(snapshots):
    base, candidate = snapshots
    def rename(document):
        document["version"] = "2.0.0"
        parameters = document["parameters"]
        parameters["properties"]["fiscal-year"] = parameters["properties"].pop("year")
        parameters["required"] = ["fiscal-year"]
    edit(candidate / READER, rename)
    report = impact_projects(base / PROJECT, candidate / PROJECT)
    assert not validate_document(report)
    assert report["decision"] == "failed"
    assert {"CALL-ARGUMENT-MISSING", "CALL-ARGUMENT-UNKNOWN", "IMPACT-BREAKING-INTERFACE"} <= codes(report)
    affected = {entry["consumer"]: entry["paths"] for entry in report["impact"]["affected"]}
    assert set(affected) == {"daily-revenue-design", "order-preview-design", "reviewed-revenue-design"}
    assert all(paths == [["read-orders", alias]] for alias, paths in affected.items())
    directions = next(iter(report["metadata"]["compatibilityDirections"].values()))
    assert directions == {"parameters/base-to-candidate": "failed", "output/rows/candidate-to-base": "passed"}


def test_impact_keeps_removed_edge_and_same_version_bytes(snapshots):
    base, candidate = snapshots
    source = candidate / READER
    source.write_bytes(source.read_bytes() + b" ")
    design = candidate / "designs" / "order-preview.ddk.json"
    def remove_step(value):
        value["version"] = "2.0.0"
        value["steps"].clear()
        value["sources"]["orders"] = {"dataset": "orders"}
        value["exports"]["orders"]["from"] = {"source": "orders"}
    edit(design, remove_step)
    report = impact_projects(base / PROJECT, candidate / PROJECT)
    assert report["decision"] == "failed"
    assert "IMPACT-VERSION-REUSE" in codes(report)
    assert {"consumer": "order-preview-design", "paths": [["read-orders", "order-preview-design"]]} in report["impact"]["affected"]
    assert any(item["identity"] == "urn:example:read-orders" and item["kinds"] == ["formatting"]
               for item in report["impact"]["changed"])


def test_effective_override_weakening_and_external_scope(snapshots):
    base, candidate = snapshots
    for folder, minimum in ((base, 5), (candidate, 2)):
        _inherit_definition(folder, "../definitions/code.json")
        (folder / "definitions" / "code.json").write_text(
            f'{{"logicalType":"string","logicalTypeOptions":{{"minLength":{minimum}}}}}'
        )
    report = impact_projects(base / PROJECT, candidate / PROJECT, non_weakening=True,
                             excluded_consumers=["outside-repository"])
    assert report["decision"] == "failed"
    assert "IMPACT-REQUIREMENT-WEAKENED" in codes(report)
    assert "outside-repository" in report["scope"]["excludedConsumers"]
    assert "changedDefinitionProvenance" in report["metadata"]


def test_impact_retains_native_definition_versions_verbatim(snapshots):
    base, candidate = snapshots
    edit(base / DATASET, lambda value: value.update(version="FY2025-Q4"))
    edit(candidate / DATASET, lambda value: value.update(version="FY2026-Q1"))
    report = impact_projects(base / PROJECT, candidate / PROJECT)
    assert not validate_document(report)
    assert report["decision"] == "passed"
    changes = report["impact"]["changed"]
    assert len(changes) == 3
    assert {(item["baseVersion"], item["candidateVersion"]) for item in changes} == {("FY2025-Q4", "FY2026-Q1")}


def test_native_impact_versions_do_not_relax_ddk_document_version(commerce):
    edit(commerce / READER, lambda value: value.update(version="FY2026-Q1"))
    assert "DOC-SCHEMA" in codes(check(commerce, "failed"))


def test_impact_detects_new_required_argument_and_weaker_output(snapshots):
    base, candidate = snapshots
    def change(component):
        component["version"] = "2.0.0"
        component["parameters"]["properties"]["region"] = {"type": "string"}
        component["parameters"]["required"].append("region")
    edit(candidate / READER, change)
    def nullable(contract):
        contract["version"] = "2.0.0"
        contract["schema"][0]["properties"][1]["required"] = False
    edit(candidate / DATASET, nullable)
    report = impact_projects(base / PROJECT, candidate / PROJECT)
    directions = report["metadata"]["compatibilityDirections"]["urn:example:read-orders/version/1.0.0/2.0.0"]
    assert directions == {"parameters/base-to-candidate": "failed", "output/rows/candidate-to-base": "failed"}
    assert report["decision"] == "failed"
    assert "IMPACT-BREAKING-INTERFACE" in codes(report)


def test_unsupported_definition_nonweakening_remains_unknown(snapshots):
    base, candidate = snapshots
    for folder, pattern in ((base, "^A"), (candidate, "^B")):
        _inherit_definition(folder, "../definitions/code.json")
        (folder / "definitions" / "code.json").write_text(
            f'{{"logicalType":"string","logicalTypeOptions":{{"pattern":"{pattern}"}}}}'
        )
    report = impact_projects(base / PROJECT, candidate / PROJECT, non_weakening=True)
    assert report["decision"] == "incomplete"
    assert any(check["group"] == "impact.non-weakening" and check["status"] == "unknown" and check["reason"]
               for check in report["checks"])
