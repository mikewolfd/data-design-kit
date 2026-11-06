"""Bounded local ODCS definition resolution with source-level provenance."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .documents import DocumentError, ResourceLimit, json_pointer, parse_json, resolve_path, validate_document
from .results import location

# Local interpretation of the Data Contract CLI 34b12923 behavior. DDK owns
# path admission, strict JSON, exact values, resolution bounds and provenance.
REFERENCE_PRECEDENCE = ("semantics", "semantic", "definition", "businessDefinition")
LOCAL_SUFFIXES = {".json", ".yaml", ".yml"}
LOCAL_FIELDS = {"id", "name", "authoritativeDefinitions", "properties", "items"}


def select_named(values, wanted, code="REF-DATASET"):
    matches = [(index, value) for index, value in enumerate(values) if value.get("id") == wanted]
    if not matches:
        matches = [(index, value) for index, value in enumerate(values) if value.get("name") == wanted]
    if not matches:
        raise DocumentError(f"{code}-MISSING", f"No object matches {wanted!r}.")
    if len(matches) != 1:
        raise DocumentError(f"{code}-AMBIGUOUS", f"Multiple objects match {wanted!r}.")
    return matches[0]


def fragment_property(document, fragment):
    """Resolve the upstream named fragment to its original JSON Pointer."""
    parts = [unquote(part) for part in fragment.split("/") if part]
    if len(parts) < 4 or parts[0] != "schema":
        raise DocumentError("REF-DEFINITION-FRAGMENT", "The fragment must start with schema and end at a property.")
    index, node = select_named(document.get("schema", []), parts[1], "REF-DEFINITION-FRAGMENT")
    pointer = ("schema", index)
    offset = 2
    while offset < len(parts):
        kind = parts[offset]
        if kind == "items" and "items" in node:
            node = node["items"]
            pointer += ("items",)
            offset += 1
        elif kind == "properties" and offset + 1 < len(parts):
            index, node = select_named(node.get("properties", []), parts[offset + 1], "REF-DEFINITION-FRAGMENT")
            pointer += ("properties", index)
            offset += 2
        else:
            raise DocumentError("REF-DEFINITION-FRAGMENT", "The named property or array item does not exist.")
    return node, pointer


def duplicate_properties(properties, pointer):
    """Find ambiguous names and IDs within each interpreted property list."""
    diagnostics = []
    ids = set()
    names = set()
    for index, prop in enumerate(properties):
        for key, seen in (("name", names), ("id", ids)):
            name = prop.get(key)
            if name is not None and name in seen:
                diagnostics.append((key, name, (*pointer, index, key)))
            if name is not None:
                seen.add(name)
        diagnostics.extend(duplicate_properties(prop.get("properties", []), (*pointer, index, "properties")))
        items = prop.get("items")
        item_pointer = (*pointer, index, "items")
        while isinstance(items, dict):
            diagnostics.extend(duplicate_properties(items.get("properties", []), (*item_pointer, "properties")))
            items = items.get("items")
            item_pointer += ("items",)
    return diagnostics


def enum_values(prop):
    if prop.get("enum"):
        return [entry["value"] for entry in prop["enum"] if entry["value"] is not None]
    legacy = (prop.get("logicalTypeOptions") or {}).get("enum")
    if not isinstance(legacy, list) or not legacy:
        legacy = None
        for item in prop.get("customProperties", []):
            if item.get("property") != "enum":
                continue
            candidate = item.get("value")
            if isinstance(candidate, str):
                try:
                    candidate = parse_json(candidate.encode())
                except (DocumentError, ResourceLimit):
                    continue
            if isinstance(candidate, list) and candidate:
                legacy = candidate
                break
    if legacy is None:
        for quality in prop.get("quality", []):
            values = quality.get("arguments", {}).get("validValues")
            if quality.get("metric") == "invalidValues" and isinstance(values, list) and values:
                legacy = values
                break
    return None if legacy is None else [value for value in legacy if value is not None]


@dataclass(frozen=True)
class DefinitionSource:
    path: Path
    sha256: str
    pointer: str
    fragment: str = ""

    def record(self):
        return {"path": str(self.path), "sha256": self.sha256, "pointer": self.pointer,
                **({"fragment": self.fragment} if self.fragment else {})}


@dataclass(frozen=True)
class EffectiveProperty:
    value: dict
    provenance: dict
    references: tuple


class RemoteDefinition(DocumentError):
    pass


class DefinitionResolver:
    def __init__(self, read, permitted_roots, max_depth):
        self.read = read
        self.permitted_roots = permitted_roots
        self.max_depth = max_depth
        self.cache = {}

    def resolve(self, prop, document, parts, active=()):
        """Resolve one property. Relative sources retain their declaring file."""
        source = (document.path, json_pointer(parts))
        if source in active:
            raise DocumentError("REF-DEFINITION-CYCLE", "Shared definition references form a cycle.", source[1])
        if len(active) > self.max_depth:
            raise ResourceLimit(f"Shared definition reference depth exceeds {self.max_depth}.")
        if source in self.cache:
            return self.cache[source]

        effective = deepcopy(prop)
        provenance = {}
        references = []
        for key in prop:
            provenance[(key,)] = {"source": location(document.path, json_pointer((*parts, key)))}
        for key in prop.get("logicalTypeOptions") or {}:
            provenance[("logicalTypeOptions", key)] = {
                "source": location(document.path, json_pointer((*parts, "logicalTypeOptions", key)))
            }

        for index, member in enumerate(prop.get("properties", [])):
            resolved = self.resolve(member, document, (*parts, "properties", index), active)
            effective["properties"][index] = resolved.value
            references.extend(resolved.references)
            provenance.update({("properties", index, *key): value for key, value in resolved.provenance.items()})
        if "items" in prop and isinstance(prop["items"], dict):
            resolved = self.resolve(prop["items"], document, (*parts, "items"), active)
            effective["items"] = resolved.value
            references.extend(resolved.references)
            provenance.update({("items", *key): value for key, value in resolved.provenance.items()})

        links = prop.get("authoritativeDefinitions", [])
        reference = next((link["url"] for kind in REFERENCE_PRECEDENCE for link in links
                          if link.get("type") == kind and link.get("url")), None)
        if reference:
            target_doc, target_prop, target_parts, fragment = self._follow(document, reference, parts)
            resolved = self.resolve(target_prop, target_doc, target_parts, (*active, source))
            references.append(DefinitionSource(target_doc.path, target_doc.sha256, json_pointer(target_parts), fragment))
            references.extend(resolved.references)
            inline_enum = enum_values(prop) is not None
            for key, value in resolved.value.items():
                if key in LOCAL_FIELDS:
                    continue
                if key == "enum" and inline_enum and key not in prop:
                    for enum_key in ("logicalTypeOptions", "customProperties", "quality"):
                        if enum_key in prop and enum_values({enum_key: prop[enum_key]}) is not None:
                            provenance[(enum_key,)]["overrides"] = resolved.provenance[(key,)]["source"]
                            break
                    continue
                if key == "logicalTypeOptions" and value:
                    effective[key] = {**value, **(prop.get(key) or {})}
                    for option in value:
                        subkey = (key, option)
                        inherited = resolved.provenance[subkey]
                        if subkey not in provenance:
                            provenance[subkey] = inherited
                        else:
                            provenance[subkey]["overrides"] = inherited["source"]
                    provenance.setdefault((key,), resolved.provenance[(key,)])
                    continue
                if key not in prop:
                    effective[key] = value
                    provenance[(key,)] = resolved.provenance[(key,)]
                else:
                    provenance[(key,)]["overrides"] = resolved.provenance[(key,)]["source"]

        result = EffectiveProperty(effective, provenance, tuple(dict.fromkeys(references)))
        self.cache[source] = result
        return result

    def _follow(self, document, reference, parts):
        pointer = json_pointer((*parts, "authoritativeDefinitions"))
        try:
            url = urlsplit(reference)
        except ValueError as exc:
            raise DocumentError("REF-DEFINITION-FRAGMENT", "Invalid shared definition reference.", pointer) from exc
        if url.scheme in {"http", "https"} or (
            url.scheme and url.scheme != "file"
        ) or url.netloc or (not url.fragment and Path(url.path).suffix.lower() not in LOCAL_SUFFIXES):
            raise RemoteDefinition("REF-DEFINITION-REMOTE", "Remote shared definition resolution is unavailable offline.", pointer)
        if url.scheme or url.query:
            raise DocumentError("REF-PATH-SCHEME", "Shared definitions must use a local path without a file scheme or query.", pointer)
        if not url.path or ("#" in reference and not url.fragment):
            raise DocumentError("REF-DEFINITION-FRAGMENT", "A named fragment must include both its file and property.", pointer)
        target = resolve_path(document.path, unquote(url.path), self.permitted_roots)
        try:
            target_doc = self.read(target)
        except FileNotFoundError as exc:
            raise DocumentError("REF-DEFINITION-MISSING", "The local shared definition file does not exist.", pointer) from exc
        issues = validate_document(target_doc.value, "dataset" if url.fragment else "definition")
        if issues:
            raise DocumentError("REF-DEFINITION-INVALID", f"The referenced definition is invalid at {issues[0].pointer or '/'}.", pointer)
        if url.fragment:
            target_prop, target_parts = fragment_property(target_doc.value, url.fragment)
        else:
            target_prop, target_parts = target_doc.value, ()
        return target_doc, target_prop, target_parts, url.fragment
