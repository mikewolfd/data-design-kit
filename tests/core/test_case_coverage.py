"""Additional executable scenarios drawn from the conformance case registry."""

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ddk.core import load_project
from ddk.documents import REPOSITORY, read_json, schema_validator, validate_document
from ddk.locks import lock_project
from ddk.results import CORE_GROUPS, ReportBuilder

from test_core import check, codes, commerce, edit

DATASET = "datasets/commerce.odcs.json"
READER = "components/read-orders.ddk.json"
DAILY = "designs/daily-revenue.ddk.json"
PREVIEW = "designs/order-preview.ddk.json"
POLICY = "policies/commerce.ddk.json"


def _compare_view(commerce, mutate):
    def change(document):
        selected = deepcopy(document["schema"][0])
        selected["id"] = selected["name"] = "order-view"
        mutate(selected)
        document["schema"].append(selected)
    edit(commerce / DATASET, change)
    edit(commerce / "project.ddk.json", lambda p: p["artifacts"].update({
        "order-view": {"kind": "dataset", "path": DATASET, "object": "order-view"},
    }))
    edit(commerce / PREVIEW, lambda d: d["exports"]["orders"].update(dataset="order-view"))


def test_pinned_odcs_combined_operators_differ_from_release(commerce):
    edit(commerce / DATASET, lambda d: d["schema"][2]["quality"][0].update(mustBeLessOrEqualTo=0))
    doc = read_json(commerce / DATASET)
    release = read_json(REPOSITORY / "vendor/odcs/3.2.0-release/odcs-json-schema.json")
    assert not validate_document(doc.value, "dataset")
    assert not schema_validator(release.value).is_valid(doc.value)
    check(commerce, "passed")


def test_unknown_property_and_legacy_runtime_configuration_are_rejected(commerce):
    edit(commerce / READER, lambda component: component.update(retryMagic=True))
    report = check(commerce, "failed")
    assert "DOC-UNKNOWN-PROPERTY" in codes(report)
    def legacy(component):
        component.pop("retryMagic")
        component["implementation"] = {"adapter": "runtime", "endpoint": "https://example.invalid"}
    edit(commerce / READER, legacy)
    assert "DOC-SCHEMA" in codes(check(commerce, "failed"))


def test_named_ports_missing_and_unexpected(commerce):
    def change(design):
        ports = design["steps"]["summarize"]["inputs"]
        ports["unexpected"] = ports.pop("customers")
    edit(commerce / DAILY, change)
    report = check(commerce, "failed")
    assert {"CALL-INPUT-MISSING", "CALL-INPUT-UNKNOWN"} <= codes(report)


def test_symbolic_bounds_are_checked_at_a_call(commerce):
    edit(commerce / READER, lambda c: c["parameters"]["properties"]["year"].update(minimum=2000))
    edit(commerce / DAILY, lambda d: d["parameters"]["properties"]["year"].update(minimum=1999, maximum=2026))
    report = check(commerce, "failed")
    assert "CALL-PARAMETER-INCOMPATIBLE" in codes(report)


def test_nullable_consumer_column_still_has_to_be_present(commerce):
    edit(commerce / DATASET, lambda d: d["schema"][0]["properties"].pop(1))
    def target(view):
        view["properties"].insert(1, {"name": "customer_id", "logicalType": "string", "required": False})
    _compare_view(commerce, target)
    report = check(commerce, "failed")
    assert "DATA-FIELD-MISSING" in codes(report)


def test_declared_nullability_and_enum_values_outweigh_enum_labels(commerce):
    edit(commerce / DATASET, lambda d: d["schema"][0]["properties"][1].update(
        required=False, enum=[{"value": "ID-1", "label": "Customer"}]
    ))
    _compare_view(commerce, lambda view: view["properties"][1].update(
        required=True, enum=[{"value": "ID-2", "label": "Customer"}]
    ))
    report = check(commerce, "failed")
    assert {"DATA-NULLABILITY", "DATA-ENUM-INCOMPATIBLE"} <= codes(report)


@pytest.mark.parametrize(("field", "physical_type"), [(3, "decimal(18,4)"), (2, "TIMESTAMPTZ")])
def test_required_physical_type_is_unknown_with_declared_evidence(commerce, field, physical_type):
    _compare_view(commerce, lambda view: view["properties"][field].update(physicalType=physical_type))
    report = check(commerce, "incomplete")
    target = next(check for check in report["checks"] if check["subject"] == "order-preview-design/export/orders")
    assert target["status"] == "unknown" and target["reason"] and target["required"] and target["applicable"]
    assert target["evidence"] == "declared"
    assert "DATA-MAPPING-UNKNOWN" in codes(report)


