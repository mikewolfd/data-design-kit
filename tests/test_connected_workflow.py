"""The no-pilot local stack demonstration binds every stage to real receipts."""

from datetime import datetime, timezone
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, unquote
import os
import shutil

import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.adapters.native import NativeTools
from ddk.catalog import build_catalog
from ddk.catalog_access import run_checked_query
from ddk.documents import DocumentError, json_dumps, read_json, validate_document
from ddk.execution import run_fixture
from ddk.fixtures import compare_rows
from ddk.impact import impact_projects

ROOT = Path(__file__).resolve().parents[1]
LIMITS = {"batch_rows": 8192, "compute_threads": 2, "max_batch_bytes": 8 << 20,
          "max_metadata_bytes": 2 << 20, "memory_bytes": 256 << 20, "scratch_bytes": 64 << 20}


def test_connected_staged_saved_plan_quality_catalog_reader(tmp_path):
    binary, python = os.environ.get("DDK_DOCSPEC_BINARY"), os.environ.get("DDK_NATIVE_PYTHON")
    if not binary or not python:
        pytest.skip("Select the actual pinned DocSpec and native Python tools")
    project = ROOT / "examples/commerce/project.ddk.json"
    fixture = ROOT / "examples/commerce/tests/revenue.fixture.ddk.json"
    runtime = DocSpecAdapter(binary, LIMITS, evidence_dir=tmp_path / "runtime")
    native = NativeTools(python, output=tmp_path / "native")
    report = run_fixture(project, fixture, runtime=runtime, tools=native, output=tmp_path / "run",
                         bindings=ROOT / "examples/commerce/bindings.ddk.json")
    assert report["decision"] == "passed", report
    assert not validate_document(report, "report")
    data = report["metadata"]["fixture"]
    execution = data["executions"]["substrait"]
    quality = data["quality"]["substrait"]
    snapshot = execution["operation"]["outputs"][0]
    assert execution["receipt"]["result"]["saved_plans"][0]["sha256"] == data["preparation"]["result"]["substrait"]["sha256"]
    request = read_json(execution["receipt"]["request"]["path"]).value
    assert request["queries"] == [], "Exported bytes, not a rerun transformation, supply the expectation check"
    staged = {item["dataset"]: item["receipt"] for item in data["staging"]}
    for item in execution["receipt"]["inputs"]:
        if item.get("format") == "parquet":
            assert any(item["path"] == f["path"] and item["sha256"] == f["sha256"]
                       for stage in staged.values() for f in stage["files"])
    assert quality["target"]["files"] == [{"path": snapshot["path"], "sha256": snapshot["sha256"]}]
    assert quality["fixtureComparison"]["status"] == "passed"
    manifest = {
        "executions": [{"path": execution["evidence"]["path"], "production": "summarize",
                        "inputs": {"orders": "orders", "customers": "customers"}, "outputs": {"rows": "daily-revenue"}}],
        "quality": [{"path": quality["receipt"]["path"], "dataset": "daily-revenue", "scope": "Every row of the exact saved-plan output"}],
        "staging": [{"path": receipt["receipt"]["path"], "dataset": alias} for alias, receipt in staged.items()],
        "productionObservations": [{"production": "summarize", "observedAt": execution["receipt"]["startedAt"]}],
        "publications": [{"id": "urn:test:reference:release", "authority": "urn:test:reference:publisher",
                          "purpose": "local-conformance", "observedAt": execution["receipt"]["endedAt"],
                          "members": {"orders": staged["orders"]["files"][0]["sha256"],
                                      "customers": staged["customers"]["files"][0]["sha256"], "daily-revenue": snapshot["sha256"]}}],
    }
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json_dumps(manifest))
    generated = build_catalog(project, metadata=metadata, metadata_adapter="local", exports=("dcat", "openlineage"),
                              output=tmp_path / "catalog", permitted_roots=(tmp_path,))
    assert generated["decision"] == "passed", generated
    assert not validate_document(generated, "report")
    observed = []
    def reader(binding):
        inputs, digests = [], {}
        for name, member in binding["inputs"].items():
            ref = member["reference"]["value"]
            path = str(Path(unquote(urlsplit(ref["location"]).path)))
            observed.append((path, ref["sha256"]))
            inputs.append({"kind": "parquet", "name": name, "path": path})
            digests[path] = ref["sha256"]
        response = runtime.execute({"scratch": str(tmp_path / "read-scratch"), "inputs": inputs,
                                    "steps": [], "outputs": [], "queries": [{"name": "consumer", "sql": binding["sql"].decode()}]},
                                   input_digests=digests)
        assert response["status"] == "succeeded", response
        return {"result": response["result"]["queries"][0]["data"], "receipt": response["evidence"]}
    consumed = run_checked_query(tmp_path / "catalog/catalog.ddk.json", "urn:example:commerce:recipe:checked-revenue",
                                 reader, release="urn:test:reference:release")
    assert observed == [(snapshot["path"], snapshot["sha256"])]
    consumed["comparison"] = compare_rows(read_json(fixture).value["expected"]["rows"], consumed["result"])
    assert consumed["comparison"]["status"] == "passed"
    (tmp_path / "consumer-result.json").write_text(json_dumps(consumed))
    candidate = tmp_path / "changed-project"
    shutil.copytree(project.parent, candidate)
    definition_path = candidate / "definitions/amount-cents.json"
    definition = deepcopy(read_json(definition_path).value)
    definition["quality"][0]["query"] = "SELECT COUNT(*) FROM ${object} WHERE amount_cents < 1"
    definition_path.write_text(json_dumps(definition))
    impact = impact_projects(project, candidate / "project.ddk.json")
    assert impact["impact"]["changed"]
    assert "summarize" in impact["metadata"]["affectedObligations"]
    assert "requalification" in impact["metadata"]["affectedObligations"]["summarize"]
    (tmp_path / "impact-report.json").write_text(json_dumps(impact))
    references = {name: {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()} for name, path in {
        "fixtureReport": tmp_path / "run/report.ddk.json",
        "catalog": tmp_path / "catalog/catalog.ddk.json",
        "catalogReport": tmp_path / "catalog/catalog.report.json",
        "consumerResult": tmp_path / "consumer-result.json",
        "impactReport": tmp_path / "impact-report.json",
    }.items()}
    (tmp_path / "reference-workflow.json").write_text(json_dumps(references))
    from ddk.conformance import verify_reference_workflow
    gate = verify_reference_workflow(references, evidence_root=tmp_path,
                                     claimed_profiles=("files.frictionless", "ingest.dlt"))
    (tmp_path / "workflow-verification.json").write_text(json_dumps(gate))
    assert gate["decision"] == "passed", gate
    disconnected = verify_reference_workflow({k: v for k, v in references.items() if k != "consumerResult"},
                                             evidence_root=tmp_path)
    assert disconnected["decision"] == "incomplete"


