"""Generic startup-pinned DDK catalog owner worker (Parquet pagination + DocSpec checked queries).

Runs as a persistent JSON-lines stdio worker initialized once per owner adapter instance:
- Verifies catalog lock SHA-256, permitted roots, and optional DocSpec executable SHA-256 once at init.
- Paginates Parquet files and multi-shard representations via PyArrow row-group/batch slicing.
- Executes checked recipes via ddk.catalog_access.run_checked_query + cached DocSpecAdapter (or explicit DuckDB fallback).
- Deletes per-query temporary folders unless retainReceiptsDir is explicitly configured.
"""

from __future__ import annotations

import atexit
import base64
from collections import OrderedDict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import file_digest, sha256
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
from time import monotonic
from typing import Any
from urllib.parse import unquote, urlsplit

MAX_LINE_BYTES = 256 * 1024
MAX_DIGEST_CACHE = 4096
JSON_NUMBER_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")
DEFAULT_DOCSPEC_LIMITS = {
    "batch_rows": 8192,
    "compute_threads": 2,
    "max_batch_bytes": 8 << 20,
    "max_metadata_bytes": 2 << 20,
    "memory_bytes": 256 << 20,
    "scratch_bytes": 64 << 20,
}


class BridgeError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def _stat_signature(path: Path) -> tuple[int, int, int, int, int]:
    st = path.stat()
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _resolve_uri_or_path(raw: str) -> Path:
    if raw.startswith("file://"):
        parsed = urlsplit(raw)
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            raise BridgeError("evidence_refused", "Only local file:// URIs are permitted.", 409)
        return Path(unquote(parsed.path))
    return Path(raw)


def _check_permitted_file(raw: str, roots: tuple[Path, ...]) -> Path:
    candidate = _resolve_uri_or_path(raw)
    if not candidate.is_absolute():
        raise BridgeError("evidence_refused", "Owner file paths must be absolute.", 409)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise BridgeError("evidence_refused", f"Permitted file is unavailable: {exc}", 404) from exc
    if not _is_within(resolved, roots):
        raise BridgeError("evidence_refused", "Target file is outside configured permittedRoots.", 409)
    if not resolved.is_file():
        raise BridgeError("evidence_refused", "Target path is not a regular file.", 409)
    return resolved


def _decimal_lexeme(value: Decimal) -> str:
    if not value.is_finite():
        raise BridgeError("owner_unsupported_type", "Non-finite Decimal value cannot be serialized.", 422)
    tup = value.as_tuple()
    exp = int(tup.exponent)
    if -30 <= exp <= 0:
        text = format(value, "f")
        if value == 0 and value.is_signed() and not text.startswith("-"):
            text = "-" + text
    else:
        text = str(value)
    if not JSON_NUMBER_RE.match(text) or len(text) > 1024:
        raise BridgeError("owner_unsupported_type", "Numeric value exceeds exact JSON number bounds.", 422)
    return text


def _float_lexeme(value: float) -> str:
    if not math.isfinite(value):
        raise BridgeError("owner_unsupported_type", "Non-finite floating-point value cannot be serialized.", 422)
    if value == 0.0 and math.copysign(1.0, value) < 0:
        return "-0"
    text = repr(value)
    if not JSON_NUMBER_RE.match(text) or len(text) > 1024:
        raise BridgeError("owner_unsupported_type", "Floating-point value exceeds exact JSON bounds.", 422)
    return text


def _format_epoch_timestamp(raw_int: int, unit: str, tz: str | None) -> str:
    scale = {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}[unit]
    digits = {"s": 0, "ms": 3, "us": 6, "ns": 9}[unit]
    seconds, rem = divmod(raw_int, scale)
    base = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    prefix = base.strftime("%Y-%m-%dT%H:%M:%S")
    frac = f".{rem:0{digits}d}".rstrip("0") if digits and rem else ""
    if frac == ".":
        frac = ""
    suffix = "Z" if tz and tz.upper() in ("UTC", "+00:00", "Z", "ETC/UTC") else (f" [{tz}]" if tz else "")
    return f"{prefix}{frac}{suffix}"


def _format_time_of_day(raw_int: int, unit: str) -> str:
    scale = {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}[unit]
    digits = {"s": 0, "ms": 3, "us": 6, "ns": 9}[unit]
    total_seconds, rem = divmod(raw_int, scale)
    hours, rem_s = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem_s, 60)
    frac = f".{rem:0{digits}d}".rstrip("0") if digits and rem else ""
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{frac}"


def _wrap_exact_object(entries: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in entries]
    if "$number" in keys or "$object" in keys or len(set(keys)) != len(keys):
        if len(set(keys)) != len(keys):
            raise BridgeError("adapter_transport", "Duplicate field names in struct cannot be serialized.", 409)
        return {"$object": [[k, v] for k, v in entries]}
    return dict(entries)


