"""Disclosure and complete local output-set replacement."""

import ctypes
from collections import defaultdict
from copy import deepcopy
import fcntl
from hashlib import file_digest, sha256
from importlib.metadata import version
import os
from pathlib import Path
import re
from shutil import rmtree
import sys
from tempfile import mkdtemp

from .catalog_access import CatalogError, field_at
from .catalog_descriptions import origin_gap, public_dataset, public_product
from .documents import json_dumps, read_json, schema_registry, schema_validator, validate_document
from .locks import build_lock
from .results import VERSION

MANIFEST = "urn:ddk:catalog:output-set"
POLICY_LISTS = {"identifiers", "aliases", "locations", "evidence", "recipes", "nativeReferences"}
FIELD_SHAPE = {"name", "logicalType", "required"}
FIELD_DESCRIPTIONS = {"businessName", "description", "dataGranularityDescription"}
TYPE_DETAIL_GRANTS = {"definitionPhysicalTypes": "physicalType", "definitionLogicalTypeOptions": "logicalTypeOptions"}
NAME_SEPARATORS = re.compile(r"[/:#\s]+")


def read_disclosure(document):
    value = document.value
    registry, schemas, _ = schema_registry()
    validator = schema_validator({"$ref": f"{schemas['catalog']['$id']}#/$defs/disclosurePolicy"}, resource_registry=registry)
    if error := next(validator.iter_errors(value), None):
        raise CatalogError("CATALOG-DISCLOSURE", error.message)
    policy = {field: frozenset(value.get(field, [])) for field in POLICY_LISTS}
    policy["descriptions"] = value.get("descriptions", False)
    policy["definitionFields"] = deepcopy(value.get("definitionFields", {}))
    for grant in TYPE_DETAIL_GRANTS:
        policy[grant] = deepcopy(value.get(grant, {}))
    extensions = value.get("projectExtensions", [])
    seen = set()
    for entry in extensions:
        key = json_dumps(entry["project"])
        if key in seen:
            raise CatalogError("CATALOG-DISCLOSURE", "A source project has more than one extension disclosure grant.")
        seen.add(key)
    policy["projectExtensions"] = deepcopy(extensions)
    policy["record"] = {"uri": document.path.as_uri(), "sha256": document.sha256}
    return policy


def _definition_view(definition, paths, descriptions):
    """Keep explicit leaves and the minimum structure needed to locate them."""
    result = {key: deepcopy(value) for key, value in definition.items() if key in FIELD_SHAPE}
    # A composite physical spelling can embed unlisted child names. Scalar
    # physical types remain exact; recursive logical structure describes parents.
    composite = definition.get("logicalType") in {"object", "array"} or bool({"properties", "items"} & definition.keys())
    if "physicalType" in definition and not composite:
        result["physicalType"] = definition["physicalType"]
    if descriptions and [] in paths:
        result.update({key: deepcopy(value) for key, value in definition.items() if key in FIELD_DESCRIPTIONS})
    properties = []
    for field in definition.get("properties", ()):
        descendants = [path[1:] for path in paths if path and path[0].get("field") == field["name"]]
        if descendants:
            properties.append(_definition_view(field, descendants, descriptions))
    if properties:
        result["properties"] = properties
    elements = [path[1:] for path in paths if path and path[0].get("each") is True]
    if elements:
        result["items"] = _definition_view(definition["items"], elements, descriptions)
    return result


def _subtree_disclosed(definition, view):
    """Check modeled children only; opaque native text has its own explicit grant."""
    return view is not None and all(
        _subtree_disclosed(field, field_at(view, [{"field": field["name"]}]))
        for field in definition.get("properties", ())
    ) and ("items" not in definition or _subtree_disclosed(definition["items"], field_at(view, [{"each": True}])))


def _hide_uri(record, allowed):
    if record["uri"] in allowed:
        return record
    return {**record, "uri": f"urn:ddk:sha256:{record['sha256']}" if "sha256" in record else "urn:ddk:withheld"}


