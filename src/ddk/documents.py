"""Strict JSON and the pinned, local-only schema registry."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from jsonschema import Draft201909Validator, Draft202012Validator, FormatChecker, validators
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT201909, DRAFT202012

_PACKAGE = Path(__file__).resolve().parent
REPOSITORY = _PACKAGE / "resources" if (_PACKAGE / "resources").is_dir() else _PACKAGE.parents[1]
SCHEMA_ROOT = REPOSITORY / "schemas" / "0.1"
ODCS_SCHEMA = "vendor/odcs/3.2.0/odcs-json-schema.json"
ODPS_SCHEMA = "vendor/odps/1.1.0/odps-json-schema-v1.1.0.json"
OPENLINEAGE_SCHEMA = "vendor/openlineage/1.55.0/OpenLineage.json"
OPENLINEAGE_VERSION_FACET = "vendor/openlineage/1.55.0/DatasetVersionDatasetFacet.json"
PINNED_SCHEMA_DIGESTS = {
    ODCS_SCHEMA: "015669375144f70d5b961dcfa0fdaad4a7f6c07e4cead34bd57402e5d466762d",
    ODPS_SCHEMA: "b7eae1af15b3c6b18e5dffaa2119212acb38ec73286933c76d16c8712e0d90d1",
    OPENLINEAGE_SCHEMA: "69f68bee00b9beac88a87059c0102410e7bb05f3f43c46d02a0409831eceb0d2",
    OPENLINEAGE_VERSION_FACET: "91f57b67bc6d639bb6d600e26b827dac551e3520a233d1785d65870da263dc34",
}

DEFAULT_LIMITS = {
    "maxDocumentBytes": 8 * 1024 * 1024,
    "maxProjectBytes": 64 * 1024 * 1024,
    "maxReferenceDepth": 32,
    "maxNesting": 64,
    "maxArtifacts": 10_000,
    "maxGraphEdges": 100_000,
    "maxDiagnostics": 10_000,
    "maxAdapterSeconds": 120,
}
FORMAT_CHECKER = FormatChecker()
URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s\x00-\x1f]*$")


def json_pointer(parts):
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def pointer_get(value, pointer):
    if pointer == "":
        return value
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("Expected an RFC 6901 JSON Pointer")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(part)
    return value


class DocumentError(ValueError):
    def __init__(self, code, message, pointer=""):
        super().__init__(message)
        self.code = code
        self.pointer = pointer


class ResourceLimit(Exception):
    pass


class RegistryError(RuntimeError):
    pass


class _Pairs(list):
    pass


class _FrozenDict(dict):
    def _immutable(self, *_args, **_kwargs):
        raise TypeError("An admitted document is immutable.")

    __setitem__ = __delitem__ = __ior__ = clear = pop = popitem = setdefault = update = _immutable

    def __deepcopy__(self, memo):
        from copy import deepcopy

        return {key: deepcopy(value, memo) for key, value in self.items()}


class _FrozenList(list):
    def _immutable(self, *_args, **_kwargs):
        raise TypeError("An admitted document is immutable.")

    __setitem__ = __delitem__ = __iadd__ = __imul__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable

    def __deepcopy__(self, memo):
        from copy import deepcopy

        return [deepcopy(value, memo) for value in self]


def freeze_json(value):
    if isinstance(value, dict):
        return _FrozenDict((key, freeze_json(member)) for key, member in value.items())
    if isinstance(value, list):
        return _FrozenList(freeze_json(member) for member in value)
    return value


def parse_json(data: bytes, *, max_nesting=DEFAULT_LIMITS["maxNesting"], preserve_integral_decimals=False):
    def reject_nonfinite(_value):
        raise DocumentError("DOC-NONFINITE-NUMBER", "JSON numbers must be finite.")

    def unpack(value, parts=()):
        if len(parts) > max_nesting:
            raise ResourceLimit(f"Parsed JSON nesting exceeds {max_nesting}.")
        if isinstance(value, _Pairs):
            output = {}
            for key, member in value:
                key_parts = (*parts, key)
                check_unicode(key, key_parts)
                if key in output:
                    raise DocumentError("DOC-DUPLICATE-KEY", "Duplicate JSON object member.", json_pointer(key_parts))
                output[key] = unpack(member, key_parts)
            return output
        if isinstance(value, list):
            return [unpack(member, (*parts, i)) for i, member in enumerate(value)]
        if isinstance(value, str):
            check_unicode(value, parts)
        return value

    def check_unicode(value, parts):
        if re.search(r"[\ud800-\udfff]", value):
            raise DocumentError("DOC-UNICODE-SURROGATE", "JSON strings must contain valid Unicode characters.", json_pointer(parts))

    def decimal(token):
        result = Decimal(token)
        if abs(result.as_tuple().exponent) > 10_000 or len(result.as_tuple().digits) > 10_000:
            raise ResourceLimit("JSON number exceeded the supported exact arithmetic capacity.")
        if result == result.to_integral_value():
            if result.adjusted() >= 4000:
                raise ResourceLimit("JSON integer exceeded the supported exact arithmetic capacity.")
            # Draft validators also examine nested meta-schemas with their
            # built-in integer checker. Preserve mathematical integers there.
            if not preserve_integral_decimals:
                return int(result)
        return result

    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentError("DOC-UTF8", f"Invalid UTF-8 at byte {exc.start}.") from exc
    try:
        return unpack(json.loads(source, object_pairs_hook=_Pairs, parse_float=decimal, parse_constant=reject_nonfinite))
    except json.JSONDecodeError as exc:
        raise DocumentError("DOC-JSON", f"{exc.msg} at line {exc.lineno}, column {exc.colno}.") from exc
    except (RecursionError, InvalidOperation) as exc:
        raise ResourceLimit("JSON nesting or numeric magnitude exceeded parser capacity.") from exc
    except ValueError as exc:
        if isinstance(exc, DocumentError):
            raise
        raise ResourceLimit("JSON integer exceeded parser capacity.") from exc


def json_dumps(value, *, sort_keys=True):
    """Serialize JSON without turning exact decimals into strings or floats."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite JSON number")
        return str(value)
    if isinstance(value, dict):
        keys = sorted(value) if sort_keys else value
        return "{" + ", ".join(json.dumps(key) + ": " + json_dumps(value[key], sort_keys=sort_keys) for key in keys) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(json_dumps(item, sort_keys=sort_keys) for item in value) + "]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True)
