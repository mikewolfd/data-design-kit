"""Exact literal and physical expectations, independent of the declaration mapper."""
from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from ddk.arrow_mapping import DECLARATION_PROFILE, EXACT_PROFILE, MappingUnavailable, map_declaration, pyarrow_schema
from ddk.arrow_observation import MANAGED_SCHEMA_V3
from ddk.docspec_job_evidence import JobEvidenceError, interpret_output_schema

pa = pytest.importorskip("pyarrow")


def decimal(physical="decimal128(38,18)", **extra):
    return {"name": "amount", "logicalType": "number", "physicalType": physical, **extra}


def binary(physical="fixed[4]", **extra):
    return {"name": "digest", "logicalType": "string", "physicalType": physical,
            "logicalTypeOptions": {"format": "binary"}, **extra}


def dataset(*fields):
    return {"name": "exact", "logicalType": "object", "properties": list(fields)}


def observe(schema, declaration):
    return interpret_output_schema(schema.serialize().to_pybytes(), declaration, profile=MANAGED_SCHEMA_V3)


def test_exact_decimal_and_binary_nested_parquet_round_trip(tmp_path):
    import pyarrow.parquet as pq
    declaration = dataset(decimal(required=True), binary(),
        {"name": "repeated", "logicalType": "array", "items": {
            "logicalType": "object", "properties": [decimal("decimal128(38,2)"), binary("binary")]}})
    original = deepcopy(declaration)
    mapping = map_declaration(declaration, profile=EXACT_PROFILE)
    rows = [{"amount": Decimal("12345678901234567890.123456789012345678"), "digest": b"\x00\xffAB",
             "repeated": [{"amount": Decimal("9007199254740993.01"), "digest": b""},
                          {"amount": Decimal("9007199254740993.01"), "digest": b""}, None]},
            {"amount": Decimal("-0.000000000000000001"), "digest": None, "repeated": []}]
    expected = pa.schema([pa.field("amount", pa.decimal128(38, 18), nullable=False), pa.field("digest", pa.binary(4)),
                          pa.field("repeated", pa.list_(pa.field("element", pa.struct([
                              pa.field("amount", pa.decimal128(38, 2)), pa.field("digest", pa.binary())]))))])
    with localcontext() as context:
        context.prec = 6  # Fixture conversion must not depend on ambient decimal arithmetic.
        actual = pa.Table.from_pylist(mapping.rows(rows), schema=pyarrow_schema(mapping.schema, pa))
    assert actual.schema == expected
    assert actual.to_pylist() == rows
    path = tmp_path / "exact.parquet"
    pq.write_table(actual, path)
    retained = pq.read_table(path)
    assert retained.schema == expected and retained.to_pylist() == rows
    result = observe(retained.schema, declaration)
    assert (result.status, result.obligations) == ("passed", ())
    assert declaration == original


@pytest.mark.parametrize("value", [Decimal("1.001"), Decimal("1000"), 1000, 1.25, "1.25", True,
                                   Decimal("NaN"), Decimal("Infinity"), Decimal("-0"), Decimal("1e1000000")])
def test_decimal_rounding_overflow_and_implicit_coercions_refuse(value):
    mapping = map_declaration(dataset(decimal("decimal128(5,2)")), profile=EXACT_PROFILE)
    with pytest.raises(MappingUnavailable):
        mapping.rows([{"amount": value}])


@pytest.mark.parametrize("physical,dtype", [("decimal128(38,2)", pa.decimal128(38,2)),
    ("decimal128(38,6)", pa.decimal128(38,6)), ("decimal128(38,9)", pa.decimal128(38,9)),
    ("decimal128(38,12)", pa.decimal128(38,12)), ("decimal128(38,18)", pa.decimal128(38,18)),
    ("decimal256(76,0)", pa.decimal256(76,0))])
