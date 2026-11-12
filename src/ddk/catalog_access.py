"""Relationship semantics and checked access to catalog versions."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
from pathlib import Path

from .documents import (
    DEFAULT_LIMITS, DocumentError, ResourceLimit, read_json, resolve_path,
    schema_validator, validate_document,
)


class CatalogError(DocumentError):
    def __init__(self, code, message, pointer="", *, status="failed", related=(), step=None):
        super().__init__(code, message, pointer)
        self.status = status
        self.related = tuple(related)
        self.step = step


def field_at(schema, path):
    field = schema
    for segment in path:
        if "each" in segment:
            if field.get("logicalType") != "array" or "items" not in field:
                return None
            field = field["items"]
        else:
            matches = [item for item in field.get("properties", ()) if item["name"] == segment["field"]]
            if len(matches) != 1:
                return None
            field = matches[0]
    return field


def row_identity_paths(schema):
    """Read the one ordered ODCS row identity for catalog and data-check owners."""
    declared = [item for item in schema.get("customProperties", ())
                if item.get("vendor") == "ddk" and item.get("property") == "rowIdentity"]
    if not declared:
        return None
    names = declared[0]["value"]
    if (len(declared) != 1 or not isinstance(names, list) or not names
            or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names)):
        raise CatalogError("CATALOG-KEY-INCOMPLETE", "An ODCS row identity needs unique ordered field names.")
    paths = [[{"field": name}] for name in names]
    for name, path in zip(names, paths):
        if field_at(schema, path) is None:
            raise CatalogError("CATALOG-KEY-PATH", f"Declared identity field {name!r} is missing.")
    return paths


def row_identity_names(schema):
    """The object's ordered row identity: its DDK rowIdentity annotation, else its ODCS primaryKey properties."""
    paths = row_identity_paths(schema)
    if paths is not None:
        return [path[0]["field"] for path in paths]
    primary = [field for field in schema.get("properties", ()) if field.get("primaryKey") is True]
    if not primary:
        return None
    positions = [field.get("primaryKeyPosition", -1) for field in primary]
    if len(primary) > 1 and (any(position < 1 for position in positions) or len(set(positions)) != len(positions)):
        raise CatalogError("CATALOG-KEY-INCOMPLETE", "A composite ODCS key needs unambiguous positions.")
    return [field["name"] for field in sorted(primary, key=lambda field: field.get("primaryKeyPosition", -1))]


def field_type(field):
    """The initial equality profile recognizes only native bytes and supported logical scalars."""
    logical = field.get("logicalType")
    physical = field.get("physicalType", "").lower()
    if physical in {"binary", "bytes", "bytea", "blob", "varbinary", "fixed_size_binary"}:
        return "binary"
    if logical == "string" and field.get("logicalTypeOptions", {}).get("format") in {"byte", "binary"}:
        return None
    if logical == "date":
        calendars = [item["value"] for item in field.get("customProperties", ())
                     if item.get("vendor") == "ddk" and item.get("property") == "calendar"]
        if calendars and calendars != ["gregorian"]:
            return None
    if logical in {"integer", "string", "date"}:
        return logical
    return None


def compare_equal(source_key, target_key, types, nulls):
    """Compare one ordered key pair under the shared exact equality rule."""
    if not types or len(source_key) != len(target_key) or len(source_key) != len(types):
        raise CatalogError("CATALOG-KEY-INCOMPLETE", "Both keys must supply every ordered component.")
    validators = {"integer": int, "string": str, "binary": bytes, "date": date}
    if nulls not in {"skip", "reject", "match"} or any(kind not in validators for kind in types):
        return {"status": "unknown", "reason": "The equality profile does not support this type or null policy."}
    if any(value is None for value in (*source_key, *target_key)):
        if nulls == "reject":
            raise CatalogError("CATALOG-KEY-NULL", "A rejected null occurred in the comparison key.")
        if nulls == "skip":
            return {"status": "passed", "matched": False}
    for left, right, kind in zip(source_key, target_key, types):
        if any(value is not None and type(value) is not validators[kind] for value in (left, right)):
            raise CatalogError("CATALOG-KEY-TYPE", "A key value has a different type from its definition.")
    return {"status": "passed", "matched": tuple(source_key) == tuple(target_key)}


def relationship_keys(row, paths):
    """Return keys with list positions so components from separate occurrences remain distinguishable."""
    def occurrences(value, path, prefix=(), positions=()):
        if not path:
            yield value, positions
            return
        segment, *tail = path
        if "field" in segment:
            name = segment["field"]
            if not isinstance(value, dict) or name not in value:
                raise CatalogError("CATALOG-KEY-PATH", "A key path is missing from the row.", status="unknown")
            yield from occurrences(value[name], tail, (*prefix, ("field", name)), positions)
        elif isinstance(value, (list, tuple)):
            prefix = (*prefix, ("each",),)
            for index, member in enumerate(value):
                yield from occurrences(member, tail, prefix, (*positions, (prefix, index)))
        else:
            raise CatalogError("CATALOG-KEY-PATH", "A key path requires a list.", status="unknown")

    keys = [((), {})]
    for path in paths:
        next_keys = []
        for value, positions in occurrences(row, path):
            for components, context in keys:
                if all(context.get(prefix, index) == index for prefix, index in positions):
                    next_keys.append(((*components, value), {**context, **dict(positions)}))
        keys = next_keys
    return keys


