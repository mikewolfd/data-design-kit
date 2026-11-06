"""Exact canonical public source-view schemas emitted by local DocSpec reads.

This profile describes observed Arrow data. It neither reconstructs original
types nor claims a physical table/snapshot identity absent from the receipt.
The raw schema owns types, nullability and metadata; the index only locates
every field and its complete native ID path. No value conversion occurs here.
"""

from copy import deepcopy
import re

from ddk.documents import json_dumps


PRIMITIVE_PROFILE = "urn:ddk:docspec:source-primitive:1"
RECURSIVE_PROFILE = "urn:ddk:docspec:source-arrow:2"
MAX_FIELDS = 4096
MAX_DEPTH = 16
MAX_NAME_BYTES = 1024
MAX_INDEX_BYTES = 2 << 20
_PRIMITIVES = {"Boolean", "Int32", "Int64", "Float32", "Float64", "Utf8", "LargeBinary", "Date32"}


def _metadata(value):
    if not isinstance(value, dict) or any(type(k) is not str or type(v) is not str for k, v in value.items()):
        raise ValueError("Native Arrow metadata must contain string keys and values")
    return value


def source_schema_index(schema):
    """Validate the complete source-only profile and index all field/item nodes.

    Unsupported types, absent IDs and incomplete children refuse the complete
    observation. Map entries have a different native ID model and are outside
    this profile. A fixed 16-byte binary is not inferred to mean UUID.
    """
    if not isinstance(schema, dict) or set(schema) != {"fields", "metadata"}:
        raise ValueError("Expected the native Arrow schema and its metadata")
    _metadata(schema["metadata"])
    index, ids = [], set()
    index_bytes = 2

    def field(node, path, parents, position, depth):
        nonlocal index_bytes
        if depth > MAX_DEPTH or len(index) >= MAX_FIELDS:
            raise ValueError("Native schema exceeds the recursive mapping bound")
        if (not isinstance(node, dict)
                or set(node) - {"name", "data_type", "nullable", "metadata", "dict_id", "dict_is_ordered"}
                or not {"name", "data_type", "nullable", "metadata"} <= node.keys()
                or type(node["name"]) is not str or not node["name"]
                or len(node["name"].encode("utf-8")) > MAX_NAME_BYTES
                or type(node["nullable"]) is not bool
                or node.get("dict_is_ordered", False) is not False
                or type(node.get("dict_id", 0)) is not int or node.get("dict_id", 0) != 0):
            raise ValueError("Incomplete or unsupported native Arrow field")
        metadata = _metadata(node["metadata"])
        identifier = metadata.get("PARQUET:field_id", "")
        if not re.fullmatch(r"[1-9][0-9]*", identifier) or not 0 < int(identifier) < 1 << 31:
            raise ValueError("Every native field and list item requires a positive i32 field ID")
        identifier = int(identifier)
        if identifier in ids:
            raise ValueError("Native field IDs must be unique across the complete schema")
        ids.add(identifier)
        native_path = [*parents, identifier]
        row = {"path": path, "nativeFieldPath": native_path, "position": position}
        index_bytes += len(json_dumps(row).encode("utf-8")) + (2 if index else 0)
        if index_bytes > MAX_INDEX_BYTES:
            raise ValueError("Native schema index exceeds its byte allocation")
        index.append(row)
        dtype = node["data_type"]
        if isinstance(dtype, str):
            if dtype not in _PRIMITIVES:
                raise ValueError(f"Unsupported canonical source type: {dtype}")
            return
        if not isinstance(dtype, dict) or len(dtype) != 1:
            raise ValueError("Unsupported native Arrow type declaration")
        kind, value = next(iter(dtype.items()))
        if kind == "Struct":
            siblings(value, path, native_path, depth + 1)
        elif kind == "List":
            field(value, [*path, {"each": True}], native_path, 0, depth + 1)
        elif kind == "Decimal128":
            if (not isinstance(value, list) or len(value) != 2 or any(type(v) is not int for v in value)
                    or not 1 <= value[0] <= 38 or not 0 <= value[1] <= value[0]):
                raise ValueError("Unsupported canonical decimal precision or scale")
        elif kind == "FixedSizeBinary":
            if type(value) is not int or not 0 < value < 1 << 31:
                raise ValueError("Fixed binary needs its exact positive byte width")
        elif kind == "Time64":
            if value != "Microsecond":
                raise ValueError("Canonical source time requires microsecond units")
        elif kind == "Timestamp":
            if (not isinstance(value, list) or len(value) != 2
                    or type(value[0]) is not str or (value[1] is not None and type(value[1]) is not str)
                    or value[0] not in {"Microsecond", "Nanosecond"}
                    or value[1] not in {None, "UTC", "+00:00"}):
                raise ValueError("Unsupported canonical timestamp unit or timezone")
        else:
            raise ValueError(f"Unsupported canonical source type: {kind}")

    def siblings(nodes, path, parents, depth):
        if not isinstance(nodes, list):
            raise ValueError("Native schema children must be a complete ordered array")
        names = set()
        for position, node in enumerate(nodes):
            name = node.get("name") if isinstance(node, dict) else None
            if not isinstance(name, str) or name in names:
                raise ValueError("Native sibling field names must be distinct strings")
            names.add(name)
            field(node, [*path, {"field": name}], parents, position, depth)

    siblings(schema["fields"], [], [], 1)
    return index


