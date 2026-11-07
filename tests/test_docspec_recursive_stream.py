"""Complete recursive IPC observations and unchanged native source protocol."""

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import pytest

from ddk.adapters.docspec import DocSpecAdapter, native_version
from ddk.adapters.docspec_schema import RECURSIVE_PROFILE, source_arrow_schema
from ddk.adapters.docspec_stream import ExactVersionStream, NativeStreamError, StreamLimits

from test_docspec_schema import nested_schema, schema, version

pa = pytest.importorskip("pyarrow")
LIMITS = StreamLimits(timeout=5)


def producer(tmp_path, mutation=None, *, raw_schema=None, arrow_override=None):
    original = schema() if raw_schema is None else raw_schema
    arrow = source_arrow_schema(original, pa) if arrow_override is None else arrow_override
    values = [None, [], [None, {"code": None}, {"code": 9007199254740993}, {"code": 9007199254740993}]]
    rows = [{"id": i, "groups": group} for i, group in enumerate(values)]
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, arrow) as writer:
        for row in rows:
            writer.write_table(pa.Table.from_pylist([row], schema=arrow))
    payload = sink.getvalue().to_pybytes()
    claimed = deepcopy(original)
    child = claimed["fields"][1]["data_type"]["List"] if mutation else None
    if mutation == "item-nullability":
        child["nullable"] = False
    elif mutation == "child-id":
        child["data_type"]["Struct"][0]["metadata"]["PARQUET:field_id"] = "19"
    elif mutation == "nested-type":
        child["data_type"]["Struct"][0]["data_type"] = "Int32"
    elif mutation == "nested-metadata":
        child["metadata"]["unexpected"] = "changed"
    elif mutation == "column-order":
        claimed["fields"][0], claimed["fields"][1] = claimed["fields"][1], claimed["fields"][0]
    executable = tmp_path / "producer.py"
    executable.write_text(f'''#!{sys.executable}
import json, pathlib, sys
request=json.loads(pathlib.Path(sys.argv[sys.argv.index('--spec')+1]).read_text())
sys.stdout.buffer.write({payload!r})
sys.stdout.buffer.flush()
receipt={{'read_id':'acde0000-0000-4000-8000-000000000001','version':request['version'],
         'schema_id':3,'schema':{claimed!r},'rows':3,'ipc_sha256':{sha256(payload).hexdigest()!r}}}
pathlib.Path(request['receipt_path']).write_text(json.dumps(receipt))
''')
    executable.chmod(0o755)
    adapter = DocSpecAdapter(executable, {}, timeout=5, evidence_dir=tmp_path / "evidence",
                             native_mapping_profile=RECURSIVE_PROFILE)
    return adapter, rows


def test_all_batches_and_recursive_receipt_are_required(tmp_path):
    adapter, rows = producer(tmp_path)
    with ExactVersionStream(adapter, tmp_path, version(tmp_path), limits=LIMITS) as stream:
        observed = [row for batch in stream for row in batch.to_pylist()]
        completed = stream.finish()
    assert [row["groups"] for row in observed] == [row["groups"] for row in rows]
    assert completed["nativeRead"]["profile"] == RECURSIVE_PROFILE
    assert completed["result"]["rows"] == 3
    assert len(completed["nativeRead"]["fields"]) == 8
    assert completed["nativeRead"]["schema"] == schema()


@pytest.mark.parametrize("mutation", ["item-nullability", "child-id", "nested-type", "nested-metadata", "column-order"])
def test_complete_stream_cannot_accept_a_different_recursive_receipt(tmp_path, mutation):
    adapter, _ = producer(tmp_path, mutation)
    with ExactVersionStream(adapter, tmp_path, version(tmp_path), limits=LIMITS) as stream:
        for _ in stream:
            pass
        with pytest.raises(NativeStreamError, match="schema"):
            stream.finish()
    assert stream.result is None


def test_depth_limit_survives_both_ipc_setup_and_receipt_completion(tmp_path):
    from ddk.adapters.docspec_schema import MAX_DEPTH
    adapter, _ = producer(tmp_path, raw_schema=nested_schema(MAX_DEPTH))
    with ExactVersionStream(adapter, tmp_path, version(tmp_path), limits=LIMITS) as stream:
        for _ in stream:
            pass
        result = stream.finish()
    assert len(result["nativeRead"]["fields"]) == MAX_DEPTH


def test_depth_beyond_profile_is_refused_during_ipc_setup(tmp_path):
    from ddk.adapters.docspec_schema import MAX_DEPTH
    depth = MAX_DEPTH + 1
    node = pa.field("value", pa.int64(), metadata={b"PARQUET:field_id": str(depth).encode()})
    for identifier in reversed(range(1, depth)):
        node = pa.field("element" if identifier > 1 else "nested", pa.list_(node),
                        metadata={b"PARQUET:field_id": str(identifier).encode()})
    adapter, _ = producer(tmp_path, raw_schema=nested_schema(depth), arrow_override=pa.schema([node]))
    with pytest.raises(NativeStreamError, match="bound"):
        with ExactVersionStream(adapter, tmp_path, version(tmp_path), limits=LIMITS):
            pytest.fail("Unsupported schema reached data reading")


