"""End-to-end conformance and runtime tests for DocSpec job productions (DDK-CATALOG-012) and S3a zero-counter SQL."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.catalog import assemble_catalog, build_catalog
from ddk.core import check_project
from ddk.documents import json_dumps, read_json, validate_document
from ddk.docspec_recipe_gate import DEFAULT_DOCSPEC_GATE_LIMITS
from ddk.impact import impact_projects
from ddk.odcs_sql_counters import compile_odcs_quality_counters


JOB_ID = "urn:example:job:daily-revenue"
CLEAN_SQL = "SELECT order_id, customer_id, order_day, amount_cents FROM orders WHERE status <> 'cancelled'"
SUMMARY_SQL = (
    "SELECT o.order_day, c.region, COALESCE(SUM(o.amount_cents), CAST(0 AS BIGINT)) AS amount_cents "
    "FROM clean_orders AS o "
    "INNER JOIN customers AS c ON o.customer_id = c.customer_id "
    "GROUP BY o.order_day, c.region"
)


@pytest.fixture
def docspec_bin():
    binary = os.environ.get("DDK_DOCSPEC_BIN") or os.environ.get("DDK_DOCSPEC_BINARY")
    if not binary:
        pytest.skip("Select the DocSpec runtime binary via DDK_DOCSPEC_BIN or DDK_DOCSPEC_BINARY")
    return binary


def _odcs_contract(contract_id: str, obj: dict) -> dict:
    return {
        "apiVersion": "v3.2.0",
        "kind": "DataContract",
        "id": contract_id,
        "version": "1.0.0",
        "status": "active",
        "schema": [obj],
    }


def _make_job_project(root: Path, *, with_quality_counters: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "contracts").mkdir(exist_ok=True)
    (root / "sql").mkdir(exist_ok=True)
    (root / "jobs").mkdir(exist_ok=True)

    orders_obj = {
        "name": "orders",
        "logicalType": "object",
        "properties": [
            {"name": "order_id", "logicalType": "string", "required": True},
            {"name": "customer_id", "logicalType": "string", "required": True},
            {"name": "order_day", "logicalType": "date", "required": True},
            {"name": "status", "logicalType": "string", "required": True},
            {"name": "amount_cents", "logicalType": "integer", "required": True},
        ],
    }
    customers_obj = {
        "name": "customers",
        "logicalType": "object",
        "properties": [
            {"name": "customer_id", "logicalType": "string", "required": True},
            {"name": "region", "logicalType": "string", "required": True},
        ],
    }
    revenue_obj = {
        "name": "daily_revenue",
        "logicalType": "object",
        "customProperties": [
            {"vendor": "ddk", "property": "rowIdentity", "value": ["order_day", "region"]},
        ],
        "properties": [
            {"name": "order_day", "logicalType": "date", "required": True},
            {"name": "region", "logicalType": "string", "required": True, "enum": [{"value": "NA"}, {"value": "EU"}]},
            {
                "name": "amount_cents",
                "logicalType": "integer",
                "required": True,
                "logicalTypeOptions": {"minimum": 0},
            },
        ],
        "quality": [
            {
                "id": "nonnegative-total",
                "type": "sql",
                "query": "SELECT COUNT(*) FROM ${object} WHERE \"amount_cents\" < 0",
                "mustBe": 0,
            }
        ],
    }

    (root / "contracts/orders.odcs.json").write_text(
        json_dumps(_odcs_contract("urn:example:contract:orders", orders_obj))
    )
    (root / "contracts/customers.odcs.json").write_text(
        json_dumps(_odcs_contract("urn:example:contract:customers", customers_obj))
    )
    (root / "contracts/daily-revenue.odcs.json").write_text(
        json_dumps(_odcs_contract("urn:example:contract:daily-revenue", revenue_obj))
    )

    (root / "sql/clean-orders.sql").write_text(CLEAN_SQL)
    (root / "sql/daily-revenue.sql").write_text(SUMMARY_SQL)

    queries = []
    quality_bindings = {}
    if with_quality_counters:
        compiled = compile_odcs_quality_counters(revenue_obj, "daily_revenue", query_name="revenue_counters")
        queries = compiled["queries"]
        for q in queries:
            q_rules = [r["id"] for r in compiled["rules"] if r["query"] == q["name"]]
            quality_bindings[q["name"]] = {"dataset": "daily-revenue", "rules": q_rules}

    job_spec = {
        "id": JOB_ID,
        "scratch": "scratch",
        "inputs": [
            {"kind": "parquet", "name": "orders", "path": "inputs/orders.parquet"},
            {"kind": "parquet", "name": "customers", "path": "inputs/customers.parquet"},
        ],
        "steps": [
            {"name": "clean_orders", "sql": CLEAN_SQL, "materialize": False},
            {"name": "daily_revenue", "sql": SUMMARY_SQL, "materialize": True},
        ],
        "outputs": [
            {
                "name": "daily_revenue",
                "path": "outputs/daily_revenue.parquet",
                "sql": "SELECT order_day, region, amount_cents FROM daily_revenue",
                "settings": {
                    "profile": "whole",
                    "row_group_rows": 8192,
                    "order_by": [
                        {"field": "order_day", "direction": "asc", "nulls": "nulls_last"},
                        {"field": "region", "direction": "asc", "nulls": "nulls_last"},
                    ],
                    "columns": ["order_day", "region", "amount_cents"],
                    "dictionary_columns": [],
                    "delta_columns": [],
                    "key_column": None,
                    "created_by": "ddk-job-test",
                    "footer_limit": 1 << 20,
                },
            },
        ],
        "queries": queries,
    }
    (root / "jobs/daily-revenue.job.json").write_text(json_dumps(job_spec))

    job_decl = {
        "specVersion": "0.1",
        "kind": "job",
        "id": JOB_ID,
        "version": "1.0.0",
        "jobSpec": "daily-revenue.job.json",
        "inputs": {"orders": "orders", "customers": "customers"},
        "outputs": {"daily_revenue": "daily-revenue"},
        "steps": {
            "clean_orders": "urn:example:recipe:clean-orders",
            "daily_revenue": "urn:example:recipe:daily-revenue",
        },
    }
    if quality_bindings:
        job_decl["qualityQueries"] = quality_bindings
    (root / "jobs/daily-revenue.job.ddk.json").write_text(json_dumps(job_decl))

    product = {
        "apiVersion": "v1.1.0",
        "kind": "DataProduct",
        "id": "urn:example:product:revenue",
        "version": "1.0.0",
        "name": "Daily Revenue",
        "status": "active",
        "inputPorts": [
            {"name": "orders", "version": "1.0.0", "contractId": "urn:example:contract:orders"},
            {"name": "customers", "version": "1.0.0", "contractId": "urn:example:contract:customers"},
        ],
        "outputPorts": [
            {"name": "daily-revenue", "version": "1.0.0", "contractId": "urn:example:contract:daily-revenue"},
        ],
    }
    (root / "product.odps.json").write_text(json_dumps(product))

    project = {
        "specVersion": "0.1",
        "kind": "project",
        "id": "urn:example:job-only-project",
        "version": "1.0.0",
        "artifacts": {
            "orders": {
                "kind": "dataset",
                "path": "contracts/orders.odcs.json",
                "object": "orders",
                "catalogId": "urn:example:dataset:orders",
                "role": "source_record",
                "origin": "publisher",
            },
            "customers": {
                "kind": "dataset",
                "path": "contracts/customers.odcs.json",
                "object": "customers",
                "catalogId": "urn:example:dataset:customers",
                "role": "source_record",
                "origin": "publisher",
            },
            "daily-revenue": {
                "kind": "dataset",
                "path": "contracts/daily-revenue.odcs.json",
                "object": "daily_revenue",
                "catalogId": "urn:example:dataset:daily-revenue",
                "role": "derived",
                "origin": "rule",
            },
            "revenue-product": {
                "kind": "product",
                "path": "product.odps.json",
            },
            "daily-revenue-job": {
                "kind": "job",
                "path": "jobs/daily-revenue.job.ddk.json",
            },
        },
        "imports": {},
        "requiredChecks": ["core.documents", "core.references", "core.datasets", "core.policies"],
        "catalog": {
            "id": "urn:example:catalog:revenue",
            "ports": [
                {"product": "revenue-product", "direction": "input", "port": "orders", "version": "1.0.0", "dataset": "orders"},
                {"product": "revenue-product", "direction": "input", "port": "customers", "version": "1.0.0", "dataset": "customers"},
                {"product": "revenue-product", "direction": "output", "port": "daily-revenue", "version": "1.0.0", "dataset": "daily-revenue"},
            ],
            "recipes": [
                {
                    "id": "urn:example:recipe:clean-orders",
                    "sql": "sql/clean-orders.sql",
                    "dialect": "datafusion",
                    "inputs": {"orders": "orders"},
                    "relationships": [],
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
                {
                    "id": "urn:example:recipe:daily-revenue",
                    "sql": "sql/daily-revenue.sql",
                    "dialect": "datafusion",
                    "inputs": {"clean_orders": "orders", "customers": "customers"},
                    "relationships": [],
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                    "resultDataset": "daily-revenue",
                },
            ],
        },
    }
    # Give clean_orders recipe its matching input schema (clean_orders reads orders)
    project["catalog"]["recipes"][1]["sql"] = "sql/daily-revenue-direct.sql"
    direct_summary_sql = (
        "SELECT o.order_day, c.region, COALESCE(SUM(o.amount_cents), CAST(0 AS BIGINT)) AS amount_cents "
        "FROM orders AS o "
        "INNER JOIN customers AS c ON o.customer_id = c.customer_id "
        "WHERE o.status <> 'cancelled' "
        "GROUP BY o.order_day, c.region"
    )
    (root / "sql/daily-revenue-direct.sql").write_text(direct_summary_sql)
    # Keep step 2 in JobSpec aligned with its mapped recipe SQL when steps maps daily_revenue -> daily-revenue recipe
    # Wait: clean_orders is step 1 (reads orders), daily_revenue is step 2 (reads clean_orders). Let's declare a clean-orders view dataset so step 2's recipe also binds cleanly!
    clean_orders_obj = {
        "name": "clean_orders",
        "logicalType": "object",
        "physicalType": "view",
        "properties": [
            {"name": "order_id", "logicalType": "string", "required": True},
            {"name": "customer_id", "logicalType": "string", "required": True},
            {"name": "order_day", "logicalType": "date", "required": True},
            {"name": "amount_cents", "logicalType": "integer", "required": True},
        ],
    }
    (root / "contracts/clean-orders.odcs.json").write_text(
        json_dumps(_odcs_contract("urn:example:contract:clean-orders", clean_orders_obj))
    )
    project["artifacts"]["clean-orders"] = {
        "kind": "dataset",
        "path": "contracts/clean-orders.odcs.json",
        "object": "clean_orders",
        "catalogId": "urn:example:dataset:clean-orders",
        "role": "derived",
        "origin": "rule",
    }
    project["catalog"]["recipes"][0]["resultDataset"] = "clean-orders"
    project["catalog"]["recipes"][1]["sql"] = "sql/daily-revenue.sql"
    project["catalog"]["recipes"][1]["inputs"] = {"clean_orders": "clean-orders", "customers": "customers"}

    project_path = root / "project.ddk.json"
    project_path.write_text(json_dumps(project))
    return project_path


def _write_input_parquets(data_dir: Path, *, negative_amount: bool = False, duplicate_region: bool = False) -> tuple[Path, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    orders_path = data_dir / "orders.parquet"
    customers_path = data_dir / "customers.parquet"

    orders_schema = pa.schema([
        pa.field("order_id", pa.string()),
        pa.field("customer_id", pa.string()),
        pa.field("order_day", pa.date32()),
        pa.field("status", pa.string()),
        pa.field("amount_cents", pa.int64()),
    ])
    customers_schema = pa.schema([
        pa.field("customer_id", pa.string()),
        pa.field("region", pa.string()),
    ])
    pq.write_table(
        pa.Table.from_pylist([
            {"order_id": "o1", "customer_id": "c1", "order_day": date(2026, 2, 1), "status": "paid", "amount_cents": -500 if negative_amount else 1200},
            {"order_id": "o2", "customer_id": "c2", "order_day": date(2026, 2, 1), "status": "cancelled", "amount_cents": 9999},
            {"order_id": "o3", "customer_id": "c2", "order_day": date(2026, 2, 1), "status": "paid", "amount_cents": 800},
        ], schema=orders_schema),
        orders_path,
    )
    cust_rows = [
        {"customer_id": "c1", "region": "NA"},
        {"customer_id": "c2", "region": "LATAM" if duplicate_region else "EU"},
    ]
    pq.write_table(pa.Table.from_pylist(cust_rows, schema=customers_schema), customers_path)
    return orders_path, customers_path


def _load_mutable_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _execute_real_job(project_dir: Path, run_dir: Path, docspec_bin: str, orders_path: Path, customers_path: Path) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    spec = _load_mutable_json(project_dir / "jobs/daily-revenue.job.json")
    spec["scratch"] = str(run_dir / "scratch")
    spec["inputs"] = [
        {"kind": "parquet", "name": "orders", "path": str(orders_path)},
        {"kind": "parquet", "name": "customers", "path": str(customers_path)},
    ]
    out_file = run_dir / "outputs" / "daily_revenue.parquet"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    spec["outputs"][0]["path"] = str(out_file)
    runtime_spec_path = run_dir / "request-job.json"
    runtime_spec_path.write_text(json_dumps(spec))

    adapter = DocSpecAdapter(docspec_bin, dict(DEFAULT_DOCSPEC_GATE_LIMITS), evidence_dir=run_dir / "evidence")
    digests = {
        str(orders_path): sha256(orders_path.read_bytes()).hexdigest(),
        str(customers_path): sha256(customers_path.read_bytes()).hexdigest(),
    }
    response = adapter.execute(spec, input_digests=digests, spec_path=runtime_spec_path)
    assert response["status"] == "succeeded", response
    return response


def test_job_production_binds_run_and_exports_openlineage(tmp_path, docspec_bin):
    project_dir = tmp_path / "project"
    project_path = _make_job_project(project_dir)

    # 1. Core offline checks + impact analysis on a pure job-only project (no components/designs).
    check_rep = check_project(project_path)
    assert check_rep["decision"] == "passed", check_rep

    changed_dir = tmp_path / "changed"
    import shutil
    shutil.copytree(project_dir, changed_dir)
    spec_copy = _load_mutable_json(changed_dir / "jobs/daily-revenue.job.json")
    spec_copy["steps"][0]["sql"] = CLEAN_SQL + " AND amount_cents >= 0"
    (changed_dir / "jobs/daily-revenue.job.json").write_text(json_dumps(spec_copy))
    impact = impact_projects(project_path, changed_dir / "project.ddk.json")
    assert "daily-revenue-job" in impact["metadata"]["affectedObligations"]
    assert "review-computation-and-requalification" in impact["metadata"]["affectedObligations"]["daily-revenue-job"]

    # 2. Execute real DocSpec job and bind bounded receipt into catalog + OpenLineage + RDF graph.
    orders_path, customers_path = _write_input_parquets(tmp_path / "data")
    run_resp = _execute_real_job(project_dir, tmp_path / "run", docspec_bin, orders_path, customers_path)

    manifest = {
        "executions": [{"path": run_resp["evidence"]["path"], "production": "daily-revenue-job"}],
    }
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json_dumps(manifest))

    out_dir = tmp_path / "catalog"
    report = build_catalog(
        project_path,
        metadata=metadata_path,
        metadata_adapter="local",
        required_groups=("catalog.jobs", "catalog.recipes"),
        exports=("dcat", "openlineage", "graph"),
        output=out_dir,
        permitted_roots=(tmp_path,),
        docspec=docspec_bin,
    )
    assert report["decision"] == "passed", report
    assert not validate_document(report, "report")

    catalog = read_json(out_dir / "catalog.ddk.json").value
    assert not validate_document(catalog, "catalog")
    prod = next(p for p in catalog["productions"] if p["alias"] == "daily-revenue-job")
    assert prod["kind"] == "job"
    assert prod["identity"]["id"] == JOB_ID
    assert [s["id"] for s in prod["steps"]] == ["clean_orders", "daily_revenue"]
    assert [s["kind"] for s in prod["steps"]] == ["view", "sql"]
    assert [s["sqlSha256"] for s in prod["steps"]] == [
        sha256(CLEAN_SQL.encode("utf-8")).hexdigest(),
        sha256(SUMMARY_SQL.encode("utf-8")).hexdigest(),
    ]

    assert len(catalog["runs"]) == 1
    bound_run = catalog["runs"][0]
    assert bound_run["production"] == "daily-revenue-job"
    assert bound_run["outcome"] == "succeeded"
    assert bound_run["inputCoverage"]["status"] == "complete"
    assert len(bound_run["inputs"]) == 2
    assert len(bound_run["outputs"]) == 1

    # Representations carry rowCount and byteSize from dr-297r InputResult / OutputResult
    by_version = {r["version"]: r for r in catalog["representations"]}
    out_rep = by_version[bound_run["outputs"][0]]
    assert out_rep["rowCount"] == 2 and out_rep["byteSize"] > 0
    for inp_ver in bound_run["inputs"]:
        assert by_version[inp_ver]["byteSize"] > 0

    # OpenLineage emits events naming the DocSpec job production
    ol_events = [json.loads(p.read_text()) for p in sorted((out_dir / "lineage").glob("*.openlineage.json"))]
    assert any(ev.get("job", {}).get("name") == JOB_ID for ev in ol_events)
    run_ev = next(ev for ev in ol_events if "run" in ev)
    assert len(run_ev["inputs"]) == 2 and len(run_ev["outputs"]) == 1

    # Direct native JobResult JSON (without DDK receipt envelope) also binds cleanly when inputs/outputs match exact JobSpec
    direct_dir = tmp_path / "direct"
    direct_dir.mkdir()
    exact_spec = _load_mutable_json(project_dir / "jobs/daily-revenue.job.json")
    exact_spec["scratch"] = str(direct_dir / "scratch")
    exact_spec["inputs"] = [
        {"kind": "parquet", "name": "orders", "path": str(orders_path)},
        {"kind": "parquet", "name": "customers", "path": str(customers_path)},
    ]
    exact_spec["outputs"][0]["path"] = str(direct_dir / "out.parquet")
    (project_dir / "jobs/daily-revenue.job.json").write_text(json_dumps(exact_spec))
    adapter2 = DocSpecAdapter(docspec_bin, dict(DEFAULT_DOCSPEC_GATE_LIMITS), evidence_dir=direct_dir / "ev")
    direct_resp = adapter2.execute(
        exact_spec,
        input_digests={},
        spec_path=project_dir / "jobs/daily-revenue.job.json",
    )
    assert direct_resp["status"] == "succeeded", direct_resp
    raw_result_path = direct_dir / "job-result.json"
    raw_result_path.write_text(json_dumps(direct_resp["result"]))
    direct_meta = tmp_path / "direct-meta.json"
    direct_meta.write_text(json_dumps({
        "executions": [{
            "path": str(raw_result_path),
            "production": "daily-revenue-job",
            "startedAt": "2026-11-11T00:00:00Z",
            "endedAt": "2026-11-11T00:00:01Z",
        }]
    }))
    direct_assembled = assemble_catalog(
        project_path,
        metadata=direct_meta,
        metadata_adapter="local",
        required_groups=("catalog.jobs",),
        permitted_roots=(tmp_path,),
        docspec=docspec_bin,
        docspec_evidence_dir=direct_dir / "gate",
    )
    assert direct_assembled.report["decision"] == "passed", direct_assembled.report
    assert len(direct_assembled.catalog["runs"]) == 1


def test_job_step_sql_mismatch_with_recipe_fails(tmp_path):
    """CASE-CATALOG-012-STEP-SQL-DIFFERS: 1-byte difference between step SQL and recipe SQL fails."""
    project_dir = tmp_path / "project"
    project_path = _make_job_project(project_dir)
    spec = _load_mutable_json(project_dir / "jobs/daily-revenue.job.json")
    spec["steps"][0]["sql"] = CLEAN_SQL + " "  # 1-byte difference from sql/clean-orders.sql
    (project_dir / "jobs/daily-revenue.job.json").write_text(json_dumps(spec))

    result = assemble_catalog(project_path, required_groups=("catalog.jobs",))
    assert result.report["decision"] == "failed", result.report
    job_checks = [c for c in result.report["checks"] if c["group"] == "catalog.jobs"]
    assert job_checks and job_checks[0]["status"] == "failed"
    assert [d["code"] for d in job_checks[0]["diagnostics"]] == ["CATALOG-JOB-STEP-MISMATCH"]


def test_job_run_request_reordering_or_drift_fails(tmp_path, docspec_bin):
    """CASE-CATALOG-012-RUN-REQUEST-DIFFERS: reordering steps in the pinned request fails with CATALOG-NATIVE-RECEIPT."""
    project_dir = tmp_path / "project"
    project_path = _make_job_project(project_dir)
    orders_path, customers_path = _write_input_parquets(tmp_path / "data")
    run_resp = _execute_real_job(project_dir, tmp_path / "run", docspec_bin, orders_path, customers_path)

    # Reorder the two steps inside the pinned request file and update the receipt's request sha256
    receipt_path = Path(run_resp["evidence"]["path"])
    receipt = _load_mutable_json(receipt_path)
    req_path = Path(receipt["request"]["path"])
    req = _load_mutable_json(req_path)
    req["steps"] = list(reversed(req["steps"]))
    req_bytes = json_dumps(req).encode("utf-8")
    req_path.write_bytes(req_bytes)
    new_req_sha = sha256(req_bytes).hexdigest()
    receipt["request"]["sha256"] = new_req_sha
    receipt["operation"]["requestIdentity"]["value"] = new_req_sha
    receipt["result"]["job_spec_sha256"] = new_req_sha
    receipt_path.write_text(json_dumps(receipt))

    meta_path = tmp_path / "metadata.json"
    meta_path.write_text(json_dumps({"executions": [{"path": str(receipt_path), "production": "daily-revenue-job"}]}))
    result = assemble_catalog(
        project_path,
        metadata=meta_path,
        metadata_adapter="local",
        required_groups=("catalog.jobs",),
        permitted_roots=(tmp_path,),
    )
    assert result.report["decision"] == "failed", result.report
    codes = [d["code"] for c in result.report["checks"] for d in c["diagnostics"]]
    assert "CATALOG-NATIVE-RECEIPT" in codes


def test_job_spec_digest_or_id_mismatch_fails_bounded_and_managed(tmp_path, docspec_bin):
    """CASE-CATALOG-012-SPEC-DIGEST-DIFFERS: mismatched job_id or job_spec_sha256 fails with CATALOG-JOB-SPEC-MISMATCH."""
    project_dir = tmp_path / "project"
    project_path = _make_job_project(project_dir)
    orders_path, customers_path = _write_input_parquets(tmp_path / "data")
    run_resp = _execute_real_job(project_dir, tmp_path / "run", docspec_bin, orders_path, customers_path)

    # 1. Tamper job_spec_sha256 in bounded receipt
    receipt_path = Path(run_resp["evidence"]["path"])
    receipt = _load_mutable_json(receipt_path)
    receipt["result"]["job_spec_sha256"] = "0" * 64
    receipt_path.write_text(json_dumps(receipt))

    meta_path = tmp_path / "metadata.json"
    meta_path.write_text(json_dumps({"executions": [{"path": str(receipt_path), "production": "daily-revenue-job"}]}))
    bounded = assemble_catalog(
        project_path,
        metadata=meta_path,
        metadata_adapter="local",
        required_groups=("catalog.jobs",),
        permitted_roots=(tmp_path,),
    )
    assert bounded.report["decision"] == "failed"
    assert "CATALOG-JOB-SPEC-MISMATCH" in [d["code"] for c in bounded.report["checks"] for d in c["diagnostics"]]

    # 2. Tamper job_id in JobSpec vs job.ddk.json declaration
    bad_spec_dir = tmp_path / "bad-spec-project"
    import shutil
    shutil.copytree(project_dir, bad_spec_dir)
    bad_spec = _load_mutable_json(bad_spec_dir / "jobs/daily-revenue.job.json")
    bad_spec["id"] = "urn:example:job:wrong-id"
    (bad_spec_dir / "jobs/daily-revenue.job.json").write_text(json_dumps(bad_spec))
    bad_static = assemble_catalog(bad_spec_dir / "project.ddk.json", required_groups=("catalog.jobs",))
    assert bad_static.report["decision"] == "failed"
    assert "CATALOG-JOB-SPEC-MISMATCH" in [d["code"] for c in bad_static.report["checks"] for d in c["diagnostics"]]


def test_whole_job_docspec_gate_catches_invalid_unmapped_step_and_missing_docspec_is_not_run(tmp_path, docspec_bin):
    project_dir = tmp_path / "project"
    project_path = _make_job_project(project_dir)

    # Drop step->recipe mapping so the job relies on the whole-job DocSpec gate
    decl = _load_mutable_json(project_dir / "jobs/daily-revenue.job.ddk.json")
    decl.pop("steps")
    (project_dir / "jobs/daily-revenue.job.ddk.json").write_text(json_dumps(decl))

    # Offline without --docspec: required catalog.jobs is not_run (incomplete)
    offline = assemble_catalog(project_path, required_groups=("catalog.jobs",))
    assert offline.report["decision"] == "incomplete"
    job_checks = [c for c in offline.report["checks"] if c["group"] == "catalog.jobs"]
    assert any(c["status"] == "not_run" and c["diagnostics"][0]["code"] == "ADAPTER-CAPABILITY-MISSING" for c in job_checks)

    # With --docspec: valid JobSpec passes prepare-job + 0-row execution + output schema check
    online = assemble_catalog(
        project_path,
        required_groups=("catalog.jobs",),
        docspec=docspec_bin,
        docspec_evidence_dir=tmp_path / "ev-ok",
    )
    assert online.report["decision"] == "passed", online.report

    # Inject dr-kg49 implicit cast inside step 1 SQL -> fails catalog.jobs
    spec = _load_mutable_json(project_dir / "jobs/daily-revenue.job.json")
    spec["steps"][0]["sql"] = "SELECT order_id, customer_id, order_day, amount_cents FROM orders WHERE amount_cents = 'zero'"
    (project_dir / "jobs/daily-revenue.job.json").write_text(json_dumps(spec))
    broken = assemble_catalog(
        project_path,
        required_groups=("catalog.jobs",),
        docspec=docspec_bin,
        docspec_evidence_dir=tmp_path / "ev-bad",
    )
    assert broken.report["decision"] == "failed", broken.report
    broken_codes = [d["code"] for c in broken.report["checks"] if c["group"] == "catalog.jobs" for d in c["diagnostics"]]
    assert "CATALOG-RECIPE-TYPE" in broken_codes


def test_job_zero_counter_quality_queries_qualify_and_reject_violations_and_tampered_sql(tmp_path, docspec_bin):
    """CASE-CATALOG-012-QUALITY-COUNTERS: S3a ODCS -> DocSpec zero-counter SQL lowering."""
    project_dir = tmp_path / "project"
    project_path = _make_job_project(project_dir, with_quality_counters=True)

    # 1. Clean data: all zero-counters evaluate to 0 -> catalog.qualification passes with zero DuckDB scans!
    orders_ok, customers_ok = _write_input_parquets(tmp_path / "data-ok")
    run_ok = _execute_real_job(project_dir, tmp_path / "run-ok", docspec_bin, orders_ok, customers_ok)
    meta_ok = tmp_path / "meta-ok.json"
    meta_ok.write_text(json_dumps({"executions": [{"path": run_ok["evidence"]["path"], "production": "daily-revenue-job"}]}))

    res_ok = assemble_catalog(
        project_path,
        metadata=meta_ok,
        metadata_adapter="local",
        required_groups=("catalog.jobs", "catalog.qualification"),
        permitted_roots=(tmp_path,),
        docspec=docspec_bin,
        docspec_evidence_dir=tmp_path / "gate-ok",
    )
    assert res_ok.report["decision"] == "passed", res_ok.report
    assert len(res_ok.catalog["checks"]) >= 6
    assert all(c["status"] == "passed" and c["evaluator"]["id"] == "docspec" for c in res_ok.catalog["checks"])

    # 2. Violating data (negative amount_cents and invalid enum region): zero-counters > 0 -> catalog.qualification fails!
    orders_bad, customers_bad = _write_input_parquets(
        tmp_path / "data-bad", negative_amount=True, duplicate_region=True
    )
    run_bad = _execute_real_job(project_dir, tmp_path / "run-bad", docspec_bin, orders_bad, customers_bad)
    meta_bad = tmp_path / "meta-bad.json"
    meta_bad.write_text(json_dumps({"executions": [{"path": run_bad["evidence"]["path"], "production": "daily-revenue-job"}]}))

    res_bad = assemble_catalog(
        project_path,
        metadata=meta_bad,
        metadata_adapter="local",
        required_groups=("catalog.jobs", "catalog.qualification"),
        permitted_roots=(tmp_path,),
    )
    assert res_bad.report["decision"] == "failed", res_bad.report
    qual_checks = [c for c in res_bad.report["checks"] if c["group"] == "catalog.qualification"]
    assert qual_checks and any(c["status"] == "failed" for c in qual_checks)
    assert any(c["status"] == "failed" for c in res_bad.catalog["checks"])

    # 3. Tampered SQL in JobSpec.queries fails DDK-CATALOG-012 with CATALOG-JOB-SPEC-MISMATCH!
    tampered_dir = tmp_path / "tampered"
    import shutil
    shutil.copytree(project_dir, tampered_dir)
    t_spec = _load_mutable_json(tampered_dir / "jobs/daily-revenue.job.json")
    t_spec["queries"][0]["sql"] = "SELECT 0 AS fake_zero"
    (tampered_dir / "jobs/daily-revenue.job.json").write_text(json_dumps(t_spec))
    run_tampered = _execute_real_job(tampered_dir, tmp_path / "run-tampered", docspec_bin, orders_ok, customers_ok)
    meta_tampered = tmp_path / "meta-tampered.json"
    meta_tampered.write_text(json_dumps({
        "executions": [{"path": run_tampered["evidence"]["path"], "production": "daily-revenue-job"}]
    }))
    res_tampered = assemble_catalog(
        tampered_dir / "project.ddk.json",
        metadata=meta_tampered,
        metadata_adapter="local",
        required_groups=("catalog.jobs", "catalog.qualification"),
        permitted_roots=(tmp_path,),
    )
    assert res_tampered.report["decision"] == "failed"
    tampered_codes = [d["code"] for c in res_tampered.report["checks"] for d in c["diagnostics"]]
    assert "CATALOG-JOB-SPEC-MISMATCH" in tampered_codes

    # 4. Distinct step.name != output.name AND planted violation introduced inside output.sql (P1-1 regression)
    distinct_dir = tmp_path / "distinct-step-out"
    shutil.copytree(project_dir, distinct_dir)
    d_decl = _load_mutable_json(distinct_dir / "jobs/daily-revenue.job.ddk.json")
    d_decl["steps"] = {
        "clean_orders": "urn:example:recipe:clean-orders",
        "staged_revenue": "urn:example:recipe:daily-revenue",
    }
    (distinct_dir / "jobs/daily-revenue.job.ddk.json").write_text(json_dumps(d_decl))
    d_spec = _load_mutable_json(distinct_dir / "jobs/daily-revenue.job.json")
    d_spec["steps"][1]["name"] = "staged_revenue"
    # Upstream step has valid amount_cents >= 0, while output.sql plants -50 in the exported Parquet!
    d_spec["outputs"][0]["sql"] = "SELECT order_day, region, CAST(-50 AS BIGINT) AS amount_cents FROM staged_revenue"
    (distinct_dir / "jobs/daily-revenue.job.json").write_text(json_dumps(d_spec))
    run_distinct = _execute_real_job(distinct_dir, tmp_path / "run-distinct", docspec_bin, orders_ok, customers_ok)
    meta_distinct = tmp_path / "meta-distinct.json"
    meta_distinct.write_text(json_dumps({
        "executions": [{"path": run_distinct["evidence"]["path"], "production": "daily-revenue-job"}]
    }))
    res_distinct = assemble_catalog(
        distinct_dir / "project.ddk.json",
        metadata=meta_distinct,
        metadata_adapter="local",
        required_groups=("catalog.jobs", "catalog.qualification"),
        permitted_roots=(tmp_path,),
        docspec=docspec_bin,
        docspec_evidence_dir=tmp_path / "gate-distinct",
    )
    assert res_distinct.report["decision"] == "failed"
    assert any(c["status"] == "failed" for c in res_distinct.catalog["checks"])

    # 5. Mixing a scalar rule and a standalone table/SQL rule (column: None) in one binding fails closed (P1-2 regression)
    mixed_dir = tmp_path / "mixed-binding"
    shutil.copytree(project_dir, mixed_dir)
    m_decl = _load_mutable_json(mixed_dir / "jobs/daily-revenue.job.ddk.json")
    m_decl["qualityQueries"] = {
        "revenue_counters": {
            "dataset": "daily-revenue",
            "rules": ["amount_cents:required", "nonnegative-total"],
        }
    }
    (mixed_dir / "jobs/daily-revenue.job.ddk.json").write_text(json_dumps(m_decl))
    m_spec = _load_mutable_json(mixed_dir / "jobs/daily-revenue.job.json")
    m_spec["queries"] = [
        {"name": "revenue_counters", "sql": 'SELECT 0 AS "amount_cents:required", 0 AS "nonnegative-total"'}
    ]
    (mixed_dir / "jobs/daily-revenue.job.json").write_text(json_dumps(m_spec))
    run_mixed = _execute_real_job(mixed_dir, tmp_path / "run-mixed", docspec_bin, orders_ok, customers_ok)
    meta_mixed = tmp_path / "meta-mixed.json"
    meta_mixed.write_text(json_dumps({
        "executions": [{"path": run_mixed["evidence"]["path"], "production": "daily-revenue-job"}]
    }))
    res_mixed = assemble_catalog(
        mixed_dir / "project.ddk.json",
        metadata=meta_mixed,
        metadata_adapter="local",
        required_groups=("catalog.jobs", "catalog.qualification"),
        permitted_roots=(tmp_path,),
    )
    assert res_mixed.report["decision"] == "failed"
    mixed_codes = [d["code"] for c in res_mixed.report["checks"] for d in c["diagnostics"]]
    assert "CATALOG-QUALITY-COVERAGE" in mixed_codes


def test_catalog_jobs_and_recipes_profiles_registered_independently():
    from ddk.conformance import PROFILES
    from ddk.documents import REPOSITORY

    assert {"catalog.jobs", "catalog.recipes"} <= PROFILES
    cases = read_json(REPOSITORY / "conformance" / "cases.json").value["cases"]
    by_id = {case["id"]: case["profile"] for case in cases}
    job_cases = {cid for cid in by_id if cid.startswith("CASE-CATALOG-012-")}
    recipe_cases = {cid for cid in by_id if cid.startswith("CASE-RECIPE-SQL-")}
    assert len(job_cases) >= 5 and all(by_id[cid] == "catalog.jobs" for cid in job_cases)
    assert len(recipe_cases) >= 8 and all(by_id[cid] == "catalog.recipes" for cid in recipe_cases)
    assert by_id["CASE-CONF-005-RUN-NEEDS-PRODUCTION"] == "catalog"


@pytest.fixture
def directory_execution(tmp_path, docspec_bin):
    project_dir = tmp_path / "project"
    project_path = _make_job_project(project_dir)
    orders, customers = _write_input_parquets(tmp_path / "data")
    parts = tmp_path / "order-parts"
    parts.mkdir()
    rows = pq.read_table(orders)
    pq.write_table(rows.slice(0, 2), parts / "first.parquet")
    pq.write_table(rows.slice(2), parts / "second.parquet")
    spec_path = project_dir / "jobs/daily-revenue.job.json"
    spec = _load_mutable_json(spec_path)
    spec["scratch"] = str(tmp_path / "scratch")
    spec["inputs"][0]["path"] = str(parts)
    spec["inputs"][1]["path"] = str(customers)
    spec["outputs"][0]["path"] = str(tmp_path / "revenue.parquet")
    spec_path.write_text(json_dumps(spec))
    adapter = DocSpecAdapter(docspec_bin, dict(DEFAULT_DOCSPEC_GATE_LIMITS), evidence_dir=tmp_path / "evidence")
    pins = {str(path): sha256(path.read_bytes()).hexdigest() for path in parts.iterdir()}
    pins[str(customers)] = sha256(customers.read_bytes()).hexdigest()
    response = adapter.execute(spec, input_digests=pins, spec_path=spec_path)
    assert response["status"] == "succeeded", response
    return project_path, spec, response


@pytest.mark.parametrize("receipt_kind", ["bounded", "direct"])
def test_directory_job_catalog_preserves_native_members_without_payload_reads(
    tmp_path, docspec_bin, directory_execution, monkeypatch, receipt_kind,
):
    project_path, spec, response = directory_execution
    assert pq.read_table(spec["outputs"][0]["path"]).to_pylist() == [
        {"order_day": date(2026, 2, 1), "region": "EU", "amount_cents": 800},
        {"order_day": date(2026, 2, 1), "region": "NA", "amount_cents": 1200},
    ]
    receipt = response["receipt"] if receipt_kind == "bounded" else response["result"]
    receipt_path = tmp_path / f"{receipt_kind}-receipt.json"
    receipt_path.write_text(json_dumps(receipt))
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json_dumps({"executions": [{
        "path": str(receipt_path), "production": "daily-revenue-job",
        "startedAt": response["receipt"]["startedAt"], "endedAt": response["receipt"]["endedAt"],
    }]}))
    production_paths = {
        *(Path(item["path"]) for item in response["result"]["inputs"][0]["files"]),
        Path(spec["inputs"][1]["path"]), Path(spec["outputs"][0]["path"]),
    }
    path_open = Path.open

    def no_payload_open(path, *args, **kwargs):
        assert path not in production_paths, "Catalog assembly opened a production data payload"
        return path_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_payload_open)
    output = tmp_path / "catalog"
    report = build_catalog(
        project_path, metadata=metadata_path, metadata_adapter="local",
        required_groups=("catalog.jobs", "catalog.recipes"), exports=("dcat", "openlineage"),
        output=output, permitted_roots=(tmp_path,), docspec=docspec_bin,
    )
    assert report["decision"] == "passed", report
    catalog = read_json(output / "catalog.ddk.json").value
    version = next(item for item in catalog["versions"] if item["dataset"] == "orders")
    native_input = response["result"]["inputs"][0]
    assert version["reference"] == {
        "scheme": "urn:ddk:version:docspec-parquet-directory-sha256", "authority": "urn:ddk:local-file",
        "value": {"location": Path(spec["inputs"][0]["path"]).as_uri(), "sha256": native_input["sha256"]},
    }
    representation = next(item for item in catalog["representations"] if item["version"] == version["id"])
    assert representation["members"] == [
        {"path": Path(item["path"]).name, "sha256": item["sha256"], "byteSize": item["bytes"]}
        for item in native_input["files"]
    ]
    assert representation["byteSize"] == sum(item["bytes"] for item in native_input["files"])
    assert catalog["runs"][0]["inputCoverage"]["status"] == "complete"
    assert version["id"] in catalog["runs"][0]["inputs"]


def test_directory_catalog_rejects_incomplete_or_mismatched_native_members(tmp_path, directory_execution):
    project_path, _spec, response = directory_execution
    for fault in ("missing", "extra", "changed", "rehashed", "omitted", "duplicate", "total", "nested"):
        receipt = deepcopy(response["receipt"])
        observed = receipt["result"]["inputs"][0]
        if fault == "missing":
            observed["files"].pop()
        elif fault == "extra":
            observed["files"].append({**observed["files"][0], "path": observed["path"] + "/third.parquet"})
        elif fault in {"changed", "rehashed"}:
            observed["files"][0]["sha256"] = "0" * 64
            if fault == "rehashed":
                tuples = [[Path(item["path"]).name, item["sha256"], item["bytes"]] for item in observed["files"]]
                observed["sha256"] = sha256(json.dumps(tuples, separators=(",", ":")).encode()).hexdigest()
        elif fault == "omitted":
            observed.pop("files")
        elif fault == "duplicate":
            observed["files"].append(deepcopy(observed["files"][0]))
        elif fault == "total":
            observed["bytes"] += 1
        elif fault == "nested":
            observed["files"][0]["path"] = observed["path"] + "/nested/first.parquet"
        receipt_path = tmp_path / f"{fault}-receipt.json"
        receipt_path.write_text(json_dumps(receipt))
        metadata_path = tmp_path / f"{fault}-metadata.json"
        metadata_path.write_text(json_dumps({"executions": [{"path": str(receipt_path), "production": "daily-revenue-job"}]}))
        result = assemble_catalog(project_path, metadata=metadata_path, metadata_adapter="local", permitted_roots=(tmp_path,))
        assert result.report["decision"] == "failed", (fault, result.report)
        assert "CATALOG-NATIVE-RECEIPT" in [d["code"] for c in result.report["checks"] for d in c["diagnostics"]], fault