def _alias(alias, allowed):
    if alias in allowed:
        return alias
    return "public-" + sha256(alias.encode()).hexdigest()


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, member in value.items():
            yield key
            yield from _strings(member)
    elif isinstance(value, list):
        for member in value:
            yield from _strings(member)


def _withheld_names(catalog, policy, details):
    """Every alias, namespace segment, object or port name and record ID the public view withholds."""
    names, identifiers = set(), set()
    scope = details.get("scope", {})
    for alias in (*scope.get("artifacts", ()), *details.get("importAliases", {})):
        names.add(alias)
        names.update(alias.split("/"))
    for entry in scope.get("projects", ()):
        namespace, _, identity = entry.rpartition("=")
        names.update(filter(None, (namespace, *namespace.split("/"))))
        identifiers.add(identity)
    for row in catalog["datasets"]:
        names.add(row["definition"]["object"])
        names.add(details.get("datasetDefinitions", {}).get(row["alias"], {}).get("name", ""))
        identifiers.update((row["id"], row["definition"]["contractId"]))
    for row in catalog["products"]:
        identifiers.add(row["id"])
        names.update(port["port"] for port in row["ports"])
    for section in ("relationships", "recipes", "versions", "sources", "representations", "releases", "runs"):
        identifiers.update(row["id"] for row in catalog[section])
    names.discard("")
    return (names - set(policy["aliases"])) | (identifiers - policy["identifiers"])


def _withheld_name(value, withheld, policy):
    """The first withheld name in a value, matching whole strings and their path-like parts."""
    granted = set(policy["aliases"]) | policy["identifiers"]
    for text in _strings(value):
        if text in granted:
            continue
        for name in (text, *NAME_SEPARATORS.split(text)):
            if name in withheld:
                return name
    return None


def _public_concepts(concepts, aliases, disclosed_paths, policy, catalog_id, peer_alias_maps=None, peer_summaries=None):
    """Concepts keep only fields whose exact path is granted, and every other value needs its own grant.

    A concept IRI the policy does not list among its identifiers, including one DDK minted from a private
    definition alias, is minted again from the public alias.
    """
    from .catalog_graph import child_iri

    peer_alias_maps = peer_alias_maps or {}
    peer_summaries = peer_summaries or {}
    view = []
    for row in concepts:
        fields = [{"dataset": aliases[field["dataset"]], "path": deepcopy(field["path"])} for field in row["fields"]
                  if "catalog" not in field and field["dataset"] in aliases
                  and field["path"] in disclosed_paths.get(aliases[field["dataset"]], ())]
        if not fields:
            continue
        for field in row["fields"]:
            if "catalog" not in field:
                continue
            peer_alias = field["catalog"]
            mapping = peer_alias_maps.get(peer_alias, {})
            if field["dataset"] not in mapping:
                continue
            pub_ds = mapping[field["dataset"]]
            peer_summary = peer_summaries.get(peer_alias, {})
            if ("disclosedDefinitionPaths" in peer_summary
                    and field["path"] not in peer_summary["disclosedDefinitionPaths"].get(pub_ds, ())):
                continue
            fields.append({"catalog": peer_alias, "dataset": pub_ds, "path": deepcopy(field["path"])})
        definition = _alias(row["definition"], policy["aliases"])
        concept = row["concept"] if row["concept"] in policy["identifiers"] else child_iri(catalog_id, "concept", definition)
        item = {"concept": concept, "definition": definition, "fields": fields}
        if "conceptKind" in row:
            item["conceptKind"] = row["conceptKind"]
        if "iriTemplate" in row and row["iriTemplate"] in (policy["identifiers"] | policy["locations"]):
            item["iriTemplate"] = row["iriTemplate"]
        for key in ("exactMatch", "closeMatch"):
            if matches := [iri for iri in row.get(key, ()) if iri in policy["identifiers"]]:
                item[key] = matches
        if policy["descriptions"] and "description" in row:
            item["description"] = row["description"]
        urls = [url for url in row.get("canonicalUrls", ()) if url in policy["locations"]]
        if urls:
            item["canonicalUrls"] = urls
        view.append(item)
    return view


