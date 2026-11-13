"""Bounded local SQL over explicitly bound versions of one pinned catalog.

This is a local, trusted-user composition API, not an HTTP authorization policy.
DocSpec owns read-only SQL execution and the exact file inventory checks. Native
versions, remote services, public partial disclosure and managed selection need
their own maintained reader profiles; this API refuses those boundaries.
"""

from hashlib import sha256
from pathlib import Path, PurePosixPath
import os
import re
import tempfile
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
    inputs, pins, total, members_count, schema_files = [], {}, 0, 0, {}
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
        schema_files[name] = []
        if reference["scheme"] == DIRECTORY_SCHEME:
            _require(path.is_dir() and bool(members), "Directory input needs complete member metadata")
            names = {member["path"] for member in members}
            _require(len(names) == len(members) and len(names) <= max_members, "Invalid member inventory")
            observed = set()
            with os.scandir(path) as entries:
                for index, entry in enumerate(entries, 1):
                    _require(index <= 2048, "Directory entry count exceeds the local query allocation")
                    _require(not entry.is_symlink() and not entry.is_dir(follow_symlinks=False), "Only flat unlinked directories are admitted")
                    if entry.name.lower().endswith(".parquet"):
                        _require(entry.name in names and entry.is_file(follow_symlinks=False), "Unexpected directory member")
                        observed.add(entry.name)
            _require(observed == names, "The complete directory membership differs from the catalog")
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
                schema_files[name].append((member_path, member["byteSize"]))
                total += member["byteSize"]
                members_count += 1
        else:
            _require(path.is_file() and not members, "Single-file input cannot carry directory members")
            size = path.stat().st_size
            _require(size == representation.get("byteSize"), "File byte size differs from its selected version")
            total += size
            members_count += 1
            schema_files[name].append((path, size))
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
    common = {"catalogLockSha256": captured.lock_sha256, "bindings": dict(bindings),
              "sqlSha256": sha256(sql.encode()).hexdigest(), "admittedInputBytes": total,
              "admittedInputMembers": members_count}
    # The retained native job JSON path narrows decimal values and writes
    # non-finite floats as null. Infer output types from exact selected Parquet
    # schemas and refuse unsupported outputs before executing the query.
    import pyarrow as pa
    import pyarrow.parquet as pq
    from .docspec_recipe_gate import encode_ipc_schema_base64, decode_ipc_schema_base64
    declared = []
    for name, files in schema_files.items():
        schemas = []
        for file, size in files:
            with file.open("rb") as stream:
                data = stream.read(size + 1)
            _require(len(data) == size and sha256(data).hexdigest() == pins[str(file)], "Input bytes changed before schema admission")
            schemas.append(pq.read_schema(pa.BufferReader(data)))
        _require(all(schema.equals(schemas[0], check_metadata=True) for schema in schemas),
                 "All members require the same exact Arrow schema for local query admission")
        declared.append({"name": name, "schema_ipc_base64": encode_ipc_schema_base64(schemas[0])})
    folder = Path(tempfile.mkdtemp(prefix="catalog-query-schema-", dir=adapter.evidence_dir))
    job_path = folder / "job.json"
    job_bytes = json_dumps(request).encode()
    job_path.write_bytes(job_bytes)
    preparation = adapter.prepare_job({"job": {"path": str(job_path), "sha256": sha256(job_bytes).hexdigest()}, "inputs": declared})
    if preparation["status"] != "succeeded":
        return {**common, "status": preparation["status"], "stage": "schema_preparation", "receipt": preparation}
    prepared = preparation["result"]
    queries = prepared.get("queries", ())
    _require(len(queries) == 1 and queries[0]["name"] == "answer", "Native preparation omitted the query schema")
    output_schema = decode_ipc_schema_base64(prepared["schemas"][queries[0]["schema_sha256"]])
    unsupported = [field.name for field in output_schema if not (
        pa.types.is_integer(field.type) or pa.types.is_boolean(field.type) or pa.types.is_null(field.type)
        or pa.types.is_string(field.type) or pa.types.is_large_string(field.type) or pa.types.is_string_view(field.type))]
    if unsupported:
        return {**common, "status": "refused", "stage": "output_type_admission", "receipt": preparation,
                "reason": "Local SQL currently returns only scalar text, integers, booleans and nulls. "
                          "Unsupported output fields: " + ", ".join(unsupported) +
                          ". Select decimal or temporal values explicitly as VARCHAR to preserve their text."}
    response = adapter.execute(request, input_digests=pins)
    result = {**common, "status": response["status"], "receipt": response, "preparation": preparation}
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
