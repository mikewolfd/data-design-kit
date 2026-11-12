"""Cross-stack catalog federation, key-format checks, exactMatch concepts, and zero-scan RML (T2.1 + T2.2)."""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ddk.catalog import assemble_catalog
from ddk.catalog_delivery import load_catalog_artifacts, verify_catalog_pair
from ddk.catalog_graph import VOCAB
from ddk.cli import main as cli_main
from ddk.documents import validate_document
from ddk.impact import compare_catalogs, impact_projects
from ddk.adapters.native import NativeTools


WIKIDATA_BILL_ID = "https://www.wikidata.org/entity/P1157"
CANONICAL_BILL_PATTERN = "^[0-9]+-[a-z]+-[0-9]+$"
INVERTED_BILL_PATTERN = "^[a-z]+[0-9]+-[0-9]+$"


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_artifacts(directory: Path, artifacts: dict[str, bytes]) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    for rel, body in artifacts.items():
        dest = directory / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    return sha256(artifacts["catalog.lock.json"]).hexdigest()


def _codes(report: dict) -> set[str]:
    return {diag["code"] for check in report["checks"] for diag in check.get("diagnostics", ())}


def _build_stack_a(
    root: Path,
    *,
    bill_pattern: str = CANONICAL_BILL_PATTERN,
    title_type: str = "string",
    contract_version: str = "1.0.0",
    write_parquet: bool = True,
) -> tuple[Path, Path, Path]:
    """Create Stack A (legislative bills) with real Parquet data and metadata."""
    parquet_path = root / "data" / "bills.parquet"
    if write_parquet:
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table({
            "bill_id": ["111-hr-3590", "117-hr-3684"],
            "title": [
                "Patient Protection and Affordable Care Act",
                "Infrastructure Investment and Jobs Act",
            ],
            "congress": pa.array([111, 117], type=pa.int32()),
        })
        pq.write_table(table, parquet_path)

    _write_json(root / "definitions" / "bill-id.json", {
        "logicalType": "string",
        "required": True,
        "logicalTypeOptions": {"pattern": bill_pattern},
        "description": "Canonical federal bill identifier formatted as congress-type-number.",
        "customProperties": [
            {"vendor": "ddk", "property": "concept", "value": "urn:example:legislative:concept:bill-id"},
            {"vendor": "ddk", "property": "conceptKind", "value": "identifier"},
            {"vendor": "ddk", "property": "exactMatch", "value": [WIKIDATA_BILL_ID]},
            {"vendor": "ddk", "property": "iriTemplate", "value": "https://congress.example.org/bill/{value}"},
        ],
    })

    _write_json(root / "datasets" / "bills.odcs.json", {
        "apiVersion": "v3.2.0",
        "kind": "DataContract",
        "id": "urn:example:legislative:contract:bills",
        "version": contract_version,
        "name": "Legislative bills",
        "status": "active",
        "schema": [{
            "id": "bills",
            "name": "bills",
            "logicalType": "object",
            "physicalType": "table",
            "properties": [
                {
                    "name": "bill_id",
                    "logicalType": "string",
                    "required": True,
                    "logicalTypeOptions": {"pattern": bill_pattern},
                    "authoritativeDefinitions": [{"type": "definition", "url": "../definitions/bill-id.json"}],
                },
                {
                    "name": "title",
                    "logicalType": title_type,
                    "required": True,
                },
                {
                    "name": "congress",
                    "logicalType": "integer",
                    "physicalType": "int32",
                    "required": True,
                },
            ],
            "customProperties": [{"vendor": "ddk", "property": "rowIdentity", "value": ["bill_id"]}],
        }],
    })

    _write_json(root / "catalog" / "product.odps.json", {
        "apiVersion": "v1.1.0",
        "kind": "DataProduct",
        "id": "urn:example:legislative:product",
        "version": "1.0.0",
        "name": "Legislative bills product",
        "status": "active",
        "description": {"purpose": "Publish canonical bill identifiers and titles."},
        "outputPorts": [{"name": "bills", "contractId": "urn:example:legislative:contract:bills", "version": contract_version}],
    })

    metadata_path = _write_json(root / "catalog" / "metadata.json", {
        "illustrative": True,
        "sources": [],
        "versions": [{
            "id": "urn:example:legislative:version:bills:v1",
            "dataset": "bills",
            "reference": {
                "scheme": "urn:example:legislative:scheme:version",
                "authority": "https://legislative.example.org",
                "value": f"bills-{contract_version}",
            },
            "retention": "present",
            "scope": "Published bills snapshot.",
            "record": {"uri": "https://legislative.example.org/evidence/metadata.json"},
            "sources": [],
        }],
        "representations": [{
            "id": "urn:example:legislative:representation:bills-parquet",
            "version": "urn:example:legislative:version:bills:v1",
            "kind": "file",
            "availability": "available",
            "mediaType": "application/vnd.apache.parquet",
            "location": parquet_path.resolve().as_uri(),
            "record": {"uri": "https://legislative.example.org/evidence/metadata.json"},
        }],
        "releases": [{
            "id": "urn:example:legislative:release:r1",
            "reference": {
                "scheme": "urn:example:legislative:scheme:release",
                "authority": "https://legislative.example.org",
                "value": "r1",
            },
            "members": ["urn:example:legislative:version:bills:v1"],
            "membership": "complete",
            "record": {"uri": "https://legislative.example.org/evidence/metadata.json"},
        }],
        "selections": [{
            "authority": "https://legislative.example.org",
            "purpose": "published",
            "release": "urn:example:legislative:release:r1",
            "observedAt": "2026-11-11T12:00:00Z",
            "record": {"uri": "https://legislative.example.org/evidence/metadata.json"},
        }],
    })

    project_path = _write_json(root / "project.ddk.json", {
        "specVersion": "0.1",
        "kind": "project",
        "id": "urn:example:legislative:project",
        "version": contract_version,
        "artifacts": {
            "bills": {
                "kind": "dataset",
                "path": "datasets/bills.odcs.json",
                "object": "bills",
                "catalogId": "urn:example:legislative:dataset:bills",
                "role": "source_record",
            },
            "bill-id": {"kind": "definition", "path": "definitions/bill-id.json"},
            "legislative-product": {"kind": "product", "path": "catalog/product.odps.json"},
        },
        "imports": {},
        "requiredChecks": ["core.documents", "core.references", "core.graph", "core.datasets", "core.policies"],
        "catalog": {
            "id": "urn:example:legislative:catalog",
            "ports": [{
                "product": "legislative-product",
                "direction": "output",
                "port": "bills",
                "version": contract_version,
                "dataset": "bills",
            }],
        },
    })
    return project_path, metadata_path, parquet_path


