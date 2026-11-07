"""Independent declared-type, literal and actual Parquet preservation cases."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
import os

import pytest

from ddk.arrow_mapping import (
    DECLARATION_PROFILE, SCALAR_PROFILE, MappingUnavailable, arrow_schema,
    map_declaration, typed_rows,
)
from ddk.adapters.native_intake import fixture_files, table_schema
from ddk.documents import ODCS_SCHEMA, REPOSITORY, read_json


def dataset(*properties):
    return {"name": "records", "logicalType": "object", "properties": list(properties)}


def prop(logical, options=None, **extra):
    return {"name": "value", "logicalType": logical,
            **({"logicalTypeOptions": options} if options is not None else {}), **extra}


def mapping(declaration):
    return map_declaration(declaration, profile=DECLARATION_PROFILE)


def test_legacy_scalar_interpretation_stays_explicit_and_options_never_widen_silently():
    original = dataset(prop("integer"))
    assert arrow_schema(original)[0]["fields"][0]["data_type"] == "Int64"
    assert typed_rows([{}], original) == [{"value": None}]  # Frozen v1 nullable fixture behavior.
    for declaration in (dataset(prop("integer", {"format": "i32"})),
                        dataset(prop("string", {"format": "binary"})),
                        dataset(prop("date", {"format": "MM/dd/yyyy"}))):
        before = deepcopy(declaration)
        schema, coverage = arrow_schema(declaration)
        assert not schema["fields"] and all(row["status"] == "unsupported" for row in coverage)
        assert coverage[-1]["facet"] == "logicalTypeOptions/format"
        with pytest.raises(MappingUnavailable):
            typed_rows([{"value": None}], declaration)
        assert declaration == before
    for logical in ("integer", "number"):
        original = dataset(prop(logical))
        with pytest.raises(MappingUnavailable):
            mapping(original).require_physical()
        assert "logicalTypeOptions" not in original["properties"][0]
    with pytest.raises(MappingUnavailable, match="Unknown"):
        arrow_schema(original, profile="unknown")


@pytest.mark.parametrize("fmt,native,low,high", [
    ("i8", "Int8", -128, 127), ("i16", "Int16", -32768, 32767),
    ("i32", "Int32", -(2**31), 2**31 - 1), ("i64", "Int64", -(2**63), 2**63 - 1),
    ("u8", "UInt8", 0, 255), ("u16", "UInt16", 0, 65535),
    ("u32", "UInt32", 0, 2**32 - 1), ("u64", "UInt64", 0, 2**64 - 1),
])
def test_integer_widths_and_signedness_are_exact_in_real_parquet(tmp_path, fmt, native, low, high):
    import pyarrow as pa
    import pyarrow.parquet as pq
    declaration = dataset(prop("integer", {"format": fmt}, required=True))
    result = fixture_files({"mappingProfile": DECLARATION_PROFILE,
                            "inputs": {"records": {"dataset": declaration, "rows": [{"value": low}, {"value": high}]}}}, tmp_path)
    member = result["files"][0]
    actual = pq.read_table(member["path"])
    assert actual.schema.field("value").type == pa.type_for_alias(native.lower())
    assert actual["value"].to_pylist() == [low, high]
    assert member["schema"]["fields"][0]["data_type"] == native
    assert result["dataValidation"] == "not_run"
    assert any(row["facet"] == "required" for row in member["validationObligations"])
    for value in (low - 1, high + 1, True, str(high), None):
        with pytest.raises(ValueError):
            mapping(declaration).rows([{"value": value}])


def test_nested_list_struct_nulls_and_requiredness_preserve_actual_values(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    declaration = dataset(prop("array", {"minItems": 1}, items={
        "logicalType": "object", "logicalTypeOptions": {"required": ["code"]},
        "properties": [{"name": "code", "logicalType": "integer", "logicalTypeOptions": {"format": "i32"}}],
    }))
    before = deepcopy(declaration)
    rows = [{"value": None}, {"value": []}, {"value": [None]}, {"value": [{"code": None}, {"code": 17}]}]
    result = fixture_files({"mappingProfile": DECLARATION_PROFILE,
                           "inputs": {"records": {"dataset": declaration, "rows": rows}}}, tmp_path)
    actual = pq.read_table(result["files"][0]["path"])
    expected_type = pa.list_(pa.field("element", pa.struct([pa.field("code", pa.int32(), nullable=True)]), nullable=True))
    assert actual.schema == pa.schema([pa.field("value", expected_type, nullable=True)])
    assert actual.to_pylist() == rows
    assert declaration == before
    assert {row["facet"] for row in result["files"][0]["validationObligations"]} == {
        "logicalTypeOptions/minItems", "logicalTypeOptions/required"}
    for absent in ({}, {"value": [{}]}):
        with pytest.raises(MappingUnavailable, match="absent"):
            mapping(declaration).rows([absent])
    with pytest.raises(ValueError, match="undeclared"):
        mapping(declaration).rows([{"value": [{"code": 1, "extra": None}]}])
    nonnull = deepcopy(declaration)
    nonnull["properties"][0]["items"]["required"] = True
    with pytest.raises(ValueError, match="non-null"):
        mapping(nonnull).rows([{"value": [None]}])


@pytest.mark.parametrize("fmt,accepted,rejected", [
    ("f32", Decimal("0.5"), 2**24 + 1),
    ("f64", Decimal("0.5"), 2**53 + 1),
])
def test_floats_require_exact_literal_representation(fmt, accepted, rejected):
    item = mapping(dataset(prop("number", {"format": fmt})))
    assert item.rows([{"value": accepted}]) == [{"value": 0.5}]
    for value in (rejected, Decimal("0.1"), Decimal("NaN"), float("inf"), 10**400):
        with pytest.raises(MappingUnavailable):
            item.rows([{"value": value}])
    for value in (True, "0.5"):
        with pytest.raises(ValueError):
            item.rows([{"value": value}])


def test_calendar_dates_and_timestamp_nanoseconds_do_not_round(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    declaration = dataset(
        prop("date", {"format": "yyyy-MM-dd"}, name="day"),
        prop("timestamp", {"format": "yyyy-MM-dd'T'HH:mm:ss.SSSSSSSSSXXX", "timezone": True,
                           "defaultTimezone": "UTC"}, name="instant"),
        prop("timestamp", {"format": "yyyy-MM-dd HH:mm:ss.SSSSSS", "timezone": False}, name="local"),
        prop("time", {"format": "HH:mm:ss.SSSSSSSSS", "timezone": False}, name="clock"),
    )
    rows = [{"day": "2024-02-29", "instant": "1970-01-01T00:00:00.123456789Z",
             "local": "1969-12-31 23:59:59.999999", "clock": "12:00:00.000000001"}]
    item = mapping(declaration)
    assert item.rows(rows) == [{"day": date(2024, 2, 29), "instant": 123456789, "local": -1, "clock": 43200000000001}]
    result = fixture_files({"mappingProfile": DECLARATION_PROFILE,
                           "inputs": {"records": {"dataset": declaration, "rows": rows}}}, tmp_path)
    actual = pq.read_table(result["files"][0]["path"])
    assert actual.schema.types == [pa.date32(), pa.timestamp("ns", "UTC"), pa.timestamp("us"), pa.time64("ns")]
    assert actual["instant"].cast(pa.int64()).to_pylist() == [123456789]
    assert actual["local"].cast(pa.int64()).to_pylist() == [-1]
    assert actual["clock"].cast(pa.int64()).to_pylist() == [43200000000001]
    for field, value in (("day", "2023-02-29"), ("day", "20240229"),
                         ("instant", "1970-01-01T00:00:00.123456789+01:00"),
                         ("instant", "1970-01-01T00:00:00.123456Z"),
                         ("instant", "9999-01-01T00:00:00.123456789Z"),
                         ("local", "1970-01-01 00:00:60.000000"), ("clock", "24:00:00.000000000")):
        with pytest.raises(ValueError):
            item.rows([{**rows[0], field: value}])


@pytest.mark.parametrize("field", [
    prop("integer", {"format": "i128"}), prop("integer", {"format": "u128"}),
    prop("string", {"format": "binary"}), prop("string", {"format": "byte"}),
    prop("string", {"format": "custom-encoding"}), prop("date", {"format": "MM/dd/yyyy"}),
    prop("timestamp", {"format": "yyyy-MM-dd HH:mm:ss"}),
    prop("timestamp", {"format": "yyyy-MM-dd HH:mm:ss", "timezone": False, "defaultTimezone": "UTC"}),
    prop("timestamp", {"format": "yyyy-MM-dd HH:mm:ssXXX", "timezone": True}),
    prop("timestamp", {"format": "yyyy-MM-dd HH:mm:ssXXX", "timezone": True, "defaultTimezone": "America/New_York"}),
    prop("time", {"format": "HH:mm:ssXXX", "timezone": True, "defaultTimezone": "UTC"}),
    prop("number", {"format": "f64"}, physicalType="DECIMAL(18,4)"),
    prop("integer", {"format": "i32"}, physicalName="renamed"),
    prop("object"), prop("object", properties=[]), prop("array"),
    prop("array", items={"name": "custom", "logicalType": "boolean"}),
])
def test_unrepresentable_declarations_refuse_even_empty_or_null_fixtures(field):
    item = mapping(dataset(field))
    assert any(row["status"] == "unsupported" for row in item.coverage)
    for rows in ([], [{"value": None}]):
        with pytest.raises(MappingUnavailable):
            item.rows(rows)


def test_invalid_odcs_options_are_not_promoted_to_a_decimal_or_default_float():
    for options in ({"precision": 18, "scale": 4}, {"format": "i32"}, {"invented": True}):
        with pytest.raises(MappingUnavailable, match="pinned ODCS"):
            mapping(dataset(prop("number", options)))
    declaration = dataset(prop("integer", {}))
    before = deepcopy(declaration)
    assert any(row["status"] == "unsupported" for row in mapping(declaration).coverage)
    assert declaration == before
    with pytest.raises(MappingUnavailable):
        mapping(dataset()).rows([{}])


def test_every_pinned_option_is_explicitly_mapped_pending_or_unsupported():
    bounds = {"minimum": 1, "maximum": 9, "exclusiveMinimum": 0, "exclusiveMaximum": 10, "multipleOf": 1}
    temporal = {key: "2026-01-01" for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")}
    cases = {
        "string": {"format": "email", "minLength": 1, "maxLength": 8, "pattern": "^A"},
        "integer": {**bounds, "format": "i32"}, "number": {**bounds, "format": "f64"},
        "date": {**temporal, "format": "yyyy-MM-dd"},
        "timestamp": {**temporal, "format": "yyyy-MM-dd HH:mm:ssXXX", "timezone": True, "defaultTimezone": "UTC"},
        "time": {**temporal, "format": "HH:mm:ss", "timezone": False, "defaultTimezone": "UTC"},
        "object": {"minProperties": 1, "maxProperties": 2, "required": ["code"]},
        "array": {"minItems": 1, "maxItems": 2, "uniqueItems": True},
        "vector": {"dimensions": 3, "elementType": "float32", "distanceMetric": "cosine",
                   "embeddingModel": "example", "embeddingModelVersion": "1", "normalized": True},
    }
    # Independently authored cases must continue to cover the pinned vocabulary.
    schema = read_json(REPOSITORY / ODCS_SCHEMA).value
    pinned_sets = [set(row["then"]["properties"]["logicalTypeOptions"]["properties"])
                   for row in schema["$defs"]["SchemaBaseProperty"]["allOf"]
                   if "logicalTypeOptions" in row.get("then", {}).get("properties", {})]
    assert {frozenset(value) for value in pinned_sets} == {frozenset(value) for value in cases.values()}
    for logical, options in cases.items():
        extra = {"properties": [{"name": "code", "logicalType": "string"}]} if logical == "object" else (
            {"items": {"logicalType": "boolean"}} if logical == "array" else {})
        original = dataset(prop(logical, options, **extra))
        before = deepcopy(original)
        entries = [row for row in mapping(original).coverage if row["path"] == [{"field": "value"}]
                   and row["facet"].startswith("logicalTypeOptions/")]
        assert {row["facet"].split("/")[1] for row in entries} == set(options)
        assert all(row["status"] in {"exact", "unknown", "unsupported"} for row in entries)
        assert all(row["status"] == "unknown" for row in entries if row["meaning"] == "validation-needed")
        assert original == before
    _, coverage = table_schema(dataset(prop("string", {"minLength": 1, "maxLength": 8, "pattern": "^A"})))
    assert {row["facet"] for row in coverage} >= {"minLength", "maxLength", "pattern"}


@pytest.mark.parametrize("legacy", [["allowed", None], '["allowed", null]', [], "invalid-json"])
def test_legacy_enum_inventory_keeps_original_forms_and_order_without_claiming_validation(tmp_path, legacy):
    custom = [
        {"property": "description", "value": "unrelated metadata"},
        {"property": "enum", "value": legacy, "vendor": "source", "description": "Original spelling"},
        {"property": "enum", "value": ["second"]},
    ]
    declaration = dataset(prop("string", enum=[{"value": "standard"}], customProperties=custom))
    original = deepcopy(declaration)
    result = fixture_files({"mappingProfile": DECLARATION_PROFILE,
                           "inputs": {"records": {"dataset": declaration, "rows": [{"value": "outside"}]}}}, tmp_path)
    obligations = result["files"][0]["validationObligations"]
    assert result["status"] == "passed" and result["scope"] == "fixture-materialization-only"
    assert result["dataValidation"] == "not_run"
    # Standard/legacy precedence and malformed legacy values stay with the
    # maintained definition/validation owners. No authored declaration vanishes.
    assert [row["facet"] for row in obligations] == ["enum", "customProperties/1", "customProperties/2"]
    assert obligations[0]["value"] == [{"value": "standard"}]
    assert [row["value"] for row in obligations[1:]] == custom[1:]
    assert all(row["path"] == [{"field": "value"}] and row["status"] == "unknown" for row in obligations)
    assert all(row["scope"] == "property" and row["constraint"] == "enum" for row in obligations[1:])
    assert declaration == original
    obligations[1]["value"]["description"] = "Changed receipt copy"
    assert declaration == original


def test_identity_and_relationship_inventory_keeps_nested_scope_order_and_unchecked_values(tmp_path):
    import pyarrow.parquet as pq
    declaration = dataset(
        prop("string", relationships=[{"to": "lookup.code"},
                                      {"id": "external", "to": "other.yaml#/schema/lookup/properties/code"}]),
        prop("array", name="details", items={"logicalType": "object",
             "relationships": [{"id": "each", "to": "lookup.detail"}], "properties": [
            {"name": "code", "logicalType": "string",
             "customProperties": [{"property": "enum", "value": '["allowed"]'}],
             "relationships": [{"to": "lookup.code", "type": "foreignKey"}]},
        ]}),
    )
    declaration["customProperties"] = [
        {"vendor": "other", "property": "rowIdentity", "value": ["ignored"]},
        {"vendor": "ddk", "property": "rowIdentity", "value": ["value"]},
        {"vendor": "ddk", "property": "rowIdentity", "value": "invalid-shape"},
    ]
    declaration["relationships"] = [
        {"from": "records.value", "to": "lookup.code"},
        {"id": "composite", "type": "foreignKey", "from": ["records.value", "records.details.code"],
         "to": ["lookup.code", "lookup.detail"],
         "customProperties": [{"vendor": "source", "property": "meaning", "value": "Retain this metadata"}]},
    ]
    original = deepcopy(declaration)
    rows = [{"value": "duplicate", "details": [{"code": "outside-enum"}]}] * 2
    result = fixture_files({"mappingProfile": DECLARATION_PROFILE,
                           "inputs": {"records": {"dataset": declaration, "rows": rows}}}, tmp_path)
    member = result["files"][0]
    obligations = member["validationObligations"]
    actual = [(entry["path"], entry["scope"], entry["facet"], entry["constraint"], entry["value"])
              for entry in obligations]
    nested_path = [{"field": "details"}, {"each": True}, {"field": "code"}]
    assert actual == [
        ([{"field": "value"}], "property", "relationships/0", "relationship", {"to": "lookup.code"}),
        ([{"field": "value"}], "property", "relationships/1", "relationship",
         {"id": "external", "to": "other.yaml#/schema/lookup/properties/code"}),
        (nested_path, "property", "customProperties/0", "enum", {"property": "enum", "value": '["allowed"]'}),
        (nested_path, "property", "relationships/0", "relationship", {"to": "lookup.code", "type": "foreignKey"}),
        ([{"field": "details"}, {"each": True}], "property", "relationships/0", "relationship",
         {"id": "each", "to": "lookup.detail"}),
        ([], "schema", "customProperties/1", "ddk.rowIdentity", declaration["customProperties"][1]),
        ([], "schema", "customProperties/2", "ddk.rowIdentity", declaration["customProperties"][2]),
        ([], "schema", "relationships/0", "relationship", declaration["relationships"][0]),
        ([], "schema", "relationships/1", "relationship", declaration["relationships"][1]),
    ]
    assert all(entry["status"] == "unknown" and entry["meaning"] == "validation-needed" for entry in obligations)
    assert result["status"] == "passed" and result["scope"] == "fixture-materialization-only"
    assert result["dataValidation"] == "not_run"
    assert pq.read_table(member["path"]).to_pylist() == rows
    assert declaration == original


def test_scalar_materializer_uses_shared_schema_and_keeps_prior_receipt_shape(tmp_path):
    result = fixture_files({"inputs": {"records": {"dataset": dataset(prop("integer")), "rows": [{"value": 3}]}}}, tmp_path)
    assert result["status"] == "passed" and "mappingProfile" not in result
    assert set(result["files"][0]) == {"name", "path", "sha256", "rows", "schema"}
    item = map_declaration(dataset(prop("integer")))
    assert item.profile == SCALAR_PROFILE


def test_quality_constraints_are_deferred_and_the_maintained_evaluator_enforces_them(tmp_path):
    from ddk.adapters.native import NativeTools
    selected = os.environ.get("DDK_NATIVE_PYTHON")
    if not selected:
        pytest.skip("Select the retained Data Contract CLI environment for the actual evaluator test")
    native = NativeTools(selected, output=tmp_path)
    declaration = dataset(prop("integer", {"format": "i32", "minimum": 10}, required=True))
    staged = native.invoke("fixture-files", {"mappingProfile": DECLARATION_PROFILE,
                            "inputs": {"records": {"dataset": declaration, "rows": [{"value": 2}]}}})
    assert staged["status"] == "passed" and staged["dataValidation"] == "not_run"
    member = staged["files"][0]
    assert any(row["facet"] == "logicalTypeOptions/minimum" and row["status"] == "unknown"
               for row in member["validationObligations"])
    document = {"apiVersion": "v3.2.0", "kind": "DataContract", "id": "urn:test:declared-minimum",
                "version": "1.0.0", "status": "draft", "schema": [declaration]}
    result = native.invoke("quality", {"document": document,
                           "target": {"kind": "files", "files": [{"path": member["path"], "sha256": member["sha256"]}]}})
    assert result["status"] == "failed", result
    assert any(row["id"].endswith("field_minimum") and row["status"] == "failed" for row in result["checks"])
    assert result["nativeReport"]
