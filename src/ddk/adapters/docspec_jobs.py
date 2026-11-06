"""Translate the concrete retained-job wire without owning native lifecycle state."""

from copy import deepcopy
from pathlib import Path
import re

from ddk.docspec_job_evidence import (
    CANDIDATE_SCHEME, verify_admitted_request, verify_completed_job, verify_job_candidate,
)
from ddk.documents import read_json


REQUEST_SCHEME = "urn:docspec:managed-job-request:blake3"
TRANSPORT_SCHEME = "urn:ddk:docspec-request:sha256"
QUALIFICATION_SCHEME = "urn:docspec:accepted-qualification:blake3"
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ACTIONS = {"prepare", "inspect", "accept", "requalify", "select"}
_EXECUTION = {"pending": "pending", "unknown": "unknown", "failed": "failed", "completed": "succeeded"}


def _digest(value):
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _same_json(left, right):
    """Compare all request fields without equating JSON booleans and numbers."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return left == right


def verify_prepare_intent(expected, actual):
    _need(_same_json(expected, actual), "Native admission differs from the complete original prepare request")


def verify_native_identity(expected, actual):
    """An intended candidate constrains recovery without claiming observation."""
    _need(expected.get("request_digest") == actual.get("request_digest")
          and expected.get("candidate") == actual.get("candidate"),
          "Native receipt differs from the original requested native identity")


def native_job_candidate(workspace, reference):
    """Preserve the native candidate as a distinct DDK reference scheme."""
    return {
        "runtime": "docspec", "scheme": CANDIDATE_SCHEME, "schemeVersion": "1",
        "namespace": str(Path(workspace).resolve()), "digestAlgorithm": "blake3",
        "reference": verify_job_candidate(reference),
    }


def managed_job_context(workspace, request):
    _need(isinstance(request, dict) and request.get("action") in _ACTIONS,
          "Unsupported retained-job action")
    _need(all(isinstance(request.get(key), str) and _ID.fullmatch(request[key])
              for key in ("dataset", "operation")),
          "Retained job requires exact dataset and operation identifiers")
    return {
        "runtime": "docspec", "workspace": str(workspace), "dataset": request["dataset"],
        "operationId": request["operation"], "kind": "whole_job",
    }


def _pinned_receipt(reference, max_bytes):
    _need(isinstance(reference, dict) and isinstance(reference.get("path"), str)
          and Path(reference["path"]).is_absolute() and _digest(reference.get("sha256")),
          "Previous observation needs an exact receipt reference")
    document = read_json(reference["path"], max_bytes=max_bytes)
    _need(document.sha256 == reference["sha256"], "Previous retained-job receipt bytes changed")
    return document.value


def managed_job_prior(context, prior, *, max_bytes):
    if prior is None:
        return None, None, None, None
    _need(isinstance(prior, dict) and prior.get("operationContext") == context,
          "Previous retained-job receipt belongs to another native operation")
    operation = prior.get("operation")
    _need(isinstance(operation, dict) and operation.get("runtime") == "docspec"
          and operation.get("mode") == "managed_operation"
          and operation.get("operationId") == context["operationId"],
          "Previous receipt does not identify this retained native job")
    identity = operation.get("requestIdentity", {})
    _need(identity.get("scheme") in {REQUEST_SCHEME, TRANSPORT_SCHEME}
          and _digest(identity.get("value")), "Invalid previous retained-job request identity")
    record = _pinned_receipt(prior.get("evidence"), max_bytes)
    _need(record.get("operationContext") == context and record.get("operation") == operation,
          "Previous operation differs from its pinned receipt")
    original = None
    if reference := record.get("originalRequest"):
        original = {"reference": deepcopy(reference), "value": _pinned_receipt(reference, max_bytes)}
        _need(managed_job_context(context["workspace"], original["value"]) == context
              and original["value"]["action"] == "prepare",
              "Original request belongs to another retained job")
        if identity["scheme"] == TRANSPORT_SCHEME:
            _need(identity["value"] == reference["sha256"], "Original prepare request identity changed")
    constraint = None
    if reference := record.get("identityConstraint"):
        constraint = {"reference": deepcopy(reference), "value": _pinned_receipt(reference, max_bytes)}
        value = constraint["value"]
        _need(managed_job_context(context["workspace"], value) == context
              and value["action"] in {"accept", "select", "requalify"}
              and _digest(value.get("request_digest")), "Invalid original requested native identity")
        candidate = verify_job_candidate(value.get("candidate"))
        _need(candidate["dataset"] == context["dataset"] and candidate["operation"] == context["operationId"],
              "Requested candidate belongs to another retained job")
        if identity["scheme"] == TRANSPORT_SCHEME and original is None:
            _need(identity["value"] == reference["sha256"], "Original native action request identity changed")
    confirmation = None
    if candidate := operation.get("candidate"):
        _need(candidate == native_job_candidate(context["workspace"], candidate.get("reference")),
              "Previous receipt has a different native candidate scheme")
        _need(candidate["reference"]["dataset"] == context["dataset"]
              and candidate["reference"]["operation"] == context["operationId"],
              "Previous candidate belongs to another retained job")
        if record.get("result", {}).get("status") == "completed":
            confirmed = record
            confirmation = {key: prior["evidence"][key] for key in ("path", "sha256")}
        else:
            confirmation = record.get("confirmation")
            confirmed = _pinned_receipt(confirmation, max_bytes)
        _need(confirmed.get("operationContext") == context,
              "Earlier confirmed evidence belongs to another native operation")
        native = confirmed.get("result", {})
        validate_managed_job_response(context, {"action": "inspect"}, native, None,
                                      original_request=original["value"] if original else None,
                                      identity_constraint=constraint["value"] if constraint else None)
        _need(native.get("status") == "completed"
              and candidate["reference"] == native["candidate"]
              and identity == {"scheme": REQUEST_SCHEME, "value": native["request_digest"]}
              and operation.get("outputs") == _outputs(native),
              "Previous completion facts differ from retained native evidence")
        if operation.get("selection") == "selected":
            _need(native["selection"] == "selected", "Previous historical selection has no confirmed native evidence")
        if accepted := operation.get("acceptedQualification"):
            _need(accepted == {"scheme": QUALIFICATION_SCHEME,
                               "value": (native.get("accepted_qualification") or {}).get("identity")},
                  "Previous qualification differs from confirmed native evidence")
    return deepcopy(operation), deepcopy(confirmation), original, constraint


def _outputs(result):
    values = result.get("completed_outputs", [])
    _need(isinstance(values, list), "Retained outputs must be an ordered list")
    outputs, names = [], set()
    for value in values:
        _need(isinstance(value, dict), "Invalid retained output observation")
        name, path = value.get("name"), value.get("path")
        _need(isinstance(name, str) and name and name not in names
              and isinstance(path, str) and Path(path).is_absolute()
              and _digest(value.get("sha256"))
              and all(type(value.get(key)) is int and value[key] >= 0 for key in ("size", "rows")),
              "Invalid or repeated retained output identity")
        names.add(name)
        outputs.append({
            "kind": "dataset-snapshot", "path": path, "sha256": value["sha256"], "tool": "docspec",
            "attributes": {"name": name, "rows": value["rows"], "size": value["size"]},
        })
    return outputs


def validate_managed_job_response(context, request, result, prior, *, original_request=None, identity_constraint=None):
    """Validate observed metadata; never reopen a caller input or select a result."""
    _need(isinstance(result, dict) and result.get("dataset") == context["dataset"]
          and result.get("operation") == context["operationId"],
          "Native receipt identifies another retained job")
    _need(_digest(result.get("request_digest")) and result.get("status") in _EXECUTION
          and result.get("selection") in {"pending", "selected", "refused"},
          "Invalid retained-job status or original request identity")
    admitted = verify_admitted_request(result)
    if original_request is not None:
        verify_prepare_intent(original_request, admitted)
    if request.get("action") == "prepare":
        verify_prepare_intent(request, admitted)
    if identity_constraint is not None:
        verify_native_identity(identity_constraint, result)
    if request.get("request_digest") is not None:
        _need(request["request_digest"] == result["request_digest"],
              "Native receipt changed the original admitted request")
    if prior and prior["requestIdentity"]["scheme"] == REQUEST_SCHEME:
        _need(prior["requestIdentity"]["value"] == result["request_digest"],
              "Reconciliation returned another admitted request")
    if request.get("policy_id") is not None:
        _need(request["policy_id"] == result.get("policy_id"),
              "Native receipt returned another policy decision")
    _outputs(result)
    candidate = result.get("candidate")
    if candidate is not None:
        verify_job_candidate(candidate)
        _need(candidate["dataset"] == context["dataset"] and candidate["operation"] == context["operationId"],
              "Native candidate belongs to another retained job")
    if request.get("candidate") is not None:
        _need(candidate == request["candidate"], "Native receipt changed the requested candidate")
    if prior and prior.get("candidate"):
        _need(candidate == prior["candidate"]["reference"], "Reconciliation changed the retained candidate")
    if prior and prior.get("selection") == "selected":
        _need(result["selection"] == "selected", "Native receipt erased the original historical selection")
    if result["status"] == "completed":
        verify_completed_job(result, require_accepted=result["selection"] == "selected")
    else:
        _need(candidate is None and result.get("accepted_qualification") is None
              and result["selection"] != "selected", "Incomplete native execution cannot supply a qualified candidate")


def managed_job_operation(context, action, request_sha256, result, status, error, prior):
    """Keep command outcome, completed computation and selection independent."""
    native_request = result.get("request_digest")
    previous_candidate = prior.get("candidate") if prior else None
    execution = _EXECUTION.get(result.get("status"))
    if execution is None:
        execution = "succeeded" if previous_candidate else (
            "not_submitted" if status == "not_submitted" else "unknown"
        )
    selection = result.get("selection", "not_requested" if status == "not_submitted" else "unknown")
    if not result and prior and prior.get("selection") == "selected":
        selection = "selected"
    operation = {
        "runtime": "docspec", "mode": "managed_operation", "operationId": context["operationId"],
        "qualificationRequired": True,
        "requestIdentity": {"scheme": REQUEST_SCHEME, "value": native_request} if native_request else (
            deepcopy(prior["requestIdentity"]) if prior else {"scheme": TRANSPORT_SCHEME, "value": request_sha256}
        ),
        "reconciliation": "supported", "execution": execution, "selection": selection,
        "outputs": _outputs(result) if result else deepcopy(prior.get("outputs", [])) if prior else [],
    }
    if candidate := result.get("candidate"):
        operation["candidate"] = native_job_candidate(context["workspace"], candidate)
    elif previous_candidate:
        operation["candidate"] = deepcopy(previous_candidate)
    if accepted := result.get("accepted_qualification"):
        operation["acceptedQualification"] = {"scheme": QUALIFICATION_SCHEME, "value": accepted["identity"]}
    elif not result and prior and prior.get("acceptedQualification"):
        operation["acceptedQualification"] = deepcopy(prior["acceptedQualification"])
    if status == "unknown" or "unknown" in (execution, selection):
        operation["reason"] = error["message"] if error else "Native execution or selection has no confirmed outcome"
    elif result.get("status") == "pending":
        operation["reason"] = "The native operation is admitted; computation has not started"
    return operation
