"""Verify retained DocSpec whole-job metadata without opening execution payloads.

This module checks the consistency and identity of explicitly admitted native
records. DocSpec remains the authority for execution, protection and acceptance.
An unkeyed digest establishes record identity, not an independent attestation.
"""

import base64
import binascii
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import UUID

from .documents import DocumentError, freeze_json, json_dumps, parse_json
from .interfaces import json_equal

CANDIDATE_SCHEME = "urn:docspec:whole-job-candidate"
COMPLETION_PROFILE = "urn:docspec:whole-job-completion:1"
SNAPSHOT_COMPLETION_PROFILE = "urn:docspec:whole-job-completion:2"
PRODUCER_COMPLETION_PROFILE = "urn:docspec:whole-job-completion:3"
COUNTER_PROFILE = "urn:docspec:quality:native-sql-zero-counters:1"
COUNTER_EVALUATOR = {"id": "urn:docspec:evaluator:native-job-reports", "version": "1"}
COUNTER_SEMANTICS = {"id": "urn:docspec:semantics:complete-integer-zero-row", "revision": "1"}
VIEW_SECTIONS = ("inputs", "steps", "outputs", "reports")
VIEW_PROFILE = "urn:docspec:whole-job-view-set:1"
SNAPSHOT_VIEW_PROFILE = "urn:docspec:whole-job-view-set:2"
PRODUCER_VIEW_PROFILE = "urn:docspec:whole-job-view-set:3"
SNAPSHOT_CUSTODY_PROFILE = "urn:docspec:whole-job-snapshot-custody:2"
INPUT_CUSTODY_SCHEME = "urn:docspec:whole-job-input-custody"
INPUT_CUSTODY_GRANT_PROFILE = "urn:docspec:whole-job-input-custody-grant:1"
PRODUCER_ADOPTION_SCHEME = "urn:docspec:whole-job-producer-adoption"
PRODUCER_PREREQUISITE_PROFILE = "urn:docspec:whole-job-producer-prerequisite:1"
_PRODUCER_EVIDENCE_PROFILES = {
    "proof": "urn:docspec:whole-job-producer-static:1",
    "model": "urn:docspec:whole-job-producer-prerequisite-grant:1",
}
_VIEW_PROFILES = {COMPLETION_PROFILE: VIEW_PROFILE, SNAPSHOT_COMPLETION_PROFILE: SNAPSHOT_VIEW_PROFILE,
                  PRODUCER_COMPLETION_PROFILE: PRODUCER_VIEW_PROFILE}
_SNAPSHOT_COMPLETION_PROFILES = {SNAPSHOT_COMPLETION_PROFILE, PRODUCER_COMPLETION_PROFILE}
_SNAPSHOT_ROLES = {"metadata", "manifest_list", "manifest", "data", "position_deletes", "equality_deletes"}
ACCEPTANCE_FIELDS = ("profile", "dataset", "operation", "request_digest", "candidate", "view_set_digest", "policy_id",
                     "policy_sha256", "expected_epoch", "expected_selection", "evaluator", "semantics", "reports")
_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class JobEvidenceError(ValueError):
    def __init__(self, code, message, *, status="failed"):
        super().__init__(message)
        self.code = code
        self.status = status


def _require(condition, message, *, code="DOCSPEC-JOB-EVIDENCE"):
    if not condition:
        raise JobEvidenceError(code, message)


def _object(value, fields, context):
    _require(isinstance(value, dict) and set(fields) <= value.keys(), f"Incomplete {context} metadata.")
    return value


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _input_custody_reference(value, owner):
    """Validate an opaque native handle without resolving or rehashing its body."""
    fields = {"scheme", "scheme_version", "dataset", "operation", "request_digest", "input", "native_record", "admission_digest"}
    _object(value, fields, "native input-custody reference")
    _require(set(value) == fields and value["scheme"] == INPUT_CUSTODY_SCHEME and value["scheme_version"] == "1"
             and all(isinstance(value[key], str) and _ID.fullmatch(value[key]) for key in ("dataset", "operation"))
             and value["dataset"] == owner and _digest(value["request_digest"])
             and isinstance(value["input"], str) and bool(value["input"]), "Invalid native input-custody identity or owner.")
    record = _object(value["native_record"], ("table", "table_uuid", "key", "revision"), "input-custody record")
    _require(set(record) == {"table", "table_uuid", "key", "revision"}
             and isinstance(record["table"], str) and bool(record["table"]) and _uuid(record["table_uuid"])
             and isinstance(record["key"], str)
             and re.fullmatch(r"job-input/" + re.escape(value["operation"]) + r"/(?:0|[1-9][0-9]*)", record["key"])
             and _integer(record["revision"], 1) and record["revision"] < 2**63,
             "Input custody requires an exact native table incarnation and input generation.")
    digest = _object(value["admission_digest"], ("algorithm", "value"), "input-admission digest")
    _require(set(digest) == {"algorithm", "value"} and digest["algorithm"] == "blake3" and _digest(digest["value"]),
             "Input custody requires its original opaque native BLAKE3 digest.")
    return value


def _blake3(data):
    try:
        from blake3 import blake3
    except ImportError as exc:
        raise JobEvidenceError("DOCSPEC-JOB-DIGEST-UNAVAILABLE", "Retained job verification requires the maintained blake3 library.",
                               status="unknown") from exc
    return blake3(data).hexdigest()


def _decode(value, context):
    _require(isinstance(value, str), f"The {context} needs original base64 bytes.")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise JobEvidenceError("DOCSPEC-JOB-EVIDENCE", f"Invalid {context} base64.") from exc


def _json(raw, context):
    try:
        # Native integer fields distinguish 1 from 1.0. General document
        # validation normalizes mathematical integers for JSON Schema instead.
        return parse_json(raw, preserve_integral_decimals=True)
    except (DocumentError, ValueError) as exc:
        raise JobEvidenceError("DOCSPEC-JOB-EVIDENCE", f"Invalid retained {context} JSON.") from exc


def _artifact(envelope, context, *, reference=None):
    _object(envelope, ("reference", "sha256", "bytes_base64"), context)
    actual_reference = verify_object_reference(envelope["reference"])
    raw = _decode(envelope["bytes_base64"], context)
    _require((reference is None or actual_reference == reference) and len(raw) == actual_reference["bytes"]
             and _digest(envelope["sha256"]) and sha256(raw).hexdigest() == envelope["sha256"]
             and _blake3(raw) == actual_reference["digest"], f"The retained {context} bytes differ from their native identity.")
    return _json(raw, context), raw, actual_reference


def verify_object_reference(value):
    """Validate a native ObjectRef without opening its path."""
    _object(value, ("owner", "path", "digest", "bytes"), "native object reference")
    _require(set(value) == {"owner", "path", "digest", "bytes"}
             and isinstance(value["owner"], str) and _ID.fullmatch(value["owner"])
             and isinstance(value["path"], str) and Path(value["path"]).is_absolute()
             and _digest(value["digest"]) and _integer(value["bytes"]), "Invalid native object reference.")
    return deepcopy(value)


