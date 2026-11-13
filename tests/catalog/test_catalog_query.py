"""Real local consumers of exact multi-file catalog versions."""

from hashlib import sha256
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddk.adapters.docspec import DocSpecAdapter
from ddk.catalog import build_catalog
from ddk.catalog_access import CatalogError
from ddk.catalog_query import execute_catalog_sql
from ddk.docspec_recipe_gate import DEFAULT_DOCSPEC_GATE_LIMITS


def save(path, value):
    path.write_text(json.dumps(value) + "\n")


@pytest.fixture
def local_catalog(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    pq.write_table(pa.table({"id": [1, 3], "amount": [7, 11]}), parts / "a.parquet")
    pq.write_table(pa.table({"id": [2, 4], "amount": [5, 13]}), parts / "b.parquet")
    weights = tmp_path / "weights.parquet"
    pq.write_table(pa.table({"id": [1, 2, 3, 4], "weight": [2, 3, 4, 5]}), weights)
    artifacts, versions, representations = {}, [], []
    record = {"uri": (tmp_path / "metadata.json").as_uri()}
    for name, columns, path in (("items", ("id", "amount"), parts), ("weights", ("id", "weight"), weights)):
        save(tmp_path / f"{name}.odcs.json", {"apiVersion": "v3.2.0", "kind": "DataContract", "id": f"urn:test:contract:{name}",
             "version": "1.0.0", "status": "active", "schema": [{"name": name, "logicalType": "object",
             "properties": [{"name": field, "logicalType": "integer"} for field in columns]}]})
        artifacts[name] = {"kind": "dataset", "path": f"{name}.odcs.json", "object": name, "catalogId": f"urn:test:dataset:{name}"}
        if path.is_dir():
            inventory = [[p.name, sha256(p.read_bytes()).hexdigest(), p.stat().st_size] for p in sorted(path.iterdir())]
            digest = sha256(json.dumps(inventory, separators=(",", ":")).encode()).hexdigest()
            members = [{"path": p, "sha256": d, "byteSize": b} for p, d, b in inventory]
            size = sum(item[2] for item in inventory)
            scheme = "urn:ddk:version:docspec-parquet-directory-sha256"
        else:
            digest, size, members = sha256(path.read_bytes()).hexdigest(), path.stat().st_size, []
            scheme = "urn:ddk:version:local-file-sha256"
        version = f"urn:test:version:{name}"
        versions.append({"id": version, "dataset": name, "reference": {"scheme": scheme, "authority": "urn:test:owner",
                         "value": {"location": path.as_uri(), "sha256": digest}}, "retention": "present", "scope": "Independent test fixture",
                         "record": record, "sources": []})
        representations.append({"id": f"urn:test:representation:{name}", "version": version, "kind": "file",
                                "availability": "available", "location": path.as_uri(), "mediaType": "application/vnd.apache.parquet",
                                "byteSize": size, "rowCount": 4, "record": record, **({"members": members} if members else {})})
    save(tmp_path / "product.odps.json", {"apiVersion": "v1.1.0", "kind": "DataProduct", "id": "urn:test:product:reader", "version": "1.0.0",
         "name": "Reader fixture", "status": "active", "outputPorts": [
             {"name": name, "version": "1.0.0", "contractId": f"urn:test:contract:{name}"} for name in ("items", "weights")]})
    artifacts["product"] = {"kind": "product", "path": "product.odps.json"}
    save(tmp_path / "project.ddk.json", {"specVersion": "0.1", "kind": "project", "id": "urn:test:project:reader", "version": "1.0.0",
         "artifacts": artifacts, "imports": {}, "requiredChecks": ["core.documents", "core.references", "core.datasets", "core.policies"],
         "catalog": {"id": "urn:test:catalog:reader", "ports": [
             {"product": "product", "direction": "output", "port": name, "version": "1.0.0", "dataset": name} for name in ("items", "weights")]}})
    save(tmp_path / "metadata.json", {"versions": versions, "representations": representations})
    report = build_catalog(tmp_path / "project.ddk.json", metadata=tmp_path / "metadata.json", metadata_adapter="local", output=tmp_path / "catalog")
    assert report["decision"] == "passed", json.dumps(report)
    return {"directory": tmp_path / "catalog", "expected_lock_sha256": sha256((tmp_path / "catalog/catalog.lock.json").read_bytes()).hexdigest(),
            "bindings": {name: f"urn:test:version:{name}" for name in ("items", "weights")},
            "scratch": tmp_path / "scratch", "permitted_roots": (tmp_path,)}


@pytest.fixture
def adapter(tmp_path):
    binary = os.environ.get("DDK_DOCSPEC_BINARY") or os.environ.get("DDK_DOCSPEC_BIN")
    assert binary, "A pinned DocSpec binary is required; this acceptance test cannot skip"
    return DocSpecAdapter(binary, DEFAULT_DOCSPEC_GATE_LIMITS, evidence_dir=tmp_path / "native", timeout=30)


def test_unprepared_join_filter_order_and_page_reads_both_members(local_catalog, adapter):
    answer = execute_catalog_sql(**local_catalog, adapter=adapter,
        sql="SELECT i.id, i.amount * w.weight AS weighted FROM items i JOIN weights w ON i.id = w.id WHERE i.id > 1 ORDER BY i.id DESC LIMIT 2 OFFSET 1")
    assert answer["status"] == "succeeded", answer
    assert answer["rows"] == [{"id": 3, "weighted": 44}, {"id": 2, "weighted": 15}]
    assert answer["admittedInputMembers"] == 3
    assert answer["catalogLockSha256"] == local_catalog["expected_lock_sha256"]


def test_valid_empty_is_success_not_missing_input(local_catalog, adapter):
    answer = execute_catalog_sql(**local_catalog, adapter=adapter, sql="SELECT id FROM items WHERE id = 99")
    assert answer["status"] == "succeeded" and answer["rows"] == []


def test_row_overflow_refuses_instead_of_returning_a_truncated_answer(local_catalog, adapter):
    answer = execute_catalog_sql(**local_catalog, adapter=adapter, sql="SELECT id FROM items", max_rows=2)
    assert answer["status"] == "refused" and "rows" not in answer
    assert answer["receipt"]["status"] == "succeeded"


@pytest.mark.parametrize("sql", ["DELETE FROM items", "CREATE TABLE stolen AS SELECT * FROM items", "SELECT * FROM items; SELECT * FROM weights",
                                 "SELECT * FROM read_parquet('/outside/catalog.parquet')", "SELECT * FROM read_csv('/outside/catalog.csv')"])
def test_native_read_only_boundary(local_catalog, adapter, sql):
    answer = execute_catalog_sql(**local_catalog, adapter=adapter, sql=sql)
    assert answer["status"] != "succeeded" and "rows" not in answer


@pytest.mark.parametrize("fault", ["lock", "version", "root", "bytes", "members", "name"])
def test_admission_refuses_before_native_invocation(local_catalog, fault):
    class NeverExecute:
        def execute(self, *_args, **_kwargs):
            pytest.fail("Invalid catalog admission reached execution")
    options = dict(local_catalog)
    if fault == "lock": options["expected_lock_sha256"] = "0" * 64
    elif fault == "version": options["bindings"] = {"items": "urn:test:missing"}
    elif fault == "root": options["permitted_roots"] = (options["directory"],)
    elif fault == "bytes": options["max_input_bytes"] = 1
    elif fault == "members": options["max_members"] = 1
    else: options["bindings"] = {"not-a-name": "urn:test:version:items"}
    with pytest.raises(CatalogError):
        execute_catalog_sql(**options, adapter=NeverExecute(), sql="SELECT * FROM items")


@pytest.mark.parametrize("fault", ["missing", "changed", "extra"])
def test_changed_member_cannot_produce_a_successful_answer(local_catalog, adapter, fault):
    root = local_catalog["directory"].parent / "parts"
    if fault == "missing":
        (root / "a.parquet").unlink()
    elif fault == "changed":
        pq.write_table(pa.table({"id": [1, 3], "amount": [8, 12]}), root / "a.parquet")
    else:
        pq.write_table(pa.table({"id": [9], "amount": [999]}), root / "c.parquet")
    try:
        answer = execute_catalog_sql(**local_catalog, adapter=adapter, sql="SELECT SUM(amount) FROM items")
    except (CatalogError, FileNotFoundError):
        return
    assert answer["status"] != "succeeded" and "rows" not in answer