def source_native_read(version, receipt):
    """Describe the complete public source view using the explicit v2 shape."""
    if type(receipt["schema_id"]) is not int or not 0 <= receipt["schema_id"] < 1 << 31:
        raise ValueError("Invalid native source schema ID")
    fields = source_schema_index(receipt["schema"])
    return {
        "profile": RECURSIVE_PROFILE,
        "version": deepcopy(version),
        "schemaIdentity": {
            "scheme": "urn:docspec:source-arrow-schema:2",
            "value": f"blake3:{version['reference']['manifest']['digest']}:{receipt['schema_id']}",
        },
        "schema": deepcopy(receipt["schema"]),
        "fields": fields,
    }


def source_arrow_schema(schema, pa):
    """Decode only the validated canonical profile for exact IPC comparison.

    PyArrow is supplied by the runtime; neither the DDK core nor declaration
    checking imports it. This function creates a schema, never casts data.
    """
    source_schema_index(schema)
    primitives = {"Boolean": pa.bool_(), "Int32": pa.int32(), "Int64": pa.int64(),
                  "Float32": pa.float32(), "Float64": pa.float64(), "Utf8": pa.string(),
                  "LargeBinary": pa.large_binary(), "Date32": pa.date32()}

    def dtype(value):
        if isinstance(value, str):
            return primitives[value]
        kind, detail = next(iter(value.items()))
        if kind == "Struct":
            return pa.struct([field(child) for child in detail])
        if kind == "List":
            return pa.list_(field(detail))
        if kind == "Decimal128":
            return pa.decimal128(*detail)
        if kind == "FixedSizeBinary":
            return pa.binary(detail)
        if kind == "Time64":
            return pa.time64("us")
        if kind == "Timestamp":
            return pa.timestamp({"Microsecond": "us", "Nanosecond": "ns"}[detail[0]], detail[1])
        raise ValueError("Unsupported canonical source type")

    def field(value):
        return pa.field(value["name"], dtype(value["data_type"]), value["nullable"], value["metadata"])

    return pa.schema([field(value) for value in schema["fields"]], metadata=schema["metadata"])


def observed_source_schema(schema, pa):
    """Admit an IPC schema before reading batches, using the same v2 type rules."""
    primitives = {pa.bool_(): "Boolean", pa.int32(): "Int32", pa.int64(): "Int64",
                  pa.float32(): "Float32", pa.float64(): "Float64", pa.string(): "Utf8",
                  pa.large_binary(): "LargeBinary", pa.date32(): "Date32"}

    def metadata(value):
        return {key.decode("utf-8"): item.decode("utf-8") for key, item in (value or {}).items()}

    nodes = 0

    def dtype(value, depth):
        if value in primitives:
            return primitives[value]
        if pa.types.is_struct(value):
            return {"Struct": [field(child, depth + 1) for child in value]}
        if pa.types.is_list(value):
            return {"List": field(value.value_field, depth + 1)}
        if pa.types.is_decimal128(value):
            return {"Decimal128": [value.precision, value.scale]}
        if pa.types.is_fixed_size_binary(value):
            return {"FixedSizeBinary": value.byte_width}
        if pa.types.is_time64(value):
            return {"Time64": {"us": "Microsecond", "ns": "Nanosecond"}[value.unit]}
        if pa.types.is_timestamp(value):
            units = {"s": "Second", "ms": "Millisecond", "us": "Microsecond", "ns": "Nanosecond"}
            return {"Timestamp": [units[value.unit], value.tz]}
        raise ValueError(f"Unsupported canonical public source-view type: {value}")

    def field(value, depth=1):
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_FIELDS or len(value.name.encode("utf-8")) > MAX_NAME_BYTES:
            raise ValueError("Observed native schema exceeds the recursive mapping bound")
        return {"name": value.name, "data_type": dtype(value.type, depth), "nullable": value.nullable,
                "dict_id": 0, "dict_is_ordered": False, "metadata": metadata(value.metadata)}

    result = {"fields": [field(value) for value in schema], "metadata": metadata(schema.metadata)}
    source_schema_index(result)
    return result
