"""Cross-product metadata, shard validation, decaying-prose policy, join metrics, and public leak guard (T3.1, T3.2, T3.4, T3.6)."""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from ddk.catalog import _check_public_no_local_leak, assemble_catalog
from ddk.catalog_access import CatalogError
from ddk.catalog_delivery import load_catalog_artifacts, verify_catalog_pair
from ddk.core import check_project
from ddk.documents import validate_document


COMMERCE = Path(__file__).resolve().parents[2] / "examples" / "commerce"


def _copy_commerce(tmp_path: Path, name: str = "commerce") -> Path:
    dest = tmp_path / name
    shutil.copytree(COMMERCE, dest)
    return dest


def _edit_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _codes(report: dict) -> set[str]:
    return {diag["code"] for check in report["checks"] for diag in check.get("diagnostics", ())}


def _write_artifacts(directory: Path, artifacts: dict[str, bytes]) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    for rel, body in artifacts.items():
        dest = directory / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    return sha256(artifacts["catalog.lock.json"]).hexdigest()


def _commerce_identifiers(catalog: dict) -> list[str]:
    ids = {catalog["id"], catalog["project"]["id"]}
    for section in ("datasets", "products", "relationships", "versions", "representations", "releases", "recipes"):
        ids.update(row["id"] for row in catalog.get(section, ()))
    for rel in catalog.get("relationships", ()):
        if "external" in rel.get("target", {}):
            ids.add(rel["target"]["external"])
    ids.update(row["definition"]["contractId"] for row in catalog["datasets"])
    return sorted(ids)


