"""Independent delivery failures and paired disclosure over one captured source."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from ddk.catalog import assemble_catalog
from ddk.catalog_delivery import PAIRED_VIEW, load_catalog_artifacts, verify_catalog_pair


COMMERCE = Path(__file__).resolve().parents[2] / "examples" / "commerce"


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "source"
    shutil.copytree(COMMERCE, root)
    baseline = assemble_catalog(root / "project.ddk.json",
                                metadata=root / "catalog/metadata.example.json", metadata_adapter="example")
    assert baseline.report["decision"] == "passed"
    catalog = baseline.catalog
    identifiers = {catalog["id"], catalog["project"]["id"]}
    for section in ("datasets", "products", "relationships", "versions", "representations", "recipes"):
        identifiers.update(row["id"] for row in catalog[section])
    identifiers.update(row["definition"]["contractId"] for row in catalog["datasets"])
    policy = root / "public.json"
    policy.write_text(json.dumps({"identifiers": sorted(identifiers), "descriptions": True,
                                 "recipes": [row["id"] for row in catalog["recipes"]],
                                 "definitionFields": {row["id"]: [[{"field": "region"}]] for row in catalog["datasets"]
                                                      if row["alias"] == "daily-revenue"}}))
    return root, policy


def assemble(inputs, **options):
    root, policy = inputs
    return assemble_catalog(root / "project.ddk.json", metadata=root / "catalog/metadata.example.json",
                            metadata_adapter="example", disclosure_policy=policy, **options)


def write(root, artifacts):
    root.mkdir()
    for name, body in artifacts.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return sha256(artifacts["catalog.lock.json"]).hexdigest()


def captured(inputs, tmp_path):
    result = assemble(inputs, include_private_artifacts=True)
    assert result.report["decision"] == "passed", result.local_report
    public, local = tmp_path / "public", tmp_path / "local"
    public_pin, local_pin = write(public, result.artifacts), write(local, result.local_artifacts)
    return (load_catalog_artifacts(public, expected_lock_sha256=public_pin, audience="public"),
            load_catalog_artifacts(local, expected_lock_sha256=local_pin, audience="local"))


def test_pair_reuses_one_source_read_without_private_disclosure(inputs, tmp_path, monkeypatch):
    root, _ = inputs
    paths = {path.resolve() for path in root.rglob("*") if path.is_file()}
    opened = Counter()
    original = Path.open

    def observe(path, *args, **kwargs):
        if path.resolve() in paths:
            opened[path.resolve()] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe)
    public, local = captured(inputs, tmp_path)
    assert opened and max(opened.values()) == 1
    aliases = verify_catalog_pair(public, local)
    assert all(public_alias.startswith("public-") for public_alias in aliases)
    assert "daily-revenue" in aliases.values()
    assert PAIRED_VIEW not in public.lock["extensions"]
    assert PAIRED_VIEW in local.lock["extensions"]
    assert str(root).encode() not in b"".join(public.artifacts.values())
    assert any("referenceDisclosure" in row and "reference" not in row for row in public.catalog["versions"])
    assert all("reference" in row for row in local.catalog["versions"])
    # Full private fields are preserved but do not enter the public definition.
    details = "urn:ddk:catalog:assembly"
    public_definition, = public.catalog["extensions"][details]["datasetDefinitions"].values()
    assert [row["name"] for row in public_definition["properties"]] == ["region"]
    assert len(local.catalog["extensions"][details]["datasetDefinitions"]["daily-revenue"]["properties"]) > 1


def test_captured_recipe_uses_the_admitted_bytes_without_any_metadata_reopen(inputs, tmp_path, monkeypatch):
    from ddk.catalog_access import run_checked_query
    import shutil

    public, local = captured(inputs, tmp_path)
    recipe = local.catalog["recipes"][0]
    expected = local.companions[recipe["sql"]]
    versions = {name: next(row["id"] for row in local.catalog["versions"] if row["dataset"] == alias)
                for name, alias in recipe["inputs"].items()}
    with pytest.raises(TypeError):
        local.catalog["datasets"][0]["definition"]["object"] = "changed"
    with pytest.raises(TypeError):
        local.lock["extensions"].clear()
    with pytest.raises(TypeError):
        local.report["checks"].append({})
    # Captured metadata remains the selected meaning if the delivery directory
    # is replaced/removed. Native data custody remains the injected owner's job.
    shutil.rmtree(local.directory)
    calls = []
    def reader(request):
        assert request["sql"] == expected
        assert {name: row["id"] for name, row in request["inputs"].items()} == versions
        calls.append(request)
        return {"result": [{"amount_cents": 42}], "receipt": {"id": "independent-read-fixture"}}
    def no_reopen(*args, **kwargs):
        raise AssertionError("Captured query must not reopen catalog, lock, SQL or data")
    monkeypatch.setattr(Path, "open", no_reopen)
    result = run_checked_query(local, recipe["id"], reader, versions=versions)
    assert result["sqlSha256"] == sha256(expected).hexdigest() and len(calls) == 1
    with pytest.raises(ValueError, match="externally pinned"):
        run_checked_query(replace(local, externally_pinned=False), recipe["id"], reader, versions=versions)
    public_recipe = public.catalog["recipes"][0]
    with pytest.raises(ValueError, match="native reference"):
        run_checked_query(public, public_recipe["id"], reader, versions=versions)
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["missing", "changed", "oversized"])
def test_captured_recipe_refuses_unavailable_or_different_sql_before_reader(inputs, tmp_path, mutation):
    from ddk.catalog_access import run_checked_query
    from ddk.documents import DEFAULT_LIMITS, ResourceLimit

    _, local = captured(inputs, tmp_path)
    recipe = local.catalog["recipes"][0]
    versions = {name: next(row["id"] for row in local.catalog["versions"] if row["dataset"] == alias)
                for name, alias in recipe["inputs"].items()}
    companions = dict(local.companions)
    if mutation == "missing":
        del companions[recipe["sql"]]
    else:
        companions[recipe["sql"]] = b"SELECT 1" if mutation == "changed" else b" " * (DEFAULT_LIMITS["maxDocumentBytes"] + 1)
    with pytest.raises(ResourceLimit if mutation == "oversized" else ValueError):
        run_checked_query(replace(local, companions=companions), recipe["id"], lambda request: pytest.fail("must not execute"), versions=versions)


@pytest.mark.parametrize("mutation", ["wrong-public-pin", "unpinned", "definition", "version", "relationship-scope", "relationship-rule", "relationship-path", "input-alias", "sql"])
def test_pair_refuses_mixed_or_changed_access_meaning(inputs, tmp_path, mutation):
    public, local = captured(inputs, tmp_path)
    local = replace(local, catalog=deepcopy(local.catalog), lock=deepcopy(local.lock), companions=dict(local.companions))
    if mutation == "wrong-public-pin":
        local.lock["extensions"][PAIRED_VIEW]["publicLockSha256"] = "0" * 64
    elif mutation == "unpinned":
        local = replace(local, externally_pinned=False)
    elif mutation == "definition":
        dataset_id = public.catalog["datasets"][0]["id"]
        next(row for row in local.catalog["datasets"] if row["id"] == dataset_id)["definition"]["source"]["sha256"] = "0" * 64
    elif mutation == "version":
        version_id = public.catalog["versions"][0]["id"]
        next(row for row in local.catalog["versions"] if row["id"] == version_id)["retention"] = "missing"
    elif mutation.startswith("relationship-"):
        identifier = public.catalog["relationships"][0]["id"]
        relation = next(row for row in local.catalog["relationships"] if row["id"] == identifier)
        if mutation == "relationship-scope":
            relation["scope"] = "same_release" if relation["scope"] != "same_release" else "version_pair"
        elif mutation == "relationship-rule":
            relation["match"] = "project_rule"
            relation["rule"] = {"id": "urn:test:other-rule", "version": "1.0.0"}
        else:
            relation["source"]["paths"] = [[{"field": "unrelated"}]]
    elif mutation == "input-alias":
        recipe = public.catalog["recipes"][0]
        next(row for row in local.catalog["recipes"] if row["id"] == recipe["id"])["inputs"] = {"wrong": "orders"}
    else:
        local.companions[public.catalog["recipes"][0]["sql"]] = b"SELECT 9 AS substituted"
    with pytest.raises(ValueError):
        verify_catalog_pair(public, local)


@pytest.mark.parametrize("mutation", ["digest", "extra", "missing", "symlink", "wrong-pin", "byte-cap"])
def test_delivery_refuses_incomplete_or_unpinned_artifact_identity(inputs, tmp_path, mutation):
    result = assemble(inputs)
    root = tmp_path / "catalog"
    pin = write(root, result.artifacts)
    options = {"expected_lock_sha256": pin}
    if mutation == "digest":
        (root / "catalog.ddk.json").write_bytes(b"{}")
    elif mutation == "extra":
        (root / "extra.txt").write_text("unmanaged")
    elif mutation == "missing":
        (root / "catalog.report.json").unlink()
    elif mutation == "symlink":
        saved = tmp_path / "saved-report.json"
        (root / "catalog.report.json").rename(saved)
        (root / "catalog.report.json").symlink_to(saved)
    elif mutation == "wrong-pin":
        options["expected_lock_sha256"] = "0" * 64
    else:
        options["max_total_bytes"] = 32
    with pytest.raises((ValueError, OSError)):
        load_catalog_artifacts(root, **options)


def test_incomplete_checks_do_not_produce_private_controls(inputs):
    result = assemble(inputs, include_private_artifacts=True, required_groups=("catalog.qualification",))
    assert result.report["decision"] != "passed"
    assert not result.artifacts and not result.local_artifacts


def test_pair_is_explicit_and_cannot_run_on_local_only_assembly(inputs):
    assert not assemble(inputs).local_artifacts
    with pytest.raises(ValueError, match="public"):
        assemble_catalog(inputs[0] / "project.ddk.json", include_private_artifacts=True)


def test_requested_dcat_is_present_in_both_complete_views(inputs, tmp_path):
    result = assemble(inputs, include_private_artifacts=True, exports=("catalog.dcat",))
    assert result.report["decision"] == "passed", result.local_report
    for label, artifacts in (("public", result.artifacts), ("local", result.local_artifacts)):
        assert "discovery.dcat.json" in artifacts
        root = tmp_path / label
        pin = write(root, artifacts)
        captured = load_catalog_artifacts(root, expected_lock_sha256=pin)
        assert any(item["path"] == "discovery.dcat.json" and item["role"] == "dcat" for item in captured.catalog["files"])


def test_unsupported_public_lineage_cannot_leave_a_partial_private_set(inputs):
    result = assemble(inputs, include_private_artifacts=True, exports=("catalog.dcat", "lineage.openlineage"))
    assert result.report["decision"] != "passed"
    assert not result.artifacts and not result.local_artifacts


def test_pair_verifies_disclosed_concepts_and_refuses_concept_tampering(inputs, tmp_path):
    root, policy_path = inputs
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    # Disclose amount_cents on daily-revenue so the shared amount-cents concept enters the public catalog.
    policy["definitionFields"]["urn:example:commerce:dataset:daily-revenue"] = [
        [{"field": "region"}], [{"field": "amount_cents"}],
    ]
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    public, local = captured(inputs, tmp_path)
    assert len(public.catalog["concepts"]) == 1
    assert verify_catalog_pair(public, local)

    for mutation in ("concept-kind", "omit-public-concept", "extra-match"):
        mutated_local = replace(local, catalog=deepcopy(local.catalog))
        mutated_public = replace(public, catalog=deepcopy(public.catalog))
        if mutation == "concept-kind":
            mutated_local.catalog["concepts"][0]["conceptKind"] = "identifier"
        elif mutation == "omit-public-concept":
            mutated_public.catalog["concepts"] = []
        else:
            mutated_public.catalog["concepts"][0]["exactMatch"] = ["https://example.org/unapproved"]
        with pytest.raises(ValueError, match="concept|Concept"):
            verify_catalog_pair(mutated_public, mutated_local)

