"""Exact multi-file custody through the public bounded DocSpec adapter."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddk.adapters import docspec
from ddk.adapters.docspec import DocSpecAdapter


LIMITS = {
    "compute_threads": 2, "memory_bytes": 128 << 20, "scratch_bytes": 16 << 20,
    "batch_rows": 128, "max_batch_bytes": 2 << 20, "max_metadata_bytes": 2 << 20,
}


def _write(path, ids, amounts):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"id": pa.array(ids, pa.int64()), "amount": pa.array(amounts, pa.int64())}), path)


def _pins(directory):
    members = []
    for path in sorted(directory.rglob("*.parquet")):
        raw = path.read_bytes()
        members.append([path.relative_to(directory).as_posix(), sha256(raw).hexdigest(), len(raw)])
    # Independently encode DocSpec's published directory inventory algorithm.
    digest = sha256(json.dumps(members, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {str(directory): digest, **{str(directory / path): digest for path, digest, _size in members}}


@pytest.fixture
def directory_job(tmp_path):
    directory = tmp_path / "parts"
    _write(directory / "one.parquet", [1, 3], [7, 11])
    _write(directory / "two-β.parquet", [2, 4], [5, 13])
    request = {
        "id": "urn:example:job:multi-file", "scratch": str(tmp_path / "scratch"),
        "inputs": [{"kind": "parquet", "name": "items", "path": str(directory)}],
        "steps": [], "outputs": [],
        "queries": [{"name": "answer", "sql": "SELECT id, amount FROM items ORDER BY id"}],
    }
    return directory, request, _pins(directory)


@pytest.fixture
def native(tmp_path):
    binary = os.environ.get("DDK_DOCSPEC_BINARY") or os.environ.get("DDK_DOCSPEC_BIN")
    assert binary, "Select the pinned DocSpec executable to run multi-file acceptance tests"
    return DocSpecAdapter(binary, LIMITS, evidence_dir=tmp_path / "evidence")


def test_native_query_reads_both_members_and_preserves_exact_inventory(native, directory_job):
    directory, request, pins = directory_job
    response = native.execute(request, input_digests=pins)
    assert response["status"] == "succeeded", response
    assert response["result"]["queries"][0]["data"] == [
        {"id": 1, "amount": 7}, {"id": 2, "amount": 5},
        {"id": 3, "amount": 11}, {"id": 4, "amount": 13},
    ]
    observed = response["result"]["inputs"][0]
    assert observed["sha256"] == pins[str(directory)]
    assert len(observed["files"]) == 2
    assert observed["bytes"] == sum(Path(item["path"]).stat().st_size for item in observed["files"])
    assert {item["path"]: item["sha256"] for item in observed["files"]} == {
        path: digest for path, digest in pins.items() if path != str(directory)
    }
    assert response["operation"]["execution"] == "succeeded"
    assert response["operation"]["reconciliation"] == "unsupported"


@pytest.mark.parametrize("pin_kind", ["root", "members", "observed"])
def test_native_directory_accepts_inventory_pin_or_complete_member_pins(native, directory_job, pin_kind):
    directory, request, pins = directory_job
    selected = ({str(directory): pins[str(directory)]} if pin_kind == "root" else
                {path: digest for path, digest in pins.items() if path != str(directory)} if pin_kind == "members" else None)
    response = native.execute(request, input_digests=selected)
    assert response["status"] == "succeeded", response
    assert len(response["result"]["queries"][0]["data"]) == 4


@pytest.mark.parametrize("change", ["missing", "extra", "changed", "root_digest", "partial_pins", "anonymous", "link", "empty", "zero_bytes", "uppercase", "limit"])
def test_directory_admission_refuses_incomplete_or_changed_pins_before_execution(tmp_path, directory_job, monkeypatch, change):
    directory, request, pins = directory_job
    first = directory / "one.parquet"
    adapter = DocSpecAdapter(sys.executable, LIMITS, evidence_dir=tmp_path / "evidence")

    def must_not_run(*_args, **_kwargs):
        pytest.fail("Refused directory input reached native execution")

    monkeypatch.setattr(docspec, "run_bounded", must_not_run)
    if change == "missing":
        first.unlink()
    elif change == "extra":
        _write(directory / "extra.parquet", [9], [99])
    elif change == "changed":
        _write(first, [1], [700])
    elif change == "root_digest":
        pins[str(directory)] = "0" * 64
    elif change == "partial_pins":
        pins = {str(first): pins[str(first)]}
    elif change == "anonymous":
        request.pop("id")
    elif change == "link":
        (directory / "linked.parquet").symlink_to(first)
    elif change == "empty":
        for path in directory.rglob("*.parquet"):
            path.unlink()
    elif change == "zero_bytes":
        first.write_bytes(b"")
    elif change == "uppercase":
        first.rename(first.with_suffix(".PARQUET"))
    elif change == "limit":
        adapter.metadata_bytes = 100
    response = adapter.execute(request, input_digests=pins)
    assert response["status"] == "not_submitted", response
    assert response["operation"]["execution"] == "not_submitted"
    assert response["result"] == {}
    assert not Path(request["scratch"]).exists()


def test_nested_directory_refuses_before_native_can_omit_its_rows(tmp_path, directory_job, monkeypatch):
    directory, request, _old_pins = directory_job
    nested = directory / "nested"
    nested.mkdir()
    (directory / "two-β.parquet").rename(nested / "two-β.parquet")
    adapter = DocSpecAdapter(sys.executable, LIMITS, evidence_dir=tmp_path / "evidence")

    def must_not_run(*_args, **_kwargs):
        pytest.fail("Nested scope reached the native reader that omits nested rows")

    monkeypatch.setattr(docspec, "run_bounded", must_not_run)
    response = adapter.execute(request, input_digests=_pins(directory))
    assert response["status"] == "not_submitted"
    assert response["error"]["code"] == "DOCSPEC-PARQUET-DIRECTORY-SCOPE"
    assert "nested" in response["error"]["message"]
    assert not Path(request["scratch"]).exists()


@pytest.mark.parametrize("change", ["missing", "extra", "changed"])
def test_directory_changed_during_native_execution_preserves_unknown(native, directory_job, monkeypatch, change):
    directory, request, pins = directory_job
    run = docspec.run_bounded

    def mutate_after_native(*args, **kwargs):
        result = run(*args, **kwargs)
        assert result["exitCode"] == 0
        if change == "missing":
            (directory / "one.parquet").unlink()
        elif change == "extra":
            _write(directory / "extra.parquet", [9], [99])
        else:
            _write(directory / "one.parquet", [1, 3], [70, 110])
        return result

    monkeypatch.setattr(docspec, "run_bounded", mutate_after_native)
    response = native.execute(request, input_digests=pins)
    assert response["status"] == "unknown", response
    assert response["error"]["code"] == "DOCSPEC-INPUT-CHANGED"
    assert response["result"] == {}
    assert response["receipt"]["unverifiedResult"]["queries"][0]["data"][0] == {"id": 1, "amount": 7}
    assert response["operation"]["execution"] == "unknown"
    assert response["operation"]["outputs"] == []


@pytest.mark.parametrize("change", ["missing", "extra", "changed", "outside", "total", "duplicate", "unobserved"])
def test_mismatched_native_directory_receipt_is_unknown(native, directory_job, monkeypatch, change):
    _directory, request, pins = directory_job
    run = docspec.run_bounded

    def alter_native_receipt(*args, **kwargs):
        result = run(*args, **kwargs)
        body = json.loads(result["stdout"])
        observed = body["inputs"][0]
        if change == "missing":
            observed["files"].pop()
        elif change == "extra":
            observed["files"].append({**observed["files"][0], "path": observed["path"] + "/z.parquet"})
        elif change == "changed":
            observed["files"][0]["sha256"] = "0" * 64
        elif change == "outside":
            observed["files"][0]["path"] = "/outside.parquet"
        elif change == "total":
            observed["bytes"] += 1
        elif change == "duplicate":
            body["inputs"].append(deepcopy(observed))
        elif change == "unobserved":
            body["inputs"] = []
        result["stdout"] = json.dumps(body).encode()
        return result

    monkeypatch.setattr(docspec, "run_bounded", alter_native_receipt)
    response = native.execute(request, input_digests=pins)
    assert response["status"] == "unknown", response
    assert response["result"] == {}
    assert "unverifiedResult" in response["receipt"]
    assert response["operation"]["execution"] == "unknown"


def test_known_sql_failure_keeps_verified_directory_inputs(native, directory_job):
    _directory, request, pins = directory_job
    request["queries"][0]["sql"] = "SELECT absent_column FROM items"
    response = native.execute(request, input_digests=pins)
    assert response["status"] == "failed", response
    assert len(response["result"]["inputs"][0]["files"]) == 2
    assert response["operation"]["execution"] == "failed"


def test_valid_empty_members_remain_successful_empty(native, directory_job):
    directory, request, _pins_before = directory_job
    for path in directory.rglob("*.parquet"):
        _write(path, [], [])
    response = native.execute(request, input_digests=_pins(directory))
    assert response["status"] == "succeeded", response
    assert response["result"]["queries"][0]["data"] == []
    assert len(response["result"]["inputs"][0]["files"]) == 2