def test_representation_shards_dcat_bytesize_and_public_redaction(tmp_path):
    root = _copy_commerce(tmp_path, "valid-shards")
    shards = [
        {
            "path": "daily_revenue/part-000.parquet",
            "sha256": "1" * 64,
            "byteSize": 2000,
            "rowCount": 50,
            "rowRange": [0, 50],
        },
        {
            "path": "daily_revenue/part-001.parquet",
            "sha256": "2" * 64,
            "byteSize": 2800,
            "rowCount": 70,
            "rowRange": [50, 120],
        },
    ]

    def add_shards(meta):
        rep = meta["representations"][0]
        rep["byteSize"] = 4800
        rep["rowCount"] = 120
        rep["members"] = deepcopy(shards)

    _edit_json(root / "catalog/metadata.example.json", add_shards)

    has_rdflib = importlib.util.find_spec("rdflib") is not None
    exports = ("dcat", "graph") if has_rdflib else ()
    result = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
        exports=exports,
    )
    assert result.report["decision"] == "passed", result.report
    assert not validate_document(result.catalog)
    rep_row, = result.catalog["representations"]
    assert rep_row["byteSize"] == 4800
    assert rep_row["rowCount"] == 120
    assert rep_row["members"] == shards

    if has_rdflib:
        import rdflib

        dcat = rdflib.Namespace("http://www.w3.org/ns/dcat#")
        dist_uri = rdflib.URIRef("urn:example:commerce:representation:revenue-parquet")
        for doc_name in ("discovery.dcat.json", "discovery.graph.jsonld"):
            g = rdflib.Graph().parse(data=result.companions[doc_name], format="json-ld")
            size_lit = g.value(dist_uri, dcat.byteSize)
            assert size_lit == rdflib.Literal("4800", datatype=rdflib.XSD.decimal)

    # Public disclosure Case A1: available representation whose location is withheld is omitted entirely.
    policy_withheld_loc = root / "policy-no-loc.json"
    policy_withheld_loc.write_text(
        json.dumps({"identifiers": _commerce_identifiers(result.catalog), "descriptions": True}),
        encoding="utf-8",
    )
    paired_withheld = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
        disclosure_policy=policy_withheld_loc,
        include_private_artifacts=True,
    )
    assert paired_withheld.report["decision"] == "passed"
    assert paired_withheld.catalog["representations"] == []
    w_pub_dir, w_loc_dir = tmp_path / "pair-no-loc" / "pub", tmp_path / "pair-no-loc" / "loc"
    w_pub_pin = _write_artifacts(w_pub_dir, paired_withheld.artifacts)
    w_loc_pin = _write_artifacts(w_loc_dir, paired_withheld.local_artifacts)
    verify_catalog_pair(
        load_catalog_artifacts(w_pub_dir, expected_lock_sha256=w_pub_pin, audience="public"),
        load_catalog_artifacts(w_loc_dir, expected_lock_sha256=w_loc_pin, audience="local"),
    )

    # Public disclosure Case A2: unavailable representation without `location` retains `byteSize` and `rowCount`
    # while stripping `members` so member paths never leak without an explicit location grant.
    unavail_dir = _copy_commerce(tmp_path, "unavail-shards")

    def add_unavailable_shards(meta):
        rep = meta["representations"][0]
        rep["availability"] = "unavailable"
        rep.pop("location", None)
        rep["byteSize"] = 4800
        rep["rowCount"] = 120
        rep["members"] = deepcopy(shards)

    _edit_json(unavail_dir / "catalog/metadata.example.json", add_unavailable_shards)
    paired_unavail = assemble_catalog(
        unavail_dir / "project.ddk.json",
        metadata=unavail_dir / "catalog/metadata.example.json",
        metadata_adapter="example",
        disclosure_policy=policy_withheld_loc,
        include_private_artifacts=True,
    )
    assert paired_unavail.report["decision"] == "passed"
    pub_unavail_rep, = paired_unavail.catalog["representations"]
    assert pub_unavail_rep["byteSize"] == 4800 and pub_unavail_rep["rowCount"] == 120
    assert "location" not in pub_unavail_rep and "members" not in pub_unavail_rep
    u_pub_dir, u_loc_dir = tmp_path / "pair-unavail" / "pub", tmp_path / "pair-unavail" / "loc"
    u_pub_pin = _write_artifacts(u_pub_dir, paired_unavail.artifacts)
    u_loc_pin = _write_artifacts(u_loc_dir, paired_unavail.local_artifacts)
    verify_catalog_pair(
        load_catalog_artifacts(u_pub_dir, expected_lock_sha256=u_pub_pin, audience="public"),
        load_catalog_artifacts(u_loc_dir, expected_lock_sha256=u_loc_pin, audience="local"),
    )

    # Public disclosure Case B: location disclosed -> relative `members` retained and pair verifies.
    policy_disclosed_loc = root / "policy-with-loc.json"
    policy_disclosed_loc.write_text(
        json.dumps({
            "identifiers": _commerce_identifiers(result.catalog),
            "descriptions": True,
            "locations": [rep_row["location"]],
        }),
        encoding="utf-8",
    )
    paired_disclosed = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
        disclosure_policy=policy_disclosed_loc,
        include_private_artifacts=True,
    )
    assert paired_disclosed.report["decision"] == "passed"
    pub_rep_loc, = paired_disclosed.catalog["representations"]
    assert pub_rep_loc["members"] == shards
    d_pub_dir, d_loc_dir = tmp_path / "pair-with-loc" / "pub", tmp_path / "pair-with-loc" / "loc"
    d_pub_pin = _write_artifacts(d_pub_dir, paired_disclosed.artifacts)
    d_loc_pin = _write_artifacts(d_loc_dir, paired_disclosed.local_artifacts)
    verify_catalog_pair(
        load_catalog_artifacts(d_pub_dir, expected_lock_sha256=d_pub_pin, audience="public"),
        load_catalog_artifacts(d_loc_dir, expected_lock_sha256=d_loc_pin, audience="local"),
    )

    # Planted shard defects must each fail with `CATALOG-REPRESENTATION-SHARDS`.
    bad_cases = {
        "byte-sum-mismatch": lambda rep: rep.update(byteSize=9999),
        "row-range-gap": lambda rep: rep["members"][0].update(rowCount=40, rowRange=[0, 40]),
        "row-total-mismatch": lambda rep: rep.update(rowCount=150),
        "member-rowcount-mismatch": lambda rep: rep["members"][1].update(rowCount=69),
        "duplicate-member-path": lambda rep: rep["members"][1].update(path="daily_revenue/part-000.parquet"),
    }
    for label, plant in bad_cases.items():
        case_dir = _copy_commerce(tmp_path, f"bad-{label}")

        def apply_bad(meta, fn=plant):
            add_shards(meta)
            fn(meta["representations"][0])

        _edit_json(case_dir / "catalog/metadata.example.json", apply_bad)
        bad_res = assemble_catalog(
            case_dir / "project.ddk.json",
            metadata=case_dir / "catalog/metadata.example.json",
            metadata_adapter="example",
        )
        assert bad_res.report["decision"] == "failed", label
        assert "CATALOG-REPRESENTATION-SHARDS" in _codes(bad_res.report), label