def _record(records, identity, role):
    candidates = [item for item in records if item["id"] == identity]
    if len(candidates) != 1:
        raise CatalogError("CATALOG-BINDING-UNRESOLVED", f"Expected one {role} for {identity!r}.")
    return candidates[0]


def _peer_catalog_doc(peer):
    from .catalog_delivery import CatalogArtifacts

    if isinstance(peer, CatalogArtifacts):
        if not peer.externally_pinned:
            raise CatalogError("CATALOG-EXTERNAL-PIN", "Captured peer catalog access requires an external lock pin.")
        return peer.catalog
    if isinstance(peer, dict):
        return peer
    raise CatalogError("CATALOG-BINDING-UNRESOLVED", "Supply a CatalogArtifacts or catalog mapping for peer binding.",
                       status="unknown")


def _version_binding(catalog, aliases, *, release=None, selection=None, versions=None, peer_catalogs=None):
    local_aliases = {name: alias for name, alias in aliases.items() if isinstance(alias, str)}
    peer_aliases = {name: alias for name, alias in aliases.items() if isinstance(alias, dict)}
    if peer_aliases and versions is None:
        raise CatalogError("CATALOG-BINDING-UNRESOLVED",
                           "Cross-catalog bindings require explicit version mappings across catalogs.")
    if (release is not None) + (selection is not None) + (versions is not None) != 1:
        raise CatalogError("CATALOG-BINDING-UNRESOLVED", "Supply one exact release, selection, or version mapping.")
    versions_by_id = {item["id"]: item for item in catalog["versions"]}
    if len(versions_by_id) != len(catalog["versions"]):
        raise CatalogError("CATALOG-BINDING-UNRESOLVED", "Dataset version identifiers are ambiguous.")
    if any(set(item["members"]) - versions_by_id.keys() for item in catalog["releases"]):
        raise CatalogError("CATALOG-BINDING-UNRESOLVED", "A release includes an unresolved version.")
    chosen = None
    if selection is not None:
        if not isinstance(selection, dict) or set(selection) - {"authority", "purpose", "release", "record"}:
            raise CatalogError("CATALOG-BINDING-UNRESOLVED", "The selection needs its authority and purpose.")
        if not {"authority", "purpose"} <= selection.keys():
            raise CatalogError("CATALOG-BINDING-UNRESOLVED", "The selection needs its authority and purpose.")
        matches = [item for item in catalog["selections"] if all(item[key] == value for key, value in selection.items())]
        matches = [item for item in matches if set(local_aliases.values()) <= {
            versions_by_id[member]["dataset"]
            for member in _record(catalog["releases"], item["release"], "release")["members"]
        }]
        if len(matches) != 1:
            raise CatalogError("CATALOG-BINDING-UNRESOLVED", "Expected one selection that covers every required input.")
        chosen = matches[0]
        release = chosen["release"]
    release_record = _record(catalog["releases"], release, "release") if release is not None else None
    if versions is not None and (not isinstance(versions, dict) or set(versions) != set(aliases)):
        raise CatalogError("CATALOG-BINDING-UNRESOLVED", "Supply an exact version for every required input.")
    bound = {}
    for name, alias in local_aliases.items():
        if release_record is not None:
            candidates = [versions_by_id[key] for key in release_record["members"]
                          if versions_by_id[key]["dataset"] == alias]
            if len(candidates) != 1:
                raise CatalogError("CATALOG-BINDING-UNRESOLVED",
                                   f"Release {release!r} needs one version of {alias!r}.")
            version = candidates[0]
        else:
            version = _record(catalog["versions"], versions[name], "dataset version")
            if version["dataset"] != alias:
                raise CatalogError("CATALOG-VERSION-MISMATCH", f"Version {version['id']!r} does not bind {alias!r}.")
        bound[name] = version
    for name, target in peer_aliases.items():
        peer_alias, peer_ds = target["catalog"], target["dataset"]
        if not peer_catalogs or peer_alias not in peer_catalogs:
            raise CatalogError("CATALOG-BINDING-UNRESOLVED",
                               f"Peer catalog {peer_alias!r} is required to bind {name!r}.", status="unknown")
        peer_doc = _peer_catalog_doc(peer_catalogs[peer_alias])
        version = _record(peer_doc["versions"], versions[name], "peer dataset version")
        if version["dataset"] != peer_ds:
            raise CatalogError("CATALOG-VERSION-MISMATCH",
                               f"Version {version['id']!r} does not bind peer dataset {peer_ds!r}.")
        bound[name] = version
    result = {"inputs": bound}
    if release_record is not None:
        result["release"] = release_record
    if chosen is not None:
        result["selection"] = chosen
    return deepcopy(result)


