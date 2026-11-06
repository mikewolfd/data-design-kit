"""Independent metadata examples; these do not establish native execution."""

import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ddk.catalog_access import CatalogError
from ddk.catalog import assemble_catalog
from ddk.catalog_managed_jobs import DEFINITION_SCHEME, managed_execution, managed_job_definition, managed_job_metadata
from ddk.catalog_metadata import LOCAL_ADAPTER, LocalMetadata
from ddk.core import load_project
from ddk.docspec_job_evidence import (
    ACCEPTANCE_FIELDS, CANDIDATE_SCHEME, COMPLETION_PROFILE, COUNTER_EVALUATOR,
    COUNTER_PROFILE, COUNTER_SEMANTICS, VIEW_PROFILE, JobEvidenceError, verify_admitted_request, verify_completed_job,
)
from ddk.documents import read_json, schema_registry, schema_validator, validate_document


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
            "native_record": {"table": "archive/native-lifecycle", "key": "job-accepted/original/counters-v1", "revision": 3}}


def _mapping_kwargs():
    return {"production": "summarize", "inputs": {"source": "orders"}, "outputs": {"public.parquet": "daily-revenue"},
            "out_of_catalog": {"inputs": [], "outputs": [{"name": "private.parquet", "reason": "Internal recovery output."}]}}


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
        {"name": "invariants", "sql_sha256": "6" * 64, "schema_sha256": counters_key, "rows": 1,
         "data": [{"orphan_count": 0}], "completion": _reference(native / "invariants.json")},
        {"name": "metadata_counts", "sql_sha256": "7" * 64, "schema_sha256": metadata_key, "rows": 1,
         "data": [{"population": 2}], "completion": _reference(native / "counts.json")},
    ]
    views = {"profile": VIEW_PROFILE, "dataset": "archive", "operation": "original", "request_digest": "a" * 64,
             "inputs": inputs, "steps": steps,
             "outputs": [{**row, "settings": {"profile": "whole"}, "completion": _reference(native / f"{row['name']}.json")}
                         for row in outputs],
             "reports": [{key: value for key, value in row.items() if key != "data"} | {"dependencies": [{"name": "shared_join"}]}
                         for row in reports]}
    view_witness = _witness(native / "views.json", views)
    job_result = {"steps": [{"name": "shared_join", "storage": "memory"}],
                  "outputs": [{key: value for key, value in row.items() if key not in {"path", "schema_sha256"}} for row in outputs],
                  "queries": [{"name": row["name"], "data": row["data"]} for row in reports]}
    manifest = {"profile": COMPLETION_PROFILE, "dataset": "archive", "operation": "original", "request_digest": "a" * 64,
                "job": {"path": str(tmp_path / "never-open-job.json"), "sha256": "b" * 64, "size": 130},
                "inputs": inputs, "steps": steps, "outputs": outputs, "reports": reports,
                "view_set": view_witness, "view_set_digest": view_witness["reference"]["digest"], "schemas": schemas,
                "evaluator": COUNTER_EVALUATOR,
                "runtime": {"id": "docspec", "version": "test-only", "binary_sha256": "c" * 64},
                "execution": "completed", "result": job_result}
    policy = {"id": "counters-v1", "profile": COUNTER_PROFILE, "evaluator": COUNTER_EVALUATOR, "semantics": COUNTER_SEMANTICS,
              "job_sha256": "b" * 64, "view_names": {key: [row["name"] for row in manifest[key]] for key in ("inputs", "steps", "outputs", "reports")},
              "required_reports": [{"name": "invariants", "sql_sha256": "6" * 64, "schema_ipc_base64": schemas[counters_key]}]}
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
    policy = next(row for row in metadata.observations["checks"] if row["evaluator"] == COUNTER_EVALUATOR)
    assert policy["subject"] == outputs[0]
    assert policy["status"] == "passed"
    assert "does not assert" in policy["scope"]
    assert metadata.observations["runs"][0]["inputCoverage"]["status"] == "unknown"
    assert metadata.managed_jobs[0]["outOfCatalog"]["outputs"][0]["name"] == "private.parquet"
    source = next(row for row in metadata.version_facts.values() if row["dataset"] == "orders")
    assert source["reference"]["value"]["location"].endswith("never-open-captured.parquet")


def test_mapped_catalog_facts_keep_normative_shapes(native_job, tmp_path):
    metadata, entry, _receipt = _metadata(tmp_path, native_job)
    managed_execution(metadata, entry)
    registry, schemas, _ = schema_registry()
    for kind, rows in (("run", metadata.observations["runs"]), ("check", metadata.observations["checks"]),
                       ("version", metadata.version_facts.values()), ("representation", metadata.observations["representations"])):
        validator = schema_validator({"$ref": f"{schemas['catalog']['$id']}#/$defs/{kind}"}, resource_registry=registry)
        for row in rows:
            assert not list(validator.iter_errors(row)), row


def test_missing_acceptance_preserves_completion_and_required_unknown(native_job, tmp_path):
    metadata, entry, _receipt = _metadata(tmp_path, native_job, accepted=False)
    managed_execution(metadata, entry)
    assert metadata.observations["runs"][0]["outcome"] == "succeeded"
    assert next(row for row in metadata.observations["checks"] if row["evaluator"] == COUNTER_EVALUATOR)["status"] == "unknown"
    assert metadata.qualification and metadata.managed_jobs[0]["acceptedQualification"] is None
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


def test_real_assembly_binds_actual_catalog_result_and_opens_no_job_payloads(native_job, tmp_path, monkeypatch):
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
    assert next(row for row in incomplete.catalog["checks"] if row["evaluator"] == COUNTER_EVALUATOR)["status"] == "unknown"
    assert "catalog.qualification" in incomplete.report["coverage"]["requestedGroups"]
    assert not incomplete.artifacts
    assert before == {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}


def test_real_public_assembly_withholds_private_members_paths_and_diagnostics(native_job, tmp_path):
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
    for secret in (b"private.parquet", b"shared_join", b"native-lifecycle", b"never-open-job", str(tmp_path).encode()):
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
    assert next(row for row in checks if row["evaluator"] == COUNTER_EVALUATOR)["status"] == "passed"
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
    assert next(row for row in result.catalog["checks"] if row["evaluator"] == COUNTER_EVALUATOR)["status"] == "passed"
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
    assert result.report["decision"] == "failed", result.report
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-definition-capture:1")["status"] == "passed"
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-output-interpretation:1")["status"] == "failed"
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
    assert next(row for row in result.catalog["checks"] if row["rule"]["id"] == "urn:ddk:check:managed-output-interpretation:1")["status"] == "unknown"
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
