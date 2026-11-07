"""Independent whole-job conformance through the actual native subprocess."""

import base64
from collections import Counter
from copy import deepcopy
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import shutil

import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.adapters.native import run_bounded
from ddk.docspec_job_evidence import (
    COUNTER_EVALUATOR, COUNTER_PROFILE, COUNTER_SEMANTICS, SNAPSHOT_COMPLETION_PROFILE, verify_completed_job,
    PRODUCER_COMPLETION_PROFILE, PRODUCER_PREREQUISITE_PROFILE,
)


LIMITS = {
    "compute_threads": 1,
    "memory_bytes": 128 << 20,
    "scratch_bytes": 64 << 20,
    "batch_rows": 2048,
    "max_batch_bytes": 8 << 20,
    "max_metadata_bytes": 4 << 20,
}


@pytest.fixture
def runtime(tmp_path):
    binary = os.environ.get("DDK_DOCSPEC_BINARY")
    if not binary:
        pytest.skip("Set DDK_DOCSPEC_BINARY to the pinned native whole-job build")
    return DocSpecAdapter(binary, LIMITS, timeout=30, evidence_dir=tmp_path / "evidence")


def _artifact(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": sha256(raw).hexdigest()}


def _whole_job(tmp_path):
    """Two inputs share a join; blocking counters and metadata have distinct roles."""
    settings = {
        "profile": "whole", "row_group_rows": 128, "order_by": [], "columns": [],
        "dictionary_columns": [], "delta_columns": [], "key_column": None,
        "created_by": "DDK independently authored whole-job fixture", "footer_limit": 65536,
    }
    return {
        "scratch": str(tmp_path / "scratch"),
        "inputs": [
            {"kind": "parquet", "name": name, "path": str(tmp_path / f"{name}.parquet")}
            for name in ("orders", "customers")
        ],
        "steps": [
            {"name": "joined", "materialize": True,
             "sql": "SELECT o.id, c.region, o.amount FROM orders o LEFT JOIN customers c ON o.customer = c.customer"},
            {"name": "totals", "sql": "SELECT region, COUNT(*) AS row_count, SUM(amount) AS total FROM joined GROUP BY region"},
        ],
        "outputs": [
            {"name": name, "path": str(tmp_path / f"{name}.parquet"),
             "sql": f"SELECT * FROM {name}",
             "settings": {**settings, "order_by": [{"field": "id" if name == "joined" else "region"}]}}
            for name in ("joined", "totals")
        ],
        "queries": [
            {"name": "invariants", "sql": "SELECT COUNT(*) - 5 AS row_delta FROM joined"},
            {"name": "null_counters", "sql": "SELECT COUNT(*) - 1 AS missing_delta FROM joined WHERE amount IS NULL"},
            {"name": "facets", "sql": "SELECT region, COUNT(*) AS count FROM joined GROUP BY region"},
        ],
    }


def _schemas():
    pa = pytest.importorskip("pyarrow")
    return {
        "orders": pa.schema([
            pa.field("source_occurrence", pa.int64(), nullable=False),
            pa.field("id", pa.int64(), nullable=False),
            pa.field("customer", pa.int64(), nullable=False),
            pa.field("amount", pa.int64(), nullable=True),
        ]),
        "customers": pa.schema([
            pa.field("customer", pa.int64(), nullable=False),
            pa.field("region", pa.string(), nullable=True),
        ]),
    }


def _preparation(tmp_path, job):
    return {
        "job": _artifact(tmp_path / "job.json", job),
        "inputs": [
            {"name": name, "schema_ipc_base64": base64.b64encode(schema.serialize().to_pybytes()).decode()}
            for name, schema in _schemas().items()
        ],
    }


def test_whole_job_preparation_preserves_all_named_views_without_opening_inputs(runtime, tmp_path):
    pa = pytest.importorskip("pyarrow")
    job = _whole_job(tmp_path)
    request = _preparation(tmp_path, job)
    response = runtime.prepare_job(request)
    assert response["status"] == "succeeded", response
    prepared = response["result"]
    assert prepared["profile"] == "urn:docspec:job:schema-only:1"
    assert prepared["status"] == "inferred"
    assert prepared["input_admission"] == prepared["execution"] == "not_run"
    assert prepared["job"] == request["job"]
    assert "operation" not in response and "candidate" not in prepared
    for section in ("inputs", "steps", "outputs", "queries"):
        assert [view["name"] for view in prepared[section]] == [view["name"] for view in job[section]]

    def schema(section, name):
        view = next(row for row in prepared[section] if row["name"] == name)
        raw = base64.b64decode(prepared["schemas"][view["schema_sha256"]])
        assert sha256(raw).hexdigest() == view["schema_sha256"]
        return pa.ipc.read_schema(pa.BufferReader(raw))

    assert schema("outputs", "joined").names == ["id", "region", "amount"]
    assert schema("outputs", "totals").names == ["region", "row_count", "total"]
    assert schema("queries", "invariants").names == ["row_delta"]
    assert schema("queries", "invariants").field(0).type == pa.int64()
    assert schema("queries", "null_counters").names == ["missing_delta"]
    assert schema("queries", "facets").names == ["region", "count"]
    assert all(not Path(item["path"]).exists() for item in (*job["inputs"], *job["outputs"]))


def test_whole_job_preparation_refuses_changed_job_bytes(runtime, tmp_path):
    job = _whole_job(tmp_path)
    request = _preparation(tmp_path, job)
    Path(request["job"]["path"]).write_text("{}\n")
    response = runtime.prepare_job(request)
    assert response["status"] == "failed", response
    assert response["error"]
    assert "candidate" not in response["result"] and "operation" not in response
    assert all(not Path(item["path"]).exists() for item in (*job["inputs"], *job["outputs"]))


# Independently authored business expectations, never calculated from fixture SQL.
ORDERS = [
    {"source_occurrence": 1, "id": 1, "customer": 10, "amount": 100},
    {"source_occurrence": 2, "id": 1, "customer": 10, "amount": 100},
    {"source_occurrence": 3, "id": 3, "customer": 20, "amount": None},
    {"source_occurrence": 4, "id": 4, "customer": 99, "amount": -25},
    {"source_occurrence": 5, "id": 5, "customer": 30, "amount": 0},
]
CUSTOMERS = [{"customer": 10, "region": "east"}, {"customer": 20, "region": "west"},
             {"customer": 30, "region": "east"}]
EXPECTED_JOINED = [
    {"id": 1, "region": "east", "amount": 100},
    {"id": 1, "region": "east", "amount": 100},
    {"id": 3, "region": "west", "amount": None},
    {"id": 4, "region": None, "amount": -25},
    {"id": 5, "region": "east", "amount": 0},
]
EXPECTED_TOTALS = [{"region": "east", "row_count": 3, "total": 200},
                   {"region": "west", "row_count": 1, "total": None},
                   {"region": None, "row_count": 1, "total": -25}]


def _retained_request(runtime, tmp_path, *, wrong_counter=False):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    job = _whole_job(tmp_path)
    # Native exports require unique sort keys. Keep source occurrence only for
    # ordering; the exported business rows still contain the intentional duplicate.
    job["steps"][0]["sql"] = (
        "SELECT o.source_occurrence, o.id, c.region, o.amount "
        "FROM orders o LEFT JOIN customers c ON o.customer = c.customer"
    )
    job["outputs"][0]["settings"].update({"order_by": [{"field": "source_occurrence"}],
                                         "columns": ["id", "region", "amount"]})
    job["queries"] = [
        {"name": "invariants", "sql": 'SELECT COUNT(*) - 5 AS row_delta FROM outputs."joined"'},
        {"name": "null_counters", "sql": 'SELECT COUNT(*) - 1 AS missing_delta FROM outputs."joined" WHERE amount IS NULL'},
        {"name": "facets", "sql": 'SELECT region, COUNT(*) AS count FROM outputs."joined" GROUP BY region'},
    ]
    if wrong_counter:
        job["queries"][0]["sql"] = 'SELECT COUNT(*) - 4 AS row_delta FROM outputs."joined"'
    preparation = _preparation(tmp_path, job)
    response = runtime.prepare_job(preparation)
    assert response["status"] == "succeeded", response
    schemas = _schemas()
    file_inputs = []
    for item, rows in zip(job["inputs"], (ORDERS, CUSTOMERS)):
        path = Path(item["path"])
        pq.write_table(pa.Table.from_pylist(rows, schema=schemas[item["name"]]), path)
        raw = path.read_bytes()
        file_inputs.append({"name": item["name"], "members": [{"key": None, "sha256": sha256(raw).hexdigest(), "size": len(raw)}]})
    prepared = response["result"]
    policy = {
        "id": "counts-v1", "profile": COUNTER_PROFILE, "evaluator": COUNTER_EVALUATOR,
        "semantics": COUNTER_SEMANTICS, "job_sha256": preparation["job"]["sha256"],
        "view_names": {section: [item["name"] for item in job["queries" if section == "reports" else section]]
                       for section in ("inputs", "steps", "outputs", "reports")},
        "required_reports": [
            {"name": query["name"], "sql_sha256": sha256(query["sql"].encode()).hexdigest(),
             "schema_ipc_base64": prepared["schemas"][next(view["schema_sha256"] for view in prepared["queries"]
                                                           if view["name"] == query["name"])]}
            for query in job["queries"][:2]
        ],
    }
    request = {
        "action": "prepare", "dataset": "whole", "operation": "original", "definition": "urn:ddk:fixture:whole-job:1",
        "job": preparation["job"], "file_inputs": file_inputs, "policy_id": policy["id"],
        "policy": _artifact(tmp_path / "policy.json", policy), "expected_epoch": 0, "expected_selection": None,
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace, request, job, policy


def _action(prepared, action, policy_id):
    native = prepared["result"]
    return {"action": action, "dataset": native["dataset"], "operation": native["operation"],
            "request_digest": native["request_digest"], "candidate": native["candidate"], "policy_id": policy_id}


def _rows(values):
    return Counter(json.dumps(row, sort_keys=True) for row in values)


def test_retained_job_outputs_native_acceptance_and_recovery_use_exact_original_work(runtime, tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    workspace, request, job, policy = _retained_request(runtime, tmp_path)
    prepared = runtime.managed_job(workspace, request)
    assert prepared["status"] == "succeeded", prepared
    assert prepared["operation"]["execution"] == "succeeded"
    assert prepared["operation"]["selection"] == "pending"
    verified = verify_completed_job(prepared["result"])
    assert verified.admitted_request == request
    for section in ("inputs", "steps", "outputs", "reports"):
        assert list(verified.view_names[section]) == policy["view_names"][section]
    outputs = {row["name"]: row for row in prepared["result"]["completed_outputs"]}
    for name, expected in (("joined", EXPECTED_JOINED), ("totals", EXPECTED_TOTALS)):
        path = Path(outputs[name]["path"])
        assert path.is_relative_to(workspace)
        assert sha256(path.read_bytes()).hexdigest() == outputs[name]["sha256"]
        assert _rows(pq.read_table(path).to_pylist()) == _rows(expected)
    assert all(not Path(output["path"]).exists() for output in job["outputs"])
    facets = next(row for row in prepared["result"]["result"]["queries"] if row["name"] == "facets")
    assert _rows(facets["data"]) == _rows([{"region": "east", "count": 3}, {"region": "west", "count": 1},
                                         {"region": None, "count": 1}])

    accepted = runtime.managed_job(workspace, _action(prepared, "accept", "counts-v1"), prior=prepared)
    assert accepted["status"] == "succeeded", accepted
    verify_completed_job(accepted["result"], require_accepted=True)
    candidate = deepcopy(accepted["result"]["candidate"])
    # Native retained facts must remain usable after caller-owned originals go.
    for path in [request["job"]["path"], request["policy"]["path"], *(item["path"] for item in job["inputs"])]:
        Path(path).unlink()
    replay = runtime.managed_job(workspace, request, prior=accepted)
    assert replay["status"] == "succeeded", replay
    assert replay["result"]["candidate"] == candidate
    assert replay["result"]["result"] == prepared["result"]["result"]

    second_policy = {**policy, "id": "counts-v2"}
    requalification = {**_action(prepared, "requalify", "counts-v2"), "previous_policy_id": "counts-v1",
                       "policy": _artifact(tmp_path / "policy-v2.json", second_policy),
                       "expected_epoch": 0, "expected_selection": None}
    qualified = runtime.managed_job(workspace, requalification, prior=replay)
    assert qualified["status"] == "succeeded", qualified
    assert qualified["result"]["candidate"] == candidate
    second = runtime.managed_job(workspace, _action(prepared, "accept", "counts-v2"), prior=qualified)
    assert second["status"] == "succeeded", second
    assert second["operation"]["acceptedQualification"] != accepted["operation"]["acceptedQualification"]
    select = {**_action(prepared, "select", "counts-v2"),
              "accepted_qualification": second["result"]["accepted_qualification"]["identity"]}
    lossy = DocSpecAdapter(runtime.executable, LIMITS, timeout=30, capture_bytes=128,
                          evidence_dir=tmp_path / "lost-selection")
    # A small capture limit bounds the returned stream, not previously pinned metadata.
    lost = lossy.managed_job(workspace, select)
    assert lost["status"] == "unknown", lost
    cold = DocSpecAdapter(runtime.executable, LIMITS, timeout=30, evidence_dir=tmp_path / "cold")
    observed = cold.managed_job(workspace, {"action": "inspect", "dataset": "whole", "operation": "original"}, prior=lost)
    assert observed["status"] == "succeeded", observed
    assert observed["operation"]["selection"] == "selected"
    assert observed["result"]["candidate"] == candidate
    assert observed["operation"]["acceptedQualification"] == second["operation"]["acceptedQualification"]


def test_native_nonzero_counter_refuses_qualification_without_erasing_completed_outputs(runtime, tmp_path):
    workspace, request, _job, _policy = _retained_request(runtime, tmp_path, wrong_counter=True)
    prepared = runtime.managed_job(workspace, request)
    assert prepared["status"] == "succeeded", prepared
    rejected = runtime.managed_job(workspace, _action(prepared, "accept", "counts-v1"), prior=prepared)
    assert rejected["status"] == "failed", rejected
    assert rejected["result"]["status"] == "completed"
    assert rejected["operation"]["execution"] == "succeeded"
    assert rejected["operation"]["selection"] == "pending"
    assert rejected["operation"]["candidate"] == prepared["operation"]["candidate"]
    assert rejected["operation"]["outputs"] == prepared["operation"]["outputs"]
    assert rejected["result"]["accepted_qualification"] is None
    assert next(row for row in rejected["result"]["completed_reports"] if row["name"] == "invariants")["data"] == [{"row_delta": 1}]


# Authored independently of both the producer SQL and retained consumer SQL.
EXPECTED_SNAPSHOT = [
    {"prefix": "snapshot", "id": 1, "amount": 7},
    {"prefix": "snapshot", "id": 2, "amount": None},
    {"prefix": "snapshot", "id": 3, "amount": -5},
]


def _snapshot_request(runtime, tmp_path):
    """Seed original Iceberg bytes through the ordinary public native job API."""
    pa = pytest.importorskip("pyarrow")
    producer = tmp_path / "producer"
    producer.mkdir()
    table = {"namespace": ["authored"], "name": "source"}
    schema = {"type": "struct", "schema-id": 0, "identifier-field-ids": [2], "fields": [
        {"id": 1, "name": "prefix", "required": True, "type": "string"},
        {"id": 2, "name": "id", "required": True, "type": "long"},
        {"id": 3, "name": "amount", "required": False, "type": "long"},
    ]}
    seed = {
        "scratch": str(producer / "scratch"), "catalog_root": str(producer / "catalog"), "inputs": [],
        "steps": [{"name": "incoming", "sql": "SELECT 'snapshot' AS prefix,CAST(id AS BIGINT) AS id,"
                   "CAST(amount AS BIGINT) AS amount FROM (VALUES (1,7),(2,NULL),(3,-5)) AS authored(id,amount)"}],
        "outputs": [], "table_operations": [
            {"kind": "create_namespace", "name": "namespace", "namespace": ["authored"], "properties": {}},
            {"kind": "create", "name": "create", "table": table, "location": str(producer / "data"),
             "schema": schema, "format_version": 2, "properties": {"gc.enabled": "true", "commit.retry.num-retries": "0"}},
            {"kind": "append", "name": "append", "table": table, "current_table": "existing", "work_table": "pending",
             "sql": "SELECT * FROM incoming", "identity_sql": "SELECT 'authored-three-values-v1' AS identity FROM pending LIMIT 1",
             "layout": {"file_bytes": 1048576, "row_group_rows": 64, "row_group_bytes": 1048576}},
        ],
    }
    # Fixture creation uses the public native CLI. DDK's ordinary calculation
    # profile deliberately excludes catalog writes.
    seed_spec = _artifact(tmp_path / "seed-job.json", seed)
    seed_limits = _artifact(tmp_path / "seed-limits.json", LIMITS)
    transport = run_bounded(
        [str(runtime.executable), "--limits", seed_limits["path"], "job", "--spec", seed_spec["path"]],
        timeout=runtime.timeout, limit=runtime.capture_bytes, stop_on_stdout_limit=True,
    )
    (tmp_path / "seed-stdout.json").write_bytes(transport["stdout"])
    (tmp_path / "seed-stderr.log").write_bytes(transport["stderr"])
    _artifact(tmp_path / "seed-transport.json", {key: value for key, value in transport.items() if key not in {"stdout", "stderr"}})
    assert transport["exitCode"] == 0 and not any(transport[key] for key in (
        "timedOut", "cancelled", "stdoutTruncated", "stderrTruncated", "drainIncomplete",
    )), transport
    head = json.loads(transport["stdout"])["table_operations"][-1]
    selector = {"kind": "native_table", "name": "source",
                **{key: head[key] for key in ("metadata_location", "table_uuid", "snapshot", "schema_id")}}
    assert selector["snapshot"] is not None
    original = {str(path): path.read_bytes() for path in (producer / "data").rglob("*") if path.is_file()}
    metadata = original[selector["metadata_location"]]
    settings = {
        "profile": "whole", "row_group_rows": 64, "order_by": [{"field": "id"}], "columns": [],
        "dictionary_columns": [], "delta_columns": [], "key_column": None,
        "created_by": "DDK independently authored native snapshot fixture", "footer_limit": 65536,
    }
    job = {
        "scratch": str(tmp_path / "caller-scratch"), "inputs": [selector],
        "steps": [{"name": "selected", "sql": "SELECT prefix,id,amount FROM source"}],
        "outputs": [{"name": "observed", "path": str(tmp_path / "unselected.parquet"),
                     "sql": "SELECT * FROM selected", "settings": settings}],
        "queries": [
            {"name": "invariants", "sql": 'SELECT COUNT(*) - 3 AS row_delta FROM outputs."observed"'},
            {"name": "diagnostics", "sql": 'SELECT COUNT(*) AS null_rows FROM outputs."observed" WHERE amount IS NULL'},
        ],
    }
    declared = pa.schema([
        pa.field("prefix", pa.string(), nullable=False, metadata={"PARQUET:field_id": "1"}),
        pa.field("id", pa.int64(), nullable=False, metadata={"PARQUET:field_id": "2"}),
        pa.field("amount", pa.int64(), nullable=True, metadata={"PARQUET:field_id": "3"}),
    ])
    job_artifact = _artifact(tmp_path / "snapshot-job.json", job)
    prepared = runtime.prepare_job({"job": job_artifact, "inputs": [
        {"name": "source", "schema_ipc_base64": base64.b64encode(declared.serialize().to_pybytes()).decode()},
    ]})
    assert prepared["status"] == "succeeded", prepared
    counter = prepared["result"]["queries"][0]
    policy = {
        "id": "snapshot-counts", "profile": COUNTER_PROFILE, "evaluator": COUNTER_EVALUATOR,
        "semantics": COUNTER_SEMANTICS, "job_sha256": job_artifact["sha256"],
        "view_names": {"inputs": ["source"], "steps": ["selected"], "outputs": ["observed"],
                       "reports": ["invariants", "diagnostics"]},
        "required_reports": [{"name": "invariants", "sql_sha256": sha256(job["queries"][0]["sql"].encode()).hexdigest(),
                              "schema_ipc_base64": prepared["result"]["schemas"][counter["schema_sha256"]]}],
    }
    request = {
        "action": "prepare", "dataset": "snapshots", "operation": "original", "definition": "urn:ddk:fixture:native-snapshot:1",
        "job": job_artifact, "file_inputs": [], "snapshot_inputs": [
            {"name": "source", "metadata_sha256": sha256(metadata).hexdigest(), "metadata_size": len(metadata)},
        ], "policy_id": policy["id"], "policy": _artifact(tmp_path / "snapshot-policy.json", policy),
        "expected_epoch": 0, "expected_selection": None, "prerequisites": [],
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace, request, job, policy, producer, original


@pytest.mark.parametrize("cold_partial", [False, True], ids=["complete-original", "missing-payload-recovery"])
def test_native_snapshot_values_ids_and_recovery_use_original_custody(runtime, tmp_path, cold_partial):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    workspace, request, job, policy, producer, original = _snapshot_request(runtime, tmp_path)
    if cold_partial:
        payloads = [Path(path) for path in original if path.endswith(".parquet")]
        assert len(payloads) == 1
        backup = tmp_path / "fixture-payload-backup"
        payloads[0].rename(backup)
        failed = runtime.managed_job(workspace, request)
        assert failed["status"] == "failed", failed
        assert not failed["operation"].get("candidate") and failed["operation"]["selection"] != "selected"
        backup.rename(payloads[0])
        for path in original:
            if not path.endswith(".parquet"):
                Path(path).unlink()
        assert not Path(job["inputs"][0]["metadata_location"]).exists()
        runtime = DocSpecAdapter(runtime.executable, LIMITS, timeout=30, evidence_dir=tmp_path / "cold-retry")
        completed = runtime.managed_job(workspace, request, prior=failed)
    else:
        completed = runtime.managed_job(workspace, request)
    assert completed["status"] == "succeeded", completed
    verified = verify_completed_job(completed["result"])
    assert verified.manifest["profile"] == SNAPSHOT_COMPLETION_PROFILE
    assert verified.admitted_request == request
    view = verified.view_set["inputs"][0]
    assert view["selector"] == job["inputs"][0] and view["files"] == []
    assert sorted(item["role"] for item in view["snapshot_custody"]["objects"]) == ["data", "manifest", "manifest_list", "metadata"]
    for item in view["snapshot_custody"]["objects"]:
        raw = original[item["uri"]]
        assert item["sha256"] == sha256(raw).hexdigest() and item["size"] == len(raw)
        assert item["retained"]["owner"] == "snapshots" and item["origin_operation"] == "original"
        retained = Path(item["retained"]["path"])
        assert retained.is_relative_to(workspace) and retained.read_bytes() == raw
    observed = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(verified.manifest["schemas"][view["schema_sha256"]])))
    assert [(field.name, str(field.type), field.nullable, field.metadata[b"PARQUET:field_id"]) for field in observed] == [
        ("prefix", "string", False, b"1"), ("id", "int64", False, b"2"), ("amount", "int64", True, b"3"),
    ]
    output = completed["result"]["completed_outputs"][0]
    assert output["rows"] == 3 and _rows(pq.read_table(output["path"]).to_pylist()) == _rows(EXPECTED_SNAPSHOT)
    assert not Path(job["outputs"][0]["path"]).exists()
    assert completed["result"]["completed_reports"][1]["data"] == [{"null_rows": 1}]
    accepted = runtime.managed_job(workspace, _action(completed, "accept", policy["id"]), prior=completed)
    assert accepted["status"] == "succeeded", accepted
    verify_completed_job(accepted["result"], require_accepted=True)
    shutil.rmtree(producer)
    for path in (request["job"]["path"], request["policy"]["path"]):
        Path(path).unlink()
    cold = DocSpecAdapter(runtime.executable, LIMITS, timeout=30, evidence_dir=tmp_path / "cold-complete")
    replay = cold.managed_job(workspace, request, prior=accepted)
    assert replay["status"] == "succeeded", replay
    assert replay["result"]["candidate"] == completed["result"]["candidate"]
    assert replay["result"]["completed_reports"] == completed["result"]["completed_reports"]
    assert replay["result"]["accepted_qualification"] == accepted["result"]["accepted_qualification"]
    select = {**_action(completed, "select", policy["id"]),
              "accepted_qualification": accepted["result"]["accepted_qualification"]["identity"]}
    selected = cold.managed_job(workspace, select, prior=replay)
    assert selected["status"] == "succeeded" and selected["operation"]["selection"] == "selected", selected


@pytest.mark.parametrize("changed", ["metadata_sha256", "table_uuid", "schema_id", "snapshot"])
def test_native_snapshot_wrong_original_pin_cannot_create_a_candidate(runtime, tmp_path, changed):
    workspace, request, job, policy, _producer, _original = _snapshot_request(runtime, tmp_path)
    if changed == "metadata_sha256":
        request["snapshot_inputs"][0]["metadata_sha256"] = "0" * 64
    else:
        job["inputs"][0][changed] = {"table_uuid": "00000000-0000-4000-8000-000000000099", "schema_id": 999, "snapshot": None}[changed]
        request["job"] = _artifact(tmp_path / "snapshot-job.json", job)
        policy["job_sha256"] = request["job"]["sha256"]
        request["policy"] = _artifact(tmp_path / "snapshot-policy.json", policy)
    refused = runtime.managed_job(workspace, request)
    assert refused["status"] == "failed", refused
    assert refused["error"]["code"] == ("managed_job_identity" if changed == "metadata_sha256" else "pin_mismatch")
    assert not refused["operation"].get("candidate")
    assert not refused["operation"].get("acceptedQualification")
    assert refused["operation"]["selection"] != "selected"
    assert not Path(job["outputs"][0]["path"]).exists()


@pytest.mark.parametrize("input_name", ["source", "renamed_source"], ids=["same-name", "renamed-input"])
def test_native_snapshot_input_reuse_chain_preserves_original_custody(runtime, tmp_path, input_name):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    workspace, request, job, policy, producer, original = _snapshot_request(runtime, tmp_path)
    donor = runtime.managed_job(workspace, request)
    assert donor["status"] == "succeeded", donor
    donor_evidence = verify_completed_job(donor["result"])
    donor_view = donor_evidence.view_set["inputs"][0]
    donor_reference = donor["result"]["input_custody"][0]
    assert donor_reference == donor_view["custody_reference"]
    original_objects = deepcopy(donor_view["snapshot_custody"]["objects"])
    shutil.rmtree(producer)
    for path in (request["job"]["path"], request["policy"]["path"]):
        Path(path).unlink()

    receiving = deepcopy(request)
    receiving["operation"] = "receiver"
    receiving["snapshot_inputs"][0].update(name=input_name, reuse_from=donor_reference)
    receiver_job = deepcopy(job)
    receiver_job["inputs"][0]["name"] = input_name
    receiver_job["steps"][0]["sql"] = f"SELECT prefix,id,amount FROM {input_name}"
    receiving["job"] = _artifact(tmp_path / "receiver-job.json", receiver_job)
    receiver_policy = deepcopy(policy)
    receiver_policy["job_sha256"] = receiving["job"]["sha256"]
    receiver_policy["view_names"]["inputs"] = [input_name]
    receiving["policy"] = _artifact(tmp_path / "receiver-policy.json", receiver_policy)
    receiver = runtime.managed_job(workspace, receiving)
    assert receiver["status"] == "succeeded", receiver
    checked = verify_completed_job(receiver["result"])
    view = checked.view_set["inputs"][0]
    assert checked.admitted_request == receiving
    assert view["custody_grant"] == {"profile": "urn:docspec:whole-job-input-custody-grant:1", "source": donor_reference}
    assert view["custody_reference"] == receiver["result"]["input_custody"][0]
    assert view["custody_reference"]["operation"] == "receiver" and view["custody_reference"]["input"] == input_name
    assert view["snapshot_custody"]["objects"] == original_objects

    chained = deepcopy(receiving)
    chained["operation"] = "chained"
    chained["snapshot_inputs"][0]["reuse_from"] = receiver["result"]["input_custody"][0]
    final = runtime.managed_job(workspace, chained)
    assert final["status"] == "succeeded", final
    checked = verify_completed_job(final["result"])
    view = checked.view_set["inputs"][0]
    assert view["custody_grant"]["source"] == receiver["result"]["input_custody"][0]
    assert view["snapshot_custody"]["objects"] == original_objects
    assert {member["origin_operation"] for member in original_objects} == {"original"}
    for member in original_objects:
        assert not Path(member["uri"]).exists()
        assert Path(member["retained"]["path"]).read_bytes() == original[member["uri"]]
    observed = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(checked.manifest["schemas"][view["schema_sha256"]])))
    assert [(field.name, str(field.type), field.nullable, field.metadata[b"PARQUET:field_id"]) for field in observed] == [
        ("prefix", "string", False, b"1"), ("id", "int64", False, b"2"), ("amount", "int64", True, b"3"),
    ]
    output = final["result"]["completed_outputs"][0]
    assert output["rows"] == 3 and _rows(pq.read_table(output["path"]).to_pylist()) == _rows(EXPECTED_SNAPSHOT)
    assert final["result"]["completed_reports"][1]["data"] == [{"null_rows": 1}]
    accepted = runtime.managed_job(workspace, _action(final, "accept", receiver_policy["id"]), prior=final)
    assert accepted["status"] == "succeeded", accepted
    verify_completed_job(accepted["result"], require_accepted=True)
    for path in (receiving["job"]["path"], receiving["policy"]["path"]):
        Path(path).unlink()
    cold = DocSpecAdapter(runtime.executable, LIMITS, timeout=30, evidence_dir=tmp_path / "cold-chain")
    replay = cold.managed_job(workspace, chained, prior=accepted)
    assert replay["status"] == "succeeded", replay
    assert replay["result"]["candidate"] == final["result"]["candidate"]
    assert replay["result"]["completed_reports"] == final["result"]["completed_reports"]
    assert replay["result"]["accepted_qualification"] == accepted["result"]["accepted_qualification"]
    select = {**_action(final, "select", receiver_policy["id"]),
              "accepted_qualification": accepted["result"]["accepted_qualification"]["identity"]}
    selected = cold.managed_job(workspace, select, prior=replay)
    assert selected["status"] == "succeeded" and selected["operation"]["selection"] == "selected", selected


