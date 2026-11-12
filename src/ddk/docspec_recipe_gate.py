"""Single-engine DocSpec SQL gate for catalog recipes (DDK-CATALOG-011) and jobs (DDK-CATALOG-012)."""

import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile

from .adapters.docspec import DocSpecAdapter, arrow_type_to_odcs
from .catalog_access import CatalogError
from .documents import json_dumps
from .results import diagnostic

DEFAULT_DOCSPEC_GATE_LIMITS = {
    "compute_threads": 2,
    "memory_bytes": 256 << 20,
    "scratch_bytes": 64 << 20,
    "batch_rows": 8192,
    "max_batch_bytes": 8 << 20,
    "max_metadata_bytes": 4 << 20,
}

_DECIMAL_RE = re.compile(r"^(?:decimal|decimal128|decimal256|numeric)\s*\(\s*(\d+)\s*,\s*(-?\d+)\s*\)$", re.IGNORECASE)
_FIXED_BIN_RE = re.compile(r"^(?:fixed_size_binary|binary|char)\s*\(\s*(\d+)\s*\)$", re.IGNORECASE)


class UnmappedSchemaError(ValueError):
    """Raised when an ODCS schema property cannot be represented as an Arrow type."""


def make_docspec_gate_adapter(docspec, docspec_limits=None, *, evidence_dir=None, timeout=120):
    """Instantiate or reuse a DocSpecAdapter for zero-row catalog SQL gating."""
    if docspec is None:
        return None
    if isinstance(docspec, DocSpecAdapter):
        return docspec
    limits = DEFAULT_DOCSPEC_GATE_LIMITS if docspec_limits is None else docspec_limits
    return DocSpecAdapter(docspec, limits, timeout=timeout, evidence_dir=evidence_dir)


def odcs_property_to_pyarrow(prop, pa):
    """Recursively convert an ODCS 3.x property dictionary into a PyArrow DataType."""
    name = prop.get("name", "<item>")
    logical = prop.get("logicalType")
    physical = (prop.get("physicalType") or "").strip()
    physical_upper = physical.upper()
    opts = prop.get("logicalTypeOptions") if isinstance(prop.get("logicalTypeOptions"), dict) else {}

    if logical is None and prop.get("properties"):
        logical = "object"

    if logical == "string":
        return pa.string()
    if logical == "boolean":
        return pa.bool_()
    if logical == "binary":
        byte_len = opts.get("byteLength") or opts.get("maxLength") if opts.get("minLength") == opts.get("maxLength") else opts.get("byteLength")
        if isinstance(byte_len, int) and byte_len > 0:
            return pa.binary(byte_len)
        match = _FIXED_BIN_RE.match(physical)
        if match and physical_upper.startswith("FIXED"):
            return pa.binary(int(match.group(1)))
        return pa.binary()
    if logical == "date":
        return pa.date32()
    if logical == "time":
        return pa.time64("us")
    if logical == "timestamp":
        tz_opt = opts.get("timezone")
        if tz_opt is False or (tz_opt is not True and physical_upper in {
            "TIMESTAMP", "TIMESTAMP_NTZ", "TIMESTAMP WITHOUT TIME ZONE",
        }):
            return pa.timestamp("us", tz=None)
        default_tz = opts.get("defaultTimezone")
        tz = default_tz if isinstance(default_tz, str) and default_tz else "UTC"
        return pa.timestamp("us", tz=tz)
    if logical == "integer":
        fmt = str(opts.get("format") or "").lower()
        if fmt == "i8" or physical_upper in {"TINYINT", "INT8"}:
            return pa.int8()
        if fmt == "i16" or physical_upper in {"SMALLINT", "INT16", "SHORT"}:
            return pa.int16()
        if fmt == "i32" or physical_upper in {"INTEGER", "INT", "INT32"}:
            return pa.int32()
        if fmt == "u8" or physical_upper in {"UTINYINT", "UINT8"}:
            return pa.uint8()
        if fmt == "u16" or physical_upper in {"USMALLINT", "UINT16"}:
            return pa.uint16()
        if fmt == "u32" or physical_upper in {"UINTEGER", "UINT32"}:
            return pa.uint32()
        if fmt == "u64" or physical_upper in {"UBIGINT", "UINT64"}:
            return pa.uint64()
        return pa.int64()
    if logical == "number":
        precision = opts.get("precision")
        scale = opts.get("scale", 0)
        if isinstance(precision, int) and isinstance(scale, int) and precision >= 1:
            return pa.decimal128(precision, scale) if precision <= 38 else pa.decimal256(precision, scale)
        match = _DECIMAL_RE.match(physical)
        if match:
            prec, sc = int(match.group(1)), int(match.group(2))
            if prec >= 1:
                return pa.decimal128(prec, sc) if prec <= 38 else pa.decimal256(prec, sc)
        fmt = str(opts.get("format") or "").lower()
        if fmt == "f32" or physical_upper in {"FLOAT", "REAL", "FLOAT32"}:
            return pa.float32()
        return pa.float64()
    if logical == "object":
        children = prop.get("properties")
        if not isinstance(children, list) or not children:
            raise UnmappedSchemaError(f"Object field {name!r} has no declared child properties.")
        return pa.struct([odcs_field_to_pyarrow(child, pa) for child in children])
    if logical == "array":
        items = prop.get("items")
        if isinstance(items, dict) and (items.get("logicalType") or items.get("properties")):
            item_prop = dict(items)
            if not item_prop.get("physicalType") and physical.endswith("[]"):
                item_prop["physicalType"] = physical[:-2].strip()
            elem_type = odcs_property_to_pyarrow(item_prop, pa)
            item_nullable = not bool(items.get("required", False))
            return pa.list_(pa.field("item", elem_type, nullable=item_nullable))
        if physical.endswith("[]"):
            base = physical[:-2].strip().upper()
            scalar_map = {
                "VARCHAR": pa.string(), "TEXT": pa.string(), "STRING": pa.string(), "UTF8": pa.string(),
                "BIGINT": pa.int64(), "INT64": pa.int64(),
                "INTEGER": pa.int32(), "INT": pa.int32(), "INT32": pa.int32(),
                "SMALLINT": pa.int16(), "INT16": pa.int16(),
                "DOUBLE": pa.float64(), "FLOAT64": pa.float64(),
                "FLOAT": pa.float32(), "FLOAT32": pa.float32(),
                "BOOLEAN": pa.bool_(), "BOOL": pa.bool_(),
                "DATE": pa.date32(),
            }
            if base in scalar_map:
                return pa.list_(pa.field("item", scalar_map[base], nullable=True))
        raise UnmappedSchemaError(f"Array field {name!r} has no declared element type.")
    raise UnmappedSchemaError(f"Field {name!r} uses unsupported logicalType {logical!r}.")


