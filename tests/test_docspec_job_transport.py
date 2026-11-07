"""Process-boundary simulations; native evidence semantics are tested separately."""

from copy import deepcopy
import base64
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.adapters import docspec_jobs
from ddk.documents import schema_registry, schema_validator


def _prepare(workspace):
    return {
        "action": "prepare", "dataset": "archive", "operation": "original",
        "definition": "urn:example:definition:one",
        "job": {"path": str(workspace / "job.json"), "sha256": "d" * 64},
        "file_inputs": [{"name": "source", "members": [{"key": None, "sha256": "e" * 64, "size": 42}]}],
        "policy_id": "counters", "policy": {"path": str(workspace / "policy.json"), "sha256": "f" * 64},
        "expected_epoch": 0, "expected_selection": None,
        "prerequisites": [{"kind": "example", "required": True}],
    }


def _request_witness(workspace, request):
    from blake3 import blake3

    raw = json.dumps(request).encode()
    return {
        "reference": {"owner": "archive", "path": str(workspace / "original-prepare.json"),
                      "digest": blake3(raw).hexdigest(), "bytes": len(raw)},
        "sha256": sha256(raw).hexdigest(), "bytes_base64": base64.b64encode(raw).decode(),
    }


@pytest.fixture
def simulated_native(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reply = tmp_path / "reply.json"
    binary = tmp_path / "simulated-native"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        f"reply = json.load(open({str(reply)!r}))\n"
        "time.sleep(reply.get('sleep', 0))\n"
        "json.dump(reply['body'], sys.stdout)\n"
        "sys.exit(reply.get('exit', 0))\n"
    )
    binary.chmod(0o755)
    adapter = DocSpecAdapter(binary, {}, timeout=2, evidence_dir=tmp_path / "evidence")
    # This suite isolates process and uncertainty handling. The metadata suite
    # verifies the complete native witnesses; actual native tests qualify them.
    monkeypatch.setattr(docspec_jobs, "verify_completed_job", lambda *_args, **_kwargs: None)
    candidate = {
        "scheme": "urn:docspec:whole-job-candidate", "scheme_version": "1",
        "dataset": "archive", "operation": "original",
        "manifest": {"owner": "archive", "path": str(workspace / "completion.json"),
                     "digest": "a" * 64, "bytes": 123},
    }
    result = {
        "dataset": "archive", "operation": "original", "request_digest": "b" * 64,
        "status": "completed", "candidate": candidate, "policy_id": "counters",
        "accepted_qualification": None, "selection": "pending",
        "admitted_request": _request_witness(workspace, _prepare(workspace)),
        "completed_outputs": [{"name": "rows", "path": str(workspace / "rows.parquet"),
                               "sha256": "c" * 64, "size": 91, "rows": 2}],
    }

    def respond(body, *, exit_code=0, sleep=0):
        reply.write_text(json.dumps({"body": body, "exit": exit_code, "sleep": sleep}))

    respond(result)
    return adapter, workspace, result, respond


def _inspect():
    return {"action": "inspect", "dataset": "archive", "operation": "original"}


def _validate_operation(operation):
    _, schemas, _ = schema_registry()
    validator = schema_validator({"$ref": schemas["common"]["$id"] + "#/$defs/runtimeOperation"})
    assert not list(validator.iter_errors(operation))


def test_acceptance_refusal_preserves_completed_computation_and_outputs(simulated_native):
    adapter, workspace, result, respond = simulated_native
    respond({"status": "failed", "error": {"code": "native_counter_failed", "message": "One required counter is nonzero"},
             "completed": result}, exit_code=1)
    request = {**_inspect(), "action": "accept", "request_digest": result["request_digest"],
               "candidate": result["candidate"], "policy_id": "counters"}
    response = adapter.managed_job(workspace, request)
    assert response["status"] == "failed"
    assert response["operation"]["execution"] == "succeeded"
    assert response["operation"]["selection"] == "pending"
    assert "acceptedQualification" not in response["operation"]
    assert response["operation"]["outputs"][0]["attributes"] == {"name": "rows", "size": 91, "rows": 2}
    assert response["result"] == result
    _validate_operation(response["operation"])


