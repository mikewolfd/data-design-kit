"""Independently specified comparison and typed-literal failure cases."""

from decimal import Decimal
from hashlib import sha256
import pytest

from ddk.arrow_mapping import MappingUnavailable, typed_rows
from ddk.documents import read_json
from ddk.fixtures import compare_rows
from ddk.execution import _record, _schema_result
from ddk.results import ReportBuilder, exit_code


def test_duplicate_rows_and_boolean_identity(tmp_path):
    comparison = compare_rows([{"n": 1}, {"n": 1}], [{"n": 1}, {"n": 2}])
    assert comparison["status"] == "failed"
    evidence = tmp_path / "independent-rows.json"
    evidence.write_text('{"expected":[{"n":1},{"n":1}],"observed":[{"n":1},{"n":2}]}')
    comparison["evidence"] = {"path": str(evidence), "sha256": sha256(evidence.read_bytes()).hexdigest()}
    builder = ReportBuilder("urn:test:duplicate-result", required_groups=("test.fixtures",))
    _record(builder, "test.fixtures", "duplicate-result", comparison, requirement="DDK-ADAPTER-007")
    report = builder.build()
    assert report["decision"] == "failed" and exit_code(report) == 1
    assert report["checks"][-1]["diagnostics"][0]["code"] == "EXEC-FIXTURE-MISMATCH"
    assert compare_rows([{"n": False}], [{"n": 0}])["status"] == "failed"
    assert compare_rows([{}], [{"n": None}])["status"] == "failed"
    assert compare_rows([], [])["status"] == "passed"


def test_tolerance_requires_a_complete_multiset_assignment():
    # Greedy pairing 1.0->1.1 leaves 1.2 unmatched; 1.0->0.9 is the valid pairing.
    comparison = {"absoluteTolerance": Decimal("0.11")}
    assert compare_rows([{"n": 1.0}, {"n": 1.2}], [{"n": 1.1}, {"n": 0.9}], comparison)["status"] == "passed"
    assert compare_rows([{"n": 1.0}, {"n": 1.2}], [{"n": 1.1}, {"n": 4}], comparison)["status"] == "failed"
    assert compare_rows([{"n": 1}, {"n": 2}], [{"n": 2}, {"n": 1}], {"rows": "ordered"})["status"] == "failed"


def test_exact_float_mapping_and_declared_type_errors():
    dataset = {"properties": [{"name": "n", "logicalType": "number", "required": True}]}
    assert typed_rows([{"n": Decimal("0.5")}], dataset) == [{"n": 0.5}]
    for value in (Decimal("0.1"), 2**53 + 1):
        with pytest.raises(MappingUnavailable):
            typed_rows([{"n": value}], dataset)
    for value in (None, True, "0.5"):
        with pytest.raises(ValueError):
            typed_rows([{"n": value}], dataset)


def test_primitive_plan_schema_does_not_establish_decimal_precision():
    expected = {"properties": [{"name": "amount", "logicalType": "number", "unique": True,
                                 "logicalTypeOptions": {"precision": 18, "scale": 4}}]}
    observed = {"fields": [{"name": "amount", "data_type": "Float64", "nullable": True}]}
    mapping = _schema_result(expected, observed)
    assert mapping["status"] == "unknown"
    builder = ReportBuilder("urn:test:primitive-plan", required_groups=("plan.output",))
    _record(builder, "plan.output", "amount", mapping, requirement="DDK-ADAPTER-002", evidence="inferred")
    report = builder.build()
    assert report["decision"] == "incomplete" and exit_code(report) == 2
    assert report["checks"][-1]["diagnostics"][0]["code"] == "ADAPTER-MAPPING-INCOMPLETE"
