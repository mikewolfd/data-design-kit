"""Unit and live DocSpec execution tests for ODCS -> DocSpec zero-counter SQL lowering (Decision 3A / S3a)."""

import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.docspec_recipe_gate import DEFAULT_DOCSPEC_GATE_LIMITS
from ddk.odcs_sql_counters import compile_odcs_quality_counters


SCHEMA_OBJECT = {
    "name": "daily_revenue",
    "logicalType": "object",
    "customProperties": [
        {"vendor": "ddk", "property": "rowIdentity", "value": ["order_day", "region"]},
    ],
    "properties": [
        {"name": "order_day", "logicalType": "date", "required": True},
        {
            "name": "region",
            "logicalType": "string",
            "required": True,
            "enum": ["NA", "EU", "APAC"],
        },
        {
            "name": "amount_cents",
            "logicalType": "integer",
            "required": True,
            "logicalTypeOptions": {"minimum": 0, "maximum": 1_000_000},
            "quality": [
                {
                    "id": "even-cents",
                    "type": "sql",
                    "query": "SELECT COUNT(*) FROM ${object} WHERE (${property} % 2) <> 0",
                    "mustBe": 0,
                }
            ],
        },
        {
            "name": "margin_ratio",
            "logicalType": "number",
            "logicalTypeOptions": {"exclusiveMinimum": 0.0, "exclusiveMaximum": 1.0},
        },
        {
            "name": "batch_code",
            "logicalType": "string",
            "unique": True,
        },
    ],
    "quality": [
        {
            "id": "no-huge-na",
            "type": "sql",
            "query": "SELECT COUNT(*) FROM ${object} WHERE \"region\" = 'NA' AND \"amount_cents\" > 500000",
            "mustBe": 0,
        },
        {
            "id": "external-rule",
            "type": "custom",
            "engine": "external",
            "implementation": "check external",
        },
    ],
}


@pytest.fixture
def docspec_bin():
    binary = os.environ.get("DDK_DOCSPEC_BIN") or os.environ.get("DDK_DOCSPEC_BINARY")
    if not binary:
        pytest.skip("Select the DocSpec runtime binary via DDK_DOCSPEC_BIN or DDK_DOCSPEC_BINARY")
    return binary


def test_compile_odcs_quality_counters_is_deterministic_and_tracks_unmapped():
    first = compile_odcs_quality_counters(SCHEMA_OBJECT, "daily_revenue", query_name="counters")
    second = compile_odcs_quality_counters(SCHEMA_OBJECT, "daily_revenue", query_name="counters")
    assert first == second
    rule_ids = [rule["id"] for rule in first["rules"]]
    assert "order_day:required" in rule_ids
    assert "region:required" in rule_ids
    assert "region:enum" in rule_ids
    assert "amount_cents:required" in rule_ids
    assert "amount_cents:minimum" in rule_ids
    assert "amount_cents:maximum" in rule_ids
    assert "margin_ratio:exclusiveMinimum" in rule_ids
    assert "margin_ratio:exclusiveMaximum" in rule_ids
    assert "batch_code:unique" in rule_ids
    assert "primary_key:unique" in rule_ids
    assert "even-cents" in rule_ids
    assert "no-huge-na" in rule_ids
    assert [item["id"] for item in first["unmapped"]] == ["external-rule"]

    # ODCS v3.2.0 RFC 0033 object-form enum items compile identically to scalar enum lists
    rfc_schema = {
        **SCHEMA_OBJECT,
        "properties": [
            (
                {**p, "enum": [{"value": "NA"}, {"value": "EU"}, {"value": "APAC"}]}
                if p["name"] == "region"
                else p
            )
            for p in SCHEMA_OBJECT["properties"]
        ],
    }
    assert compile_odcs_quality_counters(rfc_schema, "daily_revenue", query_name="counters") == first


def _write_table(path: Path, rows: list[dict]) -> None:
    arrow_schema = pa.schema([
        pa.field("order_day", pa.date32()),
        pa.field("region", pa.string()),
        pa.field("amount_cents", pa.int64()),
        pa.field("margin_ratio", pa.float64()),
        pa.field("batch_code", pa.string()),
    ])
    table = pa.Table.from_pylist(rows, schema=arrow_schema)
    pq.write_table(table, path)