def test_uniqueness_stays_a_declared_assumption(commerce):
    edit(commerce / DATASET, lambda d: d["schema"][0]["properties"][1].update(unique=True))
    report = check(commerce, "passed")
    fields = report["metadata"]["datasetMappings"]["order-preview-design/export/orders"]["fields"]
    customer, = (field for field in fields if field["field"] == "customer_id")
    assert customer["assumptions"] == [
        {"side": "available", "claim": "unique", "evidence": "declared"},
        {"side": "required", "claim": "unique", "evidence": "declared"},
    ]


def test_two_exports_get_separate_results_in_one_design(commerce):
    _compare_view(commerce, lambda view: view["properties"].append({"name": "extra_expected", "logicalType": "string"}))
    def change(design):
        design["sources"]["raw"] = {"dataset": "orders"}
        design["exports"]["direct"] = {"from": {"source": "raw"}, "dataset": "orders"}
    edit(commerce / PREVIEW, change)
    report = check(commerce, "failed")
    statuses = {item["subject"]: item["status"] for item in report["checks"] if item["group"] == "core.datasets"}
    assert statuses["order-preview-design/export/orders"] == "failed"
    assert statuses["order-preview-design/export/direct"] == "passed"
    assert "DATA-EXPORT-MISMATCH" in codes(report)


def test_unknown_rule_and_explicit_vocabulary_policy(commerce):
    edit(commerce / POLICY, lambda p: p["rules"].append(
        {"id": "external", "check": "urn:test:unavailable-policy", "configuration": {}}
    ))
    report = check(commerce, "incomplete")
    assert "POLICY-RULE-UNKNOWN" in codes(report)
    edit(commerce / POLICY, lambda p: p["rules"][-2].update(allowed=["active"]))
    report = check(commerce, "failed")
    assert "POLICY-VOCABULARY" in codes(report)


def test_explicit_quality_dependency_must_reference_a_real_field(commerce):
    check(commerce, "passed")
    edit(commerce / DATASET, lambda d: d["schema"][2]["quality"][0]["customProperties"][0].update(
        value=["nonexistent"]
    ))
    assert "POLICY-QUALITY-FIELD-MISSING" in codes(check(commerce, "failed"))


def test_invalid_prerequisite_blocks_dependents_and_keeps_independent_checks(commerce):
    (commerce / READER).write_text('{"invalid":')
    report = check(commerce, "failed")
    assert "DOC-PREREQUISITE-INVALID" in codes(report)
    assert any(record["status"] == "not_run" and record["subject"] == "order-preview-design/step/read"
               for record in report["checks"])
    assert any(record["status"] == "passed" and record["subject"] == "commerce-policy/rule/revenue-grain"
               for record in report["checks"])


def test_real_path_documents_parsed_once_per_run(commerce, monkeypatch):
    from ddk import inventory

    read = inventory.read_json
    counts = Counter()
    def measure(path, **kwargs):
        counts[Path(path).resolve()] += 1
        return read(path, **kwargs)
    monkeypatch.setattr(inventory, "read_json", measure)
    check(commerce, "passed")
    assert counts[commerce / DATASET] == counts[commerce / "definitions/amount-cents.json"] == 1
    assert all(count == 1 for count in counts.values())


def test_development_tool_identity_distinguishes_equal_version_strings(commerce, monkeypatch):
    monkeypatch.setenv("DDK_SOURCE_COMMIT", "1" * 40)
    monkeypatch.setenv("DDK_DISTRIBUTION_SHA256", "a" * 64)
    _, first = lock_project(commerce / "project.ddk.json")
    monkeypatch.setenv("DDK_SOURCE_COMMIT", "2" * 40)
    monkeypatch.setenv("DDK_DISTRIBUTION_SHA256", "b" * 64)
    _, second = lock_project(commerce / "project.ddk.json")
    assert first["tools"]["ddk"]["version"] == second["tools"]["ddk"]["version"]
    assert first["tools"]["ddk"]["commit"] != second["tools"]["ddk"]["commit"]
    assert first["tools"]["ddk"]["distributionSha256"] != second["tools"]["ddk"]["distributionSha256"]
    report = check(commerce, "failed", locked=True, lock=first)
    assert "LOCK-INPUT-MISMATCH" in codes(report)


def test_optional_uri_extension_and_unsupported_ddk_version(commerce):
    edit(commerce / READER, lambda c: c.update(extensions={"urn:test:annotation": {"mode": "optional"}}))
    check(commerce, "passed")
    inventory = load_project(commerce / "project.ddk.json")
    assert inventory.artifacts["read-orders"].value["extensions"] == {"urn:test:annotation": {"mode": "optional"}}
    edit(commerce / READER, lambda c: c.update(specVersion="7.0"))
    assert "DOC-VERSION-UNSUPPORTED" in codes(check(commerce, "failed"))