def verify_job_candidate(value):
    """Validate the distinct whole-job candidate, never a source VersionRef."""
    _object(value, ("scheme", "scheme_version", "dataset", "operation", "manifest"), "whole-job candidate")
    _require(set(value) == {"scheme", "scheme_version", "dataset", "operation", "manifest"}
             and value["scheme"] == CANDIDATE_SCHEME and value["scheme_version"] == "1"
             and all(isinstance(value[key], str) and _ID.fullmatch(value[key]) for key in ("dataset", "operation")),
             "Invalid whole-job candidate identity.")
    verify_object_reference(value["manifest"])
    _require(value["manifest"]["owner"] == value["dataset"], "Candidate manifest belongs to a different native owner.")
    return deepcopy(value)


def _named(rows, context):
    _require(isinstance(rows, list), f"The {context} needs ordered named records.")
    names = []
    for row in rows:
        _object(row, ("name",), context)
        _require(isinstance(row["name"], str) and row["name"], f"Invalid {context} name.")
        names.append(row["name"])
    _require(len(set(names)) == len(names), f"Duplicate {context} member.")
    return {row["name"]: row for row in rows}


def _schemas(manifest):
    schemas = manifest["schemas"]
    _require(isinstance(schemas, dict), "Completion schemas need their native digest dictionary.")
    decoded = {}
    for digest, encoded in schemas.items():
        raw = _decode(encoded, "native schema")
        _require(_digest(digest) and sha256(raw).hexdigest() == digest, "Native schema bytes differ from their SHA-256 key.")
        _read_schema(raw)
        decoded[digest] = raw
    for section in VIEW_SECTIONS:
        for view in manifest[section]:
            _require(_digest(view.get("schema_sha256")) and view["schema_sha256"] in decoded,
                     f"A completed {section} member has no exact native schema.")
    return decoded


def _outputs(rows):
    _named(rows, "completed output")
    for row in rows:
        _object(row, ("path", "sha256", "md5", "size", "rows", "footer_bytes", "schema_sha256"), "completed output")
        _require(isinstance(row["path"], str) and Path(row["path"]).is_absolute()
                 and _digest(row["sha256"]) and _digest(row["schema_sha256"])
                 and isinstance(row["md5"], str) and re.fullmatch(r"[0-9a-f]{32}", row["md5"])
                 and all(_integer(row[key]) for key in ("size", "rows", "footer_bytes")), "Invalid completed output identity.")


def verify_completed_outputs(rows):
    """Validate known sealed output descriptors, without asserting job completion."""
    _outputs(rows)
    return freeze_json(deepcopy(rows))


def _reports(rows):
    _named(rows, "completed report")
    for row in rows:
        _object(row, ("sql_sha256", "schema_sha256", "rows", "data", "completion"), "completed report")
        _require(_digest(row["sql_sha256"]) and _digest(row["schema_sha256"])
                 and _integer(row["rows"]) and isinstance(row["data"], list)
                 and row["rows"] == len(row["data"]), "Invalid completed report identity or row count.")
        verify_object_reference(row["completion"])


@dataclass(frozen=True)
class VerifiedJobEvidence:
    candidate: dict
    manifest: dict
    manifest_bytes: bytes
    manifest_reference: dict
    view_set: dict
    view_set_bytes: bytes
    admitted_request: dict
    policy: dict
    accepted: dict | None

    @property
    def view_names(self):
        return {section: tuple(row["name"] for row in self.manifest[section]) for section in VIEW_SECTIONS}


def producer_model_bindings(proof, *, prerequisite_inputs):
    """Compose model inputs from an already verified, accepted producer proof.

    Return independent ``inputs``, ``schemas`` and native ``request`` values.
    ``prerequisite_inputs`` preserves the caller's adopted-definition order,
    which may differ from the proof's input order. The caller supplies receiving
    owner/operation and authority conditions and checks its model inventory.
    DocSpec resolves the adoption, custody and prerequisite when admitting it.
    This helper opens no files and establishes no new acceptance or availability.
    """
    _require(isinstance(proof, VerifiedJobEvidence) and proof.accepted is not None
             and proof.manifest.get("profile") == PRODUCER_COMPLETION_PROFILE
             and proof.manifest.get("producer_evidence", {}).get("role") == "proof",
             "Model bindings require a verified accepted producer proof.")
    views = proof.view_set["inputs"]
    _require(isinstance(prerequisite_inputs, (list, tuple))
             and all(isinstance(name, str) for name in prerequisite_inputs)
             and len(prerequisite_inputs) == len(views)
             and len(set(prerequisite_inputs)) == len(prerequisite_inputs)
             and set(prerequisite_inputs) == {view["name"] for view in views},
             "Model bindings require the complete unique adopted input order.")
    schema_by_name = {item["name"]: item["schema_sha256"] for item in proof.manifest["inputs"]}
    return deepcopy({
        "inputs": [view["selector"] for view in views],
        "schemas": {view["name"]: proof.manifest["schemas"][schema_by_name[view["name"]]] for view in views},
        "request": {
            "producer_adoption": proof.manifest["producer_evidence"]["adoption"],
            "snapshot_inputs": [{"name": view["name"],
                                 "metadata_sha256": view["snapshot_custody"]["metadata_sha256"],
                                 "metadata_size": view["snapshot_custody"]["metadata_size"],
                                 "reuse_from": view["custody_reference"]} for view in views],
            "prerequisites": [{"profile": PRODUCER_PREREQUISITE_PROFILE,
                               "candidate": proof.candidate,
                               "accepted_qualification": proof.accepted["identity"],
                               "inputs": list(prerequisite_inputs)}],
        },
    })


