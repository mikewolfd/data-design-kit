"""Public release membership is usable without granting private native references."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from ddk.catalog import assemble_catalog
from ddk.catalog_delivery import verify_catalog_pair
from ddk.documents import validate_document

from test_catalog_delivery import inputs, captured, assemble  # noqa: F401


def disclose_release(inputs, *, native=False, remove_member=False):
    root, policy_path = inputs
    metadata = root / "catalog/metadata.example.json"
    source = json.loads(metadata.read_text())
    release, = source["releases"]
    release["reference"]["authority"] = "file:///private/release-owner"
    release["reference"]["value"] = {"path": "/private/release-manifest", "digest": "a" * 64}
    metadata.write_text(json.dumps(source))
    policy = json.loads(policy_path.read_text())
    policy["identifiers"] += [release["id"], source["selections"][0]["authority"]]
    policy["nativeReferences"] = [release["id"]] if native else []
    if remove_member:
        policy["identifiers"].remove(release["members"][0])
    policy_path.write_text(json.dumps(policy))
    return release


@pytest.mark.parametrize("native", [False, True])
def test_release_disclosure_keeps_exact_members_and_selection(inputs, tmp_path, native):
    original = disclose_release(inputs, native=native)
    public, local = captured(inputs, tmp_path)
    release, = public.catalog["releases"]
    assert release["members"] == original["members"] and release["membership"] == "complete"
    assert public.catalog["selections"][0]["release"] == original["id"]
    assert ("reference" in release) is native
    assert (release.get("referenceDisclosure") == "withheld") is (not native)
    assert local.catalog["releases"][0]["reference"] == original["reference"]
    assert not validate_document(public.catalog, "catalog")
    assert verify_catalog_pair(public, local)
    all_public_bytes = b"".join(public.artifacts.values())
    assert (b"/private/release" in all_public_bytes) is native


@pytest.mark.parametrize("membership", ["complete", "partial", "unknown"])
def test_omitting_member_cannot_upgrade_release_completeness(inputs, tmp_path, membership):
    original = disclose_release(inputs, remove_member=True)
    root, _ = inputs
    metadata = root / "catalog/metadata.example.json"
    source = json.loads(metadata.read_text())
    source["releases"][0]["membership"] = membership
    metadata.write_text(json.dumps(source))
    public, local = captured(inputs, tmp_path)
    release, = public.catalog["releases"]
    assert release["members"] == original["members"][1:]
    assert release["membership"] == ("partial" if membership == "complete" else membership)
    assert verify_catalog_pair(public, local)


@pytest.mark.parametrize("mutation", ["member", "completeness", "reference", "release-id", "authority", "purpose", "selected-release", "observed-at", "current-selection"])
def test_pair_refuses_changed_release_or_selection_meaning(inputs, tmp_path, mutation):
    disclose_release(inputs, native=mutation == "reference")
    public, local = captured(inputs, tmp_path)
    local = replace(local, catalog=deepcopy(local.catalog))
    release = local.catalog["releases"][0]
    if mutation == "member":
        release["members"] = []
    elif mutation == "completeness":
        release["membership"] = "unknown"
    elif mutation == "reference":
        release["reference"]["value"] = "substituted"
    elif mutation == "release-id":
        release["id"] = "urn:test:different-release"
    elif mutation == "current-selection":
        local.catalog["currentSelection"] = {"authority": "urn:test:other", "purpose": "other"}
    else:
        key = {"selected-release": "release", "observed-at": "observedAt"}.get(mutation, mutation)
        local.catalog["selections"][0][key] = "changed"
    with pytest.raises(ValueError, match="[Pp]aired|outside"):
        verify_catalog_pair(public, local)


@pytest.mark.parametrize("section", ["versions", "releases"])
def test_withheld_native_reference_is_public_only(inputs, section):
    root, _ = inputs
    path = root / "catalog/metadata.example.json"
    metadata = json.loads(path.read_text())
    metadata[section][0].pop("reference")
    metadata[section][0]["referenceDisclosure"] = "withheld"
    path.write_text(json.dumps(metadata))
    result = assemble_catalog(root / "project.ddk.json", metadata=path, metadata_adapter="example")
    assert result.report["decision"] == "failed" and not result.artifacts
    assert any(diagnostic["code"] == "CATALOG-NATIVE-REFERENCE"
               for check in result.report["checks"] for diagnostic in check.get("diagnostics", []))


def test_release_requires_exactly_one_reference_mode(inputs):
    disclose_release(inputs)
    result = assemble(inputs)
    public = deepcopy(result.catalog)
    release = public["releases"][0]
    release["reference"] = {"scheme": "urn:test:release", "authority": "urn:test:owner", "value": "x"}
    assert validate_document(public, "catalog")
    release.pop("reference")
    release.pop("referenceDisclosure")
    assert validate_document(public, "catalog")
