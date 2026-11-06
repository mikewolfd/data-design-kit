"""Disclosure and complete local output-set replacement."""

import ctypes
from copy import deepcopy
import fcntl
from hashlib import file_digest, sha256
from importlib.metadata import version
import os
from pathlib import Path
from shutil import rmtree
import sys
from tempfile import mkdtemp

from .catalog_access import CatalogError
from .documents import FORMAT_CHECKER, json_dumps, read_json, validate_document
from .locks import build_lock
from .results import VERSION

MANIFEST = "urn:ddk:catalog:output-set"
POLICY_FIELDS = {"identifiers", "aliases", "locations", "evidence", "recipes", "nativeReferences", "descriptions"}


def read_disclosure(document):
    value = document.value
    if not isinstance(value, dict) or value.keys() - POLICY_FIELDS:
        raise CatalogError("CATALOG-DISCLOSURE", "The disclosure policy contains unknown settings.")
    policy = {}
    for field in POLICY_FIELDS - {"descriptions"}:
        entries = value.get(field, [])
        if not isinstance(entries, list) or any(not isinstance(item, str) or not item for item in entries):
            raise CatalogError("CATALOG-DISCLOSURE", f"The {field} setting needs a list of exact strings.")
        if field != "aliases" and any(not FORMAT_CHECKER.conforms(item, "uri") for item in entries):
            raise CatalogError("CATALOG-DISCLOSURE", f"The {field} setting needs absolute identifiers.")
        policy[field] = frozenset(entries)
    policy["descriptions"] = value.get("descriptions", False)
    if not isinstance(policy["descriptions"], bool):
        raise CatalogError("CATALOG-DISCLOSURE", "The descriptions setting must be true or false.")
    policy["record"] = {"uri": document.path.as_uri(), "sha256": document.sha256}
    return policy


def _hide_uri(record, allowed):
    if record["uri"] in allowed:
        return record
    return {**record, "uri": f"urn:ddk:sha256:{record['sha256']}" if "sha256" in record else "urn:ddk:withheld"}


def _alias(alias, allowed):
    if alias in allowed:
        return alias
    return "public-" + sha256(alias.encode()).hexdigest()


def public_view(catalog, policy, details_key):
    """Retain explicitly admitted identifiers, locations and SQL, and close visible references."""
    view = deepcopy(catalog)
    ids = policy["identifiers"]
    if not {catalog["id"], catalog["project"]["id"]} <= ids:
        raise CatalogError("CATALOG-DISCLOSURE", "The public catalog and project identifiers must be permitted.")
    view["audience"] = "public"
    view["disclosurePolicy"] = _hide_uri(policy["record"], policy["evidence"])
    view["extensions"] = {details_key: {"scope": "Only explicitly disclosed catalog records."}}
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
    for dataset in view["datasets"]:
        definition = dataset["definition"]
        if not {dataset["id"], definition["contractId"]} <= ids:
            continue
        alias = dataset["alias"]
        aliases[alias] = _alias(alias, policy["aliases"])
        dataset["alias"] = aliases[alias]
        if not policy["descriptions"]:
            for key in ("title", "rowMeaning"):
                dataset.pop(key, None)
            definition["object"] = _alias(definition["object"], policy["aliases"])
        definition["source"] = _hide_uri(definition["source"], policy["evidence"])
        datasets.append(dataset)
    view["datasets"] = datasets
    products = []
    for product in view["products"]:
        if product["id"] not in ids:
            continue
        product["alias"] = _alias(product["alias"], policy["aliases"])
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
    view["identities"] = [{**item, "dataset": aliases[item["dataset"]]} for item in view["identities"]
                          if policy["descriptions"] and item["dataset"] in aliases]
    relationships = {}
    for relationship in view["relationships"]:
        endpoints = [relationship["source"], relationship["target"]]
        if (not policy["descriptions"] or relationship["id"] not in ids
                or any((item["dataset"] not in aliases if "dataset" in item else item["external"] not in ids)
                       for item in endpoints)
                or ("rule" in relationship and relationship["rule"]["id"] not in ids)):
            continue
        for endpoint in endpoints:
            if "dataset" in endpoint:
                endpoint["dataset"] = aliases[endpoint["dataset"]]
        relationships[relationship["id"]] = relationship
    view["relationships"] = list(relationships.values())
    recipes, omitted = [], []
    for recipe in view["recipes"]:
        if (recipe["id"] not in policy["recipes"] or recipe["id"] not in ids
                or not set(recipe["inputs"].values()) <= aliases.keys()
                or not set(recipe["relationships"]) <= relationships.keys()
                or ("resultDataset" in recipe and recipe["resultDataset"] not in aliases)):
            omitted.append(recipe["id"])
            continue
        recipe["inputs"] = {name: aliases[alias] for name, alias in recipe["inputs"].items()}
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
        else:
            item["coverage"] = [record(fact) for fact in item.get("coverage", ())]
        versions.append(record(item))
    view["versions"] = versions
    version_ids = {item["id"] for item in versions}
    view["representations"] = [
        record(item) for item in view["representations"]
        if item["id"] in ids and item["version"] in version_ids
        and ("location" not in item or item["location"] in policy["locations"])
    ]
    releases = []
    for item in view["releases"]:
        if item["id"] not in ids or item["id"] not in policy["nativeReferences"]:
            continue
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


def _public_report(report, catalog):
    public = deepcopy(report)
    public["scope"] = {
        "projects": [catalog["project"]["id"]], "artifacts": sorted(item["alias"] for item in catalog["datasets"]),
        "followedReferences": [], "excludedConsumers": [],
    }
    public["id"] = "urn:ddk:report:" + sha256(catalog["id"].encode()).hexdigest()
    for index, check in enumerate(public["checks"]):
        check["id"] = f"catalog-check-{index + 1}"
        check["subject"] = catalog["id"]
        for item in check["diagnostics"]:
            item["location"] = {"path": "catalog.ddk.json", "pointer": ""}
            item.pop("related", None)
            if item["code"] != "CATALOG-RECIPE-WITHHELD":
                item["message"] = "Details withheld by the disclosure policy."
        if "reason" in check and all(item["code"] != "CATALOG-RECIPE-WITHHELD" for item in check["diagnostics"]):
            check["reason"] = "Details withheld by the disclosure policy."
        check.pop("evidenceRecords", None)
        if check["evidence"] == "executed":
            check["evidence"] = "declared"
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
    if "catalog.dcat" in exports:
        tools["rdflib"] = {"version": version("rdflib")}
    roles = {"metadata": "metadata", "policy": "disclosure-policy", "recipe": "recipe"}
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


def write_output_set(output, catalog, companions, report, exports, metadata_adapter, inventory):
    output = Path(output).absolute()
    if output.resolve() == inventory.path.parent:
        raise CatalogError("CATALOG-OUTPUT-UNOWNED", "The project directory cannot be the generated output set.")
    files = dict(companions)
    if catalog["audience"] == "public":
        report = _public_report(report, catalog)
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
