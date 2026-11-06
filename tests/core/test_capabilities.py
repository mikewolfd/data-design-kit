"""Manifest discovery remains data-only and execution stays explicitly injected."""

import builtins
import shutil

from ddk.capabilities import read_capability_manifests
from ddk.core import check_project
from ddk.execution import build_project
from ddk.locks import lock_project

from test_core import COMMERCE, commerce


def test_offline_manifest_discovery_does_not_import_native_tools_and_adapter_injection_is_explicit(
    commerce, tmp_path, monkeypatch,
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