def _encode_python_exact(value: Any, depth: int = 0, state: list[int] | None = None) -> Any:
    if state is None:
        state = [0]
    state[0] += 1
    if state[0] > 300_000 or depth > 48:
        raise BridgeError("adapter_budget", "The owner result exceeds the supported structure budget.", 413)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        if len(value) > 1_000_000:
            raise BridgeError("adapter_budget", "An owner string exceeds the supported value budget.", 413)
        return value
    if isinstance(value, int):
        text = str(value)
        if len(text) > 1024:
            raise BridgeError("owner_unsupported_type", "Integer exceeds exact JSON bounds.", 422)
        return {"$number": text}
    if isinstance(value, Decimal):
        return {"$number": _decimal_lexeme(value)}
    if isinstance(value, float):
        return {"$number": _float_lexeme(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "type": "binary",
            "encoding": "base64",
            "value": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            iso = value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return iso
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_encode_python_exact(item, depth + 1, state) for item in value]
    if isinstance(value, dict):
        entries = [(str(k), _encode_python_exact(v, depth + 1, state)) for k, v in value.items()]
        return _wrap_exact_object(entries)
    raise BridgeError("owner_unsupported_type", f"Unsupported Python value type: {type(value).__name__}", 422)


def _encode_arrow_scalar(scalar: Any, pa: Any, depth: int = 0, state: list[int] | None = None) -> Any:
    if state is None:
        state = [0]
    state[0] += 1
    if state[0] > 300_000 or depth > 48:
        raise BridgeError("adapter_budget", "The owner page exceeds the supported structure budget.", 413)
    if not scalar.is_valid:
        return None
    dtype = scalar.type
    if pa.types.is_null(dtype):
        return None
    if pa.types.is_boolean(dtype):
        return bool(scalar.as_py())
    if pa.types.is_integer(dtype):
        return {"$number": str(int(scalar.as_py()))}
    if pa.types.is_decimal(dtype):
        return {"$number": _decimal_lexeme(scalar.as_py())}
    if pa.types.is_floating(dtype):
        return {"$number": _float_lexeme(float(scalar.as_py()))}
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype) or (
        hasattr(pa.types, "is_string_view") and pa.types.is_string_view(dtype)
    ):
        text = scalar.as_py()
        if len(text) > 1_000_000:
            raise BridgeError("adapter_budget", "An owner string exceeds the supported value budget.", 413)
        return text
    if (
        pa.types.is_binary(dtype)
        or pa.types.is_large_binary(dtype)
        or pa.types.is_fixed_size_binary(dtype)
        or (hasattr(pa.types, "is_binary_view") and pa.types.is_binary_view(dtype))
    ):
        buf = scalar.as_buffer()
        raw_bytes = buf.to_pybytes() if buf is not None else bytes(scalar.as_py())
        return {
            "type": "binary",
            "encoding": "base64",
            "value": base64.b64encode(raw_bytes).decode("ascii"),
        }
    if pa.types.is_date(dtype):
        return scalar.as_py().isoformat()
    if pa.types.is_timestamp(dtype):
        return _format_epoch_timestamp(int(scalar.value), dtype.unit, dtype.tz)
    if pa.types.is_time(dtype):
        return _format_time_of_day(int(scalar.value), dtype.unit)
    if pa.types.is_duration(dtype):
        return {"$number": str(int(scalar.value))}
    if (
        pa.types.is_list(dtype)
        or pa.types.is_large_list(dtype)
        or pa.types.is_fixed_size_list(dtype)
        or (hasattr(pa.types, "is_list_view") and pa.types.is_list_view(dtype))
        or (hasattr(pa.types, "is_large_list_view") and pa.types.is_large_list_view(dtype))
    ):
        return [_encode_arrow_scalar(child, pa, depth + 1, state) for child in scalar]
    if pa.types.is_map(dtype):
        return [
            [
                _encode_arrow_scalar(k, pa, depth + 1, state),
                _encode_arrow_scalar(v, pa, depth + 1, state),
            ]
            for k, v in scalar
        ]
    if pa.types.is_struct(dtype):
        entries: list[tuple[str, Any]] = []
        for idx in range(len(dtype)):
            field = dtype[idx]
            entries.append((field.name, _encode_arrow_scalar(scalar[idx], pa, depth + 1, state)))
        return _wrap_exact_object(entries)
    if pa.types.is_dictionary(dtype):
        return _encode_arrow_scalar(scalar.value, pa, depth, state)
    return _encode_python_exact(scalar.as_py(), depth, state)


