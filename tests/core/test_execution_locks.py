"""Retained staged-file evidence and stable locked result comparisons."""

from copy import deepcopy
from hashlib import sha256
import json

from ddk.documents import validate_document
from ddk.locks import lock_project, verify_execution_inputs
from ddk.results import exit_code, stable_report

from test_core import check, codes, commerce, selected_development_identity


def _file(path, data):
    path.write_bytes(data)
    return {"path": str(path), "sha256": sha256(data).hexdigest()}


def test_changed_staged_file_blocks_reused_saved_plan_evidence(tmp_path):
    orders = _file(tmp_path / "orders.parquet", b"first staged snapshot")
    customers = _file(tmp_path / "customers.parquet", b"independent customer snapshot")
    plan = _file(tmp_path / "saved.substrait", b"retained opaque saved calculation bytes")
    request = _file(tmp_path / "request.json", b'{"parameters":{"year":2026}}')
    tool = {"id": "docspec", "version": "0.1.0", "distributionSha256": "f" * 64}
    inputs = [
        {**orders, "name": "orders", "format": "parquet"},
        {**customers, "name": "customers", "format": "parquet"},
        {**plan, "name": "result", "format": "substrait"},
    ]
    receipt = tmp_path / "native-receipt.json"
    receipt.write_text(json.dumps({"status": "succeeded", "inputs": inputs, "request": request, "tool": tool}))
    accepted = verify_execution_inputs(receipt, current_inputs=list(reversed(inputs)), expected_tool=tool)
    assert accepted["decision"] == "passed"
    assert not validate_document(accepted)
    (tmp_path / "orders.parquet").write_bytes(b"later content with the same staged filename")
    refused = verify_execution_inputs(receipt, current_inputs=inputs, expected_tool=tool)
    assert refused["decision"] == "failed" and exit_code(refused) == 1
    assert "LOCK-EXECUTION-INPUT-MISMATCH" in codes(refused)
    issues = refused["checks"][0]["diagnostics"]
    assert [item["location"]["pointer"] for item in issues] == ["/inputs/0"]


def test_locked_stable_results_ignore_inventory_order_and_volatile_observations(commerce, selected_development_identity):
    result, lock = lock_project(commerce / "project.ddk.json")
    assert result["decision"] == "passed"
    first = check(commerce, "passed", locked=True, lock=lock)
    shuffled = deepcopy(lock)
    shuffled["files"].reverse()
    second = check(commerce, "passed", locked=True, lock=shuffled)
    first.setdefault("metadata", {})["volatile"] = {"observedAt": "2026-11-05T12:00:00Z", "elapsedMs": 23}
    second.setdefault("metadata", {})["volatile"] = {"observedAt": "2026-11-05T12:01:00Z", "elapsedMs": 37}
    assert first != second
    assert stable_report(first) == stable_report(second)
    assert first["metadata"]["volatile"]["elapsedMs"] == 23
