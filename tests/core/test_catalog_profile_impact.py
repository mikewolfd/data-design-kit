"""Independent profile-provenance and declaration-support impact expectations."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ddk.catalog import assemble_catalog
from ddk.catalog_semantics import RelationshipAssessment
from ddk.impact import compare_catalogs


COMMERCE = Path(__file__).resolve().parents[2] / "examples" / "commerce"
DETAILS = "urn:ddk:catalog:assembly"
PROFILE = "urn:test:impact:declaration-profile"
LINK = "urn:example:commerce:relationship:customer"
READER = "urn:example:commerce:recipe:daily-revenue"
CONTEXT_READER = "urn:example:commerce:recipe:checked-revenue"
UNASSESSED = "urn:test:impact:unassessed-relationship"
UNRELATED_READER = "urn:test:impact:unrelated-reader"
OBLIGATIONS = ["consumer-rebind", "metadata-regeneration"]


def snapshots():
    admitted = assemble_catalog(COMMERCE / "project.ddk.json")
    assert admitted.report["decision"] == "passed"
    base = deepcopy(admitted.catalog)
    relationship, = base["relationships"]
    unassessed = {**deepcopy(relationship), "id": UNASSESSED}
    relationship.update(match="project_rule", rule={"id": "urn:test:impact:typed-comparison", "version": "1.0.0"})
    base["relationships"].append(unassessed)
    reader = next(row for row in base["recipes"] if row["id"] == READER)
    base["recipes"].append({**deepcopy(reader), "id": UNRELATED_READER, "relationships": [UNASSESSED]})
    context_reader = next(row for row in base["recipes"] if row["id"] == CONTEXT_READER)
    context_reader["contextualRelationships"] = [LINK]
    identity = {"id": PROFILE, "version": "1.0.0"}
    base["extensions"][DETAILS]["relationshipProfile"] = {
        "identity": identity, "scope": "declaration-support-only",
        "source": {"uri": "urn:test:impact:retained-source", "sha256": sha256(b"Independent profile revision one.\n").hexdigest()},
    }
    base["extensions"][DETAILS]["relationshipAssessments"] = [{
        "relationship": LINK, "profile": deepcopy(identity), "status": "supported",
        "reason": "Independent fixture declaration compatibility.", "scope": "declaration-support-only",
    }]
    return base, deepcopy(base)


@pytest.mark.parametrize("provenance", ["version", "source", "distribution"])
def test_profile_provenance_changes_recheck_only_actually_assessed_relationships_and_readers(provenance):
    base, candidate = snapshots()
    old = base["extensions"][DETAILS]["relationshipProfile"]
    new = candidate["extensions"][DETAILS]["relationshipProfile"]
    if provenance == "version":
        new["identity"]["version"] = "2.0.0"
    elif provenance == "source":
        new["source"]["sha256"] = sha256(b"Independent profile revision two.\n").hexdigest()
    else:
        old.pop("source")
        new.pop("source")
        old["identity"]["distributionSha256"] = "a" * 64
        new["identity"]["distributionSha256"] = "b" * 64
        base["extensions"][DETAILS]["relationshipAssessments"][0]["profile"] = deepcopy(old["identity"])
    candidate["extensions"][DETAILS]["relationshipAssessments"][0]["profile"] = deepcopy(new["identity"])
    assert base["relationships"] == candidate["relationships"]
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    change = report["metadata"]["catalogChanges"][f"relationship-profile:{PROFILE}"]
    assert change["obligations"] == OBLIGATIONS
    assert change["computation"] == "unknown" and change["domainEffects"]["status"] == "unknown"
    assert change["baseRecord"] == old and change["candidateRecord"] == new
    affected = report["metadata"]["catalogAffectedObligations"]
    assert affected[f"relationship:{LINK}"] == OBLIGATIONS
    assert affected[f"recipe:{READER}"] == affected[f"recipe:{CONTEXT_READER}"] == OBLIGATIONS
    assert f"relationship:{UNASSESSED}" not in affected and f"recipe:{UNRELATED_READER}" not in affected
    assert not any("computation-review" in values or "requalification" in values for values in affected.values())
    assert PROFILE in report["metadata"]["unresolvedCatalogScope"]
    assert report["metadata"]["runtimeReuse"]["computation"]["status"] == "unknown"


@pytest.mark.parametrize("status", ["unknown", "failed"])
def test_assessment_status_changes_remain_visible_without_reclassifying_computation(status):
    base, candidate = snapshots()
    candidate["extensions"][DETAILS]["relationshipAssessments"][0].update(
        status=status, reason="Independent fixture no longer establishes this declaration.")
    assert base["relationships"] == candidate["relationships"]
    report = compare_catalogs(base, candidate)
    # A successful comparison preserves the candidate's separate support status.
    assert report["decision"] == "passed"
    change, = report["metadata"]["catalogChanges"].values()
    assert change["baseRecord"]["status"] == "supported" and change["candidateRecord"]["status"] == status
    assert change["obligations"] == OBLIGATIONS and change["domainEffects"]["status"] == "unknown"
    assert report["metadata"]["catalogAffectedObligations"][f"recipe:{READER}"] == OBLIGATIONS
    assert report["metadata"]["catalogAffectedObligations"][f"recipe:{CONTEXT_READER}"] == OBLIGATIONS
    assert change["identity"] in report["metadata"]["unresolvedCatalogScope"]
    complete = compare_catalogs(base, candidate, require_complete_scope=True)
    assert complete["decision"] == "incomplete"


def test_selected_but_unused_profile_changes_do_not_create_relationship_dependencies():
    base, candidate = snapshots()
    for catalog in (base, candidate):
        catalog["extensions"][DETAILS]["relationshipAssessments"] = []
    candidate["extensions"][DETAILS]["relationshipProfile"]["source"]["sha256"] = "c" * 64
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    assert list(report["metadata"]["catalogChanges"]) == [f"relationship-profile:{PROFILE}"]
    assert not report["impact"]["affected"] and not report["metadata"]["catalogAffectedObligations"]


def test_an_assessed_relationship_outside_the_snapshot_stays_explicitly_unresolved():
    base, candidate = snapshots()
    for catalog in (base, candidate):
        catalog["extensions"][DETAILS]["relationshipAssessments"][0]["relationship"] = "urn:test:impact:outside-snapshot"
    candidate["extensions"][DETAILS]["relationshipProfile"]["source"]["sha256"] = "c" * 64
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    assert "urn:test:impact:outside-snapshot" in report["metadata"]["unresolvedCatalogScope"]
    assert not any(name.startswith("recipe:") for name in report["metadata"]["catalogAffectedObligations"])


@pytest.mark.parametrize("malformed", ["provenance", "profile", "status", "duplicate", "existence"])
def test_incoherent_profile_assessments_are_not_silently_compared(malformed):
    base, candidate = snapshots()
    details = candidate["extensions"][DETAILS]
    if malformed == "provenance":
        details["relationshipProfile"].pop("source")
    elif malformed == "profile":
        details["relationshipAssessments"][0]["profile"]["version"] = "9.0.0"
    elif malformed == "status":
        details["relationshipAssessments"][0]["status"] = "passed"
    elif malformed == "existence":
        details["relationshipAssessments"][0]["externalExistence"] = "established"
    else:
        details["relationshipAssessments"].append(deepcopy(details["relationshipAssessments"][0]))
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "failed"
    codes = {diagnostic["code"] for check in report["checks"] for diagnostic in check["diagnostics"]}
    assert ("CATALOG-IMPACT-IDENTITY" if malformed == "duplicate" else "CATALOG-IMPACT-PROFILE") in codes


@pytest.mark.parametrize("change", ["version", "source"])
def test_public_profile_changes_preserve_provenance_with_unknown_assessment_and_consumer_scope(tmp_path, change):
    original = json.loads((COMMERCE / "project.ddk.json").read_bytes())
    for artifact in original["artifacts"].values():
        artifact["path"] = str(COMMERCE / artifact["path"])
    for recipe in original["catalog"]["recipes"]:
        recipe["sql"] = str(COMMERCE / recipe["sql"])
    rule = {"id": "urn:test:impact:public-comparison", "version": "1.0.0"}
    original["catalog"]["relationships"][0].update(match="project_rule", rule=rule)
    project = tmp_path / "project.ddk.json"
    project.write_text(json.dumps(original))
    here = Path(__file__).resolve()
    source = tmp_path / "retained-profile.py"
    source.write_bytes(here.read_bytes())
    private_reason = "private-assessment-reason:/private/profile/context"

    class PublicFixtureProfile:
        identity = {"id": PROFILE, "version": "1.0.0"}

        def __init__(self):
            self.source = source

        def assess(self, relationship):
            assert relationship.declaration["rule"] == rule
            assert [key.shared_type for key in relationship.source] == ["string"]
            assert [key.shared_type for key in relationship.target] == ["string"]
            return RelationshipAssessment("supported", private_reason)

    policy = tmp_path / "disclosure.json"
    policy.write_text(json.dumps({"identifiers": [
        "urn:example:commerce:catalog", "urn:example:commerce-project", "urn:example:commerce:product",
        "urn:example:commerce-datasets", "urn:example:commerce:dataset:orders", "urn:example:commerce:dataset:customers",
        "urn:example:commerce:dataset:daily-revenue", PROFILE, LINK, READER, rule["id"],
    ], "descriptions": True, "recipes": [READER]}))
    options = {"disclosure_policy": policy, "permitted_roots": (COMMERCE,)}
    before = assemble_catalog(project, relationship_profile=PublicFixtureProfile(), **options)
    if change == "source":
        source.write_bytes(source.read_bytes() + b"\n# Independent source provenance revision.\n")
    profile = PublicFixtureProfile()
    if change == "version":
        profile.identity = {**profile.identity, "version": "2.0.0"}
    after = assemble_catalog(project, relationship_profile=profile, **options)
    assert before.report["decision"] == after.report["decision"] == "passed"
    for result in (before, after):
        details = result.catalog["extensions"][DETAILS]
        assert details["scope"]["consumerCoverage"] == "unknown"
        assert details["relationshipAssessmentScope"]["status"] == "unknown"
        assert "relationshipAssessments" not in details
        assert any(row["id"] == LINK for row in result.catalog["relationships"])
        assert any(row["id"] == READER for row in result.catalog["recipes"])
        public = b"".join(result.artifacts.values())
        assert private_reason.encode() not in public and str(source).encode() not in public and str(here).encode() not in public
        assert result.local_report["metadata"]["relationshipAssessments"][0]["reason"] == private_reason
    report = compare_catalogs(before.catalog, after.catalog)
    assert report["decision"] == "passed", report
    changed = report["metadata"]["catalogChanges"][f"relationship-profile:{PROFILE}"]
    assert changed["obligations"] == OBLIGATIONS and changed["domainEffects"]["status"] == "unknown"
    assert changed["candidateRecord"]["assessmentScope"]["status"] == "unknown"
    assert not report["impact"]["affected"] and not report["metadata"]["catalogAffectedObligations"]
    assert any(value.startswith("urn:ddk:impact:relationship-assessment-scope:")
               for value in report["metadata"]["unresolvedCatalogScope"])
    complete = compare_catalogs(before.catalog, after.catalog, require_complete_scope=True)
    assert complete["decision"] == "incomplete"
