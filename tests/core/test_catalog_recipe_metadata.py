"""Catalog metadata changes retain separate computation and quality consequences."""

from copy import deepcopy
from pathlib import Path

from ddk.catalog import assemble_catalog
from ddk.impact import compare_catalogs


COMMERCE = Path(__file__).resolve().parents[2] / "examples" / "commerce"
DETAILS = "urn:ddk:catalog:assembly"
RECIPE = "urn:example:commerce:recipe:checked-revenue"
LINK = "urn:example:commerce:relationship:customer"
REVENUE = "urn:example:commerce:version:daily-revenue:fixture-01"
METADATA = "metadata-regeneration"
REBIND = "consumer-rebind"
COMPUTE = "computation-review"
REQUALIFY = "requalification"


def _catalogs():
    result = assemble_catalog(COMMERCE / "project.ddk.json", metadata=COMMERCE / "catalog" / "metadata.example.json",
                              metadata_adapter="example")
    assert result.report["decision"] == "passed"
    return deepcopy(result.catalog), deepcopy(result.catalog)


def _recipe(catalog):
    return next(row for row in catalog["recipes"] if row["id"] == RECIPE)


def test_recipe_title_ordered_notes_and_context_are_metadata_with_reader_rechecks():
    base, candidate = _catalogs()
    _recipe(candidate).update(title="Qualified revenue reader", notes=["Upstream customer context.", "One output row per region/day."],
                              contextualRelationships=[LINK])
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    change = report["metadata"]["catalogChanges"][f"recipe:{RECIPE}"]
    assert change["obligations"] == [REBIND, METADATA]
    assert change["computation"] == "unaffected-by-this-change"
    assert _recipe(candidate)["inputs"] == {"daily_revenue": "daily-revenue"}


def test_contextual_table_shape_change_refreshes_docs_without_claiming_consumption():
    base, candidate = _catalogs()
    for catalog in (base, candidate):
        _recipe(catalog)["contextualRelationships"] = [LINK]
    candidate["extensions"][DETAILS]["datasetDefinitions"]["orders"]["properties"][0]["physicalType"] = "large_string"
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    assert report["metadata"]["catalogChanges"]["dataset:orders"]["obligations"] == [COMPUTE, METADATA]
    assert report["metadata"]["catalogAffectedObligations"][f"recipe:{RECIPE}"] == [REBIND, METADATA]
    assert all(COMPUTE not in values and REQUALIFY not in values
               for name, values in report["metadata"]["catalogAffectedObligations"].items() if name == f"recipe:{RECIPE}")


def test_real_input_dependency_retains_computation_review_alongside_context():
    base, candidate = _catalogs()
    for catalog in (base, candidate):
        _recipe(catalog)["inputs"]["orders"] = "orders"
        _recipe(catalog)["contextualRelationships"] = [LINK]
    candidate["extensions"][DETAILS]["datasetDefinitions"]["orders"]["properties"][0]["physicalType"] = "large_string"
    report = compare_catalogs(base, candidate)
    assert COMPUTE in report["metadata"]["catalogAffectedObligations"][f"recipe:{RECIPE}"]


def test_calculation_and_required_rule_changes_keep_distinct_obligations():
    base, candidate = _catalogs()
    candidate["productions"][0]["definition"]["sha256"] = "a" * 64
    rule = {"subject": REVENUE, "rule": {"id": "urn:test:catalog:required-total", "version": "1.0.0"},
            "evaluator": {"id": "independent-fixture", "version": "1.0.0"}, "scope": "The exact retained revenue version."}
    base["extensions"][DETAILS]["requiredQualityChecks"] = [rule]
    candidate["extensions"][DETAILS]["requiredQualityChecks"] = [{**rule, "rule": {**rule["rule"], "version": "2.0.0"}}]
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    changes = report["metadata"]["catalogChanges"]
    production, = [change for name, change in changes.items() if name.startswith("production:")]
    assert production["obligations"] == [COMPUTE, METADATA]
    quality, = [change for name, change in changes.items() if name.startswith("requested-quality:")]
    assert quality["obligations"] == [METADATA, REQUALIFY]
    assert quality["computation"] == "unaffected-by-this-change"
    assert report["metadata"]["runtimeReuse"]["computation"]["status"] == "unknown"


def test_scoped_unknown_extension_change_is_metadata_with_unresolved_domain_impact():
    base, candidate = _catalogs()
    source = {"project": {"id": "urn:example:commerce-project", "version": "1.0.0"}, "namespace": "",
              "extensions": {"urn:test:domain:upstream-relations": {"source": "original"}}}
    base["extensions"][DETAILS]["projectExtensions"] = [deepcopy(source)]
    candidate["extensions"][DETAILS]["projectExtensions"] = [deepcopy(source)]
    candidate["extensions"][DETAILS]["projectExtensions"][0]["extensions"]["urn:test:domain:upstream-relations"]["source"] = "corrected"
    report = compare_catalogs(base, candidate)
    assert report["decision"] == "passed"
    change, = report["metadata"]["catalogChanges"].values()
    assert change["obligations"] == [METADATA]
    assert change["identity"] in report["metadata"]["unresolvedCatalogScope"]
    assert change["candidateRecord"]["project"] == source["project"]
    assert change["candidateRecord"]["extension"] == "urn:test:domain:upstream-relations"
    assert not report["metadata"]["catalogAffectedObligations"]