@pytest.mark.parametrize("changed", ["table_uuid", "admission_digest", "input"])
def test_native_snapshot_input_reuse_refuses_changed_native_reference(runtime, tmp_path, changed):
    workspace, request, job, _policy, _producer, _original = _snapshot_request(runtime, tmp_path)
    donor = runtime.managed_job(workspace, request)
    assert donor["status"] == "succeeded", donor
    verify_completed_job(donor["result"])
    source = deepcopy(donor["result"]["input_custody"][0])
    if changed == "table_uuid":
        source["native_record"]["table_uuid"] = "00000000-0000-4000-8000-000000000099"
    elif changed == "admission_digest":
        source["admission_digest"]["value"] = "0" * 64
    else:
        source["input"] = "absent"
    receiving = deepcopy(request)
    receiving["operation"] = "refused-receiver"
    receiving["snapshot_inputs"][0]["reuse_from"] = source
    refused = runtime.managed_job(workspace, receiving)
    assert refused["status"] == "failed" and refused["error"]["code"] == "managed_job_identity", refused
    assert not refused["operation"].get("candidate") and not refused["operation"].get("acceptedQualification")
    assert refused["operation"]["selection"] != "selected"
    assert not Path(job["outputs"][0]["path"]).exists()


def _producer_job_policy(runtime, tmp_path, label, job, schemas, *, required_names=("invariants",)):
    """Prepare only schema expectations; business counts below are authored independently."""
    artifact = _artifact(tmp_path / f"{label}-job.json", job)
    response = runtime.prepare_job({"job": artifact, "inputs": [
        {"name": name, "schema_ipc_base64": base64.b64encode(schema.serialize().to_pybytes()).decode()}
        for name, schema in schemas.items()
    ]})
    assert response["status"] == "succeeded", response
    prepared = response["result"]
    required = [query for query in job["queries"] if query["name"] in required_names]
    inferred = {query["name"]: query["schema_sha256"] for query in prepared["queries"]}
    policy = {
        "id": f"{label}-counts", "profile": COUNTER_PROFILE, "evaluator": COUNTER_EVALUATOR,
        "semantics": COUNTER_SEMANTICS, "job_sha256": artifact["sha256"],
        "view_names": {section: [item["name"] for item in job["queries" if section == "reports" else section]]
                       for section in ("inputs", "steps", "outputs", "reports")},
        "required_reports": [{"name": query["name"], "sql_sha256": sha256(query["sql"].encode()).hexdigest(),
                              "schema_ipc_base64": prepared["schemas"][inferred[query["name"]]]}
                             for query in required],
    }
    return artifact, _artifact(tmp_path / f"{label}-policy.json", policy), policy["id"]