def _build_stack_b(
    root: Path,
    *,
    peer_import: dict,
    fk_pattern: str = CANONICAL_BILL_PATTERN,
    relationship_scope: str = "version_pair",
    target_dataset: str = "bills",
    project_version: str = "1.0.0",
    write_parquet: bool = True,
) -> tuple[Path, Path, tuple[Path, Path]]:
    """Create Stack B (oversight hearings + mentions) importing Stack A via catalog.imports."""
    hearings_parquet = root / "data" / "hearings.parquet"
    mentions_parquet = root / "data" / "hearing_mentions.parquet"
    if write_parquet:
        hearings_parquet.parent.mkdir(parents=True, exist_ok=True)
        bill_ref_type = pa.list_(pa.struct([
            pa.field("bill_id", pa.string()),
            pa.field("role", pa.string()),
        ]))
        hearings_table = pa.table({
            "hearing_id": ["H-01", "H-02"],
            "chamber": ["house", "senate"],
            "primary_bill_id": ["111-hr-3590", "117-hr-3684"],
            "bill_refs": pa.array([
                [
                    {"bill_id": "111-hr-3590", "role": "focus"},
                    {"bill_id": "117-hr-3684", "role": "background"},
                ],
                [
                    {"bill_id": "117-hr-3684", "role": "focus"},
                ],
            ], type=bill_ref_type),
        })
        pq.write_table(hearings_table, hearings_parquet)

        mentions_table = pa.table({
            "mention_id": ["M-01"],
            "mentioned_bill_id": ["111-hr-3590"],
        })
        pq.write_table(mentions_table, mentions_parquet)

    # Distinct local concept URN from Stack A, linked solely by shared Wikidata P1157 exactMatch!
    _write_json(root / "definitions" / "bill-ref.json", {
        "logicalType": "string",
        "required": True,
        "logicalTypeOptions": {"pattern": fk_pattern},
        "description": "Bill identifier referenced in committee hearing records.",
        "customProperties": [
            {"vendor": "ddk", "property": "concept", "value": "urn:example:oversight:concept:bill-ref"},
            {"vendor": "ddk", "property": "conceptKind", "value": "identifier"},
            {"vendor": "ddk", "property": "exactMatch", "value": [WIKIDATA_BILL_ID]},
            {"vendor": "ddk", "property": "iriTemplate", "value": "https://congress.example.org/bill/{value}"},
        ],
    })

    _write_json(root / "policies" / "oversight.ddk.json", {
        "specVersion": "0.1",
        "kind": "policy",
        "id": "urn:example:oversight:policy",
        "version": "1.0.0",
        "rules": [{"id": "strict-concept-joins", "check": "concept-joins", "severity": "error"}],
    })

    _write_json(root / "datasets" / "oversight.odcs.json", {
        "apiVersion": "v3.2.0",
        "kind": "DataContract",
        "id": "urn:example:oversight:contract:hearings",
        "version": "1.0.0",
        "name": "Oversight hearing datasets",
        "status": "active",
        "schema": [
            {
                "id": "hearings",
                "name": "hearings",
                "logicalType": "object",
                "physicalType": "table",
                "properties": [
                    {"name": "hearing_id", "logicalType": "string", "required": True},
                    {"name": "chamber", "logicalType": "string", "required": True},
                    {
                        "name": "primary_bill_id",
                        "logicalType": "string",
                        "required": False,
                        "logicalTypeOptions": {"pattern": fk_pattern},
                        "authoritativeDefinitions": [{"type": "definition", "url": "../definitions/bill-ref.json"}],
                    },
                    {
                        "name": "bill_refs",
                        "logicalType": "array",
                        "items": {
                            "logicalType": "object",
                            "properties": [
                                {
                                    "name": "bill_id",
                                    "logicalType": "string",
                                    "logicalTypeOptions": {"pattern": fk_pattern},
                                    "authoritativeDefinitions": [{"type": "definition", "url": "../definitions/bill-ref.json"}],
                                },
                                {"name": "role", "logicalType": "string"},
                            ],
                        },
                    },
                ],
                "customProperties": [{"vendor": "ddk", "property": "rowIdentity", "value": ["hearing_id"]}],
            },
            {
                "id": "hearing_mentions",
                "name": "hearing_mentions",
                "logicalType": "object",
                "physicalType": "table",
                "properties": [
                    {"name": "mention_id", "logicalType": "string", "required": True},
                    {
                        "name": "mentioned_bill_id",
                        "logicalType": "string",
                        "required": True,
                        "logicalTypeOptions": {"pattern": fk_pattern},
                        "authoritativeDefinitions": [{"type": "definition", "url": "../definitions/bill-ref.json"}],
                    },
                ],
                "customProperties": [{"vendor": "ddk", "property": "rowIdentity", "value": ["mention_id"]}],
            },
        ],
    })

    _write_json(root / "catalog" / "product.odps.json", {
        "apiVersion": "v1.1.0",
        "kind": "DataProduct",
        "id": "urn:example:oversight:product",
        "version": "1.0.0",
        "name": "Oversight hearings product",
        "status": "active",
        "description": {"purpose": "Link committee hearings and transcript mentions to legislative bills."},
        "outputPorts": [
            {"name": "hearings", "contractId": "urn:example:oversight:contract:hearings", "version": "1.0.0"},
            {"name": "hearing-mentions", "contractId": "urn:example:oversight:contract:hearings", "version": "1.0.0"},
        ],
    })

    sql_path = root / "queries" / "hearing_bills.sql"
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text(
        "SELECT h.hearing_id, b.title FROM hearings AS h JOIN bills AS b ON h.primary_bill_id = b.bill_id\n",
        encoding="utf-8",
    )

    metadata_path = _write_json(root / "catalog" / "metadata.json", {
        "illustrative": True,
        "sources": [],
        "versions": [
            {
                "id": "urn:example:oversight:version:hearings:v1",
                "dataset": "hearings",
                "reference": {
                    "scheme": "urn:example:oversight:scheme:version",
                    "authority": "https://oversight.example.org",
                    "value": "hearings-v1",
                },
                "retention": "present",
                "scope": "Published hearings snapshot.",
                "record": {"uri": "https://oversight.example.org/evidence/metadata.json"},
                "sources": [],
            },
            {
                "id": "urn:example:oversight:version:mentions:v1",
                "dataset": "hearing-mentions",
                "reference": {
                    "scheme": "urn:example:oversight:scheme:version",
                    "authority": "https://oversight.example.org",
                    "value": "mentions-v1",
                },
                "retention": "present",
                "scope": "Published hearing mentions snapshot.",
                "record": {"uri": "https://oversight.example.org/evidence/metadata.json"},
                "sources": [],
            },
        ],
        "representations": [
            {
                "id": "urn:example:oversight:representation:hearings-parquet",
                "version": "urn:example:oversight:version:hearings:v1",
                "kind": "file",
                "availability": "available",
                "mediaType": "application/vnd.apache.parquet",
                "location": hearings_parquet.resolve().as_uri(),
                "record": {"uri": "https://oversight.example.org/evidence/metadata.json"},
            },
            {
                "id": "urn:example:oversight:representation:mentions-parquet",
                "version": "urn:example:oversight:version:mentions:v1",
                "kind": "file",
                "availability": "available",
                "mediaType": "application/vnd.apache.parquet",
                "location": mentions_parquet.resolve().as_uri(),
                "record": {"uri": "https://oversight.example.org/evidence/metadata.json"},
            },
        ],
        "releases": [{
            "id": "urn:example:oversight:release:r1",
            "reference": {
                "scheme": "urn:example:oversight:scheme:release",
                "authority": "https://oversight.example.org",
                "value": "r1",
            },
            "members": [
                "urn:example:oversight:version:hearings:v1",
                "urn:example:oversight:version:mentions:v1",
            ],
            "membership": "complete",
            "record": {"uri": "https://oversight.example.org/evidence/metadata.json"},
        }],
        "selections": [{
            "authority": "https://oversight.example.org",
            "purpose": "published",
            "release": "urn:example:oversight:release:r1",
            "observedAt": "2026-11-11T12:05:00Z",
            "record": {"uri": "https://oversight.example.org/evidence/metadata.json"},
        }],
    })

    project_path = _write_json(root / "project.ddk.json", {
        "specVersion": "0.1",
        "kind": "project",
        "id": "urn:example:oversight:project",
        "version": project_version,
        "artifacts": {
            "hearings": {
                "kind": "dataset",
                "path": "datasets/oversight.odcs.json",
                "object": "hearings",
                "catalogId": "urn:example:oversight:dataset:hearings",
                "role": "source_record",
            },
            "hearing-mentions": {
                "kind": "dataset",
                "path": "datasets/oversight.odcs.json",
                "object": "hearing_mentions",
                "catalogId": "urn:example:oversight:dataset:hearing-mentions",
                "role": "source_record",
            },
            "bill-ref": {"kind": "definition", "path": "definitions/bill-ref.json"},
            "oversight-policy": {"kind": "policy", "path": "policies/oversight.ddk.json"},
            "oversight-product": {"kind": "product", "path": "catalog/product.odps.json"},
        },
        "imports": {},
        "requiredChecks": [
            "core.documents",
            "core.references",
            "core.graph",
            "core.datasets",
            "core.policies",
        ],
        "catalog": {
            "id": "urn:example:oversight:catalog",
            "imports": {"legislative": peer_import},
            "ports": [
                {
                    "product": "oversight-product",
                    "direction": "output",
                    "port": "hearings",
                    "version": "1.0.0",
                    "dataset": "hearings",
                },
                {
                    "product": "oversight-product",
                    "direction": "output",
                    "port": "hearing-mentions",
                    "version": "1.0.0",
                    "dataset": "hearing-mentions",
                },
            ],
            "relationships": [
                {
                    "id": "urn:example:oversight:relationship:hearing-primary-bill",
                    "source": {"dataset": "hearings", "paths": [[{"field": "primary_bill_id"}]]},
                    "target": {"catalog": "legislative", "dataset": target_dataset, "paths": [[{"field": "bill_id"}]]},
                    "match": "equal",
                    "cardinality": "many_to_one",
                    "scope": relationship_scope,
                    "resolution": "required",
                    "meaning": "Each hearing's primary legislative bill.",
                    "nulls": "reject",
                },
                {
                    "id": "urn:example:oversight:relationship:hearing-bill-ref",
                    "source": {
                        "dataset": "hearings",
                        "paths": [[{"field": "bill_refs"}, {"each": True}, {"field": "bill_id"}]],
                    },
                    "target": {"catalog": "legislative", "dataset": target_dataset, "paths": [[{"field": "bill_id"}]]},
                    "match": "equal",
                    "cardinality": "many_to_one",
                    "scope": relationship_scope,
                    "resolution": "required",
                    "meaning": "Each structured bill reference inside a hearing record.",
                    "nulls": "reject",
                },
            ],
            "recipes": [{
                "id": "urn:example:oversight:recipe:hearing-bills",
                "sql": "queries/hearing_bills.sql",
                "dialect": "datafusion",
                "inputs": {
                    "hearings": "hearings",
                    "bills": {"catalog": "legislative", "dataset": target_dataset},
                },
                "relationships": ["urn:example:oversight:relationship:hearing-primary-bill"],
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                "resultGrain": "One row per hearing with a matched primary legislative bill.",
                "title": "Join hearings to peer legislative bills",
            }],
        },
    })
    return project_path, metadata_path, (hearings_parquet, mentions_parquet)


