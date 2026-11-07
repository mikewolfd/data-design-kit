"""Independent publication metadata and transport cases, without native execution."""

import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from threading import Event

import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.adapters.docspec_publication import publication_context, publication_prior
from ddk.documents import schema_registry, schema_validator


def _pin(raw):
    return {"sha256": sha256(raw).hexdigest(), "size": len(raw)}


def _encoded(raw):
    return base64.b64encode(raw).decode()


def _fixtures(workspace):
    dataset, operation = "archive", "original"
    record = {"table": "ddk.lifecycle_archive", "table_uuid": "b29414a3-ae3d-4a85-b68d-312b19aa2db1"}
    candidate = {"scheme": "urn:docspec:whole-job-candidate", "scheme_version": "1", "dataset": dataset,
                 "operation": operation, "manifest": {"owner": dataset, "path": str(workspace / "manifest.json"),
                 "digest": "1" * 64, "bytes": 300}}
    manifest = b'{"files":["public.parquet"]}\n'
    pointer = b'{"release":"frozen-release"}\n'
    output = {"name": "rows", "object": {"owner": dataset, "path": str(workspace / "rows.parquet"),
              "digest": "2" * 64, "bytes": 71}, "sha256": "3" * 64, "md5": "4" * 32, "rows": 2,
              "disposition": {"kind": "published", "name": "public.parquet", "content_type": "application/vnd.apache.parquet"}}
    scope = {"kind": "local_fixture", "publisher": "fixture", "bucket": "local", "release_prefix": "releases/one",
             "pointer_key": "current.json"}
    audit = {
        "reference": {"dataset": dataset, "operation": operation, "intent_digest": "5" * 64,
                      "native_record": {**record, "key": "job-publication-payload/original", "revision": 6}},
        "candidate": candidate, "job_request_digest": "6" * 64, "policy_id": "counts",
        "accepted_qualification": "7" * 64, "epoch": 0,
        "selection": {**record, "key": "job-selected/original", "revision": 5},
        "acceptance": {**record, "key": "job-accepted/original/counts", "revision": 4},
        "completion": {**record, "key": "job-result/original", "revision": 3},
        "scope": scope, "release_id": "8" * 64, "inventory_digest": "9" * 64,
        "controls": [{"name": "manifest.json", "content_type": "application/json", "bytes": _pin(manifest)}],
        "expected_pointer": {"kind": "absent"},
        "pointer": {"content_type": "application/json", "cache_control": "no-cache", "bytes": _pin(pointer)},
        "payload_digest": "a" * 64,
    }
    result = {"dataset": dataset, "operation": operation, "status": "retained", "intent": audit,
              "payload": {"outputs": [output], "controls_base64": [_encoded(manifest)],
                          "predecessor_bytes_base64": None, "pointer_bytes_base64": _encoded(pointer)},
              "external_authorization": "not_run", "dispatch": "not_run"}
    request = {"action": "freeze", "dataset": dataset, "operation": operation,
               **{key: deepcopy(audit[key]) for key in ("candidate", "job_request_digest", "policy_id",
                                                      "accepted_qualification", "scope", "release_id")},
               "expected_epoch": 0, "expected_selection_revision": 5,
               "outputs": [deepcopy(output)],
               "controls": [{"name": "manifest.json", "content_type": "application/json", "size": len(manifest),
                             "artifact": {"path": str(workspace / "removed-control.json"), "sha256": sha256(manifest).hexdigest()}}],
               "expected_pointer": {"kind": "absent"},
               "pointer": {"content_type": "application/json", "cache_control": "no-cache", "bytes_base64": _encoded(pointer)}}
    return request, result


@pytest.fixture
def simulated_publication(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reply = tmp_path / "reply.json"
    binary = tmp_path / "simulated-native"
    calls = tmp_path / "calls.jsonl"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        f"reply = json.load(open({str(reply)!r}))\n"
        f"with open({str(calls)!r}, 'a') as calls: calls.write(json.dumps(sys.argv) + '\\n')\n"
        "time.sleep(reply.get('sleep', 0))\n"
        "json.dump(reply['body'], sys.stdout)\n"
        "sys.exit(reply.get('exit', 0))\n"
    )
    binary.chmod(0o755)
    adapter = DocSpecAdapter(binary, {}, timeout=2, evidence_dir=tmp_path / "evidence")
    request, result = _fixtures(workspace)

    def respond(body, *, exit_code=0, sleep=0):
        reply.write_text(json.dumps({"body": body, "exit": exit_code, "sleep": sleep}))

    respond(result)
    return adapter, workspace, request, result, respond, calls