def test_catalog_recipe_with_explicit_result_grain_loads(commerce):
    def change(project):
        recipe = project["catalog"]["recipes"][0]
        recipe.pop("resultDataset")
        recipe["resultGrain"] = "One result row per day and region."
    edit(commerce / "project.ddk.json", change)
    assert check(commerce, "passed")["coverage"]["completedProfiles"] == ["core"]


def test_selected_import_leaves_other_consumer_namespace_uncovered(commerce):
    for name in ("included", "excluded"):
        project = {
            "specVersion": "0.1", "kind": "project", "version": "1.0.0", "id": f"urn:test:{name}",
            "requiredChecks": list(CORE_GROUPS), "artifacts": {
                "orders": {"kind": "dataset", "path": DATASET, "object": "orders"},
            },
        }
        (commerce / f"{name}.json").write_text(json.dumps(project))
    edit(commerce / "project.ddk.json", lambda p: p["imports"].update(
        included={"path": "included.json"}, excluded={"path": "excluded.json"},
    ))
    report = check(commerce, "passed", selection="included")
    assert set(report["scope"]["artifacts"]) == {"included/orders", "amount-cents"}
    assert "excluded/orders" in report["scope"]["excludedConsumers"]


def test_two_step_cycle_and_nonexistent_output_are_independently_reported(commerce):
    def change(design):
        design["steps"]["read"]["inputs"]["cycle"] = {"step": "summarize", "output": "rows"}
        design["exports"]["missing"] = {
            "from": {"step": "summarize", "output": "does-not-exist"}, "dataset": "daily-revenue",
        }
    edit(commerce / DAILY, change)
    report = check(commerce, "failed")
    assert {"GRAPH-CYCLE", "REF-OUTPUT-MISSING"} <= codes(report)
    assert report["metadata"]["stepOrder"]["daily-revenue-design"] == []


def test_result_keeps_evidence_levels_and_missing_optional_capability(commerce):
    builder = ReportBuilder("urn:test:report", ["core.documents", "plan.output", "test.fixtures"])
    builder.add("DDK-SYNTAX-001", "core.documents", "document", "passed")
    builder.add("DDK-GRAPH-003", "plan.output", "declared export", "passed", evidence="inferred")
    snapshot = commerce / "data" / "orders.csv"
    builder.add("DDK-ADAPTER-007", "test.fixtures", "fixture evidence", "passed", evidence="executed",
                evidence_records=[{"kind": "dataset-snapshot", "path": str(snapshot),
                                   "sha256": sha256(snapshot.read_bytes()).hexdigest()}])
    builder.missing_capabilities.add("test.portability")
    builder.add("DDK-ADAPTER-001", "test.portability", "other engine", "not_run", required=False,
                reason="No second engine was selected.")
    report = builder.build()
    assert not validate_document(report)
    assert report["decision"] == "passed"
    assert {item["evidence"] for item in report["checks"]} == {"declared", "inferred", "executed"}
    assert report["coverage"]["missingCapabilities"] == ["test.portability"]
    assert any(item.get("evidenceRecords", [{}])[0].get("path") == str(snapshot) for item in report["checks"])


def test_cli_uses_decision_exit_codes_and_one_json_object(commerce, capsys):
    from ddk.cli import main

    project = str(commerce / "project.ddk.json")
    def invoke(arguments, expected_exit, decision):
        assert main([*arguments, "--format", "json"]) == expected_exit
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert not validate_document(report)
        assert report["decision"] == decision
        assert captured.err == ""
        return report
    invoke(["check", project], 0, "passed")
    invoke(["check", project, "--require", "test.portability"], 2, "incomplete")
    edit(commerce / PREVIEW, lambda d: d["steps"]["read"]["arguments"].pop("year"))
    assert "CALL-ARGUMENT-MISSING" in codes(invoke(["check", project], 1, "failed"))
    (commerce / READER).unlink()
    invoke(["check", project], 3, "error")
    invoke(["check"], 64, "error")


def test_cli_does_not_import_a_reader_entrypoint(commerce, monkeypatch, capsys):
    from ddk.cli import main

    marker = commerce / "imported"
    module = commerce / "ddk_reader_trap.py"
    module.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    monkeypatch.syspath_prepend(str(commerce))
    edit(commerce / READER, lambda c: c.update(implementation={
        "format": "python", "entrypoint": "ddk_reader_trap:read",
        "semantics": {"id": "urn:test:python-reader", "revision": "1"},
    }))
    assert main(["check", str(commerce / "project.ddk.json"), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "passed"
    assert not marker.exists()