def _producer_requests(runtime, tmp_path, *, wrong_counter=False, wrong_producer=False, unrelated_accepted=False):
    """Adopt synthetic producer facts for three original native rows and a pinned lookup.

    These explicitly trusted fixture declarations test native membership checks;
    they do not attest that a historical Git commit wrote the seeded table.
    """
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    workspace, original_request, model_job, _policy, producer, original = _snapshot_request(runtime, tmp_path)
    unrelated = None
    if unrelated_accepted:
        completed = runtime.managed_job(workspace, original_request)
        assert completed["status"] == "succeeded", completed
        unrelated = runtime.managed_job(workspace, _action(completed, "accept", original_request["policy_id"]), prior=completed)
        assert unrelated["status"] == "succeeded", unrelated
        verify_completed_job(unrelated["result"], require_accepted=True)
    declared = pa.schema([
        pa.field("prefix", pa.string(), nullable=False, metadata={"PARQUET:field_id": "1"}),
        pa.field("id", pa.int64(), nullable=False, metadata={"PARQUET:field_id": "2"}),
        pa.field("amount", pa.int64(), nullable=True, metadata={"PARQUET:field_id": "3"}),
    ])
    lookup_schema = pa.schema([pa.field("tag", pa.string(), nullable=False)])
    lookup = tmp_path / "lookup.parquet"
    pq.write_table(pa.Table.from_pylist([{"tag": "approved"}], schema=lookup_schema), lookup)
    lookup_bytes = lookup.read_bytes()
    file_inputs = [{"name": "lookup", "members": [
        {"key": None, "sha256": sha256(lookup_bytes).hexdigest(), "size": len(lookup_bytes)},
    ]}]
    model_job["inputs"].append({"kind": "parquet", "name": "lookup", "path": str(lookup)})
    model_job["steps"][0]["sql"] = "SELECT source.prefix,source.id,source.amount,lookup.tag FROM source CROSS JOIN lookup"
    model_job["queries"].insert(1, {
        "name": "null_invariants", "sql": 'SELECT COUNT(*) - 1 AS missing_delta FROM outputs."observed" WHERE amount IS NULL',
    })
    model_artifact, model_policy, model_policy_id = _producer_job_policy(
        runtime, tmp_path, "producer-model", model_job, {"source": declared, "lookup": lookup_schema},
        required_names=("invariants", "null_invariants"),
    )
    proof_job = {
        "scratch": str(tmp_path / "proof-scratch"), "inputs": [deepcopy(model_job["inputs"][0])],
        "steps": [{"name": "population", "materialize": True,
                   "sql": "SELECT COUNT(*) AS row_count,COUNT(amount) AS present_count,"
                          "SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END) AS null_count FROM source"}],
        "outputs": [],
        "queries": [
            {"name": "invariants", "sql": f"SELECT row_count - {4 if wrong_counter else 3} AS row_delta,"
             "present_count - 2 AS present_delta FROM population"},
            {"name": "diagnostics", "sql": "SELECT null_count AS null_rows FROM population"},
        ],
    }
    proof_artifact, proof_policy, proof_policy_id = _producer_job_policy(
        runtime, tmp_path, "producer-proof", proof_job, {"source": declared},
    )
    selector = {key: value for key, value in model_job["inputs"][0].items() if key != "name"}
    lockfile_digest = sha256(b"independently authored producer dependency identity\n").hexdigest()
    producer_record = _artifact(tmp_path / "original-producer.json", {
        "version": 1, "input": "source", "selector": selector, "job": "jobs/source.json",
        "commit": ("2" if wrong_producer else "1") * 40, "lockfile_digest": lockfile_digest,
    })
    record = {"source": {"namespace": "fixture-original-records", "key": "source-head.json"},
              "sha256": producer_record["sha256"], "size": Path(producer_record["path"]).stat().st_size}
    source_bytes = (tmp_path / "seed-job.json").read_bytes()
    source_pin = {"sha256": sha256(source_bytes).hexdigest(), "size": len(source_bytes)}
    source_blob = sha1(f"blob {len(source_bytes)}\0".encode() + source_bytes).hexdigest()
    metadata_bytes = original[selector["metadata_location"]]
    definition = _artifact(tmp_path / "producer-definition.json", {
        "profile": "urn:docspec:whole-job-producer-definition:1", "definition": original_request["definition"],
        "repository": {"identity": "urn:ddk:fixture:producer-declarations", "head": "1" * 40},
        "interpretation": {"model": {"sha256": model_artifact["sha256"], "size": Path(model_artifact["path"]).stat().st_size},
                           "compatibility_registry": {"sha256": proof_policy["sha256"], "size": Path(proof_policy["path"]).stat().st_size}},
        "proof": {"job_sha256": proof_artifact["sha256"], "policy_id": proof_policy_id, "policy_sha256": proof_policy["sha256"]},
        "model": {"job_sha256": model_artifact["sha256"], "policy_id": model_policy_id, "policy_sha256": model_policy["sha256"]},
        "model_file_inputs": file_inputs,
        "inputs": [{"name": "source", "selector": selector,
                    "metadata": {"sha256": sha256(metadata_bytes).hexdigest(), "size": len(metadata_bytes)},
                    "record_namespace": record["source"]["namespace"], "head_record": record,
                    "import_anchors": [], "daily_jobs": [], "import_jobs": [],
                    "expected_versions": {"lockfile_digest": lockfile_digest}}],
        "producers": [{"input": "source", "commit": "1" * 40, "job": "jobs/source.json", "job_blob": source_blob,
                       "source_files": [{"path": "jobs/source.json", "blob": source_blob, "bytes": source_pin}],
                       "algorithm": "independently-authored-fixture-1", "versions": {"lockfile_digest": lockfile_digest}}],
    })
    adoption_request = _artifact(tmp_path / "producer-adoption.json", {
        "dataset": original_request["dataset"], "adoption": "fixture-producers", "reason": "Independent native consumer fixture",
        "expected_definition": "", "expected_epoch": 0, "expected_selection": None, "expected_adoption": None,
        "definition": definition,
    })
    # Adoption is the trusted native workspace API, separate from ordinary DDK
    # prepare/accept/select calls. DDK adds no adoption or lifecycle authority.
    transport = run_bounded(
        [str(runtime.executable), "--limits", str(tmp_path / "seed-limits.json"), "--workspace", str(workspace),
         "adopt-job-producer-definition", "--spec", adoption_request["path"]],
        timeout=runtime.timeout, limit=runtime.capture_bytes, stop_on_stdout_limit=True,
    )
    (tmp_path / "adoption-stdout.json").write_bytes(transport["stdout"])
    (tmp_path / "adoption-stderr.log").write_bytes(transport["stderr"])
    _artifact(tmp_path / "adoption-transport.json", {key: value for key, value in transport.items() if key not in {"stdout", "stderr"}})
    assert transport["exitCode"] == 0 and not any(transport[key] for key in (
        "timedOut", "cancelled", "stdoutTruncated", "stderrTruncated", "drainIncomplete",
    )), transport
    adoption = json.loads(transport["stdout"])
    assert adoption["definition_sha256"] == definition["sha256"]
    proof = {**deepcopy(original_request), "operation": "producer-proof", "job": proof_artifact,
             "policy": proof_policy, "policy_id": proof_policy_id, "producer_adoption": adoption,
             "producer_records": [{**record, "path": producer_record["path"]}]}
    model = {**deepcopy(original_request), "operation": "producer-model", "job": model_artifact,
             "policy": model_policy, "policy_id": model_policy_id, "producer_adoption": adoption, "file_inputs": file_inputs}
    return {"workspace": workspace, "proof": proof, "model": model, "model_job": model_job,
            "producer": producer, "original": original, "definition": definition, "adoption_request": adoption_request,
            "record": producer_record, "lookup": lookup, "unrelated": unrelated}


