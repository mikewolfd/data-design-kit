"""Manifest discovery remains data-only and execution stays explicitly injected."""

import builtins
from copy import deepcopy
from hashlib import sha256
import json
import shutil

import pytest

from ddk.capabilities import read_capability_manifests
from ddk.capability_evidence import admit_release_capabilities
from ddk.core import check_project
from ddk.execution import build_project
from ddk.evidence_locations import EvidenceDirectory
from ddk.locks import lock_project

from test_core import COMMERCE, commerce, selected_development_identity


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def qualified_capability_evidence(tmp_path):
    declaration = json.loads((COMMERCE.parent / "adapter-manifest.ddk.json").read_text())
    declaration.pop("extensions", None)
    declaration["profiles"] = ["plan.docspec-sql"]
    declaration["tools"] = {}
    declaration["status"] = "experimental-unverified"
    # The fixture deliberately names a bounded supported operation. Mutations
    # below must not obtain qualification from unchanged passing profile names.
    declaration["capabilities"] = [{
        "group": "plan.compile", "standards": {"sql": "tested-dialect"},
        "operations": ["prepare"], "facets": {"schemaOnly": "checked"},
        "limitations": ["One bounded SQL output"], "evidence": [],
    }]
    support = _write_json(tmp_path / "support.json", {"adapters": [declaration]})
    support["sourcePath"] = "conformance/adapter-capabilities.json"
    source = _write_json(tmp_path / "source.json", {
        "files": [{"path": support["sourcePath"], "sha256": support["sha256"]}],
    })
    tools = {"ddk": {"version": "1.0.0"}, "docspec": {"version": "1.0.0"}}
    manifest = deepcopy(declaration)
    manifest["status"] = "qualified"
    manifest["tools"] = tools
    manifest["capabilities"][0]["evidence"] = ["source.json"]
    reference = _write_json(tmp_path / "adapter.json", manifest)
    evidence = {
        "source": source, "adapterSupport": support, "adapterManifests": [reference],
        "requestedProfiles": declaration["profiles"], "tools": tools,
        "profileTools": {"plan.docspec-sql": list(tools)}, "testRuns": [],
    }
    return manifest, evidence


def test_qualified_manifest_is_bound_to_captured_support_and_exact_bytes(qualified_capability_evidence, tmp_path, commerce):
    manifest, evidence = qualified_capability_evidence
    records, errors = admit_release_capabilities(evidence, tmp_path)
    assert not errors and len(records) == 1
    verified_release = {"decision": "passed", "coverage": {"completedProfiles": manifest["profiles"]},
                        "metadata": {"testedTools": manifest["tools"], "qualifiedAdapterManifests": records}}
    report = check_project(commerce / "project.ddk.json", permitted_roots=(tmp_path,),
                           adapter_manifests=[tmp_path / "adapter.json"], verified_release=verified_release)
    assert report["metadata"]["adapterManifests"][0]["qualificationVerified"]
    assert "plan.compile" in report["coverage"]["availableCapabilities"]
    for field, replacement in (
        ("operations", ["execute-arbitrary-sql"]),
        ("facets", {"arbitraryNestedTypes": "checked"}),
        ("evidence", ["nonexistent.json"]),
        ("limitations", []),
        ("backend", "another-engine"),
        ("requestKinds", ["arbitrary-sql-build"]),
    ):
        changed = deepcopy(manifest)
        changed["capabilities"][0][field] = replacement
        _write_json(tmp_path / "adapter.json", changed)
        rejected = check_project(commerce / "project.ddk.json", permitted_roots=(tmp_path,),
                                 adapter_manifests=[tmp_path / "adapter.json"], verified_release=verified_release)
        assert not rejected["metadata"]["adapterManifests"][0]["qualificationVerified"], field
        assert "plan.compile" not in rejected["coverage"]["availableCapabilities"], field