@pytest.mark.parametrize("scenario", ("empty", "integer-date-boundary", "wrong-join"))
def test_fixture_boundary_expectations_are_independent(tmp_path, scenario):
    binary, python = os.environ.get("DDK_DOCSPEC_BINARY"), os.environ.get("DDK_NATIVE_PYTHON")
    if not binary or not python:
        pytest.skip("Select the actual pinned DocSpec and native Python tools")
    project_root = tmp_path / "commerce"
    shutil.copytree(ROOT / "examples/commerce", project_root)
    fixture_path = project_root / "tests/revenue.fixture.ddk.json"
    fixture = deepcopy(read_json(fixture_path).value)
    if scenario == "empty":
        fixture["inputs"]["orders"]["rows"] = []
        fixture["expected"]["rows"] = []
    elif scenario == "integer-date-boundary":
        fixture["inputs"]["customers"]["rows"] = [{"customer_id": "c1", "region": "north"}]
        fixture["inputs"]["orders"]["rows"] = [
            {"order_id": "b1", "customer_id": "c1", "order_day": "2024-02-29", "amount_cents": 9007199254740993, "status": "completed"},
            {"order_id": "b2", "customer_id": "c1", "order_day": "2024-02-29", "amount_cents": 2, "status": "completed"},
            {"order_id": "b3", "customer_id": "c1", "order_day": "2024-03-01", "amount_cents": 7, "status": "completed"},
        ]
        fixture["expected"]["rows"] = [
            {"order_day": "2024-02-29", "region": "north", "amount_cents": 9007199254740995},
            {"order_day": "2024-03-01", "region": "north", "amount_cents": 7},
        ]
    else:
        # The altered join still produces the promised types and passes the
        # nonnegative-output rule. The independently authored totals reject it.
        sql = project_root / "transforms/revenue.sql"
        original = sql.read_text()
        changed = original.replace("o.customer_id = c.customer_id", "o.customer_id <> c.customer_id")
        assert changed != original
        sql.write_text(changed)
    fixture_path.write_text(json_dumps(fixture))
    report = run_fixture(project_root / "project.ddk.json", fixture_path,
                         runtime=DocSpecAdapter(binary, LIMITS, evidence_dir=tmp_path / "runtime"),
                         tools=NativeTools(python, output=tmp_path / "native"), output=tmp_path / "run")
    expected = "failed" if scenario == "wrong-join" else "passed"
    assert report["decision"] == expected, report
    comparisons = report["metadata"]["fixture"]["comparisons"]
    assert set(comparisons) == {"sql", "substrait"}
    assert all(result["status"] == expected for result in comparisons.values())


