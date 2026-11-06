"""Discover adapter capabilities from explicitly admitted manifest data."""

from pathlib import Path

from .documents import DocumentError, read_json, resolve_path, validate_document
from .interfaces import json_equal
from .results import diagnostic


def read_capability_manifests(paths):
    """Read explicitly selected manifest files without importing executable code."""
    manifests = []
    for path in sorted(set(map(str, paths))):
        document = read_json(path)
        if issues := validate_document(document.value, "adapter"):
            issue = issues[0]
            raise DocumentError(issue.code, issue.message, issue.pointer)
        manifests.append(document)
    return tuple(manifests)


def discover_capabilities(inventory, manifests, verified_release=None):
    report = inventory.report
    verified_release = verified_release or {}
    tested_tools = verified_release.get("metadata", {}).get("testedTools", {})
    qualified_manifests = verified_release.get("metadata", {}).get("qualifiedAdapterManifests", ())
    qualified_profiles = set(verified_release.get("coverage", {}).get("completedProfiles", ()))
    discovered = []
    identities = set()
    for entry in sorted(set(map(str, manifests))):
        path = inventory.path
        subject = f"capability:{entry}"
        try:
            path = resolve_path(inventory.path, str(Path(entry).absolute()), inventory.permitted_roots)
            document = inventory.read(path)
        except DocumentError as exc:
            report.add("DDK-ADAPTER-001", "core.documents", subject, "failed", diagnostics=[
                diagnostic(exc.code, str(exc), path=path, pointer=exc.pointer)
            ])
            continue
        except OSError:
            detail = diagnostic("DOC-UNREADABLE", "The requested capability manifest could not be read.", path=path)
            report.error(detail)
            report.add("DDK-ADAPTER-001", "core.documents", subject, "not_run", reason=detail["message"], diagnostics=[detail])
            continue
        if issues := validate_document(document.value, "adapter"):
            report.add("DDK-ADAPTER-001", "core.documents", subject, "failed", diagnostics=[
                diagnostic(issue.code, issue.message, path=inventory.display_path(path), pointer=issue.pointer)
                for issue in issues
            ])
            continue
        manifest = document.value
        key = (manifest["id"], manifest["version"])
        if key in identities:
            report.add("DDK-ADAPTER-001", "core.documents", subject, "failed", diagnostics=[
                diagnostic("ADAPTER-IDENTITY-CONFLICT", "A manifest repeats the same adapter identity and version.",
                           path=inventory.display_path(path))
            ])
            continue
        identities.add(key)
        inventory.add_file(document, "capability", identity=manifest["id"], owner="project:/")
        inventory.dependency("project:/", f"capability:{inventory.display_path(path)}")
        qualified = (
            manifest["status"] == "qualified" and verified_release.get("decision") == "passed"
            and bool(manifest["tools"]) and set(manifest["profiles"]) <= qualified_profiles
            and all(json_equal(tool, tested_tools.get(name)) for name, tool in manifest["tools"].items())
            and all(capability["evidence"] for capability in manifest["capabilities"])
            and {"id": manifest["id"], "version": manifest["version"], "sha256": document.sha256}
                in qualified_manifests
        )
        if qualified:
            report.available_capabilities.update(capability["group"] for capability in manifest["capabilities"])
        discovered.append({
            "path": inventory.display_path(path), "sha256": document.sha256,
            "id": manifest["id"], "version": manifest["version"], "declaredStatus": manifest["status"],
            "qualificationVerified": qualified, "profiles": manifest["profiles"],
            "tools": manifest["tools"], "capabilities": manifest["capabilities"],
        })
    if discovered:
        report.metadata["adapterManifests"] = discovered