def _inspect(request):
    return {key: value for key, value in {**request, "action": "inspect"}.items()
            if key in {"action", "dataset", "operation"}}


def _validator():
    _, schemas, _ = schema_registry()
    return schema_validator({"$ref": schemas["common"]["$id"] + "#/$defs/runtimeOperation"})


def _valid(response):
    assert not list(_validator().iter_errors(response["operation"]))
    return response["operation"]["publicationIntent"]


def _unverified(response):
    reference = response["receipt"]["unverifiedResponse"]
    raw = Path(reference["path"]).read_bytes()
    assert sha256(raw).hexdigest() == reference["sha256"]
    return json.loads(raw)


def test_saved_intent_is_separate_from_computation_selection_and_external_publication(simulated_publication):
    adapter, workspace, request, result, _respond, calls = simulated_publication
    assert not Path(request["controls"][0]["artifact"]["path"]).exists()
    response = adapter.publication_intent(workspace, request)
    assert response["status"] == "succeeded", response
    publication = _valid(response)
    assert publication["outcome"] == "succeeded" and publication["payloadState"] == "retained"
    assert publication["savedIntent"]["reference"] == result["intent"]["reference"]
    assert publication["savedIntent"]["digestAlgorithm"] == "blake3"
    assert response["operation"]["execution"] == response["operation"]["selection"] == "not_requested"
    assert response["operation"]["outputs"] == []
    assert not {"qualificationRequired", "candidate", "acceptedQualification"} & response["operation"].keys()
    assert response["receipt"]["originalRequest"] == response["receipt"]["request"]
    assert response["operation"]["requestIdentity"]["value"] == response["receipt"]["request"]["sha256"]
    evidence = publication["evidence"]
    raw = Path(evidence["path"]).read_bytes()
    assert sha256(raw).hexdigest() == evidence["sha256"] and json.loads(raw) == result
    assert evidence["path"] != response["evidence"]["path"]  # No receipt self-hash.
    assert "result" not in response["receipt"]
    assert response["receipt"]["nativeResponse"] == evidence
    assert json.loads(calls.read_text())[5] == "job-publication-intent"


def test_unbound_inspect_preserves_verified_absence(simulated_publication):
    adapter, workspace, request, result, respond, _calls = simulated_publication
    absent = {**result, "status": "not_found", "intent": None, "payload": None}
    respond(absent)
    response = adapter.publication_intent(workspace, _inspect(request))
    assert response["status"] == "succeeded"
    publication = _valid(response)
    assert publication["outcome"] == "not_found" and "evidence" in publication
    assert "savedIntent" not in publication and "payloadState" not in publication


def test_retirement_keeps_the_saved_decision_but_reports_payload_loss(simulated_publication):
    adapter, workspace, request, result, respond, _calls = simulated_publication
    first = adapter.publication_intent(workspace, request)
    respond({**result, "status": "retired", "payload": None})
    retired = adapter.publication_intent(workspace, request, prior=first)
    assert retired["status"] == "succeeded", retired
    publication = _valid(retired)
    assert publication["payloadState"] == "retired"
    assert publication["savedIntent"] == first["operation"]["publicationIntent"]["savedIntent"]


def test_lost_first_freeze_requires_exact_replay_before_bound_inspect(simulated_publication):
    adapter, workspace, request, result, respond, calls = simulated_publication
    respond(result, sleep=3)
    adapter.timeout = 0.1
    lost = adapter.publication_intent(workspace, request)
    assert lost["status"] == "unknown" and _valid(lost)["outcome"] == "unknown"
    assert "savedIntent" not in lost["operation"]["publicationIntent"]
    previous_calls = calls.read_bytes() if calls.exists() else None
    with pytest.raises(ValueError, match="Replay the exact original freeze"):
        adapter.publication_intent(workspace, _inspect(request), prior=lost)
    changed = deepcopy(request)
    changed["outputs"][0]["disposition"]["name"] = "another.parquet"
    with pytest.raises(ValueError, match="complete original freeze"):
        adapter.publication_intent(workspace, changed, prior=lost)
    assert (calls.read_bytes() if calls.exists() else None) == previous_calls
    respond(result)
    cold = DocSpecAdapter(adapter.executable, {}, timeout=2, evidence_dir=workspace / "cold")
    replay = cold.publication_intent(workspace, request, prior=lost)
    assert replay["status"] == "succeeded", replay
    assert replay["receipt"]["originalRequest"] == lost["receipt"]["originalRequest"]
    inspected = cold.publication_intent(workspace, _inspect(request), prior=replay)
    assert inspected["status"] == "succeeded" and _valid(inspected)["payloadState"] == "retained"


