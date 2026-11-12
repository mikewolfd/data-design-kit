"""Unit and live DocSpec execution tests for ODCS -> DocSpec zero-counter & join-metrics SQL lowering."""

import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.docspec_recipe_gate import DEFAULT_DOCSPEC_GATE_LIMITS
from ddk.odcs_sql_counters import (
    compile_odcs_quality_counters,
    compile_relationship_join_metrics_queries,
)


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
            "logicalTypeOptions": {"minLength": 2, "maxLength": 4},
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
            "logicalTypeOptions": {"pattern": "^B[0-9]+$"},
        },
        {
            "name": "invoice_code",
            "logicalType": "string",
            "unique": True,
        },
        {
            "name": "tags",
            "logicalType": "array",
            "items": {"logicalType": "string"},
            "logicalTypeOptions": {"minItems": 1, "maxItems": 3, "uniqueItems": True},
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
            "id": "max-ten-rows",
            "metric": "rowCount",
            "mustBeLessOrEqualTo": 10,
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


def test_compile_odcs_quality_counters_is_deterministic_memory_bounded_and_tracks_unmapped():
    first = compile_odcs_quality_counters(SCHEMA_OBJECT, "daily_revenue", query_name="counters")
    second = compile_odcs_quality_counters(SCHEMA_OBJECT, "daily_revenue", query_name="counters")
    assert first == second
    rule_ids = [rule["id"] for rule in first["rules"]]
    assert "order_day:required" in rule_ids
    assert "region:required" in rule_ids
    assert "region:enum" in rule_ids
    assert "region:minLength" in rule_ids
    assert "region:maxLength" in rule_ids
    assert "amount_cents:required" in rule_ids
    assert "amount_cents:minimum" in rule_ids
    assert "amount_cents:maximum" in rule_ids
    assert "margin_ratio:exclusiveMinimum" in rule_ids
    assert "margin_ratio:exclusiveMaximum" in rule_ids
    assert "batch_code:unique" in rule_ids
    assert "batch_code:pattern" in rule_ids
    assert "invoice_code:unique" in rule_ids
    assert "tags:minItems" in rule_ids
    assert "tags:maxItems" in rule_ids
    assert "tags:uniqueItems" in rule_ids
    assert "primary_key:unique" in rule_ids
    assert "even-cents" in rule_ids
    assert "no-huge-na" in rule_ids
    assert "max-ten-rows" in rule_ids
    assert [item["id"] for item in first["unmapped"]] == ["external-rule"]

    # Zero COUNT(DISTINCT ...) anywhere: all uniqueness rules compile to spill-capable GROUP BY queries
    for q in first["queries"]:
        assert "COUNT(DISTINCT" not in q["sql"].upper(), q

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
    assert first["tableSchema"] == "outputs"
    assert all('outputs."daily_revenue"' in q["sql"] for q in first["queries"])

    unqualified = compile_odcs_quality_counters(
        SCHEMA_OBJECT, "daily_revenue", query_name="counters", table_schema=None
    )
    assert unqualified["tableSchema"] is None
    assert all('outputs.' not in q["sql"] and '"daily_revenue"' in q["sql"] for q in unqualified["queries"])


def _write_table(path: Path, rows: list[dict]) -> None:
    arrow_schema = pa.schema([
        pa.field("order_day", pa.date32()),
        pa.field("region", pa.string()),
        pa.field("amount_cents", pa.int64()),
        pa.field("margin_ratio", pa.float64()),
        pa.field("batch_code", pa.string()),
        pa.field("invoice_code", pa.string()),
        pa.field("tags", pa.list_(pa.string())),
    ])
    table = pa.Table.from_pylist(rows, schema=arrow_schema)
    pq.write_table(table, path)


def _run_compiled_queries(tmp_path: Path, docspec_bin: str, parquet_path: Path, compiled: dict) -> dict[str, dict]:
    (tmp_path / "out").mkdir(parents=True, exist_ok=True)
    adapter = DocSpecAdapter(docspec_bin, dict(DEFAULT_DOCSPEC_GATE_LIMITS), evidence_dir=tmp_path / "evidence")
    cols = ["order_day", "region", "amount_cents", "margin_ratio", "batch_code", "invoice_code", "tags"]
    response = adapter.execute(
        {
            "scratch": str(tmp_path / "scratch"),
            "inputs": [{"kind": "parquet", "name": "raw_revenue", "path": str(parquet_path)}],
            "steps": [],
            "outputs": [
                {
                    "name": "daily_revenue",
                    "path": str(tmp_path / "out" / "daily_revenue.parquet"),
                    "sql": f"SELECT {', '.join(cols)} FROM raw_revenue",
                    "settings": {
                        "profile": "whole",
                        "row_group_rows": 8192,
                        "order_by": [
                            {"field": "batch_code", "direction": "asc", "nulls": "nulls_last"},
                            {"field": "amount_cents", "direction": "asc", "nulls": "nulls_last"},
                        ],
                        "columns": cols,
                        "dictionary_columns": [],
                        "delta_columns": [],
                        "key_column": None,
                        "created_by": "ddk-test",
                        "footer_limit": 1 << 20,
                    },
                }
            ],
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

    # 2. Clean multi-row table with multiple unique columns: every counter evaluates to 0.
    clean_file = tmp_path / "clean.parquet"
    _write_table(clean_file, [
        {
            "order_day": date(2026, 1, 1),
            "region": "NA",
            "amount_cents": 200,
            "margin_ratio": 0.25,
            "batch_code": "B1",
            "invoice_code": "INV-1",
            "tags": ["retail", "direct"],
        },
        {
            "order_day": date(2026, 1, 1),
            "region": "EU",
            "amount_cents": 400,
            "margin_ratio": 0.50,
            "batch_code": "B2",
            "invoice_code": "INV-2",
            "tags": ["wholesale"],
        },
    ])
    clean_rows = _run_compiled_queries(tmp_path / "run-clean", docspec_bin, clean_file, compiled)
    for rule in compiled["rules"]:
        q_row = clean_rows[rule["query"]]
        val = q_row[rule["column"]] if rule["column"] is not None else next(iter(q_row.values()))
        assert val == 0, (rule["id"], val)

    # 3. Faulty table with planted violations across all rule classes (including 2 unique columns, regex, length, array, rowCount).
    strict_rowcount_schema = {
        **SCHEMA_OBJECT,
        "quality": [
            SCHEMA_OBJECT["quality"][0],
            {"id": "exact-two-rows", "metric": "rowCount", "mustBe": 2},
        ],
    }
    compiled_bad = compile_odcs_quality_counters(strict_rowcount_schema, "daily_revenue", query_name="counters")
    bad_file = tmp_path / "bad.parquet"
    _write_table(bad_file, [
        {
            "order_day": date(2026, 1, 1),
            "region": "NA",
            "amount_cents": 600_001,
            "margin_ratio": 1.0,
            "batch_code": "B1",
            "invoice_code": "INV-DUP",
            "tags": [],  # violates minItems=1
        },
        {
            "order_day": date(2026, 1, 1),
            "region": "NA",
            "amount_cents": -4,
            "margin_ratio": 0.0,
            "batch_code": "B1",
            "invoice_code": "INV-DUP",
            "tags": ["dup", "dup"],  # violates uniqueItems=True
        },
        {
            "order_day": None,
            "region": "LATAM",  # violates enum & maxLength=4
            "amount_cents": 2_000_000,
            "margin_ratio": 0.5,
            "batch_code": "BAD_CODE",  # violates pattern ^B[0-9]+$
            "invoice_code": "INV-3",
            "tags": ["a", "b", "c", "d"],  # violates maxItems=3
        },
    ])
    bad_rows = _run_compiled_queries(tmp_path / "run-bad", docspec_bin, bad_file, compiled_bad)
    observed = {
        rule["id"]: (
            bad_rows[rule["query"]][rule["column"]]
            if rule["column"] is not None
            else next(iter(bad_rows[rule["query"]].values()))
        )
        for rule in compiled_bad["rules"]
    }
    assert observed["order_day:required"] == 1
    assert observed["region:enum"] == 1
    assert observed["region:maxLength"] == 1
    assert observed["amount_cents:minimum"] == 1
    assert observed["amount_cents:maximum"] == 1
    assert observed["margin_ratio:exclusiveMinimum"] == 1
    assert observed["margin_ratio:exclusiveMaximum"] == 1
    assert observed["batch_code:unique"] == 1
    assert observed["batch_code:pattern"] == 1
    assert observed["invoice_code:unique"] == 1
    assert observed["tags:minItems"] == 1
    assert observed["tags:maxItems"] == 1
    assert observed["tags:uniqueItems"] == 1
    assert observed["primary_key:unique"] == 1
    assert observed["even-cents"] == 1
    assert observed["no-huge-na"] == 1
    assert observed["exact-two-rows"] == 1


def test_compile_relationship_join_metrics_queries_builds_small_target_left_and_executes(tmp_path, docspec_bin):
    catalog = {
        "datasets": [
            {"alias": "orders", "id": "urn:ex:dataset:orders"},
            {"alias": "customers", "id": "urn:ex:dataset:customers"},
        ],
        "relationships": [
            {
                "id": "urn:ex:relationship:order-customer",
                "match": "equal",
                "nulls": "skip",
                "source": {"dataset": "orders", "paths": [[{"field": "customer_id"}]]},
                "target": {"dataset": "customers", "paths": [[{"field": "customer_id"}]]},
            },
            {
                "id": "urn:ex:relationship:peer-skip",
                "match": "equal",
                "source": {"dataset": "orders", "paths": [[{"field": "customer_id"}]]},
                "target": {"catalog": "peer", "dataset": "customers", "paths": [[{"field": "customer_id"}]]},
            },
        ],
    }
    compiled = compile_relationship_join_metrics_queries(catalog, table_schema=None)
    assert len(compiled["relationships"]) == 1
    assert len(compiled["skipped"]) == 1
    q = compiled["queries"][0]
    assert 'FROM "customers"' in q["sql"]
    assert "RIGHT ANTI JOIN" in q["sql"]
    assert "COUNT(DISTINCT" not in q["sql"].upper()

    orders_file = tmp_path / "orders.parquet"
    customers_file = tmp_path / "customers.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"order_id": "o1", "customer_id": "c1"},
                {"order_id": "o2", "customer_id": "c2"},
                {"order_id": "o3", "customer_id": "c_missing"},
                {"order_id": "o4", "customer_id": None},
            ],
            schema=pa.schema([pa.field("order_id", pa.string()), pa.field("customer_id", pa.string())]),
        ),
        orders_file,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [{"customer_id": "c1"}, {"customer_id": "c2"}],
            schema=pa.schema([pa.field("customer_id", pa.string())]),
        ),
        customers_file,
    )

    adapter = DocSpecAdapter(docspec_bin, dict(DEFAULT_DOCSPEC_GATE_LIMITS), evidence_dir=tmp_path / "ev")
    resp = adapter.execute(
        {
            "scratch": str(tmp_path / "scratch"),
            "inputs": [
                {"kind": "parquet", "name": "orders", "path": str(orders_file)},
                {"kind": "parquet", "name": "customers", "path": str(customers_file)},
            ],
            "steps": [],
            "outputs": [],
            "queries": compiled["queries"],
        },
        input_digests={},
    )
    assert resp["status"] == "succeeded", resp
    metrics = resp["result"]["queries"][0]["data"][0]
    assert metrics == {
        "source_row_count": 4,
        "eligible_source_rows": 3,
        "matched_rows": 2,
        "unmatched_rows": 1,
    }
