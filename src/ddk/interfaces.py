"""Component arguments and bounded JSON Schema containment."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from fractions import Fraction
from pathlib import Path
from re import search
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, _WrappedReferencingError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from .documents import DocumentError, ResourceLimit, json_pointer, resolve_path, schema_validator
from .results import diagnostic, location

ANNOTATIONS = {
    "$schema", "$id", "$comment", "$defs", "title", "description", "default", "examples",
    "deprecated", "readOnly", "writeOnly",
}
BOUNDED = ANNOTATIONS | {
    "type", "enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "minItems", "maxItems",
}
TYPES = {"integer", "fractional", "string", "array", "object", "boolean", "null"}
OBJECT_KEYS = ANNOTATIONS | {"type", "properties", "additionalProperties", "required"}
DRAFT = "https://json-schema.org/draft/2020-12/schema"

SCHEMA_MAPS = {"properties", "patternProperties", "$defs", "dependentSchemas"}
SCHEMA_ARRAYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
SCHEMA_VALUES = {
    "additionalProperties", "unevaluatedProperties", "propertyNames", "items", "contains",
    "unevaluatedItems", "not", "if", "then", "else", "contentSchema",
}


def json_equal(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(json_equal(x, y) for x, y in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    return left == right


def json_contains(values, value):
    return any(json_equal(value, member) for member in values)


def _types(schema):
    declared = schema.get("type")
    if declared is None:
        return TYPES
    types = {declared} if isinstance(declared, str) else set(declared)
    if "number" in types:
        types = (types - {"number"}) | {"integer", "fractional"}
    return types


def _finite(schema):
    if schema is False:
        return []
    if "const" in schema:
        return [schema["const"]]
    return schema.get("enum")


def _bounds(schema, atom):
    if atom == "string":
        return ((schema.get("minLength", 0), True), (schema.get("maxLength"), True))
    if atom == "array":
        return ((schema.get("minItems", 0), True), (schema.get("maxItems"), True))
    lower = [(schema[key], inclusive) for key, inclusive in (("minimum", True), ("exclusiveMinimum", False))
             if key in schema]
    upper = [(schema[key], inclusive) for key, inclusive in (("maximum", True), ("exclusiveMaximum", False))
             if key in schema]
    lo, lo_inc = max(lower, default=(None, True), key=lambda pair: (pair[0], not pair[1]))
    hi, hi_inc = min(upper, default=(None, True), key=lambda pair: (pair[0], pair[1]))
    if atom == "integer":
        if lo is not None:
            ceil = Decimal(str(lo)).to_integral_value(rounding=ROUND_CEILING)
            lo = Fraction(lo) + 1 if not lo_inc and lo == ceil else ceil
        if hi is not None:
            floor = Decimal(str(hi)).to_integral_value(rounding=ROUND_FLOOR)
            hi = Fraction(hi) - 1 if not hi_inc and hi == floor else floor
        lo_inc = hi_inc = True
    if atom == "fractional":
        lo_inc = lo_inc and lo is not None and not _integral(lo)
        hi_inc = hi_inc and hi is not None and not _integral(hi)
    return ((lo, lo_inc), (hi, hi_inc))


def _empty(bounds):
    (lo, lo_inc), (hi, hi_inc) = bounds
    return lo is not None and hi is not None and (lo > hi or (lo == hi and not (lo_inc and hi_inc)))


def _bounds_contained(source, target):
    for (available, available_closed), (required, required_closed), sign in zip(source, target, (1, -1)):
        if required is None:
            continue
        if available is None:
            return False
        if (available < required if sign == 1 else available > required):
            return False
        if available == required and available_closed and not required_closed:
            return False
    return True


def _integral(value):
    return value == value.to_integral_value() if isinstance(value, Decimal) else value % 1 == 0


def _atomic_value_type(value):
    if type(value) is bool:
        return "boolean"
    if isinstance(value, (int, Decimal, float)):
        return "integer" if _integral(value) else "fractional"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "null" if value is None else "object"


def _finite_atom_covered(atom, bounds, allowed):
    if atom == "null":
        return json_contains(allowed, None)
    if atom == "boolean":
        return json_contains(allowed, True) and json_contains(allowed, False)
    (lo, _), (hi, _) = bounds
    if atom == "integer" and lo is not None and hi is not None:
        values = set(value for value in allowed if _atomic_value_type(value) == "integer" and lo <= value <= hi)
        return len(values) == Fraction(hi) - Fraction(lo) + 1
    if atom == "fractional" and lo is not None and lo == hi:
        return json_contains(allowed, lo)
    if hi == 0 and atom in {"string", "array"}:
        return json_contains(allowed, "" if atom == "string" else [])
    return False


def schema_containment(source, target):
    """Return whether the source admits a subset of the target's JSON values."""
    if source is False or target is True or target == {}:
        return "passed"
    source = {} if source is True else source
    target = {"enum": []} if target is False else target
    if not isinstance(source, dict) or not isinstance(target, dict):
        return "unknown"
    if source.keys() - BOUNDED or target.keys() - BOUNDED:
        return "unknown"
    source_validator = schema_validator(source)
    target_validator = schema_validator(target)
    source_values = _finite(source)
    if source_values is not None:
        return "passed" if all(target_validator.is_valid(value) for value in source_values
                               if source_validator.is_valid(value)) else "failed"

    target_values = _finite(target)
    if target_values is not None:
        target_values = [value for value in target_values if target_validator.is_valid(value)]
    for atom in sorted(_types(source)):
        bounded = atom in {"integer", "fractional", "string", "array"}
        source_bounds = _bounds(source, atom) if bounded else None
        if bounded and _empty(source_bounds):
            continue
        if atom not in _types(target):
            return "failed"
        if bounded and not _bounds_contained(source_bounds, _bounds(target, atom)):
            return "failed"
        if target_values is not None and not _finite_atom_covered(atom, source_bounds, target_values):
            return "failed"
    return "passed"


