"""Independent based-update examples through the actual DDK/DocSpec wrapper."""

from copy import deepcopy
from hashlib import sha256
from itertools import count
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ddk.adapters.docspec import DocSpecAdapter, _managed_context, native_version
from ddk.adapters.native import NativeTools, write_json


LIMITS = {
    "compute_threads": 2, "memory_bytes": 256 << 20, "scratch_bytes": 64 << 20,
    "batch_rows": 2, "max_batch_bytes": 8 << 20, "max_metadata_bytes": 4 << 20,
}
BASE = [
    {"id": "A", "agency": "X", "amount_cents": 100},
    {"id": "B", "agency": "X", "amount_cents": 200},
    {"id": "D", "agency": "Y", "amount_cents": 50},
]
EXPECTED = [
    {"id": "A", "agency": "X", "amount_cents": 120},
    {"id": "C", "agency": "Y", "amount_cents": 0},
    {"id": "D", "agency": "Y", "amount_cents": 50},
]


def test_update_context_preserves_exact_native_operation_scope(tmp_path):
    workspace = tmp_path.resolve()
    context = _managed_context(workspace, {
        "action": "prepare_update", "update": {"dataset": "amounts", "operation": "correction"},
    })
    assert context == {
        "runtime": "docspec", "workspace": str(workspace),
        "dataset": "amounts", "operationId": "correction",
    }
    with pytest.raises(ValueError, match="exact dataset"):
        _managed_context(workspace, {"action": "prepare_update", "update": {"operation": "correction"}})
    with pytest.raises(ValueError, match="Unsupported"):
        _managed_context(workspace, {"action": "prepare_refresh", "refresh": {}})


@pytest.fixture
def integration(tmp_path):
    binary, native_python = os.environ.get("DDK_DOCSPEC_BINARY"), os.environ.get("DDK_NATIVE_PYTHON")
    if not binary or not native_python:
        pytest.skip("Set DDK_DOCSPEC_BINARY and DDK_NATIVE_PYTHON to the pinned local environments")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    runtime = DocSpecAdapter(binary, LIMITS, evidence_dir=tmp_path / "runtime")
    tools = NativeTools(native_python, output=tmp_path / "quality")
    workspace = tmp_path / "host"
    workspace.mkdir()
    limits = write_json(tmp_path / "limits.json", LIMITS)
    request_sequence = count()

    def native(command, request=None, *arguments):
        path = write_json(tmp_path / f"{command}-{next(request_sequence)}-spec.json", request) if request is not None else None
        args = [str(runtime.executable), "--workspace", str(workspace), "--limits", limits["path"], command]
        args.extend(["--spec", path["path"]] if path else arguments)
        return json.loads(subprocess.check_output(args))

    def data(name, values, schema):
        path = tmp_path / (name + ".parquet")
        pq.write_table(pa.Table.from_pylist(values, schema=schema), path)
        digest = json.loads(subprocess.check_output([
            str(runtime.executable), "hash", "--input", str(path),
        ]))["digest"]
        return {"path": str(path), "digest": digest}

    def build(dataset, values, schema, *, managed=False):
        source = data(dataset + "-base", values, schema)
        spec = {"dataset": dataset, "operation": "initial", "definition": "source-v1",
                "input": source["path"], "expected_digest": source["digest"], "sql": "SELECT * FROM input"}
        if managed:
            fields = [(field.name, "integer" if pa.types.is_integer(field.type) else "string") for field in schema]
            initial_rules = rules_for(dataset, fields)
            initial_policy = policy(initial_rules, "initial-quality", None)
            prepared = runtime.managed(workspace, {"action": "prepare", "build": spec, "policy": initial_policy})
            assert prepared["status"] == "succeeded", prepared
            candidate = prepared["result"]["candidate"]
            accepted = runtime.managed(workspace, {
                "action": "accept", "dataset": dataset, "operation": "initial",
                "evidence": evidence(initial_rules, initial_policy, candidate),
            })
            assert accepted["status"] == "succeeded", accepted
            selected = runtime.managed(workspace, {
                "action": "select", "dataset": dataset, "operation": "initial", "policy_id": initial_policy["id"],
            })
            assert selected["status"] == "succeeded", selected
            return candidate, source
        release = native("run", spec)
        return {"dataset": dataset, "version": release["id"], "manifest": release["manifest"]}, source

    def policy(rules, name, base):
        planned = tools.invoke("quality-plan", rules)
        assert planned["status"] == "not_run", planned
        evaluator = planned["evaluator"]
        return {
            "id": name, "rules_sha256": planned["rules"]["sha256"],
            "evaluator": {"id": evaluator["id"], "version": evaluator["version"],
                          "distribution_sha256": evaluator["distributionSha256"]},
            "semantics": planned["mappingSemantics"], "required_checks": planned["requiredCheckIds"],
            "expected_epoch": 0, "expected_selection": base,
        }

    def evidence(rules, admitted, candidate):
        result = tools.invoke("quality", {**rules, "target": {
            "kind": "native", "nativeVersion": candidate,
            "read": {"workspace": str(workspace), "executable": str(runtime.executable),
                     "executableSha256": runtime.tool["distributionSha256"], "limits": LIMITS},
        }})
        assert result["status"] == "passed", result
        return {
            "policy_id": admitted["id"], "candidate": candidate, "rules": result["rules"],
            "evaluator": admitted["evaluator"], "semantics": admitted["semantics"],
            "checks": [{key: check[key] for key in ("id", "status")} for check in result["checks"]],
            "native_report": result["receipt"],
            "native_read": {key: result["nativeRead"][key] for key in ("path", "sha256")},
        }

    def read(version):
        result = runtime.read_version(workspace, native_version(workspace, version))
        assert result["status"] == "succeeded", result
        return pa.ipc.open_stream(result["ipc"]).read_all().to_pylist()

    return runtime, tools, workspace, native, data, build, policy, evidence, read, pa