def odcs_field_to_pyarrow(prop, pa):
    """Convert an ODCS property dict into a named PyArrow Field."""
    if not isinstance(prop, dict) or not isinstance(prop.get("name"), str) or not prop["name"]:
        raise UnmappedSchemaError("Every ODCS property requires a non-empty string name.")
    dtype = odcs_property_to_pyarrow(prop, pa)
    return pa.field(prop["name"], dtype, nullable=not bool(prop.get("required", False)))


def odcs_schema_to_pyarrow(schema_obj, pa):
    """Convert an ODCS dataset object dictionary into a PyArrow Schema."""
    props = schema_obj.get("properties") if isinstance(schema_obj, dict) else None
    if not isinstance(props, list) or not props:
        raise UnmappedSchemaError("Dataset schema declares no properties.")
    return pa.schema([odcs_field_to_pyarrow(prop, pa) for prop in props])


def pyarrow_type_to_odcs(dtype, pa):
    """Recursively convert a PyArrow DataType into an ODCS logical shape."""
    if pa.types.is_boolean(dtype):
        return {"logicalType": "boolean"}
    if pa.types.is_integer(dtype):
        return {"logicalType": "integer"}
    if pa.types.is_floating(dtype) or pa.types.is_decimal(dtype):
        return {"logicalType": "number"}
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype) or (
        hasattr(pa.types, "is_string_view") and pa.types.is_string_view(dtype)
    ):
        return {"logicalType": "string"}
    if pa.types.is_binary(dtype) or pa.types.is_large_binary(dtype) or pa.types.is_fixed_size_binary(dtype) or (
        hasattr(pa.types, "is_binary_view") and pa.types.is_binary_view(dtype)
    ):
        return {"logicalType": "binary"}
    if pa.types.is_date(dtype):
        return {"logicalType": "date"}
    if pa.types.is_time(dtype):
        return {"logicalType": "time"}
    if pa.types.is_timestamp(dtype):
        return {"logicalType": "timestamp"}
    if pa.types.is_list(dtype) or pa.types.is_large_list(dtype) or pa.types.is_fixed_size_list(dtype):
        elem = pyarrow_type_to_odcs(dtype.value_type, pa)
        return {"logicalType": "array", "items": elem} if elem is not None else None
    if pa.types.is_struct(dtype):
        props = []
        for idx in range(dtype.num_fields):
            child = dtype.field(idx)
            mapped = pyarrow_type_to_odcs(child.type, pa)
            if mapped is None:
                return None
            props.append({"name": child.name, **mapped})
        return {"logicalType": "object", "properties": props}
    return None


def pyarrow_schema_to_odcs(schema, pa):
    """Convert a PyArrow Schema into a list of ODCS output column descriptors."""
    columns = []
    for field in schema:
        mapped = pyarrow_type_to_odcs(field.type, pa)
        if mapped is None:
            raise UnmappedSchemaError(f"Output field {field.name!r} uses unmapped Arrow type {field.type}.")
        columns.append({"name": field.name, **mapped})
    return columns


