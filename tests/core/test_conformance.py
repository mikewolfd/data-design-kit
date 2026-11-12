"""Independent planted release-gate failures and retained evidence checks."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
from xml.etree import ElementTree

import pytest

from ddk.conformance import FIRST_RELEASE_PROFILES, _pytest_outcomes, _selector_status, qualify_release, verify_reference_workflow
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": name, "sha256": sha256(data).hexdigest()}


@pytest.fixture
def release_evidence(tmp_path):
    measurement = {"name": "case wall time", "value": 42, "unit": "ms", "environment": "local independent fixture"}
    measure_file = _retain(tmp_path, "measurement.json", json.dumps(measurement).encode())
    files = [
        _retain(tmp_path, "test_qualified.py", b"# Independent synthetic runner cases: core, saved, fixture\n"),
        _retain(tmp_path, "tests/test_connected_workflow.py", b"# Independently authored fixture and boundary expectations\n"),
        _retain(tmp_path, "examples/commerce/tests/revenue.fixture.ddk.json", b'{"expected":{"rows":[{"amount":1900}]}}'),
    ]
    source = _retain(tmp_path, "source-manifest.json", json.dumps({"files": files}).encode())
    tools = {"ddk": {"version": "0.1.0"}, "python": {"version": "3.12.13"}}
    xml = ElementTree.Element("testsuite", tests="7", failures="0", skipped="0", errors="0")
    properties = ElementTree.SubElement(xml, "properties")
    ElementTree.SubElement(properties, "property", name="ddk.source.sha256", value=source["sha256"])
    ElementTree.SubElement(properties, "property", name="ddk.tools.sha256",
                           value=sha256(json_dumps(tools).encode()).hexdigest())
    for name in ("test_core", "test_saved", "test_fixture"):
        ElementTree.SubElement(xml, "testcase", classname="test_qualified", name=name)
    for name in ("test_connected_staged_saved_plan_quality_catalog_reader", *(
        f"test_fixture_boundary_expectations_are_independent[{scenario}]" for scenario in ("empty", "integer", "wrong-join")
    )):
        ElementTree.SubElement(xml, "testcase", classname="tests.test_connected_workflow", name=name)
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
        "testRuns": [{"id": "core-run", "runner": "pytest", "result": observed, "tools": list(tools), "sourceRoot": "."}],
    }
    return declaration, evidence


def _junit_status(root, evidence, name, tag):
    path = root / evidence["testRuns"][0]["result"]["path"]
    xml = ElementTree.fromstring(path.read_bytes())
    case = next(item for item in xml.findall("testcase") if item.get("name") == name)
    if tag:
        ElementTree.SubElement(case, tag)
    evidence["testRuns"][0]["result"] = _retain(root, path.name, ElementTree.tostring(xml))


def _runtime_expectations(root, evidence):
    source = root / "examples/commerce/tests/revenue.fixture.ddk.json"
    boundary = root / "tests/test_connected_workflow.py"
    evidence["fixtureExpectations"] = [{
        "id": identity, "origin": "independently-authored",
        "source": {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()},
        "expected": {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()},
    } for identity, path in (("commerce-revenue", source), ("commerce-boundary-expectations", boundary))]
    fixture_report = {"metadata": {"fixture": {"source": evidence["fixtureExpectations"][0]["source"]}}}
    evidence["referenceWorkflow"] = {"fixtureReport": _retain(root, "fixture-report.json", json.dumps(fixture_report).encode())}


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
    _runtime_expectations(tmp_path, evidence)
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


def test_expectations_bind_to_executed_fixture_and_inventoried_test_sources(release_evidence, tmp_path):
    claim, evidence = release_evidence
    _runtime_expectations(tmp_path, evidence)
    result = _check(claim, evidence, tmp_path, "passed")
    assert {item["id"] for item in result["metadata"]["expectationBindings"]} == {
        "commerce-revenue", "commerce-boundary-expectations",
    }


@pytest.mark.parametrize("replace", ["source", "expected"])
def test_unrelated_admitted_expectation_cannot_replace_executed_bytes(release_evidence, tmp_path, replace):
    claim, evidence = release_evidence
    _runtime_expectations(tmp_path, evidence)
    evidence["fixtureExpectations"][0][replace] = _retain(tmp_path, "unrelated.json", b"[1900]")
    _check(claim, evidence, tmp_path, "failed", "DOC-EXPECTATION-PROVENANCE")


def test_executed_fixture_source_must_match_expectation_reference(release_evidence, tmp_path):
    claim, evidence = release_evidence
    _runtime_expectations(tmp_path, evidence)
    fixture_report = {"metadata": {"fixture": {"source": evidence["fixtureExpectations"][1]["source"]}}}
    evidence["referenceWorkflow"]["fixtureReport"] = _retain(tmp_path, "fixture-report.json", json.dumps(fixture_report).encode())
    _check(claim, evidence, tmp_path, "failed", "DOC-EXPECTATION-PROVENANCE")


def test_changed_expectation_source_cannot_reuse_old_runner_identity(release_evidence, tmp_path):
    claim, evidence = release_evidence
    _runtime_expectations(tmp_path, evidence)
    changed = _retain(tmp_path, "tests/test_connected_workflow.py", b"# Changed expected business values\n")
    evidence["fixtureExpectations"][1].update(source=changed, expected=changed)
    _check(claim, evidence, tmp_path, "failed", "DOC-EXPECTATION-PROVENANCE")


def test_changed_test_source_cannot_reuse_retained_passing_nodes(release_evidence, tmp_path):
    claim, evidence = release_evidence
    (tmp_path / "test_qualified.py").write_text("# Assertions removed after the source capture\n")
    _check(claim, evidence, tmp_path, "failed", "DOC-CONFORMANCE-EVIDENCE")


@pytest.mark.parametrize(("status", "tag", "decision"), [
    ("failed", "failure", "failed"), ("unknown", None, "incomplete"), ("not_run", "skipped", "incomplete"),
])
def test_release_retains_required_case_outcomes(release_evidence, tmp_path, status, tag, decision):
    claim, evidence = release_evidence
    evidence["caseResults"][0].update(status=status, reason="Recorded native or runner outcome")
    _junit_status(tmp_path, evidence, "test_core", tag)
    report = _check(claim, evidence, tmp_path, decision)
    case = next(item for item in report["checks"] if item["subject"] == "core/CASE-TEST-CORE")
    assert case["status"] == status and case["required"]
    if status in {"unknown", "not_run"}:
        assert case["reason"] == "Recorded native or runner outcome"


def test_optional_failed_case_stays_visible_without_gating_core(release_evidence, tmp_path):
    claim, evidence = release_evidence
    evidence["requestedProfiles"].append("plan.datafusion")
    evidence["profileTools"]["plan.datafusion"] = ["ddk", "python"]
    evidence["caseResults"].append({"caseId": "CASE-TEST-SAVED", "profile": "plan.datafusion", "kind": "executed",
                                    "status": "failed", "runs": ["core-run"]})
    _junit_status(tmp_path, evidence, "test_saved", "failure")
    report = _check(claim, evidence, tmp_path, "passed")
    case = next(item for item in report["checks"] if item["subject"] == "plan.datafusion/CASE-TEST-SAVED")
    assert case["status"] == "failed" and not case["required"]


def test_reported_uncertainty_cannot_hide_an_observed_runner_failure(release_evidence, tmp_path):
    claim, evidence = release_evidence
    evidence["caseResults"][0].update(status="unknown", reason="Caller did not classify its result")
    _junit_status(tmp_path, evidence, "test_core", "error")
    report = _check(claim, evidence, tmp_path, "failed")
    assert any(item["subject"] == "core/CASE-TEST-CORE" and item["status"] == "failed" for item in report["checks"])


def test_skipped_parameter_is_not_a_passing_expectation_test(release_evidence, tmp_path):
    claim, evidence = release_evidence
    _runtime_expectations(tmp_path, evidence)
    _junit_status(tmp_path, evidence, "test_fixture_boundary_expectations_are_independent[wrong-join]", "skipped")
    _check(claim, evidence, tmp_path, "failed", "DOC-EXPECTATION-PROVENANCE")


@pytest.mark.parametrize(("tag", "status"), [(None, "passed"), ("failure", "failed"), ("error", "failed"), ("skipped", "not_run")])
def test_retained_junit_keeps_observed_classification(release_evidence, tmp_path, tag, status):
    _, evidence = release_evidence
    _junit_status(tmp_path, evidence, "test_core", tag)
    digest = sha256(json_dumps(evidence["tools"]).encode()).hexdigest()
    outcomes = _pytest_outcomes(evidence["testRuns"][0]["result"], tmp_path, evidence["source"]["sha256"], digest)
    assert outcomes[("test_qualified", "test_core")] == status
    assert _selector_status("test_qualified.py::test_core", outcomes) == status


def test_missing_runner_source_root_cannot_qualify(release_evidence, tmp_path):
    claim, evidence = release_evidence
    evidence["testRuns"][0].pop("sourceRoot")
    _check(claim, evidence, tmp_path, "failed", "DOC-CONFORMANCE-EVIDENCE")


def test_not_run_case_needs_no_invented_execution(release_evidence, tmp_path):
    claim, evidence = release_evidence
    evidence["caseResults"][0].update(status="not_run", reason="No supported native request was submitted")
    evidence["caseResults"][0].pop("runs")
    report = _check(claim, evidence, tmp_path, "incomplete")
    check = next(item for item in report["checks"] if item["subject"] == "core/CASE-TEST-CORE")
    assert check["status"] == "not_run" and check["evidence"] == "declared"


def test_relocated_release_preserves_case_and_expectation_source_bindings(release_evidence, tmp_path):
    claim, evidence = release_evidence
    _runtime_expectations(tmp_path, evidence)
    evidence["testRuns"][0]["sourceRoot"] = str(tmp_path)
    with tempfile.TemporaryDirectory(prefix="relocated-release-", dir=tmp_path.parent) as directory:
        moved = Path(directory)
        shutil.copytree(tmp_path, moved, dirs_exist_ok=True)
        shutil.rmtree(tmp_path)
        result = _check(claim, evidence, moved, "passed", captured_root=tmp_path)
        assert len(result["metadata"]["expectationBindings"]) == 2


def test_graph_and_rml_profiles_qualify_independently_of_base_catalog(release_evidence, tmp_path):
    from ddk.conformance import PROFILES
    from ddk.documents import REPOSITORY, read_json

    assert {"catalog.graph", "catalog.rml"} <= PROFILES
    registry = read_json(REPOSITORY / "conformance" / "cases.json").value
    by_id = {case["id"]: case["profile"] for case in registry["cases"]}
    graph_cases = {cid for cid in by_id if cid.startswith("CASE-CATALOG-013-")}
    rml_cases = {cid for cid in by_id if cid.startswith("CASE-CATALOG-014-")}
    assert graph_cases and all(by_id[cid] == "catalog.graph" for cid in graph_cases)
    assert rml_cases and all(by_id[cid] == "catalog.rml" for cid in rml_cases)

    # Qualify catalog.graph and catalog.rml explicitly while verify base `catalog` does not require them.
    custom_cases = {
        "cases": [
            *REGISTERED["cases"],
            {"id": "CASE-TEST-CATALOG", "profile": "catalog", "tests": ["test_qualified.py::test_core"]},
            {"id": "CASE-TEST-GRAPH", "profile": "catalog.graph", "tests": ["test_qualified.py::test_saved"]},
            {"id": "CASE-TEST-RML", "profile": "catalog.rml", "tests": ["test_qualified.py::test_fixture"]},
        ],
    }
    claim, evidence = release_evidence
    claim["profiles"] = ["core", "catalog"]
    claim["summaryClaims"] = [{"profile": "core", "status": "passed"}, {"profile": "catalog", "status": "passed"}]
    evidence["requestedProfiles"] = ["core", "catalog"]
    evidence["profileTools"].update({"catalog": ["ddk", "python"]})
    evidence["caseResults"].append({"caseId": "CASE-TEST-CATALOG", "profile": "catalog", "kind": "executed",
                                    "status": "passed", "runs": ["core-run"]})
    # Even without CASE-TEST-GRAPH or CASE-TEST-RML results, base `catalog` qualifies cleanly.
    base_result = qualify_release(claim, evidence, cases=custom_cases, evidence_root=tmp_path)
    assert base_result["decision"] == "passed"
    assert base_result["coverage"]["completedProfiles"] == ["catalog", "core"]

    # Claiming catalog.graph and catalog.rml succeeds when their cases pass.
    claim["profiles"] = ["core", "catalog", "catalog.graph", "catalog.rml"]
    claim["summaryClaims"].extend([
        {"profile": "catalog.graph", "status": "passed"},
        {"profile": "catalog.rml", "status": "passed"},
    ])
    evidence["requestedProfiles"] = list(claim["profiles"])
    evidence["profileTools"].update({"catalog.graph": ["ddk", "python"], "catalog.rml": ["ddk", "python"]})
    evidence["caseResults"].extend([
        {"caseId": "CASE-TEST-GRAPH", "profile": "catalog.graph", "kind": "executed",
         "status": "passed", "runs": ["core-run"]},
        {"caseId": "CASE-TEST-RML", "profile": "catalog.rml", "kind": "executed",
         "status": "passed", "runs": ["core-run"]},
    ])
    full_result = qualify_release(claim, evidence, cases=custom_cases, evidence_root=tmp_path)
    assert full_result["decision"] == "passed"
    assert set(full_result["coverage"]["completedProfiles"]) == {"core", "catalog", "catalog.graph", "catalog.rml"}

