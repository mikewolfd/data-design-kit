"""Independent metadata examples; these do not establish native execution."""

import base64
from copy import deepcopy
from hashlib import sha256
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ddk.catalog_access import CatalogError
from ddk.catalog import assemble_catalog
from ddk.catalog_managed_jobs import DEFINITION_SCHEME, _input_versions, managed_execution, managed_job_definition, managed_job_metadata
from ddk.catalog_metadata import LOCAL_ADAPTER, LocalMetadata
from ddk.catalog_native_rules import NativeRuleBinding, native_rule_artifact
from ddk.core import load_project
from ddk.docspec_job_evidence import (
    ACCEPTANCE_FIELDS, CANDIDATE_SCHEME, COMPLETION_PROFILE, COUNTER_EVALUATOR,
    COUNTER_PROFILE, COUNTER_SEMANTICS, VIEW_PROFILE, SNAPSHOT_COMPLETION_PROFILE, SNAPSHOT_VIEW_PROFILE,
    PRODUCER_COMPLETION_PROFILE, PRODUCER_VIEW_PROFILE, PRODUCER_PREREQUISITE_PROFILE,
    SNAPSHOT_CUSTODY_PROFILE, JobEvidenceError, verify_admitted_request, verify_completed_job,
)
from ddk.documents import json_dumps, read_json, schema_registry, schema_validator, validate_document


def _raw(value):
    return json.dumps(value, separators=(",", ":")).encode()


def _reference(path, raw=b"native phase identity"):
    blake3 = pytest.importorskip("blake3").blake3
    return {"owner": "archive", "path": str(path), "digest": blake3(raw).hexdigest(), "bytes": len(raw)}


def _witness(path, value):
    raw = _raw(value)
    return {"reference": _reference(path, raw), "sha256": sha256(raw).hexdigest(),
            "bytes_base64": base64.b64encode(raw).decode()}


def _acceptance(body, policy):
    raw = _raw(body)
    blake3 = pytest.importorskip("blake3").blake3
    return {**deepcopy(body), "identity": blake3(raw).hexdigest(), "body_sha256": sha256(raw).hexdigest(),
            "body_bytes_base64": base64.b64encode(raw).decode(), "policy": deepcopy(policy),
            "native_record": {"table": "archive/native-lifecycle", "key": f"job-accepted/{body['operation']}/{body['policy_id']}", "revision": 3}}


def _mapping_kwargs():
    return {"production": "summarize", "inputs": {"source": "orders"}, "outputs": {"public.parquet": "daily-revenue"},
            "out_of_catalog": {"inputs": [], "outputs": [{"name": "private.parquet", "reason": "Internal recovery output."}]}}


def _original_job(tmp_path):
    settings = {"profile": "whole", "row_group_rows": 128, "order_by": [], "columns": [], "dictionary_columns": [],
                "delta_columns": [], "key_column": None, "created_by": "Independent metadata fixture", "footer_limit": 65536}
    return {"scratch": str(tmp_path / "scratch"),
            "inputs": [{"kind": "parquet", "name": "source", "path": str(tmp_path / "never-open-original.parquet")}],
            "steps": [{"name": "shared_join", "sql": "SELECT id FROM source", "materialize": True}],
            "outputs": [{"name": name, "path": str(tmp_path / "caller" / name), "sql": "SELECT id FROM shared_join", "settings": settings}
                        for name in ("public.parquet", "private.parquet")],
            "queries": [{"name": "invariants", "sql": 'SELECT COUNT(*) AS orphan_count FROM outputs."public.parquet" WHERE "id" IS NULL'},
                        {"name": "metadata_counts", "sql": "SELECT COUNT(*) AS population FROM shared_join"}]}


def _policy_check(checks):
    return next(row for row in checks if row["rule"]["id"].startswith("urn:ddk:docspec-native-policy:"))


class _FixtureRuleProfile:
    """Independent tiny concrete generator; no actual application qualification."""

    identity = {"id": "urn:test:native-output-counters", "version": "1"}

    def __init__(self, source):
        self.source = source

    def publication_checks(self, context):
        fields = context.datasets["daily-revenue"]["properties"]
        primary = sorted((field for field in fields if field.get("primaryKey")), key=lambda field: field.get("primaryKeyPosition", -1))
        paths = tuple((({"field": field["name"]},)) for field in primary)
        bindings = []
        if primary:
            names = ','.join('"' + field["name"] + '"' for field in primary)
            nulls = ' OR '.join('"' + field["name"] + '" IS NULL' for field in primary)
            sql = f'SELECT COUNT(*) AS orphan_count FROM (SELECT {names} FROM outputs."public.parquet" GROUP BY {names} HAVING COUNT(*)>1 OR {nulls}) invalid_keys'
            for facet in ("key_unique", "key_not_null"):
                bindings.append(NativeRuleBinding("daily-revenue", "public.parquet", facet, paths, "invariants", "orphan_count"))
        else:
            if [field["name"] for field in fields] != ["id"]:
                raise ValueError("This concrete profile supports the independent id fixture only")
            sql = 'SELECT COUNT(*) AS orphan_count FROM outputs."public.parquet" WHERE "id" IS NULL'
        for field in fields:
            if field.get("required"):
                if primary and field not in primary:
                    raise ValueError("No required counter for non-key fixture field")
                bindings.append(NativeRuleBinding("daily-revenue", "public.parquet", "required", (({"field": field["name"]},),), "invariants", "orphan_count"))
        return [{"name": "invariants", "sql": sql}], bindings

    def bindings(self, context, original_job):
        reports, bindings = self.publication_checks(context)
        actual = next(item for item in original_job["queries"] if item["name"] == "invariants")
        if actual != reports[0]:
            raise ValueError("Original report does not count the exact exported writer namespace and field/key paths")
        return bindings


class _RequiredOnlyProfile(_FixtureRuleProfile):
    """An explicit profile that supplies row nonnull evidence, no unique counter."""

    def publication_checks(self, context):
        field = context.datasets["daily-revenue"]["properties"][0]
        bindings = [NativeRuleBinding("daily-revenue", "public.parquet", "required", (({"field": "id"},),), "invariants", "orphan_count")] if field.get("required") else []
        return [{"name": "invariants", "sql": 'SELECT COUNT(*) AS orphan_count FROM outputs."public.parquet" WHERE "id" IS NULL'}], bindings