def verify_completed_job(result, *, require_accepted=False):
    """Check retained exact completion bytes and any attached native acceptance.

    The caller supplies an explicitly pinned native receipt. No caller JobSpec,
    input file, retained output or native object path is opened here.
    """
    _object(result, ("dataset", "operation", "request_digest", "status", "candidate", "view_set_digest", "policy_id",
                     "accepted_qualification", "selection", "completed_outputs", "completed_reports", "completion_manifest", "policy", "admitted_request"),
            "native whole-job receipt")
    _require(result["status"] == "completed", "The native job has no sealed complete candidate.")
    candidate = verify_job_candidate(result["candidate"])
    _require(candidate["dataset"] == result["dataset"] and candidate["operation"] == result["operation"]
             and _digest(result["request_digest"]) and _digest(result["view_set_digest"])
             and isinstance(result["policy_id"], str) and _ID.fullmatch(result["policy_id"]),
             "The receipt and candidate identify different native work.")
    manifest, raw, reference = _artifact(result["completion_manifest"], "completion manifest", reference=candidate["manifest"])
    _object(manifest, ("profile", "dataset", "operation", "request_digest", "job", "view_set", "view_set_digest", "schemas",
                       "execution", "evaluator", "runtime", "result", "admitted_request", *VIEW_SECTIONS),
            "whole-job completion")
    _require(isinstance(manifest["profile"], str) and manifest["profile"] in _VIEW_PROFILES
             and manifest["execution"] == "completed" and manifest["evaluator"] == COUNTER_EVALUATOR
             and isinstance(manifest["runtime"], dict) and bool(manifest["runtime"])
             and all(manifest[key] == result[key] for key in ("dataset", "operation", "request_digest", "view_set_digest")),
             "The completion belongs to different native work or an unsupported profile.")
    job = _object(manifest["job"], ("path", "sha256", "size"), "original job identity")
    _require(isinstance(job["path"], str) and _digest(job["sha256"]) and _integer(job["size"], 1),
             "The completion has no exact original JobSpec identity.")
    for section in VIEW_SECTIONS:
        _named(manifest[section], f"completion {section}")
    _outputs(manifest["outputs"])
    _reports(manifest["reports"])
    _require(manifest["outputs"] == result["completed_outputs"] and manifest["reports"] == result["completed_reports"],
             "Receipt output/report membership differs from the complete retained candidate.")
    schemas = _schemas(manifest)
    view_set, view_bytes, view_reference = _artifact(manifest["view_set"], "whole view set")
    _verify_views(view_set, view_reference, manifest)
    _verify_job_result(result, manifest)
    admitted_request = verify_admitted_request(result)
    _require(manifest["admitted_request"] == result["admitted_request"], "Completion changes its original admitted request witness.")
    _verify_admitted_inputs(admitted_request, manifest, view_set)
    _verify_input_custody(result, admitted_request, manifest, view_set)
    _verify_producer_evidence(result, admitted_request, manifest, view_set)
    policy = _verify_policy(result["policy"], result, manifest)
    accepted = result["accepted_qualification"]
    if accepted is not None:
        _verify_acceptance(accepted, result, manifest, schemas, policy)
    elif require_accepted:
        raise JobEvidenceError("DOCSPEC-JOB-ACCEPTANCE-MISSING", "The completed native candidate has no accepted qualification.",
                               status="not_run")
    if admitted_request["policy_id"] == result["policy_id"]:
        _require(admitted_request["policy"]["sha256"] == result["policy"]["sha256"],
                 "The original policy ID has different admitted policy bytes.")
        if accepted is not None:
            _require(all(admitted_request[key] == accepted[key] for key in ("expected_epoch", "expected_selection")),
                     "The original policy ID has different accepted authority conditions.")
    _require(isinstance(result["selection"], str) and result["selection"] in {"pending", "selected", "refused"},
             "Unsupported native selection observation.")
    _require(result["selection"] != "selected" or accepted is not None, "Native selection lacks its accepted qualification.")
    return VerifiedJobEvidence(freeze_json(candidate), freeze_json(manifest), raw, freeze_json(reference),
                               freeze_json(view_set), view_bytes,
                               admitted_request,
                               freeze_json(policy),
                               freeze_json(deepcopy(accepted)))


def verify_admitted_request(result):
    """Verify and decode original prepare metadata without reopening artifacts."""
    _object(result, ("dataset", "operation", "admitted_request"), "native original request observation")
    request, _raw, reference = _artifact(result["admitted_request"], "original admitted prepare request")
    _object(request, ("action", "dataset", "operation", "definition", "job", "file_inputs", "policy_id", "policy",
                      "expected_epoch", "expected_selection"), "original admitted prepare request")
    _require(request["action"] == "prepare" and request["dataset"] == result["dataset"]
             and request["operation"] == result["operation"] and reference["owner"] == result["dataset"]
             and isinstance(request["definition"], str) and bool(request["definition"])
             and isinstance(request["policy_id"], str) and _ID.fullmatch(request["policy_id"])
             and _integer(request["expected_epoch"]) and request["expected_epoch"] < 2**64,
             "Original prepare witness identifies different native work or authority.")
    for key in ("job", "policy"):
        artifact = _object(request[key], ("path", "sha256"), f"original {key} artifact pin")
        _require(isinstance(artifact["path"], str) and bool(artifact["path"]) and _digest(artifact["sha256"]),
                 f"Invalid original {key} artifact pin.")
    if request["expected_selection"] is not None:
        verify_job_candidate(request["expected_selection"])
    _named(request["file_inputs"], "original file-input pin")
    for item in request["file_inputs"]:
        _object(item, ("members",), "original file-input pin")
        _require(isinstance(item["members"], list), "Original file-input pins need complete member identities.")
        keys = []
        for member in item["members"]:
            _object(member, ("key", "sha256", "size"), "original file member pin")
            _require((member["key"] is None or isinstance(member["key"], str))
                     and _digest(member["sha256"]) and _integer(member["size"]), "Invalid original file member pin.")
            keys.append(member["key"])
        _require(len(keys) == len(set(keys)), "Original file-input pins repeat a member key.")
    snapshots = _named(request.get("snapshot_inputs", []), "original snapshot-input pin")
    _require(not snapshots.keys() & {item["name"] for item in request["file_inputs"]},
             "Original snapshot and file input names overlap.")
    for item in snapshots.values():
        fields = {"name", "metadata_sha256", "metadata_size"}
        _require(set(item) in (fields, fields | {"reuse_from"})
                 and _digest(item["metadata_sha256"]) and _integer(item["metadata_size"], 1)
                 and item["metadata_size"] < 2**64, "Invalid original snapshot metadata pin.")
        if "reuse_from" in item:
            _input_custody_reference(item["reuse_from"], request["dataset"])
    return freeze_json(request)


def _verify_admitted_inputs(request, manifest, views):
    _require(all(request["job"][key] == manifest["job"][key] for key in ("path", "sha256")),
             "Completion has a different original JobSpec artifact pin.")
    pins = {item["name"]: item["members"] for item in request["file_inputs"]}
    expected = {view["name"]: [{key: member[key] for key in ("key", "sha256", "size")} for member in view["files"]]
                for view in views["inputs"] if view["kind"] in {"parquet", "json_lines"}}
    _require(pins == expected, "Retained inputs differ from the complete original admitted file-member pins.")
    snapshots = {item["name"]: item for item in request.get("snapshot_inputs", [])}
    if manifest["profile"] in _SNAPSHOT_COMPLETION_PROFILES:
        expected = {view["name"]: {"name": view["name"],
                                  "metadata_sha256": view["snapshot_custody"]["metadata_sha256"],
                                  "metadata_size": view["snapshot_custody"]["metadata_size"]}
                    for view in views["inputs"] if view["kind"] == "native_table"}
        pins = {name: {key: value for key, value in item.items() if key != "reuse_from"} for name, item in snapshots.items()}
        _require(bool(snapshots) and pins == expected,
                 "Snapshot custody differs from the complete original native-table pins.")
    else:
        _require(not snapshots, "Version 1 completion cannot establish snapshot custody.")