def _run_compiled_queries(tmp_path: Path, docspec_bin: str, parquet_path: Path, compiled: dict) -> dict[str, dict]:
    adapter = DocSpecAdapter(docspec_bin, dict(DEFAULT_DOCSPEC_GATE_LIMITS), evidence_dir=tmp_path / "evidence")
    response = adapter.execute(
        {
            "scratch": str(tmp_path / "scratch"),
            "inputs": [{"kind": "parquet", "name": "daily_revenue", "path": str(parquet_path)}],
            "steps": [],
            "outputs": [],
            "queries": compiled["queries"],
        },
        input_digests={},
    )
    assert response["status"] == "succeeded", response
    return {item["name"]: item["data"][0] for item in response["result"]["queries"]}


def test_compiled_zero_counters_return_zero_on_empty_and_clean_tables_and_flag_planted_violations(
    tmp_path, docspec_bin
):
    from datetime import date

    compiled = compile_odcs_quality_counters(SCHEMA_OBJECT, "daily_revenue", query_name="counters")

    # 1. Empty 0-row table: every counter must evaluate to integer 0 (never NULL).
    empty_file = tmp_path / "empty.parquet"
    _write_table(empty_file, [])
    empty_rows = _run_compiled_queries(tmp_path / "run-empty", docspec_bin, empty_file, compiled)
    for rule in compiled["rules"]:
        q_row = empty_rows[rule["query"]]
        val = q_row[rule["column"]] if rule["column"] is not None else next(iter(q_row.values()))
        assert val == 0 and type(val) is int, (rule["id"], val)

    # 2. Clean multi-row table: every counter evaluates to 0.
    clean_file = tmp_path / "clean.parquet"
    _write_table(clean_file, [
        {"order_day": date(2026, 1, 1), "region": "NA", "amount_cents": 200, "margin_ratio": 0.25, "batch_code": "B1"},
        {"order_day": date(2026, 1, 1), "region": "EU", "amount_cents": 400, "margin_ratio": 0.50, "batch_code": "B2"},
    ])
    clean_rows = _run_compiled_queries(tmp_path / "run-clean", docspec_bin, clean_file, compiled)
    for rule in compiled["rules"]:
        q_row = clean_rows[rule["query"]]
        val = q_row[rule["column"]] if rule["column"] is not None else next(iter(q_row.values()))
        assert val == 0, (rule["id"], val)

    # 3. Faulty table with planted violations across all rule classes.
    bad_file = tmp_path / "bad.parquet"
    _write_table(bad_file, [
        # Duplicate (2026-01-01, NA), duplicate batch_code B1, odd amount_cents, huge NA > 500000, margin_ratio == 1.0
        {"order_day": date(2026, 1, 1), "region": "NA", "amount_cents": 600_001, "margin_ratio": 1.0, "batch_code": "B1"},
        # Duplicate (2026-01-01, NA), duplicate batch_code B1, negative amount_cents, margin_ratio == 0.0
        {"order_day": date(2026, 1, 1), "region": "NA", "amount_cents": -4, "margin_ratio": 0.0, "batch_code": "B1"},
        # Invalid enum LATAM, above maximum 2_000_000, null order_day
        {"order_day": None, "region": "LATAM", "amount_cents": 2_000_000, "margin_ratio": 0.5, "batch_code": "B3"},
    ])
    bad_rows = _run_compiled_queries(tmp_path / "run-bad", docspec_bin, bad_file, compiled)
    observed = {
        rule["id"]: (
            bad_rows[rule["query"]][rule["column"]]
            if rule["column"] is not None
            else next(iter(bad_rows[rule["query"]].values()))
        )
        for rule in compiled["rules"]
    }
    assert observed["order_day:required"] == 1
    assert observed["region:enum"] == 1
    assert observed["amount_cents:minimum"] == 1
    assert observed["amount_cents:maximum"] == 1
    assert observed["margin_ratio:exclusiveMinimum"] == 1
    assert observed["margin_ratio:exclusiveMaximum"] == 1
    assert observed["batch_code:unique"] == 1
    assert observed["primary_key:unique"] == 1
    assert observed["even-cents"] == 1
    assert observed["no-huge-na"] == 1
