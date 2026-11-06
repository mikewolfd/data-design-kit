"""Explicit logical-to-Arrow declaration mapping, independent of runtime modules."""

from datetime import date
from decimal import Decimal
import math


SCALAR_TYPES = {"string": "Utf8", "integer": "Int64", "boolean": "Boolean", "date": "Date32", "number": "Float64"}


class MappingUnavailable(ValueError):
    """The selected implementation has no exact mapping for an admitted value."""


def arrow_schema(dataset):
    fields, coverage = [], []
    for prop in dataset.get("properties", []):
        logical = prop.get("logicalType")
        if logical not in SCALAR_TYPES or (logical == "number" and prop.get("logicalTypeOptions")):
            coverage.append({"field": prop["name"], "facet": "logicalType", "status": "unsupported",
                             "reason": "This scalar Arrow profile does not establish an exact mapping"})
            continue
        fields.append({"name": prop["name"], "data_type": SCALAR_TYPES[logical],
                       "nullable": not prop.get("required", False), "dict_id": 0,
                       "dict_is_ordered": False, "metadata": {}})
        coverage.append({"field": prop["name"], "facet": "logicalType", "status": "exact",
                         "mapping": SCALAR_TYPES[logical]})
    return {"fields": fields, "metadata": {}}, coverage


def typed_rows(rows, dataset):
    """Admit fixture literals before conversion; never coerce strings to numbers."""
    properties = dataset["properties"]
    names = {prop["name"] for prop in properties}
    output = []
    for index, row in enumerate(rows):
        if set(row) - names:
            raise ValueError(f"Fixture row {index} has undeclared columns")
        converted = {}
        for prop in properties:
            name, logical = prop["name"], prop["logicalType"]
            value = row.get(name)
            if value is None:
                if prop.get("required"):
                    raise ValueError(f"Fixture row {index} is missing required {name}")
            elif logical == "date":
                if not isinstance(value, str) or len(value) != 10:
                    raise ValueError(f"Fixture {name} requires an ISO calendar date")
                value = date.fromisoformat(value)
            elif logical == "integer":
                if type(value) is not int or not -(1 << 63) <= value < (1 << 63):
                    raise ValueError(f"Fixture {name} requires a signed 64-bit integer")
            elif logical == "string" and type(value) is not str:
                raise ValueError(f"Fixture {name} requires a string")
            elif logical == "boolean" and type(value) is not bool:
                raise ValueError(f"Fixture {name} requires a boolean")
            elif logical == "number":
                if type(value) not in (int, float, Decimal):
                    raise ValueError(f"Fixture {name} requires an explicitly representable float")
                converted_float = float(value)
                if not math.isfinite(converted_float) or Decimal.from_float(converted_float) != Decimal(value):
                    raise MappingUnavailable(f"Fixture {name} is not exactly representable as Float64")
                value = converted_float
            elif logical not in SCALAR_TYPES:
                raise ValueError(f"Unsupported fixture type {logical}")
            converted[name] = value
        output.append(converted)
    return output
