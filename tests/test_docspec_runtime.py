"""Opt-in conformance against the actual DocSpec subprocess."""

from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

import pytest

from ddk.adapters.docspec import DocSpecAdapter, native_version

ROOT = Path(__file__).resolve().parents[1]
LIMITS = {
    "compute_threads": 2,
    "memory_bytes": 256 << 20,
    "scratch_bytes": 64 << 20,
    "batch_rows": 8192,
    "max_batch_bytes": 8 << 20,
    "max_metadata_bytes": 2 << 20,
}


@pytest.fixture
def runtime(tmp_path):
    binary = os.environ.get("DDK_DOCSPEC_BINARY")
    if not binary:
        pytest.skip("Set DDK_DOCSPEC_BINARY to the pinned local DocSpec build")
    return DocSpecAdapter(binary, LIMITS, evidence_dir=tmp_path / "evidence")


def arrow_schema(fields):
    return {
        "fields": [
            {"name": name, "data_type": kind, "nullable": True, "dict_id": 0,
             "dict_is_ordered": False, "metadata": {}}
            for name, kind in fields
        ],
        "metadata": {},
    }


def rows(values):
    return Counter(json.dumps(value, sort_keys=True) for value in values)


def runtime_report(response, *, saved_plan=False):
    from ddk.documents import validate_document
    from ddk.execution import _record
    from ddk.results import ReportBuilder

    group = "runtime.managed" if response["operation"]["mode"] == "managed_operation" else "runtime.job"
    report = ReportBuilder("urn:ddk:test:runtime", required_groups=(group,))
    _record(report, group, "operation", response, saved_plan=saved_plan)
    built = report.build(operations=[response["operation"]])
    assert not validate_document(built)
    return built


def test_commerce_sql_and_saved_bytes_match_independent_expectations(runtime, tmp_path):
    fixture = json.loads((ROOT / "examples/commerce/tests/revenue.fixture.ddk.json").read_bytes())
    sql = (ROOT / "examples/commerce/transforms/revenue.sql").read_text()
    schemas = {
        "orders": arrow_schema([
            ("order_id", "Utf8"), ("customer_id", "Utf8"), ("order_day", "Date32"),
            ("amount_cents", "Int64"), ("status", "Utf8"),
        ]),
        "customers": arrow_schema([("customer_id", "Utf8"), ("region", "Utf8")]),
    }
    preparation = {
        "scratch": str(tmp_path / "scratch"),
        "inputs": [{"name": name, "schema": schema} for name, schema in schemas.items()],
    }
    saved_path = tmp_path / "revenue.substrait"
    prepared = runtime.prepare({
        **preparation,
        "calculation": {
            "format": "sql", "sql": sql,
            "save_substrait": {"path": str(saved_path), "readable_path": str(tmp_path / "plan.json")},
        },
    })
    assert prepared["status"] == "succeeded", prepared
    assert [
        (field["name"], field["data_type"], field["nullable"])
        for field in prepared["result"]["schema"]["fields"]
    ] == [
        ("order_day", "Date32", True), ("region", "Utf8", True), ("amount_cents", "Int64", False),
    ]
    saved_bytes = saved_path.read_bytes()
    saved = {"path": str(saved_path), "sha256": sha256(saved_bytes).hexdigest()}
    assert saved["sha256"] == prepared["result"]["substrait"]["sha256"]
    assert prepared["result"]["substrait"]["standard_validity"] == "unknown"
    decoded = runtime.prepare({**preparation, "calculation": {"format": "substrait", **saved}})
    assert decoded["status"] == "succeeded", decoded
    assert decoded["result"]["schema"] == prepared["result"]["schema"]

    inputs = []
    for name, schema in schemas.items():
        path = tmp_path / (name + ".jsonl")
        path.write_text("".join(json.dumps(row) + "\n" for row in fixture["inputs"][name]["rows"]))
        inputs.append({
            "kind": "json_lines", "name": name, "schema": schema,
            "files": [{"key": name, "path": str(path)}],
        })
    job = {
        "scratch": preparation["scratch"], "inputs": inputs, "outputs": [],
        "queries": [{"name": "revenue", "sql": "SELECT * FROM revenue"}],
    }
    for step in ({"sql": sql}, {"substrait": saved}):
        executed = runtime.execute({**job, "steps": [{"name": "revenue", **step}]})
        assert executed["status"] == "succeeded", executed
        assert rows(executed["result"]["queries"][0]["data"]) == rows(fixture["expected"]["rows"])
        if "substrait" in step:
            assert executed["result"]["saved_plans"][0]["sha256"] == saved["sha256"]

    # Both mutations retain valid protobuf wire lengths and bind a fresh byte digest.
    for original, altered in ((b"orders", b"absent"), (b"sum", b"zzz")):
        assert original in saved_bytes
        mutant = saved_bytes.replace(original, altered, 1)
        path = tmp_path / ("mutant-" + altered.decode())
        path.write_bytes(mutant)
        executed = runtime.execute({
            **job, "steps": [{"name": "revenue", "substrait": {
                "path": str(path), "sha256": sha256(mutant).hexdigest(),
            }}],
        })
        assert executed["status"] == "failed", executed
        assert not executed["result"].get("queries")
        assert executed["operation"]["outputs"] == []
        report = runtime_report(executed, saved_plan=True)
        assert report["decision"] == "failed"
        assert report["checks"][0]["diagnostics"][0]["code"] == "EXEC-PLAN-RESTRICTED"
        assert report["operations"][0]["execution"] == "failed"

    tiny = DocSpecAdapter(runtime.executable, {**LIMITS, "memory_bytes": 128},
                          evidence_dir=tmp_path / "small-budget")
    refused = tiny.execute({**job, "steps": [{"name": "revenue", "substrait": saved}]})
    assert refused["status"] == "failed", refused
    assert refused["operation"]["outputs"] == []
    report = runtime_report(refused, saved_plan=True)
    assert report["decision"] == "error"
    assert report["checks"][0]["status"] == "not_run"
    assert report["operationalErrors"][0]["code"] == "EXEC-RESOURCE-LIMIT"
    assert report["operations"][0]["execution"] == "failed"