def test_mismatched_key_regex_and_format_fail_offline_with_key_format_conflict(tmp_path, monkeypatch):
    stack_a_proj, stack_a_meta, bills_parquet = _build_stack_a(tmp_path / "stack-a", bill_pattern=CANONICAL_BILL_PATTERN)
    stack_a_res = assemble_catalog(stack_a_proj, metadata=stack_a_meta, metadata_adapter="example")
    assert stack_a_res.report["decision"] == "passed"
    stack_a_out = tmp_path / "stack-a-out"
    pin = _write_artifacts(stack_a_out, stack_a_res.artifacts)

    # Stack B formats bill_id as hr3590-111 (^[a-z]+[0-9]+-[0-9]+$) while Stack A uses 111-hr-3590.
    stack_b_proj, stack_b_meta, (hearings_parquet, mentions_parquet) = _build_stack_b(
        tmp_path / "stack-b",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": pin},
        fk_pattern=INVERTED_BILL_PATTERN,
    )

    parquet_files = {bills_parquet.resolve(), hearings_parquet.resolve(), mentions_parquet.resolve()}
    original_open = Path.open

    def forbid_parquet_open(self, *args, **kwargs):
        if self.resolve() in parquet_files:
            raise AssertionError(f"Offline catalog assembly must never open payload file {self}")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbid_parquet_open)

    mismatch = assemble_catalog(
        stack_b_proj,
        metadata=stack_b_meta,
        metadata_adapter="example",
        peer_catalogs={"legislative": stack_a_out},
    )
    assert mismatch.report["decision"] == "failed"
    assert "CATALOG-KEY-FORMAT-CONFLICT" in _codes(mismatch.report)

    # Also verify intra-catalog format conflict (`uuid` vs `date`) and invalid `iriTemplate` checks.
    odcs = json.loads((tmp_path / "stack-b" / "datasets" / "oversight.odcs.json").read_text(encoding="utf-8"))
    odcs["schema"][0]["properties"].append({
        "name": "local_uuid",
        "logicalType": "string",
        "logicalTypeOptions": {"format": "uuid"},
    })
    odcs["schema"][1]["properties"].append({
        "name": "local_date_str",
        "logicalType": "string",
        "logicalTypeOptions": {"format": "date"},
    })
    _write_json(tmp_path / "stack-b" / "datasets" / "oversight.odcs.json", odcs)
    proj_doc = json.loads(stack_b_proj.read_text(encoding="utf-8"))
    proj_doc["catalog"]["relationships"] = [{
        "id": "urn:example:oversight:relationship:bad-format",
        "source": {"dataset": "hearings", "paths": [[{"field": "local_uuid"}]]},
        "target": {"dataset": "hearing-mentions", "paths": [[{"field": "local_date_str"}]]},
        "match": "equal",
        "cardinality": "many_to_many",
        "scope": "same_release",
        "resolution": "unresolved_allowed",
        "meaning": "Mismatched string formats.",
        "nulls": "reject",
    }]
    _write_json(stack_b_proj, proj_doc)
    format_conflict = assemble_catalog(
        stack_b_proj,
        metadata=stack_b_meta,
        metadata_adapter="example",
        peer_catalogs={"legislative": stack_a_out},
    )
    assert format_conflict.report["decision"] == "failed"
    assert "CATALOG-KEY-FORMAT-CONFLICT" in _codes(format_conflict.report)

    proj_doc["catalog"]["relationships"] = []
    proj_doc["catalog"]["recipes"] = []
    _write_json(stack_b_proj, proj_doc)
    bad_def = json.loads((tmp_path / "stack-b" / "definitions" / "bill-ref.json").read_text(encoding="utf-8"))
    bad_def["customProperties"] = [
        {"vendor": "ddk", "property": "concept", "value": "urn:example:oversight:concept:bill-ref"},
        {"vendor": "ddk", "property": "conceptKind", "value": "attribute"},
        {"vendor": "ddk", "property": "iriTemplate", "value": "https://congress.example.org/bill/no-placeholder"},
    ]
    _write_json(tmp_path / "stack-b" / "definitions" / "bill-ref.json", bad_def)
    bad_template = assemble_catalog(
        stack_b_proj,
        metadata=stack_b_meta,
        metadata_adapter="example",
        peer_catalogs={"legislative": stack_a_out},
    )
    assert bad_template.report["decision"] == "failed"
    assert "CATALOG-CONCEPT-IRI-TEMPLATE" in _codes(bad_template.report)


