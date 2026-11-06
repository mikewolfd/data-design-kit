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

from .documents import DocumentError, freeze_json, json_dumps, parse_json
from .arrow_observation import MANAGED_SCHEMA_V2, SchemaInterpretation

CANDIDATE_SCHEME = "urn:docspec:whole-job-candidate"
COMPLETION_PROFILE = "urn:docspec:whole-job-completion:1"
COUNTER_PROFILE = "urn:docspec:quality:native-sql-zero-counters:1"
COUNTER_EVALUATOR = {"id": "urn:docspec:evaluator:native-job-reports", "version": "1"}
COUNTER_SEMANTICS = {"id": "urn:docspec:semantics:complete-integer-zero-row", "revision": "1"}
VIEW_SECTIONS = ("inputs", "steps", "outputs", "reports")
VIEW_PROFILE = "urn:docspec:whole-job-view-set:1"
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
        return parse_json(raw)
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
    _require(manifest["profile"] == COMPLETION_PROFILE
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
    return freeze_json(request)


def _verify_admitted_inputs(request, manifest, views):
    _require(all(request["job"][key] == manifest["job"][key] for key in ("path", "sha256")),
             "Completion has a different original JobSpec artifact pin.")
    pins = {item["name"]: item["members"] for item in request["file_inputs"]}
    expected = {view["name"]: [{key: member[key] for key in ("key", "sha256", "size")} for member in view["files"]]
                for view in views["inputs"] if view["kind"] in {"parquet", "json_lines"}}
    _require(pins == expected, "Retained inputs differ from the complete original admitted file-member pins.")


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
    _require(views["profile"] == VIEW_PROFILE and reference["owner"] == manifest["dataset"]
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
                _verify_input(view)
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


def _verify_input(view):
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
        if kind == "version":
            version = _object(selector.get("version"), ("dataset", "version", "manifest"), "native input VersionRef")
            _require(isinstance(selector.get("workspace"), str) and Path(selector["workspace"]).is_absolute()
                     and all(isinstance(version[key], str) and _ID.fullmatch(version[key]) for key in ("dataset", "version")),
                     "Invalid original native VersionRef selector.")
            verify_object_reference(version["manifest"])


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


def interpret_output_schema(schema_bytes, declaration, *, profile=None):
    """Compare retained Arrow metadata to resolved ODCS; never inspect rows.

    This version closes field sets recursively, supports explicit primitive
    native types and the authored list/struct notation, and compares nullable
    supply to required fields. Value constraints and undeclared native field-ID
    conventions are outside this schema check, rather than silently passing.
    """
    if profile is not None:
        if profile != MANAGED_SCHEMA_V2:
            raise JobEvidenceError("DOCSPEC-SCHEMA-PROFILE", "Unsupported explicitly selected managed schema profile.", status="unknown")
        from .arrow_observation import observe_declaration
        pa, schema = _read_schema(schema_bytes)
        return observe_declaration(schema, declaration, pa)
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