def test_release_rejects_expanded_support_and_unrelated_evidence(qualified_capability_evidence, tmp_path):
    manifest, evidence = qualified_capability_evidence
    expanded = deepcopy(manifest)
    expanded["capabilities"][0]["operations"].append("arbitrary-sql-build")
    evidence["adapterManifests"] = [_write_json(tmp_path / "adapter.json", expanded)]
    records, errors = admit_release_capabilities(evidence, tmp_path)
    assert not records and "tested source declaration" in errors[0]
    unrelated = deepcopy(manifest)
    _write_json(tmp_path / "unrelated.json", {"decision": "passed"})
    unrelated["capabilities"][0]["evidence"] = ["unrelated.json"]
    evidence["adapterManifests"] = [_write_json(tmp_path / "adapter.json", unrelated)]
    records, errors = admit_release_capabilities(evidence, tmp_path)
    assert not records and "admitted source or test-run" in errors[0]


def test_release_rejects_adapter_declaration_outside_captured_source(qualified_capability_evidence, tmp_path):
    _, evidence = qualified_capability_evidence
    evidence["source"] = _write_json(tmp_path / "source.json", {"files": []})
    records, errors = admit_release_capabilities(evidence, tmp_path)
    assert not records and "source captured" in errors[0]


def test_absolute_capability_evidence_relocates_without_rewriting_captured_bytes(qualified_capability_evidence, tmp_path):
    manifest, evidence = qualified_capability_evidence
    manifest["capabilities"][0]["evidence"] = [str(tmp_path / "source.json")]
    evidence["adapterManifests"] = [_write_json(tmp_path / "adapter.json", manifest)]
    original = (tmp_path / "adapter.json").read_bytes()
    relocated = tmp_path.with_name(tmp_path.name + "-relocated")
    relocated.mkdir()
    for path in tmp_path.glob("*.json"):
        path.rename(relocated / path.name)
    records, errors = admit_release_capabilities(evidence, EvidenceDirectory(relocated, tmp_path))
    assert not errors and len(records) == 1
    assert (relocated / "adapter.json").read_bytes() == original
    manifest["capabilities"][0]["evidence"] = [str(tmp_path.parent / "foreign.json")]
    evidence["adapterManifests"] = [_write_json(relocated / "adapter.json", manifest)]
    records, errors = admit_release_capabilities(evidence, EvidenceDirectory(relocated, tmp_path))
    assert not records and "outside the captured root" in errors[0]


def test_offline_manifest_discovery_does_not_import_native_tools_and_adapter_injection_is_explicit(
    commerce, tmp_path, monkeypatch, selected_development_identity,
):
    manifest = commerce / "docspec.adapter.json"
    shutil.copyfile(COMMERCE.parent / "adapter-manifest.ddk.json", manifest)
    (commerce / "docspec.py").write_text("raise AssertionError('a manifest must never import its adapter')\n")
    monkeypatch.syspath_prepend(str(commerce))
    project = commerce / "project.ddk.json"
    original_import = builtins.__import__

    def offline_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".")[0] in {"datafusion", "datacontract", "docspec", "duckdb", "dlt", "frictionless", "pyarrow"} or (
            name.startswith(("ddk.adapters", "adapters"))
        ):
            raise AssertionError(f"unexpected native module import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", offline_import)
    document, = read_capability_manifests([manifest])
    assert document.value["status"] == "experimental-unverified"
    baseline = check_project(project)
    installed = check_project(project, adapter_manifests=[manifest])
    assert baseline["decision"] == installed["decision"] == "passed"
    assert baseline["checks"] == installed["checks"]
    declared, = installed["metadata"]["adapterManifests"]
    assert declared["declaredStatus"] == "experimental-unverified"
    assert not declared["qualificationVerified"]
    assert installed["coverage"]["availableCapabilities"] == []
    _, lock = lock_project(project, adapter_manifests=[manifest])
    assert any(item["role"] == "capability" and item["path"] == manifest.name for item in lock["files"])
    assert check_project(project, lock=lock, locked=True, adapter_manifests=[manifest])["decision"] == "passed"

    class InjectedPlanService:
        evidence_dir = tmp_path

        def __init__(self):
            self.requests = []

        def prepare(self, request):
            self.requests.append(request)
            return {"status": "not_submitted", "reason": "Deliberate injected adapter refusal."}

    injected = InjectedPlanService()
    output = tmp_path / "bundle"
    result = build_project(project, "summarize", runtime=injected, output=output, formats=("sql",))
    assert len(injected.requests) == 1
    assert injected.requests[0]["calculation"]["format"] == "sql"
    assert result["decision"] == "incomplete"
    assert not output.exists()