def _producer_model_request(fixture, proof, accepted_identity):
    request = deepcopy(fixture["model"])
    request["prerequisites"] = [{
        "profile": PRODUCER_PREREQUISITE_PROFILE, "candidate": proof["result"]["candidate"],
        "accepted_qualification": accepted_identity, "inputs": ["source"],
    }]
    request["snapshot_inputs"][0]["reuse_from"] = proof["result"]["input_custody"][0]
    return request


def _accepted_producer_proof(runtime, fixture):
    proof = runtime.managed_job(fixture["workspace"], fixture["proof"])
    assert proof["status"] == "succeeded", proof
    checked = verify_completed_job(proof["result"])
    assert checked.manifest["profile"] == PRODUCER_COMPLETION_PROFILE
    assert checked.manifest["producer_evidence"]["role"] == "proof"
    assert proof["result"]["completed_outputs"] == []
    assert proof["result"]["completed_reports"][0]["data"] == [{"row_delta": 0, "present_delta": 0}]
    assert proof["result"]["completed_reports"][1]["data"] == [{"null_rows": 1}]
    accepted = runtime.managed_job(fixture["workspace"], _action(proof, "accept", fixture["proof"]["policy_id"]), prior=proof)
    assert accepted["status"] == "succeeded", accepted
    verify_completed_job(accepted["result"], require_accepted=True)
    return accepted