def docspec_fields_to_odcs(fields):
    """Convert DocSpec JSON Arrow schema fields into ODCS output column descriptors."""
    columns = []
    for field in fields:
        mapped = arrow_type_to_odcs(field["data_type"])
        if mapped is None:
            raise UnmappedSchemaError(f"Output field {field['name']!r} uses unmapped Arrow type {field['data_type']!r}.")
        columns.append({"name": field["name"], **mapped})
    return columns


def write_empty_parquet(path, pa_schema):
    """Write a 0-row typed Parquet file for schema-faithful DataFusion planning and 0-row execution."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist([], schema=pa_schema)
    pq.write_table(table, path)


def encode_ipc_schema_base64(pa_schema):
    """Serialize a PyArrow Schema to base64 IPC bytes for DocSpec prepare-job."""
    return base64.b64encode(pa_schema.serialize().to_pybytes()).decode("ascii")


def decode_ipc_schema_base64(encoded):
    """Deserialize base64 Arrow IPC schema bytes from DocSpec prepare-job."""
    import pyarrow as pa

    raw = base64.b64decode(encoded)
    return pa.ipc.read_schema(pa.BufferReader(raw))


def _compatible_odcs_shape(actual, expected):
    """Return True when actual ODCS shape satisfies expected ODCS shape."""
    actual_lt = actual.get("logicalType")
    expected_lt = expected.get("logicalType")
    if actual_lt != expected_lt:
        if not (actual_lt == "integer" and expected_lt == "number"):
            return False
    if expected_lt == "object":
        exp_props = expected.get("properties")
        act_props = actual.get("properties")
        if not isinstance(exp_props, list) or not isinstance(act_props, list):
            return False
        if [p["name"] for p in act_props] != [p["name"] for p in exp_props]:
            return False
        return all(_compatible_odcs_shape(a, e) for a, e in zip(act_props, exp_props))
    if expected_lt == "array":
        exp_items = expected.get("items")
        act_items = actual.get("items")
        if not isinstance(exp_items, dict) or not isinstance(act_items, dict):
            return False
        return _compatible_odcs_shape(act_items, exp_items)
    return True


def compare_output_to_odcs(actual_columns, result_schema):
    """Compare inferred output columns against a declared resultDataset ODCS schema."""
    diagnostics = []
    expected_props = result_schema.get("properties", [])
    actual_by_name = {col["name"]: col for col in actual_columns}
    expected_by_name = {prop["name"]: prop for prop in expected_props}

    for name, expected in expected_by_name.items():
        if name not in actual_by_name:
            diagnostics.append({
                "code": "CATALOG-RECIPE-RESULT",
                "severity": "error",
                "message": f"Declared result column {name!r} is missing from recipe output.",
            })
        elif not _compatible_odcs_shape(actual_by_name[name], expected):
            diagnostics.append({
                "code": "CATALOG-RECIPE-RESULT",
                "severity": "error",
                "message": (
                    f"Recipe output column {name!r} has shape {actual_by_name[name]}, "
                    f"which is incompatible with declared result shape {expected.get('logicalType')!r}."
                ),
            })
    for name in actual_by_name:
        if name not in expected_by_name:
            diagnostics.append({
                "code": "CATALOG-RECIPE-RESULT",
                "severity": "error",
                "message": f"Recipe output produces undeclared result column {name!r}.",
            })
    return diagnostics


def sample_parameter_value(prop_schema):
    """Synthesize a deterministic typed value matching a parameter's JSON Schema."""
    if not isinstance(prop_schema, dict):
        return "sample"
    if "const" in prop_schema:
        return deepcopy(prop_schema["const"])
    if isinstance(prop_schema.get("enum"), list) and prop_schema["enum"]:
        return deepcopy(prop_schema["enum"][0])
    if "default" in prop_schema:
        return deepcopy(prop_schema["default"])

    ptype = prop_schema.get("type")
    if isinstance(ptype, list):
        ptype = next((item for item in ptype if item != "null"), "string")
    if ptype == "integer":
        if "minimum" in prop_schema:
            base = int(prop_schema["minimum"])
            return base + 1 if prop_schema.get("exclusiveMinimum") is True else base
        if isinstance(prop_schema.get("exclusiveMinimum"), (int, float)):
            return int(prop_schema["exclusiveMinimum"]) + 1
        if "maximum" in prop_schema:
            base = int(prop_schema["maximum"])
            return base - 1 if prop_schema.get("exclusiveMaximum") is True else base
        return 1
    if ptype == "number":
        if "minimum" in prop_schema:
            base = float(prop_schema["minimum"])
            return base + 1.0 if prop_schema.get("exclusiveMinimum") is True else base
        if isinstance(prop_schema.get("exclusiveMinimum"), (int, float)):
            return float(prop_schema["exclusiveMinimum"]) + 1.0
        return 1.0
    if ptype == "boolean":
        return True
    fmt = prop_schema.get("format")
    if fmt == "date":
        return "2026-01-01"
    if fmt == "date-time":
        return "2026-01-01T00:00:00Z"
    if fmt == "time":
        return "00:00:00"
    if fmt == "uuid":
        return "00000000-0000-0000-0000-000000000000"
    min_len = prop_schema.get("minLength")
    if isinstance(min_len, int) and min_len > 6:
        return "s" * min_len
    return "sample"