def test_bounded_job_process_loss_keeps_native_execution_unknown(runtime, tmp_path):
    limited = DocSpecAdapter(runtime.executable, LIMITS, timeout=0.001,
                             evidence_dir=tmp_path / "timed-out")
    response = limited.execute({
        "scratch": str(tmp_path / "scratch"), "inputs": [], "steps": [], "outputs": [],
        "queries": [{"name": "query", "sql": "SELECT 1 AS value"}],
    })
    assert response["error"]["code"] == "DOCSPEC-TIMEOUT"
    assert response["receipt"]["exitCode"] < 0
    report = runtime_report(response)
    assert report["decision"] == "error"
    assert report["checks"][0]["status"] == "not_run"
    assert report["operationalErrors"][0]["code"] == "EXEC-OUTCOME-UNKNOWN"
    operation = report["operations"][0]
    assert operation["execution"] == "unknown"
    assert operation["selection"] == "not_requested"
    assert operation["reconciliation"] == "unsupported"
    assert operation["outputs"] == []



def test_caller_cancellation_preserves_the_submitted_identity(runtime, tmp_path):
    from threading import Event, Timer

    cancellation = Event()
    timer = Timer(0.15, cancellation.set)
    timer.start()
    try:
        response = runtime.execute({
            "scratch": str(tmp_path / "scratch"), "inputs": [], "steps": [], "outputs": [],
            "queries": [{"name": "query", "sql": "SELECT SUM(sin(value)) AS value FROM generate_series(1, 100000000)"}],
        }, cancel_event=cancellation)
    finally:
        timer.cancel()
    assert response["error"]["code"] == "DOCSPEC-CANCELLED", response
    assert response["receipt"]["exitCode"] < 0
    report = runtime_report(response)
    assert report["decision"] == "error"
    assert report["operationalErrors"][0]["code"] == "EXEC-CANCELLED"
    operation = report["operations"][0]
    assert operation["execution"] == "unknown" and operation["outputs"] == []
    assert operation["requestIdentity"]["value"] == response["receipt"]["request"]["sha256"]