@pytest.mark.parametrize("state", ["timeout", "not_found", "changed_audit", "wrong_operation", "refused"])
def test_unconfirmed_refresh_preserves_historical_identity_without_current_protection(simulated_publication, state):
    adapter, workspace, request, result, respond, _calls = simulated_publication
    first = adapter.publication_intent(workspace, request)
    altered = deepcopy(result)
    if state == "timeout":
        respond(result, sleep=3)
        adapter.timeout = 0.1
    elif state == "not_found":
        respond({**result, "status": "not_found", "intent": None, "payload": None})
    elif state == "changed_audit":
        altered["intent"]["reference"]["intent_digest"] = "b" * 64
        respond(altered)
    elif state == "wrong_operation":
        altered["operation"] = "different"
        respond(altered)
    else:
        respond({"status": "failed", "error": {"code": "capacity", "message": "Native metadata capacity exhausted"}}, exit_code=1)
    response = adapter.publication_intent(workspace, _inspect(request), prior=first)
    publication = _valid(response)
    assert publication["outcome"] == ("refused" if state == "refused" else "unknown")
    assert publication["savedIntent"] == first["operation"]["publicationIntent"]["savedIntent"]
    assert publication["payloadState"] == "unknown"
    assert publication["evidence"] == first["operation"]["publicationIntent"]["evidence"]
    if state in {"not_found", "changed_audit", "wrong_operation"}:
        assert _unverified(response)


@pytest.mark.parametrize("change", ["boolean_revision", "table_incarnation", "candidate", "job_digest", "control_bytes",
                                    "pointer_bytes", "output_inventory", "retained_without_payload", "external_dispatch",
                                    "invalid_status", "invalid_pointer_kind", "invalid_disposition_kind", "unexpected_native_versions"])
def test_mismatched_native_metadata_cannot_confirm_saved_publication(simulated_publication, change):
    adapter, workspace, request, result, respond, _calls = simulated_publication
    altered = deepcopy(result)
    if change == "boolean_revision":
        altered["intent"]["completion"]["revision"] = True
    elif change == "table_incarnation":
        altered["intent"]["acceptance"]["table_uuid"] = "b29414a3-ae3d-4a85-b68d-312b19aa2db2"
    elif change == "candidate":
        altered["intent"]["candidate"]["operation"] = "different"
    elif change == "job_digest":
        altered["intent"]["job_request_digest"] = "b" * 64
    elif change == "control_bytes":
        altered["payload"]["controls_base64"][0] = _encoded(b"changed")
    elif change == "pointer_bytes":
        altered["payload"]["pointer_bytes_base64"] = _encoded(b"changed")
    elif change == "output_inventory":
        altered["payload"]["outputs"][0]["rows"] = 3
    elif change == "retained_without_payload":
        altered["payload"] = None
    elif change == "external_dispatch":
        altered["dispatch"] = "succeeded"
    elif change == "invalid_status":
        altered["status"] = []
    elif change == "invalid_pointer_kind":
        altered["intent"]["expected_pointer"]["kind"] = []
    elif change == "invalid_disposition_kind":
        altered["payload"]["outputs"][0]["disposition"]["kind"] = {}
    else:
        altered["native_versions"] = [{"unexpected": []}]
    respond(altered)
    response = adapter.publication_intent(workspace, request)
    assert response["status"] == "unknown" and response["result"] == {}, response
    assert _unverified(response) == altered
    assert _valid(response)["outcome"] == "unknown" and "savedIntent" not in response["operation"]["publicationIntent"]


def test_changed_prior_or_wrong_protocol_refuses_before_native_submission(simulated_publication):
    adapter, workspace, request, _result, _respond, calls = simulated_publication
    first = adapter.publication_intent(workspace, request)
    before = calls.read_bytes()
    crossed = deepcopy(first)
    crossed["operationContext"]["kind"] = "whole_job"
    with pytest.raises(ValueError, match="another publication operation"):
        adapter.publication_intent(workspace, _inspect(request), prior=crossed)
    original = Path(first["receipt"]["originalRequest"]["path"])
    original.write_bytes(original.read_bytes() + b" ")
    with pytest.raises(ValueError, match="receipt bytes changed"):
        adapter.publication_intent(workspace, request, prior=first)
    assert calls.read_bytes() == before