def resolve_relationship(catalog, relationship_id, *, release=None, selection=None, versions=None, peer_catalogs=None):
    relationship = _record(catalog["relationships"], relationship_id, "relationship")
    if "external" in relationship["target"] or relationship["scope"] == "declared":
        raise CatalogError("CATALOG-BINDING-UNRESOLVED", "This relationship needs a project-specific scope resolver.",
                           status="unknown")
    if relationship["scope"] == "same_release" and release is None and selection is None:
        raise CatalogError("CATALOG-RELEASE-SCOPE", "Both endpoints must bind to one exact release.")
    aliases = {
        side: ({"catalog": relationship[side]["catalog"], "dataset": relationship[side]["dataset"]}
               if "catalog" in relationship[side] else relationship[side]["dataset"])
        for side in ("source", "target")
    }
    return _version_binding(catalog, aliases, release=release, selection=selection, versions=versions,
                            peer_catalogs=peer_catalogs)


def resolve_query(catalog, recipe_id, *, release=None, selection=None, versions=None, parameters=None,
                  peer_catalogs=None):
    recipe = _record(catalog["recipes"], recipe_id, "query recipe")
    parameters = {} if parameters is None else parameters
    errors = list(schema_validator(recipe["parameters"]).iter_errors(parameters))
    if errors:
        raise CatalogError("CATALOG-QUERY-PARAMETERS", errors[0].message)
    binding = _version_binding(catalog, recipe["inputs"], release=release, selection=selection, versions=versions,
                               peer_catalogs=peer_catalogs)
    for relationship_id in recipe["relationships"]:
        relationship = _record(catalog["relationships"], relationship_id, "relationship")
        if relationship["scope"] == "same_release" and "release" not in binding:
            raise CatalogError("CATALOG-RELEASE-SCOPE", "The recipe needs one exact release for its relationship.")
        if relationship["scope"] in {"external", "declared"}:
            raise CatalogError("CATALOG-BINDING-UNRESOLVED", "The recipe uses a relationship with unsupported scope.",
                               status="unknown")
    return {"recipe": recipe_id, "dialect": recipe["dialect"], "parameters": deepcopy(parameters),
            **({"parameterOrder": list(recipe["parameterOrder"])} if "parameterOrder" in recipe else {}), **binding}


def run_checked_query(catalog_path, recipe_id, reader, **binding_args):
    """Use a path or one externally pinned CatalogArtifacts capture for the read."""
    from .catalog_delivery import CatalogArtifacts

    captured = catalog_path if isinstance(catalog_path, CatalogArtifacts) else None
    if captured is not None:
        if not captured.externally_pinned:
            raise CatalogError("CATALOG-EXTERNAL-PIN", "Captured data access requires an externally pinned catalog.")
        catalog = captured.catalog
    else:
        document = read_json(catalog_path)
        issues = validate_document(document.value, "catalog")
        if issues:
            raise CatalogError(issues[0].code, issues[0].message, issues[0].pointer)
        catalog = document.value
    binding = resolve_query(catalog, recipe_id, **binding_args)
    recipe = _record(catalog["recipes"], recipe_id, "query recipe")
    candidates = [item for item in catalog["files"] if item["path"] == recipe["sql"] and item["role"] == "recipe"]
    if len(candidates) != 1:
        raise CatalogError("CATALOG-RECIPE-INTEGRITY", "The SQL has no unique companion inventory entry.")
    if any("reference" not in item for item in binding["inputs"].values()):
        raise CatalogError("CATALOG-VERSION-WITHHELD", "The exact native reference is unavailable in this catalog view.",
                           status="unknown")
    if captured is not None:
        sql = captured.companions.get(recipe["sql"])
        if not isinstance(sql, bytes):
            raise CatalogError("CATALOG-RECIPE-INTEGRITY", "The selected capture omits its exact SQL companion bytes.")
    else:
        sql_path = resolve_path(document.path, recipe["sql"], (document.path.parent,))
        with sql_path.open("rb") as stream:
            sql = stream.read(DEFAULT_LIMITS["maxDocumentBytes"] + 1)
    if len(sql) > DEFAULT_LIMITS["maxDocumentBytes"]:
        raise ResourceLimit("The recipe exceeds the default document byte limit.")
    if sha256(sql).hexdigest() != candidates[0]["sha256"]:
        raise CatalogError("CATALOG-RECIPE-INTEGRITY", "The SQL bytes differ from their catalog digest.")
    request = deepcopy(binding)
    request["sql"] = sql
    result = reader(request)
    if not isinstance(result, dict) or not result.get("receipt") or "result" not in result:
        raise CatalogError("CATALOG-READ-RECEIPT", "The reader must return a result and its native read receipt.",
                           status="unknown")
    return {**result, "binding": binding, "sqlSha256": candidates[0]["sha256"]}