def rules_for(dataset, fields, *, quality=()):
    return {"document": {
        "apiVersion": "v3.2.0", "kind": "DataContract", "id": "urn:ddk:test:" + dataset,
        "name": dataset, "version": "1.0.0", "status": "draft",
        "schema": [{"name": dataset, "physicalType": "table", "logicalType": "object",
                    "properties": [{"name": name, "logicalType": kind} for name, kind in fields],
                    "quality": list(quality)}],
    }}


def test_correction_delete_quality_recovery_and_historical_replay(integration, tmp_path):
    runtime, _, workspace, native, data, build, policy, evidence, read, pa = integration
    schema = pa.schema([("id", pa.string()), ("agency", pa.string()), ("amount_cents", pa.int64())])
    base, original = build("amounts", BASE, schema, managed=True)
    rules = rules_for("amounts", [("id", "string"), ("agency", "string"), ("amount_cents", "integer")],
                      quality=[{"type": "sql", "query": "SELECT COUNT(*) FROM amounts WHERE amount_cents < 0", "mustBe": 0}])
    first = policy(rules, "quality-v1", base)
    replacements = data("correction", EXPECTED[:2], schema)
    deletions = data("deletions", [{"id": "B"}], pa.schema([("id", pa.string())]))
    operation = {"dataset": "amounts", "operation": "correction"}
    update = {**operation, "base": "initial", "definition": "source-v1", "keys": ["id"],
              "replacements": replacements, "deletions": deletions}
    prepare = {"action": "prepare_update", "update": update, "policy": first}
    request = write_json(tmp_path / "caller-request.json", prepare)

    # A real DDK caller exits after native processing, before quality or selection.
    caller = tmp_path / "caller.py"
    caller.write_text(
        "import json, os, sys\n"
        "from ddk.adapters.docspec import DocSpecAdapter\n"
        "runtime = DocSpecAdapter(sys.argv[1], json.loads(sys.argv[4]), evidence_dir=sys.argv[5])\n"
        "result = runtime.managed(sys.argv[2], json.load(open(sys.argv[3])))\n"
        "os._exit(23 if result['status'] == 'succeeded' else 24)\n"
    )
    child = subprocess.run([sys.executable, str(caller), str(runtime.executable), str(workspace),
                            request["path"], json.dumps(LIMITS), str(tmp_path / "lost-caller")], check=False)
    assert child.returncode == 23
    prepared = runtime.managed(workspace, {**operation, "action": "inspect"})
    assert prepared["status"] == "succeeded", prepared
    candidate = prepared["result"]["candidate"]
    computation = prepared["result"]["computation_identity"]
    assert prepared["operation"]["selection"] == "pending"
    assert sorted(read(candidate), key=lambda row: row["id"]) == EXPECTED
    assert sorted(read(base), key=lambda row: row["id"]) == BASE
    original_digest = sha256(Path(original["path"]).read_bytes()).hexdigest()

    changed = deepcopy(prepare)
    changed["update"]["replacements"] = data("wrong-correction", [{**EXPECTED[0], "amount_cents": 121}], schema)
    refused = runtime.managed(workspace, changed)
    assert refused["error"]["code"] == "operation_conflict"
    missing = runtime.managed(workspace, {**operation, "action": "select", "policy_id": first["id"]})
    assert missing["error"]["code"] == "qualification_required"

    valid = evidence(rules, first, candidate)
    for mutation, expected_code in (
        (lambda value: value["checks"].pop(), "qualification_coverage"),
        (lambda value: value["checks"].append(value["checks"][0]), "qualification_coverage"),
        (lambda value: value.update(candidate=base), "qualification_mismatch"),
    ):
        altered = deepcopy(valid)
        mutation(altered)
        rejected = runtime.managed(workspace, {**operation, "action": "accept", "evidence": altered})
        assert rejected["error"]["code"] == expected_code, rejected
        assert rejected["operation"]["selection"] == "pending"

    # The complete report and native observation both agree on each planted state.
    for state, expected_code in (("failed", "qualification_failed"), ("unknown", "qualification_unknown"),
                                 ("not_run", "qualification_unknown")):
        altered = deepcopy(valid)
        altered["checks"][0]["status"] = state
        report = json.loads(Path(valid["native_report"]["path"]).read_bytes())
        report["checks"][0]["status"] = state
        altered["native_report"] = write_json(tmp_path / (state + "-evaluator.json"), report)
        rejected = runtime.managed(workspace, {**operation, "action": "accept", "evidence": altered})
        assert rejected["error"]["code"] == expected_code, rejected
        assert rejected["operation"]["selection"] == "pending"

    accepted = runtime.managed(workspace, {**operation, "action": "accept", "evidence": valid})
    assert accepted["result"]["accepted_qualification"]
    changed_rules = deepcopy(rules)
    changed_rules["document"]["schema"][0]["quality"].append({
        "type": "sql", "query": "SELECT COUNT(*) FROM amounts WHERE agency = 'X'", "mustBe": 1,
    })
    second = policy(changed_rules, "quality-v2", base)
    before = native("inspect", None, "--dataset", "amounts")
    amended = runtime.managed(workspace, {
        **operation, "action": "requalify", "previous_policy_id": first["id"], "policy": second,
    })
    assert amended["result"]["candidate"] == candidate
    assert amended["result"]["computation_identity"] == computation
    assert amended["result"]["accepted_qualification"] is None
    after = native("inspect", None, "--dataset", "amounts")
    phases = {key: value for key, value in before.items() if key.startswith("phase/")}
    assert phases and phases == {key: value for key, value in after.items() if key.startswith("phase/")}
    # Recovery resolves completed work before reopening caller-owned input locators.
    Path(replacements["path"]).unlink()
    Path(deletions["path"]).unlink()
    retried = runtime.managed(workspace, prepare, prior=amended)
    assert retried["result"]["candidate"] == candidate
    assert retried["result"]["computation_identity"] == computation

    accepted = runtime.managed(workspace, {
        **operation, "action": "accept", "evidence": evidence(changed_rules, second, candidate),
    })
    assert accepted["status"] == "succeeded", accepted
    lossy = DocSpecAdapter(runtime.executable, LIMITS, evidence_dir=tmp_path / "lost-selection", capture_bytes=128)
    lost = lossy.managed(workspace, {**operation, "action": "select", "policy_id": second["id"]}, prior=accepted)
    assert lost["operation"]["selection"] == "unknown"
    assert lost["operation"]["operationId"] == "correction"
    reconciled = runtime.managed(workspace, {**operation, "action": "inspect"}, prior=lost)
    assert reconciled["result"]["candidate"] == candidate
    assert reconciled["operation"]["selection"] == "selected"

    successor = native("run", {
        "dataset": "amounts", "operation": "successor", "definition": "source-v1",
        "input": original["path"], "expected_digest": original["digest"], "sql": "SELECT * FROM input",
    })
    native("compact-lifecycle", None, "--dataset", "amounts")
    assert "readback/correction" not in native("inspect", None, "--dataset", "amounts")
    for request in (prepare, {**operation, "action": "select", "policy_id": second["id"]}):
        historical = runtime.managed(workspace, request, prior=reconciled)
        assert historical["status"] == "succeeded", historical
        assert historical["result"]["candidate"] == candidate
        assert historical["result"]["accepted_qualification"] == reconciled["result"]["accepted_qualification"]
        assert native("latest", None, "--dataset", "amounts")["id"] == successor["id"]
    assert sorted(read(candidate), key=lambda row: row["id"]) == EXPECTED
    assert sorted(read(base), key=lambda row: row["id"]) == BASE
    assert sha256(Path(original["path"]).read_bytes()).hexdigest() == original_digest