def test_actual_native_nested_source_read(tmp_path):
    binary = os.environ.get("DDK_STREAM_NATIVE_BINARY")
    if not binary:
        pytest.skip("Set DDK_STREAM_NATIVE_BINARY to the qualified local DocSpec executable")
    import pyarrow.parquet as pq
    settings = {"compute_threads": 1, "memory_bytes": 128 << 20, "scratch_bytes": 32 << 20,
                "batch_rows": 2, "max_batch_bytes": 1 << 20, "max_metadata_bytes": 2 << 20}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    arrow = source_arrow_schema(schema(), pa)
    rows = [{"id": 9007199254740993, "groups": None}, {"id": 2, "groups": []},
            {"id": 3, "groups": [None, {"code": None}, {"code": 9007199254740993}, {"code": 9007199254740993}]}]
    for row in rows:
        row.update(digest=b"\x00\x7f\x80\xff", observed_at=datetime(2026, 11, 6, 12, 30, 5, 123456, timezone.utc),
                   amount=Decimal("18446744073709551615"), day=date(2026, 11, 6))
    data, spec, limits = (tmp_path / name for name in ("rows.parquet", "build.json", "limits.json"))
    pq.write_table(pa.Table.from_pylist(rows, schema=arrow), data)
    digest = json.loads(subprocess.check_output([binary, "hash", "--input", str(data)]))["digest"]
    limits.write_text(json.dumps(settings))
    spec.write_text(json.dumps({"dataset": "records", "operation": "candidate", "input": str(data),
                               "expected_digest": digest, "sql": "SELECT * FROM input", "definition": "recursive-v2"}))
    release = json.loads(subprocess.check_output([binary, "--workspace", str(workspace), "--limits", str(limits),
                                                 "run", "--spec", str(spec)]))
    selected = native_version(workspace, {"dataset": "records", "version": "candidate", "manifest": release["manifest"]})
    adapter = DocSpecAdapter(binary, settings, timeout=10, evidence_dir=tmp_path / "evidence",
                             native_mapping_profile=RECURSIVE_PROFILE,
                             source_commit=os.environ.get("DDK_DOCSPEC_SOURCE_COMMIT"))
    inspection = adapter.inspect_version(workspace, selected)
    assert inspection["status"] == "succeeded", inspection
    physical = inspection["result"]["native_versions"][0]["physical_snapshot"]
    selector = physical["selector"]
    parsed = urlsplit(selector["metadata_location"])
    metadata_path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(selector["metadata_location"])
    stored_metadata = metadata_path.read_bytes()
    metadata = json.loads(stored_metadata)
    assert physical["metadata_sha256"] == sha256(stored_metadata).hexdigest()
    assert physical["metadata_size"] == len(stored_metadata)
    assert selector["table_uuid"] == metadata["table-uuid"]
    assert selector["snapshot"] == metadata["current-snapshot-id"]
    assert selector["schema_id"] == metadata["current-schema-id"]
    assert inspection["nativeReads"][0]["version"] == selected
    with ExactVersionStream(adapter, workspace, selected, limits=StreamLimits(timeout=10)) as stream:
        observed = [row for batch in stream for row in batch.to_pylist()]
        result = stream.finish()
    evidence = os.environ.get("DDK_NATIVE_SHAPE_EVIDENCE")
    if evidence:
        Path(evidence).write_text(json.dumps({"version": selected, "result": result,
                                             "runtime": adapter.tool, "executable": str(adapter.executable),
                                             "observed": observed}, indent=2, default=str) + "\n")
    assert sorted((row["id"], row["groups"]) for row in observed) == sorted((row["id"], row["groups"]) for row in rows)
    assert sorted(observed, key=lambda row: row["id"]) == sorted(rows, key=lambda row: row["id"])
    assert result["nativeRead"]["version"] == selected
    # Native admission assigns all root IDs before descending into list items.
    # Incoming Parquet IDs are original metadata, not this native identity.
    assert result["nativeRead"]["fields"][3]["nativeFieldPath"] == [2, 7, 8]
    assert result["result"]["rows"] == 3
    assert result["nativeRead"]["schema"]["fields"][1]["data_type"]["List"]["nullable"] is True
    assert inspection["nativeReads"][0] == result["nativeRead"]
    cold = DocSpecAdapter(binary, settings, timeout=10, evidence_dir=tmp_path / "cold-evidence",
                          native_mapping_profile=RECURSIVE_PROFILE)
    repeated = cold.inspect_version(workspace, selected)
    assert repeated["status"] == "succeeded", repeated
    assert repeated["result"]["native_versions"] == inspection["result"]["native_versions"]
    try:
        metadata_path.write_bytes(stored_metadata + b"\n")
        refused = cold.inspect_version(workspace, selected)
        assert refused["status"] == "failed", refused
        assert refused["error"]["code"] == "corrupt_object"
        assert not refused.get("nativeReads")
    finally:
        metadata_path.write_bytes(stored_metadata)
