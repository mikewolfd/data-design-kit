"""Independent expectations for the single-engine DocSpec recipe SQL gate (catalog.recipes)."""

import json
import os
from pathlib import Path
import shutil

import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.catalog import assemble_catalog
from ddk.cli import main as cli_main
from ddk.documents import read_json
from ddk.docspec_recipe_gate import DEFAULT_DOCSPEC_GATE_LIMITS, evaluate_job_spec, evaluate_recipe_specs

ROOT = Path(__file__).resolve().parents[1]
LAYERED = ROOT / "examples" / "layered"
COMMERCE = ROOT / "examples" / "commerce"
STATIONS = {"properties": [
    {"name": "station_code", "logicalType": "string"}, {"name": "elevation_m", "logicalType": "integer"},
    {"name": "site", "logicalType": "object", "properties": [{"name": "latitude", "logicalType": "number"}]},
    {"name": "sensors", "logicalType": "array", "items": {"logicalType": "object", "properties": [
        {"name": "kind", "logicalType": "string"}]}},
    {"name": "opened_on", "logicalType": "date"}, {"name": "raw", "logicalType": "string"},
]}
READINGS = {"properties": [{"name": "station_code", "logicalType": "string"}, {"name": "value", "logicalType": "number"}]}
SUMMARY = {"properties": [{"name": "station_code", "logicalType": "string"}, {"name": "readings", "logicalType": "integer"}]}
PARAMETERS = {"type": "object", "properties": {"code": {"type": "string"}, "minimum": {"type": "integer"}},
              "additionalProperties": False}