def test_update_preserves_null_policy_and_successful_empty_child_scope(integration):
    runtime, _, workspace, _, data, build, policy, evidence, read, pa = integration
    for coalesce, expected in ((False, None), (True, "retained")):
        dataset = "coalesced" if coalesce else "replaced"
        schema = pa.schema([("id", pa.string()), ("value", pa.string())])
        base, _ = build(dataset, [{"id": "A", "value": "retained"}], schema)
        admitted = policy(rules_for(dataset, [("id", "string"), ("value", "string")]), "quality", base)
        update = {"dataset": dataset, "operation": "null-correction", "base": "initial", "definition": "source-v1",
                  "keys": ["id"], "replacements": data(dataset + "-null", [{"id": "A", "value": None}], schema),
                  "deletions": None}
        if coalesce:
            update["merge"] = {"columns": {"value": "latest_or_backfill"}}
        prepared = runtime.managed(workspace, {"action": "prepare_update", "update": update, "policy": admitted})
        assert prepared["status"] == "succeeded", prepared
        assert read(prepared["result"]["candidate"]) == [{"id": "A", "value": expected}]

    schema = pa.schema([("parent_id", pa.string()), ("child_id", pa.string())])
    original = [{"parent_id": "A", "child_id": "A1"}, {"parent_id": "B", "child_id": "B1"}]
    base, _ = build("children", original, schema)
    rules = rules_for("children", [("parent_id", "string"), ("child_id", "string")])
    admitted = policy(rules, "quality", base)
    operation = {"dataset": "children", "operation": "empty-A"}
    update = {**operation, "base": "initial", "definition": "source-v1", "keys": ["parent_id"],
              "replacements": data("empty-children", [], schema),
              "deletions": data("successfully-read-parents", [{"parent_id": "A"}], pa.schema([("parent_id", pa.string())]))}
    prepared = runtime.managed(workspace, {"action": "prepare_update", "update": update, "policy": admitted})
    assert prepared["status"] == "succeeded", prepared
    candidate = prepared["result"]["candidate"]
    assert read(candidate) == [{"parent_id": "B", "child_id": "B1"}]
    accepted = runtime.managed(workspace, {**operation, "action": "accept", "evidence": evidence(rules, admitted, candidate)})
    assert accepted["status"] == "succeeded", accepted
    selected = runtime.managed(workspace, {**operation, "action": "select", "policy_id": admitted["id"]})
    assert selected["operation"]["selection"] == "selected"
    assert read(base) == original