def _verify_input_custody(result, request, manifest, views):
    """Check bound complete observations; native grants own actual availability."""
    pins = {item["name"]: item for item in request.get("snapshot_inputs", [])}
    references = []
    native_count = 0
    for index, (view, completed) in enumerate(zip(views["inputs"], manifest["inputs"])):
        native = manifest["profile"] in _SNAPSHOT_COMPLETION_PROFILES and view["kind"] == "native_table"
        native_count += int(native)
        for key in ("custody_reference", "custody_grant"):
            _require((key in view) == (key in completed), "Input custody must be bound in both complete witnesses.")
            if key in view:
                _require(native and json_equal(view[key], completed[key]),
                         "Input custody differs between witnesses or uses an unsupported input profile.")
        if "custody_reference" in view:
            for item in (view, completed):
                reference = _input_custody_reference(item["custody_reference"], manifest["dataset"])
                _require(reference["operation"] == manifest["operation"] and reference["request_digest"] == manifest["request_digest"]
                         and reference["input"] == view["name"]
                         and reference["native_record"]["key"] == f"job-input/{manifest['operation']}/{index}",
                         "A bound custody reference must identify the current operation's exact input row.")
            references.append(view["custody_reference"])
        pin = pins.get(view["name"], {})
        _require(("reuse_from" in pin) == ("custody_grant" in view),
                 "Custody reuse requires exactly the grant requested in the original admission.")
        if "custody_grant" in view:
            _require("custody_reference" in view, "A custody grant requires its current completed input reference.")
            for item in (view, completed):
                grant = _object(item["custody_grant"], ("profile", "source"), "bound input-custody grant")
                _require(set(grant) == {"profile", "source"} and grant["profile"] == INPUT_CUSTODY_GRANT_PROFILE,
                         "Unsupported native input-custody grant.")
                source = _input_custody_reference(grant["source"], manifest["dataset"])
                current = item["custody_reference"]
                _require(all(source["native_record"][key] == current["native_record"][key] for key in ("table", "table_uuid")),
                         "Same-owner custody reuse must retain the native lifecycle table incarnation.")
                _require(json_equal(grant["source"], pin["reuse_from"]),
                         "The complete custody grant differs from the original requested native handle.")
    if references:
        _require(len(references) == native_count, "New custody references must cover every native input.")
        _require(len({(item["native_record"]["table"], item["native_record"]["table_uuid"]) for item in references}) == 1,
                 "Current input references identify conflicting native lifecycle tables.")
        receipt = result.get("input_custody")
        _require(isinstance(receipt, list) and json_equal(receipt, references),
                 "Receipt custody references differ from the complete bound input membership or order.")
        for reference in receipt:
            _input_custody_reference(reference, manifest["dataset"])
    else:
        _require("input_custody" not in result, "A historical candidate cannot gain unbound custody handles.")


def _producer_adoption(value, owner):
    """Check an opaque native adoption identity without resolving its authority."""
    fields = {"scheme", "scheme_version", "dataset", "adoption", "request_digest", "native_record", "definition_sha256"}
    _object(value, fields, "native producer adoption")
    _require(set(value) == fields and value["scheme"] == PRODUCER_ADOPTION_SCHEME and value["scheme_version"] == "1"
             and value["dataset"] == owner
             and isinstance(value["adoption"], str) and _ID.fullmatch(value["adoption"])
             and _digest(value["request_digest"]) and _digest(value["definition_sha256"]),
             "Invalid native producer adoption identity or owner.")
    record = _object(value["native_record"], ("table", "table_uuid", "key", "revision"), "producer adoption record")
    _require(set(record) == {"table", "table_uuid", "key", "revision"}
             and isinstance(record["table"], str) and bool(record["table"]) and _uuid(record["table_uuid"])
             and UUID(record["table_uuid"]).int != 0
             and record["key"] == f"job-producer-adoption/{value['adoption']}"
             and _integer(record["revision"], 1) and record["revision"] < 2**63,
             "Producer adoption requires its exact native table incarnation and decision generation.")
    return value


def _verify_producer_evidence(result, request, manifest, views):
    """Bind v3 native evidence bytes; static checks and grant resolution stay native."""
    if manifest["profile"] != PRODUCER_COMPLETION_PROFILE:
        _require(all(key not in document for document in (manifest, views)
                     for key in ("producer_evidence", "producer_evidence_witness"))
                 and request.get("producer_adoption") is None and request.get("producer_records", []) == []
                 and request.get("prerequisites", []) == [],
                 "Earlier completion profiles cannot establish producer evidence or prerequisites.")
        return
    evidence = _object(manifest.get("producer_evidence"), ("adoption", "role", "evidence"), "native producer evidence")
    role = evidence["role"]
    _require(isinstance(role, str) and role in _PRODUCER_EVIDENCE_PROFILES,
             "Unsupported native producer evidence role.")
    fields = {"adoption", "role", "evidence"} | ({"prerequisite"} if role == "model" else set())
    _require(set(evidence) == fields and json_equal(views.get("producer_evidence"), evidence)
             and "producer_evidence_witness" not in views,
             "Complete native producer evidence must agree in the completion and view set.")
    adoption = _producer_adoption(evidence["adoption"], manifest["dataset"])
    _require(json_equal(request.get("producer_adoption"), adoption) and request["policy_id"] == result["policy_id"],
             "Producer evidence changes the original adoption or fixed role policy.")
    for copy in (views["producer_evidence"]["adoption"], request["producer_adoption"]):
        _producer_adoption(copy, manifest["dataset"])
    pointer = _object(evidence["evidence"], ("reference", "sha256"), "native producer evidence identity")
    witness = _object(manifest.get("producer_evidence_witness"), ("reference", "sha256", "bytes_base64"),
                      "native producer evidence witness")
    _require(set(pointer) == {"reference", "sha256"} and set(witness) == {"reference", "sha256", "bytes_base64"}
             and witness["sha256"] == pointer["sha256"], "Producer evidence needs one exact retained byte witness.")
    for copy in (pointer, views["producer_evidence"]["evidence"]):
        verify_object_reference(copy["reference"])
    body, _raw, reference = _artifact(witness, "producer evidence", reference=pointer["reference"])
    _object(body, ("profile", "dataset", "operation", "request_digest", "adoption"), "native producer evidence body")
    _require(reference["owner"] == manifest["dataset"] and body["profile"] == _PRODUCER_EVIDENCE_PROFILES[role]
             and all(body[key] == manifest[key] for key in ("dataset", "operation", "request_digest"))
             and json_equal(body["adoption"], adoption),
             "Retained producer evidence belongs to different native work or adoption.")
    _producer_adoption(body["adoption"], manifest["dataset"])
    native_inputs = [view for view in views["inputs"] if view["kind"] == "native_table"]
    _require(bool(native_inputs) and all("custody_reference" in view for view in native_inputs),
             "Producer evidence requires current custody references for every native input.")
    for view in native_inputs:
        record = view["custody_reference"]["native_record"]
        _require(all(record[key] == adoption["native_record"][key] for key in ("table", "table_uuid")),
                 "Producer adoption and input custody identify different native lifecycle tables.")
    if role == "proof":
        _require(request.get("prerequisites", []) == [] and request["file_inputs"] == []
                 and isinstance(request.get("producer_records"), list) and bool(request["producer_records"])
                 and len(native_inputs) == len(views["inputs"]) and not views["outputs"]
                 and result["selection"] != "selected" and "prerequisite" not in body,
                 "Producer proof cannot export, select, consume files or inherit a model prerequisite.")
        return
    prerequisite = _object(evidence["prerequisite"], ("profile", "candidate", "accepted_qualification", "inputs"),
                           "native producer prerequisite")
    names = prerequisite["inputs"]
    _require(set(prerequisite) == {"profile", "candidate", "accepted_qualification", "inputs"}
             and prerequisite["profile"] == PRODUCER_PREREQUISITE_PROFILE
             and _digest(prerequisite["accepted_qualification"])
             and isinstance(names, list) and all(isinstance(name, str) for name in names)
             and len(names) == len(set(names)) and set(names) == {view["name"] for view in native_inputs}
             and json_equal(request.get("prerequisites"), [prerequisite])
             and json_equal(body.get("prerequisite"), prerequisite) and request.get("producer_records", []) == [],
             "Model producer evidence changes its complete original prerequisite or input scope.")
    donor = verify_job_candidate(prerequisite["candidate"])
    for copy in (views["producer_evidence"]["prerequisite"], request["prerequisites"][0], body["prerequisite"]):
        verify_job_candidate(copy["candidate"])
    _require(donor["dataset"] == manifest["dataset"] and donor["operation"] != manifest["operation"],
             "The model prerequisite must identify a distinct same-owner proof operation.")
    for view in native_inputs:
        source = view.get("custody_grant", {}).get("source")
        _require(isinstance(source, dict) and source["operation"] == donor["operation"] and source["input"] == view["name"],
                 "The model must use the proof candidate's exact same-name native input custody.")