def test_version_dates_and_coverage_bounds_lift_to_dcat_and_respect_disclosure(tmp_path):
    root = _copy_commerce(tmp_path, "dates-and-bounds")

    def add_dates_and_bounds(meta):
        orders_ver = next(v for v in meta["versions"] if v["dataset"] == "orders")
        orders_ver["dates"] = {
            "publishedAt": "2026-11-10T00:00:00Z",
            "retrievedAt": "2026-11-10T01:15:00Z",
            "sourceUpdatedAt": "2026-11-09T22:30:00Z",
        }
        orders_ver["coverage"] = [{
            "scope": "Calendar range of recorded order dates.",
            "unit": "calendar days",
            "status": "complete",
            "kind": "true_range",
            "stage": "published",
            "bounds": {"field": "order_day", "min": "2026-01-01", "max": "2026-10-31"},
            "record": {"uri": "https://data.example.org/commerce/evidence/example-metadata.json"},
        }]

    _edit_json(root / "catalog/metadata.example.json", add_dates_and_bounds)

    has_rdflib = importlib.util.find_spec("rdflib") is not None
    exports = ("dcat", "graph") if has_rdflib else ()
    result = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
        exports=exports,
    )
    assert result.report["decision"] == "passed", result.report
    assert not validate_document(result.catalog)
    orders_ver = next(v for v in result.catalog["versions"] if v["dataset"] == "orders")
    assert orders_ver["dates"]["publishedAt"] == "2026-11-10T00:00:00Z"
    cov, = orders_ver["coverage"]
    assert (cov["kind"], cov["stage"], cov["bounds"]) == (
        "true_range",
        "published",
        {"field": "order_day", "min": "2026-01-01", "max": "2026-10-31"},
    )

    if has_rdflib:
        import rdflib

        dcat = rdflib.Namespace("http://www.w3.org/ns/dcat#")
        ver_uri = rdflib.URIRef("urn:example:commerce:version:orders:fixture-01")
        for doc_name in ("discovery.dcat.json", "discovery.graph.jsonld"):
            g = rdflib.Graph().parse(data=result.companions[doc_name], format="json-ld")
            assert g.value(ver_uri, rdflib.DCTERMS.issued) == rdflib.Literal(
                "2026-11-10T00:00:00Z", datatype=rdflib.XSD.dateTime
            )
            assert g.value(ver_uri, rdflib.DCTERMS.modified) == rdflib.Literal(
                "2026-11-09T22:30:00Z", datatype=rdflib.XSD.dateTime
            )
            temporal = g.value(ver_uri, rdflib.DCTERMS.temporal)
            assert (temporal, rdflib.RDF.type, rdflib.DCTERMS.PeriodOfTime) in g
            assert g.value(temporal, dcat.startDate) == rdflib.Literal("2026-01-01", datatype=rdflib.XSD.date)
            assert g.value(temporal, dcat.endDate) == rdflib.Literal("2026-10-31", datatype=rdflib.XSD.date)

    # Public disclosure redacts `version.dates` when `descriptions: false` and retains it when `descriptions: true`.
    no_desc_policy = root / "no-desc.json"
    no_desc_policy.write_text(
        json.dumps({"identifiers": _commerce_identifiers(result.catalog), "descriptions": False}),
        encoding="utf-8",
    )
    redacted = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
        disclosure_policy=no_desc_policy,
        include_private_artifacts=True,
    )
    assert redacted.report["decision"] == "passed"
    pub_orders_ver = next(v for v in redacted.catalog["versions"] if v["id"] == orders_ver["id"])
    assert "dates" not in pub_orders_ver
    r_pub_dir, r_loc_dir = tmp_path / "redacted-dates" / "pub", tmp_path / "redacted-dates" / "loc"
    r_pub_pin = _write_artifacts(r_pub_dir, redacted.artifacts)
    r_loc_pin = _write_artifacts(r_loc_dir, redacted.local_artifacts)
    verify_catalog_pair(
        load_catalog_artifacts(r_pub_dir, expected_lock_sha256=r_pub_pin, audience="public"),
        load_catalog_artifacts(r_loc_dir, expected_lock_sha256=r_loc_pin, audience="local"),
    )

    # Inverted bounds (`min > max`) fail with `CATALOG-COVERAGE-CONFLICT`.
    bad_bounds_dir = _copy_commerce(tmp_path, "inverted-bounds")

    def invert_bounds(meta):
        add_dates_and_bounds(meta)
        orders = next(v for v in meta["versions"] if v["dataset"] == "orders")
        orders["coverage"][0]["bounds"] = {"field": "order_day", "min": "2026-12-01", "max": "2026-01-01"}

    _edit_json(bad_bounds_dir / "catalog/metadata.example.json", invert_bounds)
    bad_bounds = assemble_catalog(
        bad_bounds_dir / "project.ddk.json",
        metadata=bad_bounds_dir / "catalog/metadata.example.json",
        metadata_adapter="example",
    )
    assert bad_bounds.report["decision"] == "failed"
    assert "CATALOG-COVERAGE-CONFLICT" in _codes(bad_bounds.report)