def test_native_producer_proof_model_and_cold_replay_preserve_original_evidence(runtime, tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    fixture = _producer_requests(runtime, tmp_path)
    workspace = fixture["workspace"]
    accepted_proof = _accepted_producer_proof(runtime, fixture)
    identity = accepted_proof["result"]["accepted_qualification"]["identity"]
    proof_select = {**_action(accepted_proof, "select", fixture["proof"]["policy_id"]), "accepted_qualification": identity}
    refused = runtime.managed_job(workspace, proof_select, prior=accepted_proof)
    assert refused["status"] == "failed" and refused["error"]["code"] == "producer_proof_not_selectable", refused
    assert refused["operation"]["selection"] != "selected"
    model_request = _producer_model_request(fixture, accepted_proof, identity)
    original_objects = verify_completed_job(accepted_proof["result"]).view_set["inputs"][0]["snapshot_custody"]["objects"]
    shutil.rmtree(fixture["producer"])
    for artifact in (fixture["proof"]["job"], fixture["proof"]["policy"], fixture["record"],
                     fixture["definition"], fixture["adoption_request"]):
        Path(artifact["path"]).unlink()
    # Missing file bytes interrupt work after native admission. The returned
    # witness establishes that boundary; an arbitrary failure would not.
    backup = tmp_path / "lookup-original.bin"
    fixture["lookup"].rename(backup)
    interrupted = runtime.managed_job(workspace, model_request)
    assert interrupted["status"] == "failed", interrupted
    partial = interrupted["result"]
    assert partial["status"] == "failed" and partial["candidate"] is None
    assert partial["operation"] == model_request["operation"] and partial["request_digest"]
    witness = partial["admitted_request"]
    admitted_bytes = base64.b64decode(witness["bytes_base64"], validate=True)
    assert sha256(admitted_bytes).hexdigest() == witness["sha256"]
    assert len(admitted_bytes) == witness["reference"]["bytes"] and json.loads(admitted_bytes) == model_request
    backup.rename(fixture["lookup"])
    retry_runtime = DocSpecAdapter(runtime.executable, LIMITS, timeout=30, evidence_dir=tmp_path / "cold-producer-retry")
    model = retry_runtime.managed_job(workspace, model_request, prior=interrupted)
    assert model["status"] == "succeeded", model
    assert model["result"]["request_digest"] == partial["request_digest"]
    assert model["result"]["admitted_request"] == witness
    checked = verify_completed_job(model["result"])
    assert checked.manifest["profile"] == PRODUCER_COMPLETION_PROFILE
    assert checked.admitted_request == model_request
    evidence = checked.manifest["producer_evidence"]
    assert evidence["role"] == "model" and evidence["prerequisite"] == model_request["prerequisites"][0]
    view = checked.view_set["inputs"][0]
    assert view["snapshot_custody"]["objects"] == original_objects
    assert view["custody_grant"]["source"] == accepted_proof["result"]["input_custody"][0]
    for item in original_objects:
        assert not Path(item["uri"]).exists()
        assert Path(item["retained"]["path"]).read_bytes() == fixture["original"][item["uri"]]
    observed = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(checked.manifest["schemas"][view["schema_sha256"]])))
    assert [(field.name, str(field.type), field.nullable, field.metadata[b"PARQUET:field_id"]) for field in observed] == [
        ("prefix", "string", False, b"1"), ("id", "int64", False, b"2"), ("amount", "int64", True, b"3"),
    ]
    output = model["result"]["completed_outputs"][0]
    expected = [
        {"prefix": "snapshot", "id": 1, "amount": 7, "tag": "approved"},
        {"prefix": "snapshot", "id": 2, "amount": None, "tag": "approved"},
        {"prefix": "snapshot", "id": 3, "amount": -5, "tag": "approved"},
    ]
    assert output["rows"] == 3 and _rows(pq.read_table(output["path"]).to_pylist()) == _rows(expected)
    assert not Path(fixture["model_job"]["outputs"][0]["path"]).exists()
    accepted_model = runtime.managed_job(workspace, _action(model, "accept", model_request["policy_id"]), prior=model)
    assert accepted_model["status"] == "succeeded", accepted_model
    verify_completed_job(accepted_model["result"], require_accepted=True)
    for path in (model_request["job"]["path"], model_request["policy"]["path"], fixture["lookup"]):
        Path(path).unlink()
    cold = DocSpecAdapter(runtime.executable, LIMITS, timeout=30, evidence_dir=tmp_path / "cold-producer-model")
    replay = cold.managed_job(workspace, model_request, prior=accepted_model)
    assert replay["status"] == "succeeded", replay
    assert replay["result"]["candidate"] == model["result"]["candidate"]
    assert replay["result"]["completed_reports"] == model["result"]["completed_reports"]
    assert replay["result"]["accepted_qualification"] == accepted_model["result"]["accepted_qualification"]
    assert verify_completed_job(replay["result"], require_accepted=True).manifest == checked.manifest
    select = {**_action(model, "select", model_request["policy_id"]),
              "accepted_qualification": accepted_model["result"]["accepted_qualification"]["identity"]}
    selected = cold.managed_job(workspace, select, prior=replay)
    assert selected["status"] == "succeeded" and selected["operation"]["selection"] == "selected", selected