def _retarget_original_job(row, job):
    """Retain changed original SQL coherently for adversarial metadata cases."""
    row = deepcopy(row)
    raw = _raw(job)
    digest = sha256(raw).hexdigest()
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    manifest["job"].update(sha256=digest, size=len(raw))
    for output in views["outputs"]:
        output["settings"] = deepcopy(next(item["settings"] for item in job["outputs"] if item["name"] == output["name"]))
    hashes = {item["name"]: sha256(item["sql"].encode()).hexdigest() for item in job["queries"]}
    for report in (*manifest["reports"], *views["reports"]):
        report["sql_sha256"] = hashes[report["name"]]
    policy = json.loads(base64.b64decode(row["policy"]["bytes_base64"]))
    policy["job_sha256"] = digest
    for report in policy["required_reports"]:
        report["sql_sha256"] = hashes[report["name"]]
    row["policy"] = _witness(Path(row["policy"]["reference"]["path"]), policy)
    admitted = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    admitted["job"]["sha256"] = digest
    admitted["policy"]["sha256"] = row["policy"]["sha256"]
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), admitted)
    if row["accepted_qualification"] is not None:
        body = {key: deepcopy(row["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
        body["policy_sha256"] = row["policy"]["sha256"]
        for report in body["reports"]:
            report["sql_sha256"] = hashes[report["name"]]
        row["accepted_qualification"] = _acceptance(body, row["policy"])
    return _reseal_completion(row, manifest, views)


def _native_rules_case(tmp_path, row, *, job=None, mutate_artifact=None, profile=None, schema=None):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    capture = assemble_catalog(project)
    if profile is None:
        source = tmp_path / "native-generator.py"
        source.write_text(inspect.getsource(_FixtureRuleProfile), encoding="utf-8")
        profile = _FixtureRuleProfile(source)
    job = deepcopy(job or _original_job(tmp_path))
    # Normal construction uses the public helper. Adversarial cases mutate
    # the captured metadata afterwards and submit an opaque original identity.
    baseline_job = deepcopy(job)
    baseline_job["queries"][0]["sql"] = profile.publication_checks(SimpleNamespace(
        datasets=capture.local_catalog["extensions"]["urn:ddk:catalog:assembly"]["datasetDefinitions"]))[0][0]["sql"]
    value = native_rule_artifact(capture, _raw(baseline_job), native_rule_profile=profile, **_mapping_kwargs())
    value["job"] = {"sha256": sha256(_raw(job)).hexdigest(), "bytes_base64": base64.b64encode(_raw(job)).decode()}
    if mutate_artifact:
        mutate_artifact(value)
    rules_path = tmp_path / "native-rules.json"
    rules_raw = _raw(value)
    rules_path.write_bytes(rules_raw)
    pin = {"path": str(rules_path), "sha256": sha256(rules_raw).hexdigest()}
    base = managed_job_definition(capture, **_mapping_kwargs())
    # This independent composition also models a caller bypassing the public
    # generator helper; the assembler must still reject wrong semantics.
    definition = DEFINITION_SCHEME + ":" + sha256(json_dumps({"definition": base, "nativeRules": {"sha256": pin["sha256"], "profile": value["profile"]}}).encode()).hexdigest()
    changed = _with_output_schema(_retarget_original_job(row, job), schema or pa.schema([pa.field("id", pa.int64(), nullable=True)]), definition=definition)
    metadata, entry, receipt = _metadata(tmp_path, changed)
    entry["nativeRules"] = pin
    metadata.document.path.write_bytes(_raw({"managedExecutions": [entry]}))
    return project, metadata.document.path, pin, profile, changed, value


def _reseal_completion(row, manifest, views):
    """Change fixture metadata coherently; this is never native proof."""
    row = deepcopy(row)
    view_witness = _witness(Path(manifest["view_set"]["reference"]["path"]), views)
    manifest["view_set"] = view_witness
    manifest["view_set_digest"] = view_witness["reference"]["digest"]
    completion = _witness(Path(row["candidate"]["manifest"]["path"]), manifest)
    row.update(completion_manifest=completion, view_set_digest=manifest["view_set_digest"],
               completed_outputs=deepcopy(manifest["outputs"]), completed_reports=deepcopy(manifest["reports"]),
               result=deepcopy(manifest["result"]), admitted_request=deepcopy(manifest["admitted_request"]))
    row["candidate"]["manifest"] = completion["reference"]
    if row["accepted_qualification"] is not None:
        body = {key: deepcopy(row["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
        body.update(candidate=row["candidate"], view_set_digest=manifest["view_set_digest"])
        row["accepted_qualification"] = _acceptance(body, row["policy"])
    return row


def _with_output_schema(row, schema, *, definition=None):
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    raw = schema.serialize().to_pybytes()
    key = sha256(raw).hexdigest()
    manifest["schemas"][key] = base64.b64encode(raw).decode()
    manifest["outputs"][0]["schema_sha256"] = views["outputs"][0]["schema_sha256"] = key
    if definition is not None:
        admitted = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
        admitted["definition"] = definition
        manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), admitted)
    return _reseal_completion(row, manifest, views)


@pytest.fixture
def native_job(tmp_path):
    pa = pytest.importorskip("pyarrow")
    native = tmp_path / "native"
    schema = pa.schema([pa.field("id", pa.int64(), nullable=False)])
    counters = pa.schema([pa.field("orphan_count", pa.int64(), nullable=True, metadata={b"meaning": b"unmatched keys"})])
    metadata_schema = pa.schema([pa.field("population", pa.int64(), nullable=False)])
    job = _original_job(tmp_path)
    job_bytes = _raw(job)
    job_sha = sha256(job_bytes).hexdigest()
    rule_sql_sha = sha256(job["queries"][0]["sql"].encode()).hexdigest()
    schemas = {}

    def register(value):
        raw = value.serialize().to_pybytes()
        digest = sha256(raw).hexdigest()
        schemas[digest] = base64.b64encode(raw).decode()
        return digest

    schema_key, counters_key, metadata_key = map(register, (schema, counters, metadata_schema))
    source = tmp_path / "never-open-original.parquet"
    member = {"key": None, "path": str(source), "sha256": "1" * 64, "size": 7,
              "retained": _reference(native / "never-open-captured.parquet", b"payload")}
    inputs = [{"name": "source", "kind": "parquet", "selector": {"kind": "parquet", "name": "source", "path": str(source)},
               "files": [member], "schema_sha256": schema_key, "admission": _reference(native / "admission.json")}]
    steps = [{"name": "shared_join", "material_identity": "2" * 64, "schema_sha256": schema_key,
              "completion": _reference(native / "shared-join.json"), "dependencies": [{"name": "source", "identity": "3" * 64}]}]
    outputs = [{"name": name, "path": str(native / name), "sha256": digest * 64, "md5": digest * 32,
                "size": 91, "rows": 2, "footer_bytes": 48, "schema_sha256": schema_key}
               for name, digest in (("public.parquet", "4"), ("private.parquet", "5"))]
    reports = [
        {"name": "invariants", "sql_sha256": rule_sql_sha, "schema_sha256": counters_key, "rows": 1,
         "data": [{"orphan_count": 0}], "completion": _reference(native / "invariants.json")},
        {"name": "metadata_counts", "sql_sha256": sha256(job["queries"][1]["sql"].encode()).hexdigest(), "schema_sha256": metadata_key, "rows": 1,
         "data": [{"population": 2}], "completion": _reference(native / "counts.json")},
    ]
    views = {"profile": VIEW_PROFILE, "dataset": "archive", "operation": "original", "request_digest": "a" * 64,
             "inputs": inputs, "steps": steps,
             "outputs": [{**row, "settings": job["outputs"][index]["settings"], "completion": _reference(native / f"{row['name']}.json")}
                         for index, row in enumerate(outputs)],
             "reports": [{key: value for key, value in row.items() if key != "data"} | {"dependencies": [{"name": "shared_join"}]}
                         for row in reports]}
    view_witness = _witness(native / "views.json", views)
    job_result = {"steps": [{"name": "shared_join", "storage": "memory"}],
                  "outputs": [{key: value for key, value in row.items() if key not in {"path", "schema_sha256"}} for row in outputs],
                  "queries": [{"name": row["name"], "data": row["data"]} for row in reports]}
    manifest = {"profile": COMPLETION_PROFILE, "dataset": "archive", "operation": "original", "request_digest": "a" * 64,
                "job": {"path": str(tmp_path / "never-open-job.json"), "sha256": job_sha, "size": len(job_bytes)},
                "inputs": inputs, "steps": steps, "outputs": outputs, "reports": reports,
                "view_set": view_witness, "view_set_digest": view_witness["reference"]["digest"], "schemas": schemas,
                "evaluator": COUNTER_EVALUATOR,
                "runtime": {"id": "docspec", "version": "test-only", "processor": "docspec.whole-job.v1", "binary_sha256": "c" * 64},
                "execution": "completed", "result": job_result}
    policy = {"id": "counters-v1", "profile": COUNTER_PROFILE, "evaluator": COUNTER_EVALUATOR, "semantics": COUNTER_SEMANTICS,
              "job_sha256": job_sha, "view_names": {key: [row["name"] for row in manifest[key]] for key in ("inputs", "steps", "outputs", "reports")},
              "required_reports": [{"name": "invariants", "sql_sha256": rule_sql_sha, "schema_ipc_base64": schemas[counters_key]}]}
    policy_witness = _witness(native / "policy.json", policy)
    capture = assemble_catalog(_authored_project(tmp_path))
    assert capture.report["decision"] == "passed"
    captured_definition = managed_job_definition(capture, **_mapping_kwargs())
    admitted = {"action": "prepare", "dataset": "archive", "operation": "original", "definition": captured_definition,
                "job": {key: manifest["job"][key] for key in ("path", "sha256")},
                "file_inputs": [{"name": "source", "members": [{key: member[key] for key in ("key", "sha256", "size")}]}],
                "policy_id": "counters-v1", "policy": {"path": str(tmp_path / "never-open-policy.json"), "sha256": policy_witness["sha256"]},
                "expected_epoch": 0, "expected_selection": None}
    request_witness = _witness(native / "admitted-request.json", admitted)
    manifest["admitted_request"] = request_witness
    completion = _witness(native / "completion.json", manifest)
    candidate = {"scheme": CANDIDATE_SCHEME, "scheme_version": "1", "dataset": "archive", "operation": "original",
                 "manifest": completion["reference"]}
    body = {"profile": COUNTER_PROFILE, "dataset": "archive", "operation": "original", "request_digest": "a" * 64,
            "candidate": candidate, "view_set_digest": manifest["view_set_digest"], "policy_id": "counters-v1",
            "policy_sha256": policy_witness["sha256"], "expected_epoch": 0, "expected_selection": None,
            "evaluator": COUNTER_EVALUATOR, "semantics": COUNTER_SEMANTICS,
            "reports": [{key: value for key, value in reports[0].items() if key in {"name", "sql_sha256", "completion", "schema_sha256"}}
                        | {"checks": [{"column": "orphan_count", "status": "passed", "value": 0}]}]}
    return {"dataset": "archive", "operation": "original", "request_digest": "a" * 64, "status": "completed",
            "candidate": candidate, "view_set_digest": manifest["view_set_digest"], "policy_id": "counters-v1", "active_policy_id": "counters-v1",
            "accepted_qualification": _acceptance(body, policy_witness), "policy": policy_witness, "selection": "pending",
            "completed_outputs": outputs, "completed_reports": reports, "completion_manifest": completion, "result": job_result,
            "admitted_request": request_witness}


def _metadata(tmp_path, native_job, *, accepted=True):
    native_job = deepcopy(native_job)
    if not accepted:
        native_job["accepted_qualification"] = None
    receipt = {"tool": {"id": "docspec", "version": "test-only", "distributionSha256": "c" * 64},
               "status": "succeeded", "nativeOutcome": "succeeded", "result": native_job, "endedAt": "2026-11-06T12:00:00Z",
               "operationContext": {"runtime": "docspec", "workspace": str(tmp_path / "native"), "dataset": "archive",
                                    "operationId": "original", "kind": "whole_job"}}
    receipt_path = tmp_path / "receipt.json"
    raw = _raw(receipt)
    receipt_path.write_bytes(raw)
    value = managed_job_metadata(receipt={"path": str(receipt_path), "sha256": sha256(raw).hexdigest()}, **_mapping_kwargs())
    path = tmp_path / "metadata.json"
    path.write_bytes(_raw(value))
    project = _authored_project(tmp_path)
    inventory = load_project(project, (tmp_path,))
    declared = assemble_catalog(project)
    assert declared.report["decision"] == "passed"
    datasets = {row["alias"]: row for row in declared.local_catalog["datasets"]}
    productions = {row["alias"]: row for row in declared.local_catalog["productions"]}
    metadata = LocalMetadata(read_json(path), inventory, LOCAL_ADAPTER, datasets,
                             productions)
    metadata.managed_jobs = []
    return metadata, value["managedExecutions"][0], receipt


def _authored_project(tmp_path):
    """A small independent catalog definition with no runtime or data reads."""
    folder = tmp_path / "authored"
    if (folder / "project.json").is_file():
        return folder / "project.json"
    folder.mkdir()
    definition_id = "urn:test:managed:definitions"
    product = {
        "apiVersion": "v1.1.0", "kind": "DataProduct", "id": "urn:test:managed:product", "version": "1.0.0",
        "name": "Retained identifier result", "status": "draft",
        "description": {"purpose": "Describe one retained public identifier output."},
        "team": {"name": "Independent metadata fixture", "members": [{"username": "fixture-owner", "role": "owner"}]},
        "inputPorts": [{"name": "source", "contractId": definition_id, "version": "1.0.0"}],
        "outputPorts": [{"name": "result", "contractId": definition_id, "version": "1.0.0"}],
    }
    definitions = {
        "apiVersion": "v3.2.0", "kind": "DataContract", "id": definition_id, "version": "1.0.0",
        "name": "Independent retained identifiers", "status": "draft",
        "schema": [{"id": name, "name": name, "logicalType": "object", "physicalType": "table",
                    "properties": [{"name": "id", "logicalType": "integer", "physicalType": "int64", "required": True}]}
                   for name in ("source", "result")],
    }
    component = {
        "specVersion": "0.1", "kind": "component", "id": "urn:test:managed:production", "version": "1.0.0", "role": "transform",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "inputs": {"source": {"dataset": "orders"}}, "outputs": {"result": {"dataset": "daily-revenue"}},
        "implementation": {"format": "sql", "dialect": "datafusion-sql", "path": "identifiers.sql",
                           "semantics": {"id": "urn:test:managed:identifier-semantics", "revision": "1"}},
    }
    project = {
        "specVersion": "0.1", "kind": "project", "id": "urn:test:managed:project", "version": "1.0.0",
        "artifacts": {
            "orders": {"kind": "dataset", "path": "definitions.json", "object": "source", "catalogId": "urn:test:managed:source"},
            "daily-revenue": {"kind": "dataset", "path": "definitions.json", "object": "result", "catalogId": "urn:test:managed:result"},
            "summarize": {"kind": "component", "path": "component.json"},
            "product": {"kind": "product", "path": "product.json"},
        },
        "imports": {},
        "requiredChecks": ["core.documents", "core.references", "core.graph", "core.calls", "core.datasets", "core.policies"],
        "catalog": {"id": "urn:test:managed:catalog", "ports": [
            {"product": "product", "direction": "input", "port": "source", "version": "1.0.0", "dataset": "orders"},
            {"product": "product", "direction": "output", "port": "result", "version": "1.0.0", "dataset": "daily-revenue"},
        ]},
    }
    for name, value in (("project.json", project), ("product.json", product), ("definitions.json", definitions), ("component.json", component)):
        (folder / name).write_bytes(_raw(value))
    (folder / "identifiers.sql").write_text("SELECT id FROM source\n", encoding="utf-8")
    return folder / "project.json"


def test_exact_complete_metadata_retains_private_members_and_actual_native_result(native_job):
    evidence = verify_completed_job(native_job, require_accepted=True)
    assert evidence.view_names == {"inputs": ("source",), "steps": ("shared_join",),
                                   "outputs": ("public.parquet", "private.parquet"), "reports": ("invariants", "metadata_counts")}
    assert evidence.manifest_bytes == base64.b64decode(native_job["completion_manifest"]["bytes_base64"])
    assert evidence.accepted["reports"][0]["checks"] == [{"column": "orphan_count", "status": "passed", "value": 0}]
    assert evidence.manifest["reports"][1]["data"] == [{"population": 2}]
    assert evidence.admitted_request["expected_epoch"] == 0 and evidence.admitted_request["expected_selection"] is None


@pytest.fixture
def native_snapshot_job(native_job, tmp_path):
    """Authored custody metadata, not a native admission or an Iceberg payload."""
    selector = {"kind": "native_table", "name": "source", "metadata_location": "s3://fixture/table/metadata/v1.json",
                "table_uuid": "4200827d-e8eb-4616-a0f9-ff4d222a582e", "snapshot": 1, "schema_id": 0}
    job = _original_job(tmp_path)
    job["inputs"] = [selector]
    row = _retarget_original_job(native_job, job)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    objects = []
    for uri, role, raw in [
        (selector["metadata_location"], "metadata", b"independent native metadata identity"),
        ("s3://fixture/table/metadata/list.avro", "manifest_list", b"original manifest list"),
        ("s3://fixture/table/metadata/manifest.avro", "manifest", b"original manifest"),
        ("s3://fixture/table/data/original.parquet", "data", b"d"),
    ]:
        objects.append({"uri": uri, "role": role, "sha256": sha256(raw).hexdigest(), "size": len(raw),
                        "retained": _reference(tmp_path / "native" / f"never-open-{role}", raw),
                        "origin_operation": "original"})
    objects.sort(key=lambda item: item["uri"])
    metadata = next(item for item in objects if item["role"] == "metadata")
    custody = {"profile": SNAPSHOT_CUSTODY_PROFILE, "scope": "selected_snapshot",
               "metadata_sha256": metadata["sha256"], "metadata_size": metadata["size"], "objects": objects}
    source = {**views["inputs"][0], "kind": "native_table", "selector": selector, "files": [], "snapshot_custody": custody}
    manifest.update(profile=SNAPSHOT_COMPLETION_PROFILE, inputs=[deepcopy(source)])
    views.update(profile=SNAPSHOT_VIEW_PROFILE, inputs=[deepcopy(source)])
    request = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    request.update(file_inputs=[], snapshot_inputs=[{"name": "source", "metadata_sha256": metadata["sha256"],
                                                   "metadata_size": metadata["size"]}], prerequisites=[])
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), request)
    return _reseal_completion(row, manifest, views)


def test_snapshot_metadata_preserves_original_uris_and_native_ownership_without_reads(native_snapshot_job, monkeypatch):
    def refuse_open(*_args, **_kwargs):
        raise AssertionError("The metadata verifier must not reopen native or caller payloads")

    monkeypatch.setattr(Path, "open", refuse_open)
    monkeypatch.setattr("builtins.open", refuse_open)
    checked = verify_completed_job(native_snapshot_job, require_accepted=True)
    view = checked.view_set["inputs"][0]
    assert checked.manifest["profile"] == SNAPSHOT_COMPLETION_PROFILE
    assert view["selector"] == {"kind": "native_table", "name": "source",
                               "metadata_location": "s3://fixture/table/metadata/v1.json",
                               "table_uuid": "4200827d-e8eb-4616-a0f9-ff4d222a582e", "snapshot": 1, "schema_id": 0}
    assert [item["role"] for item in view["snapshot_custody"]["objects"]] == ["data", "manifest_list", "manifest", "metadata"]
    assert all(item["retained"]["owner"] == "archive" and item["origin_operation"] == "original"
               for item in view["snapshot_custody"]["objects"])


def test_snapshot_catalog_binds_original_identity_without_availability_or_payload_reads(native_snapshot_job, tmp_path, monkeypatch):
    metadata, entry, _receipt = _metadata(tmp_path, native_snapshot_job)
    original = Path.open

    def metadata_only(path, *args, **kwargs):
        assert path.name == "receipt.json", f"Unexpected source or payload read: {path}"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    managed_execution(metadata, entry)
    run = metadata.observations["runs"][0]
    assert len(run["inputs"]) == 1 and run["inputCoverage"]["status"] == "unknown"
    version = metadata.version_facts[run["inputs"][0]]
    assert version["reference"] == {
        "scheme": "urn:ddk:catalog:docspec-native-table:1",
        "authority": "urn:uuid:4200827d-e8eb-4616-a0f9-ff4d222a582e",
        "value": {"metadata_location": "s3://fixture/table/metadata/v1.json",
                  "table_uuid": "4200827d-e8eb-4616-a0f9-ff4d222a582e", "snapshot": 1, "schema_id": 0,
                  "metadata_sha256": sha256(b"independent native metadata identity").hexdigest(), "metadata_size": 36},
    }
    assert version["retention"] == "unknown" and version["sources"] == []
    assert version["id"] not in metadata.physical_datasets
    assert not any(row["version"] == version["id"] for row in metadata.observations["representations"])
    assert metadata.bound_inputs[run["id"]] == {"source": version["id"]}
    view = verify_completed_job(native_snapshot_job).view_set["inputs"][0]
    assert metadata.managed_jobs[0]["inputObservations"] == [
        {"input": "source", "dataset": "orders", "version": version["id"], "schemaSha256": view["schema_sha256"]}]
    assert metadata.managed_jobs[0]["record"] == version["record"]
    assert _policy_check(metadata.observations["checks"])["status"] == "passed"


def _snapshot_mapping_case(tmp_path, native_snapshot_job):
    metadata, _entry, _receipt = _metadata(tmp_path, native_snapshot_job)
    checked = verify_completed_job(native_snapshot_job)
    # Test the mapping after witness admission; these variations are observations,
    # not newly executed or accepted native jobs.
    evidence = SimpleNamespace(view_set=json.loads(json_dumps(checked.view_set)))
    record = {"uri": "urn:test:receipt:first", "sha256": "a" * 64}
    versions, _bindings = _input_versions(metadata, evidence, {"source": "orders"}, record)
    assert len(versions) == 1
    return metadata, evidence, record, versions[0]


@pytest.mark.parametrize("field,value", [
    ("metadata_location", "/original/table/../metadata/v1.json"),
    ("metadata_location", "s3://fixture/table/%2Fmetadata/v1.json?versionId=original"),
    ("table_uuid", "79316476-09ae-4c21-a09e-d48cd0c49a31"),
    ("snapshot", 2), ("snapshot", None), ("schema_id", 1),
    ("metadata_sha256", "f" * 64), ("metadata_size", 37),
])
def test_snapshot_catalog_version_identity_preserves_each_exact_pin(native_snapshot_job, tmp_path, field, value):
    metadata, evidence, record, original_version = _snapshot_mapping_case(tmp_path, native_snapshot_job)
    view = evidence.view_set["inputs"][0]
    target = view["snapshot_custody"] if field in {"metadata_sha256", "metadata_size"} else view["selector"]
    target[field] = value
    versions, bindings = _input_versions(metadata, evidence, {"source": "orders"}, record)
    assert versions != [original_version] and bindings == {"source": versions[0]}
    reference = metadata.version_facts[versions[0]]["reference"]
    assert reference["value"][field] == value
    assert reference["authority"] == f"urn:uuid:{view['selector']['table_uuid']}"


def test_snapshot_catalog_source_identity_excludes_alias_custody_and_observed_schema(native_snapshot_job, tmp_path):
    metadata, evidence, first_record, original_version = _snapshot_mapping_case(tmp_path, native_snapshot_job)
    view = evidence.view_set["inputs"][0]
    view["name"] = view["selector"]["name"] = "renamed_input"
    view["schema_sha256"] = "8" * 64
    view["admission"]["path"] = "/different-operation/inputs.json"
    view["custody_reference"] = _input_custody_reference(operation="later")
    view["custody_grant"] = {"profile": "urn:docspec:whole-job-input-custody-grant:1", "source": _input_custody_reference()}
    for item in view["snapshot_custody"]["objects"]:
        item["retained"]["path"] = "/different-owner/retained/" + item["role"]
        item["origin_operation"] = "earliest-copy"
    second_record = {"uri": "urn:test:receipt:second", "sha256": "b" * 64}
    versions, bindings = _input_versions(metadata, evidence, {"renamed_input": "orders"}, second_record)
    assert versions == [original_version] and bindings == {"renamed_input": original_version}
    assert metadata.owners[original_version] == [first_record, second_record]
    assert len(metadata.version_facts) == 1
    assert metadata.version_facts[original_version]["retention"] == "unknown"
    assert not metadata.observations["representations"]


def test_snapshot_catalog_does_not_promote_legacy_unpinned_selectors(native_snapshot_job, tmp_path):
    manifest = json.loads(base64.b64decode(native_snapshot_job["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    manifest["profile"], views["profile"] = COMPLETION_PROFILE, VIEW_PROFILE
    for view in (manifest["inputs"][0], views["inputs"][0]):
        view.pop("snapshot_custody")
    admitted = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    admitted.pop("snapshot_inputs")
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), admitted)
    row = _reseal_completion(native_snapshot_job, manifest, views)
    metadata, entry, _receipt = _metadata(tmp_path, row)
    managed_execution(metadata, entry)
    assert metadata.observations["runs"][0]["inputs"] == []
    assert not any(version["dataset"] == "orders" for version in metadata.version_facts.values())
    assert "inputObservations" not in metadata.managed_jobs[0]
    assert any("without a supported exact catalog identity" in limit for limit in metadata.limits)


def test_snapshot_catalog_exports_metadata_without_inventing_a_reader(native_snapshot_job, tmp_path):
    metadata, _entry, _receipt = _metadata(tmp_path, native_snapshot_job)
    result = assemble_catalog(_authored_project(tmp_path), metadata=metadata.document.path, metadata_adapter="local",
                              permitted_roots=(tmp_path,), exports=("dcat", "openlineage"))
    assert result.report["decision"] == "passed", result.report
    version = next(row for row in result.catalog["versions"] if row["dataset"] == "orders")
    dcat = json.loads(result.artifacts["discovery.dcat.json"])
    node = next(row for row in dcat["@graph"] if row["@id"] == version["id"])
    assert not node.get("dcat:distribution") and "dcat:accessURL" not in node
    events = [json.loads(raw) for name, raw in result.artifacts.items() if name.startswith("lineage/")]
    completed = next(event for event in events if event.get("eventType") == "COMPLETE")
    source = completed["inputs"][0]
    assert source["namespace"] == "urn:uuid:4200827d-e8eb-4616-a0f9-ff4d222a582e"
    assert source["facets"]["version"]["datasetVersion"] == version["id"]
    assert source["name"] != "s3://fixture/table/metadata/v1.json"


@pytest.mark.parametrize("change", [
    "v1_with_custody", "mixed_view_version", "profile_array", "no_snapshot_pins", "repeated_snapshot_pin",
    "unbound_snapshot_pin", "changed_metadata_pin", "overlapping_file_pin", "prerequisite_boolean",
])
def test_resealed_snapshot_request_and_profile_mismatches_refuse(native_snapshot_job, change):
    manifest = json.loads(base64.b64decode(native_snapshot_job["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    request = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    if change == "v1_with_custody":
        manifest["profile"], views["profile"] = COMPLETION_PROFILE, VIEW_PROFILE
    elif change == "mixed_view_version":
        views["profile"] = VIEW_PROFILE
    elif change == "profile_array":
        manifest["profile"] = []
    elif change == "no_snapshot_pins":
        request["snapshot_inputs"] = []
    elif change == "repeated_snapshot_pin":
        request["snapshot_inputs"] *= 2
    elif change == "unbound_snapshot_pin":
        request["snapshot_inputs"][0]["name"] = "another"
    elif change == "changed_metadata_pin":
        request["snapshot_inputs"][0]["metadata_sha256"] = "f" * 64
    elif change == "overlapping_file_pin":
        request["file_inputs"] = [{"name": "source", "members": []}]
    else:
        request["prerequisites"] = [{"passed": True}]
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), request)
    row = _reseal_completion(native_snapshot_job, manifest, views)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(row, require_accepted=True)


@pytest.mark.parametrize("change", [
    "missing_completed_custody", "missing_view_custody", "boolean_snapshot", "boolean_schema", "boolean_object_size",
    "float_snapshot", "float_schema", "float_object_size", "float_admission_size",
])
def test_resealed_snapshot_copies_require_complete_type_sensitive_equality(native_snapshot_job, change):
    manifest = json.loads(base64.b64decode(native_snapshot_job["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    completed, view = manifest["inputs"][0], views["inputs"][0]
    if change == "missing_completed_custody":
        completed.pop("snapshot_custody")
    elif change == "missing_view_custody":
        view.pop("snapshot_custody")
    elif change == "boolean_snapshot":
        completed["selector"]["snapshot"] = True
    elif change == "boolean_schema":
        completed["selector"]["schema_id"] = False
    elif change == "boolean_object_size":
        completed["snapshot_custody"]["objects"][0]["size"] = True
    elif change == "float_snapshot":
        completed["selector"]["snapshot"] = 1.0
    elif change == "float_schema":
        completed["selector"]["schema_id"] = 0.0
    elif change == "float_object_size":
        completed["snapshot_custody"]["objects"][0]["size"] = 1.0
    else:
        completed["admission"]["bytes"] = float(completed["admission"]["bytes"])
    row = _reseal_completion(native_snapshot_job, manifest, views)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(row, require_accepted=True)


@pytest.mark.parametrize("change", [
    "role_array", "unknown_role", "unsorted", "repeated_uri", "foreign_owner", "size_mismatch", "relative_uri",
    "bad_digest", "missing_origin", "wrong_metadata_uri", "missing_metadata", "extra_metadata", "empty_with_payload",
    "missing_manifest_list", "extra_manifest_list", "invalid_uuid", "extra_selector_field", "boolean_selector",
])
def test_resealed_snapshot_custody_cannot_invent_scope_or_ownership(native_snapshot_job, change):
    manifest = json.loads(base64.b64decode(native_snapshot_job["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    view = views["inputs"][0]
    objects = view["snapshot_custody"]["objects"]
    if change == "role_array":
        objects[0]["role"] = []
    elif change == "unknown_role":
        objects[0]["role"] = "latest"
    elif change == "unsorted":
        objects.reverse()
    elif change == "repeated_uri":
        objects.insert(0, deepcopy(objects[0]))
    elif change == "foreign_owner":
        objects[0]["retained"]["owner"] = "another"
    elif change == "size_mismatch":
        objects[0]["size"] += 1
    elif change == "relative_uri":
        objects[0]["uri"] = "data.parquet"
    elif change == "bad_digest":
        objects[0]["sha256"] = "not-a-digest"
    elif change == "missing_origin":
        objects[0].pop("origin_operation")
    elif change == "wrong_metadata_uri":
        view["selector"]["metadata_location"] = "s3://fixture/table/metadata/other.json"
    elif change == "missing_metadata":
        objects[:] = [item for item in objects if item["role"] != "metadata"]
    elif change == "extra_metadata":
        objects[0]["role"] = "metadata"
    elif change == "empty_with_payload":
        view["selector"]["snapshot"] = None
    elif change == "missing_manifest_list":
        objects[:] = [item for item in objects if item["role"] != "manifest_list"]
    elif change == "extra_manifest_list":
        objects[0]["role"] = "manifest_list"
    elif change == "invalid_uuid":
        view["selector"]["table_uuid"] = "declared-table"
    elif change == "extra_selector_field":
        view["selector"]["latest"] = True
    else:
        view["selector"]["snapshot"] = True
    manifest["inputs"][0] = deepcopy(view)
    row = _reseal_completion(native_snapshot_job, manifest, views)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(row, require_accepted=True)


def test_exact_empty_snapshot_is_metadata_only_and_reuse_keeps_original_operation(native_snapshot_job):
    manifest = json.loads(base64.b64decode(native_snapshot_job["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    view = views["inputs"][0]
    view["selector"]["snapshot"] = None
    metadata = next(item for item in view["snapshot_custody"]["objects"] if item["role"] == "metadata")
    metadata["origin_operation"] = "earlier_original"
    view["snapshot_custody"]["objects"] = [metadata]
    manifest["inputs"][0] = deepcopy(view)
    row = _reseal_completion(native_snapshot_job, manifest, views)
    checked = verify_completed_job(row, require_accepted=True)
    assert checked.view_set["inputs"][0]["selector"]["snapshot"] is None
    assert checked.view_set["inputs"][0]["snapshot_custody"]["objects"][0]["origin_operation"] == "earlier_original"


def _input_custody_reference(*, operation="original", input_name="source", request_digest="a" * 64):
    """Authored opaque native identity; no native canonical digest is reproduced."""
    return {"scheme": "urn:docspec:whole-job-input-custody", "scheme_version": "1", "dataset": "archive",
            "operation": operation, "request_digest": request_digest, "input": input_name,
            "native_record": {"table": "native-lifecycle", "table_uuid": "d780a544-780b-4abb-9e1e-f7beef0aec62",
                              "key": f"job-input/{operation}/0", "revision": 17},
            "admission_digest": {"algorithm": "blake3", "value": "e" * 64}}


def _with_input_custody(row, *, reuse=False):
    row = deepcopy(row)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    reference = _input_custody_reference(request_digest=manifest["request_digest"])
    view = views["inputs"][0]
    view["custody_reference"] = reference
    if reuse:
        original = _input_custody_reference(operation="prior_consumer", input_name="original_source", request_digest="b" * 64)
        view["custody_grant"] = {"profile": "urn:docspec:whole-job-input-custody-grant:1", "source": original}
        request = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
        request["snapshot_inputs"][0]["reuse_from"] = deepcopy(original)
        manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), request)
        for member in view["snapshot_custody"]["objects"]:
            member["origin_operation"] = "earliest_copy"
    manifest["inputs"][0] = deepcopy(view)
    row["input_custody"] = [deepcopy(reference)]
    return _reseal_completion(row, manifest, views)


def _producer_parts(row):
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    request = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    body = json.loads(base64.b64decode(manifest["producer_evidence_witness"]["bytes_base64"]))
    return manifest, views, request, body


def _reseal_producer(row, manifest, views, request, body):
    """Reseal independent metadata identities, never native authority or proof."""
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), request)
    witness = _witness(Path(manifest["producer_evidence_witness"]["reference"]["path"]), body)
    manifest["producer_evidence_witness"] = witness
    for document in (manifest, views):
        if "producer_evidence" in document:
            document["producer_evidence"]["evidence"] = {key: deepcopy(witness[key]) for key in ("reference", "sha256")}
    return _reseal_completion(row, manifest, views)


def _producer_job(native_snapshot_job, tmp_path, role):
    row = _with_input_custody(native_snapshot_job, reuse=role == "model")
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    request = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    adoption = {"scheme": "urn:docspec:whole-job-producer-adoption", "scheme_version": "1",
                "dataset": "archive", "adoption": "definition-one", "request_digest": "b" * 64,
                "definition_sha256": "c" * 64,
                "native_record": {"table": "native-lifecycle", "table_uuid": "d780a544-780b-4abb-9e1e-f7beef0aec62",
                                  "key": "job-producer-adoption/definition-one", "revision": 9}}
    evidence = {"adoption": adoption, "role": role}
    body = {"profile": "urn:docspec:whole-job-producer-static:1" if role == "proof"
                        else "urn:docspec:whole-job-producer-prerequisite-grant:1",
            "dataset": "archive", "operation": "original", "request_digest": "a" * 64,
            "adoption": deepcopy(adoption), "native_private_metadata": {"original_path": "/never/open/producer-record"}}
    request["producer_adoption"] = deepcopy(adoption)
    if role == "model":
        donor = {"scheme": CANDIDATE_SCHEME, "scheme_version": "1", "dataset": "archive", "operation": "prior_consumer",
                 "manifest": _reference(tmp_path / "never-open-proof-completion")}
        prerequisite = {"profile": PRODUCER_PREREQUISITE_PROFILE, "candidate": donor,
                        "accepted_qualification": "d" * 64, "inputs": ["source"]}
        evidence["prerequisite"] = deepcopy(prerequisite)
        body["prerequisite"] = deepcopy(prerequisite)
        request["prerequisites"] = [prerequisite]
        request["snapshot_inputs"][0]["reuse_from"]["input"] = "source"
        for document in (manifest, views):
            document["inputs"][0]["custody_grant"]["source"]["input"] = "source"
    else:
        request["producer_records"] = [{"source": {"namespace": "original-records", "key": "head.json"},
                                        "path": "/never/open/head.json", "sha256": "e" * 64, "size": 73}]
        for document in (manifest, views):
            document["outputs"] = []
        manifest["result"]["outputs"] = []
        policy = json.loads(base64.b64decode(row["policy"]["bytes_base64"]))
        policy["view_names"]["outputs"] = []
        row["policy"] = _witness(Path(row["policy"]["reference"]["path"]), policy)
        request["policy"]["sha256"] = row["policy"]["sha256"]
        accepted = {key: deepcopy(row["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
        accepted["policy_sha256"] = row["policy"]["sha256"]
        row["accepted_qualification"] = _acceptance(accepted, row["policy"])
    manifest["profile"], views["profile"] = PRODUCER_COMPLETION_PROFILE, PRODUCER_VIEW_PROFILE
    manifest["producer_evidence"], views["producer_evidence"] = deepcopy(evidence), deepcopy(evidence)
    manifest["producer_evidence_witness"] = _witness(tmp_path / "never-open-producer-evidence", body)
    row = _reseal_producer(row, manifest, views, request, body)
    if role == "proof":
        job = _original_job(tmp_path)
        job["inputs"] = [deepcopy(views["inputs"][0]["selector"])]
        job["outputs"] = []
        job["queries"][0]["sql"] = "SELECT COUNT(*) AS orphan_count FROM shared_join WHERE id IS NULL"
        row = _retarget_original_job(row, job)
    return row


@pytest.fixture
def native_producer_job(native_snapshot_job, tmp_path):
    return _producer_job(native_snapshot_job, tmp_path, "model")


@pytest.mark.parametrize("role", ["proof", "model"])
def test_producer_metadata_binds_exact_native_witness_without_resolving_authority(native_snapshot_job, tmp_path, monkeypatch, role):
    row = _producer_job(native_snapshot_job, tmp_path, role)
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: pytest.fail("Producer metadata cannot open native or original artifacts"))
    checked = verify_completed_job(row, require_accepted=True)
    evidence = checked.manifest["producer_evidence"]
    assert evidence == checked.view_set["producer_evidence"]
    assert evidence["adoption"] == checked.admitted_request["producer_adoption"]
    assert evidence["role"] == role and checked.accepted["view_set_digest"] == row["view_set_digest"]
    assert "producer_evidence_witness" not in checked.view_set
    if role == "model":
        assert checked.admitted_request["prerequisites"] == [evidence["prerequisite"]]
        assert evidence["prerequisite"]["candidate"]["operation"] == "prior_consumer"
    else:
        assert checked.manifest["outputs"] == [] and checked.admitted_request["file_inputs"] == []


def test_model_producer_metadata_keeps_file_and_native_input_pins_distinct(native_snapshot_job, native_job, tmp_path, monkeypatch):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, request, body = _producer_parts(row)
    file_manifest = json.loads(base64.b64decode(native_job["completion_manifest"]["bytes_base64"]))
    file_view = json.loads(base64.b64decode(file_manifest["view_set"]["bytes_base64"]))["inputs"][0]
    file_view["name"] = file_view["selector"]["name"] = "dictionary"
    for document in (manifest, views):
        document["inputs"].append(deepcopy(file_view))
    request["file_inputs"] = [{"name": "dictionary", "members": [
        {key: member[key] for key in ("key", "sha256", "size")} for member in file_view["files"]]}]
    policy = json.loads(base64.b64decode(row["policy"]["bytes_base64"]))
    policy["view_names"]["inputs"].append("dictionary")
    row["policy"] = _witness(Path(row["policy"]["reference"]["path"]), policy)
    request["policy"]["sha256"] = row["policy"]["sha256"]
    accepted = {key: deepcopy(row["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
    accepted["policy_sha256"] = row["policy"]["sha256"]
    row["accepted_qualification"] = _acceptance(accepted, row["policy"])
    row = _reseal_producer(row, manifest, views, request, body)
    job = _original_job(tmp_path)
    job["inputs"] = [deepcopy(view["selector"]) for view in views["inputs"]]
    row = _retarget_original_job(row, job)
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: pytest.fail("File/native metadata cannot open payloads"))
    checked = verify_completed_job(row, require_accepted=True)
    assert [view["kind"] for view in checked.view_set["inputs"]] == ["native_table", "parquet"]
    assert checked.manifest["producer_evidence"]["prerequisite"]["inputs"] == ["source"]
    manifest, views, request, body = _producer_parts(row)
    request["file_inputs"][0]["members"][0]["sha256"] = "f" * 64
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_producer(row, manifest, views, request, body))


@pytest.mark.parametrize("field,value", [
    ("scheme", "caller-proof"), ("scheme_version", "2"), ("dataset", "foreign"),
    ("adoption", "bad/name"), ("request_digest", "unknown"), ("definition_sha256", "unknown"),
    ("native_record.table", "foreign-table"), ("native_record.table_uuid", "bad-uuid"),
    ("native_record.key", "job-producer-adoption/other"), ("native_record.revision", 0),
    ("native_record.revision", True), ("native_record.revision", 1.0), ("native_record.revision", 2**63),
    ("extra", "unrecognized"),
])
def test_resealed_producer_adoption_requires_exact_native_identity(native_snapshot_job, tmp_path, field, value):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, request, body = _producer_parts(row)
    for adoption in (manifest["producer_evidence"]["adoption"], views["producer_evidence"]["adoption"],
                     request["producer_adoption"], body["adoption"]):
        target = adoption
        parts = field.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_producer(row, manifest, views, request, body))


@pytest.mark.parametrize("copy", ["view_adoption", "request_adoption", "body_adoption", "completion_pointer", "view_pointer",
                                  "witness_reference", "view_candidate", "request_candidate", "body_candidate"])
def test_each_producer_identity_copy_preserves_native_integer_tokens(native_snapshot_job, tmp_path, copy):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, request, body = _producer_parts(row)
    locations = {"view_adoption": views["producer_evidence"]["adoption"]["native_record"],
                 "request_adoption": request["producer_adoption"]["native_record"],
                 "body_adoption": body["adoption"]["native_record"],
                 "completion_pointer": manifest["producer_evidence"]["evidence"]["reference"],
                 "view_pointer": views["producer_evidence"]["evidence"]["reference"],
                 "witness_reference": manifest["producer_evidence_witness"]["reference"],
                 "view_candidate": views["producer_evidence"]["prerequisite"]["candidate"]["manifest"],
                 "request_candidate": request["prerequisites"][0]["candidate"]["manifest"],
                 "body_candidate": body["prerequisite"]["candidate"]["manifest"]}
    key = "revision" if copy.endswith("adoption") else "bytes"
    locations[copy][key] = float(locations[copy][key])
    if copy.endswith("pointer") or copy == "witness_reference":
        changed = _reseal_completion(row, manifest, views)
    else:
        changed = _reseal_producer(row, manifest, views, request, body)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(changed)


def test_producer_adoption_refuses_coherent_nil_native_table_identity(native_snapshot_job, tmp_path):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, request, body = _producer_parts(row)
    nil = "00000000-0000-0000-0000-000000000000"
    for adoption in (manifest["producer_evidence"]["adoption"], views["producer_evidence"]["adoption"],
                     request["producer_adoption"], body["adoption"]):
        adoption["native_record"]["table_uuid"] = nil
    for document in (manifest, views):
        document["inputs"][0]["custody_reference"]["native_record"]["table_uuid"] = nil
        document["inputs"][0]["custody_grant"]["source"]["native_record"]["table_uuid"] = nil
    request["snapshot_inputs"][0]["reuse_from"]["native_record"]["table_uuid"] = nil
    row["input_custody"] = [deepcopy(manifest["inputs"][0]["custody_reference"])]
    with pytest.raises(JobEvidenceError, match="Producer adoption"):
        verify_completed_job(_reseal_producer(row, manifest, views, request, body))


def test_producer_adopted_scope_order_is_independent_of_current_jobspec_order(native_snapshot_job, tmp_path):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, request, body = _producer_parts(row)
    other = deepcopy(views["inputs"][0])
    other["name"] = other["selector"]["name"] = "other"
    other["custody_reference"]["input"] = other["custody_grant"]["source"]["input"] = "other"
    other["custody_reference"]["native_record"]["key"] = "job-input/original/1"
    other["custody_grant"]["source"]["native_record"]["key"] = "job-input/prior_consumer/1"
    for document in (manifest, views):
        document["inputs"].append(deepcopy(other))
        document["producer_evidence"]["prerequisite"]["inputs"] = ["other", "source"]
    request["prerequisites"][0]["inputs"] = body["prerequisite"]["inputs"] = ["other", "source"]
    request["snapshot_inputs"].append({"name": "other", "metadata_sha256": other["snapshot_custody"]["metadata_sha256"],
                                       "metadata_size": other["snapshot_custody"]["metadata_size"],
                                       "reuse_from": deepcopy(other["custody_grant"]["source"])})
    row["input_custody"].append(deepcopy(other["custody_reference"]))
    policy = json.loads(base64.b64decode(row["policy"]["bytes_base64"]))
    policy["view_names"]["inputs"].append("other")
    row["policy"] = _witness(Path(row["policy"]["reference"]["path"]), policy)
    request["policy"]["sha256"] = row["policy"]["sha256"]
    accepted = {key: deepcopy(row["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
    accepted["policy_sha256"] = row["policy"]["sha256"]
    row["accepted_qualification"] = _acceptance(accepted, row["policy"])
    row = _reseal_producer(row, manifest, views, request, body)
    job = _original_job(tmp_path)
    job["inputs"] = [deepcopy(view["selector"]) for view in views["inputs"]]
    row = _retarget_original_job(row, job)
    checked = verify_completed_job(row, require_accepted=True)
    assert [view["name"] for view in checked.view_set["inputs"]] == ["source", "other"]
    assert checked.manifest["producer_evidence"]["prerequisite"]["inputs"] == ["other", "source"]


@pytest.mark.parametrize("change", [
    "role", "extra", "view_missing", "view_role", "request_adoption", "body_adoption", "body_profile",
    "body_owner", "body_operation", "body_request", "view_duplicate_witness", "policy_id", "custody_missing",
])
def test_resealed_producer_evidence_requires_consistent_original_bindings(native_snapshot_job, tmp_path, change):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, request, body = _producer_parts(row)
    if change == "role":
        manifest["producer_evidence"]["role"] = "caller_passed"
    elif change == "extra":
        manifest["producer_evidence"]["passed"] = True
    elif change == "view_missing":
        del views["producer_evidence"]
    elif change == "view_role":
        views["producer_evidence"]["role"] = "proof"
    elif change == "request_adoption":
        request["producer_adoption"]["definition_sha256"] = "f" * 64
    elif change == "body_adoption":
        body["adoption"]["definition_sha256"] = "f" * 64
    elif change.startswith("body_"):
        key = {"body_profile": "profile", "body_owner": "dataset", "body_operation": "operation", "body_request": "request_digest"}[change]
        body[key] = "different"
    elif change == "view_duplicate_witness":
        views["producer_evidence_witness"] = deepcopy(manifest["producer_evidence_witness"])
    elif change == "policy_id":
        request["policy_id"] = "unadopted-policy"
    else:
        for document in (manifest, views):
            del document["inputs"][0]["custody_reference"]
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_producer(row, manifest, views, request, body))


@pytest.mark.parametrize("change", ["profile", "candidate_owner", "candidate_operation", "accepted", "scope", "request_missing",
                                   "request_duplicate", "body_missing", "model_records", "source_name", "source_operation"])
def test_model_prerequisite_preserves_exact_proof_and_same_name_custody(native_snapshot_job, tmp_path, change):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, request, body = _producer_parts(row)
    prerequisites = [manifest["producer_evidence"]["prerequisite"], views["producer_evidence"]["prerequisite"],
                     request["prerequisites"][0], body["prerequisite"]]
    if change in {"profile", "candidate_owner", "candidate_operation", "accepted", "scope"}:
        for prerequisite in prerequisites:
            if change == "profile":
                prerequisite["profile"] = "caller-prerequisite"
            elif change == "candidate_owner":
                prerequisite["candidate"]["dataset"] = "foreign"
            elif change == "candidate_operation":
                prerequisite["candidate"]["operation"] = "original"
            elif change == "accepted":
                prerequisite["accepted_qualification"] = True
            else:
                prerequisite["inputs"] = ["source", "extra"]
    elif change == "request_missing":
        request["prerequisites"] = []
    elif change == "request_duplicate":
        request["prerequisites"].append(deepcopy(prerequisites[0]))
    elif change == "body_missing":
        del body["prerequisite"]
    elif change == "model_records":
        request["producer_records"] = [{"path": "/never/open/model-record"}]
    else:
        key = "input" if change == "source_name" else "operation"
        value = "aliased" if change == "source_name" else "unrelated-proof"
        source = request["snapshot_inputs"][0]["reuse_from"]
        source[key] = value
        if key == "operation":
            source["native_record"]["key"] = f"job-input/{value}/0"
        for document in (manifest, views):
            document["inputs"][0]["custody_grant"]["source"] = deepcopy(source)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_producer(row, manifest, views, request, body))


@pytest.mark.parametrize("change", ["selected", "missing_records", "empty_records", "prerequisite"])
def test_producer_proof_cannot_claim_model_selection_or_omit_original_records(native_snapshot_job, tmp_path, change):
    row = _producer_job(native_snapshot_job, tmp_path, "proof")
    manifest, views, request, body = _producer_parts(row)
    if change == "selected":
        row["selection"] = "selected"
    elif change == "missing_records":
        del request["producer_records"]
    elif change == "empty_records":
        request["producer_records"] = []
    else:
        request["prerequisites"] = [{"profile": "unverified"}]
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_producer(row, manifest, views, request, body))


def test_producer_proof_cannot_export_model_outputs(native_snapshot_job, tmp_path):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, request, body = _producer_parts(row)
    for document in (manifest, views):
        document["producer_evidence"]["role"] = "proof"
        del document["producer_evidence"]["prerequisite"]
    body["profile"] = "urn:docspec:whole-job-producer-static:1"
    del body["prerequisite"]
    request["prerequisites"] = []
    request["producer_records"] = [{"source": {"namespace": "original", "key": "head.json"},
                                    "path": "/never/open/head.json", "sha256": "e" * 64, "size": 73}]
    with pytest.raises(JobEvidenceError, match="cannot export"):
        verify_completed_job(_reseal_producer(row, manifest, views, request, body))


@pytest.mark.parametrize("change", ["sha256", "digest", "size", "bytes", "owner", "missing"])
def test_producer_witness_requires_exact_original_bytes(native_snapshot_job, tmp_path, change):
    row = _producer_job(native_snapshot_job, tmp_path, "model")
    manifest, views, _request, _body = _producer_parts(row)
    witness = manifest["producer_evidence_witness"]
    if change == "missing":
        del manifest["producer_evidence_witness"]
    elif change == "sha256":
        witness["sha256"] = "f" * 64
    elif change == "bytes":
        witness["bytes_base64"] = base64.b64encode(b'{}').decode()
    else:
        witness["reference"][{"digest": "digest", "size": "bytes", "owner": "owner"}[change]] = {
            "digest": "f" * 64, "size": 1, "owner": "foreign"}[change]
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_completion(row, manifest, views))


@pytest.mark.parametrize("fixture_name", ["native_job", "native_snapshot_job"])
@pytest.mark.parametrize("change", ["prerequisites", "adoption", "evidence"])
def test_earlier_completion_profiles_cannot_gain_producer_authority(request, fixture_name, change):
    row = deepcopy(request.getfixturevalue(fixture_name))
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    admitted = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    if change == "prerequisites":
        admitted["prerequisites"] = [{"profile": "unverified"}]
    elif change == "adoption":
        admitted["producer_adoption"] = {"passed": True}
    else:
        manifest["producer_evidence"] = {"passed": True}
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), admitted)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_completion(row, manifest, views))


@pytest.mark.parametrize("reuse", [False, True])
def test_bound_input_custody_preserves_opaque_identity_and_rebound_name_without_reads(native_snapshot_job, monkeypatch, reuse):
    row = _with_input_custody(native_snapshot_job, reuse=reuse)
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: pytest.fail("Custody metadata cannot open native payloads"))
    checked = verify_completed_job(row, require_accepted=True)
    view = checked.view_set["inputs"][0]
    assert view["custody_reference"] == row["input_custody"][0]
    assert view["custody_reference"]["admission_digest"]["value"] == "e" * 64
    assert view["custody_reference"]["admission_digest"]["value"] != view["admission"]["digest"]
    if reuse:
        source = checked.admitted_request["snapshot_inputs"][0]["reuse_from"]
        assert view["custody_grant"]["source"] == source
        assert source["input"] == "original_source" and view["name"] == "source"
        assert source["operation"] == "prior_consumer"
        assert {member["origin_operation"] for member in view["snapshot_custody"]["objects"]} == {"earliest_copy"}


@pytest.mark.parametrize("change", [
    "scheme", "foreign_owner", "operation", "request", "input", "table_uuid", "ordinal",
    "revision_zero", "revision_bool", "revision_float", "revision_large", "digest_algorithm", "digest", "extra_field",
])
def test_resealed_input_custody_reference_requires_exact_current_native_identity(native_snapshot_job, change):
    row = _with_input_custody(native_snapshot_job)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    reference = views["inputs"][0]["custody_reference"]
    if change == "scheme":
        reference["scheme"] = "urn:docspec:version-ref"
    elif change == "foreign_owner":
        reference["dataset"] = "elsewhere"
    elif change == "operation":
        reference["operation"] = "different"
        reference["native_record"]["key"] = "job-input/different/0"
    elif change == "request":
        reference["request_digest"] = "c" * 64
    elif change == "input":
        reference["input"] = "other_input"
    elif change == "table_uuid":
        reference["native_record"]["table_uuid"] = "table-name-is-not-its-incarnation"
    elif change == "ordinal":
        reference["native_record"]["key"] = "job-input/original/1"
    elif change.startswith("revision_"):
        reference["native_record"]["revision"] = {"revision_zero": 0, "revision_bool": True,
                                                  "revision_float": 17.0, "revision_large": 2**63}[change]
    elif change == "digest_algorithm":
        reference["admission_digest"]["algorithm"] = "sha256"
    elif change == "digest":
        reference["admission_digest"]["value"] = "invalid"
    else:
        reference["caller_accepted"] = True
    manifest["inputs"][0] = deepcopy(views["inputs"][0])
    row["input_custody"] = [deepcopy(reference)]
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_completion(row, manifest, views), require_accepted=True)


@pytest.mark.parametrize("change", [
    "missing_completed", "missing_view", "missing_receipt", "unbound_receipt", "duplicate_receipt",
    "changed_receipt", "decimal_completed", "decimal_receipt", "null_receipt",
])
def test_input_custody_copies_and_receipt_membership_cannot_disagree(native_snapshot_job, change):
    row = _with_input_custody(native_snapshot_job)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    if change == "missing_completed":
        manifest["inputs"][0].pop("custody_reference")
    elif change == "missing_view":
        views["inputs"][0].pop("custody_reference")
    elif change == "missing_receipt":
        row.pop("input_custody")
    elif change == "unbound_receipt":
        manifest["inputs"][0].pop("custody_reference")
        views["inputs"][0].pop("custody_reference")
    elif change == "duplicate_receipt":
        row["input_custody"] *= 2
    elif change == "changed_receipt":
        row["input_custody"][0]["native_record"]["revision"] += 1
    elif change == "decimal_completed":
        manifest["inputs"][0]["custody_reference"]["native_record"]["revision"] = 17.0
    elif change == "decimal_receipt":
        row["input_custody"][0]["native_record"]["revision"] = 17.0
    else:
        row["input_custody"] = None
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_completion(row, manifest, views), require_accepted=True)


@pytest.mark.parametrize("change", ["missing_reference", "missing_grant", "one_grant_copy", "changed_source", "extra_grant_field", "foreign_source", "different_source_table", "different_source_table_uuid"])
def test_requested_input_custody_reuse_needs_exact_bound_grant(native_snapshot_job, change):
    row = _with_input_custody(native_snapshot_job, reuse=True)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    view = views["inputs"][0]
    if change == "missing_reference":
        view.pop("custody_reference")
        row.pop("input_custody")
    elif change == "missing_grant":
        view.pop("custody_grant")
    elif change == "one_grant_copy":
        manifest["inputs"][0].pop("custody_grant")
    elif change == "changed_source":
        view["custody_grant"]["source"]["native_record"]["revision"] += 1
    elif change == "extra_grant_field":
        view["custody_grant"]["passed"] = True
    else:
        if change == "foreign_source":
            view["custody_grant"]["source"]["dataset"] = "another"
        else:
            field = "table_uuid" if change.endswith("uuid") else "table"
            view["custody_grant"]["source"]["native_record"][field] = (
                "2ac396e5-a58d-4004-80a5-3833f039c4b2" if field == "table_uuid" else "another-table"
            )
        request = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
        request["snapshot_inputs"][0]["reuse_from"] = deepcopy(view["custody_grant"]["source"])
        manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), request)
    if change != "one_grant_copy":
        manifest["inputs"][0] = deepcopy(view)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_completion(row, manifest, views), require_accepted=True)


def test_unrequested_input_custody_grant_and_file_profile_handles_refuse(native_snapshot_job, native_job):
    row = _with_input_custody(native_snapshot_job, reuse=True)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    request = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    request["snapshot_inputs"][0].pop("reuse_from")
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), request)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_reseal_completion(row, manifest, views), require_accepted=True)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(_with_input_custody(native_job), require_accepted=True)