def public_view(catalog, policy, details_key):
    """Retain explicitly admitted identifiers, locations and SQL, and close visible references."""
    view = deepcopy(catalog)
    ids = policy["identifiers"]
    if not {catalog["id"], catalog["project"]["id"]} <= ids:
        raise CatalogError("CATALOG-DISCLOSURE", "The public catalog and project identifiers must be permitted.")
    profile = catalog.get("extensions", {}).get(details_key, {}).get("relationshipProfile")
    if profile is not None and profile["identity"]["id"] not in ids:
        raise CatalogError("CATALOG-DISCLOSURE", "The selected relationship profile identifier must be permitted for a public view.")
    native_profile = catalog.get("extensions", {}).get(details_key, {}).get("nativeRuleProfile")
    if native_profile is not None and native_profile["identity"]["id"] not in ids:
        raise CatalogError("CATALOG-DISCLOSURE", "The selected native rule generator identifier must be permitted for a public view.")
    view["audience"] = "public"
    view["disclosurePolicy"] = _hide_uri(policy["record"], policy["evidence"])
    view["extensions"] = {details_key: {"scope": {
        "disclosure": "Only explicitly disclosed catalog records.", "consumerCoverage": "unknown",
    }}}
    if profile is not None:
        disclosed_profile = {"identity": deepcopy(profile["identity"]), "scope": profile["scope"]}
        if "source" in profile:
            disclosed_profile["source"] = _hide_uri(deepcopy(profile["source"]), policy["evidence"])
        view["extensions"][details_key].update({
            "relationshipProfile": disclosed_profile,
            "relationshipAssessmentScope": {
                "status": "unknown", "reason": "Individual assessments and their consumer coverage are withheld by disclosure.",
            },
        })
    if native_profile is not None:
        disclosed_native = {"identity": deepcopy(native_profile["identity"])}
        if "source" in native_profile:
            disclosed_native["source"] = _hide_uri(deepcopy(native_profile["source"]), policy["evidence"])
        view["extensions"][details_key]["nativeRuleProfile"] = disclosed_native
    view["sourceInventory"] = list({
        json_dumps(redacted): redacted for item in view["sourceInventory"]
        if (redacted := _hide_uri(item, policy["evidence"]))
    }.values())

    def record(row):
        if "record" in row:
            row["record"] = _hide_uri(row["record"], policy["evidence"])
        return row

    aliases = {}
    datasets = []
    unknown_origins = []
    for dataset in view["datasets"]:
        definition = dataset["definition"]
        if not {dataset["id"], definition["contractId"]} <= ids:
            continue
        alias = dataset["alias"]
        aliases[alias] = _alias(alias, policy["aliases"])
        if dataset.get("origin") == "model" and origin_gap(dataset) is not None:
            unknown_origins.append(aliases[alias])
        dataset["alias"] = aliases[alias]
        public_dataset(dataset, policy)
        if not policy["descriptions"]:
            for key in ("title", "rowMeaning"):
                dataset.pop(key, None)
        else:
            object_name = catalog.get("extensions", {}).get(details_key, {}).get("datasetDefinitions", {}).get(alias, {}).get("name")
            if dataset.get("title") == object_name and object_name not in policy["aliases"]:
                dataset.pop("title", None)
        definition["object"] = _alias(definition["object"], policy["aliases"])
        definition["source"] = _hide_uri(definition["source"], policy["evidence"])
        datasets.append(dataset)
    view["datasets"] = datasets
    details = view["extensions"][details_key]
    authored_details = catalog.get("extensions", {}).get(details_key, {})
    dataset_ids = {row["id"]: row["alias"] for row in catalog["datasets"]}
    disclosed_definitions = {}
    disclosed_paths = {}
    for identifier, paths in policy["definitionFields"].items():
        alias = dataset_ids.get(identifier)
        definition = authored_details.get("datasetDefinitions", {}).get(alias)
        if alias not in aliases or definition is None:
            raise CatalogError("CATALOG-DISCLOSURE", "An allowed definition must name a disclosed dataset in this catalog.")
        if any(field_at(definition, path) is None for path in paths):
            raise CatalogError("CATALOG-DISCLOSURE", "An allowed definition field path does not resolve.")
        if paths:
            disclosed_definitions[aliases[alias]] = _definition_view(definition, paths, policy["descriptions"])
            disclosed_definitions[aliases[alias]].pop("physicalType", None)
            disclosed_definitions[aliases[alias]]["name"] = next(
                row["definition"]["object"] for row in datasets if row["id"] == identifier)
            disclosed_paths[aliases[alias]] = deepcopy(paths)
    for grant, attribute in TYPE_DETAIL_GRANTS.items():
        for identifier, paths in policy[grant].items():
            alias = dataset_ids.get(identifier)
            definition = authored_details.get("datasetDefinitions", {}).get(alias)
            disclosed = disclosed_definitions.get(aliases.get(alias))
            if definition is None or disclosed is None:
                raise CatalogError("CATALOG-DISCLOSURE", f"A {attribute} grant must name a disclosed dataset definition.")
            for path in paths:
                field, visible = field_at(definition, path), field_at(disclosed, path)
                value = field.get(attribute) if field is not None else None
                valid = (isinstance(value, str) and bool(value.strip()) if attribute == "physicalType"
                         else isinstance(value, dict))
                if not valid or not _subtree_disclosed(field, visible):
                    raise CatalogError("CATALOG-DISCLOSURE", f"A {attribute} grant needs an existing value and complete modeled-subtree disclosure.")
                visible[attribute] = deepcopy(value)
    if disclosed_definitions:
        details["datasetDefinitions"] = disclosed_definitions
        details["disclosedDefinitionPaths"] = disclosed_paths
    if unknown_origins:
        details["unknownOrigins"] = sorted(unknown_origins)
    authored_peers = authored_details.get("peerCatalogs", {})
    public_imports = {}
    peer_alias_maps = {}
    public_peer_summaries = {}
    for peer_alias, decl in sorted((view.get("imports") or {}).items()):
        if decl["audience"] == "local":
            if decl["id"] not in ids:
                continue
            peer_info = authored_peers.get(peer_alias, {})
            if "pairedPublic" not in peer_info:
                raise CatalogError("CATALOG-DISCLOSURE-PEER-AUDIENCE",
                                   f"Public catalog cannot import local peer catalog {peer_alias!r} without a paired public view.")
            paired = peer_info["pairedPublic"]
            public_imports[peer_alias] = {"id": decl["id"], "audience": "public", "lockSha256": paired["lockSha256"]}
            peer_alias_maps[peer_alias] = {row["localAlias"]: row["publicAlias"] for row in paired["datasets"]}
            public_peer_summaries[peer_alias] = deepcopy(paired["peerSummary"])
        elif decl["id"] in ids:
            public_imports[peer_alias] = deepcopy(decl)
            if peer_alias in authored_peers:
                peer_info = authored_peers[peer_alias]
                peer_alias_maps[peer_alias] = {ds_alias: ds_alias for ds_alias in peer_info.get("datasets", {})}
                public_peer_summaries[peer_alias] = deepcopy({k: v for k, v in peer_info.items() if k != "pairedPublic"})
    if public_imports:
        view["imports"] = public_imports
    else:
        view.pop("imports", None)
    if public_peer_summaries:
        details["peerCatalogs"] = public_peer_summaries
    view["concepts"] = _public_concepts(catalog.get("concepts", ()), aliases, disclosed_paths, policy, catalog["id"],
                                        peer_alias_maps=peer_alias_maps, peer_summaries=public_peer_summaries)
    extension_grants = {json_dumps(row["project"]): set(row["extensions"]) for row in policy["projectExtensions"]}
    known_extensions = defaultdict(set)
    disclosed_extensions = []
    withheld = _withheld_names(catalog, policy, authored_details) if extension_grants else set()
    for row in authored_details.get("projectExtensions", ()):
        key = json_dumps(row["project"])
        known_extensions[key].update(row["extensions"])
        permitted = extension_grants.get(key, set())
        if permitted:
            if row["project"]["id"] not in ids:
                raise CatalogError("CATALOG-DISCLOSURE", "A disclosed extension's source project identifier must be permitted.")
            values = {key: deepcopy(value) for key, value in row["extensions"].items() if key in permitted}
            # An extension value is opaque: refuse rather than edit it when it names a withheld identity.
            if (name := _withheld_name(values, withheld, policy)) is not None:
                raise CatalogError("CATALOG-DISCLOSURE", f"A granted project extension names withheld {name!r}; "
                                   "grant that alias or identifier, or remove it from the extension.")
            disclosed_extensions.append({
                "project": deepcopy(row["project"]),
                "namespace": _alias(row["namespace"], policy["aliases"]) if row["namespace"] else "",
                "extensions": values,
            })
    if any(key not in known_extensions or names - known_extensions[key] for key, names in extension_grants.items()):
        raise CatalogError("CATALOG-DISCLOSURE", "An extension disclosure grant names an unknown project or namespace.")
    if disclosed_extensions:
        details["projectExtensions"] = disclosed_extensions
    products = []
    for product in view["products"]:
        if product["id"] not in ids:
            continue
        product["alias"] = _alias(product["alias"], policy["aliases"])
        public_product(product, policy)
        product["definition"] = _hide_uri(product["definition"], policy["evidence"])
        product["ports"] = [item for item in product["ports"] if item["dataset"] in aliases]
        for port in product["ports"]:
            port["dataset"] = aliases[port["dataset"]]
            port["product"] = product["alias"]
            port["port"] = _alias(port["port"], policy["aliases"])
        if any(port["direction"] == "output" for port in product["ports"]):
            products.append(product)
    view["products"] = products
    if not products:
        raise CatalogError("CATALOG-DISCLOSURE", "The policy needs to permit a product and a participating output dataset.")
    restricted_aliases = {aliases[dataset_ids[identifier]] for identifier in policy["definitionFields"]}

    def _paths_disclosed(public_alias, paths):
        if public_alias not in restricted_aliases:
            return True
        allowed = disclosed_paths.get(public_alias, ())
        return all(path in allowed for path in paths)

    identities = []
    for item in view["identities"]:
        if item["dataset"] not in aliases:
            continue
        public_alias = aliases[item["dataset"]]
        non_virtual = [field["path"] for field in item["fields"] if not field["virtual"]]
        has_virtual = any(field["virtual"] for field in item["fields"])
        if policy["descriptions"]:
            if public_alias in restricted_aliases and (has_virtual or not _paths_disclosed(public_alias, non_virtual)):
                continue
            identities.append({**item, "dataset": public_alias})
        elif item["kind"] == "key" and not has_virtual and all(
            path in disclosed_paths.get(public_alias, ()) for path in non_virtual
        ):
            identities.append({**item, "dataset": public_alias, "meaning": "Disclosed key identity."})
    view["identities"] = identities
    relationships = {}
    for relationship in view["relationships"]:
        source, target = relationship["source"], relationship["target"]
        if (not policy["descriptions"] or relationship["id"] not in ids
                or source["dataset"] not in aliases
                or ("rule" in relationship and relationship["rule"]["id"] not in ids)):
            continue
        source["dataset"] = aliases[source["dataset"]]
        if not _paths_disclosed(source["dataset"], source["paths"]):
            continue
        if "catalog" in target:
            peer_alias = target["catalog"]
            mapping = peer_alias_maps.get(peer_alias, {})
            if target["dataset"] not in mapping:
                continue
            target["dataset"] = mapping[target["dataset"]]
            peer_summary = public_peer_summaries.get(peer_alias, {})
            if ("disclosedDefinitionPaths" in peer_summary
                    and not all(path in peer_summary["disclosedDefinitionPaths"].get(target["dataset"], ())
                                for path in target["paths"])):
                continue
        elif "dataset" in target:
            if target["dataset"] not in aliases:
                continue
            target["dataset"] = aliases[target["dataset"]]
            if not _paths_disclosed(target["dataset"], target["paths"]):
                continue
        elif target["external"] not in ids:
            continue
        if "joinMetrics" in relationship:
            relationship["joinMetrics"] = record(relationship["joinMetrics"])
        relationships[relationship["id"]] = relationship
    view["relationships"] = list(relationships.values())
    recipes, omitted = [], []

    def _recipe_input_disclosed(value):
        if isinstance(value, str):
            return value in aliases
        return value["catalog"] in peer_alias_maps and value["dataset"] in peer_alias_maps[value["catalog"]]

    def _rewrite_recipe_input(value):
        if isinstance(value, str):
            return aliases[value]
        return {"catalog": value["catalog"], "dataset": peer_alias_maps[value["catalog"]][value["dataset"]]}

    for recipe in view["recipes"]:
        if (recipe["id"] not in policy["recipes"] or recipe["id"] not in ids
                or not all(_recipe_input_disclosed(val) for val in recipe["inputs"].values())
                or not set(recipe["relationships"]) <= relationships.keys()
                or ("resultDataset" in recipe and recipe["resultDataset"] not in aliases)):
            omitted.append(recipe["id"])
            continue
        recipe["inputs"] = {name: _rewrite_recipe_input(val) for name, val in recipe["inputs"].items()}
        if "contextualRelationships" in recipe:
            recipe["contextualRelationships"] = [identifier for identifier in recipe["contextualRelationships"]
                                                 if identifier in relationships]
        if not policy["descriptions"]:
            for key in ("title", "notes"):
                recipe.pop(key, None)
        if "resultDataset" in recipe:
            recipe["resultDataset"] = aliases[recipe["resultDataset"]]
        recipes.append(recipe)
    view["recipes"] = recipes
    view["sources"] = [record(item) for item in view["sources"]
                       if item["id"] in ids and item["id"] in policy["nativeReferences"]]
    source_ids = {item["id"] for item in view["sources"]}
    versions = []
    for item in view["versions"]:
        if item["id"] not in ids or item["dataset"] not in aliases:
            continue
        item["dataset"] = aliases[item["dataset"]]
        item["sources"] = [key for key in item["sources"] if key in source_ids]
        if item["id"] not in policy["nativeReferences"]:
            item.pop("reference")
            item["referenceDisclosure"] = "withheld"
        if not policy["descriptions"]:
            item["scope"] = "Disclosed version record."
            item.pop("coverage", None)
            item.pop("dates", None)
        else:
            item["coverage"] = [record(fact) for fact in item.get("coverage", ())]
        versions.append(record(item))
    view["versions"] = versions
    version_ids = {item["id"] for item in versions}
    representations = []
    for item in view["representations"]:
        if item["id"] not in ids or item["version"] not in version_ids:
            continue
        if "location" in item and item["location"] not in policy["locations"]:
            continue
        if "location" not in item:
            item.pop("members", None)
        representations.append(record(item))
    view["representations"] = representations
    releases = []
    for item in view["releases"]:
        if item["id"] not in ids:
            continue
        if item["id"] not in policy["nativeReferences"]:
            item.pop("reference")
            item["referenceDisclosure"] = "withheld"
        if set(item["members"]) - version_ids:
            item["membership"] = "partial" if item["membership"] == "complete" else item["membership"]
            item["members"] = [member for member in item["members"] if member in version_ids]
        releases.append(record(item))
    view["releases"] = releases
    release_ids = {item["id"] for item in releases}
    view["selections"] = [record(item) for item in view["selections"]
                          if item["authority"] in ids and item["release"] in release_ids]
    if "currentSelection" in view and view["currentSelection"]["authority"] not in ids:
        raise CatalogError("CATALOG-DISCLOSURE", "The requested publisher authority is private.")
    view["checks"] = [record(item) for item in view["checks"]
                      if policy["descriptions"] and item["subject"] in version_ids
                      and item["rule"]["id"] in ids and item["evaluator"]["id"] in policy["aliases"]]
    view["runs"] = []
    view["productions"] = []
    return view, omitted


