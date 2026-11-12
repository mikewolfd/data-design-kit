"""Generated catalog snapshot comparison with independently stated outcomes."""

from copy import deepcopy

from ddk.documents import read_json, validate_document
from ddk.impact import compare_catalogs, impact_projects

from test_core import COMMERCE, codes

CATALOG = COMMERCE / "catalog" / "catalog.ddk.json"
PROJECT = COMMERCE / "project.ddk.json"
ASSEMBLY = "urn:ddk:catalog:assembly"
REVENUE_VERSION = "urn:example:commerce:version:daily-revenue:fixture-01"
REVENUE_REPRESENTATION = "urn:example:commerce:representation:revenue-parquet"
REVENUE_RELATIONSHIP = "urn:example:commerce:relationship:customer"


def _snapshots():
    base = deepcopy(read_json(CATALOG).value)
    return base, deepcopy(base)


def _rule(version):
    return {
        "subject": REVENUE_VERSION,
        "rule": {"id": "urn:test:quality:unique-revenue-key", "version": version},
        "evaluator": {"id": "local-quality", "version": "1.0.0"},
        "scope": "All rows of the exact retained revenue file.",
    }


def test_access_change_preserves_exact_version_and_computation_meaning():
    base, candidate = _snapshots()
    representation, = candidate["representations"]
    representation["location"] = "https://data.example.org/new/revenue.parquet"
    report = compare_catalogs(base, candidate)
    assert not validate_document(report)
    assert report["decision"] == "passed"
    assert report["impact"]["changed"] == [{"identity": REVENUE_REPRESENTATION, "kinds": ["representation", "changed"]}]
    change = report["metadata"]["catalogChanges"][f"representation:{REVENUE_REPRESENTATION}"]
    assert change["baseRecord"]["version"] == change["candidateRecord"]["version"] == REVENUE_VERSION
    assert change["baseRecord"]["location"] != change["candidateRecord"]["location"]
    assert change["obligations"] == ["consumer-rebind", "metadata-regeneration"]
    assert change["computation"] == "unaffected-by-this-change"
    assert report["metadata"]["runtimeReuse"]["computation"]["status"] == "unknown"
    assert report["metadata"]["runtimeReuse"]["qualification"]["status"] == "unknown"
    assert any(entry["consumer"].startswith("recipe:") and entry["paths"][0][0] == f"representation:{REVENUE_REPRESENTATION}"
               for entry in report["impact"]["affected"])


def test_changed_rule_and_relationship_require_requalification_and_metadata():
    base, candidate = _snapshots()
    base["extensions"] = {ASSEMBLY: {"requiredQualityChecks": [_rule("baseline")]}}
    candidate["extensions"] = {ASSEMBLY: {"requiredQualityChecks": [_rule("candidate")]}}
    candidate["relationships"][0]["meaning"] = "Match the same composite customer identity for revenue review."
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    assert not validate_document(report)
    changes = report["metadata"]["catalogChanges"]
    assert changes[f"relationship:{REVENUE_RELATIONSHIP}"]["obligations"] == ["consumer-rebind", "metadata-regeneration"]
    rule_change, = (entry for key, entry in changes.items() if key.startswith("requested-quality:"))
    assert rule_change["obligations"] == ["metadata-regeneration", "requalification"]
    assert rule_change["computation"] == "unaffected-by-this-change"
    assert rule_change["candidateRecord"]["rules"][0]["subject"] == REVENUE_VERSION
    assert rule_change["candidateRecord"]["matchingPasses"] is False
    assert report["metadata"]["runtimeReuse"]["computation"]["status"] == "unknown"
    targets = report["metadata"]["catalogAffectedObligations"]
    assert any(name.startswith("recipe:") and "requalification" in values for name, values in targets.items())
    required = compare_catalogs(base, candidate, required_groups=["catalog.qualification"])
    assert required["decision"] == "incomplete"
    assert "CATALOG-IMPACT-QUALITY-SCOPE" in codes(required)