class Document:
    path: Path
    value: object
    sha256: str
    data: bytes


def read_json(path, *, max_bytes=DEFAULT_LIMITS["maxDocumentBytes"], max_nesting=DEFAULT_LIMITS["maxNesting"]):
    path = Path(path).resolve()
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("A JSON document must be a regular file.")
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ResourceLimit(f"Document exceeds {max_bytes} bytes.")
    return Document(path, freeze_json(parse_json(data, max_nesting=max_nesting)), sha256(data).hexdigest(), data)


def resolve_path(document_path, reference, permitted_roots):
    try:
        parts = urlsplit(reference)
    except ValueError as exc:
        raise DocumentError("REF-PATH-SCHEME", "Invalid local file path.") from exc
    if parts.scheme or parts.netloc or "\x00" in reference:
        raise DocumentError("REF-PATH-SCHEME", "Only local filesystem paths are allowed.")
    try:
        resolved = (Path(document_path).parent / reference).resolve()
    except (RuntimeError, ValueError) as exc:
        raise DocumentError("REF-PATH-INVALID", "The local path cannot be resolved.") from exc
    if not any(resolved.is_relative_to(Path(root).resolve()) for root in permitted_roots):
        raise DocumentError("REF-PATH-OUTSIDE-ROOT", "The path resolves outside the permitted project roots.")
    return resolved


def _is_integer(_checker, value):
    return type(value) is int or (
        isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value()
    ) or (type(value) is float and value.is_integer())


def _multiple_of(validator, divisor, value, _schema):
    from jsonschema import ValidationError

    if validator.is_type(value, "number") and Fraction(value) % Fraction(divisor):
        yield ValidationError("Number is not an exact multiple of the schema divisor.")


def _extend(validator):
    return validators.extend(
        validator,
        {"multipleOf": _multiple_of},
        type_checker=validator.TYPE_CHECKER.redefine("integer", _is_integer),
    )


Exact202012 = _extend(Draft202012Validator)
Exact201909 = _extend(Draft201909Validator)