def test_prose_no_decaying_facts_flags_volatile_counts_hashes_and_dates_and_honors_exceptions(tmp_path):
    root = _copy_commerce(tmp_path, "prose-policy")
    _edit_json(
        root / "policies/commerce.ddk.json",
        lambda pol: pol["rules"].append({"id": "no-decaying-prose", "check": "prose-no-decaying-facts"}),
    )

    # Clean authored prose passes offline check_project.
    clean = check_project(root / "project.ddk.json")
    assert clean["decision"] == "passed"
    prose_check, = [c for c in clean["checks"] if c["requirement"] == "DDK-POLICY-008"]
    assert prose_check["status"] == "passed"

    # Plant three decaying snapshot facts across ODCS dataset, shared definition, and ODPS product prose.
    digest_hex = "a3f5" * 16
    _edit_json(
        root / "datasets/commerce.odcs.json",
        lambda doc: doc["schema"][0].update(
            description="Orders table containing 4,150,219 rows from production capture."
        ),
    )
    _edit_json(
        root / "definitions/amount-cents.json",
        lambda doc: doc.update(description=f"Minor currency units verified against snapshot {digest_hex}."),
    )
    _edit_json(
        root / "catalog/product.odps.json",
        lambda doc: doc["description"].update(limitations="Complete through regional close as of 2026-11-01."),
    )

    flagged = check_project(root / "project.ddk.json")
    assert flagged["decision"] == "failed"
    prose_fail, = [c for c in flagged["checks"] if c["requirement"] == "DDK-POLICY-008"]
    assert prose_fail["status"] == "failed"
    assert len(prose_fail["diagnostics"]) == 3
    assert {d["code"] for d in prose_fail["diagnostics"]} == {"POLICY-PROSE-DECAYING-FACT"}

    # Scoped `artifacts: ["orders"]` reports only `orders` (1 diagnostic), and `severity: "warning"` does not block pass.
    _edit_json(
        root / "policies/commerce.ddk.json",
        lambda pol: pol["rules"][-1].update(artifacts=["orders"], severity="warning"),
    )
    warned = check_project(root / "project.ddk.json")
    assert warned["decision"] == "passed"
    warn_check, = [c for c in warned["checks"] if c["requirement"] == "DDK-POLICY-008"]
    assert warn_check["status"] == "failed" and not warn_check["required"]
    assert len(warn_check["diagnostics"]) == 1

    # Explicit `exceptions` for all three `(artifact, pointer)` sites allows error-severity rule to pass cleanly!
    def set_exceptions(pol):
        pol["rules"][-1] = {
            "id": "no-decaying-prose",
            "check": "prose-no-decaying-facts",
            "severity": "error",
            "exceptions": [
                {"artifact": "orders", "pointer": "/schema/0/description", "reason": "Historical benchmark note."},
                {"artifact": "amount-cents", "pointer": "/description", "reason": "Test vector reference."},
                {
                    "artifact": "commerce-product",
                    "pointer": "/description/limitations",
                    "reason": "Fixed archive cutoff.",
                },
            ],
        }

    _edit_json(root / "policies/commerce.ddk.json", set_exceptions)
    exempted = check_project(root / "project.ddk.json")
    assert exempted["decision"] == "passed"
    exempt_check, = [c for c in exempted["checks"] if c["requirement"] == "DDK-POLICY-008"]
    assert exempt_check["status"] == "passed"