def test_bound_parameters_and_partial_output_identity(runtime, tmp_path):
    sql = "SELECT CAST($id AS BIGINT) AS id"
    prepared = runtime.prepare({
        "scratch": str(tmp_path / "scratch"), "inputs": [],
        "calculation": {"format": "sql", "sql": sql, "parameters": {"id": 13}},
    })
    assert prepared["status"] == "succeeded", prepared
    assert prepared["result"]["schema"]["fields"][0]["data_type"] == "Int64"
    settings = {
        "profile": "whole", "row_group_rows": 128, "order_by": [{"field": "id"}],
        "dictionary_columns": [], "delta_columns": [], "key_column": None,
        "created_by": "DDK fixture", "footer_limit": 65536,
    }
    first, second = tmp_path / "first.parquet", tmp_path / "existing.parquet"
    second.write_bytes(b"owned by the previous writer")
    executed = runtime.execute({
        "scratch": str(tmp_path / "scratch"), "inputs": [],
        "steps": [{"name": "rows", "sql": sql, "parameters": {"id": 13}}],
        "outputs": [
            {"name": name, "path": str(path), "sql": 'SELECT * FROM "rows"', "settings": settings}
            for name, path in (("first", first), ("second", second))
        ],
    })
    assert executed["status"] == "failed", executed
    assert executed["operation"]["execution"] == "failed"
    assert executed["operation"]["selection"] == "not_requested"
    assert executed["operation"]["reconciliation"] == "unsupported"
    assert [(item["path"], item["sha256"]) for item in executed["operation"]["outputs"]] == [
        (str(first), sha256(first.read_bytes()).hexdigest()),
    ]
    assert second.read_bytes() == b"owned by the previous writer"
    report = runtime_report(executed)
    assert report["decision"] == "error"
    assert report["checks"][0]["status"] == "not_run"
    assert report["operationalErrors"][0]["code"] == "EXEC-JOB-FAILED"


