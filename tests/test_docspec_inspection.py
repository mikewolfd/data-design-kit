"""Exact native metadata admission and independent refusal controls."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.adapters.docspec_schema import RECURSIVE_PROFILE, validate_physical_snapshot
from test_docspec_schema import schema, version


@pytest.fixture
def simulated(tmp_path):
    reply = tmp_path / "reply.json"
    executable = tmp_path / "native"
    executable.write_text(f"#!{sys.executable}\nimport pathlib,sys\n"
                          f"sys.stdout.write(pathlib.Path({str(reply)!r}).read_text())\n")
    executable.chmod(0o755)
    adapter = DocSpecAdapter(executable, {}, evidence_dir=tmp_path / "evidence",
                             native_mapping_profile=RECURSIVE_PROFILE)
    selected = version(tmp_path)
    observation = {"name": "source", "version": selected["reference"], "schema_id": 3, "schema": schema()}
    body = {"native_versions": [observation], "steps": [], "outputs": [], "queries": []}
    return adapter, selected, reply, body


def test_inspection_keeps_exact_reference_and_recursive_schema(simulated, tmp_path):
    adapter, selected, reply, body = simulated
    reply.write_text(json.dumps(body))
    actual = adapter.inspect_version(tmp_path, selected)
    assert actual["status"] == "succeeded"
    assert actual["nativeReads"][0]["version"] == selected
    assert actual["nativeReads"][0]["schema"] == schema()
    assert actual["nativeReads"][0]["fields"][3]["nativeFieldPath"] == [2, 3, 4]
    folder = Path(actual["receipt"]["request"]["path"]).parent
    submitted = json.loads((folder / "native-request.json").read_bytes())
    assert submitted["inputs"] == [{"kind": "version", "name": "source", "workspace": str(tmp_path),
                                     "version": selected["reference"]}]
    assert submitted["steps"] == submitted["outputs"] == submitted["queries"] == []
    assert actual["operation"]["selection"] == "not_requested"
    assert actual["operation"]["outputs"] == []
    assert not actual["nativeReads"][0].get("rows")


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong-name", "wrong-version", "missing-child-id"])
def test_incomplete_or_contradictory_observations_cannot_pass(simulated, tmp_path, mutation):
    adapter, selected, reply, body = simulated
    row = body["native_versions"][0]
    if mutation == "missing":
        body["native_versions"] = []
    elif mutation == "duplicate":
        body["native_versions"].append(deepcopy(row))
    elif mutation == "wrong-name":
        row["name"] = "another"
    elif mutation == "wrong-version":
        row["version"]["version"] = "different"
        selected = version(tmp_path)
    else:
        row["schema"]["fields"][1]["data_type"]["List"]["metadata"] = {}
    reply.write_text(json.dumps(body))
    actual = adapter.inspect_version(tmp_path, selected)
    assert actual["status"] == "unknown"
    assert actual["error"]["code"] == "DOCSPEC-BINDING"
    assert actual["operation"]["selection"] == "not_requested"


def test_duplicate_observations_cannot_stand_in_for_another_input(simulated, tmp_path):
    adapter, selected, reply, body = simulated
    body["native_versions"].append(deepcopy(body["native_versions"][0]))
    reply.write_text(json.dumps(body))
    actual = adapter.execute({"scratch": str(tmp_path / "scratch"), "inputs": [
        {"kind": "native", "name": name, "workspace": str(tmp_path), "nativeVersion": selected}
        for name in ("source", "other")], "steps": [], "outputs": [], "queries": []})
    assert actual["status"] == "unknown"
    assert "duplicate" in actual["error"]["message"]
    assert actual["result"] == {} and not actual.get("nativeReads")
    assert actual["receipt"]["unverifiedResult"] == body


def physical_snapshot():
    return {"selector": {"metadata_location": "file:///retained/physical.metadata.json",
                         "table_uuid": "a987fbc9-4bed-4078-8f07-9141ba07c9f3",
                         "snapshot": 9007199254740993, "schema_id": 7},
            "metadata_sha256": "b" * 64, "metadata_size": 1457}


def test_physical_uri_validation_does_not_retain_global_parser_entries():
    before = urlsplit.cache_info()
    valid = physical_snapshot()
    validate_physical_snapshot(valid)
    invalid = physical_snapshot()
    invalid["selector"]["metadata_location"] = "file:///unadmitted/metadata.json?latest=1"
    with pytest.raises(ValueError, match="absolute location"):
        validate_physical_snapshot(invalid)
    assert urlsplit.cache_info() == before


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("location", ["file:///retained/physical.metadata.json", "/retained/a [literal].metadata.json "])
def test_observed_physical_identity_preserves_logical_version_and_schema(simulated, tmp_path, empty, location):
    adapter, selected, reply, body = simulated
    physical = physical_snapshot()
    physical["selector"]["metadata_location"] = location
    if empty:
        physical["selector"]["snapshot"] = None
    body["native_versions"][0]["physical_snapshot"] = physical
    reply.write_text(json.dumps(body))
    actual = adapter.inspect_version(tmp_path, selected)
    assert actual["status"] == "succeeded"
    assert actual["result"]["native_versions"][0]["physical_snapshot"] == physical
    assert actual["nativeReads"][0]["version"] == selected
    assert actual["nativeReads"][0]["schemaIdentity"]["value"].endswith(":3")
    assert actual["nativeReads"][0]["schema"] == schema()
    assert "physical_snapshot" not in actual["nativeReads"][0]
    assert actual["operation"]["selection"] == "not_requested"


@pytest.mark.parametrize("field,value", [
    ("metadata_sha256", "B" * 64), ("metadata_sha256", True),
    ("metadata_size", True), ("metadata_size", 1457.0), ("metadata_size", 0),
    ("metadata_size", 1 << 64), ("selector", None),
    ("metadata_location", "relative.metadata.json"), ("metadata_location", "file:///a?latest=1"),
    ("metadata_location", "file:///a\x00"), ("table_uuid", "a987fbc94bed40788f079141ba07c9f3"),
    ("metadata_location", " file:///retained/x"), ("metadata_location", "file:///retained/x\ny"),
    ("metadata_location", "file:///retained/x "), ("metadata_location", "file:///retained/\x7fx"),
    ("snapshot", True), ("snapshot", 42.0), ("snapshot", -1), ("snapshot", 1 << 63),
    ("schema_id", False), ("schema_id", 7.0), ("schema_id", 1 << 31),
])
def test_invalid_physical_observation_withholds_all_admitted_results(simulated, tmp_path, field, value):
    adapter, selected, reply, body = simulated
    physical = physical_snapshot()
    target = physical if field in physical else physical["selector"]
    target[field] = value
    body["native_versions"][0]["physical_snapshot"] = physical
    reply.write_text(json.dumps(body))
    actual = adapter.inspect_version(tmp_path, selected)
    assert actual["status"] == "unknown"
    assert actual["error"]["code"] == "DOCSPEC-BINDING"
    assert actual["result"] == {} and not actual.get("nativeReads")
    assert actual["receipt"]["unverifiedResult"] == body
    assert actual["operation"]["selection"] == "not_requested"


@pytest.mark.parametrize("mutation", ["null", "missing-pin", "extra-field", "missing-selector-field"])
def test_incomplete_physical_observation_does_not_fall_back_to_legacy(simulated, tmp_path, mutation):
    adapter, selected, reply, body = simulated
    physical = physical_snapshot()
    if mutation == "null":
        physical = None
    elif mutation == "missing-pin":
        del physical["metadata_sha256"]
    elif mutation == "extra-field":
        physical["lease"] = "invented"
    else:
        del physical["selector"]["snapshot"]
    body["native_versions"][0]["physical_snapshot"] = physical
    reply.write_text(json.dumps(body))
    actual = adapter.inspect_version(tmp_path, selected)
    assert actual["status"] == "unknown"
    assert actual["result"] == {} and not actual.get("nativeReads")


@pytest.mark.parametrize("bytes_value", [True, 1.0])
def test_observed_version_keeps_native_integer_tokens(simulated, tmp_path, bytes_value):
    adapter, selected, reply, body = simulated
    selected["reference"]["manifest"]["bytes"] = 1
    body["native_versions"][0]["version"] = deepcopy(selected["reference"])
    body["native_versions"][0]["version"]["manifest"]["bytes"] = bytes_value
    reply.write_text(json.dumps(body))
    actual = adapter.inspect_version(tmp_path, selected)
    assert actual["status"] == "unknown"
    assert actual["result"] == {} and not actual.get("nativeReads")


@pytest.mark.parametrize("value", [{}, "", None, False])
def test_native_observations_require_an_array_even_without_native_inputs(simulated, tmp_path, value):
    adapter, _, reply, body = simulated
    body["native_versions"] = value
    reply.write_text(json.dumps(body))
    actual = adapter.execute({"scratch": str(tmp_path / "scratch"), "inputs": [],
                              "steps": [], "outputs": [], "queries": []})
    assert actual["status"] == "unknown"
    assert actual["result"] == {} and not actual.get("nativeReads")
    assert actual["receipt"]["unverifiedResult"] == body


def test_wrong_digest_scheme_refuses_before_native_submission(simulated, tmp_path):
    adapter, selected, _, _ = simulated
    actual = adapter.inspect_version(tmp_path, {**selected, "digestAlgorithm": "sha256"})
    assert actual["status"] == "not_submitted"
    assert actual["error"]["code"] == "DOCSPEC-NATIVE-IDENTITY"


def test_actual_retained_recursive_version_inspection(tmp_path):
    evidence = os.environ.get("DDK_INSPECTION_RETAINED_EVIDENCE")
    if not evidence:
        pytest.skip("Select an existing exact native recursive read receipt")
    retained = json.loads(Path(evidence).read_bytes())
    selected = retained["version"]
    adapter = DocSpecAdapter(retained["executable"], {
        "compute_threads": 1, "memory_bytes": 128 << 20, "scratch_bytes": 32 << 20,
        "batch_rows": 2, "max_batch_bytes": 1 << 20, "max_metadata_bytes": 2 << 20,
    }, timeout=10, evidence_dir=tmp_path / "evidence", native_mapping_profile=RECURSIVE_PROFILE)
    assert adapter.tool["distributionSha256"] == retained["runtime"]["distributionSha256"]
    actual = adapter.inspect_version(selected["namespace"], selected)
    assert actual["status"] == "succeeded", actual
    assert actual["nativeReads"][0] == retained["result"]["nativeRead"]
    assert actual["result"]["outputs"] == actual["result"].get("queries", []) == []
    assert actual["operation"]["outputs"] == []
    wrong = deepcopy(selected)
    wrong["reference"]["manifest"]["digest"] = "b" * 64
    refused = adapter.inspect_version(wrong["namespace"], wrong)
    assert refused["status"] == "failed", refused
    assert refused["error"]["code"] == "release_mismatch"
    missing = deepcopy(selected)
    missing["reference"]["version"] = "not-retained"
    refused = adapter.inspect_version(missing["namespace"], missing)
    assert refused["status"] == "failed", refused
    assert not refused.get("nativeReads")
