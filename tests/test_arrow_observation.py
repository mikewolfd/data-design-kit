"""Independent physical schemas; these examples never claim data validation."""
from copy import deepcopy

import pytest

from ddk.arrow_observation import MANAGED_SCHEMA_V2
from ddk.docspec_job_evidence import JobEvidenceError, interpret_output_schema

pa = pytest.importorskip("pyarrow")


def declaration(*properties, **extra):
    return {"name": "observed", "logicalType": "object", "properties": list(properties), **extra}


def integer(**extra):
    return {"name": "id", "logicalType": "integer", "logicalTypeOptions": {"format": "i64"}, **extra}


def observe(schema, value, profile=MANAGED_SCHEMA_V2):
    return interpret_output_schema(schema.serialize().to_pybytes(), value, profile=profile)


@pytest.mark.parametrize("format,physical", [("i8", pa.int8()), ("u8", pa.uint8()), ("i16", pa.int16()),
    ("u16", pa.uint16()), ("i32", pa.int32()), ("u32", pa.uint32()), ("i64", pa.int64()), ("u64", pa.uint64())])
def test_exact_integer_options_are_type_facts_not_row_rules(format, physical):
    value = declaration(integer(logicalTypeOptions={"format": format}))
    before = deepcopy(value)
    result = observe(pa.schema([pa.field("id", physical)]), value)
    assert (result.status, result.obligations) == ("passed", ())
    assert value == before
    wrong = observe(pa.schema([pa.field("id", pa.string())]), value)
    assert wrong.status == "failed"


@pytest.mark.parametrize("required,nullable,pending", [(True, True, True), (True, False, False),
                                                        (False, True, False), (False, False, False)])
def test_nullability_is_observed_without_inventing_row_evidence(required, nullable, pending):
    result = observe(pa.schema([pa.field("id", pa.int64(), nullable=nullable)]), declaration(integer(required=required)))
    assert result.status == "passed"
    assert [row["facet"] for row in result.obligations] == (["required"] if pending else [])
    assert result.fields[0]["nullable"] is nullable


def test_value_options_and_enum_remain_pending():
    value = declaration(integer(logicalTypeOptions={"format": "i64", "minimum": 10, "multipleOf": 2},
                                enum=[{"value": "10"}, {"value": "12"}], unique=True),
                        {"name": "label", "logicalType": "string", "logicalTypeOptions": {"pattern": "^A", "format": "email"}})
    result = observe(pa.schema([pa.field("id", pa.int64()), pa.field("label", pa.string())]), value)
    assert result.status == "passed"
    assert {row["facet"] for row in result.obligations} == {
        "logicalTypeOptions/minimum", "logicalTypeOptions/multipleOf", "enum", "key_unique",
        "logicalTypeOptions/pattern", "logicalTypeOptions/format"}


def test_nested_order_item_name_and_presence_obligation():
    value = declaration({"name": "rows", "logicalType": "array", "logicalTypeOptions": {"minItems": 1},
        "items": {"logicalType": "object", "logicalTypeOptions": {"required": ["id"]}, "properties": [integer()]}})
    nested = pa.struct([pa.field("id", pa.int64())])
    result = observe(pa.schema([pa.field("rows", pa.list_(pa.field("element", nested)))]), value)
    assert result.status == "passed"
    assert {row["facet"] for row in result.obligations} == {"logicalTypeOptions/minItems", "logicalTypeOptions/required"}
    assert result.fields[-1]["logicalPath"] == [{"field": "rows"}, {"each": True}, {"field": "id"}]
    assert result.fields[-1]["nullable"] is True  # object.required is presence, not child nonnull
    assert observe(pa.schema([pa.field("rows", pa.list_(pa.field("item", nested)))]), value).status == "failed"
    assert observe(pa.schema([pa.field("rows", pa.large_list(pa.field("element", nested)))]), value).status == "failed"
    ordered = declaration(integer(), {"name": "label", "logicalType": "string"})
    assert observe(pa.schema([pa.field("label", pa.string()), pa.field("id", pa.int64())]), ordered).status == "failed"


def test_temporal_width_unit_and_zone_are_exact():
    value = declaration({"name": "at", "logicalType": "timestamp", "logicalTypeOptions": {
        "format": "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXX", "timezone": True, "defaultTimezone": "UTC"}})
    assert observe(pa.schema([pa.field("at", pa.timestamp("us", "UTC"))]), value).status == "passed"
    for dtype in [pa.timestamp("ns", "UTC"), pa.timestamp("us"), pa.timestamp("us", "+00:00"), pa.string()]:
        assert observe(pa.schema([pa.field("at", dtype)]), value).status == "failed"


@pytest.mark.parametrize("extra", [{"physicalType": "BIGINT"}, {"logicalTypeOptions": {}},
    {"logicalTypeOptions": {"format": "i128"}}, {"customProperties": [{"property": "nativeFieldId", "value": 7}]}])
def test_unsupported_meaning_remains_unknown_without_fallback(extra):
    assert observe(pa.schema([pa.field("id", pa.int64())]), declaration(integer(**extra))).status == "unknown"


def test_default_profile_does_not_silently_adopt_new_type_interpretation():
    result = observe(pa.schema([pa.field("id", pa.int64())]), declaration(integer()), profile=None)
    assert "logicalTypeOptions/format" in {row["facet"] for row in result.obligations}
    with pytest.raises(JobEvidenceError, match="profile"):
        observe(pa.schema([pa.field("id", pa.int64())]), declaration(integer()), profile="unregistered")


def test_legacy_enum_and_relationship_obligations_survive_observation():
    relationship = {"type": "foreignKey", "to": "related.id"}
    value = declaration(integer(customProperties=[{"property": "enum", "value": '["10"]'}],
                                relationships=[relationship]), relationships=[{"from": "observed.id", **relationship}])
    result = observe(pa.schema([pa.field("id", pa.int64())]), value)
    assert result.status == "passed", result.reasons
    assert {(row["facet"], str(row["paths"])) for row in result.obligations} == {
        ("customProperties/0", "[[{'field': 'id'}]]"), ("relationships/0", "[[{'field': 'id'}]]"),
        ("relationships/0", "[[]]")}