def test_harmonized_cross_stack_federation_concepts_recipes_and_graph(tmp_path, monkeypatch):
    stack_a_proj, stack_a_meta, bills_parquet = _build_stack_a(tmp_path / "stack-a")
    stack_a_res = assemble_catalog(stack_a_proj, metadata=stack_a_meta, metadata_adapter="example")
    assert stack_a_res.report["decision"] == "passed"
    stack_a_out = tmp_path / "stack-a-out"
    pin = _write_artifacts(stack_a_out, stack_a_res.artifacts)

    stack_b_proj, stack_b_meta, (hearings_parquet, mentions_parquet) = _build_stack_b(
        tmp_path / "stack-b",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": pin},
        fk_pattern=CANONICAL_BILL_PATTERN,
    )

    parquet_files = {bills_parquet.resolve(), hearings_parquet.resolve(), mentions_parquet.resolve()}
    original_open = Path.open

    def forbid_parquet_open(self, *args, **kwargs):
        if self.resolve() in parquet_files:
            raise AssertionError(f"Offline catalog assembly must never open payload file {self}")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbid_parquet_open)

    has_rdflib = importlib.util.find_spec("rdflib") is not None
    exports = ("dcat", "graph", "rml") if has_rdflib else ("rml",)

    native_py = os.environ.get("DDK_NATIVE_PYTHON") or (
        sys.executable if importlib.util.find_spec("sqlglot") is not None else None
    )
    tools = NativeTools(native_py, output=tmp_path / "native") if native_py else None

    result = assemble_catalog(
        stack_b_proj,
        metadata=stack_b_meta,
        metadata_adapter="example",
        exports=exports,
        required_groups=("catalog.recipes",) if tools else (),
        recipe_tools=tools,
        peer_catalogs={"legislative": stack_a_out},
    )
    assert result.report["decision"] == "passed", result.report
    assert not validate_document(result.catalog)

    # Shared Wikidata P1157 exactMatch satisfies error-severity concept-joins across distinct concept URNs!
    concept_checks = [c for c in result.report["checks"] if c["subject"].endswith("/concepts")]
    assert len(concept_checks) == 2 and all(c["status"] == "passed" and c["required"] for c in concept_checks)

    concept_row, = result.catalog["concepts"]
    assert concept_row["iriTemplate"] == "https://congress.example.org/bill/{value}"
    assert {"catalog": "legislative", "dataset": "bills", "path": [{"field": "bill_id"}]} in concept_row["fields"]

    if tools is not None:
        recipe_check, = [
            c for c in result.report["checks"]
            if c["group"] == "catalog.recipes" and c["subject"] == "urn:example:oversight:recipe:hearing-bills"
        ]
        assert recipe_check["status"] == "passed"
        # Plant a nonexistent peer column in the cross-catalog SQL recipe and verify static binder rejection.
        (tmp_path / "stack-b" / "queries" / "hearing_bills.sql").write_text(
            "SELECT h.hearing_id, b.nonexistent_col FROM hearings AS h JOIN bills AS b ON h.primary_bill_id = b.bill_id\n",
            encoding="utf-8",
        )
        bad_recipe = assemble_catalog(
            stack_b_proj,
            metadata=stack_b_meta,
            metadata_adapter="example",
            required_groups=("catalog.recipes",),
            recipe_tools=tools,
            peer_catalogs={"legislative": stack_a_out},
        )
        assert bad_recipe.report["decision"] == "failed"
        assert "CATALOG-RECIPE-COLUMN" in _codes(bad_recipe.report)

    if has_rdflib:
        import rdflib

        void = rdflib.Namespace("http://rdfs.org/ns/void#")
        graph = rdflib.Graph().parse(data=result.companions["discovery.graph.jsonld"], format="json-ld")
        linksets = {
            (
                str(graph.value(ls, void.subjectsTarget)),
                str(graph.value(ls, void.objectsTarget)),
                str(graph.value(ls, void.linkPredicate)),
            )
            for ls in graph.subjects(rdflib.RDF.type, void.Linkset)
        }
        assert (
            "urn:example:oversight:dataset:hearings",
            "urn:example:legislative:dataset:bills",
            "urn:example:oversight:relationship:hearing-primary-bill",
        ) in linksets
        assert (
            "urn:example:oversight:dataset:hearings",
            "urn:example:legislative:dataset:bills",
            "urn:example:oversight:relationship:hearing-bill-ref",
        ) in linksets

        candidates = {
            (
                str(graph.value(cand, rdflib.URIRef(VOCAB + "subjectsTarget"))),
                str(graph.value(cand, rdflib.URIRef(VOCAB + "objectsTarget"))),
                frozenset(str(obj) for obj in graph.objects(cand, rdflib.DCTERMS.type)),
            )
            for cand in graph.subjects(rdflib.RDF.type, rdflib.URIRef(VOCAB + "CandidateLinkset"))
        }
        # Unjoined hearing-mentions.mentioned_bill_id discovers peer Stack A bills via shared P1157 exactMatch!
        assert (
            "urn:example:oversight:dataset:hearing-mentions",
            "urn:example:legislative:dataset:bills",
            frozenset({VOCAB + "evidence-inferred", VOCAB + "concept-kind-identifier"}),
        ) in candidates


