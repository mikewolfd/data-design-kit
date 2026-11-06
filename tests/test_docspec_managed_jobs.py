"""Independent whole-job conformance through the actual native subprocess."""

import base64
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.docspec_job_evidence import COUNTER_EVALUATOR, COUNTER_PROFILE, COUNTER_SEMANTICS, verify_completed_job


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
    {"id": 1, "customer": 10, "amount": 100},
    {"id": 1, "customer": 10, "amount": 100},
    {"id": 3, "customer": 20, "amount": None},
    {"id": 4, "customer": 99, "amount": -25},
    {"id": 5, "customer": 30, "amount": 0},
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
    if wrong_counter:
        job["queries"][0]["sql"] = "SELECT COUNT(*) - 4 AS row_delta FROM joined"
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
