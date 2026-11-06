"""CLI decision, strict JSON and explicit execution-selection regressions."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "examples/commerce/project.ddk.json"


def invoke(*args):
    return subprocess.run([sys.executable, "-m", "ddk", *map(str, args), "--format", "json"],
                          capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def test_cli_has_one_json_report_and_distinct_exit_codes(tmp_path):
    good = invoke("check", PROJECT)
    assert good.returncode == 0 and json.loads(good.stdout)["decision"] == "passed"
    missing = invoke("check", PROJECT, "--require", "test.portability")
    assert missing.returncode == 2 and json.loads(missing.stdout)["decision"] == "incomplete"
    malformed = tmp_path / "project.json"
    malformed.write_text('{"id": "a", "id": "b"}')
    bad = invoke("check", malformed)
    assert bad.returncode == 1 and json.loads(bad.stdout)["decision"] == "failed"
    absent = invoke("check", tmp_path / "absent.json")
    assert absent.returncode == 3 and json.loads(absent.stdout)["decision"] == "error"
    usage = invoke("build", PROJECT)
    assert usage.returncode == 64 and json.loads(usage.stdout)["decision"] == "error"


def test_offline_core_does_not_import_native_adapters():
    code = '''
import importlib.abc, sys
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in {'duckdb','pyarrow','datacontract','dlt','frictionless'} or fullname.startswith('ddk.adapters'):
            raise RuntimeError('Optional native import: '+fullname)
sys.meta_path.insert(0,Deny())
from ddk.cli import main
raise SystemExit(main(['check',sys.argv[1],'--format','json']))
'''
    result = subprocess.run([sys.executable, "-c", code, str(PROJECT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "passed"


def test_explicit_missing_execution_adapter_is_incomplete(tmp_path):
    result = invoke("test", PROJECT, "--fixture", ROOT / "examples/commerce/tests/revenue.fixture.ddk.json", "--output", tmp_path / "run")
    report = json.loads(result.stdout)
    assert result.returncode == 2
    assert any(c["status"] == "not_run" and c["group"] == "runtime.job" for c in report["checks"])


def test_locked_core_and_failed_output_preservation(tmp_path):
    lock = tmp_path / "lock.json"
    assert invoke("lock", PROJECT, "--output", lock).returncode == 0
    assert invoke("check", PROJECT, "--lock", lock, "--locked").returncode == 0
    output = tmp_path / "report.json"
    assert invoke("check", PROJECT, "--output", output).returncode == 0
    preserved = output.read_bytes()
    assert invoke("check", PROJECT, "--require", "plan.standard", "--output", output).returncode == 2
    assert output.read_bytes() == preserved


def _invalid_call(tmp_path):
    import shutil

    commerce = tmp_path / "commerce"
    shutil.copytree(PROJECT.parent, commerce)
    path = commerce / "designs" / "order-preview.ddk.json"
    design = json.loads(path.read_text())
    del design["steps"]["read"]["arguments"]["year"]
    path.write_text(json.dumps(design))
    return commerce / PROJECT.name


def test_cli_003_progress_is_stderr_and_invalid_call_is_one_json_report(tmp_path):
    from ddk.documents import validate_document

    result = invoke("check", _invalid_call(tmp_path), "--progress")
    report = json.loads(result.stdout)
    assert result.returncode == 1 and report["decision"] == "failed"
    assert not validate_document(report)
    assert "CALL-ARGUMENT-MISSING" in result.stdout
    assert result.stderr == "DDK check started\n"


def test_result_003_human_severity_filter_keeps_failed_decision(tmp_path):
    project = _invalid_call(tmp_path)
    visible = subprocess.run([sys.executable, "-m", "ddk", "check", str(project)],
                             text=True, capture_output=True)
    hidden = subprocess.run([sys.executable, "-m", "ddk", "check", str(project), "--severity", "info"],
                            text=True, capture_output=True)
    machine = invoke("check", project, "--severity", "info")
    assert visible.returncode == hidden.returncode == machine.returncode == 1
    assert "CALL-ARGUMENT-MISSING" in visible.stdout
    assert hidden.stdout == "DDK failed\n"
    report = json.loads(machine.stdout)
    assert report["decision"] == "failed"
    assert any(check["status"] == "failed" for check in report["checks"])


def _native_limits(tmp_path):
    path = tmp_path / "limits.json"
    path.write_text(json.dumps({
        "compute_threads": 2, "memory_bytes": 256 << 20, "scratch_bytes": 64 << 20,
        "batch_rows": 8192, "max_batch_bytes": 8 << 20, "max_metadata_bytes": 2 << 20,
    }))
    return path


def test_cli_004_two_exports_preserve_previous_complete_bundle(tmp_path):
    binary = os.environ.get("DDK_DOCSPEC_SQL_ONLY_BINARY")
    if not binary:
        pytest.skip("Set DDK_DOCSPEC_SQL_ONLY_BINARY to the pinned build without Substrait")
    output = tmp_path / "bundle"
    args = ("build", PROJECT, "--component", "summarize", "--output", output,
            "--docspec", binary, "--limits", _native_limits(tmp_path), "--export", "sql")
    first = invoke(*args)
    assert first.returncode == 0, first.stdout
    prior = {path.name: path.read_bytes() for path in output.iterdir()}
    requested = invoke(*args, "--export", "substrait")
    report = json.loads(requested.stdout)
    assert requested.returncode == 2, requested.stdout
    assert report["decision"] == "incomplete"
    assert any(check["status"] == "not_run" and any(
        diagnostic["code"] == "ADAPTER-EXPORT-UNAVAILABLE" for diagnostic in check["diagnostics"]
    ) for check in report["checks"])
    assert {path.name: path.read_bytes() for path in output.iterdir()} == prior


def test_managed_cli_prior_receipt_refuses_cross_dataset_before_submission(tmp_path):
    binary = os.environ.get("DDK_DOCSPEC_BINARY")
    if not binary:
        pytest.skip("Set DDK_DOCSPEC_BINARY to the pinned native build")
    workspace = tmp_path / "host"
    workspace.mkdir()
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"action": "inspect", "dataset": "different", "operation": "build-1"}))
    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({
        "operationContext": {"runtime": "docspec", "workspace": str(workspace),
                             "dataset": "original", "operationId": "build-1"},
        "operation": {"runtime": "docspec", "mode": "managed_operation", "operationId": "build-1"},
    }))
    output = tmp_path / "report.json"
    command = invoke("managed", PROJECT, "--request", request, "--workspace", workspace, "--prior", prior,
                     "--docspec", binary, "--limits", _native_limits(tmp_path), "--output", output)
    assert command.returncode == 1, command.stdout
    assert "EXEC-RECONCILIATION-SCOPE" in command.stdout
    assert not list(workspace.iterdir())
    assert prior.exists()


def test_safe_002_structured_parameters_and_secret_evidence(tmp_path, monkeypatch):
    import shutil

    binary = os.environ.get("DDK_DOCSPEC_BINARY")
    tool_python = os.environ.get("DDK_NATIVE_PYTHON")
    if not binary or not tool_python:
        pytest.skip("Set DDK_DOCSPEC_BINARY and DDK_NATIVE_PYTHON to run bounded SQL with quality")
    commerce = tmp_path / "commerce"
    shutil.copytree(PROJECT.parent, commerce)
    component_path = commerce / "components/summarize.ddk.json"
    component = json.loads(component_path.read_text())
    component["parameters"]["properties"].update({
        "literal": {"type": "string"}, "credential": {"type": "string"},
    })
    component_path.write_text(json.dumps(component))
    fixture_path = commerce / "tests/revenue.fixture.ddk.json"
    fixture = json.loads(fixture_path.read_text())
    marker = tmp_path / "unexpected-command-effect"
    literal = f"$(touch {marker})"
    secret = "case-safe-private-'quoted'-string-0375"
    fixture["parameters"]["literal"] = literal
    fixture_path.write_text(json.dumps(fixture))
    sql_path = commerce / "transforms/revenue.sql"
    sql = sql_path.read_text()
    # Both parameters must reach SQL as actual values before it returns the authored rows.
    guard = (f"AND CAST($literal AS VARCHAR) = '{literal}'\n"
             f"AND character_length(CAST($credential AS VARCHAR)) = {len(secret)}\n")
    sql_path.write_text(sql.replace("GROUP BY", guard + "GROUP BY"))
    monkeypatch.setenv("DDK_FIXTURE_CREDENTIAL", secret)
    output = tmp_path / "fixture-run"
    result = invoke("test", commerce / PROJECT.name, "--fixture", fixture_path, "--implementation", "sql",
                    "--secret-parameter", "credential=DDK_FIXTURE_CREDENTIAL", "--output", output,
                    "--docspec", binary, "--limits", _native_limits(tmp_path), "--tool-python", tool_python)
    report = json.loads(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["decision"] == "passed"
    assert not marker.exists()
    assert secret not in result.stdout + result.stderr
    receipts = [path for path in output.rglob("*.json") if path.name == "receipt.json"]
    assert any(json.loads(path.read_text()).get("redaction", {}).get("nativeEvidence") == "redacted-view"
               for path in receipts)
    assert any(literal in path.read_text() for path in output.rglob("request.json"))
    assert all(secret not in path.read_text() for path in output.rglob("*")
               if path.is_file() and path.suffix in {".json", ".log"})
    assert not list(output.rglob(".private-request-*"))


def test_build_rejects_reordered_output_fields_before_replacing_bundle(tmp_path):
    import shutil

    binary = os.environ.get("DDK_DOCSPEC_SQL_ONLY_BINARY")
    if not binary:
        pytest.skip("Set DDK_DOCSPEC_SQL_ONLY_BINARY to the pinned build without Substrait")
    commerce = tmp_path / "commerce"
    shutil.copytree(PROJECT.parent, commerce)
    output = tmp_path / "bundle"
    args = ("build", commerce / PROJECT.name, "--component", "summarize", "--output", output,
            "--docspec", binary, "--limits", _native_limits(tmp_path), "--export", "sql")
    assert invoke(*args).returncode == 0
    prior = (output / "bundle.ddk.json").read_bytes()
    sql_path = commerce / "transforms/revenue.sql"
    sql_path.write_text(sql_path.read_text().replace("SELECT o.order_day, c.region", "SELECT c.region, o.order_day"))
    second = invoke(*args)
    assert second.returncode == 1
    assert "Inferred field names or order differ" in second.stdout
    assert (output / "bundle.ddk.json").read_bytes() == prior


def test_sql_only_runtime_executes_authored_fixture(tmp_path):
    binary = os.environ.get("DDK_DOCSPEC_SQL_ONLY_BINARY")
    tool_python = os.environ.get("DDK_NATIVE_PYTHON")
    if not binary or not tool_python:
        pytest.skip("Set DDK_DOCSPEC_SQL_ONLY_BINARY and DDK_NATIVE_PYTHON")
    result = invoke("test", PROJECT, "--fixture", PROJECT.parent / "tests/revenue.fixture.ddk.json",
                    "--implementation", "sql", "--output", tmp_path / "run",
                    "--docspec", binary, "--limits", _native_limits(tmp_path), "--tool-python", tool_python)
    report = json.loads(result.stdout)
    assert result.returncode == 0, result.stdout
    assert report["decision"] == "passed"
    assert "plan.consumer" not in report["coverage"]["requestedGroups"]
    assert all(operation["selection"] == "not_requested" for operation in report["operations"])
    assert report["metadata"]["fixture"]["comparisons"]["sql"]["status"] == "passed"


def test_build_preserves_unmanaged_and_modified_prior_bundle_contents(tmp_path):
    binary = os.environ.get("DDK_DOCSPEC_SQL_ONLY_BINARY")
    if not binary:
        pytest.skip("Set DDK_DOCSPEC_SQL_ONLY_BINARY to the pinned build without Substrait")
    output = tmp_path / "bundle"
    args = ("build", PROJECT, "--component", "summarize", "--output", output,
            "--docspec", binary, "--limits", _native_limits(tmp_path), "--export", "sql")
    assert invoke(*args).returncode == 0
    assert invoke(*args).returncode == 0  # An intact managed set can be replaced.
    unmanaged = output / "user-notes.txt"
    unmanaged.write_text("Notes owned by the caller.")
    refused = invoke(*args)
    assert refused.returncode == 3 and "EXEC-BUNDLE-UNOWNED" in refused.stdout
    assert unmanaged.read_text() == "Notes owned by the caller."
    unmanaged.unlink()
    sql = output / "calculation.sql"
    sql.write_text("SELECT 'local edit';")
    refused = invoke(*args)
    assert refused.returncode == 3 and "EXEC-BUNDLE-UNOWNED" in refused.stdout
    assert sql.read_text() == "SELECT 'local edit';"


def test_declared_custom_function_without_runtime_implementation_is_not_run(tmp_path):
    import shutil

    binary = os.environ.get("DDK_DOCSPEC_SQL_ONLY_BINARY")
    if not binary:
        pytest.skip("Set DDK_DOCSPEC_SQL_ONLY_BINARY to the pinned SQL build")
    commerce = tmp_path / "commerce"
    shutil.copytree(PROJECT.parent, commerce)
    component_path = commerce / "components/summarize.ddk.json"
    component = json.loads(component_path.read_text())
    component["extensions"] = {"urn:test:function-declaration": {
        "name": "project_amount", "input": "integer", "result": "integer",
    }}
    component_path.write_text(json.dumps(component))
    source = commerce / "transforms/revenue.sql"
    source.write_text(source.read_text().replace("SUM(o.amount_cents)", "project_amount(o.amount_cents)"))
    output = tmp_path / "bundle"
    result = invoke("build", commerce / PROJECT.name, "--component", "summarize", "--output", output,
                    "--docspec", binary, "--limits", _native_limits(tmp_path), "--export", "sql")
    report = json.loads(result.stdout)
    assert result.returncode == 2, result.stdout
    assert report["decision"] == "incomplete"
    assert any(item["status"] == "not_run" and any(
        diagnostic["code"] == "ADAPTER-FUNCTION-IMPLEMENTATION-MISSING"
        for diagnostic in item["diagnostics"]
    ) for item in report["checks"])
    assert not output.exists()


def test_bundle_interruption_after_native_binary_preserves_previous_outputs(tmp_path, monkeypatch):
    from ddk.adapters.docspec import DocSpecAdapter
    from ddk.execution import build_project

    binary = os.environ.get("DDK_DOCSPEC_BINARY")
    if not binary:
        pytest.skip("Set DDK_DOCSPEC_BINARY to the pinned saved-plan build")
    runtime = DocSpecAdapter(binary, _native_limits(tmp_path), evidence_dir=tmp_path / "evidence")
    bundle = tmp_path / "bundle"
    assert build_project(PROJECT, "summarize", runtime=runtime, output=bundle, formats=("sql",))["decision"] == "passed"
    prior = {path.name: path.read_bytes() for path in bundle.iterdir()}
    prepare = runtime.prepare
    partial = []

    def obstruct_second_native_output(request):
        outputs = request["calculation"]["save_substrait"]
        Path(outputs["readable_path"]).write_text("Another writer owns this destination.")
        result = prepare(request)
        partial.append(Path(outputs["path"]).read_bytes())
        return result

    monkeypatch.setattr(runtime, "prepare", obstruct_second_native_output)
    interrupted = build_project(PROJECT, "summarize", runtime=runtime, output=bundle,
                                formats=("sql", "substrait"))
    assert partial[0], "The native runtime must have created the first staged output"
    assert interrupted["decision"] == "error"
    assert interrupted["operationalErrors"][0]["code"] == "EXEC-BUILD-INTERRUPTED"
    assert any(item["status"] == "not_run" and item["group"] == "plan.compile" for item in interrupted["checks"])
    assert {path.name: path.read_bytes() for path in bundle.iterdir()} == prior
