"""Descriptive ODPS and ODCS facts carried by catalog products and datasets.

Values are copied from the admitted definitions without interpretation. The
only normalization is the one the standards define: a context string is
shorthand for ``{"instructions": ...}``. Public views keep vocabulary values
and withhold free text unless descriptions are granted; even then, SLA and
context entries keep plain values without element names, links, identifiers
or custom properties.
"""

from copy import deepcopy

from .definitions import enum_values
from .policies import ddk_annotations

PURPOSE_FIELDS = ("purpose", "usage", "limitations")
PRODUCT_TEXT = ("name", "domain", "description", "context")
DATASET_TEXT = ("description", "tags", "context", "contract")
# Public SLA and context entries keep plain values only; identifiers, custom
# properties and links follow the ordinary withholding rules.
PUBLIC_SLA = {"property", "value", "valueExt", "unit", "driver", "description"}
PUBLIC_CONTEXT_ITEM = {"question", "answer", "constraint", "tags"}
# Who asserts a dataset's content (DDK-CATALOG-003). Older projects may still declare `derived`.
ORIGINS = ("publisher", "third_party", "rule", "human", "model")
MODEL_FIELDS = ("id", "version", "configurationSha256", "review")


def origin_gap(dataset, *, audience="local", unknown_origins=()):
    """(code, reason) when a dataset's declared origin leaves its evidence unknown, else None."""
    if dataset.get("origin") == "derived":
        return "CATALOG-ORIGIN-DETAIL", ("Origin `derived` does not say whether a rule or a person derived the "
                                         "content; declare `rule` or `human`.")
    if dataset.get("origin") == "model":
        if audience == "public":
            if dataset.get("alias") in unknown_origins:
                return "CATALOG-ORIGIN-METHOD", "The model method record is incomplete; details are withheld by the disclosure policy."
            return None
        missing = [key for key in MODEL_FIELDS if key not in dataset.get("model", {})]
        if missing:
            return "CATALOG-ORIGIN-METHOD", (f"The model method record lacks {', '.join(missing)}, so the origin "
                                             "evidence is unknown.")
    return None


def method_origins(prop):
    """The origin of each value a method column declares, and a failure reason when invalid (else None).

    A method column must declare a non-empty `enum`. Each value is an origin, or a finer method that one
    `vendor: ddk` custom property `methodOrigins` maps to an origin, such as {"exact_identifier": "rule"}.
    """
    declared = list(dict.fromkeys(map(str, enum_values(prop) or ())))
    if not declared:
        return {}, "declares no `enum` values"
    annotations = ddk_annotations(prop, "methodOrigins")
    if len(annotations) > 1 or (annotations and not isinstance(annotations[0], dict)):
        return {}, "has a malformed `methodOrigins` custom property; expected one object"
    finer = annotations[0] if annotations else {}
    bad_targets = sorted(
        f"{key!r}: {target!r}" for key, target in finer.items()
        if not isinstance(key, str) or target not in ORIGINS or (key in ORIGINS and target != key)
    )
    if bad_targets:
        return {}, "maps `methodOrigins` entries to invalid origins: " + ", ".join(bad_targets)
    unknown_keys = sorted(set(str(key) for key in finer) - set(declared))
    if unknown_keys:
        return {}, "maps `methodOrigins` keys absent from `enum`: " + ", ".join(unknown_keys)
    origins, outside = {}, []
    for value in declared:
        origin = value if value in ORIGINS else finer.get(value)
        if origin in ORIGINS:
            origins[value] = origin
        else:
            outside.append(value)
    if outside:
        return {}, ("declares values that are neither an origin nor mapped to one by `methodOrigins`: "
                    + ", ".join(sorted(outside)))
    return origins, None


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
        "contract": _compact({
            "description": _purpose(contract.get("description")), "context": _context(contract.get("context")),
            "slaProperties": sla, "tags": deepcopy(contract.get("tags")), "canonicalUrls": _canonical_urls(contract),
        }),
    })
    return record, unknown


def _public_context(context):
    result = {key: context[key] for key in ("instructions",) if key in context}
    for key in ("verifiedStatements", "constraints"):
        items = [{name: deepcopy(value) for name, value in item.items() if name in PUBLIC_CONTEXT_ITEM}
                 for item in context.get(key, ())]
        if items:
            result[key] = items
    return result or None


def _public_sla(entry):
    """Keep an entry whose element adds nothing beyond this dataset; withhold one naming fields or other objects."""
    element = entry.get("element")
    if element is not None and ("," in element or "." in element or element.strip("/").count("/") > 1):
        return None
    return {key: deepcopy(value) for key, value in entry.items() if key in PUBLIC_SLA}


def public_product(product, policy):
    if not policy["descriptions"]:
        for key in PRODUCT_TEXT:
            product.pop(key, None)
    else:
        context = _public_context(product.pop("context", {}))
        if context:
            product["context"] = context


def public_dataset(dataset, policy):
    """Withhold free text without a descriptions grant, and structural names and links within it."""
    # A model method record names models, configurations and reviewers, and a method column names a field:
    # neither has a disclosure grant.
    dataset.pop("model", None)
    dataset.pop("methodColumn", None)
    if not policy["descriptions"]:
        for key in DATASET_TEXT:
            dataset.pop(key, None)
        return
    contract = dataset.get("contract", {})
    for holder in (dataset, contract):
        context = _public_context(holder.pop("context", {}))
        if context:
            holder["context"] = context
    urls = [url for url in contract.pop("canonicalUrls", ()) if url in policy["locations"]]
    if urls:
        contract["canonicalUrls"] = urls
    sla = [entry for entry in map(_public_sla, contract.pop("slaProperties", ())) if entry is not None]
    if sla:
        contract["slaProperties"] = sla
    if dataset.get("contract") == {}:
        dataset.pop("contract")