def test_cross_stack_rml_lifts_in_morph_kgc_without_peer_parquet_scan(tmp_path):
    morph_python = os.environ.get("DDK_MORPH_KGC_PYTHON") or (
        sys.executable if importlib.util.find_spec("morph_kgc") is not None else None
    )
    if not morph_python:
        pytest.skip("Set DDK_MORPH_KGC_PYTHON or install morph_kgc to run end-to-end Morph-KGC cross-stack lift")

    stack_a_proj, stack_a_meta, bills_parquet = _build_stack_a(tmp_path / "stack-a")
    stack_a_res = assemble_catalog(stack_a_proj, metadata=stack_a_meta, metadata_adapter="example", exports=("rml",))
    assert stack_a_res.report["decision"] == "passed"
    stack_a_out = tmp_path / "stack-a-out"
    pin = _write_artifacts(stack_a_out, stack_a_res.artifacts)

    stack_b_proj, stack_b_meta, _ = _build_stack_b(
        tmp_path / "stack-b",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": pin},
    )
    stack_b_res = assemble_catalog(
        stack_b_proj,
        metadata=stack_b_meta,
        metadata_adapter="example",
        exports=("rml",),
        peer_catalogs={"legislative": stack_a_out},
    )
    assert stack_b_res.report["decision"] == "passed"
    stack_b_out = tmp_path / "stack-b-out"
    _write_artifacts(stack_b_out, stack_b_res.artifacts)

    # Step 1: Materialize Stack A's bills mapping while bills.parquet exists.
    stack_a_nq = tmp_path / "stack_a.nq"
    materialize_script = (
        "import pathlib, sys, morph_kgc\n"
        "mappings, dest = sys.argv[1], pathlib.Path(sys.argv[2])\n"
        "cfg = f'[CONFIGURATION]\\noutput_format = N-QUADS\\nna_values = \\\\uffff\\n[ds]\\nmappings = {mappings}\\n'\n"
        "quads = sorted(morph_kgc.materialize_set(cfg))\n"
        "dest.write_text(''.join(q + ' .\\n' for q in quads), encoding='utf-8')\n"
    )
    subprocess.run(
        [morph_python, "-B", "-c", materialize_script, str(stack_a_out / "rml/bills.yarrrml.yml"), str(stack_a_nq)],
        check=True,
        capture_output=True,
        text=True,
    )

    # Step 2: Physically delete Stack A's Parquet file BEFORE lifting Stack B!
    bills_parquet.unlink()
    assert not bills_parquet.exists()

    # Step 3: Materialize Stack B's mappings with zero peer Parquet file present on disk!
    stack_b_nq = tmp_path / "stack_b.nq"
    stack_b_mappings = f"{stack_b_out / 'rml/hearings.yarrrml.yml'},{stack_b_out / 'rml/hearing-mentions.yarrrml.yml'}"
    subprocess.run(
        [morph_python, "-B", "-c", materialize_script, stack_b_mappings, str(stack_b_nq)],
        check=True,
        capture_output=True,
        text=True,
    )

    # Step 4: Parse combined N-Quads in RDFLib and run cross-stack SPARQL queries across flat and array<object> FKs.
    sparql_script = """
import json, pathlib, sys
from rdflib import Dataset

ds = Dataset(default_union=True)
for p in sys.argv[1:]:
    ds.parse(data=pathlib.Path(p).read_text(encoding="utf-8"), format="nquads")

flat_q = '''
SELECT ?hearing_id ?bill_id ?title ?external WHERE {
  ?hearing <urn:example:oversight:dataset:hearings:field:hearing_id> ?hearing_id ;
           <urn:example:oversight:relationship:hearing-primary-bill> ?bill .
  ?bill <urn:example:legislative:dataset:bills:field:bill_id> ?bill_id ;
        <urn:example:legislative:dataset:bills:field:title> ?title ;
        <http://www.w3.org/2000/01/rdf-schema#seeAlso> ?external .
}
ORDER BY ?hearing_id
'''

nested_q = '''
SELECT ?hearing_id ?role ?bill_id ?title WHERE {
  ?hearing <urn:example:oversight:dataset:hearings:field:hearing_id> ?hearing_id ;
           <urn:example:oversight:dataset:hearings:field:bill_refs> ?item .
  ?item <urn:example:oversight:dataset:hearings:field:bill_refs:role> ?role ;
        <urn:example:oversight:relationship:hearing-bill-ref> ?bill .
  ?bill <urn:example:legislative:dataset:bills:field:bill_id> ?bill_id ;
        <urn:example:legislative:dataset:bills:field:title> ?title .
}
ORDER BY ?hearing_id ?bill_id ?role
'''

print(json.dumps({
    "quads": sum(1 for _ in ds.quads()),
    "flat": [[str(v) for v in row] for row in ds.query(flat_q)],
    "nested": [[str(v) for v in row] for row in ds.query(nested_q)],
}))
"""
    proc = subprocess.run(
        [morph_python, "-B", "-c", sparql_script, str(stack_a_nq), str(stack_b_nq)],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(proc.stdout)
    assert observed["flat"] == [
        [
            "H-01",
            "111-hr-3590",
            "Patient Protection and Affordable Care Act",
            "https://congress.example.org/bill/111-hr-3590",
        ],
        [
            "H-02",
            "117-hr-3684",
            "Infrastructure Investment and Jobs Act",
            "https://congress.example.org/bill/117-hr-3684",
        ],
    ]
    assert observed["nested"] == [
        ["H-01", "focus", "111-hr-3590", "Patient Protection and Affordable Care Act"],
        ["H-01", "background", "117-hr-3684", "Infrastructure Investment and Jobs Act"],
        ["H-02", "focus", "117-hr-3684", "Infrastructure Investment and Jobs Act"],
    ]


def test_unbound_and_mismatched_peer_imports_and_cli_peer_catalog(tmp_path):
    stack_a_proj, stack_a_meta, _ = _build_stack_a(tmp_path / "stack-a", write_parquet=False)
    stack_a_res = assemble_catalog(stack_a_proj, metadata=stack_a_meta, metadata_adapter="example")
    stack_a_out = tmp_path / "stack-a-out"
    pin = _write_artifacts(stack_a_out, stack_a_res.artifacts)

    stack_b_proj, stack_b_meta, _ = _build_stack_b(
        tmp_path / "stack-b",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": pin},
        write_parquet=False,
    )

    # 1. Omitting --peer-catalog records explicit `not_run` (`CATALOG-IMPORT-UNBOUND`) and prevents overall pass.
    unbound = assemble_catalog(stack_b_proj, metadata=stack_b_meta, metadata_adapter="example")
    assert unbound.report["decision"] == "incomplete"
    assert "CATALOG-IMPORT-UNBOUND" in _codes(unbound.report)
    import_check = next(c for c in unbound.report["checks"] if c["group"] == "catalog.imports")
    assert import_check["status"] == "not_run" and import_check["required"]

    # 2. Wrong lockSha256 fails with `CATALOG-IMPORT-MISMATCH`.
    wrong_pin_proj, wrong_pin_meta, _ = _build_stack_b(
        tmp_path / "stack-b-wrong-pin",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": "0" * 64},
        write_parquet=False,
    )
    wrong_pin = assemble_catalog(
        wrong_pin_proj,
        metadata=wrong_pin_meta,
        metadata_adapter="example",
        peer_catalogs={"legislative": stack_a_out},
    )
    assert wrong_pin.report["decision"] == "failed"
    assert "CATALOG-IMPORT-MISMATCH" in _codes(wrong_pin.report)

    # 3. Wrong catalog ID with matching lockSha256 fails with `CATALOG-IMPORT-MISMATCH`.
    wrong_id_proj, wrong_id_meta, _ = _build_stack_b(
        tmp_path / "stack-b-wrong-id",
        peer_import={"id": "urn:example:other:catalog", "audience": "local", "lockSha256": pin},
        write_parquet=False,
    )
    wrong_id = assemble_catalog(
        wrong_id_proj,
        metadata=wrong_id_meta,
        metadata_adapter="example",
        peer_catalogs={"legislative": stack_a_out},
    )
    assert wrong_id.report["decision"] == "failed"
    assert "CATALOG-IMPORT-MISMATCH" in _codes(wrong_id.report)

    # 4. End-to-end CLI `--peer-catalog` passes and writes admitted catalog output.
    cli_out = tmp_path / "cli-out"
    rc = cli_main([
        "catalog",
        str(stack_b_proj),
        "--metadata",
        str(stack_b_meta),
        "--metadata-adapter",
        "example",
        "--peer-catalog",
        f"legislative={stack_a_out}",
        "--output",
        str(cli_out),
    ])
    assert rc == 0
    admitted = load_catalog_artifacts(cli_out, audience="local")
    assert admitted.catalog["imports"]["legislative"]["lockSha256"] == pin


def test_cross_catalog_scope_and_withheld_peer_field_outcomes(tmp_path):
    stack_a_proj, stack_a_meta, _ = _build_stack_a(tmp_path / "stack-a", write_parquet=False)
    stack_a_local = assemble_catalog(stack_a_proj, metadata=stack_a_meta, metadata_adapter="example")
    stack_a_local_out = tmp_path / "stack-a-local"
    local_pin = _write_artifacts(stack_a_local_out, stack_a_local.artifacts)

    # 1. Cross-catalog relationship with `same_release` scope fails `CATALOG-CROSS-CATALOG-SCOPE`.
    same_rel_proj, same_rel_meta, _ = _build_stack_b(
        tmp_path / "stack-b-same-release",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": local_pin},
        relationship_scope="same_release",
        write_parquet=False,
    )
    same_rel = assemble_catalog(
        same_rel_proj,
        metadata=same_rel_meta,
        metadata_adapter="example",
        peer_catalogs={"legislative": stack_a_local_out},
    )
    assert same_rel.report["decision"] == "failed"
    assert "CATALOG-CROSS-CATALOG-SCOPE" in _codes(same_rel.report)

    # 2. Public peer catalog that discloses the dataset ID but withholds `bill_id` from datasetDefinitions
    # records `status="unknown"` (`CATALOG-PEER-FIELD-WITHHELD`) -> `incomplete` when `catalog.relationships` is required.
    policy_a = _write_json(tmp_path / "policy-a-withheld.json", {
        "identifiers": [
            "urn:example:legislative:catalog",
            "urn:example:legislative:project",
            "urn:example:legislative:product",
            "urn:example:legislative:dataset:bills",
            "urn:example:legislative:contract:bills",
        ],
        "descriptions": False,
        "definitionFields": {"urn:example:legislative:dataset:bills": [[{"field": "title"}]]},
    })
    stack_a_pub = assemble_catalog(
        stack_a_proj,
        metadata=stack_a_meta,
        metadata_adapter="example",
        disclosure_policy=policy_a,
    )
    assert stack_a_pub.report["decision"] == "passed"
    pub_bills_alias = stack_a_pub.catalog["datasets"][0]["alias"]
    stack_a_pub_out = tmp_path / "stack-a-public"
    pub_pin = _write_artifacts(stack_a_pub_out, stack_a_pub.artifacts)

    withheld_proj, withheld_meta, _ = _build_stack_b(
        tmp_path / "stack-b-withheld",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "public", "lockSha256": pub_pin},
        target_dataset=pub_bills_alias,
        write_parquet=False,
    )
    withheld_res = assemble_catalog(
        withheld_proj,
        metadata=withheld_meta,
        metadata_adapter="example",
        required_groups=("catalog.relationships",),
        peer_catalogs={"legislative": stack_a_pub_out},
    )
    assert withheld_res.report["decision"] == "incomplete"
    assert "CATALOG-PEER-FIELD-WITHHELD" in _codes(withheld_res.report)
    rel_checks = [
        c for c in withheld_res.report["checks"]
        if any(d["code"] == "CATALOG-PEER-FIELD-WITHHELD" for d in c.get("diagnostics", ()))
    ]
    assert rel_checks and all(c["status"] == "unknown" for c in rel_checks)


