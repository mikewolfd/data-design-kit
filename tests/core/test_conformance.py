"""Independent planted release-gate failures and retained evidence checks."""

from copy import deepcopy
from hashlib import sha256
import json
from xml.etree import ElementTree

import pytest

from ddk.conformance import FIRST_RELEASE_PROFILES, qualify_release, verify_reference_workflow
from ddk.documents import json_dumps, schema_registry, validate_document
from ddk.results import exit_code

from test_core import codes

REGISTERED = {
    "cases": [
        {"id": "CASE-TEST-CORE", "profile": "core", "tests": ["test_qualified.py::test_core"]},
        {"id": "CASE-TEST-SAVED", "profile": "plan.datafusion", "tests": ["test_qualified.py::test_saved"]},
        {"id": "CASE-TEST-FIXTURE", "profile": "test.fixtures", "tests": ["test_qualified.py::test_fixture"]},
    ],
}


def _retain(root, name, data):
    path = root / name
    path.write_bytes(data)
    return {"path": name, "sha256": sha256(data).hexdigest()}


@pytest.fixture
def release_evidence(tmp_path):
    measurement = {"name": "case wall time", "value": 42, "unit": "ms", "environment": "local independent fixture"}
    measure_file = _retain(tmp_path, "measurement.json", json.dumps(measurement).encode())
    source = _retain(tmp_path, "source-manifest.json", b'{"source":"independent synthetic evidence test"}')
    tools = {"ddk": {"version": "0.1.0"}, "python": {"version": "3.12.13"}}
    xml = ElementTree.Element("testsuite", tests="3", failures="0", skipped="0", errors="0")
    properties = ElementTree.SubElement(xml, "properties")
    ElementTree.SubElement(properties, "property", name="ddk.source.sha256", value=source["sha256"])
    ElementTree.SubElement(properties, "property", name="ddk.tools.sha256",
                           value=sha256(json_dumps(tools).encode()).hexdigest())
    for name in ("test_core", "test_saved", "test_fixture"):
        ElementTree.SubElement(xml, "testcase", classname="test_qualified", name=name)
    observed = _retain(tmp_path, "junit.xml", ElementTree.tostring(xml))
    declaration = {
        "specVersion": "0.1", "classes": ["core checker"], "profiles": ["core"],
        "summaryClaims": [{"profile": "core", "status": "passed"}],
    }
    evidence = {
        "tools": tools,
        "requestedProfiles": ["core"],
        "profileTools": {"core": ["ddk", "python"]},
        "caseResults": [{"caseId": "CASE-TEST-CORE", "profile": "core", "kind": "executed",
                         "status": "passed", "runs": ["core-run"]}],
        "unresolved": [], "fixtureExpectations": [],
        "resources": [{**measurement, "evidence": measure_file}],
        "source": source,
        "testRuns": [{"id": "core-run", "runner": "pytest", "result": observed, "tools": list(tools)}],
    }
    return declaration, evidence


def _check(claim, evidence, path, decision, diagnostic=None, **kwargs):
    result = qualify_release(claim, evidence, cases=REGISTERED, evidence_root=path, **kwargs)
    assert not validate_document(result)
    assert result["decision"] == decision
    assert exit_code(result) == {"passed": 0, "failed": 1, "incomplete": 2}[decision]
    if diagnostic is not None:
        assert diagnostic in codes(result)
    return result


def test_exact_retained_case_evidence_qualifies_only_requested_profile(release_evidence, tmp_path):
    claim, evidence = release_evidence
    result = _check(claim, evidence, tmp_path, "passed")
    assert result["coverage"]["completedProfiles"] == ["core"]
    (tmp_path / "junit.xml").write_text("changed result")
    _check(claim, evidence, tmp_path, "failed", "DOC-CONFORMANCE-EVIDENCE")


def test_core_only_claim_rejects_transformation_success_in_summary(release_evidence, tmp_path):
    claim, evidence = release_evidence
    claim["summary"] = "All transformation tests passed."
    claim["summaryClaims"].append({"profile": "test.fixtures", "status": "passed"})
    _check(claim, evidence, tmp_path, "failed", "DOC-CONFORMANCE-CLAIM")


def test_schema_that_allows_missing_output_blocks_qualification(release_evidence, tmp_path):
    claim, evidence = release_evidence
    altered = deepcopy(schema_registry()[1]["component"])
    altered["required"].remove("outputs")
    _check(claim, evidence, tmp_path, "failed", "DOC-SPECIFICATION-CONFLICT", component_schema=altered)