def test_changed_source_composition_cannot_select_qualified_update(integration):
    runtime, _, workspace, native, data, build, policy, evidence, read, pa = integration
    schema = pa.schema([("id", pa.string()), ("value", pa.int64())])
    base, source = build("records", [{"id": "A", "value": 1}], schema)
    rules = rules_for("records", [("id", "string"), ("value", "integer")])
    admitted = policy(rules, "quality", base)
    operation = {"dataset": "records", "operation": "correction"}
    prepared = runtime.managed(workspace, {
        "action": "prepare_update", "policy": admitted,
        "update": {**operation, "base": "initial", "definition": "source-v1", "keys": ["id"],
                   "replacements": data("new-value", [{"id": "A", "value": 2}], schema), "deletions": None},
    })
    assert prepared["status"] == "succeeded", prepared
    candidate = prepared["result"]["candidate"]
    accepted = runtime.managed(workspace, {**operation, "action": "accept", "evidence": evidence(rules, admitted, candidate)})
    assert accepted["status"] == "succeeded", accepted
    successor = native("run", {"dataset": "records", "operation": "successor", "definition": "source-v1",
                                "input": source["path"], "expected_digest": source["digest"], "sql": "SELECT * FROM input"})
    refused = runtime.managed(workspace, {**operation, "action": "select", "policy_id": admitted["id"]})
    assert refused["error"]["code"] == "stale_base", refused
    assert native("latest", None, "--dataset", "records")["id"] == successor["id"]
    assert read(candidate) == [{"id": "A", "value": 2}]