def _data(value):
    return (json_dumps(value) + "\n").encode("utf-8")


def public_report(report, catalog=None):
    """Keep check outcomes while withholding local diagnostics and input scope."""
    public = deepcopy(report)
    catalog_id = catalog["id"] if catalog is not None else "urn:ddk:catalog:withheld"
    public["scope"] = {
        "projects": [catalog["project"]["id"]] if catalog is not None else ["urn:ddk:project:withheld"],
        "artifacts": sorted(item["alias"] for item in catalog["datasets"]) if catalog is not None else [],
        "followedReferences": [], "excludedConsumers": [],
    }
    public["id"] = "urn:ddk:report:" + sha256(catalog_id.encode()).hexdigest()

    def withhold(item):
        item["location"] = {"path": "catalog.ddk.json", "pointer": ""}
        item.pop("related", None)
        if item["code"] != "CATALOG-RECIPE-WITHHELD":
            item["message"] = "Details withheld by the disclosure policy."

    for index, check in enumerate(public["checks"]):
        check["id"] = f"catalog-check-{index + 1}"
        check["subject"] = catalog_id
        for item in check["diagnostics"]:
            withhold(item)
        if "reason" in check and all(item["code"] != "CATALOG-RECIPE-WITHHELD" for item in check["diagnostics"]):
            check["reason"] = "Details withheld by the disclosure policy."
        check.pop("evidenceRecords", None)
        if check["evidence"] == "executed":
            check["evidence"] = "declared"
    for item in public["operationalErrors"]:
        withhold(item)
    if public["coverage"]["mappingLimits"]:
        public["coverage"]["mappingLimits"] = ["Mapping and evidence limits are retained in the local report."]
    public["lock"] = {"verified": public["lock"].get("verified", False)}
    public.pop("metadata", None)
    return public