def _verify_policy(witness, result, manifest):
    policy, _raw, reference = _artifact(witness, "admitted counter policy")
    _object(policy, ("id", "profile", "evaluator", "semantics", "job_sha256", "view_names", "required_reports"), "counter policy")
    _require(reference["owner"] == manifest["dataset"] and policy["id"] == result["policy_id"]
             and policy["profile"] == COUNTER_PROFILE and policy["evaluator"] == COUNTER_EVALUATOR
             and policy["semantics"] == COUNTER_SEMANTICS and policy["job_sha256"] == manifest["job"]["sha256"],
             "The retained policy binds different native job, profile or evaluator.")
    _require(policy["view_names"] == {section: [row["name"] for row in manifest[section]] for section in VIEW_SECTIONS},
             "The retained policy omits or changes complete native view membership.")
    required = _named(policy["required_reports"], "policy required report")
    reports = _named(manifest["reports"], "completed report")
    _require(bool(required) and required.keys() <= reports.keys(), "The retained policy names no reports or an absent report.")
    for name, rule in required.items():
        _object(rule, ("sql_sha256", "schema_ipc_base64"), "required report policy")
        _require(rule["sql_sha256"] == reports[name]["sql_sha256"], "The retained report uses different original rule SQL.")
        _same_schema(_decode(rule["schema_ipc_base64"], "expected report schema"),
                     _decode(manifest["schemas"][reports[name]["schema_sha256"]], "actual report schema"))
    return policy


def _read_schema(raw):
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise JobEvidenceError("DOCSPEC-JOB-SCHEMA-UNAVAILABLE", "Native counter verification requires maintained PyArrow.",
                               status="unknown") from exc
    try:
        return pa, pa.ipc.read_schema(pa.BufferReader(raw))
    except (ValueError, pa.ArrowException) as exc:
        raise JobEvidenceError("DOCSPEC-JOB-EVIDENCE", "Invalid native IPC counter schema.") from exc


def _same_schema(expected, actual):
    _pa, expected_schema = _read_schema(expected)
    _pa, actual_schema = _read_schema(actual)
    _require(expected_schema.equals(actual_schema, check_metadata=True), "Actual native counter schema differs from the admitted policy.")


def _verify_views(views, reference, manifest):
    _object(views, ("profile", "dataset", "operation", "request_digest", *VIEW_SECTIONS), "whole view set")
    _require(views["profile"] == _VIEW_PROFILES[manifest["profile"]] and reference["owner"] == manifest["dataset"]
             and reference["digest"] == manifest["view_set_digest"]
             and all(views[key] == manifest[key] for key in ("dataset", "operation", "request_digest")),
             "The complete native view-set identity disagrees with its completion.")
    for section in VIEW_SECTIONS:
        _named(views[section], f"view-set {section}")
        _require([row["name"] for row in views[section]] == [row["name"] for row in manifest[section]],
                 f"The complete view set has different ordered {section} membership.")
        for view, completed in zip(views[section], manifest[section]):
            keys = set(view) & set(completed)
            _require(all(view[key] == completed[key] for key in keys), f"A native {section} view differs from its completion.")
            _require(_digest(view.get("schema_sha256")) and view["schema_sha256"] in manifest["schemas"],
                     "A native view omits its exact schema interpretation.")
            if section == "inputs":
                _object(view, ("kind", "selector", "files", "admission"), "admitted input")
                verify_object_reference(view["admission"])
                snapshot_profile = manifest["profile"] in _SNAPSHOT_COMPLETION_PROFILES
                if snapshot_profile:
                    fields = ("kind", "selector", "files", "schema_sha256", "admission")
                    _object(completed, fields, "completed input")
                    verify_object_reference(completed["admission"])
                    _require(all(json_equal(view[key], completed[key]) for key in fields)
                             and view["admission"]["owner"] == manifest["dataset"],
                             "Snapshot input admission differs from its native completion owner.")
                if snapshot_profile and view["kind"] == "native_table":
                    _require("snapshot_custody" in view and "snapshot_custody" in completed
                             and json_equal(view["snapshot_custody"], completed["snapshot_custody"]),
                             "Snapshot custody must agree in the complete candidate and view set.")
                else:
                    _require("snapshot_custody" not in view and "snapshot_custody" not in completed,
                             "Snapshot custody requires a supported native-table completion profile.")
                if snapshot_profile:
                    _verify_input(completed, snapshot_profile=True, owner=manifest["dataset"])
                _verify_input(view, snapshot_profile=snapshot_profile, owner=manifest["dataset"])
            elif section == "steps":
                _object(view, ("material_identity", "completion", "dependencies"), "completed step")
                if view["completion"] is not None:
                    verify_object_reference(view["completion"])
            else:
                _object(view, ("completion",), "completed native phase")
                verify_object_reference(view["completion"])
                if section == "outputs":
                    _object(view, ("settings",), "native output settings")
                else:
                    _object(view, ("dependencies",), "native report dependencies")