def test_public_disclosure_peer_audience_guard_and_paired_public_rewrite(tmp_path):
    stack_a_proj, stack_a_meta, _ = _build_stack_a(tmp_path / "stack-a", write_parquet=False)

    # Case 1: Un-paired local Stack A cannot be disclosed into a public Stack B view (`CATALOG-DISCLOSURE-PEER-AUDIENCE`).
    unpaired_a = assemble_catalog(stack_a_proj, metadata=stack_a_meta, metadata_adapter="example")
    unpaired_a_dir = tmp_path / "unpaired-a"
    unpaired_pin = _write_artifacts(unpaired_a_dir, unpaired_a.artifacts)

    stack_b_proj, stack_b_meta, _ = _build_stack_b(
        tmp_path / "stack-b-unpaired",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": unpaired_pin},
        write_parquet=False,
    )
    disclose_all_b = _write_json(tmp_path / "policy-b.json", {
        "identifiers": [
            "urn:example:oversight:catalog",
            "urn:example:oversight:project",
            "urn:example:oversight:product",
            "urn:example:oversight:dataset:hearings",
            "urn:example:oversight:dataset:hearing-mentions",
            "urn:example:oversight:contract:hearings",
            "urn:example:oversight:relationship:hearing-primary-bill",
            "urn:example:oversight:relationship:hearing-bill-ref",
            "urn:example:oversight:recipe:hearing-bills",
            "urn:example:legislative:catalog",
        ],
        "descriptions": True,
        "recipes": ["urn:example:oversight:recipe:hearing-bills"],
        "definitionFields": {
            "urn:example:oversight:dataset:hearings": [
                [{"field": "hearing_id"}],
                [{"field": "primary_bill_id"}],
            ],
            "urn:example:oversight:dataset:hearing-mentions": [
                [{"field": "mention_id"}],
                [{"field": "mentioned_bill_id"}],
            ],
        },
    })
    blocked = assemble_catalog(
        stack_b_proj,
        metadata=stack_b_meta,
        metadata_adapter="example",
        disclosure_policy=disclose_all_b,
        peer_catalogs={"legislative": unpaired_a_dir},
    )
    assert blocked.report["decision"] == "failed"
    assert "CATALOG-DISCLOSURE-PEER-AUDIENCE" in _codes(blocked.report)

    # Case 2: Paired public + local Stack A -> paired public + local Stack B automatically rewrites to public peer!
    policy_a = _write_json(tmp_path / "policy-a-full.json", {
        "identifiers": [
            "urn:example:legislative:catalog",
            "urn:example:legislative:project",
            "urn:example:legislative:product",
            "urn:example:legislative:dataset:bills",
            "urn:example:legislative:contract:bills",
        ],
        "descriptions": True,
        "definitionFields": {
            "urn:example:legislative:dataset:bills": [[{"field": "bill_id"}], [{"field": "title"}]],
        },
    })
    paired_a = assemble_catalog(
        stack_a_proj,
        metadata=stack_a_meta,
        metadata_adapter="example",
        disclosure_policy=policy_a,
        include_private_artifacts=True,
    )
    assert paired_a.report["decision"] == "passed"
    a_pub_dir, a_loc_dir = tmp_path / "paired-a" / "public", tmp_path / "paired-a" / "local"
    a_pub_pin = _write_artifacts(a_pub_dir, paired_a.artifacts)
    a_loc_pin = _write_artifacts(a_loc_dir, paired_a.local_artifacts)

    paired_b_proj, paired_b_meta, _ = _build_stack_b(
        tmp_path / "stack-b-paired",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": a_loc_pin},
        write_parquet=False,
    )
    paired_b = assemble_catalog(
        paired_b_proj,
        metadata=paired_b_meta,
        metadata_adapter="example",
        disclosure_policy=disclose_all_b,
        include_private_artifacts=True,
        exports=("rml",),
        peer_catalogs={"legislative": a_loc_dir},
    )
    assert paired_b.report["decision"] == "passed", paired_b.local_report
    assert paired_b.catalog["imports"]["legislative"] == {
        "id": "urn:example:legislative:catalog",
        "audience": "public",
        "lockSha256": a_pub_pin,
    }
    public_peer_alias = paired_a.catalog["datasets"][0]["alias"]
    assert all(rel["target"]["dataset"] == public_peer_alias for rel in paired_b.catalog["relationships"])
    assert paired_b.catalog["recipes"][0]["inputs"]["bills"] == {
        "catalog": "legislative",
        "dataset": public_peer_alias,
    }
    b_pub_dir, b_loc_dir = tmp_path / "paired-b" / "public", tmp_path / "paired-b" / "local"
    b_pub_pin = _write_artifacts(b_pub_dir, paired_b.artifacts)
    b_loc_pin = _write_artifacts(b_loc_dir, paired_b.local_artifacts)
    verify_catalog_pair(
        load_catalog_artifacts(b_pub_dir, expected_lock_sha256=b_pub_pin, audience="public"),
        load_catalog_artifacts(b_loc_dir, expected_lock_sha256=b_loc_pin, audience="local"),
    )

    # Case 3: Withholding the peer catalog ID strips cross-catalog imports, relationships, recipes, and peer concept fields.
    withhold_peer_policy = deepcopy(json.loads(disclose_all_b.read_text(encoding="utf-8")))
    withhold_peer_policy["identifiers"].remove("urn:example:legislative:catalog")
    withhold_policy_path = _write_json(tmp_path / "policy-b-no-peer.json", withhold_peer_policy)
    stripped = assemble_catalog(
        paired_b_proj,
        metadata=paired_b_meta,
        metadata_adapter="example",
        disclosure_policy=withhold_policy_path,
        include_private_artifacts=True,
        peer_catalogs={"legislative": a_loc_dir},
    )
    assert stripped.report["decision"] == "passed"
    assert "imports" not in stripped.catalog
    assert stripped.catalog["relationships"] == []
    assert stripped.catalog["recipes"] == []
    assert all("catalog" not in f for c in stripped.catalog["concepts"] for f in c["fields"])
    s_pub_dir, s_loc_dir = tmp_path / "stripped-b" / "public", tmp_path / "stripped-b" / "local"
    s_pub_pin = _write_artifacts(s_pub_dir, stripped.artifacts)
    s_loc_pin = _write_artifacts(s_loc_dir, stripped.local_artifacts)
    verify_catalog_pair(
        load_catalog_artifacts(s_pub_dir, expected_lock_sha256=s_pub_pin, audience="public"),
        load_catalog_artifacts(s_loc_dir, expected_lock_sha256=s_loc_pin, audience="local"),
    )


