"""A runtime profile refusal preserves incomplete qualification."""

import pytest

from ddk.documents import validate_document
from ddk.execution import _record
from ddk.results import ReportBuilder


@pytest.mark.parametrize("code", ("unsupported_managed_build", "unsupported_managed_update"))
def test_unsupported_managed_operation_cannot_pass_or_claim_a_data_failure(code):
    builder = ReportBuilder("urn:ddk:test:managed-refusal", required_groups=("runtime.managed",))
    _record(builder, "runtime.managed", "operation", {
        "status": "failed", "error": {"code": code, "message": "The selected native profile is unsupported."},
    }, requirement="DDK-ADAPTER-013", evidence="declared")
    report = builder.build()
    assert not validate_document(report)
    assert report["decision"] == "incomplete"
    check, = report["checks"]
    assert check["status"] == "not_run"
    assert check["diagnostics"][0]["code"] == "ADAPTER-OPERATION-UNSUPPORTED"


def test_changed_update_base_preserves_native_stale_selection_refusal():
    builder = ReportBuilder("urn:ddk:test:stale-base", required_groups=("runtime.managed",))
    _record(builder, "runtime.managed", "operation", {
        "status": "failed", "error": {"code": "stale_base", "message": "The selected base has changed."},
    }, requirement="DDK-ADAPTER-013", evidence="declared")
    report = builder.build()
    assert not validate_document(report)
    assert report["decision"] == "failed"
    check, = report["checks"]
    assert check["status"] == "failed"
    assert check["diagnostics"][0]["code"] == "EXEC-SELECTION-STALE"