def test_native_producer_model_requires_actual_accepted_zero_counter_proof(runtime, tmp_path):
    fixture = _producer_requests(runtime, tmp_path, wrong_counter=True)
    workspace = fixture["workspace"]
    proof = runtime.managed_job(workspace, fixture["proof"])
    assert proof["status"] == "succeeded", proof
    verify_completed_job(proof["result"])
    assert proof["result"]["completed_reports"][0]["data"] == [{"row_delta": -1, "present_delta": 0}]
    assert proof["result"]["completed_reports"][1]["data"] == [{"null_rows": 1}]
    rejected = runtime.managed_job(workspace, _action(proof, "accept", fixture["proof"]["policy_id"]), prior=proof)
    assert rejected["status"] == "failed" and rejected["error"]["code"] == "job_report_failed", rejected
    assert rejected["result"]["candidate"] == proof["result"]["candidate"]
    assert rejected["result"]["accepted_qualification"] is None
    request = _producer_model_request(fixture, proof, "0" * 64)
    refused = runtime.managed_job(workspace, request)
    assert refused["status"] == "failed" and refused["error"]["code"] == "producer_prerequisite_unaccepted", refused
    assert not refused["operation"].get("candidate") and not refused["operation"].get("acceptedQualification")
    assert refused["operation"]["selection"] != "selected"
    assert not Path(fixture["model_job"]["outputs"][0]["path"]).exists()


