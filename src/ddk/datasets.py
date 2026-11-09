"""Declared tabular ODCS compatibility, independent of runtime types."""

from dataclasses import dataclass

from .definitions import enum_values
from .documents import json_pointer
from .interfaces import json_contains
from .results import diagnostic, location

SCALARS = {"string", "integer", "number", "boolean", "date", "time", "timestamp", "binary"}
UNSUPPORTED_OPTIONS = {"enum"}


@dataclass(frozen=True)
class Compatibility:
    status: str
    diagnostics: tuple
    fields: tuple


def compare_datasets(available, required, allow_additional, *, path, pointer, display_path=str):
    """Compare actual declaration to a consumer's requirements by name."""
    if available is None or required is None:
        return Compatibility("not_run", (), ())
    if available.effective is None or required.effective is None:
        return Compatibility("not_run", (), ())

    supplied = {prop["name"]: (index, prop) for index, prop in enumerate(available.effective.get("properties", []))}
    demanded = {prop["name"]: (index, prop) for index, prop in enumerate(required.effective.get("properties", []))}
    fields = []
    diagnostics = []
    failed = False
    unknown = False
    for name, (required_index, want) in demanded.items():
        available_index, have = supplied.get(name, (None, None))
        field = {"field": name, "requiredIndex": required_index, "availableIndex": available_index,
                 "status": "passed", "assumptions": []}
        fields.append(field)
        related = [location(display_path(required.path), f"{required.pointer}/properties/{required_index}")]
        if have is not None:
            related.append(location(display_path(available.path), f"{available.pointer}/properties/{available_index}"))
        kwargs = {"path": path, "pointer": pointer, "related": related}
        if have is None:
            diagnostics.append(diagnostic("DATA-FIELD-MISSING", f"The available dataset omits field {name!r}.", **kwargs))
            field["status"] = "failed"
            failed = True
            continue

        def fail(code, message):
            diagnostics.append(diagnostic(code, message, **kwargs))
            field["status"] = "failed"

        def indeterminate(message):
            diagnostics.append(diagnostic("DATA-MAPPING-UNKNOWN", message, severity="warning", **kwargs))
            if field["status"] != "failed":
                field["status"] = "unknown"

        have_type, want_type = have.get("logicalType"), want.get("logicalType")
        if have_type not in SCALARS or want_type not in SCALARS:
            indeterminate(f"Field {name!r} has a missing, nested or unsupported logical type.")
        elif have_type != want_type and (have_type, want_type) != ("integer", "number"):
            fail("DATA-FIELD-INCOMPATIBLE", f"Field {name!r} supplies {have_type} where {want_type} is required.")
        if want.get("required", False) and not have.get("required", False):
            fail("DATA-NULLABILITY", f"Field {name!r} permits nulls but the consumer requires a non-null value.")
        allowed, declared = enum_values(want), enum_values(have)
        if allowed is not None and (declared is None or any(not json_contains(allowed, value) for value in declared)):
            fail("DATA-ENUM-INCOMPATIBLE", f"Field {name!r} does not establish the consumer's allowed values.")
        if want.get("physicalType") or set(want.get("logicalTypeOptions") or {}) - UNSUPPORTED_OPTIONS:
            indeterminate(f"Field {name!r} requires physical or logical type options outside the core mapping.")
        for side, property_ in (("available", have), ("required", want)):
            for key in ("unique", "primaryKey"):
                if property_.get(key):
                    field["assumptions"].append({"side": side, "claim": key, "evidence": "declared"})
        failed |= field["status"] == "failed"
        unknown |= field["status"] == "unknown"

    for name, (index, _prop) in supplied.items():
        if name in demanded:
            continue
        fields.append({"field": name, "requiredIndex": None, "availableIndex": index,
                       "status": "passed" if allow_additional else "failed", "assumptions": []})
        if not allow_additional:
            failed = True
            diagnostics.append(diagnostic("DATA-FIELD-ADDITIONAL", f"The consumer forbids extra field {name!r}.",
                                          path=path, pointer=pointer, related=[
                                              location(display_path(available.path), f"{available.pointer}/properties/{index}")
                                          ]))
    return Compatibility("failed" if failed else "unknown" if unknown else "passed", tuple(diagnostics), tuple(fields))


def record_comparison(inventory, subject, available, required, allow_additional, path, pointer,
                      *, export=False):
    result = compare_datasets(available, required, allow_additional, path=path, pointer=pointer,
                              display_path=inventory.display_path)
    diagnostics = list(result.diagnostics)
    if export and result.status == "failed":
        diagnostics.append(diagnostic("DATA-EXPORT-MISMATCH", "The declared export does not satisfy its expected dataset.",
                                      path=path, pointer=pointer))
    reasons = {
        "not_run": "A producing or required dataset declaration did not resolve.",
        "unknown": "A required field relationship is outside the supported tabular mapping.",
    }
    if result.status == "unknown" or any(item["code"] == "DATA-MAPPING-UNKNOWN" for item in diagnostics):
        inventory.report.mapping_limits.add("Core comparison does not interpret all ODCS logical or physical types and options.")
    inventory.report.add("DDK-GRAPH-003" if export else "DDK-DATA-005", "core.datasets", subject, result.status,
                         reason=reasons.get(result.status), diagnostics=diagnostics)
    inventory.report.metadata.setdefault("datasetMappings", {})[subject] = {
        "available": available.alias if available else None,
        "required": required.alias if required else None,
        "allowAdditionalFields": allow_additional,
        "fields": list(result.fields),
    }

