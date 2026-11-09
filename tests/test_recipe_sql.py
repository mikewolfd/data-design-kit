"""Independent expectations for offline recipe SQL binding (catalog.recipes)."""

import json
import os
from pathlib import Path
import shutil

import pytest

from ddk.adapters.native import NativeTools
from ddk.catalog import assemble_catalog

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
SUMMARY = {"properties": [{"name": "station_code", "logicalType": "string"}, {"name": "readings", "logicalType": "number"}]}
PARAMETERS = {"type": "object", "properties": {"code": {"type": "string"}, "minimum": {"type": "integer"}}}

# Expected outcomes come from the declarations above, not from the binder.
CASES = {
    "join-and-parameters": ("SELECT s.station_code, count(r.value) AS readings FROM stations AS s "
                            "JOIN readings AS r ON r.station_code = s.station_code "
                            "WHERE s.station_code = ? AND s.elevation_m > ? GROUP BY s.station_code",
                            {"parameterOrder": ["code", "minimum"], "result": SUMMARY}, "passed", None),
    "nested-object-and-array": ("SELECT s.site.latitude AS latitude, e.kind FROM stations AS s, UNNEST(s.sensors) AS e",
                                {}, "passed", None),
    "numbered-and-named-parameters": ("SELECT station_code FROM stations WHERE station_code = $1 OR station_code = :code",
                                      {"parameterOrder": ["code"]}, "passed", None),
    "string-literal-date": ("SELECT station_code FROM stations WHERE opened_on >= '2020-01-01'", {}, "passed", None),
    "table-outside-inputs": ("SELECT station_code FROM calibrations", {}, "failed", "CATALOG-RECIPE-TABLE"),
    "schema-qualified-table": ("SELECT station_code FROM private.stations", {}, "failed", "CATALOG-RECIPE-TABLE"),
    "undeclared-column": ("SELECT altitude FROM stations", {}, "failed", "CATALOG-RECIPE-COLUMN"),
    "undeclared-object-field": ("SELECT s.site.longitude FROM stations AS s", {}, "failed", "CATALOG-RECIPE-COLUMN"),
    "undeclared-element-field": ("SELECT e.model FROM stations AS s, UNNEST(s.sensors) AS e", {}, "failed",
                                 "CATALOG-RECIPE-COLUMN"),
    "number-compared-with-string": ("SELECT station_code FROM stations WHERE elevation_m = station_code", {}, "failed",
                                    "CATALOG-RECIPE-TYPE"),
    "parameter-type-conflict": ("SELECT station_code FROM stations WHERE elevation_m = ?", {"parameterOrder": ["code"]},
                                "failed", "CATALOG-RECIPE-TYPE"),
    "parameter-count": ("SELECT station_code FROM stations WHERE station_code = ? AND raw = ?",
                        {"parameterOrder": ["code"]}, "failed", "CATALOG-RECIPE-PARAMETERS"),
    "result-missing-column": ("SELECT station_code FROM stations", {"result": SUMMARY}, "failed", "CATALOG-RECIPE-RESULT"),
    "result-wrong-type": ("SELECT station_code, station_code AS readings FROM stations", {"result": SUMMARY}, "failed",
                          "CATALOG-RECIPE-RESULT"),
    "two-statements": ("SELECT 1; SELECT 2", {}, "failed", "CATALOG-RECIPE-SQL-SHAPE"),
    "engine-function": ("SELECT array_element(sensors, 1) AS first FROM stations", {}, "unknown",
                        "CATALOG-RECIPE-SQL-UNSUPPORTED"),
    "json-extraction": ("SELECT raw ->> 'battery' AS battery FROM stations", {}, "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED"),
    "unknown-dialect": ("SELECT station_code FROM stations", {"dialect": "kusto"}, "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED"),
    # Positional parameters follow the SQL text, not the parse tree.
    "parameters-in-text-order": ("WITH high AS (SELECT station_code FROM stations WHERE elevation_m > ?) "
                                 "SELECT station_code FROM high WHERE station_code = ?",
                                 {"parameterOrder": ["minimum", "code"]}, "passed", None),
    "parameters-in-tree-order": ("WITH high AS (SELECT station_code FROM stations WHERE elevation_m > ?) "
                                 "SELECT station_code FROM high WHERE station_code = ?",
                                 {"parameterOrder": ["code", "minimum"]}, "failed", "CATALOG-RECIPE-TYPE"),
    "limit-parameter": ("SELECT station_code FROM stations WHERE station_code = ? LIMIT ?",
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
    "date-literal-not-a-date": ("SELECT station_code FROM stations WHERE opened_on = 'last tuesday'", {}, "failed",
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
}


@pytest.fixture
def tools(tmp_path):
    python = os.environ.get("DDK_NATIVE_PYTHON")
    if not python:
        pytest.skip("Select the pinned native Python tool environment, which provides sqlglot")
    return NativeTools(python, output=tmp_path / "native")


def _copy(tmp_path, source):
    target = tmp_path / source.name
    shutil.copytree(source, target)
    return target


def _recipe_checks(report):
    return {item["subject"]: item for item in report["checks"] if item["group"] == "catalog.recipes"}


def test_binder_cases_follow_their_declarations(tools):
    response = tools.invoke("recipe-sql", {"recipes": [
        {"id": name, "sql": sql, "dialect": "datafusion", "inputs": {"stations": STATIONS, "readings": READINGS},
         "parameters": PARAMETERS, **extra} for name, (sql, extra, _, _) in CASES.items()]})
    assert response["status"] == "completed" and response["parser"]["id"] == "sqlglot"
    for name, (_, _, status, code) in CASES.items():
        result = response["results"][name]
        assert result["status"] == status, (name, result)
        assert (code is None) == (not result["diagnostics"]), (name, result)
        assert code is None or code in {item["code"] for item in result["diagnostics"]}, (name, result)
    assert response["results"]["join-and-parameters"]["output"] == [
        {"name": "station_code", "logicalType": "string"}, {"name": "readings", "logicalType": "integer"}]


@pytest.mark.parametrize("example", [LAYERED, COMMERCE])
def test_example_recipes_bind_to_their_declared_inputs_and_results(tmp_path, tools, example):
    result = assemble_catalog(_copy(tmp_path, example) / "project.ddk.json", required_groups=("catalog.recipes",),
                              recipe_tools=tools)
    assert result.report["decision"] == "passed", result.report
    checks = _recipe_checks(result.report)
    assert checks and all(item["status"] == "passed" and item["evidence"] == "inferred" for item in checks.values())
    bindings = result.report["metadata"]["recipeBindings"]
    assert set(bindings) == set(checks)
    assert {"id": "sqlglot", "version": bindings[next(iter(bindings))]["parser"]["version"]} in result.catalog["adapters"]


def test_view_dataset_must_match_its_recipe_output(tmp_path, tools):
    layered = _copy(tmp_path, LAYERED)
    summary = layered / "product" / "summary.odcs.json"
    contract = json.loads(summary.read_bytes())
    contract["schema"][0]["physicalType"] = "view"
    contract["schema"][0]["properties"][1]["logicalType"] = "string"
    contract["schema"][0]["properties"].append({"name": "site_name", "logicalType": "string"})
    summary.write_text(json.dumps(contract))
    result = assemble_catalog(layered / "project.ddk.json", required_groups=("catalog.recipes",), recipe_tools=tools)
    assert result.report["decision"] == "failed"
    check, = _recipe_checks(result.report).values()
    assert [item["code"] for item in check["diagnostics"]] == ["CATALOG-RECIPE-RESULT"] * 2
    assert {item["location"]["path"] for item in check["diagnostics"]} == {"product/readings-per-station.sql"}


def test_requested_binding_without_a_tool_environment_is_not_run(tmp_path):
    result = assemble_catalog(_copy(tmp_path, LAYERED) / "project.ddk.json", required_groups=("catalog.recipes",))
    assert result.report["decision"] == "incomplete"
    check, = _recipe_checks(result.report).values()
    assert check["status"] == "not_run" and check["diagnostics"][0]["code"] == "ADAPTER-CAPABILITY-MISSING"
    assert "catalog.recipes" in result.report["coverage"]["missingCapabilities"]


def test_binding_runs_only_when_requested(tmp_path):
    result = assemble_catalog(_copy(tmp_path, LAYERED) / "project.ddk.json")
    assert result.report["decision"] == "passed" and not _recipe_checks(result.report)