def _verify_input(view, *, snapshot_profile=False, owner=None):
    selector = _object(view["selector"], ("kind", "name"), "original native input selector")
    _require(isinstance(view["kind"], str) and selector["kind"] == view["kind"] and selector["name"] == view["name"]
             and isinstance(view["files"], list), "Input admission changes its original selector identity.")
    for member in view["files"]:
        _object(member, ("key", "path", "sha256", "size", "retained"), "admitted file member")
        retained = verify_object_reference(member["retained"])
        _require(isinstance(member["path"], str) and Path(member["path"]).is_absolute()
                 and _digest(member["sha256"]) and _integer(member["size"])
                 and retained["bytes"] == member["size"], "Invalid retained native file member identity.")
    kind = view["kind"]
    if kind == "parquet":
        _require(len(view["files"]) == 1 and view["files"][0]["key"] is None
                 and view["files"][0]["path"] == selector.get("path"), "Parquet admission omits or changes its exact member.")
    elif kind == "json_lines":
        declared = selector.get("files")
        actual = [{"key": item["key"], "path": item["path"]} for item in view["files"]]
        _require(declared == actual and all(isinstance(item["key"], str) for item in view["files"])
                 and len({item["key"] for item in view["files"]}) == len(actual),
                 "JSON Lines admission changes complete original member keys, order or paths.")
    else:
        _require(kind in {"native_table", "iceberg", "version"} and not view["files"],
                 "Unsupported native input selector or unexpected file replacement.")
        if snapshot_profile:
            _require(kind == "native_table", "Version 2 custody requires the native-table selector.")
            _verify_snapshot_custody(view, owner)
        if kind == "version":
            version = _object(selector.get("version"), ("dataset", "version", "manifest"), "native input VersionRef")
            _require(isinstance(selector.get("workspace"), str) and Path(selector["workspace"]).is_absolute()
                     and all(isinstance(version[key], str) and _ID.fullmatch(version[key]) for key in ("dataset", "version")),
                     "Invalid original native VersionRef selector.")
            verify_object_reference(version["manifest"])


def _absolute_native_uri(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    if Path(value).is_absolute():
        return True
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme and parsed.path.startswith("/") and not parsed.query and not parsed.fragment
                    and (parsed.scheme == "file" or parsed.netloc))
    except ValueError:
        return False


def _verify_snapshot_custody(view, owner):
    """Check native custody metadata; native seals establish actual read closure."""
    selector = view["selector"]
    _require(set(selector) == {"kind", "name", "metadata_location", "table_uuid", "snapshot", "schema_id"},
             "Snapshot custody requires an exact native-table selector.")
    _require(_uuid(selector["table_uuid"]) and _absolute_native_uri(selector["metadata_location"])
             and (selector["snapshot"] is None or (_integer(selector["snapshot"]) and selector["snapshot"] < 2**63))
             and _integer(selector["schema_id"]) and selector["schema_id"] < 2**31,
             "Invalid native table UUID, snapshot, schema or metadata location.")
    custody = _object(view["snapshot_custody"], ("profile", "scope", "metadata_sha256", "metadata_size", "objects"),
                      "snapshot custody")
    _require(set(custody) == {"profile", "scope", "metadata_sha256", "metadata_size", "objects"}
             and custody["profile"] == SNAPSHOT_CUSTODY_PROFILE and custody["scope"] == "selected_snapshot"
             and _digest(custody["metadata_sha256"]) and _integer(custody["metadata_size"], 1)
             and custody["metadata_size"] < 2**64 and isinstance(custody["objects"], list),
             "Unsupported or invalid snapshot custody scope.")
    uris, metadata = [], []
    for item in custody["objects"]:
        _object(item, ("uri", "role", "sha256", "size", "retained", "origin_operation"), "snapshot object")
        retained = verify_object_reference(item["retained"])
        _require(set(item) == {"uri", "role", "sha256", "size", "retained", "origin_operation"}
                 and _absolute_native_uri(item["uri"]) and isinstance(item["role"], str) and item["role"] in _SNAPSHOT_ROLES
                 and _digest(item["sha256"]) and _integer(item["size"]) and item["size"] < 2**64
                 and retained["bytes"] == item["size"] and retained["owner"] == owner
                 and isinstance(item["origin_operation"], str) and _ID.fullmatch(item["origin_operation"]),
                 "Invalid original snapshot object identity, size or native owner.")
        uris.append(item["uri"])
        if item["role"] == "metadata":
            metadata.append(item)
    _require(uris == sorted(set(uris)), "Snapshot custody requires sorted, unique original object URIs.")
    _require(len(metadata) == 1 and metadata[0]["uri"] == selector["metadata_location"]
             and metadata[0]["sha256"] == custody["metadata_sha256"]
             and metadata[0]["size"] == custody["metadata_size"],
             "Snapshot custody must preserve its one exact original metadata object.")
    _require((len(custody["objects"]) == 1) if selector["snapshot"] is None
             else sum(item["role"] == "manifest_list" for item in custody["objects"]) == 1,
             "Exact empty selection retains only metadata; a selected snapshot requires one manifest list.")


def _verify_job_result(result, manifest):
    job_result = _object(manifest["result"], ("outputs", "steps"), "retained native JobResult")
    _require(result.get("result") == job_result, "The returned JobResult differs from the retained native completion.")
    outputs = _named(job_result["outputs"], "JobResult output")
    _require(list(outputs) == [row["name"] for row in manifest["outputs"]], "JobResult has different ordered output membership.")
    for completed in manifest["outputs"]:
        native = outputs[completed["name"]]
        _require(all(native.get(key) == completed[key] for key in ("sha256", "md5", "size", "rows", "footer_bytes")),
                 "JobResult output content identity differs from its retained output.")
    queries = _named(job_result.get("queries", []), "JobResult query")
    _require(list(queries) == [row["name"] for row in manifest["reports"]], "JobResult has different ordered report membership.")
    _require(all(queries[row["name"]].get("data") == row["data"] for row in manifest["reports"]),
             "JobResult query data differs from its retained report.")