def test_release_rejects_reassigning_a_diagnostic_code(release_evidence, tmp_path):
    claim, evidence = release_evidence
    baseline = {"DOC-DUPLICATE-KEY": "duplicate-json-object-member"}
    evidence["diagnostics"] = [{"code": "DOC-DUPLICATE-KEY", "meaning": "invalid-utf8-input"}]
    _check(claim, evidence, tmp_path, "failed", "DOC-DIAGNOSTIC-CONFLICT", previous_diagnostics=baseline)


def test_fixture_expectation_derived_from_transformation_fails_release_gate(release_evidence, tmp_path):
    claim, evidence = release_evidence
    result = _retain(tmp_path, "result.json", b"[9, 12, 15]")
    source = _retain(tmp_path, "calculation.sql", b"select count(*) from generated_rows")
    evidence["fixtureExpectations"] = [
        {"id": "fixture-generated-expected", "origin": "implementation-under-test", "expected": result, "source": source}
    ]
    _check(claim, evidence, tmp_path, "failed", "DOC-EXPECTATION-PROVENANCE")


def test_documentation_shape_check_does_not_count_as_executed_case(release_evidence, tmp_path):
    claim, evidence = release_evidence
    evidence["caseResults"][0]["kind"] = "documentation"
    _check(claim, evidence, tmp_path, "failed", "DOC-CONFORMANCE-EVIDENCE")


def test_readme_substitution_and_invented_tool_tuple_cannot_qualify(release_evidence, tmp_path):
    claim, evidence = release_evidence
    evidence["tools"]["ddk"]["version"] = "99.0.0"
    _check(claim, evidence, tmp_path, "failed", "DOC-CONFORMANCE-EVIDENCE")
    evidence["testRuns"][0]["result"] = _retain(tmp_path, "README.md", b"All core tests passed.")
    _check(claim, evidence, tmp_path, "failed", "DOC-CONFORMANCE-EVIDENCE")


def test_unrelated_passing_junit_case_does_not_cover_maintained_case(release_evidence, tmp_path):
    claim, evidence = release_evidence
    path = tmp_path / "junit.xml"
    updated = path.read_bytes().replace(b'name="test_core"', b'name="test_unrelated"')
    evidence["testRuns"][0]["result"] = _retain(tmp_path, path.name, updated)
    _check(claim, evidence, tmp_path, "failed", "DOC-CONFORMANCE-EVIDENCE")


def test_release_bundle_requires_versions_unresolved_inventory_and_fixture_provenance(release_evidence, tmp_path):
    claim, evidence = release_evidence
    for key in ("tools", "unresolved", "fixtureExpectations"):
        evidence.pop(key)
    result = _check(claim, evidence, tmp_path, "failed", "DOC-RELEASE-EVIDENCE-MISSING")
    reason, = (item["message"] for check in result["checks"] for item in check["diagnostics"])
    assert all(key in reason for key in ("tools", "unresolved", "fixtureExpectations"))


def test_first_release_requires_observed_saved_substrait_execution(release_evidence, tmp_path):
    claim, evidence = release_evidence
    claim["firstProductRelease"] = True
    claim["profiles"] = sorted(FIRST_RELEASE_PROFILES)
    evidence["requestedProfiles"] = claim["profiles"]
    evidence["profileTools"] = {profile: ["ddk", "python"] for profile in claim["profiles"]}
    authored = _retain(tmp_path, "expected.json", b"[{\"amount\":1900}]")
    evidence["fixtureExpectations"] = [
        {"id": "authored-expectation", "origin": "independently-authored", "expected": authored, "source": authored}
    ]
    evidence["caseResults"].extend([
        {**evidence["caseResults"][0], "caseId": "CASE-TEST-SAVED", "profile": "plan.datafusion"},
        {**evidence["caseResults"][0], "caseId": "CASE-TEST-FIXTURE", "profile": "test.fixtures"},
    ])
    report = _check(claim, evidence, tmp_path, "incomplete", "ADAPTER-CAPABILITY-MISSING")
    check = next(check for check in report["checks"] if check["subject"] == "plan.datafusion")
    assert check["status"] == "not_run"
    assert "saved Substrait bytes" in check["reason"]


def test_disconnected_catalog_and_fixture_reports_do_not_qualify_workflow(tmp_path):
    fixture_report = _retain(tmp_path, "fixture.json", json.dumps({"decision": "passed"}).encode())
    catalog_report = _retain(tmp_path, "catalog-report.json", json.dumps({"decision": "passed"}).encode())
    report = verify_reference_workflow({"fixtureReport": fixture_report, "catalogReport": catalog_report},
                                       evidence_root=tmp_path)
    assert report["decision"] == "incomplete" and exit_code(report) == 2
    assert "TEST-WORKFLOW-INCOMPLETE" in codes(report)