def test_transport_loss_keeps_one_confirmed_receipt_without_a_retry_chain(simulated_native):
    adapter, workspace, result, respond = simulated_native
    first = adapter.managed_job(workspace, _inspect())
    assert first["status"] == "succeeded"
    respond(result, sleep=10)
    adapter.timeout = 0.05
    lost = adapter.managed_job(workspace, _inspect(), prior=first)
    assert lost["status"] == "unknown"
    assert lost["operation"]["execution"] == "succeeded"
    assert lost["operation"]["selection"] == "unknown"
    assert lost["operation"]["outputs"] == first["operation"]["outputs"]
    confirmation = {key: first["evidence"][key] for key in ("path", "sha256")}
    assert lost["receipt"]["confirmation"] == confirmation
    again = adapter.managed_job(workspace, _inspect(), prior=lost)
    assert again["receipt"]["confirmation"] == confirmation
    assert again["operation"]["requestIdentity"] == first["operation"]["requestIdentity"]
    respond(result)
    adapter.timeout = 2
    reconciled = adapter.managed_job(workspace, _inspect(), prior=again)
    assert reconciled["status"] == "succeeded"
    assert "confirmation" not in reconciled["receipt"]
    assert reconciled["result"] == result
    _validate_operation(again["operation"])


def test_changed_confirmation_bytes_refuse_before_another_native_call(simulated_native):
    adapter, workspace, _result, _respond = simulated_native
    first = adapter.managed_job(workspace, _inspect())
    path = Path(first["evidence"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    before = set(adapter.evidence_dir.iterdir())
    with pytest.raises(ValueError, match="receipt bytes changed"):
        adapter.managed_job(workspace, _inspect(), prior=first)
    assert set(adapter.evidence_dir.iterdir()) == before


def test_wrong_candidate_response_preserves_refusal_and_previous_confirmation(simulated_native):
    adapter, workspace, result, respond = simulated_native
    first = adapter.managed_job(workspace, _inspect())
    wrong = deepcopy(result)
    wrong["candidate"]["operation"] = "someone-else"
    respond(wrong)
    response = adapter.managed_job(workspace, _inspect(), prior=first)
    assert response["status"] == "unknown"
    assert response["result"] == {}
    assert response["receipt"]["unverifiedResult"] == wrong
    assert response["operation"]["candidate"] == first["operation"]["candidate"]
    assert response["operation"]["execution"] == "succeeded"
    assert response["operation"]["selection"] == "unknown"


def test_partial_known_failure_keeps_observed_files_without_a_candidate(simulated_native):
    adapter, workspace, result, respond = simulated_native
    partial = {**result, "status": "failed", "candidate": None}
    respond({"status": "failed", "error": {"code": "query_failed", "message": "A later required report failed"},
             "completed": partial}, exit_code=1)
    response = adapter.managed_job(workspace, _inspect())
    assert response["status"] == "failed"
    assert response["operation"]["execution"] == "failed"
    assert "candidate" not in response["operation"]
    assert len(response["operation"]["outputs"]) == 1
    _validate_operation(response["operation"])


def test_native_pending_means_admitted_computation_has_not_started(simulated_native):
    adapter, workspace, result, respond = simulated_native
    pending = {**result, "status": "pending", "candidate": None, "completed_outputs": []}
    respond(pending)
    response = adapter.managed_job(workspace, _prepare(workspace))
    assert response["status"] == "succeeded"  # The command has a known native response.
    assert response["operation"]["execution"] == "pending"
    assert response["operation"]["selection"] == "pending"
    assert "candidate" not in response["operation"]
    assert "has not started" in response["operation"]["reason"]
    _validate_operation(response["operation"])


def test_initial_prepare_loss_preserves_full_intent_through_repeated_inspect(simulated_native):
    adapter, workspace, result, respond = simulated_native
    respond(result, sleep=10)
    adapter.timeout = 0.05
    lost = adapter.managed_job(workspace, _prepare(workspace))
    assert lost["status"] == "unknown"
    original = lost["receipt"]["originalRequest"]
    assert original == lost["receipt"]["request"]
    again = adapter.managed_job(workspace, _inspect(), prior=lost)
    assert again["receipt"]["originalRequest"] == original
    assert again["operation"]["requestIdentity"] == lost["operation"]["requestIdentity"]
    respond(result)
    adapter.timeout = 2
    confirmed = adapter.managed_job(workspace, _inspect(), prior=again)
    assert confirmed["status"] == "succeeded"
    assert confirmed["result"] == result
    assert confirmed["receipt"]["originalRequest"] == original
    assert confirmed["operation"]["requestIdentity"]["scheme"] == docspec_jobs.REQUEST_SCHEME
    _validate_operation(confirmed["operation"])


def test_snapshot_source_configuration_stays_outside_original_job_identity(simulated_native, monkeypatch):
    from ddk.adapters import docspec

    adapter, workspace, result, _ = simulated_native
    source = workspace / "unopened source configuration.json"
    calls = []
    original_run = docspec.run_bounded

    def observe(command, **kwargs):
        calls.append(command)
        return original_run(command, **kwargs)

    monkeypatch.setattr(docspec, "run_bounded", observe)
    request = _prepare(workspace)
    plain = adapter.managed_job(workspace, request)
    configured = adapter.managed_job(workspace, request, snapshot_source=source, prior=plain)
    assert plain["status"] == configured["status"] == "succeeded"
    assert "--snapshot-source" not in calls[0]
    index = calls[1].index("--snapshot-source")
    assert calls[1][index + 1:index + 3] == [str(source), "managed-job"]
    assert not source.exists()  # DDK transports the path; native code owns its contents.
    assert request == _prepare(workspace)
    assert configured["result"] == result
    assert configured["operation"]["requestIdentity"] == plain["operation"]["requestIdentity"]
    assert configured["receipt"]["originalRequest"] == plain["receipt"]["originalRequest"]
    assert json.loads(Path(configured["receipt"]["request"]["path"]).read_bytes()) == request
    assert str(source) not in json.dumps(configured["receipt"])


def test_snapshot_source_timeout_keeps_original_intent_for_source_free_recovery(simulated_native):
    adapter, workspace, result, respond = simulated_native
    respond(result, sleep=10)
    adapter.timeout = 0.05
    source = workspace / "unopened source configuration.json"
    lost = adapter.managed_job(workspace, _prepare(workspace), snapshot_source=source)
    assert lost["status"] == "unknown"
    original = lost["receipt"]["originalRequest"]
    assert original == lost["receipt"]["request"]
    respond(result)
    adapter.timeout = 2
    confirmed = adapter.managed_job(workspace, _inspect(), prior=lost)
    assert confirmed["status"] == "succeeded"
    assert confirmed["operation"]["operationId"] == lost["operation"]["operationId"] == "original"
    assert confirmed["receipt"]["originalRequest"] == original
    assert confirmed["result"] == result
    assert not source.exists()
    _validate_operation(confirmed["operation"])


def test_snapshot_source_does_not_enable_an_unsupported_job_owner(simulated_native, monkeypatch):
    from ddk.adapters import docspec

    adapter, workspace, _, _ = simulated_native

    def unexpected(*args, **kwargs):
        raise AssertionError("Unsupported placement must refuse before native submission")

    monkeypatch.setattr(docspec, "run_bounded", unexpected)
    response = adapter.managed_job(workspace, _prepare(workspace), backend="remote",
                                   snapshot_source=workspace / "source.json")
    assert response["status"] == "not_submitted"
    assert response["error"]["code"] == "DOCSPEC-BACKEND-UNSUPPORTED"
    assert response["operation"]["operationId"] == "original"


@pytest.mark.parametrize("field", ["definition", "job", "file_inputs", "policy", "policy_id", "expected_epoch",
                                    "expected_selection", "prerequisites"])
def test_inspect_refuses_different_original_prepare_after_first_response_loss(simulated_native, field):
    adapter, workspace, result, respond = simulated_native
    respond(result, sleep=10)
    adapter.timeout = 0.05
    lost = adapter.managed_job(workspace, _prepare(workspace))
    altered = _prepare(workspace)
    replacements = {
        "definition": "urn:example:definition:other",
        "job": {"path": str(workspace / "job.json"), "sha256": "1" * 64},
        "file_inputs": [{"name": "source", "members": [{"key": None, "sha256": "e" * 64, "size": 43}]}],
        "policy": {"path": str(workspace / "policy.json"), "sha256": "2" * 64},
        "policy_id": "other", "expected_epoch": 1, "expected_selection": result["candidate"],
        # JSON true and number 1 must remain different admission facts.
        "prerequisites": [{"kind": "example", "required": 1}],
    }
    altered[field] = replacements[field]
    wrong = {**result, "admitted_request": _request_witness(workspace, altered)}
    respond(wrong)
    adapter.timeout = 2
    refused = adapter.managed_job(workspace, _inspect(), prior=lost)
    assert refused["status"] == "unknown"
    assert refused["result"] == {}
    assert refused["receipt"]["unverifiedResult"] == wrong
    assert refused["operation"]["execution"] == "unknown"
    assert "candidate" not in refused["operation"]
    assert refused["operation"]["requestIdentity"] == lost["operation"]["requestIdentity"]
    assert "complete original prepare request" in refused["error"]["message"]


def test_repeated_prepare_cannot_change_original_intent_before_submission(simulated_native):
    adapter, workspace, result, respond = simulated_native
    respond(result, sleep=10)
    adapter.timeout = 0.05
    lost = adapter.managed_job(workspace, _prepare(workspace))
    before = set(adapter.evidence_dir.iterdir())
    changed = {**_prepare(workspace), "definition": "urn:example:other"}
    with pytest.raises(ValueError, match="complete original prepare request"):
        adapter.managed_job(workspace, changed, prior=lost)
    assert set(adapter.evidence_dir.iterdir()) == before


def test_original_prepare_bytes_must_remain_pinned_during_recovery(simulated_native):
    adapter, workspace, result, respond = simulated_native
    respond(result, sleep=10)
    adapter.timeout = 0.05
    lost = adapter.managed_job(workspace, _prepare(workspace))
    path = Path(lost["receipt"]["originalRequest"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    before = set(adapter.evidence_dir.iterdir())
    with pytest.raises(ValueError, match="receipt bytes changed"):
        adapter.managed_job(workspace, _inspect(), prior=lost)
    assert set(adapter.evidence_dir.iterdir()) == before


def test_transport_loss_preserves_confirmed_historical_selection_and_acceptance(simulated_native):
    adapter, workspace, result, respond = simulated_native
    selected = {**result, "selection": "selected", "accepted_qualification": {"identity": "7" * 64}}
    respond(selected)
    first = adapter.managed_job(workspace, _prepare(workspace))
    assert first["status"] == "succeeded"
    respond(selected, sleep=10)
    adapter.timeout = 0.05
    lost = adapter.managed_job(workspace, _inspect(), prior=first)
    again = adapter.managed_job(workspace, _inspect(), prior=lost)
    for response in (lost, again):
        assert response["status"] == "unknown"
        assert response["operation"]["execution"] == "succeeded"
        assert response["operation"]["selection"] == "selected"
        assert response["operation"]["acceptedQualification"] == first["operation"]["acceptedQualification"]
        assert response["receipt"]["confirmation"] == {key: first["evidence"][key] for key in ("path", "sha256")}
        _validate_operation(response["operation"])


def test_refused_select_retry_preserves_confirmed_historical_selection(simulated_native):
    adapter, workspace, result, respond = simulated_native
    selected = {**result, "selection": "selected", "accepted_qualification": {"identity": "7" * 64}}
    respond(selected)
    first = adapter.managed_job(workspace, _prepare(workspace))
    respond({"status": "failed", "error": {"code": "qualification_mismatch", "message": "Retry supplied another qualification"},
             "completed": selected}, exit_code=1)
    retry = {**_inspect(), "action": "select", "request_digest": result["request_digest"],
             "candidate": result["candidate"], "policy_id": "counters", "accepted_qualification": "8" * 64}
    response = adapter.managed_job(workspace, retry, prior=first)
    assert response["status"] == "failed"
    assert response["error"]["code"] == "qualification_mismatch"
    assert response["operation"]["execution"] == "succeeded"
    assert response["operation"]["selection"] == "selected"
    assert response["operation"]["acceptedQualification"] == first["operation"]["acceptedQualification"]
    _validate_operation(response["operation"])


@pytest.mark.parametrize("action", ["accept", "select", "requalify"])
@pytest.mark.parametrize("wrong_field", ["request_digest", "candidate", None])
def test_first_action_timeout_keeps_requested_identity_without_observing_candidate(simulated_native, action, wrong_field):
    adapter, workspace, result, respond = simulated_native
    request = {**_inspect(), "action": action, "request_digest": result["request_digest"],
               "candidate": result["candidate"], "policy_id": "counters"}
    respond(result, sleep=10)
    adapter.timeout = 0.05
    lost = adapter.managed_job(workspace, request)
    assert lost["status"] == "unknown"
    assert "candidate" not in lost["operation"]
    constraint = lost["receipt"]["identityConstraint"]
    assert constraint == lost["receipt"]["request"]
    again = adapter.managed_job(workspace, _inspect(), prior=lost)
    assert again["receipt"]["identityConstraint"] == constraint
    assert "candidate" not in again["operation"]
    native = deepcopy(result)
    if wrong_field == "request_digest":
        native["request_digest"] = "9" * 64
    elif wrong_field == "candidate":
        native["candidate"]["manifest"]["digest"] = "9" * 64
    respond(native)
    adapter.timeout = 2
    response = adapter.managed_job(workspace, _inspect(), prior=again)
    assert response["receipt"]["identityConstraint"] == constraint
    if wrong_field:
        assert response["status"] == "unknown"
        assert response["result"] == {}
        assert response["receipt"]["unverifiedResult"] == native
        assert "candidate" not in response["operation"]
        assert "original requested native identity" in response["error"]["message"]
    else:
        assert response["status"] == "succeeded"
        assert response["result"] == native
        assert response["operation"]["candidate"]["reference"] == result["candidate"]
    _validate_operation(response["operation"])