def test_loss_of_exact_quality_evidence_requires_requalification():
    base, candidate = _snapshots()
    rule = _rule("retained-rules")
    base["checks"].append({**rule, "status": "passed", "record": {"uri": "urn:test:quality:receipt"}})
    report = compare_catalogs(base, candidate, base_rules=[rule], candidate_rules=[rule])
    change, = (item for key, item in report["metadata"]["catalogChanges"].items() if key.startswith("requested-quality:"))
    assert change["baseRecord"]["matchingPasses"] is True
    assert change["candidateRecord"]["matchingPasses"] is False
    assert "requalification" in change["obligations"]


def test_complete_scope_request_preserves_excluded_consumers():
    base, candidate = _snapshots()
    base["extensions"] = {ASSEMBLY: {"scope": {"excludedConsumers": ["external-project"]}}}
    report = compare_catalogs(base, candidate, require_complete_scope=True)
    assert report["decision"] == "incomplete"
    assert "CATALOG-IMPACT-SCOPE" in codes(report)
    assert report["scope"]["excludedConsumers"] == ["external-project"]
    assert report["metadata"]["unresolvedCatalogScope"] == ["external-project"]


def test_publisher_selection_changes_without_reclassifying_data_versions():
    base, candidate = _snapshots()
    replacement = deepcopy(candidate["releases"][0])
    replacement["id"] = "urn:test:release:next"
    replacement["reference"]["value"] = "release-next"
    candidate["releases"].append(replacement)
    candidate["selections"][0]["release"] = replacement["id"]
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    assert set(tuple(item["kinds"]) for item in report["impact"]["changed"]) == {
        ("publisher-release", "added"), ("publisher-selection", "changed"),
    }
    change, = (item for key, item in report["metadata"]["catalogChanges"].items() if key.startswith("publisher-selection:"))
    assert change["baseRecord"][0]["release"] == base["releases"][0]["id"]
    assert change["candidateRecord"][0]["release"] == replacement["id"]
    assert "computation-review" not in change["obligations"]


def test_retains_native_key_provenance_and_keeps_qualification_separate():
    base, candidate = _snapshots()
    native = {
        "runtime": "test-runtime", "scheme": "urn:test:dataset-version", "schemeVersion": "1",
        "namespace": "example", "digestAlgorithm": "blake3",
        "reference": {"digest": "abc", "opaqueId": "2A"},
    }
    shared = {
        "authority": "urn:test:runtime",
        "computationKey": {"scheme": "urn:test:computation-key", "value": "native-computation-id"},
        "semantics": {"id": "urn:test:semantics", "revision": "1.0.0"},
        "candidate": native,
    }
    old = {**shared, "qualificationKey": {"scheme": "urn:test:qualification-key", "value": "alpha"},
           "rules": {"path": "old-rules.json", "sha256": "a" * 64}}
    new = {**shared, "qualificationKey": {"scheme": "urn:test:qualification-key", "value": "beta"},
           "rules": {"path": "new-rules.json", "sha256": "b" * 64}}
    report = compare_catalogs(base, candidate, base_reuse_records=[old], candidate_reuse_records=[new])
    assert not validate_document(report)
    reuse = report["metadata"]["runtimeReuse"]
    assert reuse["base"] == [old] and reuse["candidate"] == [new]
    assert reuse["computation"]["status"] == "same-recorded-identity"
    assert reuse["qualification"]["status"] == "changed-recorded-identity"
    relocated = {**old, "rules": {**old["rules"], "path": "relocated.json"}}
    report = compare_catalogs(base, candidate, base_reuse_records=[old], candidate_reuse_records=[relocated])
    assert report["metadata"]["runtimeReuse"]["qualification"]["status"] == "same-recorded-identity"