def test_native_producer_original_membership_is_checked_before_payload_copy(runtime, tmp_path):
    fixture = _producer_requests(runtime, tmp_path, wrong_producer=True)
    # The record byte pin is correct. Only its original producer commit is outside
    # the adopted inventory; a missing payload must not hide that static refusal.
    payloads = [Path(path) for path in fixture["original"] if path.endswith(".parquet")]
    assert len(payloads) == 1
    payloads[0].unlink()
    refused = runtime.managed_job(fixture["workspace"], fixture["proof"])
    assert refused["status"] == "failed" and refused["error"]["code"] == "producer_record_mismatch", refused
    assert not refused["operation"].get("candidate") and not refused["operation"].get("acceptedQualification")
    assert refused["operation"]["selection"] != "selected"


def test_native_producer_model_file_inventory_is_checked_before_file_open(runtime, tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    fixture = _producer_requests(runtime, tmp_path)
    proof = _accepted_producer_proof(runtime, fixture)
    request = _producer_model_request(fixture, proof, proof["result"]["accepted_qualification"]["identity"])
    pq.write_table(pa.table({"tag": ["changed"]}), fixture["lookup"])
    changed = fixture["lookup"].read_bytes()
    request["file_inputs"][0]["members"][0].update(sha256=sha256(changed).hexdigest(), size=len(changed))
    fixture["lookup"].unlink()
    refused = runtime.managed_job(fixture["workspace"], request)
    assert refused["status"] == "failed" and refused["error"]["code"] == "producer_file_inventory_mismatch", refused
    assert not refused["operation"].get("candidate") and not refused["operation"].get("acceptedQualification")
    assert refused["operation"]["selection"] != "selected"
    assert not Path(fixture["model_job"]["outputs"][0]["path"]).exists()


def test_native_producer_model_refuses_an_unrelated_actual_accepted_candidate(runtime, tmp_path):
    fixture = _producer_requests(runtime, tmp_path, unrelated_accepted=True)
    unrelated = fixture["unrelated"]
    request = _producer_model_request(fixture, unrelated, unrelated["result"]["accepted_qualification"]["identity"])
    refused = runtime.managed_job(fixture["workspace"], request)
    assert refused["status"] == "failed" and refused["error"]["code"] == "producer_prerequisite_mismatch", refused
    assert not refused["operation"].get("candidate") and not refused["operation"].get("acceptedQualification")
    assert refused["operation"]["selection"] != "selected"
    assert not Path(fixture["model_job"]["outputs"][0]["path"]).exists()


def test_native_producer_model_refuses_a_weaker_fixed_policy(runtime, tmp_path):
    fixture = _producer_requests(runtime, tmp_path)
    proof = _accepted_producer_proof(runtime, fixture)
    request = _producer_model_request(fixture, proof, proof["result"]["accepted_qualification"]["identity"])
    weaker = json.loads(Path(request["policy"]["path"]).read_bytes())
    assert [report["name"] for report in weaker["required_reports"]] == ["invariants", "null_invariants"]
    weaker["required_reports"] = weaker["required_reports"][:1]
    request["policy"] = _artifact(tmp_path / "weaker-model-policy.json", weaker)
    fixture["lookup"].unlink()
    refused = runtime.managed_job(fixture["workspace"], request)
    assert refused["status"] == "failed" and refused["error"]["code"] == "producer_policy_mismatch", refused
    assert not refused["operation"].get("candidate") and not refused["operation"].get("acceptedQualification")
    assert refused["operation"]["selection"] != "selected"
    assert not Path(fixture["model_job"]["outputs"][0]["path"]).exists()