def test_unresolved_relationships_join_metrics_external_target_and_job_production_schema(tmp_path):
    root = _copy_commerce(tmp_path, "join-metrics")

    def enrich_relationships(proj):
        rel = proj["catalog"]["relationships"][0]
        rel["unresolvedReason"] = "scope_boundary"
        rel["joinMetrics"] = {
            "matchedRows": 95,
            "totalSourceRows": 100,
            "floorPct": 90.0,
            "basis": "Fixture release orders vs customers",
            "record": {"uri": "https://data.example.org/commerce/evidence/join-metrics.json"},
        }
        proj["catalog"]["relationships"].append({
            "id": "urn:example:commerce:relationship:external-tax-authority",
            "source": {"dataset": "orders", "paths": [[{"field": "order_id"}]]},
            "target": {
                "external": "https://tax.example.gov/filings",
                "externalDataset": "tax_filings",
                "externalKeyFields": ["order_reference"],
                "limitations": "External authority publishes quarterly with 90-day lag.",
            },
            "match": "equal",
            "cardinality": "many_to_one",
            "scope": "external",
            "resolution": "external",
            "unresolvedReason": "unmeasured",
            "meaning": "Cross-reference order to external tax authority filing.",
            "nulls": "reject",
        })

    _edit_json(root / "project.ddk.json", enrich_relationships)
    res = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
    )
    assert res.report["decision"] == "passed", res.report
    assert not validate_document(res.catalog)

    by_id = {r["id"]: r for r in res.catalog["relationships"]}
    cust_rel = by_id["urn:example:commerce:relationship:customer"]
    assert cust_rel["unresolvedReason"] == "scope_boundary"
    assert cust_rel["joinMetrics"]["matchedRows"] == 95
    ext_rel = by_id["urn:example:commerce:relationship:external-tax-authority"]
    assert ext_rel["target"] == {
        "external": "https://tax.example.gov/filings",
        "externalDataset": "tax_filings",
        "externalKeyFields": ["order_reference"],
        "limitations": "External authority publishes quarterly with 90-day lag.",
    }

    # Public disclosure redacts `joinMetrics.record.uri` unless granted in `evidence`
    # and paired public+local catalogs pass `verify_catalog_pair`.
    policy_path = root / "public-join.json"
    policy_path.write_text(
        json.dumps({"identifiers": _commerce_identifiers(res.catalog), "descriptions": True}),
        encoding="utf-8",
    )
    paired = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
        disclosure_policy=policy_path,
        include_private_artifacts=True,
    )
    assert paired.report["decision"] == "passed"
    pub_cust_rel = next(
        r for r in paired.catalog["relationships"] if r["id"] == "urn:example:commerce:relationship:customer"
    )
    assert pub_cust_rel["joinMetrics"] == {
        "matchedRows": 95,
        "totalSourceRows": 100,
        "floorPct": 90.0,
        "basis": "Fixture release orders vs customers",
        "record": {"uri": "urn:ddk:withheld"},
    }
    pub_ext_rel = next(
        r for r in paired.catalog["relationships"]
        if r["id"] == "urn:example:commerce:relationship:external-tax-authority"
    )
    assert pub_ext_rel["target"]["externalDataset"] == "tax_filings"
    p_pub_dir, p_loc_dir = tmp_path / "pair-join" / "pub", tmp_path / "pair-join" / "loc"
    p_pub_pin = _write_artifacts(p_pub_dir, paired.artifacts)
    p_loc_pin = _write_artifacts(p_loc_dir, paired.local_artifacts)
    verify_catalog_pair(
        load_catalog_artifacts(p_pub_dir, expected_lock_sha256=p_pub_pin, audience="public"),
        load_catalog_artifacts(p_loc_dir, expected_lock_sha256=p_loc_pin, audience="local"),
    )

    # Planted `matchedRows > totalSourceRows` fails with `CATALOG-JOIN-METRICS-RANGE`.
    _edit_json(
        root / "project.ddk.json",
        lambda proj: proj["catalog"]["relationships"][0]["joinMetrics"].update(matchedRows=101, totalSourceRows=100),
    )
    bad_metrics = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
    )
    assert bad_metrics.report["decision"] == "failed"
    assert "CATALOG-JOIN-METRICS-RANGE" in _codes(bad_metrics.report)

    # Verify unified `kind: "job"` artifact & `production.steps` schema contract.
    proj_doc = json.loads((COMMERCE / "project.ddk.json").read_text(encoding="utf-8"))
    proj_doc["artifacts"]["nightly-job"] = {"kind": "job", "path": "jobs/nightly.ddk.json"}
    assert not validate_document(proj_doc, "project")

    cat_doc = deepcopy(res.catalog)
    cat_doc["productions"].append({
        "alias": "nightly-job",
        "kind": "job",
        "identity": {"id": "urn:example:commerce:job:nightly", "version": "1.0.0"},
        "definition": {"uri": "https://data.example.org/commerce/jobs/nightly.ddk.json", "sha256": "c" * 64},
        "inputs": ["orders"],
        "outputs": ["daily-revenue"],
        "steps": [
            {"id": "aggregate_orders", "kind": "sql", "sqlSha256": "d" * 64},
            {"id": "export_revenue", "kind": "export"},
        ],
    })
    assert not validate_document(cat_doc, "catalog")


