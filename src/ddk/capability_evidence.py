"""Bind released adapter claims to declarations captured with the tested source."""

from copy import deepcopy
import re

from .documents import DocumentError, ResourceLimit, read_json, validate_document
from .evidence_locations import evidence_path
from .interfaces import json_equal


def _document(reference, root):
    if (root is None or not isinstance(reference, dict)
            or not isinstance(reference.get("path"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", str(reference.get("sha256", "")))):
        raise ValueError("Capability evidence requires a retained path and SHA-256.")
    path = evidence_path(root, reference["path"])
    document = read_json(path)
    if document.sha256 != reference["sha256"]:
        raise ValueError("Capability evidence differs from the retained identity.")
    return path, document


def _support(manifest):
    """Keep every support claim while removing only release-specific records."""
    result = deepcopy(manifest)
    result["status"] = "experimental-unverified"
    result["tools"] = {}
    for capability in result["capabilities"]:
        capability["evidence"] = []
    return result


def admit_release_capabilities(evidence, root):
    """Return exact qualified manifest identities, or errors that block release.

    The caller admits runner outcomes separately. This checks that capability
    statements were present in that source capture and that their generated
    manifests point to those same outcomes, without importing implementations.
    """
    if "adapterManifests" not in evidence:
        return [], []
    records = []
    try:
        references = evidence["adapterManifests"]
        if not isinstance(references, list) or not references:
            raise ValueError("A claimed adapter release needs retained manifests.")
        _, source = _document(evidence.get("source"), root)
        support_ref = evidence.get("adapterSupport")
        _, support = _document(support_ref, root)
        if (support_ref.get("sourcePath") != "conformance/adapter-capabilities.json"
                or not isinstance(source.value, dict)
                or not any(isinstance(row, dict) and row.get("path") == support_ref["sourcePath"]
                           and row.get("sha256") == support.sha256 for row in source.value.get("files", ()))):
            raise ValueError("Adapter declarations must belong to the source captured by the test run.")
        declarations = support.value.get("adapters") if isinstance(support.value, dict) else None
        if not isinstance(declarations, list) or not declarations:
            raise ValueError("The captured adapter declaration inventory is missing.")
        declared = {}
        for declaration in declarations:
            if not isinstance(declaration, dict) or validate_document(declaration, "adapter"):
                raise ValueError("A captured adapter declaration has an invalid shape.")
            key = (declaration["id"], declaration["version"])
            if key in declared:
                raise ValueError("The source repeats an adapter identity and version.")
            declared[key] = _support(declaration)

        admitted_paths = set()
        evidence_refs = [evidence["source"], *[run.get("result") for run in evidence.get("testRuns", ())
                                             if isinstance(run, dict)]]
        for reference in evidence_refs:
            if reference is evidence["source"]:
                path, _ = _document(reference, root)
            else:
                # The release runner has already admitted the JUnit bytes. Bind
                # the manifest location to that retained reference, not a label.
                if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
                    raise ValueError("A capability refers to a malformed test run.")
                path = evidence_path(root, reference["path"])
                if not path.is_file():
                    raise ValueError("Capability run evidence is unavailable under the admitted root.")
            admitted_paths.add(path)

        seen = set()
        for reference in references:
            path, document = _document(reference, root)
            manifest = document.value
            if not isinstance(manifest, dict) or validate_document(manifest, "adapter"):
                raise ValueError("A release capability manifest has an invalid shape.")
            key = (manifest["id"], manifest["version"])
            if key in seen or key not in declared:
                raise ValueError("A release manifest has a repeated or uncaptured adapter identity.")
            seen.add(key)
            if not json_equal(_support(manifest), declared[key]):
                raise ValueError("A release capability claim differs from its tested source declaration.")
            profiles = set(manifest["profiles"])
            if manifest["status"] != "qualified" or not profiles <= set(evidence.get("requestedProfiles", ())):
                raise ValueError("A release manifest claims profiles outside the requested qualification.")
            tools = manifest["tools"]
            dependencies = set()
            for profile in profiles:
                dependencies.update(evidence.get("profileTools", {}).get(profile, ()))
            if (not tools or not dependencies or not dependencies <= tools.keys()
                    or any(not json_equal(tool, evidence.get("tools", {}).get(name)) for name, tool in tools.items())):
                raise ValueError("A release manifest does not identify its exact tested dependencies.")
            for capability in manifest["capabilities"]:
                paths = capability["evidence"]
                if not paths or any(evidence_path(root, path.parent / item) not in admitted_paths for item in paths):
                    raise ValueError("A capability must refer to the admitted source or test-run evidence.")
            records.append({"id": manifest["id"], "version": manifest["version"], "sha256": document.sha256})
    except (DocumentError, ResourceLimit, OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        return [], [str(exc)]
    return records, []
