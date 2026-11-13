"""Bounded local SQL over explicitly bound versions of one pinned catalog.

This is a local, trusted-user composition API, not an HTTP authorization policy.
DocSpec owns read-only SQL execution and the exact file inventory checks. Native
versions, remote services, public partial disclosure and managed selection need
their own maintained reader profiles; this API refuses those boundaries.
"""

from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlsplit

from .catalog_access import CatalogError
from .catalog_delivery import load_catalog_artifacts
from .catalog_metadata import FILE_SCHEME
from .docspec_file_inputs import DIRECTORY_SCHEME
from .documents import json_dumps


def _require(condition, message):
    if not condition:
        raise CatalogError("CATALOG-LOCAL-QUERY", message)


def _local_path(uri, permitted_roots):
    parts = urlsplit(uri)
    _require(parts.scheme == "file" and not parts.netloc and not parts.query and not parts.fragment,
             "Local query requires an exact local file URI")
    path = Path(unquote(parts.path))
    _require(path.is_absolute() and not path.is_symlink(), "Data input must be an absolute unlinked path")
    resolved = path.resolve(strict=True)
    _require(any(resolved.is_relative_to(root) for root in permitted_roots), "Data input is outside permitted roots")
    return resolved


def execute_catalog_sql(directory, *, expected_lock_sha256, bindings, sql, adapter,
                        scratch, permitted_roots, max_rows=100, max_input_bytes=16 << 20,
                        max_members=128):
    """Return native evidence and at most max_rows, refusing truncated answers.

    bindings maps SQL table names to exact catalog version IDs. No latest lookup,
    implicit release selection, query rewriting, or data
    quality assertion occurs. Empty results remain successful empty results.
    The native adapter must provide bounded execution and exact input admission.
    """
    _require(isinstance(expected_lock_sha256, str) and bool(re.fullmatch(r"[a-f0-9]{64}", expected_lock_sha256)),
             "Data access requires an external catalog lock SHA-256")
    _require(all(type(value) is int and value > 0 for value in (max_rows, max_input_bytes, max_members)),
             "Query limits must be positive integers")
    _require(isinstance(sql, str) and 0 < len(sql.encode()) <= 64 << 10, "SQL must be bounded nonempty text")
    _require(isinstance(bindings, dict) and 0 < len(bindings) <= max_members, "Explicit input version bindings are required")
    roots = tuple(Path(root).resolve(strict=True) for root in permitted_roots)
    _require(bool(roots), "Explicit data roots are required")
    captured = load_catalog_artifacts(directory, expected_lock_sha256=expected_lock_sha256, audience="local")
    catalog = captured.catalog
    inputs, pins, total, members_count = [], {}, 0, 0
    for name, version_id in bindings.items():
        _require(isinstance(name, str) and len(name) <= 128 and bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name)),
                 "SQL input names require letters, digits, underscores or hyphens; quote hyphenated names in SQL")
        versions = [v for v in catalog["versions"] if v["id"] == version_id]
        _require(len(versions) == 1, "Each binding must resolve to one exact catalog version")
        version = versions[0]
        reference = version.get("reference", {})
        _require(version.get("retention") == "present" and reference.get("scheme") in {FILE_SCHEME, DIRECTORY_SCHEME},
                 "Unsupported or unavailable local version reference")
        representations = [r for r in catalog["representations"] if r["version"] == version_id]
        _require(len(representations) == 1, "Each local version needs one unambiguous representation")
        representation = representations[0]
        value = reference.get("value", {})
        _require(representation.get("kind") == "file" and representation.get("availability") == "available"
                 and representation.get("mediaType") == "application/vnd.apache.parquet"
                 and representation.get("location") == value.get("location"),
                 "Representation must match the exact available Parquet reference")
        path = _local_path(value["location"], roots)
        members = representation.get("members", ())
        if reference["scheme"] == DIRECTORY_SCHEME:
            _require(path.is_dir() and bool(members), "Directory input needs complete member metadata")
            for member in members:
                relative = PurePosixPath(member["path"])
                _require(not relative.is_absolute() and relative.as_posix() == member["path"]
                         and not any(part in {"", ".", ".."} for part in relative.parts), "Unsafe member path")
                member_path = path.joinpath(*relative.parts)
                _require(not member_path.is_symlink() and member_path.resolve(strict=True).is_relative_to(path),
                         "Member escapes its directory")
                _require(member_path.is_file() and member_path.stat().st_size == member.get("byteSize"),
                         "Member byte size differs from the selected version")
                _require(str(member_path) not in pins, "Duplicate input member")
                pins[str(member_path)] = member["sha256"]
                total += member["byteSize"]
                members_count += 1
        else:
            _require(path.is_file() and not members, "Single-file input cannot carry directory members")
            size = path.stat().st_size
            _require(size == representation.get("byteSize"), "File byte size differs from its selected version")
            total += size
            members_count += 1
        _require(total <= max_input_bytes and members_count <= max_members, "Input exceeds the admitted query allocation")
        pins[str(path)] = value["sha256"]
        inputs.append({"kind": "parquet", "name": name, "path": str(path)})
    query_identity = sha256(json_dumps({"lock": captured.lock_sha256, "bindings": bindings, "sql": sql,
                                       "max_rows": max_rows}).encode()).hexdigest()
    # Preserve authored top-level ordering. Wrapping SQL in another SELECT can
    # discard ORDER BY semantics, especially across UNION or multiple members.
    # DocSpec bounds collection by metadata/memory/capture/time allocations; the
    # result row allowance is checked before admitting any rows to the caller.
    request = {"id": f"urn:ddk:local-query:{query_identity}", "scratch": str(Path(scratch).resolve()),
               "inputs": inputs, "steps": [], "outputs": [],
               "queries": [{"name": "answer", "sql": sql}]}
    response = adapter.execute(request, input_digests=pins)
    result = {"status": response["status"], "catalogLockSha256": captured.lock_sha256,
              "bindings": dict(bindings), "sqlSha256": sha256(sql.encode()).hexdigest(),
              "admittedInputBytes": total, "admittedInputMembers": members_count, "receipt": response}
    if response["status"] == "succeeded":
        queries = response.get("result", {}).get("queries", ())
        _require(len(queries) == 1 and queries[0]["name"] == "answer" and isinstance(queries[0]["data"], list),
                 "Native query returned an incomplete answer inventory")
        rows = queries[0]["data"]
        if len(rows) > max_rows:
            result.update(status="refused", reason="Answer exceeds the selected row limit; refine the query")
        else:
            result.update(rows=rows, columns=list(queries[0]["columns"]))
    return result