def _rename_exchange(left, right):
    library = ctypes.CDLL(None, use_errno=True)
    first, second = map(os.fsencode, (left, right))
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        rename = library.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        result = rename(first, second, 0x00000002)  # RENAME_SWAP
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        result = rename(-100, first, -100, second, 2)  # AT_FDCWD, RENAME_EXCHANGE
    else:
        raise OSError("This filesystem cannot atomically exchange output directories.")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(right))


def _confirm_previous(path):
    if path.is_symlink() or not path.is_dir():
        raise CatalogError("CATALOG-OUTPUT-UNOWNED", "The output path is not a generated catalog directory.")
    try:
        document = read_json(path / "catalog.lock.json")
        lock = document.value
        inventory = lock["extensions"][MANIFEST]
        expected = {item["path"]: item["sha256"] for item in inventory}
        if validate_document(lock, "lock") or "catalog.ddk.json" not in expected:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CatalogError("CATALOG-OUTPUT-UNOWNED", "The output directory lacks an intact generated manifest.") from exc
    expected_dirs = {parent for name in expected for parent in Path(name).parents if parent != Path(".")}
    actual = set()
    for item in path.rglob("*"):
        relative = item.relative_to(path)
        name = relative.as_posix()
        if item.is_symlink() or (item.is_dir() and relative not in expected_dirs):
            raise CatalogError("CATALOG-OUTPUT-UNOWNED", "The previous output contains unmanaged paths.")
        if not item.is_dir() and name != "catalog.lock.json":
            if not item.is_file() or name not in expected:
                raise CatalogError("CATALOG-OUTPUT-UNOWNED", "The previous output contains unmanaged files.")
            with item.open("rb") as stream:
                if file_digest(stream, "sha256").hexdigest() != expected[name]:
                    raise CatalogError("CATALOG-OUTPUT-UNOWNED", "The previous output was changed after generation.")
            actual.add(name)
    if set(expected) != actual:
        raise CatalogError("CATALOG-OUTPUT-UNOWNED", "The previous output set is incomplete.")


