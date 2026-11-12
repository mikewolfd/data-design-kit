"""Offline release-claim checks over explicitly supplied evidence."""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
from math import isfinite
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from .documents import DocumentError, REPOSITORY, ResourceLimit, json_dumps, read_json, schema_registry, schema_validator, validate_document
from .evidence_locations import EvidenceDirectory, evidence_directory, evidence_path
from .interfaces import json_equal
from .locks import evidence_sha256, tool_identities
from .results import ReportBuilder, diagnostic

PRODUCT_CLASSES = {
    "document producer", "core checker", "impact analyzer", "catalog producer", "adapter", "report consumer",
}
FIRST_RELEASE_PROFILES = {
    "core", "impact", "catalog", "catalog.dcat", "lineage.openlineage", "odcs-cli", "plan.docspec-sql",
    "execute.docspec-job", "plan.datafusion", "test.fixtures",
}
PROFILES = FIRST_RELEASE_PROFILES | {
    "catalog.graph", "catalog.rml", "files.frictionless", "ingest.dlt", "runtime.docspec-managed",
    "plan.substrait-validator", "test.portability",
}
RELEASE_GROUPS = ("release.claims", "release.evidence", "release.profiles")
CASE_STATES = {"passed", "failed", "unknown", "not_run"}
ORIGINS = {"specification", "public-standard", "independently-authored"}
REFERENCE = {"path", "sha256"}
REQUIRED_EVIDENCE = {
    "tools": dict,
    "requestedProfiles": list,
    "profileTools": dict,
    "caseResults": list,
    "unresolved": list,
    "fixtureExpectations": list,
    "resources": list,
    "source": dict,
    "testRuns": list,
}
PROFILE_INTEGRATION_CASES = {
    "odcs-cli": {
        "CASE-ADAPTER-001", "CASE-ADAPTER-002", "CASE-ADAPTER-003", "CASE-GITHUB-CLI-INHERITANCE",
        "CASE-GITHUB-ODCS-OPERATORS",
    },
    "files.frictionless": {"CASE-ADAPTER-001", "CASE-ADAPTER-002", "CASE-GITHUB-FRICTIONLESS-KEYS",
                           "CASE-GITHUB-FRICTIONLESS-ERRORS"},
    "ingest.dlt": {"CASE-ADAPTER-001", "CASE-ADAPTER-002", "CASE-ADAPTER-004"},
    "plan.docspec-sql": {"CASE-ADAPTER-001", "CASE-ADAPTER-002", "CASE-ADAPTER-008", "CASE-ADAPTER-009"},
    "execute.docspec-job": {"CASE-ADAPTER-001", "CASE-ADAPTER-008", "CASE-ADAPTER-010", "CASE-SAFE-004"},
    "plan.datafusion": {"CASE-ADAPTER-001", "CASE-ADAPTER-002", "CASE-ADAPTER-005", "CASE-ADAPTER-008",
                        "CASE-ADAPTER-009", "CASE-ADAPTER-010", "CASE-BUSINESS-REVENUE"},
    "plan.substrait-validator": {"CASE-ADAPTER-001", "CASE-ADAPTER-006", "CASE-GITHUB-VALIDATOR-TUPLE"},
    "test.fixtures": {"CASE-ADAPTER-007", "CASE-ADAPTER-010", "CASE-BUSINESS-REVENUE", "CASE-SAFE-004"},
    "test.portability": {"CASE-ADAPTER-007", "CASE-PORTABILITY-SAME-BYTES"},
    "runtime.docspec-managed": {
        "CASE-ADAPTER-001", "CASE-NATIVE-EXACT-READ", "CASE-NATIVE-FIELD-IDENTITY", "CASE-NATIVE-DIGEST-SCHEME",
        "CASE-NATIVE-UNAVAILABLE", "CASE-NATIVE-QUALITY-BRIDGE", "CASE-REUSE-ENDPOINT", "CASE-REUSE-SEMANTIC-CHANGE",
    },
}
# The initial release demonstrates these independently authored expectations.
# This mapping binds their source files to maintained tests; an origin label
# alone cannot establish that a runner used an expectation.
EXPECTATION_BINDINGS = {
    "commerce-revenue": {
        "sourcePath": "examples/commerce/tests/revenue.fixture.ddk.json",
        "tests": ["tests/test_connected_workflow.py::test_connected_staged_saved_plan_quality_catalog_reader"],
        "fixtureReport": True,
    },
    "commerce-boundary-expectations": {
        "sourcePath": "tests/test_connected_workflow.py",
        "tests": ["tests/test_connected_workflow.py::test_fixture_boundary_expectations_are_independent"],
        "fixtureReport": False,
    },
}


