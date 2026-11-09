"""Descriptive ODPS and ODCS facts carried by catalog products and datasets.

Values are copied from the admitted definitions without interpretation. The
only normalization is the one the standards define: a context string is
shorthand for ``{"instructions": ...}``. Public views keep vocabulary values
and withhold free text unless descriptions are granted.
"""

from copy import deepcopy

PURPOSE_FIELDS = ("purpose", "usage", "limitations")
PRODUCT_TEXT = ("name", "domain", "description", "context")
DATASET_TEXT = ("description", "tags", "context", "canonicalUrls", "contract")


def _context(value):
    if isinstance(value, str):
        return {"instructions": value}
    return deepcopy(value) if value else None


def _purpose(value):
    selected = {key: value[key] for key in PURPOSE_FIELDS if isinstance(value, dict) and value.get(key)}
    return selected or None


def _canonical_urls(value):
    return list(dict.fromkeys(item["url"] for item in value.get("authoritativeDefinitions", ())
                              if item.get("type") == "canonicalUrl" and item.get("url"))) or None


def _compact(record):
    return {key: value for key, value in record.items() if value not in (None, [], {})}


def product_facts(value):
    """Return the ODPS product's descriptive facts."""
    return _compact({
        "name": value.get("name"), "type": value.get("type"), "domain": value.get("domain"),
        "status": value.get("status"), "description": _purpose(value.get("description")),
        "context": _context(value.get("context")),
    })


def _sla_applies(element, selected):
    """True for this object, False for another, None when DDK cannot interpret it."""
    found = set()
    for part in (item.strip() for item in element.split(",")):
        if not part or "#" in part:
            return None
        if "/" in part:
            segments = part.lstrip("/").split("/")
            if len(segments) < 2 or segments[0] != "schema":
                return None
            found.add(segments[1] == selected.get("id"))
        else:
            found.add(part.split(".")[0] == selected.get("name"))
    return True if True in found else False


def dataset_facts(contract, selected):
    """Return (record fields, uninterpretable SLA indices) for one selected ODCS object."""
    default = contract.get("slaDefaultElement")
    sla, unknown = [], []
    for index, entry in enumerate(contract.get("slaProperties", ())):
        element = entry.get("element", default)
        applies = True if element is None else _sla_applies(element, selected)
        if applies:
            sla.append(deepcopy(entry))
        elif applies is None:
            unknown.append(index)
    record = _compact({
        "status": contract.get("status"), "description": selected.get("description"),
        "tags": deepcopy(selected.get("tags")), "context": _context(selected.get("context")),
        "canonicalUrls": _canonical_urls(selected),
        "contract": _compact({
            "description": _purpose(contract.get("description")), "context": _context(contract.get("context")),
            "slaProperties": sla, "tags": deepcopy(contract.get("tags")), "canonicalUrls": _canonical_urls(contract),
        }),
    })
    return record, unknown


def public_product(product, policy):
    if not policy["descriptions"]:
        for key in PRODUCT_TEXT:
            product.pop(key, None)


def public_dataset(dataset, policy):
    """Withhold free text without a descriptions grant and canonical URLs outside ``locations``."""
    if not policy["descriptions"]:
        for key in DATASET_TEXT:
            dataset.pop(key, None)
        return
    for holder in (dataset, dataset.get("contract", {})):
        urls = [url for url in holder.pop("canonicalUrls", ()) if url in policy["locations"]]
        if urls:
            holder["canonicalUrls"] = urls
    if dataset.get("contract") == {}:
        dataset.pop("contract")
