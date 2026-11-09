"""ODPS port resolution shared by catalog assembly and layer-order policies."""

from collections import defaultdict

from .catalog_access import CatalogError
from .documents import FORMAT_CHECKER


def product_ports(inventory):
    """Resolve each participating ODPS port to one registered ODCS object.

    Returns ``[(product, [(direction, port, version, dataset), ...]), ...]`` in
    artifact order. An explicit ``catalog.ports`` binding selects among objects
    of one contract; otherwise exactly one registered object must match the
    port's contract ID and version.
    """
    index = defaultdict(list)
    for artifact in inventory.artifacts.values():
        if artifact.kind == "dataset":
            index[(artifact.identity, artifact.version)].append(artifact)
    selections = {}
    for namespace, document in inventory.projects.items():
        for entry in document.value.get("catalog", {}).get("ports", ()):
            product = inventory.resolve(entry["product"], namespace, "product")
            dataset = inventory.resolve(entry["dataset"], namespace, "dataset")
            key = (product.alias, entry["direction"], entry["port"], entry["version"])
            if key in selections:
                raise CatalogError("CATALOG-PORT-AMBIGUOUS", "A product port has multiple explicit bindings.")
            selections[key] = dataset
    resolved = []
    for artifact in inventory.artifacts.values():
        if artifact.kind != "product":
            continue
        value = artifact.value
        if not value.get("version") or not FORMAT_CHECKER.conforms(artifact.identity, "uri"):
            raise CatalogError("CATALOG-PRODUCT-IDENTITY", "A catalog product needs an absolute ID and explicit version.")
        ports, seen = [], set()
        for direction in ("input", "output"):
            for port in value.get(f"{direction}Ports", ()):
                if not port.get("contractId") and not port.get("version"):
                    continue
                if not port.get("contractId") or not port.get("version"):
                    raise CatalogError("CATALOG-PORT-VERSION", "A participating port needs a contract ID and version.")
                key = (artifact.alias, direction, port["name"], port["version"])
                if key in seen:
                    raise CatalogError("CATALOG-PORT-AMBIGUOUS", "A product declares the same port twice.")
                seen.add(key)
                exact = (port["contractId"], port["version"])
                explicit = selections.pop(key, None)
                if explicit is not None and (explicit.identity, explicit.version) != exact:
                    raise CatalogError("CATALOG-PORT-VERSION", "The selected object has a different contract ID or version.")
                if explicit is None:
                    possible = index[exact]
                    if len(possible) > 1:
                        raise CatalogError("CATALOG-PORT-AMBIGUOUS", "Select one registered ODCS object for the port.")
                    if not possible:
                        raise CatalogError("CATALOG-PORT-VERSION", "No registered ODCS object matches the exact port version.")
                    explicit = possible[0]
                ports.append((direction, port["name"], port["version"], explicit))
        if not any(direction == "output" for direction, *_ in ports):
            raise CatalogError("CATALOG-PORT-MISSING", "The product needs at least one participating output port.")
        resolved.append((artifact, ports))
    if selections:
        raise CatalogError("CATALOG-PORT-VERSION", "An explicit binding has no corresponding versioned product port.")
    return resolved