def test_cancellation_before_submission_preserves_request_without_claiming_a_saved_decision(simulated_publication):
    adapter, workspace, request, _result, _respond, calls = simulated_publication
    cancelled = Event()
    cancelled.set()
    response = adapter.publication_intent(workspace, request, cancel_event=cancelled)
    assert response["status"] == "not_submitted" and _valid(response)["outcome"] == "not_submitted"
    assert response["receipt"]["originalRequest"] == response["receipt"]["request"]
    assert not calls.exists()


@pytest.mark.parametrize("failure", ["missing_code", "partial_completion"])
def test_conflicting_refusal_protocol_is_unknown(simulated_publication, failure):
    adapter, workspace, request, result, respond, _calls = simulated_publication
    body = {"status": "failed", "error": {"code": "capacity", "message": "No capacity"}}
    if failure == "missing_code":
        del body["error"]["code"]
    else:
        body["completed"] = result
    respond(body, exit_code=1)
    response = adapter.publication_intent(workspace, request)
    assert response["status"] == "unknown" and _valid(response)["outcome"] == "unknown"


@pytest.mark.parametrize("invalid", ["job_qualification", "job_candidate", "job_output", "execution", "selection",
                                     "no_evidence", "unknown_payload_success", "unknown_without_reason", "freeze_absence"])
def test_report_schema_prevents_publication_intent_from_becoming_job_evidence(simulated_publication, invalid):
    adapter, workspace, request, _result, _respond, _calls = simulated_publication
    operation = adapter.publication_intent(workspace, request)["operation"]
    assert not list(_validator().iter_errors(operation))
    if invalid == "job_qualification":
        operation["qualificationRequired"] = True
    elif invalid == "job_candidate":
        operation["candidate"] = operation["publicationIntent"]["savedIntent"]
    elif invalid == "job_output":
        operation["outputs"] = [operation["publicationIntent"]["evidence"]]
    elif invalid == "execution":
        operation["execution"] = "succeeded"
    elif invalid == "selection":
        operation["selection"] = "unknown"
    elif invalid == "no_evidence":
        del operation["publicationIntent"]["evidence"]
    elif invalid == "unknown_payload_success":
        operation["publicationIntent"]["payloadState"] = "unknown"
    elif invalid == "unknown_without_reason":
        operation["publicationIntent"]["outcome"] = "unknown"
        operation["publicationIntent"]["payloadState"] = "unknown"
    else:
        operation["publicationIntent"] = {"action": "freeze", "outcome": "not_found",
                                          "evidence": operation["publicationIntent"]["evidence"]}
    assert list(_validator().iter_errors(operation))


def test_existing_job_report_branches_keep_their_computation_requirements():
    operation = {"runtime": "docspec", "mode": "bounded_job", "requestIdentity": {"scheme": "urn:test:request", "value": "one"},
                 "reconciliation": "unsupported", "execution": "succeeded", "selection": "not_requested", "outputs": []}
    validator = _validator()
    assert not list(validator.iter_errors(operation))
    operation.update(mode="managed_operation", reconciliation="supported", operationId="original", qualificationRequired=True)
    assert not list(validator.iter_errors(operation))
    del operation["qualificationRequired"]
    assert list(validator.iter_errors(operation))
    operation["qualificationRequired"] = True
    operation["execution"] = "not_requested"
    assert list(validator.iter_errors(operation))


def test_exact_retired_generation_cannot_become_retained_again(simulated_publication):
    adapter, workspace, request, result, respond, _calls = simulated_publication
    first = adapter.publication_intent(workspace, request)
    respond({**result, "status": "retired", "payload": None})
    retired = adapter.publication_intent(workspace, _inspect(request), prior=first)
    assert _valid(retired)["payloadState"] == "retired"
    respond(result)
    revived = adapter.publication_intent(workspace, _inspect(request), prior=retired)
    assert revived["status"] == "unknown" and revived["result"] == {}
    assert "cannot become retained" in revived["error"]["message"]
    assert _valid(revived)["payloadState"] == "unknown"
    assert revived["operation"]["publicationIntent"]["savedIntent"] == retired["operation"]["publicationIntent"]["savedIntent"]


