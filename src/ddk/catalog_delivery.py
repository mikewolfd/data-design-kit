"""Capture standard catalog artifacts and verify their private/public pairing.

This module reads metadata only. A passed delivery check establishes the exact
artifact set, not data quality, row authorization, or native availability.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import stat
from types import MappingProxyType

from .catalog_access import CatalogError
from .documents import parse_json, validate_document


OUTPUT_SET = "urn:ddk:catalog:output-set"
PAIRED_VIEW = "urn:ddk:catalog:paired-public-view:1"


@dataclass(frozen=True)
class CatalogArtifacts:
    directory: Path
    catalog: dict
    report: dict
    lock: dict
    lock_sha256: str
    companions: Mapping[str, bytes]
    artifacts: Mapping[str, bytes]
    externally_pinned: bool


def _need(condition, message):
    if not condition:
        raise CatalogError("CATALOG-DELIVERY", message)


def _read(root, name, maximum):
    _need(isinstance(name, str) and bool(name), "Artifact path must be a nonempty string")
    relative = PurePosixPath(name)
    _need(relative.as_posix() == name and not relative.is_absolute()
          and not any(part in {"", ".", ".."} for part in relative.parts) and "\\" not in name,
          "Unsafe standard artifact path")
    path = root.joinpath(*relative.parts)
    _need(path.resolve().is_relative_to(root), "Catalog artifact escapes its selected directory")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _need(stat.S_ISREG(info.st_mode) and info.st_size <= maximum,
              "Catalog artifact is not a bounded regular file")
        data = stream.read(maximum + 1)
    _need(len(data) <= maximum, "Catalog artifact exceeded its byte allocation")
    return data


def load_catalog_artifacts(directory, *, expected_lock_sha256=None, audience=None,
                           max_artifact_bytes=64 << 20, max_total_bytes=128 << 20,
                           max_lock_bytes=2 << 20, max_files=4096):
    """Capture one exact output set without reopening definitions or data.

    An external lock pin remains mandatory for data access or pairing. Optional
    unpinned loading supports local inspection only. All budgets are finite.
    """
    for value in (max_artifact_bytes, max_total_bytes, max_lock_bytes, max_files):
        _need(type(value) is int and value > 0, "Catalog delivery budgets must be positive integers")
    root = Path(directory).resolve(strict=True)
    _need(root.is_dir(), "Catalog output must be a directory")
    lock_bytes = _read(root, "catalog.lock.json", min(max_lock_bytes, max_total_bytes))
    digest = sha256(lock_bytes).hexdigest()
    _need(expected_lock_sha256 is None or digest == expected_lock_sha256,
          "Catalog lock differs from its selected external pin")
    lock = parse_json(lock_bytes)
    _need(not validate_document(lock, "lock"), "Invalid standard catalog lock")
    inventory = lock.get("extensions", {}).get(OUTPUT_SET)
    _need(isinstance(inventory, list) and len(inventory) <= max_files,
          "Missing or oversized standard output-set inventory")
    _need(all(isinstance(row, dict) and set(row) == {"path", "sha256", "role"}
              and all(type(row[key]) is str for key in row) for row in inventory),
          "Invalid output-set inventory entry")
    expected = {row["path"]: row for row in inventory}
    _need(len(expected) == len(inventory) and {"catalog.ddk.json", "catalog.report.json"} <= expected.keys()
          and "catalog.lock.json" not in expected, "Incomplete or duplicate standard artifact membership")
    remaining, content = max_total_bytes - len(lock_bytes), {}
    for name, row in expected.items():
        _need(remaining >= 0, "Catalog artifact set exceeded its total byte allocation")
        body = _read(root, name, min(max_artifact_bytes, remaining))
        _need(sha256(body).hexdigest() == row["sha256"], "Catalog artifact differs from its exact lock digest")
        remaining -= len(body)
        content[name] = body
    actual = set()
    for count, path in enumerate(root.rglob("*"), 1):
        _need(count <= max_files * 2, "Catalog directory exceeded its entry allocation")
        _need(not path.is_symlink(), "Catalog delivery cannot contain symbolic links")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
        else:
            _need(path.is_dir(), "Catalog delivery cannot contain special files")
    _need(actual == set(expected) | {"catalog.lock.json"}, "Catalog directory differs from its complete membership")
    catalog, report = parse_json(content["catalog.ddk.json"]), parse_json(content["catalog.report.json"])
    _need(not validate_document(catalog, "catalog") and not validate_document(report, "report"),
          "Invalid standard catalog or checking report")
    companions = {name: body for name, body in content.items() if name != "catalog.ddk.json"}
    catalog_files = {row["path"]: row for row in catalog["files"]}
    _need(len(catalog_files) == len(catalog["files"]) and set(catalog_files) == set(companions)
          and all(catalog_files[name] == expected[name] for name in companions),
          "Catalog and lock disagree on complete companion membership")
    _need(report["decision"] == "passed", "Stored artifact set does not carry a passed checking report")
    _need(audience is None or catalog["audience"] == audience, "Catalog audience differs from the requested boundary")
    _need(_read(root, "catalog.lock.json", max_lock_bytes) == lock_bytes,
          "Catalog directory changed while its artifact set was captured")
    return CatalogArtifacts(root, catalog, report, lock, digest, MappingProxyType(companions),
                            MappingProxyType({**content, "catalog.lock.json": lock_bytes}),
                            expected_lock_sha256 is not None)


def paired_view_record(public_catalog, local_catalog, public_lock_bytes):
    """Record the exact public output belonging to this admitted local view.

    Call only within shared assembly, before any private output is delivered.
    This association does not grant access to private fields or recipes.
    """
    _need(public_catalog["audience"] == "public" and local_catalog["audience"] == "local",
          "Catalog pairing requires explicit public and local views")
    local = {row["id"]: row for row in local_catalog["datasets"]}
    _need(len(local) == len(local_catalog["datasets"])
          and len({row["alias"] for row in local_catalog["datasets"]}) == len(local),
          "Local dataset identities and aliases must be unique")
    _need(len({row["id"] for row in public_catalog["datasets"]}) == len(public_catalog["datasets"])
          and len({row["alias"] for row in public_catalog["datasets"]}) == len(public_catalog["datasets"]),
          "Public dataset identities and aliases must be unique")
    datasets = []
    for row in public_catalog["datasets"]:
        _need(row["id"] in local, "Public dataset is outside the local assembly")
        datasets.append({"id": row["id"], "publicAlias": row["alias"], "localAlias": local[row["id"]]["alias"]})
    return {"catalog": public_catalog["id"], "publicLockSha256": sha256(public_lock_bytes).hexdigest(),
            "datasets": datasets}


def verify_catalog_pair(public, local):
    """Verify the two externally pinned views; return explicit alias bindings.

    Consumers must separately enforce public field authorization against the
    observed native schema. A private definition is never that authorization.
    """
    _need(public.externally_pinned and local.externally_pinned, "Both catalog views need external lock pins")
    p, q = public.catalog, local.catalog
    _need(p["audience"] == "public" and q["audience"] == "local" and p["id"] == q["id"]
          and p["project"] == q["project"], "Catalog views have different identity or audience")
    expected = paired_view_record(p, q, public.artifacts["catalog.lock.json"])
    _need(local.lock.get("extensions", {}).get(PAIRED_VIEW) == expected,
          "Private lock does not identify this exact public view and dataset mapping")
    aliases = {row["publicAlias"]: row["localAlias"] for row in expected["datasets"]}
    datasets = {row["id"]: row for row in q["datasets"]}
    for row in p["datasets"]:
        source = datasets[row["id"]]
        _need(all(row["definition"].get(key) == source["definition"].get(key) for key in ("contractId", "version"))
              and row["definition"]["source"].get("sha256") == source["definition"]["source"].get("sha256"),
              "Paired dataset changed its source definition identity")
    relationships = {row["id"]: row for row in q["relationships"]}
    _need(len(relationships) == len(q["relationships"]), "Private relationship identities must be unique")
    for row in p["relationships"]:
        normalized = deepcopy(row)
        for side in ("source", "target"):
            if "dataset" in normalized[side]:
                normalized[side]["dataset"] = aliases[normalized[side]["dataset"]]
        _need(relationships.get(row["id"]) == normalized,
              "Paired relationship changed its endpoint, matching, scope or resolution meaning")
    for section in ("versions", "representations", "recipes"):
        private = {row["id"]: row for row in q[section]}
        _need(len(private) == len(q[section]) and len({row["id"] for row in p[section]}) == len(p[section]),
              "Access record identities must be unique in each catalog view")
        for row in p[section]:
            _need(row["id"] in private, "Public access record is outside the paired local catalog")
            source = private[row["id"]]
            if section == "versions":
                _need(aliases[row["dataset"]] == source["dataset"] and row["retention"] == source["retention"]
                      and ("reference" not in row or row["reference"] == source["reference"]),
                      "Paired version changed its dataset, retention or native identity")
            elif section == "representations":
                _need(all(row.get(key) == source.get(key) for key in ("version", "kind", "availability", "location", "mediaType")),
                      "Paired representation changed its exact access meaning")
            else:
                _need({key: aliases[alias] for key, alias in row["inputs"].items()} == source["inputs"],
                      "Paired recipe changed its named input mapping")
                _need(("resultDataset" not in row or aliases[row["resultDataset"]] == source.get("resultDataset"))
                      and all(row.get(key) == source.get(key) for key in ("sql", "dialect", "parameters", "parameterOrder", "relationships", "resultGrain"))
                      and public.companions[row["sql"]] == local.companions[source["sql"]],
                      "Paired recipe changed its SQL or parameter meaning")
    return deepcopy(aliases)