def _walk_schemas(schema, path=()):
    if not isinstance(schema, dict):
        return
    yield schema, path
    for keyword in SCHEMA_MAPS:
        for name, child in schema.get(keyword, {}).items():
            yield from _walk_schemas(child, (*path, keyword, name))
    for keyword in SCHEMA_ARRAYS:
        for index, child in enumerate(schema.get(keyword, [])):
            yield from _walk_schemas(child, (*path, keyword, index))
    for keyword in SCHEMA_VALUES:
        if keyword in schema:
            yield from _walk_schemas(schema[keyword], (*path, keyword))


def _schema_references(inventory, artifact, schema):
    registry = Registry()
    loaded = set()
    lookups = []
    root_uri = artifact.path.as_uri()

    def follow(contents, document, uri, depth):
        nonlocal registry
        if uri in loaded:
            return
        if depth > inventory.limits["maxReferenceDepth"]:
            raise ResourceLimit("Parameter schema reference depth exceeds the configured limit.")
        loaded.add(uri)
        registry = registry.with_resource(uri, Resource(contents, DRAFT202012))
        if isinstance(contents, dict) and "$id" in contents:
            registry = registry.with_resource(urljoin(uri, contents["$id"]), Resource(contents, DRAFT202012))
        scopes = {(): urljoin(uri, contents.get("$id", "")) if isinstance(contents, dict) else uri}
        for node, parts in _walk_schemas(contents):
            if parts:
                parent = next(scopes[parts[:i]] for i in range(len(parts) - 1, -1, -1) if parts[:i] in scopes)
                scopes[parts] = urljoin(parent, node.get("$id", ""))
            for key in ("$ref", "$dynamicRef"):
                reference = node.get(key)
                if reference is None:
                    continue
                base = scopes[parts]
                target_uri = urljoin(base, reference)
                address, fragment = urldefrag(target_uri)
                lookups.append((base, reference))
                authored = urlsplit(reference)
                if not authored.path or address == root_uri:
                    continue
                if authored.scheme or authored.netloc or authored.query or not base.startswith("file:"):
                    continue
                absolute_path = Path(unquote(urlsplit(address).path))
                target = resolve_path(document.path, str(absolute_path), inventory.permitted_roots)
                dependency = inventory.read(target)
                Draft202012Validator.check_schema(dependency.value)
                inventory.add_file(dependency, "schema", selection=fragment, owner=artifact.alias)
                inventory.dependency(artifact.alias, f"schema:{inventory.display_path(target)}")
                if address not in loaded:
                    follow(dependency.value, dependency, address, depth + 1)

    follow(schema, artifact.document, root_uri, 0)
    registry = registry.crawl()
    for base, reference in lookups:
        registry.resolver(base).lookup(reference)
    base_uri = urljoin(root_uri, schema.get("$id", ""))
    return schema_validator(schema, resource_registry=registry, resolver=registry.resolver(base_uri))


