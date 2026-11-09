"""Independent catalog expectations across definitions, metadata, and access."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from rdflib import Graph, Namespace, URIRef

from ddk.catalog import (
    CatalogError, build_catalog, compare_equal, relationship_keys, resolve_relationship, run_checked_query,
)
from ddk.documents import read_json, validate_document

ROOT = Path(__file__).resolve().parents[2]
COMMERCE = ROOT / "examples" / "commerce"
NESTED = ROOT / "examples" / "nested"
COMMERCE_PROJECT = COMMERCE / "project.ddk.json"
NESTED_PROJECT = NESTED / "project.ddk.json"
EXAMPLE = COMMERCE / "catalog" / "metadata.example.json"
ASSEMBLY = "urn:ddk:catalog:assembly"
AUTHORITY = "https://data.example.org/commerce"
RELEASE = "urn:example:commerce:release:fixture-01"
REVENUE = "urn:example:commerce:version:daily-revenue:fixture-01"
ORDERS = "urn:example:commerce:version:orders:fixture-01"
CUSTOMERS = "urn:example:commerce:version:customers:fixture-01"
RECIPE = "urn:example:commerce:recipe:daily-revenue"
RELATIONSHIP = "urn:example:register:relationship:citations"
DCAT = Namespace("http://www.w3.org/ns/dcat#")
DDK = Namespace("https://example.org/ddk/0.1/catalog#")


def write(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}


def diagnostics(report):
    return {item["code"] for check in report["checks"] for item in check["diagnostics"]}


def build_example(**kwargs):
    return build_catalog(COMMERCE_PROJECT, metadata=EXAMPLE, metadata_adapter="example", **kwargs)


def snapshot(path):
    return {str(item.relative_to(path)): item.read_bytes() for item in path.rglob("*") if item.is_file()}


def test_definition_only_catalog_preserves_port_resolution_and_has_no_observed_claims(tmp_path):
    output = tmp_path / "out"
    report = build_catalog(COMMERCE_PROJECT, exports=("dcat",), output=output)
    assert report["decision"] == "passed"
    assert not validate_document(report, "report")
    catalog = read_json(output / "catalog.ddk.json").value
    assert not validate_document(catalog, "catalog")
    assert {p["port"]: p["dataset"] for p in catalog["products"][0]["ports"]} == {
        "orders": "orders", "customers": "customers", "daily-revenue": "daily-revenue",
    }
    assert catalog["relationships"][0]["meaning"]
    assert any(item["id"] == RECIPE and item["dialect"] == "datafusion" for item in catalog["recipes"])
    assert not catalog["versions"] and not catalog["runs"] and not catalog["selections"]
    assert any("Availability" in item for item in report["coverage"]["mappingLimits"])
    assert "currentSelection" not in catalog
    assert not list(Graph().parse(output / "discovery.dcat.json", format="json-ld").triples(
        (None, DCAT.hasCurrentVersion, None)
    ))


def test_relocate_sql_and_bind_exact_versions_before_reader(tmp_path):
    authored = tmp_path / "source"
    shutil.copytree(COMMERCE, authored)
    expected_sql = (authored / "transforms" / "revenue.sql").read_bytes()
    output = tmp_path / "generated"
    assert build_catalog(authored / "project.ddk.json", metadata=EXAMPLE, metadata_adapter="example",
                         output=output)["decision"] == "passed"
    moved = Path(shutil.move(output, tmp_path / "relocated"))
    shutil.rmtree(authored)
    calls = []

    def reader(request):
        calls.append(request)
        assert request["sql"] == expected_sql
        assert {name: item["reference"]["value"] for name, item in request["inputs"].items()} == {
            "orders": "orders-01", "customers": "customers-01",
        }
        return {"result": [{"amount_cents": 42}], "receipt": {"id": "read-fixture"}}

    with pytest.raises(CatalogError, match="does not bind") as caught:
        run_checked_query(moved / "catalog.ddk.json", RECIPE, reader,
                          versions={"orders": REVENUE, "customers": CUSTOMERS})
    assert caught.value.code == "CATALOG-VERSION-MISMATCH"
    assert calls == []
    result = run_checked_query(moved / "catalog.ddk.json", RECIPE, reader,
                               versions={"orders": ORDERS, "customers": CUSTOMERS})
    assert result["binding"]["inputs"]["orders"]["id"] == ORDERS
    assert result["receipt"] == {"id": "read-fixture"}
    catalog = read_json(moved / "catalog.ddk.json").value
    recipe = next(item for item in catalog["recipes"] if item["id"] == RECIPE)
    (moved / recipe["sql"]).write_bytes(b"changed")
    with pytest.raises(CatalogError, match="differ from their catalog digest"):
        run_checked_query(moved / "catalog.ddk.json", RECIPE, reader,
                          versions={"orders": ORDERS, "customers": CUSTOMERS})
    assert len(calls) == 1


def test_atomic_refresh_and_dcat_current_selection(tmp_path):
    output = tmp_path / "set"
    options = {"output": output, "exports": ("dcat",), "current_selection": (AUTHORITY, "public-revenue")}
    assert build_example(**options)["decision"] == "passed"
    before = snapshot(output)
    assert build_example(**options)["decision"] == "passed"
    assert snapshot(output) == before
    graph = Graph().parse(output / "discovery.dcat.json", format="json-ld")
    logical = URIRef("urn:example:commerce:dataset:daily-revenue")
    assert (URIRef("urn:example:commerce:catalog"), DCAT.dataset, logical) in graph
    assert (logical, DCAT.hasCurrentVersion, URIRef(REVENUE)) in graph
    distribution = URIRef("urn:example:commerce:representation:revenue-parquet")
    assert (URIRef(REVENUE), DCAT.distribution, distribution) in graph
    assert graph.value(distribution, DCAT.downloadURL) == URIRef(
        "https://data.example.org/commerce/releases/fixture-01/daily_revenue.parquet"
    )
    assert graph.value(graph.value(logical, DDK.currentSelection), DDK.release) == URIRef(RELEASE)
    lock = read_json(output / "catalog.lock.json").value
    assert lock["catalogOptions"]["currentSelection"] == {"authority": AUTHORITY, "purpose": "public-revenue"}
    assert not validate_document(lock, "lock")
    unavailable = build_example(**{**options, "exports": ("dcat", "unavailable")})
    assert unavailable["decision"] == "incomplete"
    assert "ADAPTER-CAPABILITY-MISSING" in diagnostics(unavailable)
    assert snapshot(output) == before
    raw = deepcopy(read_json(EXAMPLE).value)
    raw["releases"].append({**raw["releases"][0], "id": "urn:example:another-release",
                            "reference": {**raw["releases"][0]["reference"], "value": "other"}})
    raw["selections"].append({**raw["selections"][0], "release": "urn:example:another-release",
                              "observedAt": "2001-01-01T00:00:00Z"})
    ambiguous = tmp_path / "ambiguous.json"
    for rows in (raw["selections"], list(reversed(raw["selections"]))):
        write(ambiguous, {**raw, "selections": rows})
        failed = build_catalog(COMMERCE_PROJECT, metadata=ambiguous, metadata_adapter="example", **options)
        assert failed["decision"] == "failed"
        assert "CATALOG-SELECTION-AMBIGUOUS" in diagnostics(failed)
        assert snapshot(output) == before


def test_public_discovery_withholds_native_location_and_evidence(tmp_path):
    output = tmp_path / "public"
    public_url = "https://data.example.org/commerce/releases/fixture-01/daily_revenue.parquet"
    distribution = "urn:example:commerce:representation:revenue-parquet"
    policy = tmp_path / "disclosure.json"
    write(policy, {"identifiers": [
        "urn:example:commerce:catalog", "urn:example:commerce-project", "urn:example:commerce:product",
        "urn:example:commerce-datasets", "urn:example:commerce:dataset:daily-revenue", REVENUE, distribution,
    ], "locations": [public_url]})
    report = build_example(output=output, exports="dcat", disclosure_policy=policy)
    assert report["decision"] == "passed", report
    data = b"".join(snapshot(output).values())
    assert str(COMMERCE).encode() not in data
    assert b"example-metadata.json" not in data
    assert b"daily-revenue-01" not in data
    assert b"SELECT" not in data
    assert b"CATALOG-RECIPE-WITHHELD" in data
    assert public_url.encode() in data
    catalog = read_json(output / "catalog.ddk.json").value
    assert catalog["versions"][0]["id"] == REVENUE
    assert catalog["versions"][0]["referenceDisclosure"] == "withheld"


def test_observed_partial_lineage_retains_existing_native_identity(tmp_path):
    raw = deepcopy(read_json(EXAMPLE).value)
    run = raw["runs"][0]
    run["inputs"] = [ORDERS]
    run["inputCoverage"]["status"] = "partial"
    unobserved = deepcopy(raw["sources"][0])
    unobserved["id"] = "urn:test:commerce:source:customers"
    unobserved["reference"]["value"] = "customers-capture-01"
    raw["sources"].append(unobserved)
    next(item for item in raw["versions"] if item["id"] == CUSTOMERS)["sources"].append(unobserved["id"])
    run["openLineageRunId"] = "1cd0c8e5-a233-5182-9f12-2898d5f0788f"
    raw["lineage"] = {
        "jobs": {"summarize": {"namespace": "example-scheduler", "name": "daily_revenue"}},
        "datasets": {ORDERS: {"namespace": "s3://example-bucket", "name": "orders.parquet", "version": "native-1"}},
    }
    metadata = tmp_path / "metadata.json"
    write(metadata, raw)
    output = tmp_path / "output"
    result = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="example",
                           exports="openlineage", output=output)
    assert result["decision"] == "passed", result
    events = [read_json(path).value for path in (output / "lineage").glob("*.json")]
    assert all(not validate_document(item, "openlineage") for item in events)
    complete = next(item for item in events if item.get("eventType") == "COMPLETE")
    assert complete["run"]["runId"] == run["openLineageRunId"]
    assert complete["job"] == {"namespace": "example-scheduler", "name": "daily_revenue"}
    assert len(complete["inputs"]) == 1
    assert complete["inputs"][0]["facets"]["version"]["datasetVersion"] == "native-1"
    assert complete["inputs"][0]["name"] == "orders.parquet"
    catalog = read_json(output / "catalog.ddk.json").value
    assert catalog["runs"][0]["inputCoverage"] == run["inputCoverage"]
    assert unobserved["id"] in {item["id"] for item in catalog["sources"]}
    assert CUSTOMERS not in catalog["runs"][0]["inputs"]
    assert catalog["extensions"][ASSEMBLY]["illustrativeMetadata"] is True
    raw["runs"][0]["outcome"] = "unknown"
    raw["runs"][0].pop("endedAt")
    write(metadata, raw)
    unresolved = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="example",
                               exports="openlineage", output=output)
    assert unresolved["decision"] == "passed"
    statuses = {read_json(path).value.get("eventType") for path in (output / "lineage").glob("*.json")}
    assert statuses == {None, "START"}
    saved = read_json(output / "catalog.ddk.json").value
    assert saved["runs"][0]["outcome"] == "unknown"
    assert any("no supported terminal event" in limit for limit in unresolved["coverage"]["mappingLimits"])


def test_missing_or_stale_evidence_does_not_qualify_discovery(tmp_path):
    raw = deepcopy(read_json(EXAMPLE).value)
    raw.pop("illustrative")
    check = raw["checks"][0]
    identity = {key: check[key] for key in ("subject", "rule", "evaluator", "scope")}
    raw["qualification"] = [identity]
    metadata = tmp_path / "metadata.json"
    write(metadata, raw)
    kwargs = {"metadata": metadata, "metadata_adapter": "local"}
    incomplete = build_catalog(COMMERCE_PROJECT, **kwargs)
    assert incomplete["decision"] == "incomplete"
    assert "CATALOG-EVIDENCE-MISSING" in diagnostics(incomplete)
    catalog = incomplete["metadata"]["catalog"]
    assert catalog["runs"][0]["outcome"] == "succeeded"
    assert any(item["id"] == REVENUE for item in catalog["versions"])
    assert any(item["version"] == REVENUE and item["availability"] == "available" for item in catalog["representations"])
    assert any(item["status"] == "not_run" and item["required"] for item in incomplete["checks"])

    old = "urn:test:version:revenue:old"
    current = next(item for item in raw["versions"] if item["id"] == REVENUE)
    raw["versions"].append({**current, "id": old, "reference": {**current["reference"], "value": "revenue-old"}})
    native_check = write(tmp_path / "quality-old.json", {"subject": old, "rule": identity["rule"], "status": "passed"})
    raw["checks"] = [{**identity, "subject": old, "status": "passed",
                      "record": {"uri": Path(native_check["path"]).as_uri(), "sha256": native_check["sha256"]}}]
    raw["qualification"][0]["rule"] = {**identity["rule"], "version": "2.0.0"}
    write(metadata, raw)
    stale = build_catalog(COMMERCE_PROJECT, **kwargs)
    assert stale["decision"] == "incomplete"
    assert "CATALOG-EVIDENCE-SCOPE" in diagnostics(stale)
    assert any(item["status"] == "unknown" and item["required"] for item in stale["checks"])
    [preserved] = stale["metadata"]["catalog"]["checks"]
    assert preserved["subject"] == old and preserved["status"] == "passed"


def _row(source):
    row = deepcopy(source)
    row["record.id"] = bytes.fromhex(row["record.id"])
    row["issued_on"] = date.fromisoformat(row["issued_on"])
    row["citations"] = [_row({**citation, "citations": []}) for citation in row["citations"]]
    return row


def test_nested_paths_preserve_literal_dot_order_types_and_scope(tmp_path):
    result = build_catalog(NESTED_PROJECT)
    assert result["decision"] == "passed", result
    catalog = result["metadata"]["catalog"]
    link = next(item for item in catalog["relationships"] if item["id"] == RELATIONSHIP)
    sample = read_json(NESTED / "rows.expected.json").value
    rows = [_row(item) for item in sample["rows"]]
    matches = []
    for source_position, row in enumerate(rows):
        for citation_position, (source_key, positions) in enumerate(relationship_keys(row, link["source"]["paths"])):
            assert list(positions.values()) == [citation_position]
            for target_position, target in enumerate(rows):
                [(target_key, _)] = relationship_keys(target, link["target"]["paths"])
                if compare_equal(source_key, target_key, ("binary", "date"), "skip")["matched"]:
                    matches.append({"sourcePosition": source_position, "citationPosition": citation_position,
                                    "targetPosition": target_position})
    assert matches == sample["expectedCitationTargets"]
    assert not compare_equal(("A ",), ("A",), ("string",), "match")["matched"]
    assert not compare_equal((None,), (None,), ("integer",), "skip")["matched"]
    assert compare_equal((None,), (None,), ("integer",), "match")["matched"]
    assert compare_equal((1,), (1,), ("integer",), "unknown")["status"] == "unknown"
    with pytest.raises(CatalogError) as null:
        compare_equal((None,), (None,), ("integer",), "reject")
    assert null.value.code == "CATALOG-KEY-NULL"
    with pytest.raises(CatalogError) as scope:
        resolve_relationship(catalog, "urn:example:register:relationship:next",
                             versions={"source": "urn:example:release:a", "target": "urn:example:release:b"})
    assert scope.value.code == "CATALOG-RELEASE-SCOPE"
    copied = tmp_path / "project"
    shutil.copytree(NESTED, copied)
    project = deepcopy(read_json(NESTED_PROJECT).value)
    for side in ("source", "target"):
        project["catalog"]["relationships"][0][side]["paths"].pop()
    write(copied / "project.ddk.json", project)
    incomplete = build_catalog(copied / "project.ddk.json")
    assert incomplete["decision"] == "failed"
    assert "CATALOG-KEY-INCOMPLETE" in diagnostics(incomplete)


NATIVE_TIME = "2026-02-03T04:05:06Z"
NATIVE_CHECK = "daily_revenue__region__field_is_present"
EXACT_FIELDS = "ddk:exact-field-names"
NATIVE_CHECK_ID = "8e16b836-801f-48cf-bbdf-7fb38d63ca80"


def _stage_receipt(tmp_path):
    from ddk.core import load_project

    alias, table = "daily-revenue", "daily_revenue"
    dataset = load_project(COMMERCE_PROJECT).resolve(alias).effective
    source = {"path": str(tmp_path / "source.csv"), "sha256": "1" * 64}
    output = {"path": str(tmp_path / "staged.parquet"), "sha256": "2" * 64, "rows": 1,
              "table": table, "loadId": "load-1", "size": 512}
    data_job = {"table_name": table, "job_id": "daily_revenue.file.parquet"}
    system_job = {"table_name": "_dlt_pipeline_state", "job_id": "_dlt_pipeline_state.state.jsonl.gz"}
    native = {
        "loads_ids": ["load-1"],
        "load_packages": [{"load_id": "load-1", "state": "loaded", "jobs": [data_job, system_job]}],
        "job_metrics": [
            {**data_job, "remote_url": Path(output["path"]).as_uri(), "load_id": "load-1",
             "file_size": 512, "state": "completed"},
            {**system_job, "load_id": "load-1", "state": "completed"},
        ],
    }
    request = write(tmp_path / "stage-request.json", {"dataset": deepcopy(dataset), "files": [source], "table": table})
    receipt = {"status": "passed", "sourceFiles": [source], "files": [output], "loadIds": ["load-1"],
               "normalizedTable": table,
               "request": request, "tool": {"name": "dlt", "version": "1.20.0"},
               "nativeReport": write(tmp_path / "load.json", native)}
    return receipt, native


def _quality_receipt(tmp_path, staged_file):
    from ddk.core import load_project
    from ddk.quality import dataset_rules

    initial = dataset_rules(load_project(COMMERCE_PROJECT).resolve("daily-revenue"))
    target = {"kind": "files", "files": [{key: staged_file[key] for key in ("path", "sha256")}]}
    required = [NATIVE_CHECK, EXACT_FIELDS]
    native = {"dataContractId": "urn:example:commerce-datasets", "dataContractVersion": "1.0.0",
              "datacontractCliVersion": "1.2.9", "dryRun": False, "timestampEnd": NATIVE_TIME,
              "result": "passed", "checks": [{"id": NATIVE_CHECK_ID, "key": NATIVE_CHECK, "result": "passed"}]}
    observed = {"target": target, "fields": ["order_day", "region", "amount_cents"], "model": "daily_revenue"}
    mapping = {"id": "urn:example:quality-mapping", "revision": "1"}
    return {
        "status": "passed", "evaluator": {"id": "urn:example:dcc", "version": "1.2.9"}, "target": target,
        "request": write(tmp_path / "quality-request.json", {**initial, "target": target}),
        "rules": write(tmp_path / "rules.json", {**initial, "requiredCheckIds": required, "mappingSemantics": mapping}),
        "mappingSemantics": mapping, "requiredCheckIds": required,
        "nativeReport": write(tmp_path / "native-quality.json", native),
        "schemaObservation": write(tmp_path / "observed-schema.json", observed),
        "observedFields": observed["fields"],
        "checks": [
            {"id": NATIVE_CHECK, "nativeCheckIds": [NATIVE_CHECK_ID], "status": "passed"},
            {"id": EXACT_FIELDS, "nativeCheckIds": [], "status": "passed"},
        ],
    }


def test_stage_requires_exact_completed_native_file_inventory(tmp_path):
    receipt, native = _stage_receipt(tmp_path)
    wrapper = tmp_path / "staging.json"
    metadata = tmp_path / "metadata.json"
    write(metadata, {"staging": [{"path": wrapper.name, "dataset": "daily-revenue"}]})

    write(wrapper, receipt)
    report = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="local")
    assert report["decision"] == "passed", report
    version, = report["metadata"]["catalog"]["versions"]
    source, = report["metadata"]["catalog"]["sources"]
    assert source["content"]["value"] == "1" * 64
    assert source["scope"] == "Daily revenue by date and region: source.csv. Source file recorded for this data load."
    assert version["reference"]["value"]["sha256"] == "2" * 64
    assert version["sources"] == [source["id"]]
    assert not (tmp_path / "source.csv").exists()
    assert not (tmp_path / "staged.parquet").exists()

    bad_size = deepcopy(receipt)
    bad_size["files"][0]["size"] += 1
    omitted = deepcopy(native)
    omitted["job_metrics"].append({**native["job_metrics"][0], "remote_url": (tmp_path / "omitted.parquet").as_uri()})
    missing_file = {**receipt, "nativeReport": write(tmp_path / "omitted.json", omitted)}
    incomplete = deepcopy(native)
    incomplete["job_metrics"][0]["state"] = "failed"
    uncompleted = {**receipt, "nativeReport": write(tmp_path / "incomplete.json", incomplete)}
    for invalid in (bad_size, missing_file, uncompleted):
        write(wrapper, invalid)
        failed = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="local")
        assert failed["decision"] == "failed"
        assert "CATALOG-STAGING-LOAD" in diagnostics(failed)


def test_quality_requires_raw_run_check_and_exact_schema_evidence(tmp_path):
    stage, _ = _stage_receipt(tmp_path)
    stage_ref = write(tmp_path / "staging.json", stage)
    receipt = _quality_receipt(tmp_path, stage["files"][0])
    native = deepcopy(read_json(receipt["nativeReport"]["path"]).value)
    native["checks"][0]["name"] = "The customer region field is present"
    receipt["nativeReport"] = write(Path(receipt["nativeReport"]["path"]), native)
    wrapper = tmp_path / "quality.json"
    manifest = tmp_path / "metadata.json"
    write(manifest, {"staging": [{**stage_ref, "dataset": "daily-revenue"}],
                     "quality": [{"path": wrapper.name, "dataset": "daily-revenue", "scope": "The entire staged file."}]})

    write(wrapper, receipt)
    report = build_catalog(COMMERCE_PROJECT, metadata=manifest, metadata_adapter="local")
    assert report["decision"] == "passed", report
    catalog = report["metadata"]["catalog"]
    assert len(catalog["checks"]) == 2
    assert any(check.get("reason") == "The customer region field is present — passed" for check in catalog["checks"])
    assert len(catalog["extensions"][ASSEMBLY]["requiredQualityChecks"]) == 2

    wrong_id = deepcopy(receipt)
    wrong_id["checks"][0]["nativeCheckIds"] = [NATIVE_CHECK_ID.replace("8e16", "0e16")]
    wrong_status = deepcopy(receipt)
    wrong_status["checks"][0]["status"] = "failed"
    omitted = deepcopy(receipt)
    omitted["checks"].pop(0)
    wrong_schema = deepcopy(receipt)
    wrong_schema["observedFields"] = ["order_day", "REGION", "amount_cents"]
    for malformed, code in (
        (wrong_id, "CATALOG-QUALITY-CONTRADICTION"), (wrong_status, "CATALOG-QUALITY-CONTRADICTION"),
        (omitted, "CATALOG-QUALITY-COVERAGE"), (wrong_schema, "CATALOG-QUALITY-CONTRADICTION"),
    ):
        write(wrapper, malformed)
        invalid = build_catalog(COMMERCE_PROJECT, metadata=manifest, metadata_adapter="local")
        assert invalid["decision"] == "failed", invalid
        assert code in diagnostics(invalid)

    no_schema = deepcopy(receipt)
    no_schema.pop("schemaObservation")
    write(wrapper, no_schema)
    incomplete = build_catalog(COMMERCE_PROJECT, metadata=manifest, metadata_adapter="local")
    assert incomplete["decision"] == "incomplete"
    assert "CATALOG-EVIDENCE-MISSING" in diagnostics(incomplete)
    assert {item["status"] for item in incomplete["metadata"]["catalog"]["checks"]} == {"passed", "not_run"}


def test_quality_explanation_preserves_failure_and_refuses_ambiguous_rule_meaning():
    from ddk.catalog_metadata import _quality_reason

    check = {"name": "Native amount check", "qualityId": "amount", "result": "failed",
             "reason": "Two negative values"}
    document = {"schema": [{"properties": [{"quality": [
        {"id": "amount", "description": "Amounts are zero or greater."},
    ]}]}]}
    assert _quality_reason(check, document) == "Amounts are zero or greater. — Two negative values"
    document["schema"].append({"quality": [{"id": "amount", "description": "Amounts are below the ceiling."}]})
    assert _quality_reason(check, document) == "Native amount check — Two negative values"
    assert _quality_reason(check, {"schema": []}) == "Native amount check — Two negative values"
    assert _quality_reason({"result": "unknown", "reason": "Evaluator stopped"}, {}) == "Evaluator stopped"


def test_docspec_capture_error_preserves_native_execution_without_observed_consumption(tmp_path):
    registered = {"path": str(tmp_path / "orders.parquet"), "sha256": "3" * 64,
                  "name": "orders", "format": "parquet"}
    output = {"path": str(tmp_path / "revenue.parquet"), "sha256": "4" * 64,
              "attributes": {"name": "result", "rows": 1, "size": 123}}
    request = write(tmp_path / "job.json", {
        "inputs": [{"name": "orders", "path": registered["path"], "kind": "parquet"}],
        "outputs": [{"name": "result", "path": output["path"]}],
    })
    wrapper = tmp_path / "job-receipt.json"
    receipt = {
        "request": request, "status": "error", "nativeOutcome": "succeeded", "stderrTruncated": True,
        "error": {"code": "DOCSPEC-DIAGNOSTIC-LIMIT"}, "endedAt": NATIVE_TIME,
        "inputs": [registered], "result": {"inputs": [{"name": "orders"}],
                                          "outputs": [{**output["attributes"], "sha256": output["sha256"]}]},
        "operation": {"runtime": "docspec", "mode": "bounded_job", "execution": "succeeded", "outputs": [output],
                      "requestIdentity": {"scheme": "urn:ddk:docspec-request:sha256", "value": request["sha256"]}},
        "tool": {"id": "docspec", "version": "0.1.0"},
    }
    write(wrapper, receipt)
    metadata = tmp_path / "metadata.json"
    write(metadata, {"executions": [{"path": wrapper.name, "production": "summarize",
                                    "inputs": {"orders": "orders"}, "outputs": {"result": "daily-revenue"}}]})
    output_set = tmp_path / "generated"
    report = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="local", output=output_set)
    assert report["decision"] == "error"
    assert {item["code"] for item in report["operationalErrors"]} == {"DOCSPEC-DIAGNOSTIC-LIMIT"}
    catalog = report["metadata"]["catalog"]
    run, = catalog["runs"]
    assert run["outcome"] == "succeeded"
    assert run["inputCoverage"]["status"] == "unknown"
    assert not run["inputs"]
    assert len(run["outputs"]) == 1
    assert catalog["extensions"][ASSEMBLY]["registeredRunInputs"][run["id"]].keys() == {"orders"}
    assert not output_set.exists()

    receipt["nativeOutcome"] = "failed"
    write(wrapper, receipt)
    contradiction = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="local")
    assert contradiction["decision"] == "failed"
    assert "CATALOG-NATIVE-RECEIPT" in diagnostics(contradiction)


def test_shared_content_keeps_two_source_occurrences_and_exact_definition(tmp_path):
    raw = deepcopy(read_json(EXAMPLE).value)
    first = raw["sources"][0]
    second = {**first, "id": "urn:test:orders:second-occurrence", "scope": "A different acquisition request.",
              "reference": {**first["reference"], "value": "orders-capture-02"},
              "record": {"uri": "urn:test:orders:source-receipt:02"}}
    raw["sources"].append(second)
    raw["versions"][0]["sources"].append(second["id"])
    metadata = tmp_path / "observations.json"
    write(metadata, raw)
    result = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="example")
    assert result["decision"] == "passed"
    catalog = result["metadata"]["catalog"]
    occurrences = {item["id"]: item for item in catalog["sources"]}
    assert set(occurrences) == {first["id"], second["id"]}
    assert occurrences[first["id"]]["content"] == occurrences[second["id"]]["content"]
    version = next(item for item in catalog["versions"] if item["id"] == ORDERS)
    assert set(version["sources"]) == {first["id"], second["id"]}
    definition = next(item["definition"] for item in catalog["datasets"] if item["alias"] == version["dataset"])
    assert definition["object"] == "orders"
    assert definition["source"]["sha256"] == sha256((COMMERCE / "datasets/commerce.odcs.json").read_bytes()).hexdigest()


def test_conflicting_version_reports_both_authority_records(tmp_path):
    raw = deepcopy(read_json(EXAMPLE).value)
    first = raw["versions"][0]
    second = {**first, "retention": "missing", "record": {"uri": "urn:test:orders:retention:second"}}
    raw["versions"].append(second)
    metadata = tmp_path / "conflict.json"
    write(metadata, raw)
    result = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="example")
    assert result["decision"] == "failed"
    conflict, = [item for check in result["checks"] for item in check["diagnostics"]
                 if item["code"] == "CATALOG-AUTHORITY-CONFLICT"]
    assert {item["path"] for item in conflict["related"]} == {first["record"]["uri"], second["record"]["uri"]}


def test_port_binding_missing_or_wrong_revision(tmp_path):
    copy = tmp_path / "commerce"
    shutil.copytree(COMMERCE, copy)
    path = copy / "project.ddk.json"
    project = deepcopy(read_json(path).value)
    project["catalog"]["ports"] = [port for port in project["catalog"]["ports"] if port["port"] != "orders"]
    write(path, project)
    result = build_catalog(path)
    assert result["decision"] == "failed"
    assert "CATALOG-PORT-AMBIGUOUS" in diagnostics(result)

    project = deepcopy(read_json(COMMERCE_PROJECT).value)
    old_contract = deepcopy(read_json(copy / "datasets/commerce.odcs.json").value)
    old_contract["version"] = "0.8.0"
    write(copy / "datasets/previous.odcs.json", old_contract)
    project["artifacts"]["orders-previous"] = {**project["artifacts"]["orders"], "path": "datasets/previous.odcs.json"}
    next(port for port in project["catalog"]["ports"] if port["port"] == "orders")["dataset"] = "orders-previous"
    write(path, project)
    result = build_catalog(path)
    assert result["decision"] == "failed"
    assert "CATALOG-PORT-VERSION" in diagnostics(result)


def test_opaque_native_version_and_byte_digest_remain_distinct(tmp_path):
    raw = deepcopy(read_json(EXAMPLE).value)
    version = next(item for item in raw["versions"] if item["id"] == REVENUE)
    reference = {"scheme": "urn:test:storage:snapshot", "authority": "urn:test:publisher:warehouse",
                 "value": {"commitSequence": 9300000000000301, "byteSha256": "b" * 64}}
    version["reference"] = reference
    metadata = tmp_path / "metadata.json"
    write(metadata, raw)
    result = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="example")
    catalog = result["metadata"]["catalog"]
    assert result["decision"] == "passed"
    assert next(item for item in catalog["versions"] if item["id"] == REVENUE)["reference"] == reference
    assert catalog["representations"][0]["version"] == REVENUE


def test_new_release_preserves_historical_binding_and_run_inputs(tmp_path):
    from ddk.catalog import resolve_query

    project_dir = tmp_path / "commerce"
    shutil.copytree(COMMERCE, project_dir)
    project_path = project_dir / "project.ddk.json"
    project = deepcopy(read_json(project_path).value)
    project["catalog"]["relationships"][0]["scope"] = "same_release"
    write(project_path, project)
    raw = deepcopy(read_json(EXAMPLE).value)
    raw["releases"][0]["members"] = [ORDERS, CUSTOMERS, REVENUE]
    metadata = tmp_path / "metadata.json"
    write(metadata, raw)

    def catalog():
        result = build_catalog(project_path, metadata=metadata, metadata_adapter="example")
        assert result["decision"] == "passed"
        return result["metadata"]["catalog"]

    selector = {"authority": AUTHORITY, "purpose": "public-revenue"}
    old = catalog()
    historical = resolve_query(old, RECIPE, selection=selector)
    next_orders = "urn:test:version:orders:02"
    next_release = "urn:test:release:02"
    raw["versions"].append({**raw["versions"][0], "id": next_orders,
                            "reference": {**raw["versions"][0]["reference"], "value": "orders-02"}})
    raw["releases"].append({**raw["releases"][0], "id": next_release, "members": [next_orders, CUSTOMERS, REVENUE],
                            "reference": {**raw["releases"][0]["reference"], "value": "fixture-02"}})
    raw["selections"][0].update(release=next_release, observedAt="2026-12-01T12:00:00Z")
    write(metadata, raw)
    new = catalog()
    latest = resolve_query(new, RECIPE, selection=selector)
    replay = resolve_query(new, RECIPE, release=historical["release"]["id"])
    assert historical["selection"]["release"] == RELEASE
    assert latest["selection"]["release"] == next_release
    assert latest["inputs"]["orders"]["id"] == next_orders
    assert replay["inputs"] == historical["inputs"]
    assert new["runs"] == old["runs"]
    assert new["runs"][0]["inputs"] == [ORDERS, CUSTOMERS]


def test_empty_absent_and_failed_acquisition_keep_distinct_records(tmp_path):
    raw = deepcopy(read_json(EXAMPLE).value)
    version = next(item for item in raw["versions"] if item["id"] == REVENUE)
    version["coverage"] = [
        {"scope": "Published daily revenue table", "unit": "rows", "status": "complete",
         "observed": 0, "expected": 0, "record": version["record"]},
        {"scope": "Upstream reportable orders", "unit": "rows", "status": "unknown",
         "observed": 0, "record": version["record"]},
    ]
    source = raw["sources"][0]
    for outcome in ("empty", "confirmed_absent", "failed"):
        raw["sources"].append({"id": f"urn:test:acquisition:{outcome}", "outcome": outcome,
                               "scope": f"Acquisition report for {outcome}", "record": source["record"],
                               "reference": {**source["reference"], "value": outcome}})
    metadata = tmp_path / "states.json"
    write(metadata, raw)
    result = build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="example")
    assert result["decision"] == "passed"
    catalog = result["metadata"]["catalog"]
    published = next(item for item in catalog["versions"] if item["id"] == REVENUE)
    assert published["retention"] == "present"
    coverage = {item["status"]: item for item in published["coverage"]}
    assert coverage["complete"]["expected"] == coverage["complete"]["observed"] == 0
    assert "expected" not in coverage["unknown"]
    assert {item["outcome"] for item in catalog["sources"]} == {"retained", "empty", "confirmed_absent", "failed"}
    assert catalog["representations"][0]["availability"] == "available"
    assert REVENUE in catalog["releases"][0]["members"]


def test_dcat_preserves_historical_version_and_disjoint_current_selection(tmp_path):
    raw = deepcopy(read_json(EXAMPLE).value)
    old_revenue = "urn:test:revenue:historical"
    public_orders = "urn:test:release:orders"
    preview_revenue = "urn:test:release:preview"
    published = next(item for item in raw["versions"] if item["id"] == REVENUE)
    raw["versions"].append({**published, "id": old_revenue,
                            "reference": {**published["reference"], "value": "daily-revenue-old"}})
    for release_id, member, purpose in [(public_orders, ORDERS, "public-revenue"), (preview_revenue, old_revenue, "preview")]:
        previous = raw["releases"][0]
        raw["releases"].append({**previous, "id": release_id, "members": [member],
                                "reference": {**previous["reference"], "value": release_id}})
        raw["selections"].append({**raw["selections"][0], "release": release_id, "purpose": purpose})
    metadata = tmp_path / "selected.json"
    write(metadata, raw)
    result_path = tmp_path / "output"
    args = {"metadata": metadata, "metadata_adapter": "example", "output": result_path, "exports": "dcat"}
    result = build_catalog(COMMERCE_PROJECT, current_selection=(AUTHORITY, "public-revenue"), **args)
    assert result["decision"] == "passed"
    graph = Graph().parse(result_path / "discovery.dcat.json", format="json-ld")
    orders = URIRef("urn:example:commerce:dataset:orders")
    revenue = URIRef("urn:example:commerce:dataset:daily-revenue")
    assert set(graph.subject_objects(DCAT.hasCurrentVersion)) == {(orders, URIRef(ORDERS)), (revenue, URIRef(REVENUE))}
    assert (revenue, DCAT.hasVersion, URIRef(old_revenue)) in graph
    assert not list(graph.objects(URIRef(old_revenue), DCAT.distribution))
    assert build_catalog(COMMERCE_PROJECT, **args)["decision"] == "passed"
    graph = Graph().parse(result_path / "discovery.dcat.json", format="json-ld")
    assert not list(graph.subject_objects(DCAT.hasCurrentVersion))


def test_required_project_rule_remains_unknown_with_declared_relationship(tmp_path):
    copy = tmp_path / "nested"
    shutil.copytree(NESTED, copy)
    path = copy / "project.ddk.json"
    project = deepcopy(read_json(path).value)
    custom = project["catalog"]["relationships"][0]
    custom["match"] = "project_rule"
    custom["rule"] = {"id": "urn:test:register:rule", "version": "1.0.0"}
    write(path, project)
    result = build_catalog(path)
    assert result["decision"] == "incomplete"
    check, = [check for check in result["checks"] if check["subject"] == custom["id"]]
    assert check["required"] and check["status"] == "unknown"
    assert "CATALOG-MATCH-UNSUPPORTED" in diagnostics(result)
    assert custom in result["metadata"]["catalog"]["relationships"]


def test_fresh_process_refresh_reuses_receipts_without_payload_io(tmp_path):
    import subprocess
    import sys

    stage, _ = _stage_receipt(tmp_path)
    stage_ref = write(tmp_path / "staging.json", stage)
    quality = _quality_receipt(tmp_path, stage["files"][0])
    quality_ref = write(tmp_path / "quality.json", quality)
    payloads = [stage["sourceFiles"][0]["path"], stage["files"][0]["path"]]
    for path in payloads:
        Path(path).write_bytes(b"Payload access is prohibited for this metadata refresh.")
    metadata = tmp_path / "metadata.json"
    write(metadata, {
        "staging": [{**stage_ref, "dataset": "daily-revenue"}],
        "quality": [{**quality_ref, "dataset": "daily-revenue", "scope": "The entire staged file."}],
    })
    generated = tmp_path / "output"
    program = """