def analyze_and_prepare_sql(sql, parameters_schema=None, parameter_order=None):
    """Scan SQL for statement boundaries, operators, and parameters; return (rewritten_sql, bound_params, issue)."""
    props = (parameters_schema or {}).get("properties", {}) if isinstance(parameters_schema, dict) else {}
    order = list(parameter_order) if isinstance(parameter_order, (list, tuple)) else None

    out = []
    bound = {}
    has_tokens_after_semicolon = False
    seen_semicolon = False
    saw_meaningful_token = False

    n = len(sql)
    i = 0
    while i < n:
        ch = sql[i]
        # Whitespace
        if ch.isspace():
            out.append(ch)
            i += 1
            continue
        # Line comment --
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            end = sql.find("\n", i + 2)
            if end == -1:
                end = n
            out.append(sql[i:end])
            i = end
            continue
        # Block comment /* ... */
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            if end == -1:
                return None, None, ("failed", "CATALOG-RECIPE-SQL-SHAPE", "Unterminated block comment in recipe SQL.")
            out.append(sql[i:end + 2])
            i = end + 2
            continue
        if seen_semicolon:
            has_tokens_after_semicolon = True
        # Single-quoted string literal '...'
        if ch == "'":
            saw_meaningful_token = True
            start = i
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(sql[start:i])
            continue
        # Double-quoted identifier "..."
        if ch == '"':
            saw_meaningful_token = True
            start = i
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(sql[start:i])
            continue
        # Semicolon
        if ch == ";":
            seen_semicolon = True
            i += 1
            continue
        saw_meaningful_token = True
        # Unsupported PostgreSQL JSON extraction operators ->, ->>, #>, #>>
        if ch == "-" and i + 1 < n and sql[i + 1] == ">":
            return None, None, (
                "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED",
                "JSON operator extraction is outside the DataFusion SQL profile; use json_get functions.",
            )
        if ch == "#" and i + 1 < n and sql[i + 1] == ">":
            return None, None, (
                "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED",
                "JSON path operator extraction is outside the DataFusion SQL profile.",
            )
        # Positional ? placeholder is unsupported in DataFusion (use $1..$n or $name)
        if ch == "?":
            return None, None, (
                "failed", "CATALOG-RECIPE-PARAMETERS",
                "DataFusion recipes do not support '?' placeholders; use '$1'..'$n' with parameterOrder or '$name'.",
            )
        # $1..$n or $name placeholder
        if ch == "$" and i + 1 < n:
            if sql[i + 1].isdigit():
                j = i + 1
                while j < n and sql[j].isdigit():
                    j += 1
                index = int(sql[i + 1:j])
                if order is None or index < 1 or index > len(order):
                    return None, None, (
                        "failed", "CATALOG-RECIPE-PARAMETERS",
                        f"Positional parameter ${index} exceeds declared parameterOrder.",
                    )
                param_name = order[index - 1]
                if param_name not in props:
                    return None, None, (
                        "failed", "CATALOG-RECIPE-PARAMETERS",
                        f"Positional parameter {param_name!r} is missing from recipe parameters.",
                    )
                bound[str(index)] = sample_parameter_value(props[param_name])
                out.append(sql[i:j])
                i = j
                continue
            if sql[i + 1].isalpha() or sql[i + 1] == "_":
                j = i + 2
                while j < n and (sql[j].isalnum() or sql[j] == "_"):
                    j += 1
                name = sql[i + 1:j]
                if name not in props:
                    return None, None, (
                        "failed", "CATALOG-RECIPE-PARAMETERS",
                        f"Named parameter ${name} is not declared in recipe parameters.",
                    )
                bound[name] = sample_parameter_value(props[name])
                out.append(sql[i:j])
                i = j
                continue
        # :name placeholder is unsupported in DataFusion (ignoring :: type casts)
        if ch == ":":
            if i + 1 < n and sql[i + 1] == ":":
                out.append("::")
                i += 2
                continue
            if i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "_"):
                j = i + 2
                while j < n and (sql[j].isalnum() or sql[j] == "_"):
                    j += 1
                name = sql[i + 1:j]
                return None, None, (
                    "failed", "CATALOG-RECIPE-PARAMETERS",
                    f"DataFusion recipes do not support ':{name}' placeholders; use '${name}' or '$1'..'$n'.",
                )
        out.append(ch)
        i += 1

    if not saw_meaningful_token or has_tokens_after_semicolon:
        return None, None, (
            "failed", "CATALOG-RECIPE-SQL-SHAPE",
            "Recipe SQL must contain exactly one SQL query statement.",
        )
    return "".join(out).strip(), bound, None


