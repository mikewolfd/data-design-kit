"""Independent regressions for strict, implementation-free checking."""

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import shutil
import socket

import pytest

from ddk.core import check_project, load_project
from ddk.documents import DocumentError, ResourceLimit, json_dumps, parse_json, validate_document
from ddk.interfaces import schema_containment
from ddk.results import CORE_GROUPS, ReportBuilder, diagnostic, exit_code

COMMERCE = Path(__file__).resolve().parents[2] / "examples" / "commerce"


@pytest.fixture
def commerce(tmp_path):
    target = tmp_path / "commerce"
    shutil.copytree(COMMERCE, target)
    return target


@pytest.fixture
def selected_development_identity(monkeypatch):
    """Select an independent installed identity for tests of other lock fields."""
    from ddk import locks
    from ddk.results import VERSION

    identity = {"version": VERSION, "commit": "1" * 40, "distributionSha256": "a" * 64}
    monkeypatch.setattr(locks, "distribution_identity", lambda: dict(identity))
    return identity


def edit(path, change):
    value = json.loads(path.read_bytes())
    change(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def codes(report):
    return {item["code"] for check in report["checks"] for item in check["diagnostics"]}


def check(folder, expected, **kwargs):
    report = check_project(folder / "project.ddk.json", **kwargs)
    assert not validate_document(report, "report")
    assert report["decision"] == expected
    assert exit_code(report) == {"passed": 0, "failed": 1, "incomplete": 2, "error": 3}[expected]
    return report


@pytest.mark.parametrize(("source", "code", "pointer"), [
    (b'{"outer":{"a/b~c":1,"a/b~c":2}}', "DOC-DUPLICATE-KEY", "/outer/a~1b~0c"),
    (b'{"number":NaN}', "DOC-NONFINITE-NUMBER", ""),
    (b'{"number":-Infinity}', "DOC-NONFINITE-NUMBER", ""),
    (b'{"bad":"\xff"}', "DOC-UTF8", ""),
    (br'{"bad":"\ud800"}', "DOC-UNICODE-SURROGATE", "/bad"),
])
@pytest.mark.parametrize("preserve_integral_decimals", [False, True])
def test_strict_json(source, code, pointer, preserve_integral_decimals):
    with pytest.raises(DocumentError) as issue:
        parse_json(source, preserve_integral_decimals=preserve_integral_decimals)
    assert (issue.value.code, issue.value.pointer) == (code, pointer)


def test_exact_decimal_value_and_bytes():
    source = b'{"value":0.1000000000000000000000000000000000001}'
    assert parse_json(source)["value"] == Decimal("0.1000000000000000000000000000000000001")
    assert parse_json(json_dumps(parse_json(source)).encode()) == parse_json(source)


def test_native_number_mode_preserves_integer_tokens_without_changing_core_normalization():
    raw = b'{"integer":1,"decimal":1.0,"exponent":1e0,"negativeZero":-0.0}'
    ordinary = parse_json(raw)
    native = parse_json(raw, preserve_integral_decimals=True)
    assert all(type(value) is int for value in ordinary.values())
    assert type(native["integer"]) is int
    assert all(type(native[key]) is Decimal for key in ("decimal", "exponent", "negativeZero"))
    assert native["negativeZero"].is_signed()


@pytest.mark.parametrize("preserve_integral_decimals", [False, True])
@pytest.mark.parametrize("number", [b"1e4000", b"1e10001"])
def test_native_number_mode_keeps_numeric_capacity_limits(number, preserve_integral_decimals):
    with pytest.raises(ResourceLimit):
        parse_json(number, preserve_integral_decimals=preserve_integral_decimals)


def test_offline_core_does_not_open_implementation(commerce, monkeypatch):
    (commerce / "transforms" / "revenue.sql").unlink()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("core tried the network"))
    report = check(commerce, "passed")
    assert report["coverage"]["completedProfiles"] == ["core"]
    assert {record["evidence"] for record in report["checks"]} == {"declared"}
    assert set(report["metadata"]["stepOrder"]) == {
        "daily-revenue-design", "order-preview-design", "reviewed-revenue-design",
    }
    for mapping in report["metadata"]["datasetMappings"].values():
        assert "fields" in mapping and "allowAdditionalFields" in mapping


def test_unknown_required_profile_has_independent_instances(commerce):
    report = check(commerce, "incomplete", required_groups=["plan.output"])
    assert report["coverage"]["missingCapabilities"] == ["plan.output"]
    inferred = [item for item in report["checks"] if item["group"] == "plan.output"]
    assert len(inferred) == 3
    assert all(item["status"] == "not_run" and item["reason"] and item["evidence"] == "inferred" for item in inferred)
    assert "ADAPTER-IMPLEMENTATION-MISSING" in codes(report)
    assert "ADAPTER-CAPABILITY-MISSING" in codes(report)