def test_public_no_local_leak_guard_catches_paths_cloud_uris_and_credentials(tmp_path):
    root = _copy_commerce(tmp_path, "leak-guard")
    baseline = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
    )
    ids = _commerce_identifiers(baseline.catalog)

    # Clean public view passes.
    clean_policy = root / "clean-public.json"
    clean_policy.write_text(json.dumps({"identifiers": ids, "descriptions": True}), encoding="utf-8")
    clean_pub = assemble_catalog(
        root / "project.ddk.json",
        metadata=root / "catalog/metadata.example.json",
        metadata_adapter="example",
        disclosure_policy=clean_policy,
        exports=("rml",),
    )
    assert clean_pub.report["decision"] == "passed"

    # End-to-end assemble_catalog catches a disclosed local filesystem path, s3:// URI, and URL credentials!
    for idx, leaked_text in enumerate([
        "Copied from /Users/alice/staging/orders.parquet during ingest.",
        "Backed by s3://internal-lake-bucket/commerce/orders.parquet.",
        "Fetched from https://etl_bot:s3cr3tPass@internal.example.org/orders.parquet.",
    ]):
        leak_dir = _copy_commerce(tmp_path, f"e2e-leak-{idx}")
        _edit_json(
            leak_dir / "datasets/commerce.odcs.json",
            lambda doc, txt=leaked_text: doc["schema"][0].update(description=txt),
        )
        leak_res = assemble_catalog(
            leak_dir / "project.ddk.json",
            metadata=leak_dir / "catalog/metadata.example.json",
            metadata_adapter="example",
            disclosure_policy=clean_policy,
        )
        assert leak_res.report["decision"] == "failed", leaked_text
        assert "CATALOG-PUBLIC-NO-LOCAL-LEAK" in _codes(leak_res.report), leaked_text

    # Direct unit sweep over every required leak pattern across both catalog JSON and companion bytes.
    for sample in (
        "/Users/alice/data.parquet",
        "/home/runner/work/data.parquet",
        "/private/tmp/run/data.parquet",
        "/private/var/tmp/data.parquet",
        "/var/folders/xx/yy/T/data.parquet",
        "C:\\Users\\alice\\data.parquet",
        "file:///data/orders.parquet",
        "s3://bucket/orders.parquet",
        "r2://bucket/orders.parquet",
        "gs://bucket/orders.parquet",
        "https://user:password@example.org/orders.parquet",
    ):
        tampered_cat = deepcopy(clean_pub.catalog)
        tampered_cat["datasets"][0]["description"] = f"Source: {sample}"
        with pytest.raises(CatalogError) as exc_info:
            _check_public_no_local_leak(tampered_cat, {}, {"identifiers": frozenset()})
        assert exc_info.value.code == "CATALOG-PUBLIC-NO-LOCAL-LEAK", sample

        with pytest.raises(CatalogError) as comp_exc:
            _check_public_no_local_leak(
                clean_pub.catalog,
                {"rml/orders.yarrrml.yml": ("mapping", f"# {sample}\n".encode("utf-8"))},
                {"identifiers": frozenset()},
            )
        assert comp_exc.value.code == "CATALOG-PUBLIC-NO-LOCAL-LEAK", sample