def _verify_acceptance(accepted, result, manifest, schemas, policy):
    _object(accepted, (*ACCEPTANCE_FIELDS, "identity", "body_sha256", "body_bytes_base64", "native_record", "policy"),
            "native accepted qualification")
    body_raw = _decode(accepted["body_bytes_base64"], "accepted qualification body")
    _require(_digest(accepted["body_sha256"]) and sha256(body_raw).hexdigest() == accepted["body_sha256"]
             and _blake3(body_raw) == accepted["identity"], "Accepted native body bytes differ from their exact identity.")
    body = _json(body_raw, "accepted qualification body")
    _require(isinstance(body, dict) and set(body) == set(ACCEPTANCE_FIELDS)
             and body == {key: accepted[key] for key in ACCEPTANCE_FIELDS}, "Accepted native body disagrees with the returned record.")
    _require(_digest(accepted["identity"]) and accepted["profile"] == COUNTER_PROFILE
             and all(accepted[key] == result[key] for key in ("dataset", "operation", "request_digest"))
             and accepted["candidate"] == result["candidate"] and accepted["view_set_digest"] == result["view_set_digest"]
             and accepted["policy_id"] == result["policy_id"] and _digest(accepted["policy_sha256"])
             and accepted["policy"] == result["policy"] and accepted["policy_sha256"] == result["policy"]["sha256"]
             and accepted["evaluator"] == COUNTER_EVALUATOR and accepted["semantics"] == COUNTER_SEMANTICS,
             "Native acceptance binds different candidate, rules, evaluator or semantics.")
    _require(_integer(accepted["expected_epoch"]) and accepted["expected_epoch"] < 2**64,
             "Native acceptance has no exact expected authority epoch.")
    if accepted["expected_selection"] is not None:
        verify_job_candidate(accepted["expected_selection"])
    native_record = _object(accepted["native_record"], ("table", "key", "revision"), "native accepted-record location")
    _require(all(isinstance(native_record[key], str) and native_record[key] for key in ("table", "key"))
             and native_record["key"] == f"job-accepted/{result['operation']}/{result['policy_id']}"
             and _integer(native_record["revision"], 1), "Native acceptance lacks an exact retained record location.")
    reports = _named(accepted["reports"], "accepted required report")
    _require(list(reports) == [rule["name"] for rule in policy["required_reports"]],
             "Native acceptance omits, duplicates or reorders admitted required reports.")
    native_reports = _named(manifest["reports"], "retained report")
    for name, report in reports.items():
        native = native_reports.get(name)
        _object(report, ("sql_sha256", "completion", "schema_sha256", "checks"), "accepted report")
        _require(native is not None and all(report[key] == native[key] for key in ("sql_sha256", "completion", "schema_sha256")),
                 "An accepted report differs from the exact retained report completion.")
        _verify_counter_row(report, native, schemas[report["schema_sha256"]])


def _verify_counter_row(accepted, native, schema_bytes):
    pa, schema = _read_schema(schema_bytes)
    columns = schema.names
    _require(bool(columns) and len(columns) == len(set(columns)) and all(pa.types.is_integer(field.type) for field in schema),
             "A required native counter schema is not a complete unique integer schema.")
    _require(native["rows"] == 1 and len(native["data"]) == 1 and isinstance(native["data"][0], dict)
             and set(native["data"][0]) == set(columns), "A required native counter report lacks one exact complete row.")
    checks = accepted["checks"]
    _require(isinstance(checks, list) and len(checks) == len(columns)
             and [check.get("column") for check in checks if isinstance(check, dict)] == columns,
             "Accepted counter outcomes omit, duplicate or reorder required columns.")
    for column, check in zip(columns, checks):
        value = native["data"][0][column]
        _require(type(value) is int and value == 0 and check.get("status") == "passed"
                 and type(check.get("value")) is int and check["value"] == value,
                 "Native acceptance lacks an exact passed zero-integer outcome.")


@dataclass(frozen=True)
class SchemaInterpretation:
    status: str
    reasons: tuple
    fields: tuple
    obligations: tuple


def interpret_output_schema(schema_bytes, declaration):
    """Compare retained Arrow metadata to resolved ODCS; never inspect rows.

    This version closes field sets recursively, supports explicit primitive
    native types and the authored list/struct notation, and compares nullable
    supply to required fields. Value constraints and undeclared native field-ID
    conventions are outside this schema check, rather than silently passing.
    """
    from .definitions import enum_values

    pa, schema = _read_schema(schema_bytes)
    findings, mappings, obligations = [], [], []

    def note(status, reason):
        findings.append((status, reason))

    def obligation(facet, path, reason):
        obligations.append(freeze_json({"facet": facet, "paths": [deepcopy(path)], "reason": reason}))

    def restrictions(node, path):
        reason = "Authored value constraints require their own exact evidence; Arrow schema does not evaluate them."
        if node.get("unique"):
            obligation("key_unique", path, reason)
        if enum_values(node) is not None:
            obligation("enum", path, reason)
        for index, _rule in enumerate(node.get("quality", [])):
            obligation(f"quality/{index}", path, reason)
        if node.get("relationships"):
            obligation("relationships", path, reason)
        for key, value in node.get("logicalTypeOptions", {}).items():
            binary_format = (key == "format" and value == "binary" and isinstance(node.get("physicalType"), str)
                             and re.fullmatch(r"fixed\[\d+\]", node["physicalType"]))
            if not binary_format:
                obligation(f"logicalTypeOptions/{key}", path, reason)
        for item in node.get("customProperties", []):
            if re.sub(r"[^a-z]", "", str(item.get("property", "")).lower()) in {"nativefieldid", "fieldid", "icebergfieldid"}:
                note("unknown", "An authored native field-ID mapping has no selected supported interpretation.")

    def physical(node, actual):
        spelling = node.get("physicalType")
        logical = node.get("logicalType")
        if spelling is None:
            return
        if not isinstance(spelling, str):
            note("unknown", "An authored physical type has no supported interpretation.")
            return
        text = spelling.strip().lower()
        if logical == "object" and text.startswith("struct<"):
            children = node.get("properties", [])
            if all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", child["name"]) and isinstance(child.get("physicalType"), str) for child in children):
                expected = "struct<" + ",".join(child["name"] + " " + child["physicalType"] for child in children) + ">"
                if re.sub(r"\s+", "", spelling) != re.sub(r"\s+", "", expected):
                    note("failed", "Authored struct physical spelling disagrees with its own child definitions.")
            else:
                note("unknown", "A struct physical spelling cannot be fully compared to its authored children.")
            return
        if logical == "array" and text.startswith("list<"):
            child = node.get("items", {})
            expected = "list<" + str(child.get("physicalType", "")) + ">"
            if not child.get("physicalType"):
                note("unknown", "A list physical spelling has no complete authored element type.")
            elif re.sub(r"\s+", "", spelling) != re.sub(r"\s+", "", expected):
                note("failed", "Authored list physical spelling disagrees with its own element definition.")
            return
        if text in {"object", "struct", "table"} and logical == "object":
            return
        if text in {"array", "list"} and logical == "array":
            return
        if text in {"string", "utf8", "dict"}:
            matches = pa.types.is_string(actual) or pa.types.is_large_string(actual) or pa.types.is_string_view(actual)
        elif text in {"boolean", "bool"}:
            matches = pa.types.is_boolean(actual)
        elif match := re.fullmatch(r"fixed\[(\d+)\]", text):
            matches = pa.types.is_fixed_size_binary(actual) and actual.byte_width == int(match[1])
        elif match := re.fullmatch(r"timestamp<(second|millisecond|microsecond|nanosecond),([^<>]+)>", spelling):
            units = {"second": "s", "millisecond": "ms", "microsecond": "us", "nanosecond": "ns"}
            matches = pa.types.is_timestamp(actual) and actual.unit == units[match[1]] and actual.tz == match[2]
        elif text == "timestamp":
            note("unknown", "Timestamp interpretation requires explicit native unit and timezone semantics.")
            return
        else:
            aliases = {"date32": pa.date32(), "date64": pa.date64(), "binary": pa.binary(), "large_binary": pa.large_binary()}
            expected = aliases.get(text)
            if expected is None:
                try:
                    expected = pa.type_for_alias(text)
                except ValueError:
                    note("unknown", "An authored physical type is outside the selected Arrow mapping profile.")
                    return
            matches = actual == expected
        if not matches:
            note("failed", "A retained native field has a different explicit physical type.")

    def visit(node, field, logical_path, native_path, position):
        restrictions(node, logical_path)
        actual = field.type
        if pa.types.is_dictionary(actual):
            actual = actual.value_type
        logical = node.get("logicalType")
        mappings.append(freeze_json({"logicalPath": logical_path, "nativePath": native_path, "position": position,
                                     "nativeType": str(field.type), "nullable": field.nullable}))
        if node.get("required", False) and field.nullable:
            obligation("required", logical_path, "Nullable Arrow metadata does not establish the authored nonnull row obligation.")
        binary = pa.types.is_binary(actual) or pa.types.is_large_binary(actual) or pa.types.is_fixed_size_binary(actual)
        physical_binary = isinstance(node.get("physicalType"), str) and (node["physicalType"].startswith("fixed[") or node["physicalType"] in {"binary", "large_binary"})
        compatible = {
            "string": pa.types.is_string(actual) or pa.types.is_large_string(actual) or pa.types.is_string_view(actual) or (binary and physical_binary),
            "integer": pa.types.is_integer(actual), "boolean": pa.types.is_boolean(actual),
            "date": pa.types.is_date(actual), "timestamp": pa.types.is_timestamp(actual),
            "object": pa.types.is_struct(actual), "array": pa.types.is_list(actual) or pa.types.is_large_list(actual),
            "number": pa.types.is_integer(actual) or pa.types.is_floating(actual) or pa.types.is_decimal(actual),
        }
        if logical not in compatible:
            note("unknown", "An authored logical type is outside the selected Arrow mapping profile.")
            return
        if not compatible[logical]:
            note("failed", "A retained native field has a different logical type or nested shape.")
            return
        if logical in {"number", "timestamp"} and not node.get("physicalType"):
            note("unknown", "A numeric or timestamp interpretation requires an explicit native physical type.")
        physical(node, actual)
        if logical == "object":
            fields(node.get("properties", []), actual, logical_path, native_path)
        elif logical == "array":
            if not isinstance(node.get("items"), dict):
                note("unknown", "An authored array has no complete element definition.")
            else:
                visit(node["items"], actual.value_field, [*logical_path, {"each": True}], [*native_path, {"each": True}], 0)

    def fields(declarations, actual_fields, logical_path, native_path):
        expected = {node.get("physicalName", node["name"]): node for node in declarations}
        observed = {field.name: (index, field) for index, field in enumerate(actual_fields)}
        if len(expected) != len(declarations) or len(observed) != len(actual_fields) or set(expected) != set(observed):
            note("failed", "Retained native fields are extra, missing or ambiguous within an authored struct.")
        for name, node in expected.items():
            if name in observed:
                index, field = observed[name]
                visit(node, field, [*logical_path, {"field": node["name"]}], [*native_path, {"field": name}], index)

    restrictions(declaration, [])
    fields(declaration.get("properties", []), schema, [], [])
    status = "failed" if any(item[0] == "failed" for item in findings) else "unknown" if findings else "passed"
    return SchemaInterpretation(status, tuple(dict.fromkeys(reason for _status, reason in findings)), tuple(mappings), tuple(obligations))