# Expected outcomes come from the declarations above and DocSpec's DataFusion 53.1 + dr-kg49 rules.
CASES = {
    "join-and-parameters": ("SELECT s.station_code, count(r.value) AS readings FROM stations AS s "
                            "JOIN readings AS r ON r.station_code = s.station_code "
                            "WHERE s.station_code = $1 AND s.elevation_m > $2 GROUP BY s.station_code",
                            {"parameterOrder": ["code", "minimum"], "result": SUMMARY}, "passed", None),
    "nested-object-and-array": ("WITH u AS (SELECT s.site.latitude AS latitude, unnest(s.sensors) AS sensor "
                                "FROM stations AS s) SELECT latitude, sensor.kind FROM u",
                                {}, "passed", None),
    "named-parameters": ("SELECT station_code FROM stations WHERE station_code = $code AND elevation_m > $minimum",
                         {}, "passed", None),
    "question-parameter-refused": ("SELECT station_code FROM stations WHERE station_code = ?",
                                   {"parameterOrder": ["code"]}, "failed", "CATALOG-RECIPE-PARAMETERS"),
    "colon-parameter-refused": ("SELECT station_code FROM stations WHERE station_code = :code",
                                {}, "failed", "CATALOG-RECIPE-PARAMETERS"),
    "typed-date-literal": ("SELECT station_code FROM stations WHERE opened_on >= DATE '2020-01-01'",
                           {}, "passed", None),
    "bare-string-date-refused": ("SELECT station_code FROM stations WHERE opened_on >= '2020-01-01'",
                                 {}, "failed", "CATALOG-RECIPE-TYPE"),
    "table-outside-inputs": ("SELECT station_code FROM calibrations", {}, "failed", "CATALOG-RECIPE-TABLE"),
    "schema-qualified-table": ("SELECT station_code FROM private.stations", {}, "failed", "CATALOG-RECIPE-TABLE"),
    "undeclared-column": ("SELECT altitude FROM stations", {}, "failed", "CATALOG-RECIPE-COLUMN"),
    "undeclared-object-field": ("SELECT s.site.longitude FROM stations AS s", {}, "failed", "CATALOG-RECIPE-COLUMN"),
    "undeclared-element-field": ("WITH u AS (SELECT unnest(s.sensors) AS sensor FROM stations AS s) "
                                 "SELECT sensor.model FROM u", {}, "failed",
                                 "CATALOG-RECIPE-COLUMN"),
    "number-compared-with-string": ("SELECT station_code FROM stations WHERE elevation_m = station_code", {}, "failed",
                                    "CATALOG-RECIPE-TYPE"),
    "parameter-type-conflict": ("SELECT station_code FROM stations WHERE elevation_m = $1", {"parameterOrder": ["code"]},
                                "failed", "CATALOG-RECIPE-TYPE"),
    "parameter-count": ("SELECT station_code FROM stations WHERE station_code = $1 AND raw = $2",
                        {"parameterOrder": ["code"]}, "failed", "CATALOG-RECIPE-PARAMETERS"),
    "result-missing-column": ("SELECT station_code FROM stations", {"result": SUMMARY}, "failed", "CATALOG-RECIPE-RESULT"),
    "result-wrong-type": ("SELECT station_code, station_code AS readings FROM stations", {"result": SUMMARY}, "failed",
                          "CATALOG-RECIPE-RESULT"),
    "two-statements": ("SELECT 1; SELECT 2", {}, "failed", "CATALOG-RECIPE-SQL-SHAPE"),
    "unknown-udf": ("SELECT custom_udf(sensors, 1) AS first FROM stations", {}, "unknown",
                    "CATALOG-RECIPE-SQL-UNSUPPORTED"),
    "json-extraction": ("SELECT raw ->> 'battery' AS battery FROM stations", {}, "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED"),
    "unknown-dialect": ("SELECT station_code FROM stations", {"dialect": "kusto"}, "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED"),
    # Positional $1..$n follow declared parameterOrder indices.
    "parameters-in-text-order": ("WITH high AS (SELECT station_code FROM stations WHERE elevation_m > $1) "
                                 "SELECT station_code FROM high WHERE station_code = $2",
                                 {"parameterOrder": ["minimum", "code"]}, "passed", None),
    "parameters-in-tree-order": ("WITH high AS (SELECT station_code FROM stations WHERE elevation_m > $1) "
                                 "SELECT station_code FROM high WHERE station_code = $2",
                                 {"parameterOrder": ["code", "minimum"]}, "failed", "CATALOG-RECIPE-TYPE"),
    "limit-parameter": ("SELECT station_code FROM stations WHERE station_code = $1 LIMIT $2",
                        {"parameterOrder": ["code", "minimum"]}, "passed", None),
    "recursive-cte": ("WITH RECURSIVE n AS (SELECT 1 AS k UNION ALL SELECT k + 1 FROM n WHERE k < 3) SELECT k FROM n",
                      {}, "passed", None),
    "cte-reads-itself": ("WITH again AS (SELECT * FROM again) SELECT * FROM again", {}, "failed", "CATALOG-RECIPE-TABLE"),
    "in-list-type": ("SELECT station_code FROM stations WHERE elevation_m IN ('high', 'low')", {}, "failed",
                     "CATALOG-RECIPE-TYPE"),
    "in-subquery-type": ("SELECT station_code FROM stations WHERE elevation_m IN (SELECT station_code FROM readings)", {},
                         "failed", "CATALOG-RECIPE-TYPE"),
    "between-type": ("SELECT station_code FROM stations WHERE station_code BETWEEN 1 AND 5", {}, "failed", "CATALOG-RECIPE-TYPE"),
    "like-on-number": ("SELECT station_code FROM stations WHERE elevation_m LIKE '1%'", {}, "failed", "CATALOG-RECIPE-TYPE"),
    "distinct-from-type": ("SELECT station_code FROM stations WHERE elevation_m IS DISTINCT FROM 'x'", {}, "failed",
                           "CATALOG-RECIPE-TYPE"),
    "date-literal-not-a-date": ("SELECT station_code FROM stations WHERE opened_on = CAST('last tuesday' AS DATE)", {}, "failed",
                                "CATALOG-RECIPE-TYPE"),
    "union-mixed-types": ("SELECT elevation_m AS v FROM stations UNION ALL SELECT station_code AS v FROM stations", {},
                          "failed", "CATALOG-RECIPE-TYPE"),
    "case-mixed-types": ("SELECT CASE WHEN elevation_m > 0 THEN station_code ELSE 0 END AS v FROM stations", {}, "failed",
                         "CATALOG-RECIPE-TYPE"),
    "arithmetic-on-string": ("SELECT station_code + 1 AS v FROM stations", {}, "failed", "CATALOG-RECIPE-TYPE"),
    "field-of-string": ("SELECT (raw).battery AS b FROM stations", {}, "failed", "CATALOG-RECIPE-COLUMN"),
    "index-of-string": ("SELECT raw[1] AS b FROM stations", {}, "failed", "CATALOG-RECIPE-COLUMN"),
    "using-missing-column": ("SELECT s.station_code FROM stations AS s JOIN readings AS r USING (missing)", {}, "failed",
                             "CATALOG-RECIPE-COLUMN"),
    "missing-ordinal": ("SELECT station_code FROM stations ORDER BY 3", {}, "failed", "CATALOG-RECIPE-COLUMN"),
    "nested-result-match": ("SELECT site FROM stations", {"result": {"properties": [
        {"name": "site", "logicalType": "object", "properties": [{"name": "latitude", "logicalType": "number"}]}]}},
        "passed", None),
    "nested-result-shape": ("SELECT site FROM stations", {"result": {"properties": [
        {"name": "site", "logicalType": "object", "properties": [{"name": "latitude", "logicalType": "string"},
                                                                 {"name": "longitude", "logicalType": "number"}]}]}},
        "failed", "CATALOG-RECIPE-RESULT"),
    # DataFusion 53.1 + datafusion-functions-json built-in execution through DocSpec.
    "datafusion-regexp-and-json": ("SELECT (regexp_match(raw, 'v=([0-9]+)'))[1] AS station_code, "
                                   "json_get_int(json_get(raw, 'counts'), 0) AS readings FROM stations "
                                   "WHERE regexp_like(raw, '^v') AND json_get_str(raw, 'kind') = 'wind'",
                                   {"result": SUMMARY}, "passed", None),
    "datafusion-arrays-and-dates": ("SELECT unnest(make_array(station_code, raw)) AS code, "
                                    "to_date(raw, '%Y-%m-%d') AS day, array_element(sensors, 1) AS first_sensor "
                                    "FROM stations WHERE array_length(sensors) > 0", {}, "passed", None),
    "regexp-on-number": ("SELECT station_code FROM stations WHERE regexp_like(elevation_m, '^1')", {}, "failed",
                         "CATALOG-RECIPE-TYPE"),
    "json-path-not-key-or-index": ("SELECT json_get_str(raw, 1.5) AS kind FROM stations", {}, "failed",
                                   "CATALOG-RECIPE-TYPE"),
    "json-document-not-text": ("SELECT json_get_str(site, 'latitude') AS kind FROM stations", {}, "failed",
                               "CATALOG-RECIPE-TYPE"),
    "array-has-on-string": ("SELECT station_code FROM stations WHERE array_has(raw, 'x')", {}, "failed",
                            "CATALOG-RECIPE-TYPE"),
    "array-has-element-type": ("SELECT station_code FROM stations WHERE array_has(make_array(station_code), 1)", {},
                               "failed", "CATALOG-RECIPE-TYPE"),
    "make-array-mixed-types": ("SELECT make_array(station_code, elevation_m) AS v FROM stations", {}, "failed",
                               "CATALOG-RECIPE-TYPE"),
    "unnest-a-string": ("SELECT unnest(raw) AS v FROM stations", {}, "failed", "CATALOG-RECIPE-TYPE"),
    "regexp-match-arity": ("SELECT regexp_match(raw) AS v FROM stations", {}, "failed", "CATALOG-RECIPE-TYPE"),
    "repeated-output-name": ("SELECT station_code, raw FROM stations UNION ALL SELECT raw, raw FROM stations", {}, "failed",
                             "CATALOG-RECIPE-SQL-SHAPE"),
    "repeated-output-alias": ("SELECT station_code AS v, raw AS v FROM stations", {}, "failed", "CATALOG-RECIPE-SQL-SHAPE"),
    "postgres-has-no-datafusion-signatures": ("SELECT json_get_str(raw, 'kind') AS kind FROM stations",
                                              {"dialect": "postgres"}, "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED"),
}


