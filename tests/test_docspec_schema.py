"""Independent canonical schema and value expectations for source read v2."""

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from ddk.adapters.docspec import _native_read, native_version
from ddk.adapters.docspec_schema import (
    RECURSIVE_PROFILE, observed_source_schema, source_arrow_schema,
    source_native_read, source_schema_index,
)


def field(name, dtype, identifier, *, nullable=True):
    return {"name": name, "data_type": dtype, "nullable": nullable, "dict_id": 0,
            "dict_is_ordered": False, "metadata": {"PARQUET:field_id": str(identifier)}}


def schema():
    return {"fields": [
        field("id", "Int64", 1, nullable=False),
        field("groups", {"List": field("element", {"Struct": [field("code", "Int64", 4)]}, 3)}, 2),
        field("digest", {"FixedSizeBinary": 4}, 5),
        field("observed_at", {"Timestamp": ["Microsecond", "UTC"]}, 6),
        field("amount", {"Decimal128": [20, 0]}, 7),
        field("day", "Date32", 8),
    ], "metadata": {"owner": "native-public-source-view"}}


def version(tmp_path):
    return native_version(tmp_path, {"dataset": "source", "version": "prepared",
                          "manifest": {"owner": "source", "path": str(tmp_path / "manifest"),
                                       "digest": "a" * 64, "bytes": 100}})


def test_complete_recursive_index_and_raw_schema_are_separately_preserved(tmp_path):
    original = schema()
    receipt = {"schema_id": 3, "schema": original}
    result = source_native_read(version(tmp_path), receipt)
    assert result["profile"] == RECURSIVE_PROFILE
    assert result["fields"] == [
        {"path": [{"field": "id"}], "nativeFieldPath": [1], "position": 0},
        {"path": [{"field": "groups"}], "nativeFieldPath": [2], "position": 1},
        {"path": [{"field": "groups"}, {"each": True}], "nativeFieldPath": [2, 3], "position": 0},
        {"path": [{"field": "groups"}, {"each": True}, {"field": "code"}], "nativeFieldPath": [2, 3, 4], "position": 0},
        {"path": [{"field": "digest"}], "nativeFieldPath": [5], "position": 2},
        {"path": [{"field": "observed_at"}], "nativeFieldPath": [6], "position": 3},
        {"path": [{"field": "amount"}], "nativeFieldPath": [7], "position": 4},
        {"path": [{"field": "day"}], "nativeFieldPath": [8], "position": 5},
    ]
    assert result["schema"] == original
    result["schema"]["fields"][1]["data_type"]["List"]["nullable"] = False
    assert original["fields"][1]["data_type"]["List"]["nullable"] is True
    assert "physicalTable" not in result and "originalSchema" not in result
    with pytest.raises(ValueError, match="Exact mapping unavailable"):
        _native_read(version(tmp_path), receipt)
    assert _native_read(version(tmp_path), receipt, RECURSIVE_PROFILE)["schema"] == original


def test_independent_arrow_schema_preserves_nested_values_and_exact_types():
    pa = pytest.importorskip("pyarrow")
    def f(name, dtype, identifier, nullable=True):
        return pa.field(name, dtype, nullable, {b"PARQUET:field_id": str(identifier).encode()})
    expected = pa.schema([
        f("id", pa.int64(), 1, False),
        f("groups", pa.list_(f("element", pa.struct([f("code", pa.int64(), 4)]), 3)), 2),
        f("digest", pa.binary(4), 5),
        f("observed_at", pa.timestamp("us", "UTC"), 6),
        f("amount", pa.decimal128(20, 0), 7),
        f("day", pa.date32(), 8),
    ], metadata={b"owner": b"native-public-source-view"})
    actual = source_arrow_schema(schema(), pa)
    assert actual.equals(expected, check_metadata=True)
    assert observed_source_schema(expected, pa) == schema()
    values = [None, [], [None, {"code": None}, {"code": 9007199254740993}, {"code": 9007199254740993}]]
    rows = [{"id": i, "groups": groups, "digest": b"\x00\x7f\x80\xff",
             "observed_at": datetime(2026, 11, 6, 12, 30, 5, 123456, timezone.utc),
             "amount": Decimal("18446744073709551615"), "day": date(2026, 11, 6)}
            for i, groups in enumerate(values)]
    table = pa.Table.from_pylist(rows, schema=expected)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, expected) as writer:
        writer.write_table(table)
    read = pa.ipc.open_stream(sink.getvalue()).read_all()
    assert read.schema.equals(actual, check_metadata=True)
    assert read.to_pylist() == rows
    assert read.column("groups").to_pylist() == values


@pytest.mark.parametrize("case", ["missing-item-id", "duplicate-child-id", "duplicate-sibling-name", "missing-child-type",
                                 "invalid-id", "bool-nullable", "unsupported-map", "unsupported-union", "timestamp-zone",
                                 "timestamp-unit", "decimal-scale", "fixed-binary-width", "unsigned-original"])