def _emit(report, requirement, group, subject, status, code=None, message=None, pointer=""):
    report.add(requirement, group, subject, status, reason=message if status in {"unknown", "not_run"} else None,
               diagnostics=([diagnostic(code, message, path="<release-evidence>", pointer=pointer,
                                        severity="warning" if status in {"unknown", "not_run"} else "error")]
                            if code else []))


def _names(value):
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value) and len(value) == len(set(value))


def _claim(report, claim):
    if not isinstance(claim, dict):
        claim = {}
    classes, profiles = claim.get("classes"), claim.get("profiles")
    summary = claim.get("summaryClaims", [])
    valid = (
        claim.get("specVersion") == "0.1"
        and _names(classes) and bool(classes) and set(classes) <= PRODUCT_CLASSES
        and _names(profiles) and bool(profiles) and set(profiles) <= PROFILES
        and isinstance(claim.get("firstProductRelease", False), bool)
        and ("core checker" not in classes or "core" in profiles)
        and (not claim.get("summary") or bool(summary))
        and isinstance(summary, list)
        and all(isinstance(item, dict) and item.get("profile") in profiles and item.get("status") in CASE_STATES
                for item in summary)
    )
    _emit(report, "DDK-CONF-001", "release.claims", "profile-claims", "passed" if valid else "failed",
          None if valid else "DOC-CONFORMANCE-CLAIM",
          None if valid else "Release claims must identify supported product classes and profiles. Summary claims must stay within that scope.")
    return set(profiles) if valid else set()