@FORMAT_CHECKER.checks("uri")
def _uri(value):
    if not isinstance(value, str):
        return True
    if not URI.fullmatch(value) or re.search(r"%(?![a-fA-F0-9]{2})", value):
        return False
    try:
        return value.isascii() and bool(urlsplit(value).scheme) and not re.search(r'["<>\\^\x60{|}]', value)
    except ValueError:
        return False


@lru_cache(maxsize=1)
def schema_registry():
    paths = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    paths += [REPOSITORY / path for path in (ODCS_SCHEMA, ODPS_SCHEMA, OPENLINEAGE_SCHEMA, OPENLINEAGE_VERSION_FACET)]
    schemas = {}
    entries = {}
    registry = Registry()
    for path in paths:
        try:
            document = read_json(path, max_nesting=128)
        except (OSError, DocumentError, ResourceLimit) as exc:
            raise RegistryError(f"Pinned schema {path.name} could not be loaded.") from exc
        relative = path.relative_to(REPOSITORY).as_posix()
        if relative in PINNED_SCHEMA_DIGESTS and PINNED_SCHEMA_DIGESTS[relative] != document.sha256:
            raise RegistryError(f"Pinned schema {path.name} differs from its recorded SHA-256.")
        value = document.value
        key = path.name.removesuffix(".schema.json")
        if path == REPOSITORY / ODCS_SCHEMA:
            key = "dataset"
        elif path == REPOSITORY / ODPS_SCHEMA:
            key = "product"
        elif path == REPOSITORY / OPENLINEAGE_SCHEMA:
            key = "openlineage"
        elif path == REPOSITORY / OPENLINEAGE_VERSION_FACET:
            key = "openlineage-version-facet"
        dialect = DRAFT201909 if "2019-09" in value.get("$schema", "") else DRAFT202012
        uri = value.get("$id", path.as_uri())
        registry = registry.with_resource(uri, Resource(value, dialect))
        schemas[key] = value
        entries[relative] = document.sha256
    return registry.crawl(), schemas, entries


@dataclass(frozen=True)
class SchemaIssue:
    code: str
    message: str
    pointer: str


def schema_validator(schema, *, resource_registry=None, resolver=None):
    dialect = Exact201909 if isinstance(schema, dict) and "2019-09" in schema.get("$schema", "") else Exact202012
    kwargs = {"_resolver": resolver} if resolver is not None else {}
    return dialect(schema, registry=resource_registry if resource_registry is not None else schema_registry()[0],
                   format_checker=FORMAT_CHECKER, **kwargs)


def validate_document(value, kind=None):
    registry, schemas, _ = schema_registry()
    if kind is None and isinstance(value, dict):
        kind = {"DataContract": "dataset", "DataProduct": "product"}.get(value.get("kind"), value.get("kind"))
    if kind == "definition":
        odcs = schemas["dataset"]
        schema = {"$schema": odcs["$schema"], "$defs": odcs["$defs"], "type": "object",
                  "$ref": "#/$defs/SchemaBaseProperty", "unevaluatedProperties": False}
    else:
        schema = schemas.get(kind)
    if schema is None or kind == "common":
        return [SchemaIssue("DOC-KIND-UNSUPPORTED", "Unknown or missing document kind.", "/kind")]
    if isinstance(value, dict):
        expected = {"dataset": "v3.2.0", "product": "v1.1.0"}.get(kind)
        if expected and value.get("apiVersion") != expected:
            return [SchemaIssue("DOC-VERSION-UNSUPPORTED", f"This profile requires apiVersion {expected}.", "/apiVersion")]
        if kind not in {"definition", "dataset", "product", "openlineage", "openlineage-version-facet"}:
            if "specVersion" in value and value["specVersion"] != "0.1":
                return [SchemaIssue("DOC-VERSION-UNSUPPORTED", "Expected DDK specVersion 0.1.", "/specVersion")]
    return sorted(
        (SchemaIssue(
            "DOC-UNKNOWN-PROPERTY" if error.validator == "additionalProperties" else "DOC-SCHEMA",
            error.message,
            json_pointer(error.absolute_path),
        ) for error in schema_validator(schema, resource_registry=registry).iter_errors(value)),
        key=lambda issue: (issue.pointer, issue.code, issue.message),
    )