def test_duplicate_binding_origin_is_rejected_before_any_native_call(tmp_path):
    project_root = tmp_path / "commerce"
    shutil.copytree(ROOT / "examples/commerce", project_root)
    binding_path = project_root / "bindings.ddk.json"
    binding = deepcopy(read_json(binding_path).value)
    binding["data"].append(deepcopy(binding["data"][0]))
    binding_path.write_text(json_dumps(binding))
    class Uncalled:
        def __getattr__(self, name):
            raise AssertionError("Invalid bindings must be refused before native work")
    with pytest.raises(DocumentError) as refusal:
        run_fixture(project_root / "project.ddk.json", project_root / "tests/revenue.fixture.ddk.json",
                    runtime=Uncalled(), tools=Uncalled(), output=tmp_path / "run", bindings=binding_path)
    assert refusal.value.code == "EXEC-BINDING-DUPLICATE"


def test_cli_fixture_cleanup_retains_failure_and_unrelated_data(tmp_path, capsys, monkeypatch):
    from ddk import cli
    binary, python = os.environ.get("DDK_DOCSPEC_BINARY"), os.environ.get("DDK_NATIVE_PYTHON")
    if not binary or not python:
        pytest.skip("Select the actual pinned DocSpec and native Python tools")
    original_mkdtemp = cli.tempfile.mkdtemp
    folders = []
    def owned_directory(*args, **kwargs):
        if kwargs.get("prefix") == "ddk-command-":
            kwargs["dir"] = tmp_path
            result = original_mkdtemp(*args, **kwargs)
            folders.append(Path(result))
            return result
        return original_mkdtemp(*args, **kwargs)
    monkeypatch.setattr(cli.tempfile, "mkdtemp", owned_directory)
    unrelated = tmp_path / "native-candidate-retained"
    unrelated.write_text("Caller-owned retained state")
    limits = tmp_path / "limits.json"
    limits.write_text(json_dumps(LIMITS))
    base = ["test", str(ROOT / "examples/commerce/project.ddk.json"), "--implementation", "sql",
            "--docspec", binary, "--tool-python", python, "--limits", str(limits), "--format", "json"]
    assert cli.main([*base, "--fixture", str(ROOT / "examples/commerce/tests/revenue.fixture.ddk.json")]) == 0
    passed = __import__("json").loads(capsys.readouterr().out)
    assert passed["decision"] == "passed" and not folders[-1].exists()
    fixture = deepcopy(read_json(ROOT / "examples/commerce/tests/revenue.fixture.ddk.json").value)
    fixture["expected"]["rows"][0]["amount_cents"] = 999
    broken = tmp_path / "independent-wrong-expectation.fixture.json"
    broken.write_text(json_dumps(fixture))
    assert cli.main([*base, "--fixture", str(broken)]) == 1
    failed = __import__("json").loads(capsys.readouterr().out)
    assert failed["decision"] == "failed" and folders[-1].is_dir()
    assert failed["operations"] and failed["metadata"]["dataLifetime"]["retained"] is True
    assert unrelated.read_text() == "Caller-owned retained state"


@pytest.mark.parametrize("interruption", ("timeout", "cancel"))
def test_fixture_caller_interruption_retains_original_uncertain_request(tmp_path, interruption):
    binary, python = os.environ.get("DDK_DOCSPEC_BINARY"), os.environ.get("DDK_NATIVE_PYTHON")
    if not binary or not python:
        pytest.skip("Select the actual pinned DocSpec and native Python tools")
    class InterruptedExecution(DocSpecAdapter):
        def execute(self, request, **kwargs):
            # Preparation is unchanged; only waiting for actual execution ends.
            if interruption == "timeout":
                self.timeout = 0.001
            else:
                class CancelAfterSubmission:
                    calls = 0
                    def is_set(self):
                        self.calls += 1
                        return self.calls > 1
                kwargs["cancel_event"] = CancelAfterSubmission()
            return super().execute(request, **kwargs)
    report = run_fixture(ROOT / "examples/commerce/project.ddk.json",
                         ROOT / "examples/commerce/tests/revenue.fixture.ddk.json",
                         runtime=InterruptedExecution(binary, LIMITS, evidence_dir=tmp_path / "runtime"),
                         tools=NativeTools(python, output=tmp_path / "native"), output=tmp_path / "run", formats=("sql",))
    assert report["decision"] == "error"
    expected_code = "EXEC-CANCELLED" if interruption == "cancel" else "EXEC-OUTCOME-UNKNOWN"
    assert any(error["code"] == expected_code for error in report["operationalErrors"])
    operation, = report["operations"]
    assert operation["execution"] == "unknown" and operation["reconciliation"] == "unsupported"
    assert operation["selection"] == "not_requested" and operation["outputs"] == []
    execution = report["metadata"]["fixture"]["executions"]["sql"]
    retained = read_json(execution["evidence"]["path"]).value
    assert retained["operation"]["requestIdentity"] == operation["requestIdentity"]
    assert (tmp_path / "run/report.ddk.json").is_file()