def classify_docspec_sql_error(error):
    """Map a DocSpec prepare-job or 0-row job error dict to (status, code, message)."""
    code = (error or {}).get("code") or ""
    message = (error or {}).get("message") or "DocSpec rejected the SQL query."
    low = message.lower()

    if code == "implicit_cast":
        return "failed", "CATALOG-RECIPE-TYPE", message
    if code in {"DOCSPEC-TIMEOUT", "DOCSPEC-CANCELLED", "DOCSPEC-IO", "DOCSPEC-NO-RECEIPT", "DOCSPEC-RECEIPT-LIMIT"}:
        return "not_run", "EXEC-NATIVE-UNAVAILABLE", message

    if "dot access not supported" in low:
        return "failed", "CATALOG-RECIPE-COLUMN", message

    if "invalid function '" in low or 'invalid function "' in low:
        return "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED", message
    if "not implemented" in low or "this feature is not implemented" in low:
        return "unknown", "CATALOG-RECIPE-SQL-UNSUPPORTED", message

    if ("table '" in low and "not found" in low) or ('table "' in low and "not found" in low) or "failed to resolve table" in low:
        return "failed", "CATALOG-RECIPE-TABLE", message

    if "cast error:" in low or "cannot cast" in low or "type_coercion" in low or "cannot coerce" in low:
        return "failed", "CATALOG-RECIPE-TYPE", message

    if (
        "schema contains duplicate" in low
        or "projections require unique expression names" in low
        or "sql parser error" in low
        or ("expected:" in low and "sql" in low)
        or "push_down_leaf_projections" in low
        or "__datafusion_extracted_" in low
        or "optimizer rule" in low
    ):
        return "failed", "CATALOG-RECIPE-SQL-SHAPE", message

    if (
        "no field named" in low
        or "not found in struct" in low
        or ("column" in low and ("not found" in low or "does not exist" in low))
        or ("join key" in low and "does not exist" in low)
        or ("order by" in low and ("out of bounds" in low or "index" in low or "position" in low))
        or "only structs" in low
        or "field access" in low
        or "cannot access field" in low
        or "get_field" in low
        or "cannot index" in low
        or "array_element does not support type" in low
        or ("list_element" in low and "utf8" in low)
    ):
        return "failed", "CATALOG-RECIPE-COLUMN", message

    if "placeholder" in low or "parameter" in low and ("missing" in low or "unresolved" in low or "not found" in low):
        return "failed", "CATALOG-RECIPE-PARAMETERS", message

    return "failed", "CATALOG-RECIPE-TYPE", message