def _sql_literal(value: Any, schema_prop: dict[str, Any], raw_lexeme: str | None) -> str:
    declared_type = schema_prop.get("type")
    if declared_type == "boolean" or isinstance(value, bool):
        if not isinstance(value, bool):
            raise BridgeError("invalid_parameters", "Expected boolean recipe parameter.", 400)
        return "TRUE" if value else "FALSE"
    if declared_type == "integer":
        lex = raw_lexeme if raw_lexeme is not None else (str(value) if isinstance(value, int) and not isinstance(value, bool) else None)
        if lex is None or not re.fullmatch(r"-?(?:0|[1-9]\d*)", lex):
            raise BridgeError("invalid_parameters", "Expected exact integer recipe parameter.", 400)
        val_int = int(lex)
        if -(1 << 63) <= val_int < (1 << 63):
            return f"CAST({val_int} AS BIGINT)"
        return lex
    if declared_type == "number":
        lex = raw_lexeme if raw_lexeme is not None else (str(value) if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) else None)
        if lex is None or not JSON_NUMBER_RE.match(lex):
            raise BridgeError("invalid_parameters", "Expected exact numeric recipe parameter.", 400)
        return f"CAST({lex} AS DOUBLE)"
    if declared_type == "string" or isinstance(value, str):
        if not isinstance(value, str):
            raise BridgeError("invalid_parameters", "Expected string recipe parameter.", 400)
        if "\x00" in value:
            raise BridgeError("invalid_parameters", "NUL bytes are not permitted in SQL string parameters.", 400)
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    raise BridgeError("invalid_parameters", f"Unsupported recipe parameter type: {declared_type!r}", 400)


def _bind_sql_parameters(
    sql_text: str,
    parameters: dict[str, Any],
    raw_lexemes: dict[str, str],
    param_schema: dict[str, Any],
    parameter_order: list[str] | None,
) -> str:
    """Safely substitute ?, $1..$N, :name, and $name outside SQL strings, quoted identifiers, and comments."""
    props = param_schema.get("properties", {}) if isinstance(param_schema, dict) else {}
    out: list[str] = []
    i = 0
    n = len(sql_text)
    qmark_index = 0
    while i < n:
        ch = sql_text[i]
        # Single-quoted string literal
        if ch == "'":
            start = i
            i += 1
            while i < n:
                if sql_text[i] == "'":
                    i += 1
                    if i < n and sql_text[i] == "'":
                        i += 1
                        continue
                    break
                i += 1
            out.append(sql_text[start:i])
            continue
        # Double-quoted identifier
        if ch == '"':
            start = i
            i += 1
            while i < n:
                if sql_text[i] == '"':
                    i += 1
                    if i < n and sql_text[i] == '"':
                        i += 1
                        continue
                    break
                i += 1
            out.append(sql_text[start:i])
            continue
        # Line comment --
        if ch == "-" and i + 1 < n and sql_text[i + 1] == "-":
            start = i
            i += 2
            while i < n and sql_text[i] != "\n":
                i += 1
            out.append(sql_text[start:i])
            continue
        # Block comment /* ... */
        if ch == "/" and i + 1 < n and sql_text[i + 1] == "*":
            start = i
            i += 2
            while i + 1 < n and not (sql_text[i] == "*" and sql_text[i + 1] == "/"):
                i += 1
            i = min(n, i + 2)
            out.append(sql_text[start:i])
            continue
        # Positional ? placeholder
        if ch == "?":
            if not parameter_order or qmark_index >= len(parameter_order):
                raise BridgeError("invalid_parameters", "Positional SQL placeholder has no matching parameterOrder entry.", 400)
            name = parameter_order[qmark_index]
            qmark_index += 1
            if name not in parameters:
                raise BridgeError("invalid_parameters", f"Missing value for parameter {name!r}.", 400)
            out.append(_sql_literal(parameters[name], props.get(name, {}), raw_lexemes.get(name)))
            i += 1
            continue
        # PostgreSQL cast :: must NOT be treated as :param
        if ch == ":" and i + 1 < n and sql_text[i + 1] == ":":
            out.append("::")
            i += 2
            continue
        # Named :param or $param or positional $1
        if ch in (":", "$") and i + 1 < n:
            m_num = re.match(r"\$([1-9]\d*)\b", sql_text[i:]) if ch == "$" else None
            m_name = re.match(r"[:$]([A-Za-z_][A-Za-z0-9_]*)\b", sql_text[i:])
            if m_num:
                idx = int(m_num.group(1)) - 1
                if not parameter_order or idx < 0 or idx >= len(parameter_order):
                    raise BridgeError("invalid_parameters", f"Positional parameter ${idx + 1} is out of range.", 400)
                name = parameter_order[idx]
                if name not in parameters:
                    raise BridgeError("invalid_parameters", f"Missing value for parameter {name!r}.", 400)
                out.append(_sql_literal(parameters[name], props.get(name, {}), raw_lexemes.get(name)))
                i += len(m_num.group(0))
                continue
            if m_name:
                name = m_name.group(1)
                if name not in parameters:
                    raise BridgeError("invalid_parameters", f"Missing value for parameter {name!r}.", 400)
                out.append(_sql_literal(parameters[name], props.get(name, {}), raw_lexemes.get(name)))
                i += len(m_name.group(0))
                continue
        out.append(ch)
        i += 1
    if parameter_order and qmark_index not in (0, len(parameter_order)):
        raise BridgeError("invalid_parameters", "Positional SQL placeholder count disagrees with parameterOrder.", 400)
    return "".join(out)