def _inventory(files):
    return [{"path": path, "sha256": sha256(data).hexdigest(), "role": role}
            for path, (role, data) in sorted(files.items())]


def _lock(inventory, catalog, exports, metadata_adapter, generated):
    options = {"audience": catalog["audience"], "exports": exports}
    if metadata_adapter:
        options["metadataAdapter"] = metadata_adapter
    if "currentSelection" in catalog:
        options["currentSelection"] = catalog["currentSelection"]
    tools = {item["id"]: {key: value for key, value in item.items() if key != "id"}
             for item in catalog["adapters"]}
    if {"catalog.dcat", "catalog.graph"} & set(exports):
        tools["rdflib"] = {"version": version("rdflib")}
    roles = {"metadata": "metadata", "policy": "disclosure-policy", "recipe": "recipe", "implementation": "implementation"}
    extra = [{"path": item["uri"], "role": roles[item["role"]], "sha256": item["sha256"]}
             for item in catalog["sourceInventory"] if item["role"] in roles]
    lock = build_lock(inventory, tools=tools, extra_files=extra, catalog_options=options)
    if catalog["audience"] == "public":
        lock["files"] = [{"path": item["uri"], "role": roles.get(item["role"], item["role"]),
                          "sha256": item["sha256"]} for item in catalog["sourceInventory"]]
    lock["extensions"] = {MANIFEST: generated}
    issues = validate_document(lock, "lock")
    if issues:
        raise CatalogError("CATALOG-LOCK-SCHEMA", issues[0].message, issues[0].pointer)
    return lock