@pytest.fixture
def docspec_bin():
    binary = os.environ.get("DDK_DOCSPEC_BIN") or os.environ.get("DDK_DOCSPEC_BINARY")
    if not binary:
        pytest.skip("Select the DocSpec runtime binary via DDK_DOCSPEC_BIN or DDK_DOCSPEC_BINARY")
    return binary


@pytest.fixture
def runtime(tmp_path, docspec_bin):
    return DocSpecAdapter(docspec_bin, dict(DEFAULT_DOCSPEC_GATE_LIMITS), evidence_dir=tmp_path / "docspec")


def _copy(tmp_path, source):
    target = tmp_path / source.name
    shutil.copytree(source, target)
    return target


def _recipe_checks(report):
    return {item["subject"]: item for item in report["checks"] if item["group"] == "catalog.recipes"}


def test_binder_cases_follow_their_declarations(runtime):
    response = evaluate_recipe_specs([
        {"id": name, "sql": sql, "dialect": extra.get("dialect", "datafusion"),
         "inputs": {"stations": STATIONS, "readings": READINGS},
         "parameters": PARAMETERS, **extra}
        for name, (sql, extra, _, _) in CASES.items()
    ], runtime)
    assert response["status"] == "completed" and response["parser"]["id"] == "docspec"
    assert response["parser"]["distributionSha256"] == runtime.tool["distributionSha256"]
    for name, (_, _, status, code) in CASES.items():
        result = response["results"][name]
        assert result["status"] == status, (name, result)
        assert (code is None) == (not result["diagnostics"]), (name, result)
        assert code is None or code in {item["code"] for item in result["diagnostics"]}, (name, result)
    assert response["results"]["join-and-parameters"]["output"] == [
        {"name": "station_code", "logicalType": "string"}, {"name": "readings", "logicalType": "integer"}]
    assert len(response["results"]["join-and-parameters"]["evidence"]) == 2