def test_exact_native_version_survives_latest_change(runtime, tmp_path):
    pa = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    limits = tmp_path / "limits.json"
    limits.write_text(json.dumps(LIMITS))
    first_reference = None
    for version, values in (("v1", [1, 2]), ("v2", [9])):
        data = tmp_path / f"{version}.parquet"
        parquet.write_table(pa.table({
            "id": pa.array(values, pa.int64()), "label": pa.array([f"row-{value}" for value in values], pa.string()),
        }), data)
        native_digest = json.loads(subprocess.check_output([
            str(runtime.executable), "hash", "--input", str(data),
        ]))["digest"]
        spec = tmp_path / f"{version}.json"
        spec.write_text(json.dumps({
            "dataset": "records", "operation": version, "input": str(data),
            "expected_digest": native_digest, "sql": "SELECT id, label FROM input", "definition": "one",
        }))
        release = json.loads(subprocess.check_output([
            str(runtime.executable), "--workspace", str(workspace), "--limits", str(limits),
            "run", "--spec", str(spec),
        ]))
        if version == "v1":
            first_reference = {"dataset": "records", "version": version, "manifest": release["manifest"]}
    version = native_version(workspace, first_reference)
    query = {
        "scratch": str(tmp_path / "scratch"),
        "inputs": [{"kind": "native", "name": "records", "workspace": str(workspace), "nativeVersion": version}],
        "steps": [], "outputs": [], "queries": [{"name": "old", "sql": "SELECT id, label FROM records ORDER BY id"}],
    }
    semantic_profile = {"id": "urn:test:docspec:function-and-overflow-semantics", "revision": "1"}
    old = runtime.execute(query, semantic_profile=semantic_profile)
    assert old["status"] == "succeeded", old
    assert old["result"]["queries"][0]["data"] == [{"id": 1, "label": "row-1"}, {"id": 2, "label": "row-2"}]
    assert old["nativeReads"][0]["version"] == version
    assert old["nativeReads"][0]["fields"][0]["nativeFieldId"] == 1
    wrong_algorithm = {**version, "digestAlgorithm": "sha256"}
    wrong = runtime.execute({**query, "inputs": [{**query["inputs"][0], "nativeVersion": wrong_algorithm}]})
    assert wrong["status"] == "not_submitted"
    report = runtime_report(wrong)
    assert report["decision"] == "failed"
    assert report["checks"][0]["diagnostics"][0]["code"] == "EXEC-NATIVE-IDENTITY"
    missing = {**version, "reference": {**first_reference, "version": "missing"}}
    wrong = runtime.execute({**query, "inputs": [{**query["inputs"][0], "nativeVersion": missing}]})
    assert wrong["status"] == "failed"
    assert wrong["error"]["code"] == "no_release"
    assert not wrong.get("nativeReads")
    report = runtime_report(wrong)
    assert report["decision"] == "error"
    assert report["checks"][0]["status"] == "not_run"
    assert report["operationalErrors"][0]["code"] == "EXEC-NATIVE-UNAVAILABLE"

    edit = tmp_path / "schema.json"
    edit.write_text(json.dumps({
        "dataset": "records", "operation": "schema-v3", "base": "v2", "definition": "one",
        "next_definition": "two", "fields": [{"id": 2, "name": "label"}, {"id": 1, "name": "identifier"}],
    }))
    renamed = json.loads(subprocess.check_output([
        str(runtime.executable), "--workspace", str(workspace), "--limits", str(limits),
        "schema", "--spec", str(edit),
    ]))
    new_ref = native_version(workspace, {
        "dataset": "records", "version": "schema-v3", "manifest": renamed["manifest"],
    })
    new_read = runtime.read_version(workspace, new_ref)
    assert [(field["engineName"], field["nativeFieldId"]) for field in new_read["nativeRead"]["fields"]] == [
        ("label", 2), ("identifier", 1),
    ]
    after_rename = runtime.execute(query, semantic_profile=semantic_profile)
    assert [(field["engineName"], field["nativeFieldId"]) for field in after_rename["nativeReads"][0]["fields"]] == [
        ("id", 1), ("label", 2),
    ]
    assert after_rename["result"]["queries"] == old["result"]["queries"]

    from shutil import copy2
    from ddk.locks import verify_execution_inputs

    relocated = tmp_path / "relocated-docspec"
    copy2(runtime.executable, relocated)
    other = DocSpecAdapter(relocated, LIMITS, evidence_dir=tmp_path / "relocated-evidence")
    moved = other.execute(query, semantic_profile=semantic_profile)
    assert moved["result"]["queries"] == old["result"]["queries"]
    assert moved["receipt"]["endpoint"] != old["receipt"]["endpoint"]
    assert moved["operation"]["requestIdentity"] == old["operation"]["requestIdentity"]
    assert moved["receipt"]["tool"] == old["receipt"]["tool"]
    verify = {
        "expected_tool": moved["receipt"]["tool"],
        "current_native_reads": moved["nativeReads"],
        "permitted_roots": (tmp_path,),
    }
    assert verify_execution_inputs(old["evidence"]["path"], **verify, expected_semantics=semantic_profile)["decision"] == "passed"
    changed = verify_execution_inputs(old["evidence"]["path"], **verify,
                                      expected_semantics={**semantic_profile, "revision": "2"})
    assert changed["decision"] == "failed"
    assert changed["checks"][0]["diagnostics"][0]["code"] == "EXEC-SEMANTICS-MISMATCH"

    backfill = tmp_path / "backfill.json"
    backfill.write_text(json.dumps({
        "dataset": "records", "operation": "v4", "base": "schema-v3", "definition": "two",
        "group": "extra", "group_definition": "extra-v1",
        "fields": [{"id": 1, "name": "doubled", "expression": "identifier * 2"}],
    }))
    grouped = json.loads(subprocess.check_output([
        str(runtime.executable), "--workspace", str(workspace), "--limits", str(limits),
        "backfill", "--spec", str(backfill),
    ]))
    group_version = native_version(workspace, {
        "dataset": "records", "version": "v4", "manifest": grouped["manifest"],
    })
    ambiguous = runtime.execute({**query, "inputs": [{**query["inputs"][0], "nativeVersion": group_version}]})
    assert ambiguous["status"] == "failed"
    assert ambiguous["error"]["code"] == "unsupported_native_mapping"