def prepare_output_set(catalog, companions, report, exports, metadata_adapter, inventory):
    """Prepare the standard control files from admitted in-memory inputs."""
    files = dict(companions)
    if catalog["audience"] == "public":
        report = public_report(report, catalog)
    issues = validate_document(report, "report")
    if issues:
        raise CatalogError("CATALOG-REPORT-SCHEMA", issues[0].message, issues[0].pointer)
    files["catalog.report.json"] = ("report", _data(report))
    catalog["files"] = _inventory(files)
    issues = validate_document(catalog, "catalog")
    if issues:
        raise CatalogError("CATALOG-OUTPUT-SCHEMA", issues[0].message, issues[0].pointer)
    files["catalog.ddk.json"] = ("catalog", _data(catalog))
    files["catalog.lock.json"] = ("lock", _data(_lock(inventory, catalog, exports, metadata_adapter, _inventory(files))))
    return files


def write_output_set(output, catalog, companions, report, exports, metadata_adapter, inventory, *, prepared=None):
    output = Path(output).absolute()
    if output.resolve() == inventory.path.parent:
        raise CatalogError("CATALOG-OUTPUT-UNOWNED", "The project directory cannot be the generated output set.")
    files = (prepare_output_set(catalog, companions, report, exports, metadata_adapter, inventory)
             if prepared is None else prepared)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix=".ddk-catalog-", dir=output.parent))
    try:
        for name, (_, data) in sorted(files.items()):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or name != relative.as_posix():
                raise CatalogError("CATALOG-OUTPUT-PATH", "A companion path must stay within the output set.")
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        descriptor = os.open(output.parent, os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if os.path.lexists(output):
                _confirm_previous(output)
                _rename_exchange(staging, output)
            else:
                os.rename(staging, output)
        finally:
            os.close(descriptor)
    finally:
        if staging.exists():
            rmtree(staging)
    return _inventory(files)