@pytest.mark.parametrize("example", [LAYERED, COMMERCE])
def test_example_recipes_bind_to_their_declared_inputs_and_results(tmp_path, docspec_bin, example):
    result = assemble_catalog(
        _copy(tmp_path, example) / "project.ddk.json",
        required_groups=("catalog.recipes",),
        docspec=docspec_bin,
        docspec_evidence_dir=tmp_path / "evidence",
    )
    assert result.report["decision"] == "passed", result.report
    checks = _recipe_checks(result.report)
    assert checks and all(item["status"] == "passed" and item["evidence"] == "executed" for item in checks.values())
    bindings = result.report["metadata"]["recipeBindings"]
    assert set(bindings) == set(checks)
    first_parser = bindings[next(iter(bindings))]["parser"]
    assert first_parser["id"] == "docspec" and first_parser["distributionSha256"]
    assert {
        "id": "docspec",
        "version": first_parser["version"],
        "distributionSha256": first_parser["distributionSha256"],
    } in result.catalog["adapters"]


def test_view_dataset_must_match_its_recipe_output(tmp_path, docspec_bin):
    layered = _copy(tmp_path, LAYERED)
    summary = layered / "product" / "summary.odcs.json"
    contract = json.loads(summary.read_bytes())
    contract["schema"][0]["physicalType"] = "view"
    contract["schema"][0]["properties"][1]["logicalType"] = "string"
    contract["schema"][0]["properties"].append({"name": "site_name", "logicalType": "string"})
    summary.write_text(json.dumps(contract))
    result = assemble_catalog(
        layered / "project.ddk.json",
        required_groups=("catalog.recipes",),
        docspec=docspec_bin,
        docspec_evidence_dir=tmp_path / "evidence",
    )
    assert result.report["decision"] == "failed"
    check, = _recipe_checks(result.report).values()
    assert [item["code"] for item in check["diagnostics"]] == ["CATALOG-RECIPE-RESULT"] * 2
    assert {item["location"]["path"] for item in check["diagnostics"]} == {"product/readings-per-station.sql"}


