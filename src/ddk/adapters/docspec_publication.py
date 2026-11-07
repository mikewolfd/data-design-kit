"""Observe DocSpec's saved publication intent without publishing or owning it.

Native digests and lifecycle generations remain opaque owner-issued identities.
These checks compare the returned metadata and inline control bytes; they never
open output objects, decide retention, or contact a publisher.
"""

import base64
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
from uuid import UUID

from ddk.docspec_job_evidence import verify_job_candidate, verify_object_reference
from ddk.documents import json_dumps, read_json


INTENT_SCHEME = "urn:ddk:docspec-publication-intent"
TRANSPORT_SCHEME = "urn:ddk:docspec-request:sha256"
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_HEX = re.compile(r"[0-9a-f]{64}")


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _object(value, fields, label):
    _need(isinstance(value, dict) and set(value) == set(fields), f"Invalid publication {label}")
    return value


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _integer(value, *, minimum=0, ceiling=2**64):
    return type(value) is int and minimum <= value < ceiling


def _equal(left, right):
    # Preserve JSON integer tokens as well as boolean/number distinctions.
    return json_dumps(left) == json_dumps(right)


def publication_context(workspace, request):
    _need(isinstance(request, dict) and request.get("action") in {"freeze", "inspect"},
          "Unsupported publication-intent action")
    _need(all(isinstance(request.get(key), str) and _ID.fullmatch(request[key])
              for key in ("dataset", "operation")), "Publication intent requires exact dataset and operation identifiers")
    return {"runtime": "docspec", "workspace": str(workspace), "dataset": request["dataset"],
            "operationId": request["operation"], "kind": "publication_intent"}


def _record(value, key, *, table=None):
    _object(value, ("table", "table_uuid", "key", "revision"), "native record")
    try:
        native_uuid = UUID(value["table_uuid"])
        valid_uuid = str(native_uuid) == value["table_uuid"] and native_uuid.int != 0
    except (ValueError, TypeError, AttributeError):
        valid_uuid = False
    _need(isinstance(value["table"], str) and bool(value["table"]) and valid_uuid
          and value["key"] == key and _integer(value["revision"], minimum=1, ceiling=2**63),
          "Publication intent lacks an exact native table incarnation and generation")
    if table is not None:
        _need(all(value[field] == table[field] for field in ("table", "table_uuid")),
              "Publication records name different native table incarnations")
    return value


def native_intent(workspace, reference):
    _object(reference, ("dataset", "operation", "intent_digest", "native_record"), "intent reference")
    _need(all(isinstance(reference[key], str) and _ID.fullmatch(reference[key])
              for key in ("dataset", "operation")) and _digest(reference["intent_digest"]),
          "Invalid native publication identity")
    _record(reference["native_record"], f"job-publication-payload/{reference['operation']}")
    return {"runtime": "docspec", "scheme": INTENT_SCHEME, "schemeVersion": "1",
            "namespace": str(workspace), "digestAlgorithm": "blake3", "reference": deepcopy(reference)}


def _pin(value):
    _object(value, ("sha256", "size"), "byte pin")
    _need(_digest(value["sha256"]) and _integer(value["size"]), "Invalid publication byte identity")