@pytest.mark.parametrize("field", ["revision", "bytes"])
def test_cold_native_metadata_preserves_integer_tokens(simulated_publication, field):
    adapter, workspace, request, result, _respond, calls = simulated_publication
    first = adapter.publication_intent(workspace, request)
    original_calls = calls.read_bytes()
    altered = deepcopy(result)
    if field == "revision":
        altered["intent"]["completion"]["revision"] = 3.0
    else:
        altered["intent"]["controls"][0]["bytes"]["size"] = float(altered["intent"]["controls"][0]["bytes"]["size"])
    raw = json.dumps(altered).encode()
    native_pin = first["operation"]["publicationIntent"]["evidence"]
    Path(native_pin["path"]).write_bytes(raw)
    receipt_path = Path(first["evidence"]["path"])
    receipt = json.loads(receipt_path.read_bytes())
    receipt["operation"]["publicationIntent"]["evidence"]["sha256"] = sha256(raw).hexdigest()
    receipt["nativeResponse"]["sha256"] = sha256(raw).hexdigest()
    rebound = json.dumps(receipt).encode()
    receipt_path.write_bytes(rebound)
    first["evidence"]["sha256"] = sha256(rebound).hexdigest()
    first["operation"] = receipt["operation"]
    with pytest.raises(ValueError, match="generation|byte identity"):
        adapter.publication_intent(workspace, _inspect(request), prior=first)
    assert calls.read_bytes() == original_calls


def test_near_capture_limit_keeps_compact_recoverable_metadata_at_the_same_limits(simulated_publication):
    adapter, workspace, request, result, respond, _calls = simulated_publication
    raw = b"x" * 21000
    result["intent"]["controls"][0]["bytes"] = _pin(raw)
    result["payload"]["controls_base64"] = [_encoded(raw)]
    request["controls"][0]["size"] = len(raw)
    request["controls"][0]["artifact"]["sha256"] = sha256(raw).hexdigest()
    adapter.capture_bytes = 32768
    adapter.metadata_bytes = 8192
    assert 0.9 * adapter.capture_bytes < len(json.dumps(result).encode()) < adapter.capture_bytes
    respond(result)
    first = adapter.publication_intent(workspace, request)
    assert first["status"] == "succeeded", first
    assert Path(first["evidence"]["path"]).stat().st_size < adapter.metadata_bytes
    assert "result" not in first["receipt"]
    context = publication_context(str(workspace), _inspect(request))
    _previous, confirmed, _original = publication_prior(context, _inspect(request), first,
        max_metadata_bytes=adapter.metadata_bytes, max_native_bytes=adapter.capture_bytes)
    assert set(confirmed["value"]) == {"intent", "status"}  # The old delivery payload has no remaining consumer.
    cold = DocSpecAdapter(adapter.executable, {}, timeout=2, evidence_dir=workspace / "cold",
                          capture_bytes=adapter.capture_bytes, metadata_bytes=adapter.metadata_bytes)
    inspected = cold.publication_intent(workspace, _inspect(request), prior=first)
    assert inspected["status"] == "succeeded" and _valid(inspected)["payloadState"] == "retained"
    replayed = cold.publication_intent(workspace, request, prior=inspected)
    assert replayed["status"] == "succeeded", replayed


def test_oversize_original_freeze_refuses_before_submission(simulated_publication):
    adapter, workspace, request, _result, _respond, calls = simulated_publication
    adapter.metadata_bytes = 8192
    request["pointer"]["bytes_base64"] = _encoded(b"p" * 10000)
    refused = adapter.publication_intent(workspace, request)
    assert refused["status"] == "not_submitted" and refused["error"]["code"] == "DOCSPEC-REQUEST-LIMIT"
    assert _valid(refused)["outcome"] == "not_submitted" and not calls.exists()


def test_unadmitted_final_receipt_does_not_return_success_or_discard_original_evidence(simulated_publication):
    adapter, workspace, request, result, respond, calls = simulated_publication
    adapter.metadata_bytes = 4096
    for record in (result["intent"]["reference"]["native_record"], result["intent"]["selection"],
                   result["intent"]["acceptance"], result["intent"]["completion"]):
        record["table"] = "large-native-table-identity-" + "x" * 6000
    respond(result)
    with pytest.raises(OSError, match="original request retained.*native response retained"):
        adapter.publication_intent(workspace, request)
    assert calls.exists()
    folders = list(adapter.evidence_dir.iterdir())
    assert len(folders) == 1
    assert json.loads((folders[0] / "request.json").read_bytes()) == request
    assert json.loads((folders[0] / "stdout.json").read_bytes()) == result
    assert not (folders[0] / "receipt.json").exists()