def test_incomplete_or_unsupported_schema_refuses_the_whole_observation(case):
    raw = schema()
    item = raw["fields"][1]["data_type"]["List"]
    if case == "missing-item-id":
        item["metadata"] = {}
    elif case == "duplicate-child-id":
        item["data_type"]["Struct"][0]["metadata"]["PARQUET:field_id"] = "1"
    elif case == "duplicate-sibling-name":
        raw["fields"][2]["name"] = "groups"
    elif case == "missing-child-type":
        item.pop("data_type")
    elif case == "invalid-id":
        item["metadata"]["PARQUET:field_id"] = str(1 << 31)
    elif case == "bool-nullable":
        item["nullable"] = 1
    elif case in {"unsupported-map", "unsupported-union"}:
        raw["fields"][1]["data_type"] = {"Map" if case.endswith("map") else "Union": []}
    elif case == "timestamp-zone":
        raw["fields"][3]["data_type"] = {"Timestamp": ["Microsecond", "America/New_York"]}
    elif case == "timestamp-unit":
        raw["fields"][3]["data_type"] = {"Timestamp": ["Millisecond", "UTC"]}
    elif case == "decimal-scale":
        raw["fields"][4]["data_type"] = {"Decimal128": [20, 21]}
    elif case == "fixed-binary-width":
        raw["fields"][2]["data_type"] = {"FixedSizeBinary": True}
    elif case == "unsigned-original":
        raw["fields"][0]["data_type"] = "UInt64"
    with pytest.raises(ValueError):
        source_schema_index(raw)


def test_repeated_names_at_distinct_struct_paths_are_unambiguous():
    raw = {"fields": [field("left", {"Struct": [field("value", "Int64", 2)]}, 1),
                       field("right", {"Struct": [field("value", "Int64", 4)]}, 3)], "metadata": {}}
    paths = source_schema_index(raw)
    assert paths[1]["nativeFieldPath"] == [1, 2]
    assert paths[3]["nativeFieldPath"] == [3, 4]


def nested_schema(depth):
    node = field("value", "Int64", depth)
    for identifier in reversed(range(1, depth)):
        node = field("element" if identifier > 1 else "nested", {"List": node}, identifier)
    return {"fields": [node], "metadata": {}}


def test_mapping_bounds_are_exact_and_apply_before_schema_copy():
    from ddk.adapters.docspec_schema import MAX_DEPTH, MAX_FIELDS, MAX_NAME_BYTES
    raw = {"fields": [field(f"c{index}", "Int64", index + 1) for index in range(MAX_FIELDS)], "metadata": {}}
    assert len(source_schema_index(raw)) == MAX_FIELDS
    raw["fields"].append(field("overflow", "Int64", MAX_FIELDS + 1))
    with pytest.raises(ValueError, match="bound"):
        source_schema_index(raw)
    assert len(source_schema_index(nested_schema(MAX_DEPTH))) == MAX_DEPTH
    with pytest.raises(ValueError, match="bound"):
        source_schema_index(nested_schema(MAX_DEPTH + 1))
    raw = {"fields": [field("x" * (MAX_NAME_BYTES + 1), "Int64", 1)], "metadata": {}}
    with pytest.raises(ValueError):
        source_schema_index(raw)


def test_index_byte_bound_matches_the_actual_unicode_and_escape_serialization(monkeypatch):
    from ddk.adapters import docspec_schema
    from ddk.documents import json_dumps
    names = ['field\U00010330"\\\n', 'second\U0001f600"\\\t']
    raw = {"fields": [field(name, "Int64", index + 1) for index, name in enumerate(names)], "metadata": {}}
    expected = [{"path": [{"field": name}], "nativeFieldPath": [index + 1], "position": index}
                for index, name in enumerate(names)]
    exact_size = len(json.dumps(expected, sort_keys=True, ensure_ascii=True).encode("utf-8"))
    assert len(json_dumps(expected).encode("utf-8")) == exact_size
    monkeypatch.setattr(docspec_schema, "MAX_INDEX_BYTES", exact_size)
    assert source_schema_index(raw) == expected
    monkeypatch.setattr(docspec_schema, "MAX_INDEX_BYTES", exact_size - 1)
    with pytest.raises(ValueError, match="byte allocation"):
        source_schema_index(raw)
    monkeypatch.setattr(docspec_schema, "MAX_INDEX_BYTES", exact_size)
    raw["fields"].append(field("next", "Int64", 3))
    with pytest.raises(ValueError, match="byte allocation"):
        source_schema_index(raw)


def test_repeated_long_ancestor_names_cannot_expand_index_without_bound():
    children = [field(f"c{index}", "Int64", index + 2) for index in range(2200)]
    raw = {"fields": [field("p" * 1024, {"Struct": children}, 1)], "metadata": {}}
    with pytest.raises(ValueError, match="byte allocation"):
        source_schema_index(raw)


@pytest.mark.parametrize("dtype", [{"Time64": "Microsecond"}, {"Timestamp": ["Nanosecond", None]},
                                   {"Timestamp": ["Microsecond", "+00:00"]}])
def test_additional_canonical_temporal_shapes_roundtrip_without_defaulting(dtype):
    pa = pytest.importorskip("pyarrow")
    raw = {"fields": [field("time", dtype, 1)], "metadata": {}}
    assert observed_source_schema(source_arrow_schema(raw, pa), pa) == raw


def test_common_schema_distinguishes_v1_and_v2_without_reinterpretation(tmp_path):
    from ddk.documents import schema_validator
    # Validate the shared referenced definition directly; no fabricated execution report.
    v2 = source_native_read(version(tmp_path), {"schema_id": 3, "schema": schema()})
    selected = schema_validator({"$ref": "https://example.org/ddk/0.1/common.schema.json#/$defs/nativeRead"})
    assert not list(selected.iter_errors(v2))
    legacy = schema_validator({"$ref": "https://example.org/ddk/0.1/common.schema.json#/$defs/nativeReadV1"})
    assert list(legacy.iter_errors(v2))
    malformed = deepcopy(v2)
    malformed.pop("profile")
    assert list(selected.iter_errors(malformed))