def evaluate_recipe_specs(recipes, adapter):
    """Validate a list of recipe specs via DocSpec prepare-job + 0-row job execution.

    Each entry in ``recipes`` has:
      - ``id``: recipe identifier
      - ``sql``: UTF-8 SQL string
      - ``dialect``: declared SQL dialect
      - ``inputs``: ``{sql_input_name: odcs_schema_dict}``
      - ``parameters``: JSON Schema dict
      - ``parameterOrder`` (optional): list of parameter names
      - ``result`` (optional): ODCS schema dict for ``resultDataset``
    """
    try:
        import pyarrow as pa
    except ImportError as exc:
        return {
            "status": "not_run",
            "reason": f"PyArrow is required to synthesize 0-row Parquet inputs for DocSpec SQL gating: {exc}",
            "results": {},
        }

    gate_dir = Path(tempfile.mkdtemp(prefix="recipe-gate-", dir=adapter.evidence_dir))
    parquet_cache = {}

    def empty_input(odcs_schema):
        key = sha256(json_dumps(odcs_schema, sort_keys=True).encode("utf-8")).hexdigest()
        if key not in parquet_cache:
            pa_schema = odcs_schema_to_pyarrow(odcs_schema, pa)
            pq_path = gate_dir / f"input-{key[:16]}.parquet"
            write_empty_parquet(pq_path, pa_schema)
            parquet_cache[key] = (pq_path, pa_schema, encode_ipc_schema_base64(pa_schema))
        return parquet_cache[key]

    results = {}
    evidence_records = []
    seen_evidence = set()

    def record_evidence(resp):
        ev = (resp or {}).get("evidence")
        if ev and ev["path"] not in seen_evidence:
            seen_evidence.add(ev["path"])
            evidence_records.append({"kind": "native-report", "path": ev["path"], "sha256": ev["sha256"]})
            return ({"kind": "native-report", "path": ev["path"], "sha256": ev["sha256"]},)
        return ()

    for index, recipe in enumerate(recipes):
        rid = recipe["id"]
        dialect = recipe.get("dialect", "datafusion")
        if dialect != "datafusion":
            reason = f"Dialect {dialect!r} is outside the DataFusion DocSpec SQL profile."
            results[rid] = {
                "status": "unknown",
                "reason": reason,
                "diagnostics": [{"code": "CATALOG-RECIPE-SQL-UNSUPPORTED", "severity": "warning", "message": reason}],
                "evidence": (),
            }
            continue

        rewritten_sql, bound_params, sql_issue = analyze_and_prepare_sql(
            recipe["sql"], recipe.get("parameters"), recipe.get("parameterOrder"),
        )
        if sql_issue is not None:
            status, code, msg = sql_issue
            results[rid] = {
                "status": status,
                "reason": msg if status != "failed" else None,
                "diagnostics": [{
                    "code": code,
                    "severity": "error" if status == "failed" else "warning",
                    "message": msg,
                }],
                "evidence": (),
            }
            continue

        try:
            job_inputs = []
            prep_inputs = []
            for input_name, odcs_schema in sorted(recipe.get("inputs", {}).items()):
                pq_path, _, ipc_b64 = empty_input(odcs_schema)
                job_inputs.append({"kind": "parquet", "name": input_name, "path": str(pq_path)})
                prep_inputs.append({"name": input_name, "schema_ipc_base64": ipc_b64})
        except UnmappedSchemaError as exc:
            reason = str(exc)
            results[rid] = {
                "status": "unknown",
                "reason": reason,
                "diagnostics": [{"code": "CATALOG-RECIPE-SQL-UNSUPPORTED", "severity": "warning", "message": reason}],
                "evidence": (),
            }
            continue

        recipe_dir = gate_dir / f"r-{index:04d}"
        recipe_dir.mkdir(parents=True, exist_ok=True)
        step_spec = {"name": "recipe_output", "sql": rewritten_sql}
        if bound_params:
            step_spec["parameters"] = bound_params
        job_spec = {
            "scratch": str(recipe_dir / "scratch"),
            "inputs": job_inputs,
            "steps": [step_spec],
            "outputs": [],
            "queries": [{"name": "recipe_probe", "sql": 'SELECT * FROM "recipe_output"'}],
        }
        spec_path = recipe_dir / "job.json"
        spec_bytes = (json.dumps(job_spec, sort_keys=True) + "\n").encode("utf-8")
        spec_path.write_bytes(spec_bytes)

        prep_resp = adapter.prepare_job({
            "job": {"path": str(spec_path), "sha256": sha256(spec_bytes).hexdigest()},
            "inputs": prep_inputs,
        })
        ev_list = list(record_evidence(prep_resp))
        if prep_resp["status"] != "succeeded":
            status, code, msg = classify_docspec_sql_error(prep_resp.get("error") or {})
            results[rid] = {
                "status": status,
                "reason": msg if status in {"unknown", "not_run"} else None,
                "diagnostics": [{
                    "code": code,
                    "severity": "error" if status == "failed" else "warning",
                    "message": msg,
                }],
                "evidence": tuple(ev_list),
            }
            continue

        # Decode inferred output schema from prepare-job
        prepared = prep_resp["result"]
        step_view = next(view for view in prepared["steps"] if view["name"] == "recipe_output")
        out_pa_schema = decode_ipc_schema_base64(prepared["schemas"][step_view["schema_sha256"]])
        try:
            output_cols = pyarrow_schema_to_odcs(out_pa_schema, pa)
        except UnmappedSchemaError as exc:
            reason = str(exc)
            results[rid] = {
                "status": "unknown",
                "reason": reason,
                "diagnostics": [{"code": "CATALOG-RECIPE-SQL-UNSUPPORTED", "severity": "warning", "message": reason}],
                "evidence": tuple(ev_list),
            }
            continue

        # Execute 0-row docspec job to catch optimizer/execution-plan faults (e.g. dr-7uke)
        exec_resp = adapter.execute(job_spec, spec_path=spec_path)
        ev_list.extend(record_evidence(exec_resp))
        if exec_resp["status"] != "succeeded":
            status, code, msg = classify_docspec_sql_error(exec_resp.get("error") or {})
            results[rid] = {
                "status": status,
                "reason": msg if status in {"unknown", "not_run"} else None,
                "diagnostics": [{
                    "code": code,
                    "severity": "error" if status == "failed" else "warning",
                    "message": msg,
                }],
                "evidence": tuple(ev_list),
            }
            continue

        result_diags = []
        if recipe.get("result") is not None:
            result_diags = compare_output_to_odcs(output_cols, recipe["result"])

        results[rid] = {
            "status": "failed" if result_diags else "passed",
            "diagnostics": result_diags,
            "output": output_cols,
            "evidence": tuple(ev_list),
        }

    return {
        "status": "completed",
        "parser": deepcopy(adapter.tool),
        "results": results,
        "evidence": tuple(evidence_records),
    }