def test_peer_catalog_schema_change_propagates_downstream_impact(tmp_path):
    # Base Stack A v1 (title: string) and Stack B v1
    a_v1_proj, a_v1_meta, _ = _build_stack_a(
        tmp_path / "a-v1", title_type="string", contract_version="1.0.0", write_parquet=False
    )
    a_v1_res = assemble_catalog(a_v1_proj, metadata=a_v1_meta, metadata_adapter="example")
    a_v1_out = tmp_path / "a-v1-out"
    pin_v1 = _write_artifacts(a_v1_out, a_v1_res.artifacts)

    b_v1_proj, b_v1_meta, _ = _build_stack_b(
        tmp_path / "b-v1",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": pin_v1},
        write_parquet=False,
    )
    b_v1_res = assemble_catalog(
        b_v1_proj, metadata=b_v1_meta, metadata_adapter="example", peer_catalogs={"legislative": a_v1_out}
    )
    b_v1_out = tmp_path / "b-v1-out"
    _write_artifacts(b_v1_out, b_v1_res.artifacts)

    # Candidate Stack A v2 changes `title` logicalType from string -> integer (contract_version 2.0.0)
    a_v2_proj, a_v2_meta, _ = _build_stack_a(
        tmp_path / "a-v2", title_type="integer", contract_version="2.0.0", write_parquet=False
    )
    a_v2_res = assemble_catalog(a_v2_proj, metadata=a_v2_meta, metadata_adapter="example")
    a_v2_out = tmp_path / "a-v2-out"
    pin_v2 = _write_artifacts(a_v2_out, a_v2_res.artifacts)
    assert pin_v2 != pin_v1

    b_v2_proj, b_v2_meta, _ = _build_stack_b(
        tmp_path / "b-v2",
        peer_import={"id": "urn:example:legislative:catalog", "audience": "local", "lockSha256": pin_v2},
        project_version="2.0.0",
        write_parquet=False,
    )
    b_v2_res = assemble_catalog(
        b_v2_proj, metadata=b_v2_meta, metadata_adapter="example", peer_catalogs={"legislative": a_v2_out}
    )
    b_v2_out = tmp_path / "b-v2-out"
    _write_artifacts(b_v2_out, b_v2_res.artifacts)

    # Compare catalogs directly and via full project+catalog impact analysis.
    cat_report = compare_catalogs(b_v1_res.catalog, b_v2_res.catalog, peer_catalogs={"legislative": a_v2_out})
    assert not validate_document(cat_report)
    changed_ids = {item["identity"] for item in cat_report["impact"]["changed"]}
    assert "urn:example:legislative:catalog" in changed_ids
    assert "urn:example:legislative:dataset:bills" in changed_ids
    obligations = cat_report["metadata"]["catalogAffectedObligations"]
    assert "computation-review" in obligations["recipe:urn:example:oversight:recipe:hearing-bills"]
    assert "consumer-rebind" in obligations["relationship:urn:example:oversight:relationship:hearing-primary-bill"]
    assert "consumer-rebind" in obligations["dataset:hearings"]

    combined = impact_projects(
        b_v1_proj,
        b_v2_proj,
        base_catalog=b_v1_out / "catalog.ddk.json",
        candidate_catalog=b_v2_out / "catalog.ddk.json",
        peer_catalogs={"legislative": a_v2_out},
    )
    assert not validate_document(combined)
    assert combined["decision"] == "passed"
    assert any(
        item["identity"] == "urn:example:legislative:catalog"
        and item.get("baseVersion") == pin_v1
        and item.get("candidateVersion") == pin_v2
        for item in combined["impact"]["changed"]
    )

    # Verify CLI `ddk impact --peer-catalog ...` exits 0 and emits valid report JSON.
    impact_report_path = tmp_path / "cli-impact.json"
    rc = cli_main([
        "impact",
        "--base",
        str(b_v1_proj),
        "--candidate",
        str(b_v2_proj),
        "--base-catalog",
        str(b_v1_out / "catalog.ddk.json"),
        "--candidate-catalog",
        str(b_v2_out / "catalog.ddk.json"),
        "--peer-catalog",
        f"legislative={a_v2_out}",
        "--output",
        str(impact_report_path),
    ])
    assert rc == 0
    cli_report = json.loads(impact_report_path.read_text(encoding="utf-8"))
    assert not validate_document(cli_report)