def _strip_trailing_semicolon(sql_text: str) -> str:
    # Strip trailing whitespace and optional trailing semicolon (even before trailing line comments)
    lines = sql_text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    joined = "\n".join(lines).rstrip()
    if joined.endswith(";"):
        return joined[:-1].rstrip()
    return joined


class OwnerWorker:
    def __init__(self) -> None:
        self.initialized = False
        self.pa: Any = None
        self.pq: Any = None
        self.duckdb: Any = None
        self.run_checked_query: Any = None
        self.runtime: Any = None
        self.engine_info: dict[str, Any] | None = None
        self.fallback_engine = "none"
        self.catalog_path: Path | None = None
        self.catalog_sha256: str | None = None
        self.catalog_doc: dict[str, Any] | None = None
        self.captured_artifacts: Any = None
        self.lock_path: Path | None = None
        self.lock_sha256: str | None = None
        self.permitted_roots: tuple[Path, ...] = ()
        self.retain_receipts_dir: Path | None = None
        self.worker_temp_dir = Path(tempfile.mkdtemp(prefix="ddk-owner-worker-")).resolve()
        self.digest_cache: OrderedDict[tuple[int, int, int, int, int], str] = OrderedDict()
        atexit.register(self._cleanup)

    def _cleanup(self) -> None:
        shutil.rmtree(self.worker_temp_dir, ignore_errors=True)

    def _verify_cached_digest(self, path: Path, expected_sha256: str, max_bytes: int) -> None:
        sig = _stat_signature(path)
        cached = self.digest_cache.get(sig)
        if cached is not None:
            self.digest_cache.move_to_end(sig)
            if cached != expected_sha256:
                raise BridgeError("integrity_mismatch", "Parquet file bytes differ from catalog SHA-256.", 409)
            return
        if sig[2] > max_bytes:
            raise BridgeError("adapter_budget", "Parquet file exceeds verifyDigestMaxBytes budget.", 413)
        actual = _sha256_file(path)
        self.digest_cache[sig] = actual
        if len(self.digest_cache) > MAX_DIGEST_CACHE:
            self.digest_cache.popitem(last=False)
        if actual != expected_sha256:
            raise BridgeError("integrity_mismatch", "Parquet file bytes differ from catalog SHA-256.", 409)

    def init(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.initialized:
            raise BridgeError("invalid_registration", "Owner worker is already initialized.", 409)
        ddk_src = params.get("ddkSrcPath")
        if ddk_src:
            src_resolved = str(Path(ddk_src).resolve(strict=True))
            if src_resolved not in sys.path:
                sys.path.insert(0, src_resolved)

        import pyarrow as pa
        import pyarrow.parquet as pq
        from ddk.adapters.docspec import DocSpecAdapter
        from ddk.catalog_access import run_checked_query

        self.pa = pa
        self.pq = pq
        self.run_checked_query = run_checked_query

        raw_roots = params.get("permittedRoots") or []
        if not isinstance(raw_roots, list) or not raw_roots:
            raise BridgeError("invalid_registration", "DocSpecCatalogOwner requires at least one permittedRoot.", 400)
        resolved_roots: list[Path] = []
        for raw_root in raw_roots:
            if not isinstance(raw_root, str) or not Path(raw_root).is_absolute():
                raise BridgeError("invalid_registration", "Every permittedRoot must be an absolute directory path.", 400)
            try:
                root_path = Path(raw_root).resolve(strict=True)
            except OSError as exc:
                raise BridgeError("invalid_registration", f"Permitted root does not exist: {raw_root}", 400) from exc
            if not root_path.is_dir():
                raise BridgeError("invalid_registration", f"Permitted root is not a directory: {raw_root}", 400)
            resolved_roots.append(root_path)
        self.permitted_roots = tuple(resolved_roots)

        catalog_path = Path(params["catalogPath"]).resolve(strict=True)
        lock_path = Path(params["lockPath"]).resolve(strict=True)
        if not catalog_path.is_file() or not lock_path.is_file():
            raise BridgeError("invalid_registration", "Catalog and lock files must exist.", 400)
        lock_bytes = lock_path.read_bytes()
        actual_lock_sha = sha256(lock_bytes).hexdigest()
        expected_lock_sha = params.get("expectedLockSha256")
        if expected_lock_sha and actual_lock_sha != expected_lock_sha:
            raise BridgeError("integrity_mismatch", "The catalog.lock.json digest differs from lockSha256.", 409)
        catalog_bytes = catalog_path.read_bytes()
        actual_catalog_sha = sha256(catalog_bytes).hexdigest()
        self.catalog_path = catalog_path
        self.catalog_sha256 = actual_catalog_sha
        self.lock_path = lock_path
        self.lock_sha256 = actual_lock_sha
        self.digest_cache[_stat_signature(lock_path)] = actual_lock_sha
        self.digest_cache[_stat_signature(catalog_path)] = actual_catalog_sha

        from types import MappingProxyType
        from ddk.catalog_delivery import CatalogArtifacts
        from ddk.documents import freeze_json, parse_json, validate_document

        catalog_doc = parse_json(catalog_bytes)
        lock_doc = parse_json(lock_bytes)
        self.catalog_doc = catalog_doc
        if not validate_document(catalog_doc, "catalog"):
            companions: dict[str, bytes] = {}
            root_dir = catalog_path.parent
            for file_entry in catalog_doc.get("files", ()):
                if isinstance(file_entry, dict) and file_entry.get("role") == "recipe":
                    rel = file_entry.get("path")
                    if isinstance(rel, str):
                        comp_path = (root_dir / rel).resolve()
                        if comp_path.is_relative_to(root_dir) and comp_path.is_file():
                            comp_bytes = comp_path.read_bytes()
                            companions[rel] = comp_bytes
                            self.digest_cache[_stat_signature(comp_path)] = sha256(comp_bytes).hexdigest()
            self.captured_artifacts = CatalogArtifacts(
                root_dir,
                freeze_json(catalog_doc),
                freeze_json({}),
                freeze_json(lock_doc),
                actual_lock_sha,
                MappingProxyType(companions),
                MappingProxyType({"catalog.ddk.json": catalog_bytes, "catalog.lock.json": lock_bytes, **companions}),
                True,
            )

        retain_dir = params.get("retainReceiptsDir")
        if retain_dir:
            retain_path = Path(retain_dir).resolve()
            retain_path.mkdir(parents=True, exist_ok=True)
            self.retain_receipts_dir = retain_path.resolve(strict=True)

        docspec_binary = params.get("docspecBinary")
        docspec_sha256 = params.get("docspecSha256")
        self.fallback_engine = params.get("fallbackEngine") or "none"

        if docspec_binary:
            bin_path = Path(docspec_binary)
            if not bin_path.is_absolute():
                raise BridgeError("invalid_registration", "docspecBinary must be an absolute path.", 400)
            try:
                resolved_bin = bin_path.resolve(strict=True)
            except OSError as exc:
                raise BridgeError("owner_unavailable", f"DocSpec binary is unavailable: {exc}", 503) from exc
            limits = dict(DEFAULT_DOCSPEC_LIMITS)
            if isinstance(params.get("docspecLimits"), dict):
                limits.update(params["docspecLimits"])
            timeout_sec = float(params.get("docspecTimeoutSec") or 15.0)
            evidence_root = self.retain_receipts_dir or (self.worker_temp_dir / "evidence")
            evidence_root.mkdir(parents=True, exist_ok=True)
            # DocSpecAdapter hashes the executable ONCE here and pins its stat identity.
            self.runtime = DocSpecAdapter(
                resolved_bin,
                limits,
                timeout=timeout_sec,
                evidence_dir=evidence_root,
                capture_bytes=4 << 20,
            )
            actual_bin_sha = self.runtime.tool["distributionSha256"]
            if docspec_sha256 and actual_bin_sha != docspec_sha256:
                raise BridgeError(
                    "integrity_mismatch",
                    "The selected DocSpec binary SHA-256 differs from docspecSha256.",
                    409,
                )
            self.engine_info = {
                "id": self.runtime.tool["id"],
                "version": self.runtime.tool["version"],
                "binarySha256": actual_bin_sha,
            }
        elif self.fallback_engine == "duckdb":
            try:
                import duckdb
            except ImportError as exc:
                raise BridgeError("owner_unavailable", f"DuckDB fallback engine unavailable: {exc}", 503) from exc
            self.duckdb = duckdb
            self.engine_info = {
                "id": "duckdb",
                "version": duckdb.__version__,
            }
        elif self.fallback_engine != "none":
            raise BridgeError("invalid_registration", f"Unsupported fallbackEngine: {self.fallback_engine!r}", 400)

        self.initialized = True
        return {
            "pythonVersion": sys.version.split()[0],
            "pyarrowVersion": pa.__version__,
            "lockSha256": self.lock_sha256,
            "engine": self.engine_info,
        }

    def read_page(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.initialized:
            raise BridgeError("owner_unavailable", "Owner worker is not initialized.", 503)
        shards = params.get("shards") or []
        offset = int(params["offset"])
        limit = int(params["limit"])
        verify_max = int(params.get("verifyDigestMaxBytes") or (256 << 20))
        if not shards or offset < 0 or limit < 1 or limit > 100:
            raise BridgeError("page_budget", "Invalid Parquet shard pagination parameters.", 400)

        pa = self.pa
        pq = self.pq
        opened: list[tuple[Path, Any, int]] = []
        expected_cursor = 0
        for index, shard in enumerate(shards):
            path = _check_permitted_file(shard["path"], self.permitted_roots)
            st_size = path.stat().st_size
            if shard.get("byteSize") is not None and st_size != int(shard["byteSize"]):
                raise BridgeError("integrity_mismatch", "Parquet shard byteSize disagrees with file size.", 409)
            if shard.get("sha256"):
                self._verify_cached_digest(path, shard["sha256"], verify_max)
            try:
                pf = pq.ParquetFile(path, memory_map=False)
            except Exception as exc:
                raise BridgeError("owner_schema_mismatch", f"Unable to open Parquet metadata: {exc}", 422) from exc
            num_rows = int(pf.metadata.num_rows)
            if shard.get("rowCount") is not None and num_rows != int(shard["rowCount"]):
                raise BridgeError("binding_mismatch", "Parquet shard rowCount disagrees with footer metadata.", 409)
            if shard.get("rowRange") is not None:
                r_start, r_end = int(shard["rowRange"][0]), int(shard["rowRange"][1])
                if r_start != expected_cursor or (r_end - r_start) != num_rows:
                    raise BridgeError("binding_mismatch", "Parquet shard rowRange is not contiguous with metadata.", 409)
            expected_cursor += num_rows
            opened.append((path, pf, num_rows))

        total = expected_cursor
        arrow_schema = opened[0][1].schema_arrow
        schema_summary = [
            {"name": field.name, "type": str(field.type), "nullable": bool(field.nullable)}
            for field in arrow_schema
        ]

        if offset >= total:
            return {
                "rows": [],
                "rowPositions": [],
                "total": total,
                "hasMore": False,
                "rowOrder": "source-row",
                "schema": schema_summary,
            }

        target_start = offset
        target_end = min(offset + limit, total)
        rows: list[dict[str, Any]] = []
        row_positions: list[int] = []
        node_budget = [0]
        global_cursor = 0

        for _path, pf, shard_rows in opened:
            shard_start = global_cursor
            shard_end = shard_start + shard_rows
            if shard_end <= target_start or shard_start >= target_end:
                global_cursor = shard_end
                continue
            rg_cursor = shard_start
            for rg_idx in range(pf.num_row_groups):
                rg_rows = int(pf.metadata.row_group(rg_idx).num_rows)
                rg_start = rg_cursor
                rg_end = rg_start + rg_rows
                rg_cursor = rg_end
                if rg_end <= target_start or rg_start >= target_end:
                    continue
                batch_cursor = rg_start
                batch_size = min(2048, max(limit * 2, 128))
                for batch in pf.iter_batches(batch_size=batch_size, row_groups=[rg_idx]):
                    b_len = len(batch)
                    b_start = batch_cursor
                    b_end = b_start + b_len
                    batch_cursor = b_end
                    if b_end <= target_start:
                        continue
                    if b_start >= target_end:
                        break
                    local_start = max(0, target_start - b_start)
                    local_len = min(b_end, target_end) - (b_start + local_start)
                    sliced = batch.slice(local_start, local_len)
                    col_names = sliced.schema.names
                    cols = [sliced.column(c_idx) for c_idx in range(sliced.num_columns)]
                    for r_idx in range(len(sliced)):
                        entries = [
                            (col_names[c_idx], _encode_arrow_scalar(cols[c_idx][r_idx], pa, 1, node_budget))
                            for c_idx in range(len(col_names))
                        ]
                        rows.append(_wrap_exact_object(entries))
                        row_positions.append(b_start + local_start + r_idx)
                    if b_end >= target_end:
                        break
            global_cursor = shard_end

        return {
            "rows": rows,
            "rowPositions": row_positions,
            "total": total,
            "hasMore": offset + len(rows) < total,
            "rowOrder": "source-row",
            "schema": schema_summary,
        }

    def run_query(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.initialized or self.catalog_path is None:
            raise BridgeError("owner_unavailable", "Owner worker is not initialized.", 503)
        if self.runtime is None and self.duckdb is None:
            raise BridgeError("owner_unavailable", "No query execution engine is configured for this owner.", 503)

        from ddk.catalog_access import CatalogError

        recipe_id = str(params["recipeId"])
        expected_sql_sha = str(params["expectedSqlSha256"])
        limit = int(params["limit"])
        wrap_limit = bool(params.get("wrapLimit", True))
        release_id = params.get("releaseId")
        versions = params.get("versions")
        input_specs: dict[str, dict[str, Any]] = params["inputs"]
        py_parameters: dict[str, Any] = params.get("parameters") or {}
        raw_lexemes: dict[str, str] = params.get("rawNumericParameters") or {}
        verify_max = int(params.get("verifyDigestMaxBytes") or (256 << 20))

        # O(1) stat-cached integrity check that lock, catalog, and recipe companion have not mutated on disk
        if self.lock_path and self.lock_sha256:
            self._verify_cached_digest(self.lock_path, self.lock_sha256, 16 << 20)
        if self.catalog_path and self.catalog_sha256:
            self._verify_cached_digest(self.catalog_path, self.catalog_sha256, 64 << 20)

        catalog_doc = self.catalog_doc or json.loads(self.catalog_path.read_bytes())
        recipe_doc = next((r for r in catalog_doc.get("recipes", ()) if r.get("id") == recipe_id), None)
        if recipe_doc is None:
            raise BridgeError("unknown_recipe", f"Recipe {recipe_id!r} is absent from catalog.", 404)
        sql_rel = recipe_doc.get("sql")
        if isinstance(sql_rel, str):
            sql_file = (self.catalog_path.parent / sql_rel).resolve()
            if not sql_file.is_file():
                raise BridgeError("integrity_mismatch", "Recipe SQL companion file is missing.", 409)
            self._verify_cached_digest(sql_file, expected_sql_sha, 16 << 20)

        started = monotonic()
        captured_meta: dict[str, Any] = {}

        def _reader(native_binding: dict[str, Any]) -> dict[str, Any]:
            sql_bytes: bytes = native_binding["sql"]
            if sha256(sql_bytes).hexdigest() != expected_sql_sha:
                raise BridgeError("integrity_mismatch", "Recipe SQL companion digest mismatch.", 409)

            bound_inputs = native_binding["inputs"]
            if set(bound_inputs.keys()) != set(input_specs.keys()):
                raise BridgeError("recipe_inputs", "Resolved recipe inputs differ from requested bindings.", 409)

            resolved_inputs: list[dict[str, str]] = []
            input_digests: dict[str, str] = {}
            for input_name, version_doc in bound_inputs.items():
                spec = input_specs[input_name]
                if version_doc.get("id") != spec["versionId"]:
                    raise BridgeError("binding_mismatch", f"Input {input_name!r} resolved a different version.", 409)
                file_path = _check_permitted_file(spec["path"], self.permitted_roots)
                if spec.get("sha256"):
                    self._verify_cached_digest(file_path, spec["sha256"], verify_max)
                    input_digests[str(file_path)] = spec["sha256"]
                resolved_inputs.append({"kind": "parquet", "name": input_name, "path": str(file_path)})

            raw_sql = sql_bytes.decode("utf-8")
            bound_sql = _bind_sql_parameters(
                raw_sql,
                py_parameters,
                raw_lexemes,
                recipe_doc.get("parameters", {}),
                native_binding.get("parameterOrder"),
            )
            exec_sql = (
                f"SELECT * FROM (\n{_strip_trailing_semicolon(bound_sql)}\n) AS _ddk_recipe_query LIMIT {limit + 1}"
                if wrap_limit
                else bound_sql
            )

            if self.runtime is not None:
                scratch_dir = Path(tempfile.mkdtemp(prefix="query-scratch-", dir=self.worker_temp_dir))
                evidence_folder: Path | None = None
                try:
                    response = self.runtime.execute(
                        {
                            "scratch": str(scratch_dir),
                            "inputs": resolved_inputs,
                            "steps": [],
                            "outputs": [],
                            "queries": [{"name": "consumer", "sql": exec_sql}],
                        },
                        input_digests=input_digests or None,
                    )
                    ev = response.get("evidence") or {}
                    if ev.get("path"):
                        evidence_folder = Path(ev["path"]).parent
                    if response["status"] == "unknown":
                        err_msg = (response.get("error") or {}).get("message") or "DocSpec execution outcome is unknown."
                        raise BridgeError("native_read_unknown", err_msg, 408)
                    if response["status"] != "succeeded":
                        err_msg = (response.get("error") or {}).get("message") or "DocSpec refused or failed the query."
                        raise BridgeError("native_read_refused", err_msg, 409)
                    stdout_path = evidence_folder / "stdout.json" if evidence_folder else None
                    if stdout_path and stdout_path.is_file():
                        exact_doc = json.loads(
                            stdout_path.read_text("utf-8"),
                            parse_float=Decimal,
                            parse_int=Decimal,
                        )
                        raw_rows = exact_doc["queries"][0]["data"]
                    else:
                        raw_rows = response["result"]["queries"][0]["data"]

                    retained_record = None
                    if self.retain_receipts_dir is not None and ev.get("path") and ev.get("sha256"):
                        retained_record = {
                            "path": str(Path(ev["path"]).resolve(strict=True)),
                            "sha256": ev["sha256"],
                        }
                    captured_meta["record"] = retained_record
                    return {"result": raw_rows, "receipt": ev}
                finally:
                    shutil.rmtree(scratch_dir, ignore_errors=True)
                    if self.retain_receipts_dir is None and evidence_folder is not None:
                        shutil.rmtree(evidence_folder, ignore_errors=True)

            # Explicit DuckDB fallback when configured without docspecBinary
            conn = self.duckdb.connect(":memory:")
            try:
                for item in resolved_inputs:
                    safe_ident = item["name"].replace('"', '""')
                    safe_path = item["path"].replace("'", "''")
                    conn.execute(f'CREATE VIEW "{safe_ident}" AS SELECT * FROM read_parquet(\'{safe_path}\')')
                rel = conn.sql(exec_sql)
                arrow_table = rel.fetch_arrow_table()
                pa = self.pa
                cols = [arrow_table.column(i) for i in range(arrow_table.num_columns)]
                names = arrow_table.schema.names
                node_budget = [0]
                encoded_rows: list[dict[str, Any]] = []
                for r_idx in range(arrow_table.num_rows):
                    entries = [
                        (names[c_idx], _encode_arrow_scalar(cols[c_idx][r_idx], pa, 1, node_budget))
                        for c_idx in range(len(names))
                    ]
                    encoded_rows.append(_wrap_exact_object(entries))
                captured_meta["pre_encoded"] = True
                return {
                    "result": encoded_rows,
                    "receipt": {"kind": "duckdb-fallback", "tool": "duckdb", "version": self.duckdb.__version__},
                }
            finally:
                conn.close()

        binding_kwargs: dict[str, Any] = {"parameters": py_parameters}
        if release_id is not None:
            binding_kwargs["release"] = release_id
        else:
            binding_kwargs["versions"] = versions

        target_catalog = self.captured_artifacts if self.captured_artifacts is not None else self.catalog_path
        try:
            consumed = self.run_checked_query(target_catalog, recipe_id, _reader, **binding_kwargs)
        except BridgeError:
            raise
        except CatalogError as exc:
            status = 400 if exc.code == "CATALOG-QUERY-PARAMETERS" else 409
            raise BridgeError("native_scope_refused", f"{exc.code}: {exc}", status) from exc

        elapsed_ms = round((monotonic() - started) * 1000.0, 2)
        raw_rows = consumed["result"]
        if captured_meta.get("pre_encoded"):
            encoded_all = raw_rows
        else:
            node_budget = [0]
            encoded_all = [_encode_python_exact(row, 1, node_budget) for row in raw_rows]

        has_more = len(encoded_all) > limit
        sliced_rows = encoded_all[:limit]
        result_payload: dict[str, Any] = {
            "rows": sliced_rows,
            "rowPositions": list(range(len(sliced_rows))),
            "hasMore": has_more,
            "sqlSha256": consumed["sqlSha256"],
            "elapsedMs": elapsed_ms,
            "engine": self.engine_info,
        }
        if not has_more:
            result_payload["total"] = len(sliced_rows)
        if captured_meta.get("record"):
            result_payload["record"] = captured_meta["record"]
        return result_payload


def main() -> None:
    worker = OwnerWorker()
    while True:
        line = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
        if not line:
            break
        if len(line) > MAX_LINE_BYTES:
            resp = {
                "id": None,
                "ok": False,
                "error": {"code": "request_budget", "message": "Worker request exceeded line budget.", "status": 413},
            }
            sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
            sys.stdout.flush()
            continue
        req_id = None
        try:
            message = json.loads(line.decode("utf-8"))
            req_id = message.get("id")
            method = message.get("method")
            params = message.get("params") or {}
            if method == "init":
                result = worker.init(params)
            elif method == "read_page":
                result = worker.read_page(params)
            elif method == "run_query":
                result = worker.run_query(params)
            elif method == "ping":
                result = {"ok": True}
            else:
                raise BridgeError("invalid_request", f"Unknown worker method: {method!r}", 400)
            resp = {"id": req_id, "ok": True, "result": result}
        except BridgeError as exc:
            resp = {
                "id": req_id,
                "ok": False,
                "error": {"code": exc.code, "message": str(exc), "status": exc.status},
            }
        except Exception as exc:
            resp = {
                "id": req_id,
                "ok": False,
                "error": {"code": "owner_unavailable", "message": str(exc), "status": 503},
            }
        sys.stdout.write(json.dumps(resp, separators=(",", ":"), ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