def test_lost_acceptance_replays_after_caller_artifacts_are_removed(integration, tmp_path):
    runtime, _, workspace, native, data, build, policy, evidence, read, pa = integration
    schema = pa.schema([("id", pa.string()), ("value", pa.int64())])
    base, source = build("records", [{"id": "A", "value": 1}], schema)
    rules = rules_for("records", [("id", "string"), ("value", "integer")])
    # A valid retained parameter makes metadata decoding material to admission.
    rules["parameters"] = {"retained_annotation": "x" * (512 << 10)}
    admitted = policy(rules, "quality", base)
    operation = {"dataset": "records", "operation": "correction"}
    prepared = runtime.managed(workspace, {
        "action": "prepare_update", "policy": admitted,
        "update": {**operation, "base": "initial", "definition": "source-v1", "keys": ["id"],
                   "replacements": data("new-value", [{"id": "A", "value": 2}], schema), "deletions": None},
    })
    assert prepared["status"] == "succeeded", prepared
    candidate = prepared["result"]["candidate"]
    observed = evidence(rules, admitted, candidate)
    # Caller report locations are provenance even when they share a native prefix.
    caller_report = Path(candidate["manifest"]["path"]).with_name("caller-evaluator.json")
    caller_report.write_bytes(Path(observed["native_report"]["path"]).read_bytes())
    observed["native_report"] = {**observed["native_report"], "path": str(caller_report)}
    request = {**operation, "action": "accept", "evidence": observed}
    original_rules = Path(observed["rules"]["path"]).read_bytes()
    evaluated = json.loads(Path(observed["native_report"]["path"]).read_bytes())
    lossy = DocSpecAdapter(runtime.executable, LIMITS, evidence_dir=tmp_path / "lost-accept", capture_bytes=128)
    lost = lossy.managed(workspace, request, prior=prepared)
    assert lost["operation"]["selection"] == "unknown"
    inspected = runtime.managed(workspace, {**operation, "action": "inspect"}, prior=lost)
    accepted_identity = inspected["result"]["accepted_qualification"]
    assert accepted_identity and inspected["operation"]["selection"] == "pending"

    for artifact in (observed["rules"], observed["native_report"], observed["native_read"], evaluated["nativeReport"]):
        Path(artifact["path"]).unlink()
    cold = DocSpecAdapter(runtime.executable, LIMITS, evidence_dir=tmp_path / "cold-caller")
    changed = deepcopy(request)
    changed["evidence"]["native_report"]["sha256"] = "f" * 64
    mismatch = cold.managed(workspace, changed, prior=inspected)
    assert mismatch["status"] == "failed", mismatch
    assert mismatch["result"]["accepted_qualification"] == accepted_identity

    constrained = DocSpecAdapter(runtime.executable, {**LIMITS, "memory_bytes": 16 << 20, "max_batch_bytes": 1 << 20},
                                 evidence_dir=tmp_path / "bounded-replay")
    capacity = constrained.managed(workspace, request, prior=inspected)
    assert capacity["status"] == "failed", capacity
    assert capacity["error"]["code"] == "capacity", capacity

    replayed = cold.managed(workspace, request, prior=inspected)
    assert replayed["status"] == "succeeded", replayed
    assert replayed["result"]["accepted_qualification"] == accepted_identity
    assert replayed["result"]["candidate"] == candidate
    retained = native("inspect", None, "--dataset", "records")["managed-quality-evidence/correction/quality"]
    retained_rules = retained["resolved_rules_json"].encode("utf-8")
    assert retained_rules == original_rules
    assert sha256(retained_rules).hexdigest() == observed["rules"]["sha256"]
    selected = cold.managed(workspace, {**operation, "action": "select", "policy_id": admitted["id"]}, prior=replayed)
    assert selected["operation"]["selection"] == "selected"
    assert read(candidate) == [{"id": "A", "value": 2}]

    successor = native("run", {"dataset": "records", "operation": "successor", "definition": "source-v1",
                                "input": source["path"], "expected_digest": source["digest"], "sql": "SELECT * FROM input"})
    native("compact-lifecycle", None, "--dataset", "records")
    compacted = native("inspect", None, "--dataset", "records")
    assert "readback/correction" not in compacted
    assert compacted["result/correction"]
    historical = cold.managed(workspace, request, prior=selected)
    assert historical["status"] == "succeeded", historical
    assert historical["result"]["accepted_qualification"] == accepted_identity
    assert native("latest", None, "--dataset", "records")["id"] == successor["id"]

    retained = native("inspect", None, "--dataset", "records")
    old_data = next(obj for obj in retained["result/correction"]["dataset"]["groups"]["source"]["objects"]
                    if obj["path"].endswith(".parquet"))

    def retire(kind, *, extra=()):
        plan = native("plan-" + kind + "-retirement", None,
                      "--dataset", "records", "--retirement", "end-" + kind,
                      "--reason", "End the exact retired candidate promise", *extra)
        artifact = write_json(tmp_path / ("end-" + kind + ".json"), plan)
        command = {"phase": "phases", "change": "changes"}.get(kind, kind)
        native("retire-" + command, None, "--plan", artifact["path"])

    versions = [version for version in ("correction", "successor") if "change-certificate/" + version in retained]
    if versions:
        version_file = write_json(tmp_path / "change-versions.json", versions)
        retire("change", extra=("--versions", version_file["path"]))
    retire("availability", extra=("--operation", "correction"))
    phases = [key for key, value in retained.items() if key.startswith("phase/") and value.get("operation") == "correction"]
    if phases:
        phase_file = write_json(tmp_path / "phase-keys.json", phases)
        retire("phase", extra=("--keys", phase_file["path"]))
    retire("operation", extra=("--operation", "correction"))
    native("compact-lifecycle", None, "--dataset", "records")
    objects = write_json(tmp_path / "retired-objects.json", [old_data])
    inspection = native("inspect-retention", None, "--objects", objects["path"])
    assert inspection["objects"][0]["blocker"] is None
    assert not Path(old_data["path"]).exists()
    after = native("inspect", None, "--dataset", "records")
    assert after["managed-quality-evidence/correction/quality"]["identity"] == accepted_identity
    assert any(key.startswith("managed-quality-read/correction/") for key in after)
    ended = cold.managed(workspace, request, prior=historical)
    assert ended["error"]["code"] == "availability_retired", ended
    assert read({"dataset": "records", "version": "successor", "manifest": successor["manifest"]}) == [{"id": "A", "value": 1}]