def evaluate_job_spec(job_id, job_spec_doc, input_schemas, output_schemas, adapter, *,
                      out_of_catalog_inputs=(), out_of_catalog_outputs=()):
    """Verify a whole DocSpec JobSpec via prepare-job + 0-row job execution against ODCS schemas."""
    try:
        import pyarrow as pa
    except ImportError as exc:
        return {
            "status": "not_run",
            "reason": f"PyArrow is required to synthesize 0-row Parquet inputs for DocSpec job gating: {exc}",
            "diagnostics": [{"code": "EXEC-NATIVE-UNAVAILABLE", "severity": "warning", "message": str(exc)}],
            "evidence": (),
        }

    if out_of_catalog_inputs:
        reason = f"Job {job_id!r} declares out-of-catalog inputs {sorted(out_of_catalog_inputs)} without ODCS schemas."
        return {
            "status": "unknown",
            "reason": reason,
            "diagnostics": [{"code": "CATALOG-JOB-INPUT-UNBOUND", "severity": "warning", "message": reason}],
            "evidence": (),
        }

    gate_dir = Path(tempfile.mkdtemp(prefix="job-gate-", dir=adapter.evidence_dir))
    raw_job = deepcopy(job_spec_doc.value)
    job_inputs = []
    prep_inputs = []
    try:
        for item in raw_job.get("inputs", ()):
            name = item["name"]
            if name not in input_schemas:
                reason = f"Job {job_id!r} input {name!r} is not bound to a catalog dataset."
                return {
                    "status": "failed",
                    "diagnostics": [{"code": "CATALOG-JOB-SPEC-MISMATCH", "severity": "error", "message": reason}],
                    "evidence": (),
                }
            pa_schema = odcs_schema_to_pyarrow(input_schemas[name], pa)
            pq_path = gate_dir / f"in-{name}.parquet"
            write_empty_parquet(pq_path, pa_schema)
            job_inputs.append({"kind": "parquet", "name": name, "path": str(pq_path)})
            prep_inputs.append({"name": name, "schema_ipc_base64": encode_ipc_schema_base64(pa_schema)})
    except UnmappedSchemaError as exc:
        reason = str(exc)
        return {
            "status": "unknown",
            "reason": reason,
            "diagnostics": [{"code": "CATALOG-RECIPE-SQL-UNSUPPORTED", "severity": "warning", "message": reason}],
            "evidence": (),
        }

    rewritten_outputs = []
    for index, out_item in enumerate(raw_job.get("outputs", ())):
        out_copy = deepcopy(out_item)
        out_copy["path"] = str(gate_dir / f"out-{index:04d}-{out_item['name']}.parquet")
        rewritten_outputs.append(out_copy)

    gate_job = {
        **raw_job,
        "scratch": str(gate_dir / "scratch"),
        "inputs": job_inputs,
        "outputs": rewritten_outputs,
    }
    spec_path = gate_dir / "gate-job.json"
    spec_bytes = (json.dumps(gate_job, sort_keys=True) + "\n").encode("utf-8")
    spec_path.write_bytes(spec_bytes)

    evidence = []
    prep_resp = adapter.prepare_job({
        "job": {"path": str(spec_path), "sha256": sha256(spec_bytes).hexdigest()},
        "inputs": prep_inputs,
    })
    if prep_resp.get("evidence"):
        ev = prep_resp["evidence"]
        evidence.append({"kind": "native-report", "path": ev["path"], "sha256": ev["sha256"]})
    if prep_resp["status"] != "succeeded":
        status, code, msg = classify_docspec_sql_error(prep_resp.get("error") or {})
        return {
            "status": status,
            "reason": msg if status in {"unknown", "not_run"} else None,
            "diagnostics": [{"code": code, "severity": "error" if status == "failed" else "warning", "message": msg}],
            "evidence": tuple(evidence),
        }

    prepared = prep_resp["result"]
    diags = []
    for out_view in prepared.get("outputs", ()):
        name = out_view["name"]
        if name in out_of_catalog_outputs:
            continue
        if name not in output_schemas:
            diags.append({
                "code": "CATALOG-JOB-SPEC-MISMATCH",
                "severity": "error",
                "message": f"Job {job_id!r} output {name!r} is not bound to a catalog dataset.",
            })
            continue
        out_pa_schema = decode_ipc_schema_base64(prepared["schemas"][out_view["schema_sha256"]])
        try:
            out_cols = pyarrow_schema_to_odcs(out_pa_schema, pa)
        except UnmappedSchemaError as exc:
            return {
                "status": "unknown",
                "reason": str(exc),
                "diagnostics": [{"code": "CATALOG-RECIPE-SQL-UNSUPPORTED", "severity": "warning", "message": str(exc)}],
                "evidence": tuple(evidence),
            }
        diags.extend(compare_output_to_odcs(out_cols, output_schemas[name]))

    exec_resp = adapter.execute(gate_job, spec_path=spec_path)
    if exec_resp.get("evidence"):
        ev = exec_resp["evidence"]
        evidence.append({"kind": "native-report", "path": ev["path"], "sha256": ev["sha256"]})
    if exec_resp["status"] != "succeeded":
        status, code, msg = classify_docspec_sql_error(exec_resp.get("error") or {})
        return {
            "status": status,
            "reason": msg if status in {"unknown", "not_run"} else None,
            "diagnostics": [{"code": code, "severity": "error" if status == "failed" else "warning", "message": msg}],
            "evidence": tuple(evidence),
        }

    return {
        "status": "failed" if diags else "passed",
        "diagnostics": diags,
        "evidence": tuple(evidence),
    }