@pytest.mark.parametrize("change", [None, "receipt_order", "mixed_legacy", "duplicate_ordinal", "different_table", "different_table_uuid"])
def test_input_custody_requires_all_native_inputs_in_exact_order(native_snapshot_job, tmp_path, change):
    row = _with_input_custody(native_snapshot_job)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    extra = deepcopy(views["inputs"][0])
    extra["name"] = extra["selector"]["name"] = "source_alias"
    job = _original_job(tmp_path)
    job["inputs"] = [deepcopy(views["inputs"][0]["selector"]), deepcopy(extra["selector"])]
    row = _retarget_original_job(row, job)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    extra["custody_reference"] = _input_custody_reference(input_name="source_alias", request_digest=manifest["request_digest"])
    extra["custody_reference"]["native_record"]["key"] = "job-input/original/1"
    extra["custody_reference"]["admission_digest"]["value"] = "f" * 64
    views["inputs"].append(extra)
    manifest["inputs"].append(deepcopy(extra))
    row["input_custody"].append(deepcopy(extra["custody_reference"]))
    policy = json.loads(base64.b64decode(row["policy"]["bytes_base64"]))
    policy["view_names"]["inputs"].append("source_alias")
    row["policy"] = _witness(Path(row["policy"]["reference"]["path"]), policy)
    request = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    request["snapshot_inputs"].append({**request["snapshot_inputs"][0], "name": "source_alias"})
    request["policy"]["sha256"] = row["policy"]["sha256"]
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), request)
    body = {key: deepcopy(row["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
    body["policy_sha256"] = row["policy"]["sha256"]
    row["accepted_qualification"] = _acceptance(body, row["policy"])
    if change == "receipt_order":
        row["input_custody"].reverse()
    elif change == "mixed_legacy":
        views["inputs"][1].pop("custody_reference")
        manifest["inputs"][1].pop("custody_reference")
        row["input_custody"].pop()
    elif change == "duplicate_ordinal":
        for reference in (views["inputs"][1]["custody_reference"], manifest["inputs"][1]["custody_reference"], row["input_custody"][1]):
            reference["native_record"]["key"] = "job-input/original/0"
    elif change in {"different_table", "different_table_uuid"}:
        field = "table_uuid" if change.endswith("uuid") else "table"
        for reference in (views["inputs"][1]["custody_reference"], manifest["inputs"][1]["custody_reference"], row["input_custody"][1]):
            reference["native_record"][field] = "2ac396e5-a58d-4004-80a5-3833f039c4b2" if field == "table_uuid" else "another-table"
    row = _reseal_completion(row, manifest, views)
    if change is None:
        checked = verify_completed_job(row, require_accepted=True)
        assert [item["custody_reference"]["input"] for item in checked.view_set["inputs"]] == ["source", "source_alias"]
    else:
        with pytest.raises(JobEvidenceError):
            verify_completed_job(row, require_accepted=True)


@pytest.mark.parametrize("status", ["pending", "unknown", "failed"])
def test_partial_input_custody_handles_do_not_create_catalog_input_bindings(native_snapshot_job, tmp_path, status):
    row = deepcopy(native_snapshot_job)
    row.update(status=status, candidate=None, completion_manifest=None, accepted_qualification=None,
               input_custody=[_input_custody_reference()])
    metadata, _entry, _receipt = _metadata(tmp_path, row)
    result = assemble_catalog(_authored_project(tmp_path), metadata=metadata.document.path,
                              metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    run = result.catalog["runs"][0]
    assert run["inputs"] == [] and run["inputCoverage"]["status"] == "unknown"
    assert not result.artifacts


@pytest.mark.parametrize("mutation", [
    lambda row: row["candidate"].update(operation="different"),
    lambda row: row["completion_manifest"].update(bytes_base64=base64.b64encode(b"{}").decode()),
    lambda row: row["completed_outputs"].pop(),
    lambda row: row["completed_reports"].pop(),
    lambda row: row["result"]["queries"][0].update(data=[{"orphan_count": 1}]),
    lambda row: row.update(accepted_qualification={"passed": True}),
    lambda row: row["accepted_qualification"].update(candidate={}),
    lambda row: row["accepted_qualification"]["native_record"].update(revision=0),
])
def test_wrong_candidate_incomplete_membership_and_caller_booleans_refuse(native_job, mutation):
    row = deepcopy(native_job)
    mutation(row)
    with pytest.raises(JobEvidenceError):
        verify_completed_job(row)


@pytest.mark.parametrize("mutation", [
    lambda body: body.update(reports=[]),
    lambda body: body["reports"][0].update(checks=[]),
    lambda body: body["reports"][0]["checks"][0].update(value=True),
    lambda body: body["reports"][0]["checks"][0].update(status="unknown"),
    lambda body: body["evaluator"].update(version="different"),
    lambda body: body["semantics"].update(revision="different"),
    lambda body: body.update(view_set_digest="f" * 64),
])
def test_resealed_incomplete_or_wrong_native_acceptance_refuses(native_job, mutation):
    row = deepcopy(native_job)
    body = {key: deepcopy(row["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
    mutation(body)
    row["accepted_qualification"] = _acceptance(body, row["policy"])
    with pytest.raises(JobEvidenceError):
        verify_completed_job(row)


def test_original_prepare_witness_retains_every_field_and_verifies_original_bytes(native_job):
    request = verify_admitted_request(native_job)
    assert request["definition"].startswith(DEFINITION_SCHEME + ":")
    assert request["file_inputs"] == [{"name": "source", "members": [{"key": None, "sha256": "1" * 64, "size": 7}]}]
    assert request["expected_epoch"] == 0 and request["expected_selection"] is None
    changed = deepcopy(native_job)
    changed["admitted_request"]["bytes_base64"] = base64.b64encode(b"{}").decode()
    with pytest.raises(JobEvidenceError):
        verify_admitted_request(changed)


def test_resealed_prepare_file_pin_cannot_disagree_with_retained_inputs(native_job):
    changed = deepcopy(native_job)
    admitted = deepcopy(verify_admitted_request(changed))
    admitted["file_inputs"][0]["members"][0]["sha256"] = "d" * 64
    request_path = Path(changed["admitted_request"]["reference"]["path"])
    request_witness = _witness(request_path, admitted)
    manifest = json.loads(base64.b64decode(changed["completion_manifest"]["bytes_base64"]))
    manifest["admitted_request"] = request_witness
    completion = _witness(Path(changed["candidate"]["manifest"]["path"]), manifest)
    changed.update(admitted_request=request_witness, completion_manifest=completion)
    changed["candidate"]["manifest"] = completion["reference"]
    body = {key: deepcopy(changed["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
    body["candidate"] = changed["candidate"]
    changed["accepted_qualification"] = _acceptance(body, changed["policy"])
    with pytest.raises(JobEvidenceError, match="file-member pins"):
        verify_completed_job(changed)


def test_catalog_maps_scoped_output_without_opening_payloads_or_caller_job(native_job, tmp_path, monkeypatch):
    metadata, entry, _receipt = _metadata(tmp_path, native_job)
    original = Path.open

    def metadata_only(path, *args, **kwargs):
        assert path.name in {"metadata.json", "receipt.json"}, f"Unexpected payload or caller input open: {path}"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    managed_execution(metadata, entry)
    outputs = metadata.observations["runs"][0]["outputs"]
    assert len(outputs) == 1
    policy = _policy_check(metadata.observations["checks"])
    assert policy["subject"] == outputs[0]
    assert policy["status"] == "passed"
    assert "does not assert" in policy["scope"]
    assert metadata.observations["runs"][0]["inputCoverage"]["status"] == "unknown"
    assert metadata.managed_jobs[0]["outOfCatalog"]["outputs"][0]["name"] == "private.parquet"
    source = next(row for row in metadata.version_facts.values() if row["dataset"] == "orders")
    assert source["reference"]["value"]["location"].endswith("never-open-captured.parquet")


@pytest.mark.parametrize("fixture_name", ["native_job", "native_snapshot_job", "native_producer_job"])
def test_mapped_catalog_facts_keep_normative_shapes(request, fixture_name, tmp_path):
    native_job = request.getfixturevalue(fixture_name)
    metadata, entry, _receipt = _metadata(tmp_path, native_job)
    managed_execution(metadata, entry)
    registry, schemas, _ = schema_registry()
    for kind, rows in (("run", metadata.observations["runs"]), ("check", metadata.observations["checks"]),
                       ("version", metadata.version_facts.values()), ("representation", metadata.observations["representations"])):
        validator = schema_validator({"$ref": f"{schemas['catalog']['$id']}#/$defs/{kind}"}, resource_registry=registry)
        for row in rows:
            assert not list(validator.iter_errors(row)), row


@pytest.mark.parametrize("fixture_name", ["native_job", "native_producer_job"])
def test_missing_acceptance_preserves_completion_and_required_unknown(request, fixture_name, tmp_path):
    native_job = request.getfixturevalue(fixture_name)
    metadata, entry, _receipt = _metadata(tmp_path, native_job, accepted=False)
    managed_execution(metadata, entry)
    assert metadata.observations["runs"][0]["outcome"] == "succeeded"
    assert _policy_check(metadata.observations["checks"])["status"] == "unknown"
    assert metadata.qualification and metadata.managed_jobs[0]["acceptedQualification"] is None
    if fixture_name == "native_producer_job":
        manifest = json.loads(base64.b64decode(native_job["completion_manifest"]["bytes_base64"]))
        assert metadata.managed_jobs[0]["producerEvidence"] == manifest["producer_evidence"]
    with pytest.raises(JobEvidenceError) as caught:
        verify_completed_job({**native_job, "accepted_qualification": None}, require_accepted=True)
    assert caught.value.status == "not_run"


@pytest.mark.parametrize("mutation", [
    lambda entry: entry["outOfCatalog"]["outputs"].clear(),
    lambda entry: entry["outputs"].update({"private.parquet": "daily-revenue"}),
    lambda entry: entry["inputs"].clear(),
    lambda entry: entry["outputs"].update({"unknown.parquet": "daily-revenue"}),
])
def test_catalog_requires_complete_unambiguous_native_dispositions(native_job, tmp_path, mutation):
    metadata, entry, _receipt = _metadata(tmp_path, native_job)
    mutation(entry)
    with pytest.raises(CatalogError) as caught:
        managed_execution(metadata, entry)
    assert caught.value.code == "CATALOG-NATIVE-MEMBERSHIP"


def test_diagnostic_failure_does_not_erase_complete_native_execution(native_job, tmp_path):
    metadata, entry, receipt = _metadata(tmp_path, native_job)
    receipt.update(status="error", error={"code": "DOCSPEC-DIAGNOSTIC-LIMIT"}, stderrTruncated=True)
    raw = _raw(receipt)
    Path(entry["receipt"]["path"]).write_bytes(raw)
    entry["receipt"]["sha256"] = sha256(raw).hexdigest()
    managed_execution(metadata, entry)
    assert metadata.observations["runs"][0]["outcome"] == "succeeded"
    assert metadata.operational_errors[0][0] == "DOCSPEC-DIAGNOSTIC-LIMIT"


@pytest.mark.parametrize("status, expected", [("pending", "not_run"), ("unknown", "unknown"), ("failed", "unknown")])
def test_incomplete_execution_preserves_known_outputs_and_uncertainty(native_job, tmp_path, status, expected):
    row = deepcopy(native_job)
    row.update(status=status, candidate=None, completion_manifest=None, accepted_qualification=None)
    row["completed_outputs"] = row["completed_outputs"][:1]
    metadata, entry, _receipt = _metadata(tmp_path, row)
    managed_execution(metadata, entry)
    assert len(metadata.observations["runs"][0]["outputs"]) == 1
    assert metadata.observations["runs"][0]["outcome"] == ("failed" if status == "failed" else "unknown")
    assert metadata.quality_issues[0].status == expected
    assert not metadata.observations["checks"]


@pytest.mark.parametrize("fixture_name", ["native_job", "native_snapshot_job", "native_producer_job"])
def test_real_assembly_binds_actual_catalog_result_and_opens_no_job_payloads(request, fixture_name, tmp_path, monkeypatch):
    native_job = request.getfixturevalue(fixture_name)
    project = _authored_project(tmp_path)
    metadata, _entry, _receipt = _metadata(tmp_path, native_job)
    original = Path.open

    def metadata_only(path, *args, **kwargs):
        assert not path.name.startswith("never-open") and path.name not in {"public.parquet", "private.parquet"}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    options = {"metadata": metadata.document.path, "metadata_adapter": "local", "permitted_roots": (tmp_path,),
               "required_groups": ("catalog.qualification",)}
    result = assemble_catalog(project, **options)
    assert result.report["decision"] == "passed", result.report
    assert result.catalog is not None and result.artifacts
    assert not validate_document(result.catalog, "catalog")
    run = result.catalog["runs"][0]
    version = next(row for row in result.catalog["versions"] if row["id"] in run["outputs"])
    assert version["dataset"] == "daily-revenue"
    assert version["reference"]["value"] == {"location": Path(native_job["completed_outputs"][0]["path"]).as_uri(), "sha256": "4" * 64}
    assert run["reference"]["value"] == native_job["candidate"]
    assert result.catalog["checks"][0]["subject"] == version["id"]
    trace = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]
    assert trace["acceptedQualification"] == native_job["accepted_qualification"]["identity"]
    assert trace["outOfCatalog"]["outputs"][0]["name"] == "private.parquet"
    manifest = json.loads(base64.b64decode(native_job["completion_manifest"]["bytes_base64"]))
    if fixture_name == "native_producer_job":
        assert trace["producerEvidence"] == manifest["producer_evidence"]
        assert set(trace["producerEvidence"]) == {"adoption", "role", "evidence", "prerequisite"}
        assert "producer_evidence_witness" not in trace
    else:
        assert "producerEvidence" not in trace
    assert not result.catalog["releases"] and not result.catalog["selections"]
    again = assemble_catalog(project, **options)
    assert again.report["decision"] == "passed" and again.artifacts == result.artifacts


def test_real_assembly_missing_acceptance_stays_incomplete_and_preserves_prior_controls(native_job, tmp_path):
    project = _authored_project(tmp_path)
    metadata, _entry, _receipt = _metadata(tmp_path, native_job)
    output = tmp_path / "controls"
    options = {"metadata": metadata.document.path, "metadata_adapter": "local", "permitted_roots": (tmp_path,), "output": output}
    accepted = assemble_catalog(project, **options)
    assert accepted.report["decision"] == "passed", accepted.report
    before = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    _metadata(tmp_path, native_job, accepted=False)
    incomplete = assemble_catalog(project, **options)
    assert incomplete.report["decision"] == "incomplete", incomplete.report
    assert incomplete.catalog["runs"][0]["outcome"] == "succeeded"
    assert _policy_check(incomplete.catalog["checks"])["status"] == "unknown"
    assert "catalog.qualification" in incomplete.report["coverage"]["requestedGroups"]
    assert not incomplete.artifacts
    assert before == {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}


@pytest.mark.parametrize("fixture_name", ["native_job", "native_snapshot_job", "native_producer_job"])
def test_real_public_assembly_withholds_private_members_paths_and_diagnostics(request, fixture_name, tmp_path):
    native_job = request.getfixturevalue(fixture_name)
    project = _authored_project(tmp_path)
    metadata, _entry, _receipt = _metadata(tmp_path, native_job)
    options = {"metadata": metadata.document.path, "metadata_adapter": "local", "permitted_roots": (tmp_path,)}
    local = assemble_catalog(project, **options)
    assert local.report["decision"] == "passed"
    catalog = local.catalog
    identifiers = {catalog["id"], catalog["project"]["id"], *(row["id"] for row in catalog["products"]),
                   *(row["id"] for row in catalog["datasets"]), *(row["definition"]["contractId"] for row in catalog["datasets"]),
                   *(row["id"] for row in catalog["versions"]), *(row["rule"]["id"] for row in catalog["checks"])}
    disclosure = tmp_path / "disclosure.json"
    disclosure.write_bytes(_raw({"identifiers": sorted(identifiers), "aliases": [COUNTER_EVALUATOR["id"]], "descriptions": True}))
    public = assemble_catalog(project, disclosure_policy=disclosure, **options)
    assert public.report["decision"] == "passed", public.report
    assert public.catalog["audience"] == "public" and public.artifacts
    assert public.catalog["checks"][0]["status"] == "passed"
    assert "managedExecutions" not in public.catalog["extensions"]["urn:ddk:catalog:assembly"]
    public_bytes = b"".join(public.artifacts.values()) + _raw(public.report) + _raw(public.catalog)
    for secret in (b"private.parquet", b"shared_join", b"native-lifecycle", b"never-open-job", str(tmp_path).encode(),
                   b"s3://fixture/table", b"4200827d-e8eb-4616-a0f9-ff4d222a582e", b"definition-one", b"/never/open/producer-record"):
        assert secret not in public_bytes
    assert public.local_catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"]

    # A missing disposition fails structural admission; its public report must
    # retain the refusal code without disclosing the omitted native filename.
    value = deepcopy(read_json(metadata.document.path).value)
    value["managedExecutions"][0]["outOfCatalog"]["outputs"] = []
    metadata.document.path.write_bytes(_raw(value))
    refused = assemble_catalog(project, disclosure_policy=disclosure, **options)
    assert refused.report["decision"] == "failed" and not refused.artifacts
    assert any(item["code"] == "CATALOG-NATIVE-MEMBERSHIP" for check in refused.report["checks"] for item in check["diagnostics"])
    assert b"private.parquet" not in _raw(refused.report) and str(tmp_path).encode() not in _raw(refused.report)


@pytest.mark.parametrize("change, expected", [("schema", "failed"), ("constraint", "incomplete"), ("production", "incomplete")])
def test_old_native_acceptance_cannot_qualify_changed_authored_definitions(native_job, tmp_path, change, expected):
    metadata, _entry, _receipt = _metadata(tmp_path, native_job)
    project = _authored_project(tmp_path)
    if change == "production":
        path = project.parent / "component.json"
        value = deepcopy(read_json(path).value)
        value["version"] = "1.0.1"
    else:
        path = project.parent / "definitions.json"
        value = deepcopy(read_json(path).value)
        if change == "schema":
            value["schema"][1]["properties"][0]["physicalType"] = "int32"
        else:
            value["schema"][1]["properties"][0]["unique"] = True
    path.write_bytes(_raw(value))
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == expected, result.report
    assert not result.artifacts
    checks = result.catalog["checks"]
    assert _policy_check(checks)["status"] == "passed"
    assert next(row for row in checks if row["rule"]["id"] == "urn:ddk:check:managed-definition-capture:1")["status"] == "unknown"
    assert "production" not in result.catalog["runs"][0]


def test_actual_assembly_rejects_extra_observed_native_output_field(native_job, tmp_path):
    pa = pytest.importorskip("pyarrow")
    changed = _with_output_schema(native_job, pa.schema([pa.field("id", pa.int64(), nullable=False),
                                                        pa.field("unadvertised", pa.string(), nullable=True)]))
    metadata, _entry, _receipt = _metadata(tmp_path, changed)
    result = assemble_catalog(_authored_project(tmp_path), metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "failed", result.report
    check = next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-output-interpretation:1")
    assert check["status"] == "failed" and "extra" in check["reason"]
    assert _policy_check(result.catalog["checks"])["status"] == "passed"
    assert not result.artifacts


@pytest.mark.parametrize("mismatch", ["child_type", "child_nullability", "list_element_nullability", "missing_child"])
def test_actual_assembly_rejects_nested_type_nullability_and_membership_mismatch(native_job, tmp_path, mismatch):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    path = project.parent / "definitions.json"
    value = deepcopy(read_json(path).value)
    value["schema"][1]["properties"] = [{"name": "children", "logicalType": "array", "required": True,
                                        "items": {"logicalType": "object", "required": True, "properties": [
                                            {"name": "code", "logicalType": "string", "physicalType": "string", "required": True}]}}]
    path.write_bytes(_raw(value))
    captured = managed_job_definition(assemble_catalog(project), **_mapping_kwargs())
    children = [] if mismatch == "missing_child" else [pa.field("code", pa.int64() if mismatch == "child_type" else pa.string(),
                                                              nullable=mismatch == "child_nullability")]
    schema = pa.schema([pa.field("children", pa.list_(pa.field("item", pa.struct(children),
                                                                nullable=mismatch == "list_element_nullability")), nullable=False)])
    changed = _with_output_schema(native_job, schema, definition=captured)
    metadata, _entry, _receipt = _metadata(tmp_path, changed)
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    expected = "incomplete" if "nullability" in mismatch else "failed"
    assert result.report["decision"] == expected, result.report
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-definition-capture:1")["status"] == "passed"
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-output-interpretation:1")["status"] == ("passed" if "nullability" in mismatch else "failed")
    assert not result.artifacts


@pytest.mark.parametrize("unsupported", ["timestamp", "native_id", "value_constraint"])
def test_exact_capture_does_not_turn_unsupported_authored_interpretation_into_pass(native_job, tmp_path, unsupported):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    path = project.parent / "definitions.json"
    value = deepcopy(read_json(path).value)
    field = value["schema"][1]["properties"][0]
    observed = pa.field("id", pa.int64(), nullable=False)
    if unsupported == "timestamp":
        field.update(logicalType="timestamp", physicalType="timestamp")
        observed = pa.field("id", pa.timestamp("us", tz="UTC"), nullable=False)
    elif unsupported == "native_id":
        field["customProperties"] = [{"vendor": "fixture", "property": "native_field_id", "value": 9}]
        observed = pa.field("id", pa.int64(), nullable=False, metadata={b"PARQUET:field_id": b"9"})
    else:
        field["unique"] = True
    path.write_bytes(_raw(value))
    captured = managed_job_definition(assemble_catalog(project), **_mapping_kwargs())
    changed = _with_output_schema(native_job, pa.schema([observed]), definition=captured)
    metadata, _entry, _receipt = _metadata(tmp_path, changed)
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-definition-capture:1")["status"] == "passed"
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-output-interpretation:1")["status"] == ("passed" if unsupported == "value_constraint" else "unknown")
    assert not result.artifacts


def test_exact_nested_native_interpretation_preserves_dictionary_fixed_width_and_positions(native_job, tmp_path):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    path = project.parent / "definitions.json"
    value = deepcopy(read_json(path).value)
    value["schema"][1]["properties"] = [
        {"name": "label", "logicalType": "string", "physicalType": "dict", "required": True},
        {"name": "tokens", "logicalType": "array", "physicalType": "list<struct<key fixed[8], rank int16>>", "required": True,
         "items": {"logicalType": "object", "physicalType": "struct<key fixed[8], rank int16>", "required": True,
                   "properties": [{"name": "key", "logicalType": "string", "physicalType": "fixed[8]", "required": True},
                                  {"name": "rank", "logicalType": "integer", "physicalType": "int16", "required": True}]}},
        {"name": "recorded", "logicalType": "timestamp", "physicalType": "timestamp<microsecond,UTC>", "required": True},
    ]
    path.write_bytes(_raw(value))
    captured = managed_job_definition(assemble_catalog(project), **_mapping_kwargs())
    schema = pa.schema([pa.field("tokens", pa.list_(pa.field("item", pa.struct([
        pa.field("key", pa.binary(8), nullable=False), pa.field("rank", pa.int16(), nullable=False)]), nullable=False)), nullable=False),
        pa.field("label", pa.dictionary(pa.int16(), pa.string()), nullable=False),
        pa.field("recorded", pa.timestamp("us", tz="UTC"), nullable=False)])
    metadata, _entry, _receipt = _metadata(tmp_path, _with_output_schema(native_job, schema, definition=captured))
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "passed", result.report
    interpretation = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]
    label = next(row for row in interpretation["fields"] if row["logicalPath"] == [{"field": "label"}])
    key = next(row for row in interpretation["fields"] if row["logicalPath"] == [{"field": "tokens"}, {"each": True}, {"field": "key"}])
    assert label["position"] == 1 and label["nativeType"].startswith("dictionary")
    assert key["nativePath"] == [{"field": "tokens"}, {"each": True}, {"field": "key"}]


def test_changed_resolved_source_custody_cannot_requalify_identical_effective_schema(native_job, tmp_path):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    path = project.parent / "definitions.json"
    value = deepcopy(read_json(path).value)
    field = value["schema"][1]["properties"][0]
    field["description"] = "Inline description retains precedence."
    field["authoritativeDefinitions"] = [{"type": "definition", "url": "shared.json"}]
    path.write_bytes(_raw(value))
    shared = project.parent / "shared.json"
    shared.write_bytes(_raw({"logicalType": "integer", "physicalType": "int64", "description": "Original source description."}))
    captured = managed_job_definition(assemble_catalog(project), **_mapping_kwargs())
    row = _with_output_schema(native_job, pa.schema([pa.field("id", pa.int64(), nullable=False)]), definition=captured)
    metadata, _entry, _receipt = _metadata(tmp_path, row)
    shared.write_bytes(_raw({"logicalType": "integer", "physicalType": "int64", "description": "Different exact source bytes."}))
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-output-interpretation:1")["status"] == "passed"
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-definition-capture:1")["status"] == "unknown"
    assert not result.artifacts


def test_source_backed_public_rule_api_qualifies_required_rows_without_rewriting_nullable_schema(native_job, tmp_path, monkeypatch):
    project, metadata, pin, profile, row, value = _native_rules_case(tmp_path, native_job)
    capture = assemble_catalog(project)
    assert managed_job_definition(capture, native_rules=pin, native_rule_profile=profile, **_mapping_kwargs()) == verify_admitted_request(row)["definition"]
    original = Path.open

    def metadata_only(path, *args, **kwargs):
        assert not path.name.startswith("never-open") and path.suffix != ".parquet"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    result = assemble_catalog(project, metadata=metadata, metadata_adapter="local", native_rule_profile=profile, permitted_roots=(tmp_path,))
    assert result.report["decision"] == "passed", result.report
    trace = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]
    observed = trace["outputInterpretations"][0]
    assert observed["fields"][0]["nullable"] is True
    assert observed["rowObligations"][0]["status"] == "passed"
    assert observed["rowObligations"][0]["nativeCounter"]["column"] == "orphan_count"
    assert value["bindings"] == [{"dataset": "daily-revenue", "output": "public.parquet", "facet": "required",
                                   "paths": [[{"field": "id"}]], "report": "invariants", "column": "orphan_count"}]
    assert not validate_document(result.catalog, "catalog")


@pytest.mark.parametrize("wrong", ["writer", "sql", "path", "column", "missing", "duplicate", "job_bytes", "source", "no_profile"])
def test_actual_assembly_refuses_wrong_native_facet_binding(native_job, tmp_path, wrong):
    job = _original_job(tmp_path)
    if wrong == "writer":
        job["queries"][0]["sql"] = job["queries"][0]["sql"].replace('outputs."public.parquet"', 'outputs."private.parquet"')
    elif wrong == "sql":
        job["queries"][0]["sql"] = "SELECT 0 AS orphan_count"

    def mutate(value):
        if wrong == "path":
            value["bindings"][0]["paths"] = [[{"field": "another_field"}]]
        elif wrong == "column":
            value["bindings"][0]["column"] = "different_counter"
        elif wrong == "missing":
            value["bindings"] = []
        elif wrong == "duplicate":
            value["bindings"] *= 2
        elif wrong == "job_bytes":
            value["job"] = {"sha256": sha256(b"{}").hexdigest(), "bytes_base64": base64.b64encode(b"{}").decode()}

    project, metadata, _pin, profile, _row, _value = _native_rules_case(tmp_path, native_job, job=job, mutate_artifact=mutate)
    if wrong == "source":
        Path(profile.source).write_text("# Different source bytes under the same declared profile version.\n", encoding="utf-8")
    result = assemble_catalog(project, metadata=metadata, metadata_adapter="local",
                              native_rule_profile=None if wrong == "no_profile" else profile, permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    assert not result.artifacts
    assert _policy_check(result.catalog["checks"])["status"] == "passed"
    assert any(item["code"].startswith("CATALOG-NATIVE-RULE-") for check in result.report["checks"] for item in check["diagnostics"])
    observations = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]
    assert observations["rowObligations"][0]["status"] == "unknown"


def test_ordered_primary_key_has_distinct_unique_and_null_rejection_bound_to_same_counter(native_job, tmp_path):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    definitions_path = project.parent / "definitions.json"
    definitions = deepcopy(read_json(definitions_path).value)
    definitions["schema"][1]["properties"] = [
        {"name": "id", "logicalType": "integer", "physicalType": "int64", "required": True, "primaryKey": True, "primaryKeyPosition": 2},
        {"name": "other", "logicalType": "integer", "physicalType": "int64", "required": True, "primaryKey": True, "primaryKeyPosition": 1},
    ]
    definitions_path.write_bytes(_raw(definitions))
    job = _original_job(tmp_path)
    job["outputs"][0]["sql"] = "SELECT id,CAST(7 AS BIGINT) AS other FROM shared_join"
    job["queries"][0]["sql"] = 'SELECT COUNT(*) AS orphan_count FROM (SELECT "other","id" FROM outputs."public.parquet" GROUP BY "other","id" HAVING COUNT(*)>1 OR "other" IS NULL OR "id" IS NULL) invalid_keys'
    project, metadata, _pin, profile, _row, value = _native_rules_case(
        tmp_path, native_job, job=job, schema=pa.schema([pa.field("id", pa.int64()), pa.field("other", pa.int64())]))
    result = assemble_catalog(project, metadata=metadata, metadata_adapter="local", native_rule_profile=profile, permitted_roots=(tmp_path,))
    assert result.report["decision"] == "passed", result.report
    keys = [binding for binding in value["bindings"] if binding["facet"].startswith("key_")]
    assert {row["facet"] for row in keys} == {"key_unique", "key_not_null"}
    assert all(row["paths"] == [[{"field": "other"}], [{"field": "id"}]] for row in keys)
    assert {row["column"] for row in keys} == {"orphan_count"}


def test_binary_format_with_exact_fixed_width_is_schema_evidence(native_job, tmp_path):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    path = project.parent / "definitions.json"
    value = deepcopy(read_json(path).value)
    value["schema"][1]["properties"][0].update(logicalType="string", physicalType="fixed[8]", logicalTypeOptions={"format": "binary"})
    path.write_bytes(_raw(value))
    captured = managed_job_definition(assemble_catalog(project), **_mapping_kwargs())
    metadata, _entry, _receipt = _metadata(tmp_path, _with_output_schema(native_job, pa.schema([pa.field("id", pa.binary(8), nullable=False)]), definition=captured))
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "passed", result.report


def test_authored_primary_key_survives_a_separate_project_alternate_key(native_job, tmp_path):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    definitions_path = project.parent / "definitions.json"
    definitions = deepcopy(read_json(definitions_path).value)
    definitions["schema"][1]["properties"] = [
        {"name": "id", "logicalType": "integer", "physicalType": "int64", "required": True, "primaryKey": True},
        {"name": "alternate_id", "logicalType": "integer", "physicalType": "int64", "required": False},
    ]
    definitions_path.write_bytes(_raw(definitions))
    project_value = deepcopy(read_json(project).value)
    project_value["catalog"]["identities"] = [{"dataset": "daily-revenue", "kind": "key", "scope": "dataset_version",
                                               "meaning": "An independently authored alternate key.",
                                               "fields": [{"path": [{"field": "alternate_id"}], "virtual": False, "physicalType": "int64"}]}]
    project.write_bytes(_raw(project_value))
    captured = managed_job_definition(assemble_catalog(project), **_mapping_kwargs())
    row = _with_output_schema(native_job, pa.schema([pa.field("id", pa.int64(), nullable=False), pa.field("alternate_id", pa.int64())]), definition=captured)
    metadata, _entry, _receipt = _metadata(tmp_path, row)
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    rows = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]["rowObligations"]
    unique_paths = [row["paths"] for row in rows if row["facet"] == "key_unique"]
    assert [[{"field": "id"}]] in unique_paths and [[{"field": "alternate_id"}]] in unique_paths
    assert not any(row["facet"] == "key_not_null" for row in rows)
    assert not result.artifacts


@pytest.mark.parametrize("extra", ["missing_field", "invented_facet"])
def test_generated_valid_plus_unauthored_extra_binding_cannot_be_silently_ignored(native_job, tmp_path, extra):
    pa = pytest.importorskip("pyarrow")
    project, metadata, pin, profile, row, value = _native_rules_case(tmp_path, native_job)

    class ExtraProfile(_FixtureRuleProfile):
        def bindings(self, context, original_job):
            values = super().bindings(context, original_job)
            return [*values, NativeRuleBinding("daily-revenue", "public.parquet", "required" if extra == "missing_field" else "key_unique",
                                               (({"field": "missing" if extra == "missing_field" else "id"},),), "invariants", "orphan_count")]

    selected = ExtraProfile(profile.source)
    value["bindings"].append({"dataset": "daily-revenue", "output": "public.parquet",
                              "facet": "required" if extra == "missing_field" else "key_unique",
                              "paths": [[{"field": "missing" if extra == "missing_field" else "id"}]],
                              "report": "invariants", "column": "orphan_count"})
    raw = _raw(value)
    Path(pin["path"]).write_bytes(raw)
    pin["sha256"] = sha256(raw).hexdigest()
    base = managed_job_definition(assemble_catalog(project), **_mapping_kwargs())
    definition = DEFINITION_SCHEME + ":" + sha256(json_dumps({"definition": base, "nativeRules": {"sha256": pin["sha256"], "profile": value["profile"]}}).encode()).hexdigest()
    changed = _with_output_schema(row, pa.schema([pa.field("id", pa.int64())]), definition=definition)
    mapped, entry, _receipt = _metadata(tmp_path, changed)
    entry["nativeRules"] = pin
    mapped.document.path.write_bytes(_raw({"managedExecutions": [entry]}))
    result = assemble_catalog(project, metadata=mapped.document.path, metadata_adapter="local", native_rule_profile=selected, permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    assert any(item["code"] == "CATALOG-NATIVE-RULE-SCOPE" for check in result.report["checks"] for item in check["diagnostics"])
    assert not result.artifacts


@pytest.mark.parametrize("generator_grant, source_grant", [(False, False), (True, False), (True, True)])
def test_public_native_facet_claim_requires_generator_identity_and_explicit_source_disclosure(native_job, tmp_path, generator_grant, source_grant):
    project, metadata, _pin, profile, _row, _value = _native_rules_case(tmp_path, native_job)
    options = {"metadata": metadata, "metadata_adapter": "local", "native_rule_profile": profile, "permitted_roots": (tmp_path,)}
    local = assemble_catalog(project, **options)
    assert local.report["decision"] == "passed"
    catalog = local.catalog
    selected = catalog["extensions"]["urn:ddk:catalog:assembly"]["nativeRuleProfile"]
    assert profile.identity in catalog["adapters"]
    ids = {catalog["id"], catalog["project"]["id"], *(item["id"] for item in catalog["products"]),
           *(item["id"] for item in catalog["datasets"]), *(item["definition"]["contractId"] for item in catalog["datasets"]),
           *(item["id"] for item in catalog["versions"]), *(item["rule"]["id"] for item in catalog["checks"])}
    if generator_grant:
        ids.add(profile.identity["id"])
    disclosure = tmp_path / "native-disclosure.json"
    disclosure.write_bytes(_raw({"identifiers": sorted(ids), "aliases": [COUNTER_EVALUATOR["id"]], "descriptions": True,
                                 "evidence": [selected["source"]["uri"]] if source_grant else []}))
    public = assemble_catalog(project, disclosure_policy=disclosure, **options)
    if not generator_grant:
        assert public.report["decision"] == "failed" and not public.artifacts
        assert str(tmp_path).encode() not in _raw(public.report)
    else:
        assert public.report["decision"] == "passed", public.report
        attribution = public.catalog["extensions"]["urn:ddk:catalog:assembly"]["nativeRuleProfile"]
        assert attribution["identity"] == profile.identity
        assert attribution["source"]["sha256"] == selected["source"]["sha256"]
        assert attribution["source"]["uri"] == (selected["source"]["uri"] if source_grant else "urn:ddk:sha256:" + selected["source"]["sha256"])
        assert any(row["rule"]["id"].startswith("urn:ddk:managed-value-facet:") and row["evaluator"] == COUNTER_EVALUATOR
                   for row in public.catalog["checks"])


def _export_key_case(tmp_path, native_job, *, hidden_sort=False, nullable=True, required=True):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    definitions_path = project.parent / "definitions.json"
    definitions = deepcopy(read_json(definitions_path).value)
    definitions["schema"][1]["properties"][0].update(primaryKey=True, primaryKeyPosition=1, required=required)
    definitions_path.write_bytes(_raw(definitions))
    job = _original_job(tmp_path)
    settings = job["outputs"][0]["settings"]
    settings["order_by"] = [{"field": "id"}, *([{"field": "source_occurrence"}] if hidden_sort else [])]
    settings["columns"] = ["id"]
    source = tmp_path / "required-generator.py"
    source.write_text(inspect.getsource(_RequiredOnlyProfile), encoding="utf-8")
    return _native_rules_case(tmp_path, native_job, job=job, profile=_RequiredOnlyProfile(source),
                               schema=pa.schema([pa.field("id", pa.int64(), nullable=nullable)]))


@pytest.mark.parametrize("nullable", [True, False])
def test_exact_complete_visible_export_sort_tuple_supplies_unique_evidence_only(native_job, tmp_path, nullable):
    project, metadata, _pin, profile, _row, value = _export_key_case(tmp_path, native_job, nullable=nullable)
    assert {binding["facet"] for binding in value["bindings"]} == {"required"}
    result = assemble_catalog(project, metadata=metadata, metadata_adapter="local", native_rule_profile=profile, permitted_roots=(tmp_path,))
    assert result.report["decision"] == "passed", result.report
    rows = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]["rowObligations"]
    unique = next(row for row in rows if row["facet"] == "key_unique")
    assert unique["status"] == "passed" and unique["nativeExport"]["sortFields"] == ["id"]
    check = next(row for row in result.catalog["checks"] if "ordered export" in row["scope"])
    assert check["evaluator"]["id"] == "docspec" and "nonnull" in check["scope"]
    if nullable:
        nonnull = next(row for row in rows if row["facet"] == "key_not_null")
        assert nonnull["status"] == "passed" and "composedNonnull" in nonnull
    else:
        assert not any(row["facet"] == "key_not_null" for row in rows)


def test_extra_hidden_source_occurrence_sort_cannot_prove_visible_business_key_unique(native_job, tmp_path):
    project, metadata, _pin, profile, _row, _value = _export_key_case(tmp_path, native_job, hidden_sort=True)
    result = assemble_catalog(project, metadata=metadata, metadata_adapter="local", native_rule_profile=profile, permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    rows = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]["rowObligations"]
    assert next(row for row in rows if row["facet"] == "key_unique")["status"] == "unknown"
    assert next(row for row in rows if row["facet"] == "key_not_null")["status"] == "passed"
    assert not result.artifacts


def test_export_unique_does_not_discharge_nonnull_without_authored_required_binding(native_job, tmp_path):
    project, metadata, _pin, profile, _row, _value = _export_key_case(tmp_path, native_job, required=False)
    result = assemble_catalog(project, metadata=metadata, metadata_adapter="local", native_rule_profile=profile, permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    rows = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]["rowObligations"]
    assert next(row for row in rows if row["facet"] == "key_unique")["status"] == "passed"
    assert next(row for row in rows if row["facet"] == "key_not_null")["status"] == "unknown"
    assert not result.artifacts


@pytest.mark.parametrize("unsupported", ["processor", "binary", "settings"])
def test_export_unique_requires_matching_native_processor_binary_and_settings(native_job, tmp_path, unsupported):
    project, metadata, pin, profile, row, _value = _export_key_case(tmp_path, native_job)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    if unsupported == "processor":
        manifest["runtime"]["processor"] = "uninterpreted-exporter"
    elif unsupported == "binary":
        manifest["runtime"]["binary_sha256"] = "d" * 64
    else:
        views["outputs"][0]["settings"]["order_by"] = [{"field": "source_occurrence"}]
    changed = _reseal_completion(row, manifest, views)
    mapped, entry, _receipt = _metadata(tmp_path, changed)
    entry["nativeRules"] = pin
    mapped.document.path.write_bytes(_raw({"managedExecutions": [entry]}))
    result = assemble_catalog(project, metadata=mapped.document.path, metadata_adapter="local", native_rule_profile=profile, permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    rows = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]["rowObligations"]
    assert next(row for row in rows if row["facet"] == "key_unique")["status"] == "unknown"
    assert not result.artifacts


@pytest.mark.parametrize("target", ["context", "job"])
def test_explicit_profile_receives_immutable_definition_and_original_job_arguments(native_job, tmp_path, target):
    source = tmp_path / "mutating-generator.py"
    source.write_text("# Independent adversarial callback fixture.\n", encoding="utf-8")

    class MutatingProfile(_FixtureRuleProfile):
        def bindings(self, context, original_job):
            if target == "context":
                context.datasets["daily-revenue"]["properties"][0]["required"] = False
            else:
                original_job["queries"][0]["sql"] = "SELECT 0"
            return super().bindings(context, original_job)

    capture = assemble_catalog(_authored_project(tmp_path))
    before = _raw(capture.local_catalog)
    with pytest.raises(CatalogError) as caught:
        native_rule_artifact(capture, _raw(_original_job(tmp_path)), native_rule_profile=MutatingProfile(source), **_mapping_kwargs())
    assert caught.value.code == "CATALOG-NATIVE-RULE-PROFILE" and caught.value.status == "unknown"
    assert _raw(capture.local_catalog) == before


@pytest.mark.parametrize("positions", [(1, 1), (None, None)])
def test_ambiguous_primary_order_stays_unknown_when_alternate_project_key_masks_core_derivation(native_job, tmp_path, positions):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    path = project.parent / "definitions.json"
    definitions = deepcopy(read_json(path).value)
    definitions["schema"][1]["properties"] = [
        {"name": name, "logicalType": "integer", "physicalType": "int64", "primaryKey": True,
         **({"primaryKeyPosition": position} if position is not None else {})}
        for name, position in zip(("id", "other"), positions)
    ] + [{"name": "alternate_id", "logicalType": "integer", "physicalType": "int64"}]
    path.write_bytes(_raw(definitions))
    value = deepcopy(read_json(project).value)
    value["catalog"]["identities"] = [{"dataset": "daily-revenue", "kind": "key", "scope": "dataset_version", "meaning": "Separate alternate key.",
                                        "fields": [{"path": [{"field": "alternate_id"}], "virtual": False, "physicalType": "int64"}]}]
    project.write_bytes(_raw(value))
    capture = assemble_catalog(project)
    assert capture.report["decision"] == "passed"
    row = _with_output_schema(native_job, pa.schema([pa.field(name, pa.int64()) for name in ("id", "other", "alternate_id")]),
                              definition=managed_job_definition(capture, **_mapping_kwargs()))
    metadata, _entry, _receipt = _metadata(tmp_path, row)
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    rows = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]["rowObligations"]
    assert next(row for row in rows if row["facet"] == "unsupported_primary_key_order")["status"] == "unknown"
    assert not result.artifacts


@pytest.mark.parametrize("container", ["object", "array"])
def test_nested_authored_primary_key_remains_required_unknown(native_job, tmp_path, container):
    pa = pytest.importorskip("pyarrow")
    project = _authored_project(tmp_path)
    path = project.parent / "definitions.json"
    definitions = deepcopy(read_json(path).value)
    code = {"name": "code", "logicalType": "string", "physicalType": "string", "primaryKey": True}
    children = {"name": "children", "logicalType": container}
    if container == "array":
        children["items"] = {"logicalType": "object", "properties": [code]}
        native = pa.list_(pa.struct([pa.field("code", pa.string())]))
        expected_path = [{"field": "children"}, {"each": True}, {"field": "code"}]
    else:
        children["properties"] = [code]
        native = pa.struct([pa.field("code", pa.string())])
        expected_path = [{"field": "children"}, {"field": "code"}]
    definitions["schema"][1]["properties"] = [children]
    path.write_bytes(_raw(definitions))
    capture = assemble_catalog(project)
    assert capture.report["decision"] == "passed", capture.report
    row = _with_output_schema(native_job, pa.schema([pa.field("children", native)]),
                              definition=managed_job_definition(capture, **_mapping_kwargs()))
    metadata, _entry, _receipt = _metadata(tmp_path, row)
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    observed = result.catalog["extensions"]["urn:ddk:catalog:assembly"]["managedExecutions"][0]["outputInterpretations"][0]
    assert observed["status"] == "passed"
    assert any(item["facet"] == "unsupported_primary_key_scope" and item["paths"] == [expected_path]
               and item["status"] == "unknown" for item in observed["rowObligations"])
    assert not result.artifacts


@pytest.mark.parametrize("status", ["pending", "unknown", "failed"])
def test_incomplete_native_observation_never_invents_a_current_production_binding(native_job, tmp_path, status):
    project = _authored_project(tmp_path)
    row = deepcopy(native_job)
    row.update(status=status, candidate=None, completion_manifest=None, accepted_qualification=None)
    row["completed_outputs"] = row["completed_outputs"][:1]
    metadata, _entry, _receipt = _metadata(tmp_path, row)
    path = project.parent / "component.json"
    production = deepcopy(read_json(path).value)
    production["version"] = "99.0.0"
    path.write_bytes(_raw(production))
    result = assemble_catalog(project, metadata=metadata.document.path, metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "incomplete", result.report
    run = result.catalog["runs"][0]
    assert "production" not in run
    assert run["reference"]["value"]["operation"] == row["operation"]
    assert len(run["outputs"]) == 1 and not result.artifacts


@pytest.mark.parametrize("changed", ["policy", "expected_epoch", "expected_selection"])
def test_original_policy_id_cannot_change_policy_bytes_or_authority_conditions(native_job, tmp_path, changed):
    row = deepcopy(native_job)
    manifest = json.loads(base64.b64decode(row["completion_manifest"]["bytes_base64"]))
    views = json.loads(base64.b64decode(manifest["view_set"]["bytes_base64"]))
    original = json.loads(base64.b64decode(manifest["admitted_request"]["bytes_base64"]))
    if changed == "policy":
        original["policy"]["sha256"] = "9" * 64
    elif changed == "expected_epoch":
        original["expected_epoch"] = 17
    else:
        original["expected_selection"] = deepcopy(row["candidate"])
    manifest["admitted_request"] = _witness(Path(manifest["admitted_request"]["reference"]["path"]), original)
    row = _reseal_completion(row, manifest, views)
    with pytest.raises(JobEvidenceError, match="original policy ID"):
        verify_completed_job(row)
    metadata, _entry, _receipt = _metadata(tmp_path, row)
    result = assemble_catalog(_authored_project(tmp_path), metadata=metadata.document.path,
                              metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "failed", result.report
    assert not result.artifacts


def test_distinct_requalification_policy_preserves_original_request_with_new_authority(native_job, tmp_path):
    row = deepcopy(native_job)
    original = verify_admitted_request(row)
    policy = json.loads(base64.b64decode(row["policy"]["bytes_base64"]))
    policy["id"] = "counters-v2"
    witness = _witness(Path(row["policy"]["reference"]["path"]).with_name("policy-v2.json"), policy)
    body = {key: deepcopy(row["accepted_qualification"][key]) for key in ACCEPTANCE_FIELDS}
    body.update(policy_id="counters-v2", policy_sha256=witness["sha256"], expected_epoch=17,
                expected_selection=deepcopy(row["candidate"]))
    row.update(policy_id="counters-v2", active_policy_id="counters-v2", policy=witness,
               accepted_qualification=_acceptance(body, witness), selection="pending")
    verified = verify_completed_job(row, require_accepted=True)
    assert verified.admitted_request == original
    assert verified.accepted["expected_epoch"] == 17 and original["expected_epoch"] == 0
    metadata, _entry, _receipt = _metadata(tmp_path, row)
    result = assemble_catalog(_authored_project(tmp_path), metadata=metadata.document.path,
                              metadata_adapter="local", permitted_roots=(tmp_path,))
    assert result.report["decision"] == "passed", result.report