def test_combined_impact_rejects_catalog_from_another_project_revision():
    base, candidate = _snapshots()
    candidate["project"]["version"] = "7.0.0"
    report = impact_projects(PROJECT, PROJECT, base_catalog=base, candidate_catalog=candidate)
    assert report["decision"] == "failed"
    assert "CATALOG-IMPACT-SNAPSHOT" in codes(report)


def test_combined_impact_checks_generated_catalog_project_bytes():
    base, candidate = _snapshots()
    base["extensions"] = {ASSEMBLY: {"scope": {"projects": ["urn:example:commerce-project"]}}}
    candidate["extensions"] = deepcopy(base["extensions"])
    source = next(row for row in base["sourceInventory"] if row["role"] == "project")
    source["sha256"] = read_json(PROJECT).sha256
    stale = next(row for row in candidate["sourceInventory"] if row["role"] == "project")
    stale["sha256"] = "f" * 64
    report = impact_projects(PROJECT, PROJECT, base_catalog=base, candidate_catalog=candidate)
    assert report["decision"] == "failed"
    assert "CATALOG-IMPACT-SNAPSHOT" in codes(report)


def test_catalog_definition_changes_classify_quality_and_shape_separately():
    base, candidate = _snapshots()
    baseline = {"name": "daily_revenue", "properties": [{"name": "amount_cents", "logicalType": "integer"}]}
    old_revision = next(row["definition"] for row in base["datasets"] if row["alias"] == "daily-revenue")
    new_revision = next(row["definition"] for row in candidate["datasets"] if row["alias"] == "daily-revenue")
    assert old_revision["version"] == "1.0.0"
    new_revision["version"] = "2026-Q4"
    new_revision["source"]["sha256"] = "c" * 64
    quality_only = {**deepcopy(baseline), "quality": [{"id": "positive", "type": "sql"}]}
    base["extensions"] = {ASSEMBLY: {"datasetDefinitions": {"daily-revenue": baseline}}}
    candidate["extensions"] = {ASSEMBLY: {"datasetDefinitions": {"daily-revenue": quality_only}}}
    report = compare_catalogs(base, candidate)
    changed, = report["impact"]["changed"]
    assert (changed["baseVersion"], changed["candidateVersion"]) == ("1.0.0", "2026-Q4")
    change = report["metadata"]["catalogChanges"]["dataset:daily-revenue"]
    assert change["obligations"] == ["metadata-regeneration", "requalification"]
    assert change["computation"] == "unaffected-by-this-change"
    quality_only["properties"][0]["logicalType"] = "string"
    report = compare_catalogs(base, candidate)
    assert report["metadata"]["catalogChanges"]["dataset:daily-revenue"]["computation"] == "review-required"


def test_concept_changes_require_metadata_regeneration_and_rebind_on_carrier_datasets():
    base, candidate = _snapshots()
    concept = {
        "concept": "urn:example:commerce:catalog:concept:amount-cents",
        "definition": "amount-cents",
        "conceptKind": "attribute",
        "fields": [
            {"dataset": "orders", "path": [{"field": "amount_cents"}]},
            {"dataset": "daily-revenue", "path": [{"field": "amount_cents"}]},
        ],
    }
    base["concepts"] = [deepcopy(concept)]
    candidate["concepts"] = [{**deepcopy(concept), "canonicalUrls": ["https://example.org/amount-cents"],
                              "conceptKind": "identifier"}]
    report = compare_catalogs(base, candidate)
    assert not validate_document(report)
    assert report["decision"] == "passed"
    key = f"concept:{concept['concept']}"
    change = report["metadata"]["catalogChanges"][key]
    assert change["obligations"] == ["consumer-rebind", "metadata-regeneration"]
    assert change["computation"] == "unaffected-by-this-change"
    affected = report["metadata"]["catalogAffectedObligations"]
    assert "dataset:orders" in affected and "dataset:daily-revenue" in affected
    assert any(name.startswith("recipe:") and "metadata-regeneration" in values for name, values in affected.items())