def bind_recipes_with_docspec(assembly, adapter):
    """Run the single-engine DocSpec recipe SQL gate for an Assembly."""
    from .catalog import CHECK_IDS, DETAILS, RECIPE_GROUP

    report = assembly.report
    if not assembly.queries:
        report.add(
            CHECK_IDS["recipes"], RECIPE_GROUP, "recipes", "not_run",
            applicable=False, evidence="inferred", reason="The loaded scope declares no recipes.",
        )
        return
    if adapter is None:
        report.missing_capabilities.add(RECIPE_GROUP)
        for identifier in sorted(assembly.queries):
            assembly.check(
                "recipes", identifier,
                CatalogError(
                    "ADAPTER-CAPABILITY-MISSING",
                    "Recipe SQL binding requires an explicitly selected DocSpec executable (--docspec).",
                    status="not_run",
                ),
                path=assembly.recipe_sources[identifier],
                required=True,
            )
        return

    bindable = []
    for identifier, (row, data) in sorted(assembly.queries.items()):
        input_schemas = {}
        blocked = None
        for name, ref in row["inputs"].items():
            if isinstance(ref, str):
                input_schemas[name] = assembly.dataset_schemas[ref]
            else:
                peer_alias, peer_ds = ref["catalog"], ref["dataset"]
                if peer_alias in assembly.unbound_peers:
                    code = (
                        "CATALOG-IMPORT-UNBOUND"
                        if assembly.unbound_peers[peer_alias] == "unbound"
                        else "CATALOG-IMPORT-MISMATCH"
                    )
                    status = "not_run" if code == "CATALOG-IMPORT-UNBOUND" else "failed"
                    blocked = CatalogError(
                        code, f"Recipe {identifier!r} requires bound peer catalog {peer_alias!r}.",
                        status=status,
                    )
                    break
                peer = assembly.peers[peer_alias]
                peer_defs = peer.catalog.get("extensions", {}).get(DETAILS, {}).get("datasetDefinitions", {})
                if peer_ds not in peer_defs:
                    blocked = CatalogError(
                        "CATALOG-PEER-FIELD-WITHHELD",
                        f"Peer dataset {peer_alias}:{peer_ds} withholds datasetDefinitions needed for SQL binding.",
                        status="unknown",
                    )
                    break
                input_schemas[name] = peer_defs[peer_ds]
        if blocked is not None:
            assembly.check("recipes", identifier, blocked, path=assembly.recipe_sources[identifier], required=True)
            continue
        bindable.append({
            "id": identifier,
            "sql": data.decode("utf-8"),
            "dialect": row["dialect"],
            "inputs": input_schemas,
            "parameters": row["parameters"],
            **({"parameterOrder": row["parameterOrder"]} if "parameterOrder" in row else {}),
            "result": assembly.dataset_schemas.get(row.get("resultDataset")),
        })
    if not bindable:
        return

    response = evaluate_recipe_specs(bindable, adapter)

    if response["status"] != "completed":
        reason = response.get("reason") or "DocSpec recipe gate did not complete."
        for entry in bindable:
            identifier = entry["id"]
            path = assembly.inventory.display_path(assembly.recipe_sources[identifier])
            report.add(
                CHECK_IDS["recipes"], RECIPE_GROUP, identifier, "not_run",
                required=True, evidence="inferred", reason=reason,
                diagnostics=[diagnostic("EXEC-NATIVE-UNAVAILABLE", reason, path=path)],
            )
        return

    assembly.recipe_parser = deepcopy(response["parser"])
    bindings = report.metadata.setdefault("recipeBindings", {})
    for entry in bindable:
        identifier = entry["id"]
        path = assembly.inventory.display_path(assembly.recipe_sources[identifier])
        result = response["results"][identifier]
        evidence = result.get("evidence") or ()
        report.add(
            CHECK_IDS["recipes"], RECIPE_GROUP, identifier, result["status"],
            required=True, evidence="executed" if evidence else "inferred",
            reason=result.get("reason"), evidence_records=evidence,
            diagnostics=[
                diagnostic(item["code"], item["message"], path=path, severity=item["severity"])
                for item in result["diagnostics"]
            ],
        )
        bindings[identifier] = {
            "parser": deepcopy(assembly.recipe_parser),
            **({"output": result["output"]} if "output" in result else {}),
            **({"evidence": list(evidence)} if evidence else {}),
        }