def test_zero_row_execution_catches_optimizer_faults_missed_by_prepare_job(tmp_path, runtime):
    """DataFusion 53.1 push_down_leaf_projections (dr-7uke) passes prepare-job on an unmaterialized
    JSON-extracting UNION ALL view, then fails at 0-row execution."""
    docs_schema = {"properties": [
        {"name": "id", "logicalType": "string"},
        {"name": "docket_id", "logicalType": "string"},
        {"name": "title", "logicalType": "string"},
        {"name": "attributes", "logicalType": "string"},
    ]}
    dockets_schema = {"properties": [
        {"name": "id", "logicalType": "string"},
        {"name": "attributes", "logicalType": "string"},
    ]}
    view_sql = (
        "WITH regs AS ("
        "  SELECT coalesce(json_get_str(k.attributes, 'rin'), d.docket_id) AS rulemaking_id,"
        "         d.id, d.title, json_get_str(d.attributes, 'frDocNum') AS fr_document_number,"
        "         CAST(substr(json_get_str(d.attributes, 'commentStartDate'), 1, 10) AS DATE) AS opens,"
        "         CAST(substr(json_get_str(d.attributes, 'commentEndDate'), 1, 10) AS DATE) AS closes"
        "  FROM regulations_documents AS d"
        "  LEFT JOIN regulations_dockets AS k ON k.id = d.docket_id"
        ") "
        "SELECT rulemaking_id, 'opens' AS event, opens AS event_date, title, fr_document_number "
        "FROM regs WHERE opens IS NOT NULL "
        "UNION ALL "
        "SELECT rulemaking_id, 'closes' AS event, closes AS event_date, title, fr_document_number "
        "FROM regs WHERE closes IS NOT NULL"
    )
    job_doc = tmp_path / "dr-7uke.job.json"
    spec = {
        "id": "urn:test:job:dr-7uke",
        "scratch": "scratch",
        "inputs": [
            {"kind": "parquet", "name": "regulations_documents", "path": "docs.parquet"},
            {"kind": "parquet", "name": "regulations_dockets", "path": "dockets.parquet"},
        ],
        "steps": [
            {"name": "rulemaking_timeline", "sql": view_sql, "materialize": False},
        ],
        "outputs": [],
        "queries": [
            {"name": "history",
             "sql": "SELECT event_date, event, title, fr_document_number "
                    "FROM rulemaking_timeline WHERE rulemaking_id = 'RIN-1'"},
        ],
    }
    job_doc.write_text(json.dumps(spec))
    result = evaluate_job_spec(
        "urn:test:job:dr-7uke",
        read_json(job_doc),
        {"regulations_documents": docs_schema, "regulations_dockets": dockets_schema},
        {},
        runtime,
    )
    # Both phases ran either way: prepare-job accepted the view, then the 0-row job executed it.
    assert len(result["evidence"]) == 2, result
    prepared, executed = [read_json(item["path"]).value for item in result["evidence"]]
    assert prepared["status"] == "succeeded"
    assert prepared["result"]["execution"] == "not_run"
    if result["status"] == "passed":
        # A repaired engine must execute the query and retain its independently expected empty result.
        assert result["diagnostics"] == []
        assert executed["status"] == executed["operation"]["execution"] == "succeeded"
        assert executed["result"]["queries"] == [{
            "name": "history", "columns": ["event_date", "event", "title", "fr_document_number"], "data": [],
        }]
    else:
        assert result["status"] == "failed", result
        assert executed["status"] == "failed"
        assert any("__datafusion_extracted" in d["message"] or "push_down_leaf_projections" in d["message"]
                   for d in result["diagnostics"]), result["diagnostics"]


def test_zero_row_execution_failure_cannot_pass_from_preparation_alone(tmp_path):
    """Simulate an execution-only fault even when the selected native engine has been repaired."""
    calls = []

    class FailingExecution:
        evidence_dir = tmp_path

        def prepare_job(self, request):
            calls.append("prepare")
            return {"status": "succeeded", "result": {"outputs": []}}

        def execute(self, job, *, spec_path):
            calls.append("execute")
            return {"status": "failed", "error": {
                "code": "sql", "message": "Optimizer rule 'push_down_leaf_projections' failed in execution",
            }}

    spec_path = tmp_path / "job.json"
    spec_path.write_text(json.dumps({"inputs": [], "steps": [], "outputs": [],
                                     "queries": [{"name": "probe", "sql": "SELECT 1"}]}))
    result = evaluate_job_spec("urn:test:execution-fault", read_json(spec_path), {}, {}, FailingExecution())
    assert calls == ["prepare", "execute"]
    assert result["status"] == "failed"
    assert [item["code"] for item in result["diagnostics"]] == ["CATALOG-RECIPE-SQL-SHAPE"]


def test_cli_catalog_docspec_binds_recipes_and_records_adapter(tmp_path, docspec_bin, capsys):
    layered = _copy(tmp_path, LAYERED)
    out_dir = tmp_path / "out"
    rc = cli_main([
        "catalog", str(layered / "project.ddk.json"),
        "--format", "json",
        "--require", "catalog.recipes",
        "--docspec", docspec_bin,
        "--output", str(out_dir),
    ])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    catalog = json.loads((out_dir / "catalog.ddk.json").read_text())
    assert report["decision"] == "passed"
    assert any(item["id"] == "docspec" for item in catalog["adapters"])


def test_requested_binding_without_a_tool_environment_is_not_run(tmp_path):
    result = assemble_catalog(_copy(tmp_path, LAYERED) / "project.ddk.json", required_groups=("catalog.recipes",))
    assert result.report["decision"] == "incomplete"
    check, = _recipe_checks(result.report).values()
    assert check["status"] == "not_run" and check["diagnostics"][0]["code"] == "ADAPTER-CAPABILITY-MISSING"
    assert "catalog.recipes" in result.report["coverage"]["missingCapabilities"]


def test_binding_runs_only_when_requested(tmp_path):
    result = assemble_catalog(_copy(tmp_path, LAYERED) / "project.ddk.json")
    assert result.report["decision"] == "passed" and not _recipe_checks(result.report)