def _bytes(value, pin):
    _pin(pin)
    _need(isinstance(value, str) and len(value) == 4 * ((pin["size"] + 2) // 3),
          "Publication inline bytes differ from their declared size")
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError("Invalid publication inline base64") from exc
    _need(base64.b64encode(raw).decode() == value and len(raw) == pin["size"]
          and sha256(raw).hexdigest() == pin["sha256"], "Publication inline bytes differ from their pin")


def _audit(context, value):
    _object(value, ("reference", "candidate", "job_request_digest", "policy_id", "accepted_qualification", "epoch",
                    "selection", "acceptance", "completion", "scope", "release_id", "inventory_digest", "controls",
                    "expected_pointer", "pointer", "payload_digest"), "audit")
    wrapped = native_intent(context["workspace"], value["reference"])
    reference = wrapped["reference"]
    _need(reference["dataset"] == context["dataset"] and reference["operation"] == context["operationId"],
          "Publication intent belongs to another native operation")
    candidate = verify_job_candidate(value["candidate"])
    _need(candidate["dataset"] == context["dataset"] and candidate["operation"] == context["operationId"],
          "Publication candidate belongs to another producing job")
    _need(all(_digest(value[key]) for key in ("job_request_digest", "accepted_qualification", "release_id",
                                             "inventory_digest", "payload_digest"))
          and isinstance(value["policy_id"], str) and _ID.fullmatch(value["policy_id"])
          and _integer(value["epoch"]), "Invalid publication audit identities")
    table = reference["native_record"]
    operation = context["operationId"]
    completion = _record(value["completion"], f"job-result/{operation}", table=table)
    acceptance = _record(value["acceptance"], f"job-accepted/{operation}/{value['policy_id']}", table=table)
    selection = _record(value["selection"], f"job-selected/{operation}", table=table)
    _need(completion["revision"] < acceptance["revision"] < selection["revision"] < table["revision"],
          "Publication audit generations do not preserve native decision order")
    scope = _object(value["scope"], ("kind", "publisher", "bucket", "release_prefix", "pointer_key"), "scope")
    _need(scope["kind"] == "local_fixture" and all(isinstance(scope[key], str) and scope[key]
          for key in ("publisher", "bucket", "release_prefix", "pointer_key")), "Unsupported publication scope")
    controls = value["controls"]
    _need(isinstance(controls, list), "Publication controls must be an ordered list")
    names = set()
    for control in controls:
        _object(control, ("name", "content_type", "bytes"), "control pin")
        _need(isinstance(control["name"], str) and control["name"] and control["name"] not in names
              and isinstance(control["content_type"], str) and control["content_type"], "Invalid publication control")
        names.add(control["name"])
        _pin(control["bytes"])
    _need("manifest.json" in names, "Publication manifest control is missing")
    condition = value["expected_pointer"]
    _need(isinstance(condition, dict) and condition.get("kind") in {"absent", "present"},
          "Invalid original publication pointer condition")
    if condition["kind"] == "absent":
        _object(condition, ("kind",), "absent pointer")
    else:
        _object(condition, ("kind", "etag", "bytes"), "predecessor pointer")
        _need(isinstance(condition["etag"], str) and bool(condition["etag"]), "Missing opaque publisher token")
        _pin(condition["bytes"])
    pointer = _object(value["pointer"], ("content_type", "cache_control", "bytes"), "pointer pin")
    _need(all(isinstance(pointer[key], str) and pointer[key] for key in ("content_type", "cache_control")),
          "Invalid pointer headers")
    _pin(pointer["bytes"])
    return wrapped


def _payload(context, audit, payload):
    _object(payload, ("outputs", "controls_base64", "predecessor_bytes_base64", "pointer_bytes_base64"), "payload")
    _need(isinstance(payload["outputs"], list) and isinstance(payload["controls_base64"], list)
          and len(payload["controls_base64"]) == len(audit["controls"]), "Incomplete publication inventory")
    names = set()
    for output in payload["outputs"]:
        _object(output, ("name", "object", "sha256", "md5", "rows", "disposition"), "output")
        native = verify_object_reference(output["object"])
        _need(native["owner"] == context["dataset"] and isinstance(output["name"], str) and output["name"]
              and output["name"] not in names and _digest(output["sha256"])
              and isinstance(output["md5"], str) and re.fullmatch(r"[0-9a-f]{32}", output["md5"])
              and _integer(output["rows"]), "Invalid sealed publication output")
        names.add(output["name"])
        disposition = output["disposition"]
        _need(isinstance(disposition, dict) and disposition.get("kind") in {"private", "published"},
              "Invalid publication output disposition")
        if disposition["kind"] == "private":
            _object(disposition, ("kind",), "private disposition")
        else:
            _object(disposition, ("kind", "name", "content_type"), "published disposition")
            _need(all(isinstance(disposition[key], str) and disposition[key] for key in ("name", "content_type")),
                  "Invalid published output name or type")
    for control, encoded in zip(audit["controls"], payload["controls_base64"]):
        _bytes(encoded, control["bytes"])
    condition = audit["expected_pointer"]
    if condition["kind"] == "present":
        _bytes(payload["predecessor_bytes_base64"], condition["bytes"])
    else:
        _need(payload["predecessor_bytes_base64"] is None, "Absent pointer cannot carry predecessor bytes")
    _bytes(payload["pointer_bytes_base64"], audit["pointer"]["bytes"])


def _freeze_matches(request, audit, payload):
    for field in ("candidate", "job_request_digest", "policy_id", "accepted_qualification", "scope", "release_id"):
        _need(_equal(request.get(field), audit[field]), "Native publication audit differs from the original freeze request")
    _need(type(request.get("expected_epoch")) is int and request["expected_epoch"] == audit["epoch"]
          and type(request.get("expected_selection_revision")) is int
          and request["expected_selection_revision"] == audit["selection"]["revision"],
          "Native publication audit differs from the original selection generation")
    controls = request.get("controls")
    _need(isinstance(controls, list) and len(controls) == len(audit["controls"]), "Original control inventory changed")
    for expected, observed in zip(controls, audit["controls"]):
        _need(isinstance(expected, dict) and isinstance(expected.get("artifact"), dict)
              and expected.get("name") == observed["name"] and expected.get("content_type") == observed["content_type"]
              and type(expected.get("size")) is int and expected["size"] == observed["bytes"]["size"]
              and expected["artifact"].get("sha256") == observed["bytes"]["sha256"], "Original control pin changed")
    expected_pointer = request.get("expected_pointer")
    _need(isinstance(expected_pointer, dict) and expected_pointer.get("kind") == audit["expected_pointer"]["kind"],
          "Original publisher condition changed")
    if expected_pointer["kind"] == "present":
        _need(expected_pointer.get("etag") == audit["expected_pointer"]["etag"], "Original publisher token changed")
        _bytes(expected_pointer.get("bytes_base64"), audit["expected_pointer"]["bytes"])
    pointer = request.get("pointer")
    _need(isinstance(pointer, dict) and all(pointer.get(key) == audit["pointer"][key]
          for key in ("content_type", "cache_control")), "Original pointer headers changed")
    _bytes(pointer.get("bytes_base64"), audit["pointer"]["bytes"])
    if payload is not None:
        _need(_equal(request.get("outputs"), payload["outputs"]), "Original publication output inventory changed")


def validate_publication_response(context, request, result, *, original_request=None, prior_result=None):
    _object(result, ("dataset", "operation", "status", "intent", "payload", "external_authorization", "dispatch"), "receipt")
    _need(result["dataset"] == context["dataset"] and result["operation"] == context["operationId"],
          "Native receipt identifies another publication operation")
    _need(result["external_authorization"] == result["dispatch"] == "not_run",
          "Local publication intent cannot establish external authorization or dispatch")
    status = result["status"]
    _need(status in {"not_found", "retained", "retired"}, "Invalid publication-intent state")
    if status == "not_found":
        _need(request["action"] == "inspect" and result["intent"] is None and result["payload"] is None,
              "Invalid absent publication observation")
        _need(prior_result is None or prior_result["intent"] is None,
              "Native absence cannot erase a previously verified saved intent")
        return
    _audit(context, result["intent"])
    if status == "retained":
        _payload(context, result["intent"], result["payload"])
    else:
        _need(result["payload"] is None, "Retired publication payload must be absent")
    if prior_result is not None and prior_result["intent"] is not None:
        _need(_equal(prior_result["intent"], result["intent"]), "Native publication audit changed after it was saved")
        _need(not (prior_result["status"] == "retired" and status == "retained"),
              "An exact retired publication generation cannot become retained again")
    freeze = request if request["action"] == "freeze" else original_request
    if freeze is not None:
        _freeze_matches(freeze, result["intent"], result["payload"])


def _pinned(reference, max_bytes):
    _need(isinstance(reference, dict) and isinstance(reference.get("path"), str)
          and Path(reference["path"]).is_absolute() and _digest(reference.get("sha256")),
          "Publication recovery requires an exact retained receipt pin")
    document = read_json(reference["path"], max_bytes=max_bytes, preserve_integral_decimals=True)
    _need(document.sha256 == reference["sha256"], "Retained publication receipt bytes changed")
    return document.value


def publication_prior(context, request, prior, *, max_metadata_bytes, max_native_bytes):
    if prior is None:
        return None, None, None
    _need(isinstance(prior, dict) and prior.get("operationContext") == context,
          "Previous observation belongs to another publication operation")
    record = _pinned(prior.get("evidence"), max_metadata_bytes)
    operation = prior.get("operation")
    _need(record.get("operationContext") == context and isinstance(operation, dict)
          and record.get("operation") == operation and isinstance(operation.get("publicationIntent"), dict)
          and operation.get("operationId") == context["operationId"], "Previous observation is not a publication intent")
    original = None
    if reference := record.get("originalRequest"):
        original = {"reference": deepcopy(reference), "value": _pinned(reference, max_metadata_bytes)}
        _need(publication_context(context["workspace"], original["value"]) == context
              and original["value"]["action"] == "freeze", "Original freeze belongs to another native operation")
        if request["action"] == "freeze":
            _need(_equal(request, original["value"]), "Replay requires the complete original freeze request")
    publication = operation["publicationIntent"]
    confirmed = None
    if saved := publication.get("savedIntent"):
        _need(saved == native_intent(context["workspace"], saved.get("reference")), "Previous native intent wrapper changed")
        observed = _pinned(publication.get("evidence"), max_native_bytes)
        validate_publication_response(context, {"action": "inspect"}, observed,
                                      original_request=original["value"] if original else None)
        _need(observed["intent"] is not None and observed["intent"]["reference"] == saved["reference"],
              "Previous saved intent differs from pinned native evidence")
        confirmed = {"reference": deepcopy(publication["evidence"]),
                     "value": {"intent": observed["intent"], "status": observed["status"]}}
    elif original is not None and request["action"] == "inspect":
        raise ValueError("Replay the exact original freeze request before reconciling its unconfirmed saved identity")
    return deepcopy(operation), confirmed, original


def publication_operation(context, action, request_sha256, result, status, error, prior, native_evidence):
    publication = {"action": action, "outcome": "unknown"}
    if status == "succeeded" and result:
        publication["outcome"] = "not_found" if result["status"] == "not_found" else "succeeded"
        publication["evidence"] = deepcopy(native_evidence)
        if result["intent"] is not None:
            publication["savedIntent"] = native_intent(context["workspace"], result["intent"]["reference"])
            publication["payloadState"] = result["status"]
    else:
        publication["outcome"] = "not_submitted" if status == "not_submitted" else "refused" if status == "failed" else "unknown"
        previous = prior.get("publicationIntent", {}) if prior else {}
        if "savedIntent" in previous:
            publication.update(savedIntent=deepcopy(previous["savedIntent"]), payloadState="unknown",
                               evidence=deepcopy(previous["evidence"]))
    operation = {"runtime": "docspec", "mode": "managed_operation", "operationId": context["operationId"],
                 "requestIdentity": {"scheme": TRANSPORT_SCHEME, "value": request_sha256},
                 "reconciliation": "supported", "execution": "not_requested", "selection": "not_requested",
                 "outputs": [], "publicationIntent": publication}
    if publication["outcome"] == "unknown":
        operation["reason"] = (error or {}).get("message", "Native publication-intent outcome is unknown")
    return operation
