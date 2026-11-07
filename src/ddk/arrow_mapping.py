"""Versioned ODCS declarations and exact fixture literals, without a data validator.

The original scalar profile remains the default. The explicit recursive profile
describes Arrow storage and fixture conversion; value constraints still require
the maintained quality evaluator. Neither profile establishes native execution.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
import math
import re
import struct


SCALAR_PROFILE = "urn:ddk:odcs:arrow-scalar:1"
DECLARATION_PROFILE = "urn:ddk:odcs:arrow-declaration:2"
EXACT_PROFILE = "urn:ddk:odcs:arrow-declaration:3"
SCALAR_TYPES = {"string": "Utf8", "integer": "Int64", "boolean": "Boolean", "date": "Date32", "number": "Float64"}
_INTEGER_TYPES = {f"{prefix}{bits}": f"{native}{bits}" for prefix, native in (("i", "Int"), ("u", "UInt"))
                  for bits in (8, 16, 32, 64)}
_ARROW_ALIASES = {"Utf8": "string", "LargeUtf8": "large_string", "Boolean": "bool", "Date32": "date32",
                  "Binary": "binary", "LargeBinary": "large_binary",
                  "Float32": "float32", "Float64": "float64",
                  **{value: value.lower() for value in _INTEGER_TYPES.values()}}
_VALUE_OPTIONS = {
    "string": {"minLength", "maxLength", "pattern"},
    "integer": {"multipleOf", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "number": {"multipleOf", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "date": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "timestamp": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "time": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "object": {"minProperties", "maxProperties", "required"},
    "array": {"minItems", "maxItems", "uniqueItems"},
}
_TEXT_FORMATS = {"password", "email", "uuid", "uri", "hostname", "ipv4", "ipv6"}
_TIME_FORMATS = {"HH:mm:ss" + suffix: digits for suffix, digits in
                 (("", 0), (".SSS", 3), (".SSSSSS", 6), (".SSSSSSSSS", 9))}
_TIMESTAMP_FORMATS = {"yyyy-MM-dd" + separator + clock: (separator, digits)
                      for separator in (" ", "'T'") for clock, digits in _TIME_FORMATS.items()}
_UTC_ZONES = {"UTC", "Etc/UTC", "+00:00"}
_MAX_DEPTH, _MAX_FIELDS = 16, 4096


class MappingUnavailable(ValueError):
    """The selected profile cannot preserve a declaration or fixture value."""


def _field(name, dtype, nullable):
    return {"name": name, "data_type": dtype, "nullable": nullable, "dict_id": 0,
            "dict_is_ordered": False, "metadata": {}}


def _temporal_type(logical, options):
    """Support a finite JDK-format subset, with explicitly declared zone meaning."""
    fmt, aware, zone = (options.get(key) for key in ("format", "timezone", "defaultTimezone"))
    if logical == "date":
        return "Date32" if fmt in (None, "yyyy-MM-dd") else None
    if type(aware) is not bool:
        return None
    if logical == "time":
        if fmt not in _TIME_FORMATS or aware or zone is not None:
            return None
        return {"Time64": "Nanosecond" if _TIME_FORMATS[fmt] == 9 else "Microsecond"}
    if not isinstance(fmt, str):
        return None
    base = fmt.removesuffix("XXX")
    if base not in _TIMESTAMP_FORMATS:
        return None
    if aware:
        if not fmt.endswith("XXX") or zone not in _UTC_ZONES:
            return None
    elif fmt.endswith("XXX") or zone is not None:
        return None
    return {"Timestamp": ["Nanosecond" if _TIMESTAMP_FORMATS[base][1] == 9 else "Microsecond", zone]}


def _validate_declaration(dataset):
    # The exact pinned upstream shape owns conditional option sets. JSON Schema
    # defaults remain annotations: this validator inserts no values.
    from .documents import schema_registry, schema_validator
    registry, schemas, _ = schema_registry()
    odcs = schemas["dataset"]
    schema = {"$schema": odcs["$schema"], "$defs": odcs["$defs"], "$ref": "#/$defs/SchemaObject"}
    if error := next(schema_validator(schema, resource_registry=registry).iter_errors(dataset), None):
        raise MappingUnavailable(f"Invalid pinned ODCS dataset declaration at {error.json_path}: {error.message}")


def _exact_type(prop):
    """Finite canonical physical spellings, never an engine SQL type parser."""
    physical, logical = prop.get("physicalType"), prop.get("logicalType")
    options = prop.get("logicalTypeOptions", {})
    if not isinstance(physical, str):
        return None
    if logical == "number" and "format" not in options:
        match = re.fullmatch(r"decimal(128|256)\(([1-9][0-9]*),(0|[1-9][0-9]*)\)", physical)
        if match and len(match[2]) <= 2 and len(match[3]) <= 2:
            bits, precision, scale = map(int, match.groups())
            if 0 <= scale <= precision <= (38 if bits == 128 else 76):
                return {f"Decimal{bits}": [precision, scale]}
    if logical == "string" and options.get("format") == "binary":
        if physical in {"binary", "large_binary"}:
            return {"binary": "Binary", "large_binary": "LargeBinary"}[physical]
        match = re.fullmatch(r"fixed\[([1-9][0-9]*)\]", physical)
        if match and len(match[1]) <= 5 and int(match[1]) <= 65536:
            return {"FixedSizeBinary": int(match[1])}
    return None


def _recursive_schema(dataset, profile):
    _validate_declaration(dataset)
    coverage, count = [], 0

    def record(path, facet, status, meaning, **details):
        coverage.append({"path": deepcopy(path), "facet": facet, "status": status,
                         "meaning": meaning, "profile": profile, **details})

    def external_obligations(node, path, scope):
        # Preserve declarations for their maintained owners. In particular,
        # definitions.enum_values owns legacy enum interpretation/precedence;
        # the mapper must not activate, rewrite or evaluate those constraints.
        for index, custom in enumerate(node.get("customProperties", [])):
            constraint = None
            if scope == "property" and custom["property"] == "enum":
                constraint = "enum"
            elif scope == "schema" and custom.get("vendor") == "ddk" and custom["property"] == "rowIdentity":
                constraint = "ddk.rowIdentity"
            if constraint:
                record(path, f"customProperties/{index}", "unknown", "validation-needed",
                       value=deepcopy(custom), scope=scope, constraint=constraint,
                       reason="Requires maintained declaration interpretation and actual-data validation")
        for index, relationship in enumerate(node.get("relationships", [])):
            record(path, f"relationships/{index}", "unknown", "validation-needed",
                   value=deepcopy(relationship), scope=scope, constraint="relationship",
                   reason="Requires maintained relationship resolution and actual-data validation")

    def siblings(properties, path, depth):
        if not properties:
            record(path, "properties", "unsupported", "physical-mapping",
                   reason="This profile requires declared nonempty children for exact Parquet fixture materialization")
            return []
        names = [prop["name"] for prop in properties]
        if len(names) != len(set(names)):
            raise MappingUnavailable("Object property names must be distinct")
        return [field(prop, prop["name"], [*path, {"field": prop["name"]}], depth) for prop in properties]

    def field(prop, name, path, depth):
        nonlocal count
        count += 1
        if count > _MAX_FIELDS or depth > _MAX_DEPTH:
            raise MappingUnavailable("Declaration exceeds the recursive field/depth bound")
        logical, options = prop.get("logicalType"), prop.get("logicalTypeOptions", {})
        exact = _exact_type(prop) if profile == EXACT_PROFILE else None
        dtype = None
        if logical == "integer":
            dtype = _INTEGER_TYPES.get(options.get("format"))
        elif logical == "number":
            dtype = {"f32": "Float32", "f64": "Float64"}.get(options.get("format"))
        elif logical in {"date", "timestamp", "time"}:
            dtype = _temporal_type(logical, options)
        elif logical == "string":
            if options.get("format") is None or options["format"] in _TEXT_FORMATS:
                dtype = "Utf8"
        elif logical == "boolean":
            dtype = "Boolean"
        elif logical == "object":
            dtype = {"Struct": siblings(prop.get("properties"), path, depth + 1)}
        elif logical == "array":
            if "items" in prop:
                dtype = {"List": field(prop["items"], "element", [*path, {"each": True}], depth + 1)}
        if exact is not None:
            dtype = exact
        record(path, "logicalType", "exact" if dtype is not None else "unsupported", "physical-mapping",
               value=logical, mapping=deepcopy(dtype), reason="Explicit profile; no inferred numeric format or timezone")
        record(path, "required", "exact", "physical-mapping", nullable=not prop.get("required", False),
               declared="required" in prop)
        if "name" in prop and prop["name"] != name:
            record(path, "name", "unsupported", "physical-mapping", value=prop["name"],
                   reason="List items use the canonical Parquet element name")
        if prop.get("required"):
            record(path, "required", "unknown", "validation-needed", value=True,
                   reason="Declared nullability is not evidence that actual data satisfies it")
        for key, value in options.items():
            meaning = "validation-needed" if key in _VALUE_OPTIONS.get(logical, set()) else "physical-mapping"
            if logical == "string" and key == "format" and value in _TEXT_FORMATS:
                meaning = "validation-needed"
            supported = key in _VALUE_OPTIONS.get(logical, set()) or (
                key == "format" and logical in {"integer", "number", "date", "timestamp", "time"} and dtype is not None
            ) or (key in {"timezone", "defaultTimezone"} and logical in {"time", "timestamp"} and dtype is not None)
            supported = supported or (logical == "string" and key == "format" and value in _TEXT_FORMATS)
            supported = supported or (exact is not None and logical == "string" and key == "format" and value == "binary")
            record(path, "logicalTypeOptions/" + key,
                   "unknown" if supported and meaning == "validation-needed" else "exact" if supported else "unsupported",
                   meaning, value=deepcopy(value),
                   reason="Requires separate maintained data validation" if meaning == "validation-needed"
                          else "Preserved by the explicit mapping" if supported else "No exact mapping in this profile")
        if "logicalTypeOptions" in prop and not options:
            record(path, "logicalTypeOptions", "exact", "physical-mapping", value={})
        for key in ("enum", "unique", "primaryKey", "primaryKeyPosition", "quality"):
            if key in prop:
                record(path, key, "unknown", "validation-needed", value=deepcopy(prop[key]),
                       reason="A declaration or fixture conversion does not execute data rules")
        external_obligations(prop, path, "property")
        physical = prop.get("physicalType") if exact is not None else dtype if isinstance(dtype, str) else None
        for key, expected in (("physicalName", name), ("physicalType", physical)):
            if key in prop:
                record(path, key, "exact" if prop[key] == expected else "unsupported", "physical-mapping",
                       value=prop[key], reason="Only identical names and this profile's explicit canonical Arrow spellings are supported")
        return _field(name, dtype, not prop.get("required", False))

    fields = siblings(dataset.get("properties"), [], 1)
    if dataset.get("quality"):
        record([], "quality", "unknown", "validation-needed", value=deepcopy(dataset["quality"]))
    external_obligations(dataset, [], "schema")
    return {"fields": fields, "metadata": {}}, coverage


def _scalar_schema(dataset):
    fields, coverage = [], []
    for prop in dataset.get("properties", []):
        logical = prop.get("logicalType")
        if logical not in SCALAR_TYPES or prop.get("logicalTypeOptions"):
            coverage.append({"field": prop["name"], "facet": "logicalType", "status": "unsupported",
                             "reason": "The scalar v1 profile cannot preserve type options or nested types"})
            coverage.extend({"field": prop["name"], "facet": "logicalTypeOptions/" + key,
                             "status": "unsupported", "value": deepcopy(value)}
                            for key, value in prop.get("logicalTypeOptions", {}).items())
            continue
        fields.append(_field(prop["name"], SCALAR_TYPES[logical], not prop.get("required", False)))
        coverage.append({"field": prop["name"], "facet": "logicalType", "status": "exact", "mapping": SCALAR_TYPES[logical]})
    return {"fields": fields, "metadata": {}}, coverage


def pyarrow_schema(schema, pa):
    """Construct a declared Arrow schema; PyArrow is injected only by execution."""
    def dtype(value):
        if isinstance(value, str):
            return pa.type_for_alias(_ARROW_ALIASES[value])
        kind, detail = next(iter(value.items()))
        if kind == "Struct":
            return pa.struct([field(child) for child in detail])
        if kind == "List":
            return pa.list_(field(detail))
        if kind == "FixedSizeBinary":
            return pa.binary(detail)
        if kind in {"Decimal128", "Decimal256"}:
            return (pa.decimal128 if kind == "Decimal128" else pa.decimal256)(*detail)
        units = {"Microsecond": "us", "Nanosecond": "ns"}
        if kind == "Time64":
            return pa.time64(units[detail])
        if kind == "Timestamp":
            return pa.timestamp(units[detail[0]], detail[1])
        raise MappingUnavailable("Unsupported declared Arrow type")

    def field(value):
        return pa.field(value["name"], dtype(value["data_type"]), nullable=value["nullable"])

    return pa.schema([field(value) for value in schema["fields"]])


def _temporal_value(value, prop, dtype):
    if not isinstance(value, str):
        raise ValueError("Temporal fixtures require explicitly formatted strings")
    if dtype == "Date32":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("Date fixtures require yyyy-MM-dd")
        return date.fromisoformat(value)
    logical, options = prop["logicalType"], prop["logicalTypeOptions"]
    fmt = options["format"]
    digits = _TIME_FORMATS[fmt] if logical == "time" else _TIMESTAMP_FORMATS[fmt.removesuffix("XXX")][1]
    clock = r"(?P<h>[0-9]{2}):(?P<m>[0-9]{2}):(?P<s>[0-9]{2})"
    fraction = rf"\.(?P<f>[0-9]{{{digits}}})" if digits else ""
    pattern = clock + fraction
    if logical == "timestamp":
        separator = _TIMESTAMP_FORMATS[fmt.removesuffix("XXX")][0].replace("'", "")
        pattern = r"(?P<d>[0-9]{4}-[0-9]{2}-[0-9]{2})" + separator + pattern
        if options["timezone"]:
            pattern += r"(?:Z|\+00:00)"
    match = re.fullmatch(pattern, value)
    if match is None:
        raise ValueError("Temporal fixture differs from its explicit format/UTC offset")
    parts = match.groupdict()
    hour, minute, second = (int(parts[key]) for key in ("h", "m", "s"))
    time(hour, minute, second)  # Reject invalid clock fields and leap seconds.
    days = (date.fromisoformat(parts["d"]) - date(1970, 1, 1)).days if "d" in parts else 0
    scale = 9 if digits == 9 else 6
    result = ((days * 24 + hour) * 3600 + minute * 60 + second) * 10**scale
    result += int(parts.get("f") or 0) * 10**(scale - digits)
    if not -(1 << 63) <= result < (1 << 63):
        raise MappingUnavailable("Temporal fixture exceeds its exact Arrow unit range")
    return result


def _decimal_value(value, precision, scale):
    if type(value) not in (int, Decimal):
        raise MappingUnavailable("Decimal fixtures require an exact JSON/Python decimal or integer, never a float or string")
    value = Decimal(value)
    if not value.is_finite() or (value.is_zero() and value.is_signed()):
        raise MappingUnavailable("Decimal fixtures require finite values without an unrepresentable negative zero")
    sign, digits, exponent = value.as_tuple()
    shift = exponent + scale
    if value.is_zero():
        digits = (0,)
    elif shift >= 0:
        if len(digits) + shift > precision:
            raise MappingUnavailable("Decimal fixture exceeds its declared precision")
        digits = digits + (0,) * shift
    else:
        if -shift >= len(digits) or any(digits[shift:]):
            raise MappingUnavailable("Decimal fixture would require rounding to its declared scale")
        digits = digits[:shift]
    if len(digits) > precision:
        raise MappingUnavailable("Decimal fixture exceeds its declared precision")
    return Decimal((sign, digits, -scale))


def _binary_value(value, width=None):
    if type(value) is not bytes or (width is not None and len(value) != width):
        raise MappingUnavailable("Binary fixtures require raw bytes of the declared width; no text encoding is inferred")
    return value


def _value(value, prop, field, recursive):
    dtype = field["data_type"]
    if value is None:
        if not field["nullable"]:
            raise ValueError(f"Fixture {field['name']} requires a non-null value")
        return None
    if isinstance(dtype, dict):
        kind, detail = next(iter(dtype.items()))
        if kind == "Struct":
            return _row(value, prop["properties"], detail, recursive)
        if kind == "List":
            if type(value) is not list:
                raise ValueError("Array fixtures require a list")
            return [_value(item, prop["items"], detail, recursive) for item in value]
        if kind in {"Decimal128", "Decimal256"}:
            return _decimal_value(value, *detail)
        if kind == "FixedSizeBinary":
            return _binary_value(value, detail)
        return _temporal_value(value, prop, dtype)
    if dtype in {"Binary", "LargeBinary"}:
        return _binary_value(value)
    if dtype == "Date32":
        return _temporal_value(value, prop, dtype)
    if dtype.startswith(("Int", "UInt")):
        bits = int(dtype.removeprefix("UInt").removeprefix("Int"))
        low, high = (0, 1 << bits) if dtype.startswith("U") else (-(1 << (bits - 1)), 1 << (bits - 1))
        if type(value) is not int or not low <= value < high:
            raise ValueError(f"Fixture {field['name']} requires an exact {dtype} integer")
    elif dtype in {"Float32", "Float64"}:
        if type(value) not in (int, float, Decimal):
            raise ValueError("Numeric fixtures require explicitly representable numbers")
        try:
            converted = float(value)
            if dtype == "Float32":
                converted = struct.unpack("!f", struct.pack("!f", converted))[0]
        except (OverflowError, struct.error):
            raise MappingUnavailable(f"Fixture value exceeds {dtype}") from None
        if not math.isfinite(converted) or Decimal.from_float(converted) != Decimal(value):
            raise MappingUnavailable(f"Fixture value is not exactly representable as {dtype}")
        return converted
    elif (dtype == "Utf8" and type(value) is not str) or (dtype == "Boolean" and type(value) is not bool):
        raise ValueError(f"Fixture {field['name']} requires {dtype}")
    return value


def _row(row, properties, fields, recursive):
    if not isinstance(row, dict):
        raise ValueError("Object fixtures require dictionaries")
    names = {prop["name"] for prop in properties}
    if set(row) - names:
        raise ValueError("Fixture object has undeclared members")
    if recursive and names - row.keys():
        raise MappingUnavailable("Arrow cannot preserve absent members separately from null; supply an explicit presence representation")
    return {prop["name"]: _value(row.get(prop["name"]), prop, field, recursive)
            for prop, field in zip(properties, fields, strict=True)}


@dataclass
class DeclarationMapping:
    """One captured declaration shared by schema and exact fixture conversion."""

    dataset: dict
    profile: str
    schema: dict
    coverage: list

    def require_physical(self):
        if any(item["status"] != "exact" and item.get("meaning") != "validation-needed" for item in self.coverage):
            raise MappingUnavailable("Unsupported Arrow declaration mapping; inspect mappingCoverage")

    def rows(self, rows):
        self.require_physical()
        return [_row(row, self.dataset["properties"], self.schema["fields"], self.profile != SCALAR_PROFILE) for row in rows]


def map_declaration(dataset, *, profile=SCALAR_PROFILE):
    """Capture one selected mapping; constraints remain separate data obligations."""
    original = deepcopy(dataset)
    if profile == SCALAR_PROFILE:
        schema, coverage = _scalar_schema(original)
    elif isinstance(profile, str) and profile in {DECLARATION_PROFILE, EXACT_PROFILE}:
        schema, coverage = _recursive_schema(original, profile)
    else:
        raise MappingUnavailable(f"Unknown Arrow declaration profile {profile!r}")
    return DeclarationMapping(original, profile, schema, coverage)


def arrow_schema(dataset, *, profile=SCALAR_PROFILE):
    mapping = map_declaration(dataset, profile=profile)
    return mapping.schema, mapping.coverage


def typed_rows(rows, dataset, *, profile=SCALAR_PROFILE):
    """Convert fixture literals exactly; this is not whole-data rule validation."""
    return map_declaration(dataset, profile=profile).rows(rows)