def test_selection_keeps_prerequisites_and_excludes_unreadable_sibling(commerce):
    (commerce / "designs" / "reviewed-revenue.ddk.json").unlink()
    report = check(commerce, "passed", selection="daily-revenue-design")
    assert "reviewed-revenue-design" in report["scope"]["excludedConsumers"]
    assert {"daily-revenue-design", "summarize", "read-orders", "orders", "amount-cents"} <= set(report["scope"]["artifacts"])
    assert report["metadata"]["selection"] == ["daily-revenue-design"]


def test_import_scopes_local_and_root_relative_aliases(commerce):
    shared = commerce / "shared"
    shared.mkdir()
    source = json.loads((commerce / "components" / "read-orders.ddk.json").read_bytes())
    source["id"] = "urn:test:shared-reader"
    source["outputs"]["rows"]["dataset"] = "orders"
    (shared / "reader.json").write_text(json.dumps(source))
    project = {
        "specVersion": "0.1", "kind": "project", "id": "urn:test:shared", "version": "1.0.0",
        "requiredChecks": list(CORE_GROUPS), "artifacts": {
            "reader": {"kind": "component", "path": "reader.json"},
            "orders": {"kind": "dataset", "path": "../datasets/commerce.odcs.json", "object": "customers"},
        },
    }
    (shared / "project.json").write_text(json.dumps(project))
    edit(commerce / "project.ddk.json", lambda p: p["imports"].update({"shared": {"path": "shared/project.json"}}))
    inventory = load_project(commerce / "project.ddk.json")
    assert inventory.resolve("orders", "shared").selection == "customers"
    assert inventory.resolve("/orders", "shared").selection == "orders"
    assert "shared/orders" in inventory.dependencies["shared/reader"]
    check(commerce, "passed")


def test_import_cycle(commerce):
    edit(commerce / "project.ddk.json", lambda p: p["imports"].update({"again": {"path": "./project.ddk.json"}}))
    report = check(commerce, "failed")
    assert "REF-IMPORT-CYCLE" in codes(report)