def test_managed_reconciliation_checks_full_scope_before_submission(runtime, tmp_path):
    workspace = tmp_path / "first-host"
    other = tmp_path / "second-host"
    workspace.mkdir()
    other.mkdir()
    # A scoped lost-response receipt can exist before a candidate is observed.
    prior = {
        "operationContext": {"runtime": "docspec", "workspace": str(workspace),
                             "dataset": "first-dataset", "operationId": "run1"},
        "operation": {"runtime": "docspec", "mode": "managed_operation", "operationId": "run1",
                      "execution": "unknown", "selection": "unknown"},
    }
    inspect = {"action": "inspect", "dataset": "first-dataset", "operation": "run1"}
    before = list(runtime.evidence_dir.iterdir())
    with pytest.raises(ValueError, match="another workspace"):
        runtime.managed(other, inspect, prior=prior)
    with pytest.raises(ValueError, match="another workspace"):
        runtime.managed(workspace, {**inspect, "dataset": "second-dataset"}, prior=prior)
    assert list(runtime.evidence_dir.iterdir()) == before


def test_managed_build_uses_exact_external_quality_and_recovers_lost_selection(runtime, tmp_path):
    from copy import deepcopy
    from datetime import date

    from ddk.adapters.native import NativeTools, write_json
    from ddk.core import load_project
    from ddk.quality import dataset_rules

    native_python = os.environ.get("DDK_NATIVE_PYTHON")
    if not native_python:
        pytest.skip("Set DDK_NATIVE_PYTHON to the pinned native quality environment")
    pa = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    tools = NativeTools(native_python, output=tmp_path / "quality")
    workspace = tmp_path / "host"
    workspace.mkdir()
    fixture = json.loads((ROOT / "examples/commerce/tests/revenue.fixture.ddk.json").read_bytes())
    expected = fixture["expected"]["rows"]
    typed = [{**row, "order_day": date.fromisoformat(row["order_day"])} for row in expected]
    schema = pa.schema([("order_day", pa.date32()), ("region", pa.string()), ("amount_cents", pa.int64())])
    data = tmp_path / "independent-revenue.parquet"
    parquet.write_table(pa.Table.from_pylist(typed, schema=schema), data)
    digest = json.loads(subprocess.check_output([
        str(runtime.executable), "hash", "--input", str(data),
    ]))["digest"]
    artifact = load_project(ROOT / "examples/commerce/project.ddk.json").resolve("daily-revenue")
    rules = dataset_rules(artifact)
    changed = deepcopy(rules)
    changed["document"]["schema"][0]["quality"][0]["query"] = (
        "SELECT COUNT(*) FROM daily_revenue WHERE amount_cents < 0"
    )

    def quality_policy(request, policy_id):
        plan = tools.invoke("quality-plan", request)
        assert plan["status"] == "not_run", plan
        tool = plan["evaluator"]
        return {
            "id": policy_id, "rules_sha256": plan["rules"]["sha256"],
            "evaluator": {"id": tool["id"], "version": tool["version"],
                          "distribution_sha256": tool["distributionSha256"]},
            "semantics": plan["mappingSemantics"], "required_checks": plan["requiredCheckIds"],
            "expected_epoch": 0, "expected_selection": None,
        }

    first = quality_policy(rules, "rules-v1")
    second = quality_policy(changed, "rules-v2")
    assert first["rules_sha256"] != second["rules_sha256"]
    operation = {"dataset": "revenue", "operation": "candidate-1"}
    prepare = {
        "action": "prepare",
        "build": {**operation, "input": str(data), "expected_digest": digest,
                  "definition": "source-v1", "sql": "SELECT order_day, region, amount_cents FROM input"},
        "policy": first,
    }
    prepared = runtime.managed(workspace, prepare)
    assert prepared["status"] == "succeeded", prepared
    candidate = prepared["result"]["candidate"]
    computation = prepared["result"]["computation_identity"]
    assert prepared["operation"]["selection"] == "pending"
    rebound = runtime.managed(workspace, {
        **prepare, "build": {**prepare["build"], "sql": "SELECT order_day, region, amount_cents + 1 AS amount_cents FROM input"},
    })
    assert rebound["status"] == "failed"
    assert runtime_report(rebound)["checks"][0]["diagnostics"][0]["code"] == "EXEC-REQUEST-CONFLICT"
    assert rebound["operation"]["candidate"] == prepared["operation"]["candidate"]
    missing = runtime.managed(workspace, {**operation, "action": "select", "policy_id": first["id"]})
    assert missing["error"]["code"] == "qualification_required"
    assert missing["operation"]["execution"] == "succeeded"
    limits = write_json(tmp_path / "limits.json", LIMITS)
    build = write_json(tmp_path / "ordinary-build.json", prepare["build"])
    bypass = subprocess.run([
        str(runtime.executable), "--workspace", str(workspace), "--limits", limits["path"],
        "run", "--spec", build["path"],
    ], capture_output=True, check=False)
    assert bypass.returncode != 0
    assert b"qualification_policy_mismatch" in bypass.stderr

    def quality_evidence(request, policy, status="passed"):
        evaluated = tools.invoke("quality", {
            **request,
            "target": {
                "kind": "native", "nativeVersion": candidate,
                "read": {"workspace": str(workspace), "executable": str(runtime.executable),
                         "executableSha256": runtime.tool["distributionSha256"], "limits": LIMITS},
            },
        })
        assert evaluated["status"] == status, evaluated
        assert evaluated["rules"]["sha256"] == policy["rules_sha256"]
        assert evaluated["evaluator"]["distributionSha256"] == policy["evaluator"]["distribution_sha256"]
        return evaluated, {
            "policy_id": policy["id"], "candidate": candidate, "rules": evaluated["rules"],
            "evaluator": policy["evaluator"], "semantics": policy["semantics"],
            "checks": [{name: check[name] for name in ("id", "status")} for check in evaluated["checks"]],
            "native_report": evaluated["receipt"],
            "native_read": {name: evaluated["nativeRead"][name] for name in ("path", "sha256")},
        }

    _, first_evidence = quality_evidence(rules, first)
    first_checks = first_evidence["checks"]
    incomplete = {**first_evidence, "checks": [*first_checks[:-1], first_checks[0]]}
    refused = runtime.managed(workspace, {**operation, "action": "accept", "evidence": incomplete})
    assert refused["error"]["code"] == "qualification_coverage"
    assert runtime_report(refused)["checks"][0]["diagnostics"][0]["code"] == "EXEC-QUALIFICATION-COVERAGE"
    assert refused["operation"]["selection"] == "pending"
    accepted = runtime.managed(workspace, {**operation, "action": "accept", "evidence": first_evidence})
    first_qualification = accepted["result"]["accepted_qualification"]
    assert first_qualification
    amended = runtime.managed(workspace, {
        **operation, "action": "requalify", "previous_policy_id": first["id"], "policy": second,
    })
    assert amended["result"]["candidate"] == candidate
    assert amended["result"]["computation_identity"] == computation
    assert amended["result"]["accepted_qualification"] is None
    stale = runtime.managed(workspace, {**operation, "action": "select", "policy_id": first["id"]})
    assert stale["error"]["code"] == "stale_qualification_policy"
    stale_evidence = runtime.managed(workspace, {
        **operation, "action": "accept", "evidence": first_evidence,
    })
    assert stale_evidence["error"]["code"] == "qualification_mismatch"

    evaluated, evidence = quality_evidence(changed, second)
    failed_native = json.loads(Path(evaluated["nativeReport"]["path"]).read_bytes())
    failed_native["result"] = "failed"
    replaced_raw = write_json(tmp_path / "failed-native.json", failed_native)
    forged = deepcopy(evaluated)
    forged["nativeReport"] = replaced_raw
    forged_ref = write_json(tmp_path / "inconsistent-evaluator-receipt.json", forged)
    rejected = runtime.managed(workspace, {
        **operation, "action": "accept", "evidence": {**evidence, "native_report": forged_ref},
    })
    assert rejected["error"]["code"] == "qualification_mismatch"
    assert rejected["operation"]["selection"] == "pending"

    accepted = runtime.managed(workspace, {**operation, "action": "accept", "evidence": evidence})
    selected_qualification = accepted["result"]["accepted_qualification"]
    assert selected_qualification and selected_qualification != first_qualification
    lossy = DocSpecAdapter(runtime.executable, LIMITS, evidence_dir=tmp_path / "lost-receipt", capture_bytes=128)
    lost = lossy.managed(workspace, {**operation, "action": "select", "policy_id": second["id"]},
                         prior=accepted)
    assert lost["operation"]["selection"] == "unknown"
    assert lost["operation"]["operationId"] == operation["operation"]
    reconciled = runtime.managed(workspace, {**operation, "action": "inspect"}, prior=lost)
    assert reconciled["operation"]["selection"] == "selected"
    assert reconciled["result"]["computation_identity"] == computation
    assert reconciled["result"]["candidate"] == candidate
    assert reconciled["result"]["accepted_qualification"] == selected_qualification
    audit, audit_evidence = quality_evidence(changed, second)
    assert audit["nativeRead"]["observed"]["read_id"] != evaluated["nativeRead"]["observed"]["read_id"]
    audit_only = runtime.managed(workspace, {**operation, "action": "accept", "evidence": audit_evidence})
    assert runtime_report(audit_only)["checks"][0]["diagnostics"][0]["code"] == "EXEC-QUALIFICATION-AUDIT-ONLY"
    assert audit_only["operation"]["selection"] == "selected"
    assert audit_only["result"]["accepted_qualification"] == selected_qualification

    # Change real native authority after another candidate has accepted evidence.
    next_operation = {**operation, "operation": "candidate-2"}
    next_policy = {**second, "expected_selection": candidate}
    pending = runtime.managed(workspace, {
        **prepare, "build": {**prepare["build"], **next_operation}, "policy": next_policy,
    })
    assert pending["status"] == "succeeded", pending
    candidate = pending["result"]["candidate"]
    wrong_candidate = runtime.managed(workspace, {**next_operation, "action": "accept", "evidence": evidence})
    assert wrong_candidate["error"]["code"] == "qualification_mismatch"
    assert runtime_report(wrong_candidate)["checks"][0]["diagnostics"][0]["code"] == "EXEC-QUALIFICATION-MISMATCH"
    assert wrong_candidate["operation"]["candidate"]["reference"] == candidate

    advance = write_json(tmp_path / "advance-latest.json", {
        **prepare["build"], "operation": "latest-advanced",
    })
    latest_release = json.loads(subprocess.check_output([
        str(runtime.executable), "--workspace", str(workspace), "--limits", limits["path"],
        "run", "--spec", advance["path"],
    ]))
    assert latest_release["id"] == "latest-advanced"
    bridge, evidence = quality_evidence(changed, next_policy)
    assert bridge["target"] == {"kind": "native", "nativeVersion": candidate}
    assert bridge["nativeRead"]["observed"]["version"] == candidate
    assert bridge["nativeRead"]["transport"] == "arrow-ipc-pipe"
    assert not list(tools.output.rglob("*.parquet"))
    accepted = runtime.managed(workspace, {**next_operation, "action": "accept", "evidence": evidence})
    assert accepted["result"]["accepted_qualification"]
    subprocess.run([
        str(runtime.executable), "--workspace", str(workspace), "--limits", limits["path"],
        "fence-operations", "--dataset", operation["dataset"], "--expected-epoch", "0",
    ], capture_output=True, check=True)
    fenced = runtime.managed(workspace, {
        **next_operation, "action": "select", "policy_id": next_policy["id"],
    })
    assert fenced["status"] == "failed", fenced
    assert fenced["error"]["code"] in {"stale_eligibility", "stale_qualification_authority"}
    assert fenced["operation"]["selection"] == "refused"
    assert runtime_report(fenced)["checks"][0]["diagnostics"][0]["code"] == "EXEC-SELECTION-STALE"
    latest = json.loads(subprocess.check_output([
        str(runtime.executable), "--workspace", str(workspace), "--limits", limits["path"],
        "latest", "--dataset", operation["dataset"],
    ]))
    assert latest["id"] == "latest-advanced"

    # A real unsupported Data Contract CLI rule returns a native warning.
    unavailable_rules = deepcopy(rules)
    unavailable_rules["document"]["schema"][0]["quality"].append({
        "id": "soda-audit", "type": "custom", "engine": "soda", "implementation": "row_count > 0",
    })
    unknown_policy = {
        **quality_policy(unavailable_rules, "rules-unknown"),
        "expected_epoch": 1,
        "expected_selection": {"dataset": operation["dataset"], "version": latest["id"], "manifest": latest["manifest"]},
    }
    unknown_operation = {**operation, "operation": "candidate-unknown"}
    pending = runtime.managed(workspace, {
        **prepare, "build": {**prepare["build"], **unknown_operation}, "policy": unknown_policy,
    })
    assert pending["status"] == "succeeded", pending
    candidate = pending["result"]["candidate"]
    unknown, evidence = quality_evidence(unavailable_rules, unknown_policy, status="unknown")
    assert any(check["status"] == "unknown" for check in unknown["checks"])
    rejected = runtime.managed(workspace, {**unknown_operation, "action": "accept", "evidence": evidence})
    check = runtime_report(rejected)["checks"][0]
    assert check["status"] == "unknown"
    assert check["diagnostics"][0]["code"] == "EXEC-QUALIFICATION-UNKNOWN"
    assert rejected["operation"]["selection"] == "pending"

    mixed_rules = deepcopy(unavailable_rules)
    mixed_rules["document"]["schema"][0]["quality"].append({
        "id": "require-empty", "type": "sql", "query": "SELECT COUNT(*) FROM daily_revenue", "mustBe": 0,
    })
    mixed_policy = {
        **quality_policy(mixed_rules, "rules-mixed"),
        "expected_epoch": unknown_policy["expected_epoch"],
        "expected_selection": unknown_policy["expected_selection"],
    }
    mixed_operation = {**operation, "operation": "candidate-mixed"}
    mixed_pending = runtime.managed(workspace, {
        **prepare, "build": {**prepare["build"], **mixed_operation}, "policy": mixed_policy,
    })
    assert mixed_pending["status"] == "succeeded", mixed_pending
    candidate = mixed_pending["result"]["candidate"]
    mixed, evidence = quality_evidence(mixed_rules, mixed_policy, status="failed")
    assert {"failed", "unknown"} <= {check["status"] for check in mixed["checks"]}
    rejected = runtime.managed(workspace, {**mixed_operation, "action": "accept", "evidence": evidence})
    check = runtime_report(rejected)["checks"][0]
    assert check["status"] == "failed"
    assert check["diagnostics"][0]["code"] == "EXEC-QUALIFICATION-FAILED"
    assert rejected["operation"]["selection"] == "pending"

    from ddk.adapters.native import file_sha256
    candidate = pending["result"]["candidate"]
    inaccessible = tmp_path / "other-host"
    inaccessible.mkdir()
    unavailable = tools.invoke("quality", {**rules, "target": {
        "kind": "native", "nativeVersion": candidate,
        "read": {"workspace": str(inaccessible), "executable": str(runtime.executable),
                 "executableSha256": runtime.tool["distributionSha256"], "limits": LIMITS},
    }})
    assert unavailable["status"] == "error"
    assert "DOCSPEC-NATIVE-UNAVAILABLE" in unavailable["reason"]
    assert "nativeRead" not in unavailable
    file_pass = tools.invoke("quality", {
        **rules, "target": {"kind": "files", "files": [{"path": str(data), "sha256": file_sha256(data)}]},
    })
    assert file_pass["status"] == "passed"
    file_only = runtime.managed(workspace, {**unknown_operation, "action": "accept", "evidence": {
        "candidate": candidate, "native_report": file_pass["receipt"],
    }}, prior=pending)
    report = runtime_report(file_only)
    assert report["decision"] == "incomplete"
    assert report["checks"][0]["diagnostics"][0]["code"] == "ADAPTER-QUALITY-ACCESS-MISSING"
    assert "exitCode" not in file_only["receipt"]

    unsupported = runtime.managed(workspace, {**unknown_operation, "action": "inspect"},
                                  backend="unqualified-remote", prior=pending)
    report = runtime_report(unsupported)
    assert report["decision"] == "incomplete"
    assert report["checks"][0]["diagnostics"][0]["code"] == "ADAPTER-OPERATION-UNSUPPORTED"
    assert "exitCode" not in unsupported["receipt"]