def check_interface(inventory, artifact):
    schema = artifact.value["parameters"]
    kwargs = {"path": inventory.display_path(artifact.path), "pointer": "/parameters"}
    subject = artifact.alias
    if schema.get("$schema", DRAFT).rstrip("#") != DRAFT:
        inventory.report.add("DDK-CALL-004", "core.calls", subject, "failed", diagnostics=[
            diagnostic("CALL-SCHEMA-DIALECT", "Parameters must use JSON Schema Draft 2020-12.", **kwargs)
        ])
        return None
    absent = sorted(set(schema.get("required", [])) - schema["properties"].keys())
    if absent:
        inventory.report.add("DDK-CALL-004", "core.calls", subject, "failed", diagnostics=[
            diagnostic("CALL-SCHEMA-REQUIRED", f"Required parameter {name!r} has no property declaration.", **kwargs)
            for name in absent
        ])
        return None
    try:
        Draft202012Validator.check_schema(schema)
        validator = _schema_references(inventory, artifact, schema)
    except (Unresolvable, FileNotFoundError):
        reason = "A parameter schema reference is unavailable in the offline registry."
        inventory.report.add("DDK-CALL-004", "core.calls", subject, "unknown", reason=reason, diagnostics=[
            diagnostic("CALL-SCHEMA-REFERENCE-UNKNOWN", reason, severity="warning", **kwargs)
        ])
        return None
    except OSError:
        reason = "The referenced local parameter schema could not be read."
        detail = diagnostic("DOC-UNREADABLE", reason, **kwargs)
        inventory.report.error(detail)
        inventory.report.add("DDK-CALL-004", "core.calls", subject, "not_run", reason=reason, diagnostics=[detail])
        return None
    except (SchemaError, DocumentError, ValueError) as exc:
        code = exc.code if isinstance(exc, DocumentError) else "CALL-SCHEMA-INVALID"
        inventory.report.add("DDK-CALL-004", "core.calls", subject, "failed", diagnostics=[
            diagnostic(code, "The parameter schema or a local dependency is invalid.", **kwargs)
        ])
        return None
    inventory.report.add("DDK-CALL-004", "core.calls", subject, "passed")
    return validator