def test_actual_declared_precisions_and_scales_are_not_float_defaults(physical, dtype):
    declaration = dataset(decimal(physical))
    mapping = map_declaration(declaration, profile=EXACT_PROFILE)
    assert pyarrow_schema(mapping.schema, pa) == pa.schema([pa.field("amount", dtype)])
    assert observe(pa.schema([pa.field("amount", dtype)]), declaration).status == "passed"
    for wrong in (pa.float64(), pa.decimal128(20,0), pa.string()):
        assert observe(pa.schema([pa.field("amount", wrong)]), declaration).status == "failed"


@pytest.mark.parametrize("physical,dtype,value", [("binary", pa.binary(), b""),
    ("large_binary", pa.large_binary(), b"\x00\xff"), ("fixed[4]", pa.binary(4), b"\x00\xffAB")])
def test_binary_bytes_are_exact_without_text_encoding(physical, dtype, value):
    declaration = dataset(binary(physical))
    mapping = map_declaration(declaration, profile=EXACT_PROFILE)
    assert pyarrow_schema(mapping.schema, pa) == pa.schema([pa.field("digest", dtype)])
    assert mapping.rows([{"digest": value}]) == [{"digest": value}]
    assert observe(pa.schema([pa.field("digest", dtype)]), declaration).status == "passed"
    assert observe(pa.schema([pa.field("digest", pa.string())]), declaration).status == "failed"
    for wrong in ("AP9BQg==", "00ff4142", bytearray(value), 1):
        with pytest.raises(MappingUnavailable):
            mapping.rows([{"digest": wrong}])


def test_fixed_width_and_decimal_scale_changes_fail():
    declaration = dataset(decimal("decimal128(20,2)"), binary("fixed[4]"))
    for fields in [(pa.decimal128(20,3), pa.binary(4)), (pa.decimal128(21,2), pa.binary(4)),
                   (pa.decimal128(20,2), pa.binary(8)), (pa.decimal128(20,2), pa.binary())]:
        assert observe(pa.schema([pa.field("amount", fields[0]), pa.field("digest", fields[1])]), declaration).status == "failed"
    with pytest.raises(MappingUnavailable):
        map_declaration(dataset(binary()), profile=EXACT_PROFILE).rows([{"digest": b"abc"}])


@pytest.mark.parametrize("prop", [decimal("DECIMAL(38,2)"), decimal("decimal128(39,2)"),
    decimal("decimal128(10,11)"), decimal("decimal128(10,-1)"), decimal("decimal128(010,2)"),
    decimal("decimal128(10,2)", logicalTypeOptions={"format":"f64"}),
    binary("fixed[0]"), binary("fixed[65537]"), binary("fixed[04]"),
    {"name":"digest", "logicalType":"string", "logicalTypeOptions":{"format":"binary"}},
    {"name":"digest", "logicalType":"string", "physicalType":"binary", "logicalTypeOptions":{"format":"byte"}}])
def test_ambiguous_or_unsupported_physical_meaning_stays_unknown(prop):
    mapping = map_declaration(dataset(prop), profile=EXACT_PROFILE)
    with pytest.raises(MappingUnavailable):
        mapping.require_physical()


def test_version_two_and_default_do_not_gain_new_mapping():
    for field in (decimal(), binary()):
        with pytest.raises(MappingUnavailable):
            map_declaration(dataset(field), profile=DECLARATION_PROFILE).require_physical()
    value = dataset(decimal(logicalTypeOptions={"minimum": 10}), binary(required=True))
    result = observe(pa.schema([pa.field("amount", pa.decimal128(38,18)), pa.field("digest", pa.binary(4))]), value)
    assert result.status == "passed"
    assert {row["facet"] for row in result.obligations} == {"logicalTypeOptions/minimum", "required"}


@pytest.mark.parametrize("profile", [{}, [], True, "unregistered"])
def test_malformed_profile_refuses_through_the_supported_error(profile):
    with pytest.raises(MappingUnavailable):
        map_declaration(dataset(decimal()), profile=profile)
    with pytest.raises(JobEvidenceError, match="profile"):
        interpret_output_schema(pa.schema([pa.field("amount", pa.decimal128(38,18))]).serialize().to_pybytes(),
                                dataset(decimal()), profile=profile)
