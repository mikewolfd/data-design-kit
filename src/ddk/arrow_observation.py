"""Compare observed Arrow to the one explicit declaration mapping.

The mapper owns representation meaning. This observer checks those type facts,
retains independent value obligations, and never reads rows or runs a rule.
"""
from copy import deepcopy
from dataclasses import dataclass
import re

from .arrow_mapping import DECLARATION_PROFILE, EXACT_PROFILE, MappingUnavailable, map_declaration, pyarrow_schema
from .documents import freeze_json, json_dumps

MANAGED_SCHEMA_V2 = "urn:ddk:metadata:arrow-odcs:2"
MANAGED_SCHEMA_V3 = "urn:ddk:metadata:arrow-odcs:3"
MANAGED_SCHEMA_PROFILES = {MANAGED_SCHEMA_V2: DECLARATION_PROFILE, MANAGED_SCHEMA_V3: EXACT_PROFILE}


@dataclass(frozen=True)
class SchemaInterpretation:
    status: str
    reasons: tuple
    fields: tuple
    obligations: tuple


def observe_declaration(schema, declaration, pa, *, profile=DECLARATION_PROFILE):
    """Interpret canonical v2 types once, without converting observed values."""
    findings, fields, obligations = [], [], []
    reason = "Authored values require their own exact evidence; Arrow metadata does not evaluate them."
    try:
        mapping = map_declaration(declaration, profile=profile)
    except MappingUnavailable as exc:
        return SchemaInterpretation("unknown", (str(exc),), (), ())

    def obligation(facet, path, detail=reason):
        obligations.append({"facet": facet, "paths": [deepcopy(path)], "reason": detail})

    for item in mapping.coverage:
        if item["meaning"] != "validation-needed":
            continue
        facet, path, value = item["facet"], item["path"], item.get("value")
        # The shared key owner separately reads root rowIdentity and preserves
        # primary, alternate, virtual and nested keys. Avoid generic duplicates.
        if facet in {"primaryKey", "primaryKeyPosition"} or item.get("constraint") == "ddk.rowIdentity":
            continue
        if facet == "unique":
            if value is True:
                obligation("key_unique", path)
        elif facet == "required":
            if value is True:
                obligation("required", path)
        elif facet == "quality":
            for index, _rule in enumerate(value):
                obligation(f"quality/{index}", path)
        else:
            obligation(facet, path)

    # Native-ID custom properties are not instructions to bind a physical ID.
    def authored_ids(node):
        for item in node.get("customProperties", []):
            if re.sub(r"[^a-z]", "", str(item.get("property", "")).lower()) in {"nativefieldid", "fieldid", "icebergfieldid"}:
                findings.append(("unknown", "An authored native field-ID mapping has no selected supported interpretation."))
        for child in node.get("properties", []):
            authored_ids(child)
        if isinstance(node.get("items"), dict):
            authored_ids(node["items"])

    authored_ids(mapping.dataset)
    unsupported = [item for item in mapping.coverage
                   if item["meaning"] == "physical-mapping" and item["status"] != "exact"]
    if unsupported:
        reasons = [message for _, message in findings] + [item["reason"] for item in unsupported]
        return SchemaInterpretation("unknown", tuple(dict.fromkeys(reasons)), (),
                                    tuple(freeze_json(row) for row in obligations))
    expected = pyarrow_schema(mapping.schema, pa)
    nonnull = set()

    def visit(wanted, observed, logical_path, native_path, position):
        fields.append(freeze_json({"logicalPath": logical_path, "nativePath": native_path, "position": position,
                                   "nativeType": str(observed.type), "nullable": observed.nullable}))
        if not observed.nullable:
            nonnull.add(json_dumps(logical_path))
        left, right = wanted.type, observed.type
        if pa.types.is_struct(left):
            if not pa.types.is_struct(right):
                findings.append(("failed", "A retained field has a different nested shape."))
            else:
                siblings(left, right, logical_path, native_path)
        elif pa.types.is_list(left):
            if not pa.types.is_list(right):
                findings.append(("failed", "A retained array has a different physical list type."))
            elif left.value_field.name != right.value_field.name:
                findings.append(("failed", "A retained list item differs from the explicit canonical field name."))
            else:
                visit(left.value_field, right.value_field, [*logical_path, {"each": True}],
                      [*native_path, {"each": True}], 0)
        elif left != right:
            findings.append(("failed", "A retained field differs from the declared exact Arrow type, width, unit or timezone."))

    def siblings(wanted, observed, logical_path, native_path):
        names = [field.name for field in observed]
        if names != [field.name for field in wanted] or len(set(names)) != len(names):
            findings.append(("failed", "Retained fields are extra, missing, reordered or ambiguous within an authored struct."))
            return
        for position, (left, right) in enumerate(zip(wanted, observed)):
            visit(left, right, [*logical_path, {"field": left.name}], [*native_path, {"field": right.name}], position)

    siblings(expected, schema, [], [])
    obligations = [row for row in obligations if not (row["facet"] == "required"
                    and json_dumps(row["paths"][0]) in nonnull)]
    status = "failed" if any(item[0] == "failed" for item in findings) else "unknown" if findings else "passed"
    return SchemaInterpretation(status, tuple(dict.fromkeys(message for _, message in findings)), tuple(fields),
                                tuple(freeze_json(row) for row in obligations))