def check_arguments(inventory, design, step, call, component, validator, design_validator):
    report = inventory.report
    subject = f"{design.alias}/step/{step}"
    path = inventory.display_path(design.path)
    parts = ("steps", step, "arguments")
    if validator is None or design_validator is None:
        report.add("DDK-CALL-004", "core.calls", subject, "not_run",
                   reason="A required parameter schema is invalid or unresolved.")
        return
    schema = component.value["parameters"]
    arguments = call["arguments"]
    related = [location(inventory.display_path(component.path), "/parameters")]
    diagnostics = []
    for missing in sorted(set(schema.get("required", [])) - arguments.keys()):
        diagnostics.append(diagnostic("CALL-ARGUMENT-MISSING", f"Required argument {missing!r} is absent.",
                                      path=path, pointer=json_pointer(parts), related=related))
    # A top-level patternProperties may admit an argument without a properties entry.
    patterns = schema.get("patternProperties", {})
    unexpected = {name for name in arguments.keys() - schema["properties"].keys()
                  if not any(search(pattern, name) for pattern in patterns)}
    for extra in sorted(unexpected):
        diagnostics.append(diagnostic("CALL-ARGUMENT-UNKNOWN", f"Unexpected argument {extra!r}.",
                                      path=path, pointer=json_pointer((*parts, extra)), related=related))
    symbolic = any("parameter" in argument for argument in arguments.values())
    if not symbolic:
        try:
            errors = list(validator.iter_errors({name: item["literal"] for name, item in arguments.items()}))
        except _WrappedReferencingError:
            reason = "A parameter schema reference is unresolved."
            report.add("DDK-CALL-004", "core.calls", subject, "unknown", reason=reason)
            return
        for error in errors:
            if list(error.absolute_schema_path) in [["required"], ["additionalProperties"]] and diagnostics:
                continue
            code = "CALL-TYPE-MISMATCH" if error.validator == "type" else "CALL-ARGUMENT-INVALID"
            diagnostics.append(diagnostic(code, f"Literal arguments violate the {error.validator} constraint.",
                                          path=path, pointer=json_pointer((*parts, *error.absolute_path)),
                                          related=related))
        report.add("DDK-CALL-004", "core.calls", subject, "failed" if diagnostics else "passed",
                   diagnostics=diagnostics)
        return

    properties = design.value["parameters"]["properties"]
    failed = bool(diagnostics)
    for name, argument in sorted(arguments.items()):
        if name in unexpected:
            continue
        where = {"path": path, "pointer": json_pointer((*parts, name)), "related": related}
        target = schema["properties"].get(name, True)
        if "parameter" in argument:
            parameter = argument["parameter"]
            if parameter not in properties:
                status = "failed"
                item = diagnostic("CALL-PARAMETER-MISSING", f"Design parameter {parameter!r} is undeclared.", **where)
            else:
                status = schema_containment(properties[parameter], target)
                item = {
                    "failed": lambda: diagnostic("CALL-PARAMETER-INCOMPATIBLE", "The design parameter admits values rejected by the component.", **where),
                    "unknown": lambda: diagnostic("CALL-PARAMETER-CONTAINMENT-UNKNOWN", "The schema uses constraints outside supported symbolic containment.", severity="warning", **where),
                }.get(status, lambda: None)()
            reason = "The schema uses constraints outside supported symbolic containment." if status == "unknown" else None
        else:
            try:
                valid = validator.evolve(schema=target).is_valid(argument["literal"])
                status = "passed" if valid else "failed"
                item = None if valid else diagnostic("CALL-ARGUMENT-INVALID", "The literal violates its parameter constraint.", **where)
            except _WrappedReferencingError:
                status = "unknown"
                item = diagnostic("CALL-SCHEMA-REFERENCE-UNKNOWN", "The parameter schema reference is unresolved.", **where)
            reason = "A parameter schema reference is unresolved." if status == "unknown" else None
        report.add("DDK-CALL-005", "core.calls", f"{subject}/argument/{name}", status,
                   reason=reason, diagnostics=[item] if item else [])
        failed |= status == "failed"
    if failed:
        report.add("DDK-CALL-006", "core.calls", subject, "failed", diagnostics=diagnostics)
    elif schema.keys() - OBJECT_KEYS or design.value["parameters"].keys() - OBJECT_KEYS:
        reason = "A whole-object constraint may change symbolic argument validity."
        report.add("DDK-CALL-006", "core.calls", subject, "unknown", reason=reason, diagnostics=[
            diagnostic("CALL-CORRELATION-UNKNOWN", reason, path=path, pointer=json_pointer(parts), severity="warning",
                       related=related)
        ])
    else:
        report.add("DDK-CALL-006", "core.calls", subject, "passed")


def interface_compatibility(base, candidate):
    """Compare acceptance of an entire base argument object by the candidate."""
    if set(candidate.get("required", [])) - set(base.get("required", [])):
        return "failed"
    if json_equal(base, candidate):
        return "passed"
    if base.keys() - OBJECT_KEYS or candidate.keys() - OBJECT_KEYS:
        return "unknown"
    if set(base["properties"]) - set(candidate["properties"]):
        return "failed"
    statuses = {schema_containment(source, candidate["properties"][name]) for name, source in base["properties"].items()}
    if "failed" in statuses:
        return "failed"
    return "unknown" if "unknown" in statuses else "passed"
