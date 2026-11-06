"""Exact native metadata admission and independent refusal controls."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.adapters.docspec_schema import RECURSIVE_PROFILE
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