def test_outside_symlink_rejected_before_read(commerce, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("deliberately invalid JSON")
    linked = commerce / "components" / "read-orders.ddk.json"
    linked.unlink()
    linked.symlink_to(outside)
    report = check(commerce, "failed")
    assert "REF-PATH-OUTSIDE-ROOT" in codes(report)
    assert "DOC-JSON" not in codes(report)
    report = check(commerce, "failed", permitted_roots=[tmp_path])
    assert "DOC-JSON" in codes(report)


def test_conflicting_identity_is_detected(commerce):
    source = commerce / "components" / "read-orders.ddk.json"
    second = commerce / "components" / "shadow.json"
    second.write_bytes(source.read_bytes() + b" ")
    edit(commerce / "project.ddk.json", lambda p: p["artifacts"].update({
        "shadow": {"kind": "component", "path": "components/shadow.json"},
    }))
    assert "REF-IDENTITY-CONFLICT" in codes(check(commerce, "failed"))


def test_dataset_selection_checks_id_before_name(commerce):
    dataset = commerce / "datasets" / "commerce.odcs.json"
    edit(dataset, lambda d: d["schema"][1].update(name="orders"))
    assert load_project(commerce / "project.ddk.json").artifacts["orders"].selection == "orders"
    edit(dataset, lambda d: d["schema"][0].update(id="orders-other-id"))
    assert "REF-DATASET-AMBIGUOUS" in codes(check(commerce, "failed"))


def test_defaults_are_not_arguments_and_independent_exports_continue(commerce):
    reader = commerce / "components" / "read-orders.ddk.json"
    edit(reader, lambda c: c["parameters"]["properties"]["year"].update(default=2026))
    design = commerce / "designs" / "order-preview.ddk.json"
    edit(design, lambda d: d["steps"]["read"]["arguments"].pop("year"))
    report = check(commerce, "failed")
    assert "CALL-ARGUMENT-MISSING" in codes(report)
    assert any(item["group"] == "core.datasets" and item["subject"] == "daily-revenue-design/export/revenue"
               and item["status"] == "passed" for item in report["checks"])


def test_literal_objects_keep_reserved_looking_keys_as_data(commerce):
    reader = commerce / "components" / "read-orders.ddk.json"
    edit(reader, lambda c: c["parameters"]["properties"].update(
        note={"type": "object", "properties": {"parameter": {"type": "null"}}, "required": ["parameter"]}
    ))
    edit(commerce / "designs" / "order-preview.ddk.json", lambda d: d["steps"]["read"]["arguments"].update(
        note={"literal": {"parameter": None}}
    ))
    check(commerce, "passed")


@pytest.mark.parametrize(("source", "target", "expected"), [
    ('{"type":"integer","minimum":1}', '{"type":"number","exclusiveMinimum":0.9}', "passed"),
    ('{"type":"integer","minimum":1}', '{"type":"number","exclusiveMinimum":1}', "failed"),
    ('{"type":"integer","exclusiveMinimum":0,"maximum":2}', '{"enum":[1,2]}', "passed"),
    ('{"type":"number","minimum":1,"maximum":1}', '{"type":"integer"}', "passed"),
    ('{"const":0.1000000000000000000000000000000000001}', '{"minimum":0.1000000000000000000000000000000000002}', "failed"),
    ('{"const":true}', '{"const":1}', "failed"),
    ('{"type":"string","maxLength":0}', '{"const":""}', "passed"),
    ('{"type":"array","minItems":3}', '{"type":"array","minItems":4}', "failed"),
    ('{"type":"string","pattern":"^X"}', '{"type":"string","minLength":1}', "unknown"),
])
def test_symbolic_containment(source, target, expected):
    assert schema_containment(parse_json(source.encode()), parse_json(target.encode())) == expected


def test_literal_condition_and_symbolic_whole_object_are_distinct(commerce):
    reader = commerce / "components" / "read-orders.ddk.json"
    edit(reader, lambda c: c["parameters"].update(
        **{"if": {"properties": {"year": {"const": 2026}}}, "then": {"properties": {"year": {"minimum": 2026}}}}
    ))
    report = check(commerce, "incomplete")
    assert "CALL-CORRELATION-UNKNOWN" in codes(report)
    assert any(item["requirement"] == "DDK-CALL-004" and item["subject"] == "order-preview-design/step/read"
               and item["status"] == "passed" for item in report["checks"])


def test_missing_producer_blocks_dependent_export_only(commerce):
    design = commerce / "designs" / "order-preview.ddk.json"
    def change(document):
        document["exports"]["orders"]["from"]["step"] = "missing"
        document["steps"]["read"]["arguments"]["year"] = {"literal": True}
    edit(design, change)
    report = check(commerce, "failed")
    assert {"REF-STEP-MISSING", "CALL-TYPE-MISMATCH"} <= codes(report)
    assert any(item["group"] == "core.datasets" and item["subject"] == "order-preview-design/export/orders"
               and item["status"] == "not_run" for item in report["checks"])


def test_graph_cycle_preserves_independent_work(commerce):
    design = commerce / "designs" / "daily-revenue.ddk.json"
    edit(design, lambda d: d["steps"]["summarize"]["inputs"].update({"orders": {"step": "summarize", "output": "revenue"}}))
    report = check(commerce, "failed")
    assert "GRAPH-CYCLE" in codes(report)
    assert "summarize" not in report["metadata"]["stepOrder"]["daily-revenue-design"]
    assert any(item["subject"] == "order-preview-design/export/orders" and item["status"] == "passed" for item in report["checks"])


def test_dataset_aggregates_independent_failure_and_unknown(commerce):
    def change(document):
        duplicate = deepcopy(document["schema"][0])
        duplicate["id"] = duplicate["name"] = "order_view"
        duplicate["properties"][0]["logicalType"] = "boolean"
        duplicate["properties"][1]["physicalType"] = "decimal(10,3)"
        document["schema"].append(duplicate)
    edit(commerce / "datasets" / "commerce.odcs.json", change)
    edit(commerce / "project.ddk.json", lambda p: p["artifacts"].update({
        "order-view": {"kind": "dataset", "path": "datasets/commerce.odcs.json", "object": "order_view"},
    }))
    edit(commerce / "designs" / "order-preview.ddk.json", lambda d: d["exports"]["orders"].update(dataset="order-view"))
    report = check(commerce, "failed")
    assert {"DATA-FIELD-INCOMPATIBLE", "DATA-MAPPING-UNKNOWN", "DATA-EXPORT-MISMATCH"} <= codes(report)


def test_row_identity_duplicate_and_unknown_sql_dependencies(commerce):
    def change(document):
        document["schema"][2]["customProperties"][0]["value"] = ["region", "region", "missing"]
        document["schema"][2]["quality"][0].pop("customProperties")
    edit(commerce / "datasets" / "commerce.odcs.json", change)
    report = check(commerce, "failed")
    assert {"POLICY-ROW-IDENTITY", "POLICY-QUALITY-DEPENDENCIES-UNKNOWN"} <= codes(report)
    assert any(item["status"] == "unknown" and item["group"] == "core.policies" for item in report["checks"])


def test_resource_limit_retains_prior_checks(commerce):
    report = check(commerce, "error", limits={"maxArtifacts": 2})
    assert report["limits"]["maxArtifacts"] == 2
    assert "EXEC-RESOURCE-LIMIT" in codes(report)
    assert any(item["status"] == "passed" for item in report["checks"])


@pytest.mark.parametrize(("status", "required", "applicable", "operational", "expected"), [
    ("failed", True, True, False, "failed"),
    ("failed", False, True, False, "passed"),
    ("unknown", True, True, False, "incomplete"),
    ("not_run", True, True, False, "incomplete"),
    ("not_run", True, False, False, "passed"),
    ("failed", True, True, True, "error"),
])
def test_reducer(status, required, applicable, operational, expected):
    builder = ReportBuilder("urn:test:report")
    builder.add("DDK-RESULT-002", "core.calls", "test", status, required=required, applicable=applicable,
                reason="Missing evidence" if status in {"unknown", "not_run"} else None)
    if operational:
        builder.error(diagnostic("DOC-UNREADABLE", "A file could not be read."))
    assert builder.build()["decision"] == expected