import os
import sys
from ddk.catalog import build_catalog
from ddk.documents import json_dumps

forbidden = set(sys.argv[4:])

def audit(event, args):
    if event == 'subprocess.Popen' or (
        event in {'open', 'shutil.copyfile'} and any(
            isinstance(arg, (str, bytes, os.PathLike)) and os.fsdecode(arg) in forbidden for arg in args
        )
    ):
        raise AssertionError('Catalog assembly attempted payload access or execution')

sys.addaudithook(audit)
report = build_catalog(sys.argv[1], metadata=sys.argv[2], metadata_adapter='local',
                       output=sys.argv[3], exports='dcat')
assert report['decision'] == 'passed', json_dumps(report)
"""
    command = [sys.executable, "-c", program, str(COMMERCE_PROJECT), str(metadata), str(generated), *payloads]
    subprocess.run(command, check=True, capture_output=True)
    before = snapshot(generated)
    subprocess.run(command, check=True, capture_output=True)
    assert before == snapshot(generated)
    assert not any(name.endswith((".parquet", ".csv")) for name in before)
    checks = read_json(generated / "catalog.report.json").value["checks"]
    assert sum(item["evidence"] == "executed" and item["group"] == "catalog.qualification" for item in checks) == 2


def test_openlineage_native_and_mapped_events_replay_into_one_receiver(tmp_path):
    from contextlib import closing
    import sqlite3

    native = [read_json(COMMERCE / "catalog" / f"{stage}.openlineage.json").value
              for stage in ("job", "start", "complete")]
    declared, _, complete = native
    raw = deepcopy(read_json(EXAMPLE).value)
    run = raw["runs"][0]
    run["openLineageRunId"] = complete["run"]["runId"]
    definition_aliases = ("orders", "customers", "daily-revenue")
    versions = [ORDERS, CUSTOMERS, REVENUE]
    raw["lineage"] = {
        "jobs": {"summarize": deepcopy(declared["job"])},
        "declaredDatasets": dict(zip(definition_aliases, (*declared["inputs"], *declared["outputs"]))),
        "datasets": {
            version: {"namespace": item["namespace"], "name": item["name"], "version": item["facets"]["version"]["datasetVersion"]}
            for version, item in zip(versions, (*complete["inputs"], *complete["outputs"]))
        },
    }
    metadata = tmp_path / "source.json"
    write(metadata, raw)
    output = tmp_path / "generated"
    assert build_catalog(COMMERCE_PROJECT, metadata=metadata, metadata_adapter="example",
                         exports="openlineage", output=output)["decision"] == "passed"
    generated = [read_json(path).value for path in (output / "lineage").glob("*.json")]
    catalog = read_json(output / "catalog.ddk.json").value
    mapping = catalog["extensions"][ASSEMBLY]["openLineageVersions"]
    exact = {item["id"]: item["reference"] for item in catalog["versions"]}
    originals = {item["id"]: item["reference"] for item in raw["versions"]}

    with closing(sqlite3.connect(":memory:")) as receiver:
        receiver.executescript("""
            CREATE TABLE job (ns TEXT, name TEXT, PRIMARY KEY (ns, name));
            CREATE TABLE run (ns TEXT, name TEXT, id TEXT, PRIMARY KEY (ns, name, id));
            CREATE TABLE dataset (ns TEXT, name TEXT, version TEXT, PRIMARY KEY (ns, name, version));
        """)
        for event in [*native, *generated, *generated, *native]:
            assert not validate_document(event, "openlineage")
            job = (event["job"]["namespace"], event["job"]["name"])
            receiver.execute("INSERT OR IGNORE INTO job VALUES (?, ?)", job)
            if "run" in event:
                receiver.execute("INSERT OR IGNORE INTO run VALUES (?, ?, ?)", (*job, event["run"]["runId"]))
            for item in (*event.get("inputs", ()), *event.get("outputs", ())):
                facet = item.get("facets", {}).get("version")
                if facet:
                    assert not validate_document(facet, "openlineage-version-facet")
                    pair = (item["namespace"], item["name"])
                    version = facet["datasetVersion"]
                    receiver.execute("INSERT OR IGNORE INTO dataset VALUES (?, ?, ?)", (*pair, version))
                    matched = [key for key, row in mapping.items()
                               if (row["namespace"], row["name"], row["datasetVersion"]) == (*pair, version)]
                    [known] = matched
                    assert exact[known] == originals[known]
        native_job = (declared["job"]["namespace"], declared["job"]["name"])
        assert receiver.execute("SELECT * FROM job").fetchall() == [native_job]
        assert receiver.execute("SELECT * FROM run").fetchall() == [(*native_job, complete["run"]["runId"])]
        native_datasets = {(item["namespace"], item["name"], item["facets"]["version"]["datasetVersion"])
                           for item in (*complete["inputs"], *complete["outputs"])}
        assert set(receiver.execute("SELECT * FROM dataset")) == native_datasets
    assert catalog["runs"][0]["openLineageRunId"] == complete["run"]["runId"]


def test_stage_empty_file_and_completed_load_without_file_remain_distinct(tmp_path):
    stage, native = _stage_receipt(tmp_path)
    stage["files"][0]["rows"] = 0
    normalized = {**native, "job_metrics": [{**metric, "items_count": 0} for metric in native["job_metrics"]]}
    stage.update(snapshotStatus="materialized", inputRows=0, normalizedRows=0,
                 discardedRows={"status": "observed", "count": 0},
                 nativeNormalizeReport=write(tmp_path / "normalize.json", normalized))
    path = tmp_path / "staging.json"
    manifest = tmp_path / "metadata.json"
    write(manifest, {"staging": [{"path": path.name, "dataset": "daily-revenue"}]})

    def catalog():
        write(path, stage)
        return build_catalog(COMMERCE_PROJECT, metadata=manifest, metadata_adapter="local")

    result = catalog()
    assert result["decision"] == "passed"
    built = result["metadata"]["catalog"]
    [version] = built["versions"]
    assert version["coverage"][0]["observed"] == 0
    [snapshot] = built["extensions"][ASSEMBLY]["stagingObservations"]
    assert snapshot["snapshotStatus"] == "materialized" and snapshot["versions"] == [version["id"]]
    assert built["representations"][0]["availability"] == "available"

    def without_data_jobs(report):
        return {**report, "load_packages": [{**report["load_packages"][0], "jobs": report["load_packages"][0]["jobs"][1:]}],
                "job_metrics": report["job_metrics"][1:]}

    stage.update(files=[], snapshotStatus="empty-no-file", inputRows=1,
                 discardedRows={"status": "observed", "count": 1},
                 nativeReport=write(tmp_path / "load-no-file.json", without_data_jobs(native)),
                 nativeNormalizeReport=write(tmp_path / "normalize-no-file.json", without_data_jobs(normalized)))
    result = catalog()
    assert result["decision"] == "passed"
    built = result["metadata"]["catalog"]
    [staging] = built["extensions"][ASSEMBLY]["stagingObservations"]
    assert staging["snapshotStatus"] == "empty-no-file" and staging["discardedRows"]["count"] == 1
    assert staging["sources"] == [built["sources"][0]["id"]]
    assert not built["versions"] and not built["representations"] and not staging["versions"]

    stage["nativeNormalizeReport"] = None
    result = catalog()
    assert result["decision"] == "failed"
    assert "CATALOG-STAGING-LOAD" in diagnostics(result)


def test_stage_refuses_renamed_table_or_missing_native_metrics(tmp_path):
    stage, native = _stage_receipt(tmp_path)
    wrapper = tmp_path / "staging.json"
    manifest = tmp_path / "metadata.json"
    write(manifest, {"staging": [{"path": wrapper.name, "dataset": "daily-revenue"}]})

    def refused(candidate, diagnostic):
        write(wrapper, candidate)
        result = build_catalog(COMMERCE_PROJECT, metadata=manifest, metadata_adapter="local")
        assert result["decision"] == "failed"
        assert diagnostic in diagnostics(result)
        assert "catalog" not in result.get("metadata", {})

    refused({**stage, "normalizedTable": "daily_revenue_renamed"}, "CATALOG-EVIDENCE-SCOPE")
    legacy = {key: value for key, value in stage.items() if key != "normalizedTable"}
    refused(legacy, "CATALOG-EVIDENCE-SCOPE")
    renamed = deepcopy(native)
    renamed["job_metrics"][0]["table_name"] = "daily_revenue_renamed"
    renamed["load_packages"][0]["jobs"][0]["table_name"] = "daily_revenue_renamed"
    empty = {**stage, "files": [], "snapshotStatus": "empty-no-file", "normalizedRows": 0,
             "inputRows": 1, "discardedRows": {"status": "observed", "count": 1}}
    refused({**empty, "nativeReport": write(tmp_path / "renamed-load.json", renamed)},
            "CATALOG-STAGING-LOAD")

    native_without_file = {
        **native, "load_packages": [{**native["load_packages"][0], "jobs": native["load_packages"][0]["jobs"][1:]}],
        "job_metrics": native["job_metrics"][1:],
    }
    empty["nativeReport"] = write(tmp_path / "no-file-load.json", native_without_file)
    missing_metrics = {**native, "job_metrics": native["job_metrics"][1:]}
    refused({**empty, "nativeNormalizeReport": write(tmp_path / "missing-normalize-metrics.json", missing_metrics)},
            "CATALOG-STAGING-LOAD")
    for normalized in (native, renamed):
        nonzero = {**normalized, "job_metrics": [{**metric, "items_count": 1} for metric in normalized["job_metrics"]]}
        refused({**empty, "nativeNormalizeReport": write(tmp_path / "nonzero-normalize.json", nonzero)},
                "CATALOG-STAGING-LOAD")