def _specification_conflict(report, component_schema):
    # The expectation is DDK-CALL-001: a component declares at least one output.
    required_shape = {
        "specVersion": "0.1", "kind": "component", "id": "urn:ddk:conformance:missing-output",
        "version": "1.0.0", "role": "reader", "inputs": {},
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    schema = schema_registry()[1]["component"] if component_schema is None else component_schema
    validator = schema_validator(schema)
    contradictory = any(validator.is_valid(candidate) for candidate in (required_shape, {**required_shape, "outputs": {}}))
    _emit(report, "DDK-CONF-004", "release.claims", "component-output-shape", "failed" if contradictory else "passed",
          "DOC-SPECIFICATION-CONFLICT" if contradictory else None,
          "The component schema accepts a declaration with no outputs, which DDK-CALL-001 forbids." if contradictory else None)


def _diagnostic_assignments(report, previous, current):
    if previous is None and current is None:
        return
    seen = dict(previous or {})
    valid = isinstance(current, list)
    for item in current if valid else ():
        code = item.get("code") if isinstance(item, dict) else None
        meaning = item.get("meaning") if isinstance(item, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z]+-[A-Z0-9-]+", code) or not isinstance(meaning, str) or not meaning:
            valid = False
            break
        if code in seen and seen[code] != meaning:
            valid = False
            break
        seen[code] = meaning
    _emit(report, "DDK-RESULT-005", "release.claims", "diagnostic-assignments", "passed" if valid else "failed",
          None if valid else "DOC-DIAGNOSTIC-CONFLICT",
          None if valid else "A diagnostic code is reassigned or lacks a stable meaning.")


def _reference(value):
    return (
        isinstance(value, dict) and REFERENCE <= value.keys()
        and isinstance(value["path"], str) and bool(value["path"])
        and isinstance(value["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
    )


def _admitted(reference, root, verified):
    if not _reference(reference) or root is None:
        return False
    key = (reference["path"], reference["sha256"])
    if key not in verified:
        try:
            path = evidence_path(root, reference["path"])
            verified[key] = path.is_relative_to(evidence_directory(root)) and evidence_sha256(path) == reference["sha256"]
        except (DocumentError, OSError, ResourceLimit, RuntimeError, ValueError):
            verified[key] = False
    return verified[key]


def _evidence_shape(evidence, profiles):
    if not isinstance(evidence, dict):
        return list(REQUIRED_EVIDENCE)
    missing = [key for key, kind in REQUIRED_EVIDENCE.items() if not isinstance(evidence.get(key), kind)]
    if missing:
        return missing
    tools = evidence["tools"]
    if not tools or any(
        not isinstance(tool, dict) or not isinstance(tool.get("version"), str) or not tool["version"]
        or ("commit" in tool and not re.fullmatch(r"[a-f0-9]{40}", str(tool["commit"])))
        or ("distributionSha256" in tool and not re.fullmatch(r"[a-f0-9]{64}", str(tool["distributionSha256"])))
        or ("commit" in tool and "distributionSha256" not in tool)
        or (re.search(r"(?:dev|unreleased)", tool["version"], re.IGNORECASE)
            and not {"commit", "distributionSha256"} <= tool.keys())
        for tool in tools.values()
    ):
        missing.append("tools")
    if not _names(evidence["requestedProfiles"]) or not profiles <= set(evidence["requestedProfiles"]):
        missing.append("requestedProfiles")
    for profile in sorted(profiles):
        dependencies = evidence["profileTools"].get(profile)
        if not _names(dependencies) or not dependencies or not set(dependencies) <= tools.keys():
            missing.append(f"profileTools/{profile}")
    if any(not isinstance(item, dict) or item.get("status") not in {"unknown", "not_run"}
           or not isinstance(item.get("reason"), str) or not item["reason"] for item in evidence["unresolved"]):
        missing.append("unresolved")
    if not evidence["resources"] or any(
        not isinstance(item, dict) or not all(item.get(key) for key in ("name", "unit", "environment"))
        or isinstance(item.get("value"), bool) or not isinstance(item.get("value"), (int, float, Decimal))
        or isinstance(item["value"], float) and not isfinite(item["value"])
        or isinstance(item["value"], Decimal) and not item["value"].is_finite()
        or not _reference(item.get("evidence"))
        for item in evidence["resources"]
    ):
        missing.append("resources")
    if not _reference(evidence["source"]):
        missing.append("source")
    return missing


def _run_source(reference, relative, run, root, verified):
    """Match retained bytes to the source path supplied to the admitted runner."""
    if not _reference(reference) or len(run) < 4 or root is None:
        return False
    source_root, files = run[2:4]
    try:
        return (
            files.get(relative) == reference["sha256"]
            and evidence_path(root, reference["path"]) == (source_root / relative).resolve()
            and _admitted(reference, root, verified)
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _selector_source(selector, run, root, verified):
    relative = selector.partition("::")[0]
    return _run_source({"path": str(run[2] / relative), "sha256": run[3].get(relative)},
                       relative, run, root, verified)


def _expectations(report, evidence, root, verified, required, run_results):
    fixtures = evidence["fixtureExpectations"]
    invalid = []
    seen = set()
    pending = False
    bindings = []
    workflow = _fixture_workflow(evidence.get("referenceWorkflow"), root)
    for index, fixture in enumerate(fixtures):
        binding = EXPECTATION_BINDINGS.get(fixture.get("id")) if isinstance(fixture, dict) else None
        if not binding or fixture["id"] in seen or fixture.get("origin") not in ORIGINS or not all(
            _reference(fixture.get(key)) for key in ("expected", "source")
        ):
            invalid.append(index)
            continue
        seen.add(fixture["id"])
        if root is None:
            pending = True
            continue
        matching = [run for run in run_results.values() if all(
            _run_source(fixture[key], binding["sourcePath"], run, root, verified) for key in ("expected", "source")
        ) and all(_selector_passed(selector, run[1]) and _selector_source(selector, run, root, verified)
                  for selector in binding["tests"])]
        if not matching:
            invalid.append(index)
            continue
        if binding["fixtureReport"]:
            metadata = workflow.get("metadata") if isinstance(workflow, dict) else None
            fixture_metadata = metadata.get("fixture") if isinstance(metadata, dict) else None
            actual = fixture_metadata.get("source") if isinstance(fixture_metadata, dict) else None
            if actual is None:
                pending = True
                continue
            if not any(_run_source(actual, binding["sourcePath"], run, root, verified) for run in matching):
                invalid.append(index)
                continue
        bindings.append({"id": fixture["id"], "origin": fixture["origin"],
                         "sourcePath": binding["sourcePath"], "sha256": fixture["source"]["sha256"],
                         "tests": binding["tests"]})
    if invalid:
        _emit(report, "DDK-TEST-001", "release.evidence", "fixture-expectations", "failed",
              "DOC-EXPECTATION-PROVENANCE", "Expectation references must match the admitted runner sources, maintained tests, and executed fixture source. Authorship remains a named assertion.",
              f"/fixtureExpectations/{invalid[0]}")
    elif required and seen != EXPECTATION_BINDINGS.keys():
        _emit(report, "DDK-TEST-003", "release.evidence", "fixture-expectations", "failed",
              "DOC-RELEASE-EVIDENCE-MISSING", "The maintained fixture and boundary expectation sources are required for these release profiles.", "/fixtureExpectations")
    elif pending:
        _emit(report, "DDK-TEST-001", "release.evidence", "fixture-expectations", "not_run",
              "DOC-RELEASE-EVIDENCE-MISSING", "An admitted runner and executed fixture report are required to bind expectation sources.")
    else:
        _emit(report, "DDK-TEST-001", "release.evidence", "fixture-expectations", "passed")
        if bindings:
            report.metadata["expectationBindings"] = bindings


def _catalog(cases):
    directory = REPOSITORY / "conformance"
    data = read_json(directory / "cases.json").value if cases is None else cases
    registry = {row["id"]: dict(row) for row in data["cases"]}
    if cases is None:
        for name in ("core-evidence.json", "catalog-evidence.json", "runtime-evidence.json", "integration-evidence.json"):
            if not (directory / name).is_file():
                continue
            for row in read_json(directory / name).value["cases"]:
                if row["id"] in registry and (row.get("coverage") == "exercised" or row.get("status") == "verified"):
                    record = registry[row["id"]]
                    record["tests"] = sorted(set(record.get("tests", ())) | set(row.get("tests", ())))
    return registry


def _pytest_outcomes(reference, root, source_digest, tools_digest):
    if not _reference(reference) or root is None:
        return None
    try:
        path = evidence_path(root, reference["path"])
        if not path.is_relative_to(evidence_directory(root)) or not path.is_file():
            return None
        with path.open("rb") as stream:
            data = stream.read((8 << 20) + 1)
        if len(data) > 8 << 20 or sha256(data).hexdigest() != reference["sha256"] or b"<!DOCTYPE" in data:
            return None
        document = ElementTree.fromstring(data)
    except (OSError, RuntimeError, ValueError, ElementTree.ParseError):
        return None
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if not suites:
        return None
    outcomes = {}
    for suite in suites:
        properties = {item.get("name"): item.get("value") for item in suite.findall("properties/property")}
        if properties.get("ddk.source.sha256") != source_digest or properties.get("ddk.tools.sha256") != tools_digest:
            return None
        children = suite.findall("testcase")
        if suite.get("tests") != str(len(children)):
            return None
        for case in children:
            key = (case.get("classname"), case.get("name"))
            if None in key or key in outcomes:
                return None
            outcomes[key] = (
                "failed" if any(child.tag in {"failure", "error"} for child in case)
                else "not_run" if case.find("skipped") is not None else "passed"
            )
    return outcomes


def _source_files(reference, root):
    document = _read_reference(reference, root)
    if document is None or not isinstance(document.value, dict):
        return None
    rows = document.value.get("files")
    if not isinstance(rows, list) or not rows:
        return None
    files = {}
    for row in rows:
        if not _reference(row):
            return None
        path = Path(row["path"])
        if path.is_absolute() or path.as_posix() != row["path"] or ".." in path.parts or row["path"] in files:
            return None
        files[row["path"]] = row["sha256"]
    return files


def _runner_results(report, evidence, root, verified):
    files = _source_files(evidence["source"], root)
    if files is None:
        _emit(report, "DDK-TEST-003", "release.evidence", "source-identity", "not_run" if root is None else "failed",
              "DOC-RELEASE-EVIDENCE-MISSING", "An admitted source inventory with exact relative file identities is required to bind test outcomes.")
        return {}
    results = {}
    seen = set()
    for index, run in enumerate(evidence["testRuns"]):
        outcomes = None
        source_root = None
        if (isinstance(run, dict) and isinstance(run.get("id"), str) and run["id"] and run["id"] not in seen
                and run.get("runner") == "pytest" and _names(run.get("tools")) and run["tools"]
                and set(run["tools"]) <= evidence["tools"].keys()
                and isinstance(run.get("sourceRoot"), str) and run["sourceRoot"]):
            seen.add(run["id"])
            tools = {name: evidence["tools"][name] for name in run["tools"]}
            digest = sha256(json_dumps(tools).encode()).hexdigest()
            try:
                source_root = evidence_path(root, run["sourceRoot"])
                if source_root.is_relative_to(evidence_directory(root)) and source_root.is_dir():
                    outcomes = _pytest_outcomes(run.get("result"), root, evidence["source"]["sha256"], digest)
            except (OSError, RuntimeError, ValueError):
                pass
        if outcomes is None:
            _emit(report, "DDK-TEST-002", "release.evidence", f"test-run/{index}", "failed",
                  "DOC-CONFORMANCE-EVIDENCE", "Test evidence must identify its retained source root and a pytest JUnit report bound to exact source and tool identities.",
                  f"/testRuns/{index}")
        else:
            results[run["id"]] = (set(run["tools"]), outcomes, source_root, files)
    return results


def _selector_status(selector, outcomes):
    path, sep, name = selector.partition("::")
    if not sep or not path.endswith(".py"):
        return None
    classname = ".".join((*Path(path[:-3]).parts, *name.split("::")[:-1]))
    function = name.split("::")[-1]
    matching = [status for (module, test), status in outcomes.items()
                if module == classname and (test == function or ("[" not in function and test.startswith(f"{function}[")))]
    if not matching:
        return None
    return next((status for status in ("failed", "unknown", "not_run") if status in matching), "passed")


def _selector_passed(selector, outcomes):
    return _selector_status(selector, outcomes) == "passed"


def _required_cases(profile, registry):
    return ({case for case, record in registry.items() if record["profile"] == profile}
            | (PROFILE_INTEGRATION_CASES.get(profile, set()) & registry.keys()))


def _observed_case(tests, dependencies, runs, run_results):
    statuses = []
    for selector in tests:
        observations = [_selector_status(selector, run_results[run][1]) for run in runs
                        if dependencies <= run_results[run][0]]
        observations = [status for status in observations if status is not None]
        statuses.append(next((status for status in ("failed", "unknown", "not_run") if status in observations),
                             "passed" if observations else "not_run"))
    return next((status for status in ("failed", "unknown", "not_run") if status in statuses),
                "passed" if statuses else "not_run")


def _case_observations(report, evidence, registry, profiles, run_results, root, verified):
    passed = defaultdict(set)
    seen = set()
    for index, result in enumerate(evidence["caseResults"]):
        subject = f"case-result/{index}"
        if not isinstance(result, dict):
            result = {}
        case, profile = result.get("caseId"), result.get("profile")
        valid = (
            isinstance(case, str) and case in registry
            and isinstance(profile, str) and profile in evidence["requestedProfiles"]
            and registry[case]["profile"] in {profile, "integration", "product-release"}
            and (profile, case) not in seen
            and result.get("status") in CASE_STATES
        )
        status = result.get("status")
        if not valid or (status in {"passed", "failed", "unknown"} and result.get("kind") != "executed") or (
            status in {"unknown", "not_run"} and (not isinstance(result.get("reason"), str) or not result["reason"])
        ):
            _emit(report, "DDK-TEST-002", "release.evidence", subject, "failed", "DOC-CONFORMANCE-EVIDENCE",
                  "A claimed case needs distinct executed evidence matching the registered case and requested profile.",
                  f"/caseResults/{index}")
            continue
        seen.add((profile, case))
        runs = result.get("runs")
        tests = registry[case].get("tests", ())
        dependencies = set(evidence["profileTools"].get(profile, ()))
        runs = [] if runs is None and status == "not_run" else runs
        valid_runs = _names(runs) and all(run in run_results for run in runs)
        source_matches = valid_runs and all(
            _selector_source(selector, run_results[run], root, verified)
            for selector in tests for run in runs
            if dependencies <= run_results[run][0] and _selector_status(selector, run_results[run][1]) is not None
        )
        observed = _observed_case(tests, dependencies, runs, run_results) if valid_runs else None
        if (not valid_runs or status != "not_run" and (not tests or not runs or not source_matches)
                or status == "passed" and observed != "passed"
                or status == "failed" and observed != "failed"):
            _emit(report, "DDK-TEST-002", "release.evidence", subject, "failed", "DOC-CONFORMANCE-EVIDENCE",
                  "Case outcomes must match maintained pytest nodes, their inventoried source bytes, and the declared tool tuple.",
                  f"/caseResults/{index}/runs")
        else:
            # A reported uncertainty cannot conceal an observed runner failure.
            status = "failed" if observed == "failed" else status
            required = profile in profiles and case in _required_cases(profile, registry)
            records = [{"kind": "native-report", **run["result"]} for run in evidence["testRuns"] if run["id"] in runs]
            reason = result.get("reason") if status in {"unknown", "not_run"} else None
            report.add("DDK-TEST-002", "release.evidence", f"{profile}/{case}", status, required=required,
                       evidence="executed" if records else "declared", reason=reason, evidence_records=records)
            if status == "passed":
                passed[profile].add(case)
    return passed


def _read_reference(reference, root):
    if not _reference(reference) or root is None:
        return None
    try:
        path = evidence_path(root, reference["path"])
        if path.is_relative_to(evidence_directory(root)):
            document = read_json(path)
            if document.sha256 == reference["sha256"]:
                return document
    except (DocumentError, OSError, ResourceLimit, RuntimeError, ValueError):
        return None
    return None


def _fixture_workflow(workflow, root):
    if isinstance(workflow, dict) and "fixtureReport" in workflow:
        workflow = workflow["fixtureReport"]
    if _reference(workflow):
        document = _read_reference(workflow, root)
        return document.value if document is not None else None
    return workflow


def _measurement_verified(measurement, root):
    document = _read_reference(measurement["evidence"], root)
    if document is None or not isinstance(document.value, dict):
        return False
    fields = ("name", "value", "unit", "environment")
    expected = {key: measurement[key] for key in fields}
    rows = document.value.get("measurements", [document.value])
    return isinstance(rows, list) and any(
        isinstance(row, dict) and json_equal(expected, {key: row.get(key) for key in fields}) for row in rows
    )


def _saved_substrait(workflow, root, verified):
    try:
        workflow = _fixture_workflow(workflow, root)
        if not isinstance(workflow, dict) or validate_document(workflow, "report"):
            return False
        compared = any(
            check["group"] == "test.fixtures" and check["subject"] == "substrait"
            and check["evidence"] == "executed" and check["status"] == "passed"
            and all(_admitted(ref, root, verified) for ref in check.get("evidenceRecords", []))
            for check in workflow["checks"]
        )
        fixture = workflow.get("metadata", {}).get("fixture", {})
        prepared = fixture.get("preparation", {}).get("result", {}).get("substrait", {})
        run = fixture.get("executions", {}).get("substrait", {})
        native = _read_reference(run.get("evidence"), root)
        if native is None or native.value.get("status") != "succeeded":
            return False
        saved = [row for row in native.value.get("inputs", []) if row.get("format") == "substrait"]
        return (
            compared and run.get("status") == "succeeded"
            and len(saved) == 1 and _reference(saved[0]) and _reference(prepared) and saved[0]["sha256"] == prepared["sha256"]
            and _admitted(saved[0], root, verified) and _admitted(prepared, root, verified)
        )
    except (AttributeError, DocumentError, KeyError, TypeError, ValueError):
        return False


def _pass(report, group):
    return any(check["group"] == group and check["status"] == "passed" for check in report["checks"])


def _exact_file(version, file):
    reference = version.get("reference", {})
    if reference.get("scheme") != "urn:ddk:version:local-file-sha256":
        return False
    value = reference.get("value")
    if not isinstance(value, dict) or value.get("sha256") != file["sha256"]:
        return False
    location = urlsplit(value.get("location", ""))
    return location.scheme == "file" and not location.netloc and Path(unquote(location.path)) == Path(file["path"])


def _same_file(left, right):
    return _reference(left) and _reference(right) and all(left[key] == right[key] for key in REFERENCE)


def _staged_exactly(fixture_report, root, verified, profiles):
    fixture = fixture_report["metadata"]["fixture"]
    staging = fixture.get("staging", ())
    if "files.frictionless" in profiles and not _pass(fixture_report, "files.structure"):
        return False
    if not staging:
        return not profiles & {"files.frictionless", "ingest.dlt"}
    staged = set()
    for entry in staging:
        native = _read_reference(entry["receipt"]["receipt"], root)
        if native is None or native.value.get("status") != "passed":
            return False
        files = native.value.get("files", ())
        if not files or not json_equal(files, entry["receipt"]["files"]):
            return False
        if any(row.get("loadId") not in native.value.get("loadIds", ()) or not _admitted(row, root, verified) for row in files):
            return False
        staged.update((row["path"], row["sha256"]) for row in files)
    for format_ in ("sql", "substrait"):
        receipt = _read_reference(fixture["executions"][format_]["evidence"], root)
        if receipt is None or receipt.value.get("status") != "succeeded":
            return False
        consumed = {(row["path"], row["sha256"]) for row in receipt.value["inputs"] if row["format"] == "parquet"}
        if consumed != staged:
            return False
    return True


def _impact_connected(impact_report, catalog):
    if validate_document(impact_report, "report") or impact_report["decision"] == "error":
        return False
    impact = impact_report.get("impact", {})
    obligations = impact_report.get("metadata", {}).get("affectedObligations", {})
    production = {row["production"] for row in catalog["runs"] if "production" in row}
    return (
        impact.get("baseProject") == catalog["project"]["id"] and bool(impact.get("changed"))
        and any(check["requirement"] == "DDK-IMPACT-002" and check["status"] == "passed" for check in impact_report["checks"])
        and any(item["consumer"] in production and item["paths"] and item["consumer"] in obligations
                for item in impact.get("affected", ()))
    )


def _connected(reference, root, verified, profiles):
    if not isinstance(reference, dict) or not _saved_substrait(reference, root, verified):
        return False
    documents = {key: _read_reference(reference.get(key), root)
                 for key in ("fixtureReport", "catalog", "catalogReport", "consumerResult", "impactReport")}
    if any(document is None for document in documents.values()):
        return False
    fixture_report, catalog, catalog_report, consumer, impact_report = (doc.value for doc in documents.values())
    if (validate_document(catalog, "catalog") or validate_document(catalog_report, "report")
            or not isinstance(consumer, dict) or fixture_report["decision"] != "passed" or catalog_report["decision"] != "passed"):
        return False
    if not catalog["products"] or not all(_pass(catalog_report, group) for group in ("catalog.dcat", "lineage.openlineage")):
        return False
    if not any(item["role"] == "report" and item["sha256"] == documents["catalogReport"].sha256
               for item in catalog["files"]):
        return False
    if not _impact_connected(impact_report, catalog) or not _staged_exactly(fixture_report, root, verified, profiles):
        return False

    fixture = fixture_report["metadata"]["fixture"]
    execution = fixture["executions"]["substrait"]
    quality = fixture.get("quality", {}).get("substrait", {})
    targets = quality.get("target", {}).get("files", [])
    if (fixture["executions"].get("sql", {}).get("status") != "succeeded"
            or quality.get("status") != "passed" or quality.get("fixtureComparison", {}).get("status") != "passed"
            or len(targets) != 1 or not _admitted(quality.get("receipt"), root, verified)
            or not _admitted(targets[0], root, verified)):
        return False
    exact = targets[0]
    if not any(_same_file(row, exact) for row in execution.get("operation", {}).get("outputs", ())):
        return False
    versions = [version for version in catalog["versions"] if _exact_file(version, exact)]
    if len(versions) != 1:
        return False
    version, = versions
    version_id = version["id"]
    assembly = catalog.get("extensions", {}).get("urn:ddk:catalog:assembly", {})
    obligations = [row for row in assembly.get("requiredQualityChecks", ()) if row.get("subject") == version_id]
    if not obligations or not all(any(
        check["status"] == "passed" and check["subject"] == version_id
        and check.get("record", {}).get("sha256") == quality["receipt"]["sha256"]
        and all(json_equal(check.get(key), rule.get(key)) for key in ("rule", "scope", "evaluator"))
        for check in catalog["checks"]
    ) for rule in obligations):
        return False
    if version_id not in assembly.get("openLineageVersions", {}) or not any(
        run["outcome"] == "succeeded" and version_id in run["outputs"]
        and run["record"].get("sha256") == execution["evidence"]["sha256"] and run.get("openLineageRunId")
        for run in catalog["runs"]
    ):
        return False

    binding = consumer.get("binding", {})
    consumer_receipt = _read_reference(consumer.get("receipt"), root)
    release = binding.get("release")
    recipe = next((row for row in catalog["recipes"] if row["id"] == binding.get("recipe")), None)
    if (consumer.get("comparison", {}).get("status") != "passed" or consumer_receipt is None
            or consumer_receipt.value.get("status") != "succeeded" or not isinstance(release, dict)
            or version_id not in release.get("members", [])
            or not any(json_equal(release, row) for row in catalog["releases"])
            or not any(json_equal(row, version) for row in binding.get("inputs", {}).values())
            or recipe is None):
        return False
    return any(_same_file(row, exact) for row in consumer_receipt.value.get("inputs", ())) and any(
        row["role"] == "recipe" and row["path"] == recipe["sql"] and row["sha256"] == consumer.get("sqlSha256")
        for row in catalog["files"]
    )


def _connected_check(report, reference, root, verified, profiles):
    try:
        passed = _connected(reference, root, verified, profiles)
    except (AttributeError, DocumentError, KeyError, TypeError, ValueError):
        passed = False
    _emit(report, "DDK-TEST-004", "release.profiles", "connected-workflow", "passed" if passed else "not_run",
          None if passed else "TEST-WORKFLOW-INCOMPLETE",
          None if passed else "The supplied reports do not connect the generated catalog reader to the exact quality-checked saved-plan output.")


def verify_reference_workflow(reference, *, evidence_root, claimed_profiles=(), captured_root=None):
    report = ReportBuilder("urn:ddk:reference-workflow", ("release.profiles",))
    root = EvidenceDirectory(evidence_root, captured_root)
    _connected_check(report, reference, root, {}, set(claimed_profiles))
    return report.build()


def qualify_release(claim, evidence, *, cases=None, previous_diagnostics=None, component_schema=None, evidence_root=None,
                    captured_root=None):
    """Validate claimed scope and existing evidence without running product workloads."""
    report = ReportBuilder("urn:ddk:release", RELEASE_GROUPS)
    report.tools = tool_identities()
    profiles = _claim(report, claim)
    _specification_conflict(report, component_schema)
    if missing := _evidence_shape(evidence, profiles):
        _emit(report, "DDK-TEST-003", "release.evidence", "bundle", "failed", "DOC-RELEASE-EVIDENCE-MISSING",
              f"Missing or invalid release evidence: {', '.join(missing)}.")
        return report.build()
    _diagnostic_assignments(report, previous_diagnostics, evidence.get("diagnostics"))
    root = EvidenceDirectory(evidence_root, captured_root) if evidence_root is not None else None
    verified = {}
    if root is not None and not all(_measurement_verified(item, root) for item in evidence["resources"]):
        _emit(report, "DDK-TEST-003", "release.evidence", "resource-measurements", "failed", "DOC-RELEASE-EVIDENCE-MISSING",
              "A resource measurement has no matching retained artifact.", "/resources")
    registry = _catalog(cases)
    first = isinstance(claim, dict) and claim.get("firstProductRelease", False)
    run_results = _runner_results(report, evidence, root, verified)
    _expectations(report, evidence, root, verified, bool(profiles & {"test.fixtures", "plan.datafusion"}), run_results)
    passed = _case_observations(report, evidence, registry, profiles | ({"product-release"} if first else set()),
                                run_results, root, verified)
    required = profiles | (FIRST_RELEASE_PROFILES if first else set())
    report.metadata["requestedProfiles"] = sorted(required)
    report.metadata["testedTools"] = evidence["tools"]
    report.metadata["unresolvedReleaseEvidence"] = evidence["unresolved"]
    for profile in sorted(required):
        expected = _required_cases(profile, registry)
        missing = sorted(expected - passed[profile])
        reason = None
        if profile not in profiles:
            reason = "The release does not claim this required profile."
        elif not passed[profile] or missing:
            reason = "Passing case evidence is missing." + (f" Pending cases: {', '.join(missing)}." if missing else "")
        elif profile == "plan.datafusion" and not _saved_substrait(evidence.get("referenceWorkflow"), root, verified):
            reason = "An executed fixture tied to the saved Substrait bytes is missing."
        if reason:
            report.missing_capabilities.add(profile)
            _emit(report, "DDK-VERSION-003", "release.profiles", profile, "not_run", "ADAPTER-CAPABILITY-MISSING", reason)
        else:
            _emit(report, "DDK-VERSION-003", "release.profiles", profile, "passed")
    if first:
        _connected_check(report, evidence.get("referenceWorkflow"), root, verified, profiles)
        release_cases = {case for case, record in registry.items() if record["profile"] == "product-release"}
        if missing := sorted(release_cases - passed["product-release"]):
            _emit(report, "DDK-TEST-002", "release.profiles", "workflow-cases", "not_run",
                  "TEST-WORKFLOW-INCOMPLETE", f"Required reference workflow cases lack passing evidence: {', '.join(missing)}.")
    from .capability_evidence import admit_release_capabilities

    adapters, errors = admit_release_capabilities(evidence, root)
    if errors:
        _emit(report, "DDK-ADAPTER-001", "release.evidence", "adapter-manifests", "failed",
              "DOC-CAPABILITY-EVIDENCE", "; ".join(errors))
    if report.build()["decision"] == "passed":
        report.completed_profiles.update(required)
        if adapters:
            report.metadata["qualifiedAdapterManifests"] = adapters
    return report.build()
