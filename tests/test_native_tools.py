"""Opt-in, actual maintained-tool tests; expected violations are authored here."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import subprocess
import tarfile
from time import monotonic

import pytest

from ddk.adapters.native import NativeTools, run_bounded
from ddk.core import load_project
from ddk.documents import read_json
from ddk.quality import dataset_rules
from ddk.execution import _record
from ddk.results import ReportBuilder, exit_code

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native(tmp_path):
    python = os.environ.get("DDK_NATIVE_PYTHON")
    if not python:
        pytest.skip("Select the pinned native Python tool environment")
    return NativeTools(python, output=tmp_path)


def document(extra=None):
    obj = {"apiVersion": "v3.2.0", "kind": "DataContract", "id": "urn:test:quality", "version": "1.0.0", "status": "draft",
           "schema": [{"name": "records", "logicalType": "object", "properties": [
               {"name": "id", "logicalType": "integer", "required": True, "unique": True},
               {"name": "value", "logicalType": "integer", "required": True}],
               "quality": [{"id": "nonnegative", "type": "sql", "query": "SELECT count(*) FROM records WHERE value < 0", "mustBe": 0}]}]}
    if extra:
        obj["schema"][0]["quality"].extend(extra)
    return obj


def exact_file(native, doc, rows):
    result = native.invoke("fixture-files", {"inputs": {"records": {"dataset": doc["schema"][0], "rows": rows}}})
    assert result["status"] == "passed", result
    member = result["files"][0]
    return {"kind": "files", "files": [{"path": member["path"], "sha256": member["sha256"]}]}


def test_quality_keeps_failed_unknown_and_missing_checks(native):
    doc = document()
    target = exact_file(native, doc, [{"id": 1, "value": -1}, {"id": 1, "value": 3}])
    result = native.invoke("quality", {"document": doc, "target": target})
    assert result["status"] == "failed", result
    assert any(c["id"].endswith("field_unique") and c["status"] == "failed" for c in result["checks"])
    assert any(c.get("qualityId") == "nonnegative" and c["status"] == "failed" for c in result["checks"])
    target = exact_file(native, doc, [{"id": 1, "value": 3}])
    missing = native.invoke("quality", {"document": doc, "target": target, "requiredCheckIds": ["missing-check"]})
    assert missing["status"] == "not_run"
    unsupported = document([{"id": "external-custom", "type": "custom", "engine": "unavailable", "implementation": "check data"}])
    assert native.invoke("odcs-lint", {"document": unsupported})["status"] == "passed"
    unknown = native.invoke("quality", {"document": unsupported, "target": target})
    assert unknown["status"] in ("not_run", "unknown"), unknown
    assert any(c["id"].startswith("ddk:unmapped-quality:") for c in unknown["checks"])
    builder = ReportBuilder("urn:test:unsupported-quality", required_groups=("data.odcs",))
    _record(builder, "data.odcs", "records", unknown, requirement="DDK-ADAPTER-003")
    reduced = builder.build()
    assert reduced["decision"] == "incomplete" and exit_code(reduced) == 2
    assert reduced["checks"][-1]["diagnostics"][0]["code"] == "ADAPTER-QUALITY-UNSUPPORTED"


def test_native_lint_and_version_perspective_are_separate(native):
    base = document()
    assert native.invoke("odcs-lint", {"document": base})["status"] == "passed"
    candidate = deepcopy(base)
    candidate["version"] = "2.0.0"
    candidate["schema"][0]["properties"].pop()
    consumer = native.invoke("odcs-versions", {"base": base, "candidate": candidate, "perspective": "consumer"})
    producer = native.invoke("odcs-versions", {"base": base, "candidate": candidate, "perspective": "producer"})
    assert consumer["native"]["is_breaking"] is True and consumer["status"] == "failed"
    assert producer["native"]["is_breaking"] is False
    # The native detector leaves the metadata version change untested. Keep
    # that limit visible rather than reducing non-breaking to fully passed.
    assert producer["status"] == "unknown"
    assert consumer["perspective"] == "consumer" and producer["perspective"] == "producer"


def test_selected_definition_resolver_matches_pinned_development_semantics(native, tmp_path):
    source, archive = os.environ.get("DDK_ODCS_DEV_SOURCE"), os.environ.get("DDK_ODCS_DEV_ARCHIVE")
    if not source or not archive:
        pytest.skip("Select the retained public development source and exact archive")
    assert sha256(Path(archive).read_bytes()).hexdigest() == "fab9cc88b9e499de24220d568c565d9d1036640bd0f2a4dac90008796e851909"
    prefix = "datacontract-cli-34b12923e0366fa4004c2f90644da41769699e0f/"
    with tarfile.open(archive) as upstream:
        for member in upstream.getmembers():
            relative = member.name.removeprefix(prefix)
            if member.isfile() and relative.startswith("datacontract/") and relative.endswith(".py"):
                assert (Path(source) / relative).read_bytes() == upstream.extractfile(member).read()
    probe = '''
import json, tempfile
from pathlib import Path
from datacontract.lint.resolve import inline_definition_into_property
from datacontract.model.enum_values import get_enum_values
from open_data_contract_standard.model import SchemaProperty
with tempfile.TemporaryDirectory() as root:
    location=Path(root)
    (location/'base.json').write_text(json.dumps({'logicalType':'string','logicalTypeOptions':{'pattern':'^A','maxLength':20},'enum':[{'value':'A01'}]}))
    field=SchemaProperty.model_validate({'name':'code','logicalType':'string','logicalTypeOptions':{'maxLength':8},'customProperties':[{'property':'enum','value':['A02']}],'authoritativeDefinitions':[{'type':'definition','url':'base.json'}]})
    inline_definition_into_property(field,base_location=str(location/'main.json'))
    print(json.dumps({'options':field.logicalTypeOptions,'values':get_enum_values(field)}))
'''
    observations = {}
    for label, path in (("published-1.2.9", ""), ("development-34b12923", source)):
        result = subprocess.run([str(native.python), "-c", probe], env={**os.environ, "PYTHONPATH": path},
                                text=True, capture_output=True, timeout=30, check=True)
        observations[label] = json.loads(result.stdout)
    assert observations["published-1.2.9"] == {"options": {"maxLength": 8}, "values": ["A01"]}
    assert observations["development-34b12923"] == {"options": {"pattern": "^A", "maxLength": 8}, "values": ["A02"]}
    (tmp_path / "native-resolver-comparison.json").write_text(json.dumps(observations, indent=2))


def test_quality_uses_original_types_and_exact_case(native):
    doc = document()
    actual = deepcopy(doc)
    actual["schema"][0]["properties"][1] = {"name": "VALUE", "logicalType": "string", "required": True}
    target = exact_file(native, actual, [{"id": 1, "VALUE": "3"}])
    result = native.invoke("quality", {"document": doc, "target": target})
    assert result["status"] == "failed"
    assert next(c for c in result["checks"] if c["id"] == "ddk:exact-field-names")["status"] == "failed"
    assert any(c["id"].endswith("field_type") and c["status"] == "failed" for c in result["checks"])


def test_quality_cannot_use_unbound_file_or_environment(native, monkeypatch):
    doc = document()
    target = exact_file(native, doc, [{"id": 1, "value": 3}])
    other = exact_file(native, doc, [{"id": 9, "value": 4}])
    path = other["files"][0]["path"].replace("'", "''")
    bad = document([{"id": "outside", "type": "sql", "query": f"SELECT count(*) FROM read_parquet('{path}')", "mustBe": 1}])
    result = native.invoke("quality", {"document": bad, "target": target})
    assert result["status"] == "not_run", result
    assert result["operational"]["queryIssues"][0]["code"] == "QUALITY-SQL-UNSUPPORTED"
    monkeypatch.setenv("DDK_IMPLICIT_LIMIT", "0")
    implicit = document([{"id": "environment", "type": "sql", "query": "SELECT ${DDK_IMPLICIT_LIMIT}", "mustBe": 0}])
    result = native.invoke("quality", {"document": implicit, "target": target})
    assert result["status"] == "failed", result
    result = native.invoke("quality", {"document": implicit, "target": target, "parameters": None})
    assert result["status"] == "failed"


def test_output_readback_compares_exact_file_without_transform_rerun(native):
    doc = document()
    target = exact_file(native, doc, [{"id": 1, "value": 3}])
    result = native.invoke("quality", {"document": doc, "target": target, "expectedRows": [{"id": 1, "value": 9}],
                                        "comparison": {"rows": "unordered-multiset", "absoluteTolerance": 0, "relativeTolerance": 0}})
    assert result["status"] == "passed", result
    assert result["fixtureComparison"]["status"] == "failed"
    evidence = read_json(result["fixtureComparison"]["evidence"]["path"]).value
    assert evidence["target"] == target and evidence["rows"] == [{"id": 1, "value": 3}]


def test_frictionless_composite_key_and_invalid_date(native, tmp_path):
    dataset = {"name": "records", "properties": [{"name": "id", "logicalType": "integer", "required": True},
                                                 {"name": "day", "logicalType": "date", "required": True}],
               "customProperties": [{"vendor": "ddk", "property": "rowIdentity", "value": ["id", "day"]}]}
    for filename, body in (("duplicate.csv", "id,day\n1,2026-01-01\n1,2026-01-01\n"),
                           ("invalid.csv", "id,day\n1,2026-02-30\n")):
        path = tmp_path / filename
        path.write_text(body)
        result = native.invoke("files", {"dataset": dataset, "files": [{"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}]})
        assert result["status"] == "failed", result
        assert result["native"][0]["stats"]["errors"] >= 1


def test_dlt_freeze_and_exact_native_job_inventory(native):
    dataset = document()["schema"][0]
    failed = native.invoke("stage", {"dataset": dataset, "rows": [{"id": 1, "value": 3, "new_field": "unexpected"}]})
    assert failed["status"] == "failed", failed
    assert failed["files"] == []
    passed = native.invoke("stage", {"dataset": dataset, "rows": [{"id": 1, "value": 3}]})
    assert passed["status"] == "passed", passed
    report = read_json(passed["nativeReport"]["path"]).value
    for member in passed["files"]:
        assert member["loadId"] in passed["loadIds"]
        assert any(j["remote_url"] == Path(member["path"]).as_uri() and j["state"] == "completed" for j in report["job_metrics"])
        assert member["systemColumns"] == ["_dlt_load_id", "_dlt_id"]
    assert passed["quarantine"] == "not_requested"


def test_process_tree_timeout_and_capture_limits(tmp_path):
    started = monotonic()
    code = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']);time.sleep(20)"
    result = run_bounded([sys.executable, "-c", code], timeout=0.2, limit=1024)
    assert result["timedOut"] and monotonic() - started < 3
    result = run_bounded([sys.executable, "-c", "import sys;sys.stderr.write('x'*5000);print('{}')"], timeout=2, limit=100)
    assert result["stderrTruncated"] and len(result["stderr"]) == 100


def test_dlt_empty_schema_and_discard_counts(native):
    dataset = document()["schema"][0]
    empty = native.invoke("stage", {"dataset": dataset, "rows": []})
    assert empty["status"] == "passed", empty
    assert empty["inputRows"] == empty["normalizedRows"] == empty["discardedRows"]["count"] == 0
    assert sum(member["rows"] for member in empty["files"]) == 0
    fields = {field["name"]: field for field in empty["files"][0]["schema"]["fields"]}
    assert fields["id"]["data_type"] == "Int64" and fields["id"]["nullable"] is False
    for rows, expected in (([{"id": 1, "value": 3}, {"id": 2, "value": 4, "extra": True}], 1),
                           ([{"id": 2, "value": 4, "extra": True}], 0)):
        result = native.invoke("stage", {"dataset": dataset, "rows": rows,
                                           "schemaPolicy": {"tables": "freeze", "columns": "discard_row", "data_type": "freeze"}})
        assert result["status"] == "passed", result
        assert result["inputRows"] == len(rows) and result["normalizedRows"] == expected
        assert result["discardedRows"]["count"] == 1 and result["discardedRows"]["status"] == "observed"
        assert sum(member["rows"] for member in result["files"]) == expected
        assert result["nativeNormalizeReport"] and result["quarantine"] == "not_requested"


@pytest.mark.parametrize("table,field", (("UpperCase", "id"), ("records", "MixedCase"), ("records", "a__b")))
def test_dlt_normalization_cannot_be_mistaken_for_discarded_data(native, table, field):
    result = native.invoke("stage", {"dataset": {"name": table, "properties": [
        {"name": field, "logicalType": "integer", "required": True}]}, "rows": [{field: 1}]})
    assert result["status"] == "unknown", result
    assert "normalization" in result["reason"]
    assert "discardedRows" not in result and "files" not in result


def test_frictionless_check_start_errors_never_claim_complete_coverage(native, tmp_path):
    dataset = {"name": "records", "properties": [{"name": "id", "logicalType": "integer"},
                                                  {"name": "label", "logicalType": "string"}]}
    path = tmp_path / "records.csv"
    path.write_text("id,label\n1,a\n2,b\n")
    checks = [{"type": "deviated-value", "fieldName": "label", "average": "invalid"},
              {"type": "required-value", "fieldName": "absent"}]
    result = native.invoke("files", {"dataset": dataset, "checks": checks, "files": [{"path": str(path)}]})
    assert result["status"] in ("failed", "unknown"), result
    assert result["checkCoverage"] == "incomplete" and result["requestedChecks"] == checks
    assert result["nativeReport"]


def test_frictionless_primary_key_null_semantics_and_unsupported_precision(native, tmp_path):
    dataset = {"name": "records", "properties": [{"name": "id", "logicalType": "integer"},
                                                  {"name": "day", "logicalType": "date"}],
               "customProperties": [{"vendor": "ddk", "property": "rowIdentity", "value": ["id", "day"]}]}
    path = tmp_path / "null-key.csv"
    path.write_text("id,day\n,\n")
    result = native.invoke("files", {"dataset": dataset, "files": [{"path": str(path)}]})
    assert result["status"] == "failed", result
    dataset = {"name": "precise", "properties": [{"name": "amount", "logicalType": "number",
                                                   "logicalTypeOptions": {"precision": 18, "scale": 4}}]}
    path.write_text("amount\n1.25\n")
    result = native.invoke("files", {"dataset": dataset, "files": [{"path": str(path)}]})
    assert result["status"] == "unknown", result
    assert {c["facet"] for c in result["mappingCoverage"] if c["status"] == "unsupported"} == {"precision", "scale"}
    builder = ReportBuilder("urn:test:unsupported-precision", required_groups=("files.structure",))
    _record(builder, "files.structure", "precise", result, requirement="DDK-ADAPTER-002")
    reduced = builder.build()
    assert reduced["decision"] == "incomplete" and exit_code(reduced) == 2
    assert reduced["checks"][-1]["diagnostics"][0]["code"] == "ADAPTER-MAPPING-INCOMPLETE"


def test_quality_resources_default_scratch_budget_is_256_mib():
    from ddk.quality import QualityResources

    assert QualityResources().scratchBytes == 256 << 20


def test_batched_odcs_lint_evaluates_multiple_contracts_in_single_worker_invocation(native, tmp_path):
    from ddk.cli import main as cli_main

    valid_doc = document()
    bad_doc = deepcopy(valid_doc)
    bad_doc["id"] = "urn:test:quality-bad"
    bad_doc.pop("version")
    batch = native.invoke("odcs-lint", {"documents": [
        {"alias": "good", "document": valid_doc},
        {"alias": "bad", "document": bad_doc},
    ]})
    assert batch["status"] == "failed"
    assert batch["results"]["good"]["status"] == "passed"
    assert batch["results"]["bad"]["status"] in {"failed", "error"}
    assert batch["evaluator"]["id"] == "urn:ddk:quality:datacontract-cli"

    # End-to-end ddk check --require odcs.lint batches all project dataset contracts in one worker call
    commerce = tmp_path / "commerce"
    import shutil
    shutil.copytree(ROOT / "examples/commerce", commerce)
    report_path = tmp_path / "lint-report.ddk.json"
    rc = cli_main([
        "check", str(commerce / "project.ddk.json"),
        "--require", "odcs.lint",
        "--tool-python", str(native.python),
        "--output", str(report_path),
    ])
    assert rc == 0
    rep = json.loads(report_path.read_text())
    lint_checks = [c for c in rep["checks"] if c["group"] == "odcs.lint"]
    assert len(lint_checks) == 3 and all(c["status"] == "passed" for c in lint_checks)
    assert len({c["subject"] for c in lint_checks}) == 3