def native_export_uniqueness(evidence, original_job, output, paths, interpretation, tool):
    """Interpret profile-1 export's complete visible sort tuple, never a subset."""
    runtime = evidence.manifest["runtime"]
    if (original_job is None or interpretation.status != "passed" or evidence.manifest["profile"] != COMPLETION_PROFILE
            or runtime.get("processor") != "docspec.whole-job.v1" or not _digest(tool.get("distributionSha256"))
            or runtime.get("binary_sha256") != tool["distributionSha256"]
            or not paths or any(len(path) != 1 or "field" not in path[0] for path in paths)):
        return None
    original = next((item for item in original_job["outputs"] if item["name"] == output), None)
    retained = next((item for item in evidence.view_set["outputs"] if item["name"] == output), None)
    if original is None or retained is None:
        return None
    settings = _export_settings(original.get("settings"))
    if settings is None or settings != _export_settings(retained.get("settings")):
        return None
    pa, schema = _read_schema(_decode(evidence.manifest["schemas"][retained["schema_sha256"]], "export schema"))
    if settings["columns"] and settings["columns"] != schema.names:
        return None
    mapped = {json_dumps(field["logicalPath"]): field for field in interpretation.fields}
    names = []
    for path in paths:
        field = mapped.get(json_dumps(path))
        if field is None or len(field["nativePath"]) != 1 or "field" not in field["nativePath"][0]:
            return None
        name = field["nativePath"][0]["field"]
        if schema.names.count(name) != 1:
            return None
        kind = schema.field(name).type
        if not (pa.types.is_integer(kind) or pa.types.is_boolean(kind) or pa.types.is_string(kind)
                or pa.types.is_large_string(kind) or pa.types.is_date(kind) or pa.types.is_fixed_size_binary(kind)):
            return None
        names.append(name)
    if len(set(names)) != len(names) or names != [sort["field"] for sort in settings["order_by"]]:
        return None
    return {"profile": "urn:ddk:interpretation:docspec-ordered-export:1", "output": output,
            "completion": deepcopy(retained["completion"]), "schemaSha256": retained["schema_sha256"],
            "sortFields": names, "jobSha256": evidence.manifest["job"]["sha256"]}


def _export_settings(value):
    """Only the frozen native profile-1 defaults/set semantics are normalized."""
    fields = {"profile", "row_group_rows", "order_by", "columns", "dictionary_columns", "delta_columns", "key_column", "created_by", "footer_limit"}
    if not isinstance(value, dict) or set(value) - fields or fields - {"columns"} - value.keys():
        return None
    result = deepcopy(value)
    if (not isinstance(result["profile"], str) or result["profile"] not in {"whole", "ranged", "lookup"}
            or not isinstance(result["order_by"], list) or not result["order_by"]
            or not _integer(result["row_group_rows"], 1) or not _integer(result["footer_limit"], 1)
            or not isinstance(result["created_by"], str) or not result["created_by"]):
        return None
    order = []
    for sort in result["order_by"]:
        if (not isinstance(sort, dict) or set(sort) - {"field", "direction", "nulls"}
                or not isinstance(sort.get("field"), str) or not sort["field"]
                or not isinstance(sort.get("direction", "asc"), str) or sort.get("direction", "asc") not in {"asc", "desc"}
                or not isinstance(sort.get("nulls", "nulls_last"), str) or sort.get("nulls", "nulls_last") not in {"nulls_first", "nulls_last"}):
            return None
        order.append({"field": sort["field"], "direction": sort.get("direction", "asc"), "nulls": sort.get("nulls", "nulls_last")})
    result["order_by"] = order
    result.setdefault("columns", [])
    for name in ("columns", "dictionary_columns", "delta_columns"):
        if (not isinstance(result[name], list) or not all(isinstance(item, str) for item in result[name])
                or len(set(result[name])) != len(result[name])):
            return None
        if name != "columns":
            result[name] = sorted(result[name])
    return result
