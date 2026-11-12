"""Knowledge-graph views of an assembled catalog (DDK-CATALOG-013 and DDK-CATALOG-014).

Both read only the admitted catalog. The graph adds PROV-O, DQV, VoID and SKOS statements to the
unchanged DCAT 3 document. The YARRRML mappings let an RML engine such as Morph-KGC lift one exact
version's rows into RDF; DDK writes the mappings and never runs them.
"""

import json
import re
from collections import defaultdict, namedtuple
from hashlib import sha256
from urllib.parse import quote, unquote, urlsplit

from .catalog_access import CatalogError
from .catalog_descriptions import method_origins, origin_gap
from .catalog_exports import CONTEXT, current_versions, dcat_graph, dcat_resolves
from .catalog_metadata import check_report, stable_id
from .documents import json_dumps
from .policies import ddk_annotations

DETAILS = "urn:ddk:catalog:assembly"
VOCAB = "urn:ddk:vocab:"
ODPS = "https://github.com/bitol-io/open-data-product-standard/tree/v1.1.0"
GRAPH_CONTEXT = {
    **CONTEXT, "dqv": "http://www.w3.org/ns/dqv#", "void": "http://rdfs.org/ns/void#",
    "skos": "http://www.w3.org/2004/02/skos/core#", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#", "ddkv": VOCAB,
}
GRAPH_ADAPTER = {"id": "ddk.catalog.graph", "version": "0.1.0"}
RML_ADAPTER = {"id": "ddk.catalog.rml", "version": "0.1.0"}
# Only declarations that pin a representation get a datatype; logical `number` stays plain (DDK-DATA-003).
# Unbounded or 64-bit `integer` maps to `xsd:long` so values above 2^53 never pass through Morph-KGC's float64 cast.
DATATYPES = {"boolean": "xsd:boolean", "date": "xsd:date", "timestamp": "xsd:dateTime", "time": "xsd:time"}
INT32_PHYSICAL_TYPES = frozenset({
    "int8", "int16", "int32", "int1", "int2", "int4", "tinyint", "smallint", "int", "integer",
    "uint8", "uint16", "uint32", "utinyint", "usmallint", "uinteger",
})
INT32_MIN, INT32_MAX = -2147483648, 4294967295
MATCH_PREDICATES = {"same": "http://www.w3.org/2004/02/skos/core#exactMatch",
                    "undecided": "http://www.w3.org/2004/02/skos/core#closeMatch", "not_same": VOCAB + "noMatch"}
FILE_TYPES = ("application/vnd.apache.parquet", "text/csv")  # a version's copies, preferred first: Parquet keeps types
ATTRIBUTED = "http://www.w3.org/ns/prov#wasAttributedTo"
SUBPROPERTY = "http://www.w3.org/2000/01/rdf-schema#subPropertyOf"
SEE_ALSO = "http://www.w3.org/2000/01/rdf-schema#seeAlso"
ROW = "__ddk_row"  # row position, the identity of rows in a dataset without a top-level key
# DuckDB renders these as text itself: through pandas, a nullable integer column becomes floats, and a key of 5
# would name row "5.0" in one mapping and "5" in another.
AS_TEXT = {"integer", "number", "boolean"}
# Every generated DuckDB query filters SQL NULLs with IS NOT NULL before Pandas reads the result; setting Morph-KGC
# `na_values` to Unicode noncharacter U+FFFF preserves literal "None", "", "nan", "NaT" and "<NA>" strings intact.
NA_VALUES = "\uffff"
NA_SENTINEL = "\\uffff"
GLOB_CHARS = frozenset("*?[")
SAFE_YAML_KEY = re.compile(r"^[A-Za-z0-9_./#%+-]+(?::[A-Za-z0-9_./#%+-]+)*$")


def child_iri(base, *parts):
    """An IRI under a catalog identifier: URNs extend with ':' and other IRIs with '/'."""
    separator = ":" if base.startswith("urn:") else "/"
    return separator.join([base.rstrip(":/"), *(quote(str(part), safe="") for part in parts)])


def field_predicate(dataset_id, path):
    """The predicate for a field: scoped to its dataset, so two fields never share one by accident."""
    return child_iri(dataset_id, "field", *path)


def _definitions(catalog):
    return catalog.get("extensions", {}).get(DETAILS, {}).get("datasetDefinitions", {})


def _peer_catalogs(catalog):
    return catalog.get("extensions", {}).get(DETAILS, {}).get("peerCatalogs", {})


def _concepts(catalog):
    """{(dataset alias, field names): concept IRI}; an array item's concept applies to the array's values."""
    return {(field["dataset"], tuple(step["field"] for step in field["path"] if "field" in step)): row["concept"]
            for row in catalog.get("concepts", ()) for field in row["fields"] if "catalog" not in field}


def _concept_templates(catalog):
    """{(dataset alias, field names): iriTemplate} for local identifier-concept fields declaring iriTemplate."""
    return {
        (field["dataset"], tuple(step["field"] for step in field["path"] if "field" in step)): row["iriTemplate"]
        for row in catalog.get("concepts", ())
        if row.get("conceptKind") == "identifier" and row.get("iriTemplate")
        for field in row["fields"]
        if "catalog" not in field
    }


def _fields(properties, path=()):
    """Every declared field, with array items addressed by the array's own path."""
    for prop in properties:
        here = (*path, prop["name"])
        yield here, prop
        yield from _fields(prop.get("properties", ()), here)
        if isinstance(prop.get("items"), dict):
            yield from _fields(prop["items"].get("properties", ()), here)


def _row_keys(catalog):
    """Each dataset's first declared key of top-level, non-virtual fields; other keys cannot name a row."""
    keys = {}
    for identity in catalog["identities"]:
        fields = [item["path"] for item in identity["fields"]]
        if (identity["kind"] == "key" and identity["dataset"] not in keys
                and all(len(path) == 1 and "field" in path[0] and not item["virtual"]
                        for path, item in zip(fields, identity["fields"]))):
            keys[identity["dataset"]] = [path[0]["field"] for path in fields]
    return keys


def _blank(scope, columns):
    """A blank-node template whose label is scoped by a hash, so rows of two datasets or versions never merge."""
    label = "b" + sha256(scope.encode()).hexdigest()[:20]
    return {"value": label + "".join(f"_$({column})" for column in columns), "type": "blanknode"}


def _template(base, columns):
    separator = ":" if base.startswith("urn:") else "/"
    return base + "".join(f"{separator}$({column})" for column in columns)


def _key(value):
    """A hashable form of a JSON-LD value: a string, or a node or value object of strings."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and all(isinstance(item, str) for item in value.values()):
        return tuple(sorted(value.items()))
    return json_dumps(value)


class _Nodes:
    def __init__(self, graph):
        self.items = {node["@id"]: node for node in graph}
        self.seen = {}

    def node(self, identifier, *types):
        item = self.items.setdefault(identifier, {"@id": identifier})
        self.add(item, "@type", *types)
        return item

    def add(self, item, key, *values):
        seen = self.seen.get((item["@id"], key))
        if seen is None:
            current = item.get(key, [])
            seen = self.seen[(item["@id"], key)] = set(map(_key, current if isinstance(current, list) else [current]))
        for value in values:
            if value in (None, "", []) or _key(value) in seen:
                continue
            seen.add(_key(value))
            current = item.get(key)
            if current is None:
                item[key] = value
            elif isinstance(current, list):
                current.append(value)
            else:
                item[key] = [current, value]


def _ref(identifier):
    return {"@id": identifier}


def _concept(prefix, value):
    return _ref(f"ddkv:{prefix}-{value}")


def _target_id(relationship, aliases, peer_catalogs=None, imports=None):
    """A relationship target's dataset identifier, peer dataset identifier, or external identifier."""
    target = relationship["target"]
    if "catalog" in target:
        peer_alias, peer_ds = target["catalog"], target["dataset"]
        peer_ds_id = (peer_catalogs or {}).get(peer_alias, {}).get("datasets", {}).get(peer_ds)
        if peer_ds_id is not None:
            return peer_ds_id
        peer_cat_id = (imports or {}).get(peer_alias, {}).get("id", f"urn:ddk:peer:{peer_alias}")
        return child_iri(peer_cat_id, "dataset", peer_ds)
    return aliases[target["dataset"]] if "dataset" in target else target["external"]


def graph_document(catalog):
    """DCAT 3 plus PROV-O, DQV, VoID and SKOS for the catalog's facts, read back by an independent reader.

    Returns the JSON-LD document and the graph the reader parsed from it, so Turtle reuses that parse. The one
    parse also checks the DCAT part, which is why the DCAT document is built here without its own.
    """
    try:
        from rdflib import Graph, Literal, RDF, URIRef
    except ImportError as exc:
        raise CatalogError("ADAPTER-CAPABILITY-MISSING", "The graph export requires an independent JSON-LD reader.",
                           status="not_run") from exc
    nodes = _Nodes(dcat_graph(catalog)["@graph"])
    root = nodes.node(catalog["id"])
    aliases = {item["alias"]: item["id"] for item in catalog["datasets"]}
    peer_catalogs = _peer_catalogs(catalog)
    imports = catalog.get("imports", {})
    definitions, concepts = _definitions(catalog), _concepts(catalog)
    audience = catalog.get("audience", "local")
    unknown_origins = frozenset(catalog.get("extensions", {}).get(DETAILS, {}).get("unknownOrigins", ()))
    concept_kinds = {row["concept"]: row["conceptKind"] for row in catalog.get("concepts", ()) if row.get("conceptKind")}

    def open_concept(scheme, value):
        """A concept in a catalog-scoped scheme for open values such as statuses and layer names."""
        scheme_id = child_iri(catalog["id"], scheme)
        nodes.add(nodes.node(scheme_id, "skos:ConceptScheme"), "skos:prefLabel", scheme)
        nodes.add(root, "dcat:themeTaxonomy", _ref(scheme_id))
        concept = nodes.node(child_iri(catalog["id"], scheme, value), "skos:Concept")
        nodes.add(concept, "skos:prefLabel", value)
        nodes.add(concept, "skos:inScheme", _ref(scheme_id))
        return _ref(concept["@id"])

    for dataset in catalog["datasets"]:
        item = nodes.node(dataset["id"], "prov:Entity")
        layer = dataset["alias"].strip("/").rpartition("/")[0]
        nodes.add(root, "dcat:themeTaxonomy", _ref("ddkv:DatasetRole"))
        nodes.add(item, "dcat:theme", _concept("role", dataset["role"]),
                  open_concept("status", dataset["status"]) if dataset.get("status") else None,
                  open_concept("layer", layer) if layer else None)
        if isinstance(dataset.get("description"), str):
            nodes.add(item, "dcterms:description", dataset["description"])
        nodes.add(item, "skos:definition", dataset.get("rowMeaning"))
        if dataset.get("origin"):
            _attribution(nodes, item, dataset, audience=audience, unknown_origins=unknown_origins)
        model = dataset.get("model", {})
        if model.get("review"):
            nodes.add(item, "dcat:theme", _concept("review", model["review"]))
        if model.get("review") in {"spot_checked", "reviewed"}:
            review = nodes.node(stable_id("review", dataset["id"], model), "prov:Activity")
            nodes.add(review, "dcterms:type", _concept("review", model["review"]))
            nodes.add(review, "prov:used", _ref(dataset["id"]))
            if model.get("reviewer"):
                person = nodes.node(stable_id("person", model["reviewer"]), "prov:Person", "prov:Agent")
                nodes.add(person, "rdfs:label", model["reviewer"])
                nodes.add(review, "prov:wasAssociatedWith", _ref(person["@id"]))
        properties = definitions.get(dataset["alias"], {}).get("properties", ())
        if dataset.get("methodColumn"):
            column = next((prop for prop in properties if prop["name"] == dataset["methodColumn"]), None)
            origins, reason = method_origins(column) if column is not None else ({}, "missing")
            if reason is None and origins:
                nodes.add(item, "ddkv:methodColumn", _ref(field_predicate(dataset["id"], (dataset["methodColumn"],))))
                for value, origin in origins.items():
                    agent = nodes.node(child_iri(dataset["id"], "agent", value), "prov:Agent")
                    nodes.add(agent, "rdfs:label", value)
                    nodes.add(agent, "dcterms:type", _concept("origin", origin))
        for path, prop in _fields(properties):
            field = nodes.node(field_predicate(dataset["id"], path), "rdf:Property")
            nodes.add(field, "rdfs:subPropertyOf", _ref(concepts[(dataset["alias"], path)])
                      if (dataset["alias"], path) in concepts else None)
            nodes.add(field, "rdfs:label", ".".join(path))
            nodes.add(field, "skos:definition", prop.get("description"))
            nodes.add(field, "rdfs:isDefinedBy", _ref(dataset["id"]))
            nodes.add(field, "rdfs:seeAlso", *(_ref(entry["url"]) for entry in prop.get("authoritativeDefinitions", ())
                                               if entry.get("type") == "canonicalUrl" and entry.get("url")))
    for version in catalog["versions"]:
        nodes.node(version["id"], "prov:Entity")
    plans = {}
    for production in catalog["productions"]:
        plan = nodes.node(production["identity"]["id"], "prov:Plan")
        nodes.add(plan, "rdfs:label", production["alias"])
        nodes.add(plan, "dcterms:hasVersion", production["identity"]["version"])
        nodes.add(plan, "dcterms:source", _ref(production["definition"]["uri"]))
        plans[production["alias"]] = plan["@id"]
    for run in catalog["runs"]:
        activity = nodes.node(run["id"], "prov:Activity")
        nodes.add(activity, "prov:used", *map(_ref, run["inputs"]))
        nodes.add(activity, "dcterms:source", _ref(run["record"]["uri"]))
        for key, term in (("startedAt", "prov:startedAtTime"), ("endedAt", "prov:endedAtTime")):
            if run.get(key):
                nodes.add(activity, term, {"@value": run[key], "@type": "http://www.w3.org/2001/XMLSchema#dateTime"})
        if run.get("production") in plans:
            association = nodes.node(stable_id("association", run["id"]), "prov:Association")
            nodes.add(association, "prov:hadPlan", _ref(plans[run["production"]]))
            nodes.add(activity, "prov:qualifiedAssociation", _ref(association["@id"]))
        for output in run["outputs"]:
            nodes.add(nodes.node(output), "prov:wasGeneratedBy", _ref(run["id"]))
    for check in catalog["checks"]:
        measurement = nodes.node(stable_id("measurement", check), "dqv:QualityMeasurement")
        metric = nodes.node(check["rule"]["id"], "dqv:Metric")
        nodes.add(metric, "dcterms:hasVersion", check["rule"]["version"])
        evaluator = nodes.node(stable_id("evaluator", check["evaluator"]), "prov:SoftwareAgent")
        nodes.add(evaluator, "rdfs:label", check["evaluator"]["id"])
        nodes.add(evaluator, "dcterms:hasVersion", check["evaluator"].get("version"))
        nodes.add(measurement, "dqv:computedOn", _ref(check["subject"]))
        nodes.add(measurement, "dqv:isMeasurementOf", _ref(metric["@id"]))
        nodes.add(measurement, "dqv:value", check["status"])
        nodes.add(measurement, "ddkv:outcome", _concept("outcome", check["status"]))
        nodes.add(measurement, "dcterms:type", _concept("evidence", "executed" if check_report(check) else "declared"))
        nodes.add(measurement, "prov:wasAttributedTo", _ref(evaluator["@id"]))
        nodes.add(measurement, "dcterms:coverage", check.get("scope"))
        nodes.add(measurement, "rdfs:comment", check.get("reason"))
        nodes.add(measurement, "dcterms:source", _ref(check["record"]["uri"]) if check.get("record") else None)
    for relationship in catalog["relationships"]:
        linkset = nodes.node(child_iri(relationship["id"], "linkset"), "void:Linkset")
        nodes.add(nodes.node(relationship["id"], "rdf:Property"), "rdfs:label", relationship.get("meaning"))
        nodes.add(linkset, "void:linkPredicate", _ref(relationship["id"]))
        nodes.add(linkset, "void:subjectsTarget", _ref(aliases[relationship["source"]["dataset"]]))
        nodes.add(linkset, "void:objectsTarget", _ref(_target_id(relationship, aliases, peer_catalogs, imports)))
        nodes.add(linkset, "dcterms:description", relationship.get("meaning"))
        nodes.add(linkset, "dcterms:type", *(_concept(key, relationship[key]) for key in (
            "cardinality", "scope", "nulls", "match") if relationship.get(key)))
    glossary = child_iri(catalog["id"], "glossary")
    for row in catalog.get("concepts", ()):
        concept = nodes.node(row["concept"], "skos:Concept", "rdf:Property")
        nodes.add(nodes.node(glossary, "skos:ConceptScheme"), "skos:prefLabel", "glossary")
        nodes.add(root, "dcat:themeTaxonomy", _ref(glossary))
        nodes.add(concept, "skos:inScheme", _ref(glossary))
        nodes.add(concept, "skos:prefLabel", row["definition"])
        nodes.add(concept, "skos:definition", row.get("description"))
        if row.get("conceptKind"):
            nodes.add(concept, "dcterms:type", _concept("concept-kind", row["conceptKind"]))
        nodes.add(concept, "skos:exactMatch", *map(_ref, row.get("exactMatch", ())))
        nodes.add(concept, "skos:closeMatch", *map(_ref, row.get("closeMatch", ())))
        nodes.add(concept, "rdfs:seeAlso", *map(_ref, row.get("canonicalUrls", ())))
    candidate_entries = [
        *((stable_id("candidate-linkset", subject, target, concept), aliases[subject], aliases[target], concept)
          for subject, target, concept in candidate_links(catalog)),
        *((stable_id("candidate-linkset", subject_id, target_id, concept), subject_id, target_id, concept)
          for subject_id, target_id, concept in cross_catalog_candidate_links(catalog)),
    ]
    for node_id, subject_id, target_id, concept in candidate_entries:
        linkset = nodes.node(node_id, "ddkv:CandidateLinkset")
        nodes.add(linkset, "ddkv:subjectsTarget", _ref(subject_id))
        nodes.add(linkset, "ddkv:objectsTarget", _ref(target_id))
        nodes.add(linkset, "dcterms:subject", _ref(concept))
        nodes.add(linkset, "dcterms:type", _concept("evidence", "inferred"),
                  _concept("concept-kind", concept_kinds[concept]) if concept in concept_kinds else None)
        nodes.add(linkset, "dcterms:description", "Both datasets carry this concept, the second keys its rows by it, and "
                  "other declared relationships join on it. No relationship joins these two: a candidate, not a link.")
    for product in catalog["products"]:
        item = nodes.node(product["id"], "dcat:Resource")
        nodes.add(item, "dcterms:conformsTo", _ref(ODPS))
        nodes.add(item, "dcterms:title", product.get("name"))
        nodes.add(item, "dcterms:hasVersion", product.get("version"))
        nodes.add(item, "dcterms:source", _ref(product["definition"]["uri"]))
        description = product.get("description")
        nodes.add(item, "dcterms:description", description.get("purpose") if isinstance(description, dict) else description)
        nodes.add(item, "dcat:theme", open_concept("status", product["status"]) if product.get("status") else None)
        for port in product["ports"]:
            nodes.add(item, "dcterms:hasPart" if port["direction"] == "output" else "dcterms:requires",
                      _ref(aliases[port["dataset"]]))
    document = {"@context": GRAPH_CONTEXT, "@graph": [nodes.items[key] for key in sorted(nodes.items)]}
    parsed = Graph().parse(data=json_dumps(document), format="json-ld")

    def iri(term):
        prefix, _, local = term.partition(":")
        return URIRef(GRAPH_CONTEXT[prefix] + local if prefix in GRAPH_CONTEXT else term)

    found = {
        "datasets": len(set(parsed.objects(iri(catalog["id"]), iri("dcat:dataset")))),
        "versions": len(set(parsed.subjects(iri("dcat:isVersionOf")))),
        "relationships": len(set(parsed.subjects(RDF.type, iri("void:Linkset")))),
        "checks": len(set(parsed.subjects(RDF.type, iri("dqv:QualityMeasurement")))),
        "products": len(set(parsed.subjects(iri("dcterms:conformsTo"), iri(ODPS)))),
    }
    missing = [edge for edge in graph_edges(catalog) if tuple(map(iri, edge)) not in parsed]
    missing.extend(
        (stable_id("measurement", check), "dqv:value", check["status"])
        for check in catalog["checks"]
        if (iri(stable_id("measurement", check)), iri("dqv:value"), Literal(check["status"])) not in parsed
    )
    if not dcat_resolves(parsed, catalog):
        missing.insert(0, "the DCAT catalog and its datasets")
    if found != graph_counts(catalog) or missing:
        raise CatalogError("CATALOG-GRAPH-VALIDATION", f"The JSON-LD reader found {found} for "
                           f"{graph_counts(catalog)} and lacks {len(missing)} expected edges, such as {missing[:1]}.")
    return document, parsed


def graph_counts(catalog):
    """What the graph must hold, counted from the catalog itself."""
    return {"datasets": len({item["id"] for item in catalog["datasets"]}), "versions": len(catalog["versions"]),
            "relationships": len(catalog["relationships"]),
            "checks": len({json_dumps(item) for item in catalog["checks"]}),
            "products": len({item["id"] for item in catalog["products"]})}


def _attribution(nodes, item, dataset, *, audience="local", unknown_origins=()):
    """The dataset `prov:wasAttributedTo` its origin's agent, qualified as a declaration DDK has not verified.

    A complete model method record names a configured `prov:SoftwareAgent`; an incomplete record or the older
    `derived` names only the origin, and the attribution carries the `unknown` outcome and its reason.
    """
    gap = origin_gap(dataset, audience=audience, unknown_origins=unknown_origins)
    model = dataset.get("model", {}) if dataset["origin"] == "model" and gap is None else {}
    if model:
        agent = nodes.node(stable_id("model", model["id"], model["version"], model["configurationSha256"]),
                           "prov:SoftwareAgent", "prov:Agent")
        nodes.add(agent, "rdfs:label", model["id"])
        nodes.add(agent, "dcterms:hasVersion", model["version"])
        nodes.add(agent, "dcterms:identifier", "sha256:" + model["configurationSha256"])
    else:
        agent = nodes.node(stable_id("origin-agent", dataset["id"], dataset["origin"]), "prov:Agent")
    nodes.add(agent, "dcterms:type", _concept("origin", dataset["origin"]))
    nodes.add(item, "prov:wasAttributedTo", _ref(agent["@id"]))
    attribution = nodes.node(stable_id("attribution", dataset["id"]), "prov:Attribution")
    nodes.add(item, "prov:qualifiedAttribution", _ref(attribution["@id"]))
    nodes.add(attribution, "prov:agent", _ref(agent["@id"]))
    nodes.add(attribution, "dcterms:type", _concept("evidence", "declared"), _concept("outcome", "unknown") if gap else None)
    nodes.add(attribution, "rdfs:comment", gap[1] if gap else None)


def candidate_links(catalog):
    """(carrier, keyed dataset, concept) where a dataset carries a concept that another keys its rows by.

    Only concepts some declared relationship already joins on count. That keeps out value types nothing joins on,
    but not a date some relationship does join on. Inferred, never declared: pairs a relationship already joins
    are left out. The count grows with carriers times keyed datasets per concept, not with every pair of carriers.
    """
    keys = _row_keys(catalog)
    declared = {frozenset((row["source"]["dataset"], row["target"].get("dataset")))
                for row in catalog["relationships"] if "catalog" not in row["target"]}
    joined = {(row[side]["dataset"], json_dumps(path)) for row in catalog["relationships"]
              for side in ("source", "target") if "dataset" in row[side] and "catalog" not in row[side]
              for path in row[side]["paths"]}
    found = set()
    for row in catalog.get("concepts", ()):
        local_fields = [field for field in row["fields"] if "catalog" not in field]
        if not any((field["dataset"], json_dumps(field["path"])) in joined for field in local_fields):
            continue
        anchors = {field["dataset"] for field in local_fields
                   if keys.get(field["dataset"]) and [[{"field": name}] for name in keys[field["dataset"]]] == [field["path"]]}
        for field in local_fields:
            for anchor in sorted(anchors - {field["dataset"]}):
                pair = tuple(sorted((field["dataset"], anchor))) if field["dataset"] in anchors else (field["dataset"], anchor)
                if frozenset(pair) not in declared:
                    found.add((*pair, row["concept"]))
    return sorted(found)


def cross_catalog_candidate_links(catalog):
    """(subject_dataset_id, object_dataset_id, concept) across local and imported peer catalogs."""
    aliases = {item["alias"]: item["id"] for item in catalog.get("datasets", ())}
    peer_catalogs = _peer_catalogs(catalog)
    imports = catalog.get("imports", {})
    local_keys = _row_keys({"identities": catalog.get("identities", ())})
    peer_keys = {peer_alias: _row_keys({"identities": peer_info.get("identities", ())})
                 for peer_alias, peer_info in peer_catalogs.items()}
    declared_cross = {(row["source"]["dataset"], (row["target"]["catalog"], row["target"]["dataset"]))
                      for row in catalog.get("relationships", ()) if "catalog" in row["target"]}
    joined_any = {(row[side].get("catalog"), row[side]["dataset"], json_dumps(path))
                  for row in catalog.get("relationships", ())
                  for side in ("source", "target") if "dataset" in row[side] for path in row[side]["paths"]}
    found = set()
    for row in catalog.get("concepts", ()):
        local_fields = [field for field in row["fields"] if "catalog" not in field and field["dataset"] in aliases]
        peer_fields = [field for field in row["fields"] if "catalog" in field]
        if not local_fields or not peer_fields:
            continue
        if row.get("conceptKind") != "identifier" and not any(
            (field.get("catalog"), field["dataset"], json_dumps(field["path"])) in joined_any
            for field in row["fields"]
        ):
            continue
        for lf in local_fields:
            l_is_key = bool(local_keys.get(lf["dataset"])
                            and [[{"field": name}] for name in local_keys[lf["dataset"]]] == [lf["path"]])
            for pf in peer_fields:
                if (lf["dataset"], (pf["catalog"], pf["dataset"])) in declared_cross:
                    continue
                peer_info = peer_catalogs.get(pf["catalog"], {})
                peer_ds_id = (peer_info.get("datasets", {}).get(pf["dataset"])
                              or child_iri(imports.get(pf["catalog"], {}).get("id", f"urn:ddk:peer:{pf['catalog']}"),
                                           "dataset", pf["dataset"]))
                p_keys = peer_keys.get(pf["catalog"], {}).get(pf["dataset"])
                p_is_key = bool(p_keys and [[{"field": name}] for name in p_keys] == [pf["path"]])
                if p_is_key or (not p_is_key and not l_is_key and not peer_info.get("identities")):
                    found.add((aliases[lf["dataset"]], peer_ds_id, row["concept"]))
                elif l_is_key:
                    found.add((peer_ds_id, aliases[lf["dataset"]], row["concept"]))
    return sorted(found)


def graph_edges(catalog):
    """The evidence-carrying edges the graph must contain, read straight from the catalog records."""
    aliases = {item["alias"]: item["id"] for item in catalog["datasets"]}
    peer_catalogs = _peer_catalogs(catalog)
    imports = catalog.get("imports", {})
    for run in catalog["runs"]:
        yield from ((run["id"], "prov:used", version) for version in run["inputs"])
        yield from ((version, "prov:wasGeneratedBy", run["id"]) for version in run["outputs"])
    for check in catalog["checks"]:
        measurement = stable_id("measurement", check)
        yield measurement, "dqv:computedOn", check["subject"]
        yield measurement, "ddkv:outcome", f"ddkv:outcome-{check['status']}"
        yield measurement, "dcterms:type", "ddkv:evidence-" + ("executed" if check_report(check) else "declared")
    for relationship in catalog["relationships"]:
        linkset = child_iri(relationship["id"], "linkset")
        yield linkset, "void:subjectsTarget", aliases[relationship["source"]["dataset"]]
        yield linkset, "void:objectsTarget", _target_id(relationship, aliases, peer_catalogs, imports)
        yield linkset, "void:linkPredicate", relationship["id"]
    for product in catalog["products"]:
        for port in product["ports"]:
            yield (product["id"], "dcterms:hasPart" if port["direction"] == "output" else "dcterms:requires",
                   aliases[port["dataset"]])


def turtle_bytes(graph):
    for prefix, namespace in GRAPH_CONTEXT.items():
        graph.bind(prefix, namespace, override=True)
    return graph.serialize(format="turtle").encode("utf-8")


# RML mappings. DuckDB views, which Morph-KGC runs for `query` sources over files, project each declared field,
# unnest declared arrays, number keyless rows, join along declared equal-value relationships and split declared
# decision tables by decision. Every view filters SQL NULLs with IS NOT NULL and projects unambiguous positional
# aliases (k0, v0, i0, t0), so real NULLs never enter Pandas and literal "None" or "" strings survive intact.
# None aggregates or computes a value, so a mapping re-expresses rows and never derives new ones (ADR-015).

def _sql_name(name):
    return '"' + str(name).replace('"', '""') + '"'


def _sql_text(value):
    return "'" + str(value).replace("'", "''") + "'"


def _sql_field(path, table=None):
    expression = (f"{table}." if table else "") + _sql_name(path[0])
    return expression + "".join(f"[{_sql_text(part)}]" for part in path[1:])


def _phys_name(prop):
    return prop.get("physicalName") or prop["name"]


def _datatype(prop):
    logical = prop.get("logicalType")
    if logical == "integer":
        physical = str(prop.get("physicalType") or "").strip().lower()
        if physical in INT32_PHYSICAL_TYPES:
            return "xsd:integer"
        options = prop.get("logicalTypeOptions")
        if isinstance(options, dict):
            minimum, maximum = options.get("minimum"), options.get("maximum")
            if (isinstance(minimum, (int, float)) and not isinstance(minimum, bool)
                    and isinstance(maximum, (int, float)) and not isinstance(maximum, bool)
                    and INT32_MIN <= minimum <= maximum <= INT32_MAX):
                return "xsd:integer"
        return "xsd:long"
    return DATATYPES.get(logical)


def _text(expression, prop):
    return f"CAST({expression} AS VARCHAR)" if prop.get("logicalType") in AS_TEXT else expression


def _column(path):
    return ".".join(path)


def _path_key(path):
    return ":".join(quote(str(part), safe="") for part in path)


def _resolve_field(properties, logical_path):
    """Return (physical_path, prop) for a tuple of logical field names, falling back to logical names."""
    current = list(properties)
    physical, prop = [], {}
    for index, name in enumerate(logical_path):
        found = next((item for item in current if item.get("name") == name), None)
        if found is None:
            return (*physical, *logical_path[index:]), {}
        physical.append(_phys_name(found))
        prop = found
        current = list(found.get("properties", ()))
    return tuple(physical), prop


def _iri(value):
    """An IRI term map. Readers that guess IRIs from the scheme would read a `urn:` constant as a literal."""
    return {"value": value, "type": "iri"}


def _value(dataset_id, path, prop, column):
    """A field's value under its dataset-scoped predicate, typed when its declaration pins a representation."""
    datatype = _datatype(prop)
    return {"p": _iri(field_predicate(dataset_id, path)),
            "o": {"value": f"$({column})", "datatype": datatype} if datatype else f"$({column})"}


def _local_path(location):
    parts = urlsplit(location)
    return unquote(parts.path) if parts.scheme == "file" else location


def _files(catalog):
    """Each exact version's available Parquet or CSV copy, and any rejected glob-containing paths."""
    files, globbed = {}, {}
    for record in sorted((item for item in catalog["representations"] if item.get("mediaType") in FILE_TYPES),
                         key=lambda item: (FILE_TYPES.index(item["mediaType"]), item["id"])):
        if record["kind"] == "file" and record["availability"] == "available":
            path = _local_path(record["location"])
            if any(char in path for char in GLOB_CHARS):
                globbed.setdefault(record["version"], path)
            else:
                files.setdefault(record["version"], path)
    return files, globbed


def _bindings(catalog):
    """({alias: (exact version, file)}, {alias: why not}, {alias: chosen version}) for catalog datasets.

    A current selection binds versions as it binds DCAT's current versions (DDK-CATALOG-008). Without one, a
    dataset binds only when the catalog holds exactly one version of it: file order and time never break a tie.
    """
    version_aliases = {item["id"]: item["dataset"] for item in catalog["versions"]}
    held = defaultdict(list)
    for version, alias in version_aliases.items():
        held[alias].append(version)
    selecting = bool(catalog.get("currentSelection"))
    chosen = ({alias: version for alias, (version, _) in current_versions(catalog, version_aliases).items()}
              if selecting else {alias: versions[0] for alias, versions in held.items() if len(versions) == 1})
    (files, globbed), bound, unbound = _files(catalog), {}, {}
    for alias in (item["alias"] for item in catalog["datasets"]):
        version, count = chosen.get(alias), len(held.get(alias, ()))
        if version in files:
            bound[alias] = (version, files[version])
        elif version and version in globbed:
            unbound[alias] = (f"Its exact version {version} has a file path containing DuckDB glob characters "
                              "(*, ? or [), which cannot safely bind one file.")
        elif version:
            unbound[alias] = f"Its exact version {version} has no available Parquet or CSV file."
        elif selecting:
            unbound[alias] = "The current selection names no version of it."
        else:
            unbound[alias] = (f"The catalog holds {count} versions of it; choose one with a current selection."
                              if count else "The catalog holds no version of it.")
    return bound, unbound, chosen


def _release_sharing(catalog):
    """Whether two exact versions are members of one release."""
    releases = defaultdict(set)
    for release in catalog["releases"]:
        for member in release["members"]:
            releases[member].add(release["id"])
    return lambda left, right: bool(releases[left] & releases[right])


def _reader(path, numbered=False):
    """DuckDB reads every file, so values render the same in every mapping; CSV preserves quoted empty strings."""
    if path.lower().endswith((".csv", ".tsv")):
        reader = f"read_csv({_sql_text(path)}, all_varchar = true, header = true, allow_quoted_nulls = false)"
        return f"(SELECT row_number() OVER () AS {_sql_name(ROW)}, * FROM {reader})" if numbered else reader
    if numbered:  # the position DuckDB reads from the file, not an order the query happens to keep
        return (f"(SELECT file_row_number AS {_sql_name(ROW)}, * EXCLUDE (file_row_number) "
                f"FROM read_parquet({_sql_text(path)}, file_row_number = true))")
    return f"read_parquet({_sql_text(path)})"


class _Rows:
    """How one dataset's rows are read and named: by key, or by position in the file when it has none.

    `version` is the bound exact version with a readable file, or None for a template that reads a placeholder file.
    `chosen_version` is the catalog's selected exact version even when no file representation is available.
    """

    def __init__(self, dataset, key, path, version, chosen_version, properties):
        self.dataset, self.key, self.path = dataset, key, path
        self.version, self.chosen_version = version, chosen_version
        self.properties = tuple(properties)
        self.columns = key or [ROW]
        self.key_aliases = [f"k{index}" for index in range(len(self.columns))]
        self.reader = _reader(path, numbered=not key)
        specs = []
        for index, column in enumerate(self.columns):
            if key:
                (phys,), prop = _resolve_field(self.properties, (column,))
            else:
                phys, prop = ROW, {}
            specs.append((phys, prop, f"k{index}"))
        self._key_specs = tuple(specs)

    def subject(self):
        if self.key:
            return _template(child_iri(self.dataset["id"], "row"), self.key_aliases)
        return _blank(f"{self.dataset['id']}\n{self.version or 'template'}", self.key_aliases)

    def select_keys(self, table=None):
        return [f"{_text(_sql_field((phys,), table), prop)} AS {alias}" for phys, prop, alias in self._key_specs]

    def projected_keys(self):
        return ", ".join(self.key_aliases)

    def key_not_null(self, table=None):
        return [f"{_sql_field((phys,), table)} IS NOT NULL" for phys, _, _ in self._key_specs]

    def where(self, *extra, table=None):
        clauses = list(dict.fromkeys([*self.key_not_null(table), *extra]))
        return " AND ".join(clauses)


class _PeerRows:
    """A peer catalog dataset's row identity and schema, resolved offline without opening peer data files."""

    def __init__(self, dataset, key, properties):
        self.dataset = dataset
        self.key = key
        self.properties = tuple(properties)
        self.version = None
        self.chosen_version = None
        self.is_peer = True


# What every dataset's mappings share: each dataset's rows, peer rows, its concept fields and the catalog's releases.
_Context = namedtuple("_Context", "rows peer_rows concepts templates same_release")


def _target(relationship, context):
    """Target fields, when they are top-level fields, and the target's rows when it has a key."""
    endpoint = relationship["target"]
    if "catalog" in endpoint:
        target = context.peer_rows.get((endpoint["catalog"], endpoint.get("dataset")))
    else:
        target = context.rows.get(endpoint.get("dataset"))
    paths = endpoint["paths"] if target else ()
    if target is None or not target.key or not all(len(path) == 1 and "field" in path[0] for path in paths):
        return None, None
    return [path[0]["field"] for path in paths], target


def _rml_plan(catalog):
    public = catalog.get("audience") == "public"
    assembly_ext = catalog.get("extensions", {}).get(DETAILS)
    definitions = (assembly_ext or {}).get("datasetDefinitions", {})
    if assembly_ext is None or (not definitions and not public):
        raise CatalogError("ADAPTER-CAPABILITY-MISSING", "RML mappings need the catalog's dataset definitions.",
                           status="not_run")
    datasets = {item["alias"]: item for item in catalog["datasets"]}
    keys, (bound, unbound, chosen) = _row_keys(catalog), _bindings(catalog)
    disclosed_paths = (assembly_ext or {}).get("disclosedDefinitionPaths", {})
    mappable, withheld_limits = {}, set()
    for alias, dataset in sorted(datasets.items()):
        if public:
            allowed = disclosed_paths.get(alias, ())
            key_fields = keys.get(alias)
            if alias not in definitions or not key_fields or not all(
                [{"field": name}] in allowed for name in key_fields
            ):
                withheld_limits.add(
                    f"{dataset['id']} is not mapped in public RML: its row key or field definitions are withheld by "
                    "the disclosure policy."
                )
                continue
        mappable[alias] = dataset
    notes, rows = {}, {}
    for alias, dataset in mappable.items():
        version, path = bound.get(alias, (None, alias.rpartition("/")[2] + ".parquet"))
        notes[alias] = [] if version else [f"Template: {unbound[alias]} Every source reads {path}; point them at "
                                           "one exact version's file."]
        rows[alias] = _Rows(dataset, keys.get(alias), path, version, chosen.get(alias),
                            definitions.get(alias, {}).get("properties", ()))
    peer_rows = {}
    for peer_alias, peer_info in sorted(_peer_catalogs(catalog).items()):
        peer_keys = _row_keys({"identities": peer_info.get("identities", ())})
        peer_defs = peer_info.get("datasetDefinitions", {})
        peer_disclosed = peer_info.get("disclosedDefinitionPaths", {})
        for peer_ds, peer_ds_id in sorted(peer_info.get("datasets", {}).items()):
            key_fields = peer_keys.get(peer_ds)
            if not key_fields:
                continue
            if peer_info.get("audience") == "public" and peer_ds in peer_disclosed:
                if not all([{"field": name}] in peer_disclosed[peer_ds] for name in key_fields):
                    continue
            peer_rows[(peer_alias, peer_ds)] = _PeerRows(
                {"id": peer_ds_id, "alias": peer_ds},
                key_fields,
                peer_defs.get(peer_ds, {}).get("properties", ()),
            )
    context = _Context(rows, peer_rows, _concepts(catalog), _concept_templates(catalog), _release_sharing(catalog))
    outgoing = defaultdict(list)
    for relationship in catalog["relationships"]:
        source_alias = relationship["source"]["dataset"]
        if source_alias not in mappable:
            continue
        if public:
            if not all(path in disclosed_paths.get(source_alias, ()) for path in relationship["source"]["paths"]):
                continue
            if "catalog" in relationship["target"]:
                peer_target = (relationship["target"]["catalog"], relationship["target"].get("dataset"))
                if peer_target not in peer_rows:
                    continue
            else:
                target_alias = relationship["target"].get("dataset")
                if target_alias is not None and (
                    target_alias not in mappable
                    or not all(path in disclosed_paths.get(target_alias, ())
                               for path in relationship["target"]["paths"])
                ):
                    continue
        outgoing[source_alias].append(relationship)
    documents = {}
    for alias, dataset in sorted(mappable.items()):
        mappings = _dataset_mappings(dataset, definitions.get(alias, {}), outgoing[alias], context, notes[alias],
                                     public=public, disclosed_paths=disclosed_paths.get(alias, ()))
        if alias in bound:
            for mapping in mappings.values():
                mapping["graphs"] = _iri(bound[alias][0])
        documents[alias] = ({"prefixes": {"xsd": "http://www.w3.org/2001/XMLSchema#"}, "mappings": mappings},
                            notes[alias])
    return documents, bound, withheld_limits


def rml_mappings(catalog):
    """One YARRRML document per mappable dataset: {alias: (document, notes)}. Notes name what it leaves out and why.

    A dataset bound to an exact version maps into that version's named graph. Any other is a template: it reads
    a placeholder file, claims no version, and its first note says why it is unbound.
    """
    return _rml_plan(catalog)[0]


def _dataset_mappings(dataset, definition, relationships, context, notes, *, public=False, disclosed_paths=()):
    alias, dataset_id, rows = dataset["alias"], dataset["id"], context.rows[dataset["alias"]]
    scalars, arrays = [], []
    for logical_path, phys_path, prop in _walk(definition.get("properties", ())):
        kind = prop.get("logicalType")
        (arrays if kind == "array" else scalars).append((logical_path, phys_path, prop))
        if kind == "object":
            notes.append(f"{_column(logical_path)} is an object without declared fields, so it is not mapped.")
    mappings = {}
    for logical_path, phys_path, prop in scalars:
        if prop.get("logicalType") == "object":
            continue
        raw_expr = _sql_field(phys_path)
        query = (f"SELECT {', '.join([*rows.select_keys(), f'{_text(raw_expr, prop)} AS v0'])} "
                 f"FROM {rows.reader} WHERE {rows.where(f'{raw_expr} IS NOT NULL')}")
        po = [_value(dataset_id, logical_path, prop, "v0")]
        if (alias, logical_path) in context.templates:
            po.append({"p": _iri(SEE_ALSO), "o": _iri(context.templates[(alias, logical_path)].replace("{value}", "$(v0)"))})
        mappings[f"{alias}#field:{_path_key(logical_path)}"] = {
            "sources": [{"query": query}], "s": rows.subject(), "po": po,
        }
    if dataset.get("methodColumn") and (not public or [{"field": dataset["methodColumn"]}] in disclosed_paths):
        method_prop = next((prop for prop in definition.get("properties", ())
                            if prop["name"] == dataset["methodColumn"]), None)
        origins, reason = method_origins(method_prop) if method_prop is not None else ({}, "missing")
        if reason is None and origins:
            raw_expr = _sql_field((_phys_name(method_prop),))
            query = (f"SELECT {', '.join([*rows.select_keys(), f'{_text(raw_expr, method_prop)} AS v0'])} "
                     f"FROM {rows.reader} WHERE {rows.where(f'{raw_expr} IS NOT NULL')}")
            mappings[f"{alias}#method"] = {
                "sources": [{"query": query}], "s": rows.subject(),
                "po": [{"p": _iri(ATTRIBUTED), "o": _iri(_template(child_iri(dataset_id, "agent"), ["v0"]))}],
            }
    each_links = defaultdict(list)
    each_object_links = defaultdict(list)
    for relationship in relationships:
        link = _link(relationship, rows, context, notes)
        if link is None:
            continue
        kind, value = link
        if kind == "each":
            each_links[value[0]].append(value[1])
        elif kind == "each_object":
            each_object_links[value[0]].append(value[1])
        else:
            mappings[f"{alias}#{relationship['id']}"] = value
    for logical_path, phys_path, prop in arrays:
        mappings.update(_array_mappings(dataset_id, alias, logical_path, phys_path, prop, rows,
                                        each_links.pop(logical_path, []),
                                        each_object_links.pop(logical_path, []), context.templates, notes))
    for path in dict.fromkeys([*each_links, *each_object_links]):
        notes.append(f"Links through {_column(path)} are not mapped: it is not a declared array field.")
    # A concept field keeps its own predicate; one statement per field says which concept it carries, so the rows
    # are not written twice. SPARQL reaches every carrier with `?p rdfs:subPropertyOf <concept>`.
    for (owner, path), concept in sorted(context.concepts.items()):
        if owner == alias:
            mappings[f"{alias}#concept:{_path_key(path)}"] = {
                "sources": [{"query": "SELECT 1 AS one"}], "s": _iri(field_predicate(dataset_id, path)),
                "po": [{"p": _iri(SUBPROPERTY), "o": _iri(concept)}]}
    decisions = next(iter(ddk_annotations(definition, "matchDecisions")), None)
    if decisions and not public:
        mappings.update(_decision_mappings(alias, decisions, definition, relationships, rows, context, notes))
    return mappings


def _walk(properties, logical=(), physical=()):
    """Scalar leaves, arrays and empty objects under struct nesting; array items are handled with their array."""
    for prop in properties:
        here_logical = (*logical, prop["name"])
        here_physical = (*physical, _phys_name(prop))
        if prop.get("logicalType") == "object" and prop.get("properties"):
            yield from _walk(prop["properties"], here_logical, here_physical)
        else:
            yield here_logical, here_physical, prop


def _array_mappings(dataset_id, alias, logical_path, phys_path, prop, rows, links, object_links, templates, notes):
    """Unnest one array: scalar items become repeated values, object items become nodes under the row."""
    label, key = _column(logical_path), _path_key(logical_path)
    if not isinstance(prop.get("items"), dict):
        notes.append(f"{label} is not mapped: its array element definition is absent or withheld.")
        return {}
    items = prop["items"]
    raw_array = _sql_field(phys_path)
    if items.get("logicalType") != "object":
        if items.get("logicalType") == "array":
            notes.append(f"{label} is not mapped: arrays of arrays need a view of their own.")
            return {}
        if object_links:
            notes.append(f"Links through {label} are not mapped: its items are not objects.")
        unnested = _text(f"UNNEST({raw_array})", items)
        inner = (f"SELECT {', '.join([*rows.select_keys(), f'{unnested} AS v0'])} "
                 f"FROM {rows.reader} WHERE {rows.where(f'{raw_array} IS NOT NULL')}")
        query = f"SELECT * FROM ({inner}) WHERE v0 IS NOT NULL"
        po = [_value(dataset_id, logical_path, items, "v0"), *links]
        if (alias, logical_path) in templates:
            po.append({"p": _iri(SEE_ALSO), "o": _iri(templates[(alias, logical_path)].replace("{value}", "$(v0)"))})
        return {f"{alias}#array:{key}": {"sources": [{"query": query}], "s": rows.subject(), "po": po}}
    leaves = []
    for leaf_logical, leaf_phys, child in _walk(items.get("properties", ())):
        if child.get("logicalType") in {"array", "object"}:
            notes.append(f"{label}.{_column(leaf_logical)} is not mapped: it nests inside an array element.")
        else:
            leaves.append((leaf_logical, leaf_phys, child))
    positions = f"UNNEST(range(1, len({raw_array}) + 1)) AS i0"
    inner = (f"SELECT {', '.join([*rows.select_keys(), f'UNNEST({raw_array}) AS __ddk_item', positions])} "
             f"FROM {rows.reader} WHERE {rows.where(f'{raw_array} IS NOT NULL')}")
    if rows.key:  # an item is named under its row: <row>:<array>:<position>
        separator = ":" if dataset_id.startswith("urn:") else "/"
        element = _template(child_iri(dataset_id, "row"), rows.key_aliases) + separator + key
        element = _template(element, ["i0"])
    else:
        element = _blank(f"{dataset_id}\n{rows.version or 'template'}\n{key}", [*rows.key_aliases, "i0"])
    if links:
        notes.append(f"Links through {label} are not mapped: its items are objects.")
    subject_element = _iri(element) if rows.key else element
    result = {
        f"{alias}#array:{key}": {
            "sources": [{"query": f"SELECT {rows.projected_keys()}, i0 FROM ({inner}) WHERE __ddk_item IS NOT NULL"}],
            "s": rows.subject(),
            "po": [{"p": _iri(field_predicate(dataset_id, logical_path)), "o": subject_element}],
        }
    }
    for leaf_logical, leaf_phys, child in leaves:
        leaf_raw = _sql_field(("__ddk_item", *leaf_phys))
        leaf_query = (f"SELECT {rows.projected_keys()}, i0, {_text(leaf_raw, child)} AS v0 "
                      f"FROM ({inner}) WHERE __ddk_item IS NOT NULL AND {leaf_raw} IS NOT NULL")
        full_path = (*logical_path, *leaf_logical)
        po = [_value(dataset_id, full_path, child, "v0")]
        if (alias, full_path) in templates:
            po.append({"p": _iri(SEE_ALSO), "o": _iri(templates[(alias, full_path)].replace("{value}", "$(v0)"))})
        result[f"{alias}#item:{key}:{_path_key(leaf_logical)}"] = {
            "sources": [{"query": leaf_query}], "s": subject_element, "po": po,
        }
    item_props = items.get("properties", ())
    for obj_link in object_links:
        target = obj_link["target"]
        projections, not_nulls, target_aliases = [], [], []
        for index, (tgt_field, item_logical) in enumerate(obj_link["item_fields"]):
            item_phys, src_prop = _resolve_field(item_props, item_logical)
            _, tgt_prop = _resolve_field(target.properties, (tgt_field,))
            cast_prop = src_prop if src_prop.get("logicalType") in AS_TEXT else tgt_prop
            raw_fk = _sql_field(("__ddk_item", *item_phys))
            projections.append(f"{_text(raw_fk, cast_prop)} AS t{index}")
            not_nulls.append(f"{raw_fk} IS NOT NULL")
            target_aliases.append(f"t{index}")
        where_clauses = ["__ddk_item IS NOT NULL", *dict.fromkeys(not_nulls)]
        link_query = (f"SELECT {', '.join([rows.projected_keys(), 'i0', *projections])} "
                      f"FROM ({inner}) WHERE {' AND '.join(where_clauses)}")
        result[f"{alias}#item-link:{key}:{obj_link['id']}"] = {
            "sources": [{"query": link_query}], "s": subject_element,
            "po": [{"p": _iri(obj_link["id"]),
                    "o": _iri(_template(child_iri(target.dataset["id"], "row"), target_aliases))}],
        }
    return result


def _object_array_paths(source_paths):
    """Return shared array_logical tuple if every source path traverses one shared array then item fields."""
    if not source_paths:
        return None
    shared = None
    for path in source_paths:
        each_idxs = [idx for idx, step in enumerate(path) if step.get("each")]
        if len(each_idxs) != 1:
            return None
        idx = each_idxs[0]
        if idx == 0 or idx >= len(path) - 1:
            return None
        if not all("field" in step for pos, step in enumerate(path) if pos != idx):
            return None
        prefix = tuple(step["field"] for step in path[:idx])
        if shared is None:
            shared = prefix
        elif shared != prefix:
            return None
    return shared


def _scope_allows_key_link(identifier, scope, rows, target, context, notes):
    if scope not in {"same_release", "version_pair"}:
        notes.append(f"{identifier} is not mapped: its {scope} scope needs a project-specific resolver.")
        return False
    if scope == "same_release" and rows.version is not None:
        if not target.chosen_version or not context.same_release(rows.version, target.chosen_version):
            notes.append(f"{identifier} is not mapped: its scope is the same release, and the bound versions "
                         f"{rows.version} and {target.chosen_version or 'unbound'} share none.")
            return False
    return True


def _link(relationship, rows, context, notes):
    """A relationship as ('each', (array path, po)) on a scalar array mapping, or ('view', mapping) that projects
    direct non-null foreign keys or joins the two bound exact versions in DuckDB within the relationship's scope."""
    identifier = relationship["id"]
    if relationship.get("match") == "project_rule":
        notes.append(f"{identifier} is not mapped: a project rule, not equal values, decides its matches.")
        return None
    if "dataset" not in relationship["target"]:
        notes.append(f"{identifier} is not mapped: its target is external.")
        return None
    nulls = relationship.get("nulls", "skip")
    if nulls == "unknown":
        notes.append(f"{identifier} is not mapped: its null handling is unknown.")
        return None
    fields, target = _target(relationship, context)
    if target is None:
        notes.append(f"{identifier} is not mapped: its target has no top-level key to name its rows.")
        return None
    scope = relationship.get("scope", "version_pair")
    source_paths = relationship["source"]["paths"]
    flat = all(len(path) == 1 and "field" in path[0] for path in source_paths)
    pairs = dict(zip(fields, source_paths))
    if nulls != "match" and flat and set(fields) == set(target.key):
        # The link names the target row and reads no target file, gated on the relationship's scope.
        if not _scope_allows_key_link(identifier, scope, rows, target, context, notes):
            return None
        projections, not_nulls, target_aliases = [], [], []
        for index, field in enumerate(target.key):
            src_logical = pairs[field][0]["field"]
            (src_phys,), src_prop = _resolve_field(rows.properties, (src_logical,))
            _, tgt_prop = _resolve_field(target.properties, (field,))
            cast_prop = src_prop if src_prop.get("logicalType") in AS_TEXT else tgt_prop
            raw_fk = _sql_field((src_phys,))
            projections.append(f"{_text(raw_fk, cast_prop)} AS t{index}")
            not_nulls.append(f"{raw_fk} IS NOT NULL")
            target_aliases.append(f"t{index}")
        query = f"SELECT {', '.join([*rows.select_keys(), *projections])} FROM {rows.reader} WHERE {rows.where(*not_nulls)}"
        return "view", {"sources": [{"query": query}], "s": rows.subject(),
                        "po": [{"p": _iri(identifier),
                                "o": _iri(_template(child_iri(target.dataset["id"], "row"), target_aliases))}]}
    eaches = [path for path in source_paths if path[-1].get("each")]
    if (nulls != "match" and len(source_paths) == 1 and len(eaches) == 1 and set(fields) == set(target.key)
            and all("field" in step for step in eaches[0][:-1])):
        if not _scope_allows_key_link(identifier, scope, rows, target, context, notes):
            return None
        array = tuple(step["field"] for step in eaches[0][:-1])
        return "each", (array, {"p": _iri(identifier),
                                "o": _iri(_template(child_iri(target.dataset["id"], "row"), ["v0"]))})
    object_array = _object_array_paths(source_paths)
    if (nulls != "match" and object_array is not None
            and len(fields) == len(source_paths) and set(fields) == set(target.key)):
        if not _scope_allows_key_link(identifier, scope, rows, target, context, notes):
            return None
        item_fields = [(field, tuple(step["field"] for step in pairs[field][len(object_array) + 1:]))
                       for field in target.key]
        return "each_object", (object_array, {"id": identifier, "item_fields": item_fields, "target": target})
    if len(eaches) > 1 or any(not all("field" in step for step in (path[:-1] if path in eaches else path))
                              for path in source_paths):
        notes.append(f"{identifier} is not mapped: its source path is not fields with at most one array.")
        return None
    if getattr(target, "is_peer", False):
        notes.append(f"{identifier} is not mapped: cross-catalog RML links project foreign keys to peer primary keys without scanning peer files.")
        return None
    # A join reads both files, so both sides need a bound exact version, paired as the scope allows.
    if not (rows.version and target.version):
        notes.append(f"{identifier} is not mapped: its join reads both exact versions, and one side is a template.")
        return None
    if scope not in {"same_release", "version_pair"}:
        notes.append(f"{identifier} is not mapped: its {scope} scope needs a project-specific resolver.")
        return None
    if scope == "same_release" and not context.same_release(rows.version, target.version):
        notes.append(f"{identifier} is not mapped: its scope is the same release, and the bound versions "
                     f"{rows.version} and {target.version} share none.")
        return None
    child = rows.reader
    item_prop = {}
    if eaches:
        array_logical = tuple(step["field"] for step in eaches[0][:-1])
        array_phys, array_prop = _resolve_field(rows.properties, array_logical)
        item_prop = array_prop.get("items") if isinstance(array_prop.get("items"), dict) else {}
        unnested = _text(f"UNNEST({_sql_field(array_phys)})", item_prop)
        child = (f"(SELECT *, {unnested} AS __ddk_each FROM {rows.reader} "
                 f"WHERE {rows.where(f'{_sql_field(array_phys)} IS NOT NULL')})")
    operator = "IS NOT DISTINCT FROM" if nulls == "match" else "="
    conditions, extra_where = [], []
    for field, path in pairs.items():
        (tgt_phys,), tgt_prop = _resolve_field(target.properties, (field,))
        if path in eaches:
            left_expr = 'c."__ddk_each"'
            cast_prop = item_prop if item_prop.get("logicalType") in AS_TEXT else tgt_prop
            right_expr = _text(_sql_field((tgt_phys,), "p"), cast_prop)
            if nulls != "match":
                extra_where.append('c."__ddk_each" IS NOT NULL')
        else:
            src_logical = tuple(step["field"] for step in path)
            src_phys, src_prop = _resolve_field(rows.properties, src_logical)
            need_text = src_prop.get("logicalType") in AS_TEXT or tgt_prop.get("logicalType") in AS_TEXT
            cast_prop = {"logicalType": "integer"} if need_text else {}
            left_expr = _text(_sql_field(src_phys, "c"), cast_prop)
            right_expr = _text(_sql_field((tgt_phys,), "p"), cast_prop)
        conditions.append(f"{left_expr} {operator} {right_expr}")
    target_projs = [f"{_text(_sql_field((phys,), 'p'), prop)} AS t{index}"
                    for index, (phys, prop, _) in enumerate(target._key_specs)]
    selected = ", ".join([*rows.select_keys("c"), *target_projs])
    where_clause = rows.where(*target.key_not_null("p"), *extra_where, table="c")
    query = (f"SELECT {selected} FROM {child} AS c JOIN {target.reader} AS p ON "
             f"{' AND '.join(conditions)} WHERE {where_clause}")
    return "view", {"sources": [{"query": query}], "s": rows.subject(),
                    "po": [{"p": _iri(identifier),
                            "o": _iri(_template(child_iri(target.dataset["id"], "row"),
                                                [f"t{index}" for index in range(len(target.key))]))}]}


def _decision_spec(spec):
    if isinstance(spec, str):
        return spec, None
    if isinstance(spec, dict) and isinstance(spec.get("column"), str):
        if isinstance(spec.get("relationships"), list) and len(spec["relationships"]) == 2:
            return spec["column"], (spec["relationships"][0], spec["relationships"][1])
        left = spec.get("left") or spec.get("leftRelationship")
        right = spec.get("right") or spec.get("rightRelationship")
        if isinstance(left, str) and isinstance(right, str):
            return spec["column"], (left, right)
        return spec["column"], ()
    return None, ()


def _decision_mappings(alias, spec, definition, relationships, rows, context, notes):
    """A declared match-decision table: each row links the two rows it judges, by its decision."""
    column, pair_ids = _decision_spec(spec)
    by_name = {prop["name"]: prop for prop in definition.get("properties", ())}
    candidates = {}
    for relationship in sorted(relationships, key=lambda item: item["id"]):
        fields, target = _target(relationship, context)
        paths = relationship["source"]["paths"]
        if target is None or set(fields) != set(target.key) or not all(len(p) == 1 and "field" in p[0] for p in paths):
            continue
        scope = relationship.get("scope", "version_pair")
        if not _scope_allows_key_link(relationship["id"], scope, rows, target, context, []):
            continue
        pairs = dict(zip(fields, paths))
        candidates[relationship["id"]] = (target, [pairs[f][0]["field"] for f in target.key])
    if pair_ids is None:
        chosen = list(candidates.values()) if len(candidates) == 2 else []
    elif len(pair_ids) == 2 and pair_ids[0] != pair_ids[1] and all(rid in candidates for rid in pair_ids):
        chosen = [candidates[pair_ids[0]], candidates[pair_ids[1]]]
    else:
        chosen = []
    if not column or column not in by_name or len(chosen) != 2:
        notes.append(f"Match decisions are declared on {spec!r} but need a declared decision column and two valid "
                     "relationships to keyed rows, so they are not mapped.")
        return {}
    decision_phys = _phys_name(by_name[column])
    projections, not_nulls, side_iris = [], [], []
    for prefix, (target, src_columns) in zip(("s", "o"), chosen):
        aliases = []
        for index, (src_col, tgt_col) in enumerate(zip(src_columns, target.key)):
            (src_phys,), src_prop = _resolve_field(rows.properties, (src_col,))
            _, tgt_prop = _resolve_field(target.properties, (tgt_col,))
            cast_prop = src_prop if src_prop.get("logicalType") in AS_TEXT else tgt_prop
            raw_col = _sql_field((src_phys,))
            col_alias = f"{prefix}{index}"
            projections.append(f"{_text(raw_col, cast_prop)} AS {col_alias}")
            not_nulls.append(f"{raw_col} IS NOT NULL")
            aliases.append(col_alias)
        side_iris.append(_iri(_template(child_iri(target.dataset["id"], "row"), aliases)))
    select_list = ", ".join(projections)
    non_null_clause = " AND ".join(dict.fromkeys(not_nulls))
    return {f"{alias}#{decision}": {
        "sources": [{"query": (f"SELECT {select_list} FROM {rows.reader} "
                               f"WHERE {_sql_name(decision_phys)} = {_sql_text(decision)} AND {non_null_clause}")}],
        "s": side_iris[0], "po": [{"p": _iri(predicate), "o": side_iris[1]}],
    } for decision, predicate in MATCH_PREDICATES.items()}


def _yaml_key(key):
    text = str(key)
    return text if SAFE_YAML_KEY.match(text) else json.dumps(text, ensure_ascii=False)


def _yaml(value, depth=0):
    """Block YAML whose scalars, sequences and term maps are JSON, which YAML 1.2 reads unchanged."""
    pad, lines = "  " * depth, []
    for raw_key, item in value.items():
        key = _yaml_key(raw_key)
        if isinstance(item, dict) and ("value" in item or not item):
            lines.append(f"{pad}{key}: {json.dumps(item, ensure_ascii=False)}")
        elif isinstance(item, dict):
            lines += [f"{pad}{key}:", _yaml(item, depth + 1)]
        elif isinstance(item, list):
            lines.append(f"{pad}{key}:")
            for entry in item:
                lines.append(f"{pad}  - " + (_yaml(entry, depth + 2).lstrip() if isinstance(entry, dict)
                                             else json.dumps(entry, ensure_ascii=False)))
        else:
            lines.append(f"{pad}{key}: {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines)


def rml_documents(catalog):
    """YAML files named rml/<alias>.yarrrml.yml, each headed by what it reads and what it leaves out, and the
    export's mapping limits."""
    datasets = {item["alias"]: item for item in catalog["datasets"]}
    documents, bound, withheld_limits = _rml_plan(catalog)
    files, templates = {}, 0
    for alias, (document, notes) in documents.items():
        graph = bound[alias][0] if alias in bound else None
        templates += graph is None
        header = [f"# YARRRML for {datasets[alias]['id']} from DDK catalog {catalog['id']}.",
                  f"# Rows of exact version {graph} land in that named graph; every source reads its file."
                  if graph else "# A template: it names no exact version, so rows land in the default graph.",
                  "# DuckDB views (`query` sources, run by Morph-KGC) project non-null fields, array items and joins.",
                  f"# Set Morph-KGC `na_values = {NA_SENTINEL}` so literal \"None\" and \"\" strings survive intact.",
                  *(f"# {note}" for note in notes)]
        files[f"rml/{alias.strip('/')}.yarrrml.yml"] = ("\n".join(header) + "\n" + _yaml(document) + "\n").encode("utf-8")
    limits = set(withheld_limits)
    if templates:
        limits.add(f"{templates} of {len(files)} RML documents are templates bound to no exact version; each "
                   "document's header says why.")
    return files, limits


# Native DataFusion + Rust row-quad compiler & materializer.
# Eliminates Python Pandas (`Morph-KGC`) and in-memory Python `rdflib` loops over scalable row data while preserving
# identical W3C RDF / N-Quads semantics to `rml_mappings(catalog)` (`iri_encode`, `nquad_escape`, typed literals,
# named version graphs, nested structs, scalar/object arrays, intra- & cross-catalog links, and `matchDecisions`).

QUAD_COLUMNS = ("subject", "predicate", "object_kind", "object_value", "object_datatype", "graph", "nquad")
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema#"


def _df_field(path, table=None):
    expr = (f"{table}." if table else "") + _sql_name(path[0])
    for part in path[1:]:
        expr = f"get_field({expr}, {_sql_text(part)})"
    return expr


def _df_text(expression, prop):
    lt = prop.get("logicalType")
    if lt == "boolean":
        return f"CASE WHEN {expression} THEN 'true' ELSE 'false' END"
    if lt == "timestamp":
        return f"regexp_replace(CAST({expression} AS VARCHAR), '^([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}) ', '$1T')"
    return f"CAST({expression} AS VARCHAR)"


def _expand_datatype_iri(datatype):
    if not datatype:
        return None
    if datatype.startswith("xsd:"):
        return XSD_NAMESPACE + datatype[4:]
    return datatype


def _df_iri_expr(base, col_exprs):
    if not col_exprs:
        return _sql_text(base)
    sep = ":" if base.startswith("urn:") else "/"
    parts = [_sql_text(base)]
    for ce in col_exprs:
        parts.extend([_sql_text(sep), f"iri_encode({ce})"])
    return f"concat({', '.join(parts)})"


def _df_concept_iri_expr(template_str, val_expr):
    chunks = template_str.split("{value}")
    if len(chunks) == 1:
        return _sql_text(template_str)
    parts = []
    for idx, chunk in enumerate(chunks):
        if chunk:
            parts.append(_sql_text(chunk))
        if idx + 1 < len(chunks):
            parts.append(f"iri_encode({val_expr})")
    return parts[0] if len(parts) == 1 else f"concat({', '.join(parts)})"


def _df_blank_expr(scope, col_exprs):
    label = "_:b" + sha256(scope.encode()).hexdigest()[:20]
    parts = [_sql_text(label)]
    for ce in col_exprs:
        parts.extend(["'_'", f"regexp_replace({ce}, '[^A-Za-z0-9_.-]', '_')"])
    return f"concat({', '.join(parts)})"


def _quad_branch(
    *,
    subj_expr,
    subj_is_bnode,
    pred_iri,
    obj_kind,
    obj_expr,
    obj_datatype_iri=None,
    graph_iri=None,
    from_where_sql="",
):
    subj_sql = f"CAST({subj_expr} AS VARCHAR)"
    pred_sql = f"CAST({_sql_text(pred_iri)} AS VARCHAR)"
    kind_sql = f"CAST({_sql_text(obj_kind)} AS VARCHAR)"
    val_sql = f"CAST({obj_expr} AS VARCHAR)"
    dt_sql = f"CAST({_sql_text(obj_datatype_iri)} AS VARCHAR)" if obj_datatype_iri else "CAST(NULL AS VARCHAR)"
    graph_sql = f"CAST({_sql_text(graph_iri)} AS VARCHAR)" if graph_iri else "CAST(NULL AS VARCHAR)"

    subj_nt = subj_expr if subj_is_bnode else f"concat('<', {subj_expr}, '>')"
    pred_nt = _sql_text(f"<{pred_iri}>")
    if obj_kind in {"iri"}:
        obj_nt = f"concat('<', {obj_expr}, '>')"
    elif obj_kind == "bnode":
        obj_nt = obj_expr
    elif obj_datatype_iri:
        obj_nt = f"concat('\"', nquad_escape({obj_expr}), {_sql_text(f'\"^^<{obj_datatype_iri}>')})"
    else:
        obj_nt = f"concat('\"', nquad_escape({obj_expr}), '\"')"
    tail_nt = _sql_text(f" <{graph_iri}> .") if graph_iri else _sql_text(" .")
    nquad_sql = f"CAST(concat({subj_nt}, ' ', {pred_nt}, ' ', {obj_nt}, {tail_nt}) AS VARCHAR)"

    tail = f" {from_where_sql}" if from_where_sql else ""
    return (
        f"SELECT {subj_sql} AS subject, {pred_sql} AS predicate, {kind_sql} AS object_kind, "
        f"{val_sql} AS object_value, {dt_sql} AS object_datatype, {graph_sql} AS graph, "
        f"{nquad_sql} AS nquad{tail}"
    )


class _DfRows:
    """DataFusion SQL row reader & subject builder for one bound Parquet dataset."""

    def __init__(self, dataset, key, parquet_path, version, chosen_version, properties, table_ident, reader_ident):
        self.dataset = dataset
        self.key = key
        self.path = parquet_path
        self.version = version
        self.chosen_version = chosen_version
        self.properties = tuple(properties)
        self.table_ident = table_ident
        self.reader_ident = reader_ident
        self.columns = key or [ROW]
        self.key_aliases = [f"k{index}" for index in range(len(self.columns))]
        specs = []
        for index, column in enumerate(self.columns):
            if key:
                (phys,), prop = _resolve_field(self.properties, (column,))
            else:
                phys, prop = ROW, {"logicalType": "integer"}
            specs.append((phys, prop, f"k{index}"))
        self._key_specs = tuple(specs)

    def select_keys(self, table=None):
        return [f"{_df_text(_df_field((phys,), table), prop)} AS {alias}" for phys, prop, alias in self._key_specs]

    def key_exprs(self, table=None):
        return [_df_text(_df_field((phys,), table), prop) for phys, prop, _ in self._key_specs]

    def projected_keys(self):
        return ", ".join(self.key_aliases)

    def key_not_null(self, table=None):
        return [f"{_df_field((phys,), table)} IS NOT NULL" for phys, _, _ in self._key_specs]

    def where(self, *extra, table=None):
        clauses = list(dict.fromkeys([*self.key_not_null(table), *extra]))
        return " AND ".join(clauses)

    def subject_expr(self, key_col_exprs=None):
        exprs = key_col_exprs if key_col_exprs is not None else self.key_aliases
        if self.key:
            return _df_iri_expr(child_iri(self.dataset["id"], "row"), exprs), False
        return _df_blank_expr(f"{self.dataset['id']}\n{self.version or 'template'}", exprs), True


def _catalog_parquet_digests(catalog):
    """Extract already-verified SHA-256 digests from local file version references so inputs are not re-hashed."""
    from pathlib import Path
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    known = {}
    for ver in catalog.get("versions", ()):
        ref = ver.get("reference")
        if not isinstance(ref, dict) or ref.get("scheme") != "urn:ddk:version:local-file-sha256":
            continue
        val = ref.get("value")
        if not isinstance(val, dict):
            continue
        loc, digest = val.get("location"), val.get("sha256")
        if not isinstance(loc, str) or not isinstance(digest, str) or len(digest) != 64:
            continue
        try:
            raw_path = url2pathname(urlparse(loc).path) if loc.startswith("file://") else loc
            known[str(Path(raw_path).resolve())] = digest
        except OSError:
            continue
    return known


def compile_graph_quads_job(
    catalog,
    *,
    scratch_dir,
    output_parquet_path,
    datasets=None,
    file_overrides=None,
    job_id=None,
):
    """Compile an admitted catalog's row-level RDF graph into a pure DataFusion DocSpec JobSpec.

    Every referenced Parquet dataset becomes a ``JobInput``; multi-consumer intermediate tables (keyless row
    numbering and object-array unnesting) materialize once as ``SqlStep``s; equality joins place the keyed
    target dataset on the LEFT build side; and ``iri_encode`` / ``nquad_escape`` scalar UDFs build deterministic
    W3C N-Quads columns exported to ``output_parquet_path``.
    """
    from pathlib import Path

    public = catalog.get("audience") == "public"
    assembly_ext = catalog.get("extensions", {}).get(DETAILS)
    definitions = (assembly_ext or {}).get("datasetDefinitions", {})
    if assembly_ext is None or (not definitions and not public):
        raise CatalogError(
            "ADAPTER-CAPABILITY-MISSING",
            "Graph quad compilation needs the catalog's dataset definitions.",
            status="not_run",
        )

    overrides = {alias: str(Path(p).resolve()) for alias, p in (file_overrides or {}).items()}
    all_datasets = {item["alias"]: item for item in catalog["datasets"]}
    selected_aliases = None
    if datasets is not None:
        selected_aliases = set(datasets)
        unknown = sorted(selected_aliases - set(all_datasets))
        if unknown:
            raise CatalogError(
                "CATALOG-DATASET-UNKNOWN",
                f"Unknown dataset alias(es) for quad compilation: {', '.join(unknown)}.",
            )

    keys = _row_keys(catalog)
    bound, unbound, chosen = _bindings(catalog)
    disclosed_paths = (assembly_ext or {}).get("disclosedDefinitionPaths", {})

    mappable = {}
    notes = defaultdict(list)
    for alias, dataset in sorted(all_datasets.items()):
        if public:
            allowed = disclosed_paths.get(alias, ())
            key_fields = keys.get(alias)
            if alias not in definitions or not key_fields or not all(
                [{"field": name}] in allowed for name in key_fields
            ):
                if selected_aliases is None or alias in selected_aliases:
                    notes[alias].append(
                        f"{dataset['id']} is not mapped in public quads: its row key or field definitions are withheld."
                    )
                continue
        mappable[alias] = dataset

    df_rows = {}
    local_unbound_targets = {}
    for ds_idx, (alias, dataset) in enumerate(sorted(mappable.items())):
        is_selected = selected_aliases is None or alias in selected_aliases
        if alias in overrides:
            version = bound[alias][0] if alias in bound else chosen.get(alias)
            parquet_path = overrides[alias]
        elif alias in bound:
            version, parquet_path = bound[alias]
        else:
            if is_selected:
                notes[alias].append(f"Skipped unbound dataset {alias!r}: {unbound.get(alias, 'no bound file')}.")
            if keys.get(alias):
                target_stub = _PeerRows(dataset, keys[alias], definitions.get(alias, {}).get("properties", ()))
                target_stub.chosen_version = chosen.get(alias)
                target_stub.is_peer = False
                local_unbound_targets[alias] = target_stub
            continue

        if not parquet_path.lower().endswith(".parquet"):
            if is_selected:
                notes[alias].append(
                    f"Skipped {alias!r}: native DataFusion quad materialization requires Parquet inputs (got {parquet_path!r})."
                )
            if keys.get(alias):
                target_stub = _PeerRows(dataset, keys[alias], definitions.get(alias, {}).get("properties", ()))
                target_stub.chosen_version = chosen.get(alias) or version
                target_stub.is_peer = False
                local_unbound_targets[alias] = target_stub
            continue

        resolved_path = str(Path(parquet_path).resolve())
        table_ident = f"ds_{ds_idx}"
        key_cols = keys.get(alias)
        reader_ident = table_ident if key_cols else f"{table_ident}_numbered"
        df_rows[alias] = _DfRows(
            dataset,
            key_cols,
            resolved_path,
            version,
            chosen.get(alias) or version,
            definitions.get(alias, {}).get("properties", ()),
            table_ident,
            reader_ident,
        )

    peer_rows = {}
    for peer_alias, peer_info in sorted(_peer_catalogs(catalog).items()):
        peer_keys = _row_keys({"identities": peer_info.get("identities", ())})
        peer_defs = peer_info.get("datasetDefinitions", {})
        peer_disclosed = peer_info.get("disclosedDefinitionPaths", {})
        for peer_ds, peer_ds_id in sorted(peer_info.get("datasets", {}).items()):
            key_fields = peer_keys.get(peer_ds)
            if not key_fields:
                continue
            if peer_info.get("audience") == "public" and peer_ds in peer_disclosed:
                if not all([{"field": name}] in peer_disclosed[peer_ds] for name in key_fields):
                    continue
            peer_rows[(peer_alias, peer_ds)] = _PeerRows(
                {"id": peer_ds_id, "alias": peer_ds},
                key_fields,
                peer_defs.get(peer_ds, {}).get("properties", ()),
            )

    all_local_rows = {**local_unbound_targets, **df_rows}
    context = _Context(
        all_local_rows,
        peer_rows,
        _concepts(catalog),
        _concept_templates(catalog),
        _release_sharing(catalog),
    )
    outgoing = defaultdict(list)
    for relationship in catalog["relationships"]:
        source_alias = relationship["source"]["dataset"]
        if source_alias not in df_rows:
            continue
        if selected_aliases is not None and source_alias not in selected_aliases:
            continue
        if public:
            if not all(path in disclosed_paths.get(source_alias, ()) for path in relationship["source"]["paths"]):
                continue
            if "catalog" in relationship["target"]:
                peer_target = (relationship["target"]["catalog"], relationship["target"].get("dataset"))
                if peer_target not in peer_rows:
                    continue
            else:
                target_alias = relationship["target"].get("dataset")
                if target_alias is not None and (
                    target_alias not in mappable
                    or not all(path in disclosed_paths.get(target_alias, ()) for path in relationship["target"]["paths"])
                ):
                    continue
        outgoing[source_alias].append(relationship)

    used_aliases = set()
    derived_steps = []
    branches = []
    step_counter = 0

    active_rows = [
        (alias, rows)
        for alias, rows in sorted(df_rows.items())
        if selected_aliases is None or alias in selected_aliases
    ]
    for alias, rows in active_rows:
        used_aliases.add(alias)
        dataset = rows.dataset
        dataset_id = dataset["id"]
        definition = definitions.get(alias, {})
        graph_iri = rows.version
        ds_notes = notes[alias]
        ds_disclosed = disclosed_paths.get(alias, ())

        scalars, arrays = [], []
        for logical_path, phys_path, prop in _walk(definition.get("properties", ())):
            kind = prop.get("logicalType")
            (arrays if kind == "array" else scalars).append((logical_path, phys_path, prop))
            if kind == "object":
                ds_notes.append(f"{_column(logical_path)} is an object without declared fields, so it is not mapped.")

        # 1. Scalar leaves
        for logical_path, phys_path, prop in scalars:
            if prop.get("logicalType") == "object":
                continue
            raw_expr = _df_field(phys_path)
            val_expr = _df_text(raw_expr, prop)
            subj_expr, subj_bnode = rows.subject_expr(rows.key_exprs())
            from_where = f"FROM {rows.reader_ident} WHERE {rows.where(f'{raw_expr} IS NOT NULL')}"
            dt_iri = _expand_datatype_iri(_datatype(prop))
            branches.append(
                _quad_branch(
                    subj_expr=subj_expr,
                    subj_is_bnode=subj_bnode,
                    pred_iri=field_predicate(dataset_id, logical_path),
                    obj_kind="literal",
                    obj_expr=val_expr,
                    obj_datatype_iri=dt_iri,
                    graph_iri=graph_iri,
                    from_where_sql=from_where,
                )
            )
            if (alias, logical_path) in context.templates:
                branches.append(
                    _quad_branch(
                        subj_expr=subj_expr,
                        subj_is_bnode=subj_bnode,
                        pred_iri=SEE_ALSO,
                        obj_kind="iri",
                        obj_expr=_df_concept_iri_expr(context.templates[(alias, logical_path)], val_expr),
                        graph_iri=graph_iri,
                        from_where_sql=from_where,
                    )
                )

        # 2. Method attribution column
        if dataset.get("methodColumn") and (not public or [{"field": dataset["methodColumn"]}] in ds_disclosed):
            method_prop = next(
                (prop for prop in definition.get("properties", ()) if prop["name"] == dataset["methodColumn"]),
                None,
            )
            origins, reason = method_origins(method_prop) if method_prop is not None else ({}, "missing")
            if reason is None and origins:
                raw_expr = _df_field((_phys_name(method_prop),))
                val_expr = _df_text(raw_expr, method_prop)
                subj_expr, subj_bnode = rows.subject_expr(rows.key_exprs())
                from_where = f"FROM {rows.reader_ident} WHERE {rows.where(f'{raw_expr} IS NOT NULL')}"
                branches.append(
                    _quad_branch(
                        subj_expr=subj_expr,
                        subj_is_bnode=subj_bnode,
                        pred_iri=ATTRIBUTED,
                        obj_kind="iri",
                        obj_expr=_df_iri_expr(child_iri(dataset_id, "agent"), [val_expr]),
                        graph_iri=graph_iri,
                        from_where_sql=from_where,
                    )
                )

        # 3. Relationships (direct key FKs, peer FKs, array links, and non-key joins)
        each_links = defaultdict(list)
        each_object_links = defaultdict(list)
        for relationship in outgoing[alias]:
            rel_id = relationship["id"]
            if relationship.get("match") == "project_rule":
                ds_notes.append(f"{rel_id} is not mapped: a project rule, not equal values, decides its matches.")
                continue
            if "dataset" not in relationship["target"]:
                ds_notes.append(f"{rel_id} is not mapped: its target is external.")
                continue
            nulls = relationship.get("nulls", "skip")
            if nulls == "unknown":
                ds_notes.append(f"{rel_id} is not mapped: its null handling is unknown.")
                continue
            fields, target = _target(relationship, context)
            if target is None:
                ds_notes.append(f"{rel_id} is not mapped: its target has no top-level key to name its rows.")
                continue
            scope = relationship.get("scope", "version_pair")
            source_paths = relationship["source"]["paths"]
            flat = all(len(path) == 1 and "field" in path[0] for path in source_paths)
            pairs = dict(zip(fields, source_paths))

            if nulls != "match" and flat and set(fields) == set(target.key):
                if not _scope_allows_key_link(rel_id, scope, rows, target, context, ds_notes):
                    continue
                tgt_exprs, not_nulls = [], []
                for field in target.key:
                    src_logical = pairs[field][0]["field"]
                    (src_phys,), src_prop = _resolve_field(rows.properties, (src_logical,))
                    _, tgt_prop = _resolve_field(target.properties, (field,))
                    cast_prop = src_prop if src_prop.get("logicalType") in AS_TEXT else tgt_prop
                    raw_fk = _df_field((src_phys,))
                    tgt_exprs.append(_df_text(raw_fk, cast_prop))
                    not_nulls.append(f"{raw_fk} IS NOT NULL")
                subj_expr, subj_bnode = rows.subject_expr(rows.key_exprs())
                from_where = f"FROM {rows.reader_ident} WHERE {rows.where(*not_nulls)}"
                branches.append(
                    _quad_branch(
                        subj_expr=subj_expr,
                        subj_is_bnode=subj_bnode,
                        pred_iri=rel_id,
                        obj_kind="iri",
                        obj_expr=_df_iri_expr(child_iri(target.dataset["id"], "row"), tgt_exprs),
                        graph_iri=graph_iri,
                        from_where_sql=from_where,
                    )
                )
                continue

            eaches = [path for path in source_paths if path[-1].get("each")]
            if (
                nulls != "match"
                and len(source_paths) == 1
                and len(eaches) == 1
                and set(fields) == set(target.key)
                and all("field" in step for step in eaches[0][:-1])
            ):
                if not _scope_allows_key_link(rel_id, scope, rows, target, context, ds_notes):
                    continue
                arr_path = tuple(step["field"] for step in eaches[0][:-1])
                each_links[arr_path].append((rel_id, target.dataset["id"]))
                continue

            object_array = _object_array_paths(source_paths)
            if (
                nulls != "match"
                and object_array is not None
                and len(fields) == len(source_paths)
                and set(fields) == set(target.key)
            ):
                if not _scope_allows_key_link(rel_id, scope, rows, target, context, ds_notes):
                    continue
                item_fields = [
                    (field, tuple(step["field"] for step in pairs[field][len(object_array) + 1 :]))
                    for field in target.key
                ]
                each_object_links[object_array].append({"id": rel_id, "item_fields": item_fields, "target": target})
                continue

            if len(eaches) > 1 or any(
                not all("field" in step for step in (path[:-1] if path in eaches else path))
                for path in source_paths
            ):
                ds_notes.append(f"{rel_id} is not mapped: its source path is not fields with at most one array.")
                continue
            if getattr(target, "is_peer", False):
                ds_notes.append(
                    f"{rel_id} is not mapped: cross-catalog quad links project foreign keys to peer primary keys without scanning peer files."
                )
                continue
            if not (rows.version and target.version) or not getattr(target, "reader_ident", None):
                ds_notes.append(f"{rel_id} is not mapped: its join reads both exact versions, and one side is unbound.")
                continue
            if scope not in {"same_release", "version_pair"}:
                ds_notes.append(f"{rel_id} is not mapped: its {scope} scope needs a project-specific resolver.")
                continue
            if scope == "same_release" and not context.same_release(rows.version, target.version):
                ds_notes.append(
                    f"{rel_id} is not mapped: its scope is the same release, and {rows.version} and {target.version} share none."
                )
                continue
            used_aliases.add(target.dataset["alias"])

            child_sql = rows.reader_ident
            item_prop = {}
            if eaches:
                arr_logical = tuple(step["field"] for step in eaches[0][:-1])
                arr_phys, arr_prop = _resolve_field(rows.properties, arr_logical)
                item_prop = arr_prop.get("items") if isinstance(arr_prop.get("items"), dict) else {}
                unnested = _df_text(f"UNNEST({_df_field(arr_phys)})", item_prop)
                child_sql = (
                    f"(SELECT *, {unnested} AS __ddk_each FROM {rows.reader_ident} "
                    f"WHERE {rows.where(f'{_df_field(arr_phys)} IS NOT NULL')})"
                )
            operator = "IS NOT DISTINCT FROM" if nulls == "match" else "="
            conditions, extra_where = [], []
            for field, path in pairs.items():
                (tgt_phys,), tgt_prop = _resolve_field(target.properties, (field,))
                if path in eaches:
                    right_expr = 'c."__ddk_each"'
                    cast_prop = item_prop if item_prop.get("logicalType") in AS_TEXT else tgt_prop
                    left_expr = _df_text(_df_field((tgt_phys,), "p"), cast_prop)
                    if nulls != "match":
                        extra_where.append('c."__ddk_each" IS NOT NULL')
                else:
                    src_logical = tuple(step["field"] for step in path)
                    src_phys, src_prop = _resolve_field(rows.properties, src_logical)
                    need_text = src_prop.get("logicalType") in AS_TEXT or tgt_prop.get("logicalType") in AS_TEXT
                    cast_prop = {"logicalType": "integer"} if need_text else {}
                    left_expr = _df_text(_df_field((tgt_phys,), "p"), cast_prop)
                    right_expr = _df_text(_df_field(src_phys, "c"), cast_prop)
                conditions.append(f"{left_expr} {operator} {right_expr}")
            subj_expr, subj_bnode = rows.subject_expr(rows.key_exprs("c"))
            tgt_key_exprs = target.key_exprs("p")
            where_clause = rows.where(*target.key_not_null("p"), *extra_where, table="c")
            # Build hash table on LEFT (`target.reader_ident AS p`) and probe with `child_sql AS c`
            from_where = (
                f"FROM {target.reader_ident} AS p INNER JOIN {child_sql} AS c "
                f"ON {' AND '.join(conditions)} WHERE {where_clause}"
            )
            branches.append(
                _quad_branch(
                    subj_expr=subj_expr,
                    subj_is_bnode=subj_bnode,
                    pred_iri=rel_id,
                    obj_kind="iri",
                    obj_expr=_df_iri_expr(child_iri(target.dataset["id"], "row"), tgt_key_exprs),
                    graph_iri=graph_iri,
                    from_where_sql=from_where,
                )
            )

        # 4. Scalar & object arrays
        for logical_path, phys_path, prop in arrays:
            label, key = _column(logical_path), _path_key(logical_path)
            links = each_links.pop(logical_path, [])
            object_links = each_object_links.pop(logical_path, [])
            if not isinstance(prop.get("items"), dict):
                ds_notes.append(f"{label} is not mapped: its array element definition is absent or withheld.")
                continue
            items = prop["items"]
            raw_arr = _df_field(phys_path)
            if items.get("logicalType") != "object":
                if items.get("logicalType") == "array":
                    ds_notes.append(f"{label} is not mapped: arrays of arrays need a view of their own.")
                    continue
                if object_links:
                    ds_notes.append(f"Links through {label} are not mapped: its items are not objects.")
                unnested = _df_text(f"UNNEST({raw_arr})", items)
                step_counter += 1
                arr_step = f"arr_{step_counter}"
                inner_sql = (
                    f"SELECT {rows.projected_keys()}, v0 FROM ("
                    f"SELECT {', '.join([*rows.select_keys(), f'{unnested} AS v0'])} "
                    f"FROM {rows.reader_ident} WHERE {rows.where(f'{raw_arr} IS NOT NULL')}"
                    ") AS _u WHERE v0 IS NOT NULL"
                )
                need_materialize = bool(links) or ((alias, logical_path) in context.templates)
                derived_steps.append({"name": arr_step, "sql": inner_sql, "materialize": need_materialize})
                subj_expr, subj_bnode = rows.subject_expr(rows.key_aliases)
                from_where = f"FROM {arr_step}"
                branches.append(
                    _quad_branch(
                        subj_expr=subj_expr,
                        subj_is_bnode=subj_bnode,
                        pred_iri=field_predicate(dataset_id, logical_path),
                        obj_kind="literal",
                        obj_expr="v0",
                        obj_datatype_iri=_expand_datatype_iri(_datatype(items)),
                        graph_iri=graph_iri,
                        from_where_sql=from_where,
                    )
                )
                for link_pred, tgt_ds_id in links:
                    branches.append(
                        _quad_branch(
                            subj_expr=subj_expr,
                            subj_is_bnode=subj_bnode,
                            pred_iri=link_pred,
                            obj_kind="iri",
                            obj_expr=_df_iri_expr(child_iri(tgt_ds_id, "row"), ["v0"]),
                            graph_iri=graph_iri,
                            from_where_sql=from_where,
                        )
                    )
                if (alias, logical_path) in context.templates:
                    branches.append(
                        _quad_branch(
                            subj_expr=subj_expr,
                            subj_is_bnode=subj_bnode,
                            pred_iri=SEE_ALSO,
                            obj_kind="iri",
                            obj_expr=_df_concept_iri_expr(context.templates[(alias, logical_path)], "v0"),
                            graph_iri=graph_iri,
                            from_where_sql=from_where,
                        )
                    )
                continue

            # Object array: materialize unnested 1-based indexed elements once
            leaves = []
            for leaf_logical, leaf_phys, child in _walk(items.get("properties", ())):
                if child.get("logicalType") in {"array", "object"}:
                    ds_notes.append(f"{label}.{_column(leaf_logical)} is not mapped: it nests inside an array element.")
                else:
                    leaves.append((leaf_logical, leaf_phys, child))
            if links:
                ds_notes.append(f"Links through {label} are not mapped: its items are objects.")
            step_counter += 1
            obj_step = f"obj_arr_{step_counter}"
            obj_sql = (
                f"SELECT {rows.projected_keys()}, CAST(i0 AS VARCHAR) AS i0_str, "
                "array_element(__ddk_arr, i0) AS __ddk_item FROM ("
                f"SELECT {', '.join([*rows.select_keys(), f'{raw_arr} AS __ddk_arr', f'UNNEST(generate_series(CAST(1 AS BIGINT), CAST(array_length({raw_arr}) AS BIGINT))) AS i0'])} "
                f"FROM {rows.reader_ident} "
                f"WHERE {rows.where(f'{raw_arr} IS NOT NULL', f'COALESCE(array_length({raw_arr}), 0) > 0')}"
                ") AS _idx WHERE array_element(__ddk_arr, i0) IS NOT NULL"
            )
            derived_steps.append({"name": obj_step, "sql": obj_sql, "materialize": True})

            parent_subj_expr, parent_bnode = rows.subject_expr(rows.key_aliases)
            if rows.key:
                sep = ":" if dataset_id.startswith("urn:") else "/"
                elem_expr = f"concat({parent_subj_expr}, {_sql_text(sep + key + sep)}, i0_str)"
                elem_bnode = False
            else:
                elem_expr = _df_blank_expr(
                    f"{dataset_id}\n{rows.version or 'template'}\n{key}",
                    [*rows.key_aliases, "i0_str"],
                )
                elem_bnode = True

            branches.append(
                _quad_branch(
                    subj_expr=parent_subj_expr,
                    subj_is_bnode=parent_bnode,
                    pred_iri=field_predicate(dataset_id, logical_path),
                    obj_kind="bnode" if elem_bnode else "iri",
                    obj_expr=elem_expr,
                    graph_iri=graph_iri,
                    from_where_sql=f"FROM {obj_step}",
                )
            )
            for leaf_logical, leaf_phys, child in leaves:
                leaf_raw = _df_field(("__ddk_item", *leaf_phys))
                leaf_val = _df_text(leaf_raw, child)
                full_path = (*logical_path, *leaf_logical)
                from_where = f"FROM {obj_step} WHERE {leaf_raw} IS NOT NULL"
                branches.append(
                    _quad_branch(
                        subj_expr=elem_expr,
                        subj_is_bnode=elem_bnode,
                        pred_iri=field_predicate(dataset_id, full_path),
                        obj_kind="literal",
                        obj_expr=leaf_val,
                        obj_datatype_iri=_expand_datatype_iri(_datatype(child)),
                        graph_iri=graph_iri,
                        from_where_sql=from_where,
                    )
                )
                if (alias, full_path) in context.templates:
                    branches.append(
                        _quad_branch(
                            subj_expr=elem_expr,
                            subj_is_bnode=elem_bnode,
                            pred_iri=SEE_ALSO,
                            obj_kind="iri",
                            obj_expr=_df_concept_iri_expr(context.templates[(alias, full_path)], leaf_val),
                            graph_iri=graph_iri,
                            from_where_sql=from_where,
                        )
                    )
            item_props = items.get("properties", ())
            for obj_link in object_links:
                target = obj_link["target"]
                tgt_exprs, not_nulls = [], []
                for tgt_field, item_logical in obj_link["item_fields"]:
                    item_phys, src_prop = _resolve_field(item_props, item_logical)
                    _, tgt_prop = _resolve_field(target.properties, (tgt_field,))
                    cast_prop = src_prop if src_prop.get("logicalType") in AS_TEXT else tgt_prop
                    raw_fk = _df_field(("__ddk_item", *item_phys))
                    tgt_exprs.append(_df_text(raw_fk, cast_prop))
                    not_nulls.append(f"{raw_fk} IS NOT NULL")
                from_where = f"FROM {obj_step} WHERE {' AND '.join(dict.fromkeys(not_nulls))}"
                branches.append(
                    _quad_branch(
                        subj_expr=elem_expr,
                        subj_is_bnode=elem_bnode,
                        pred_iri=obj_link["id"],
                        obj_kind="iri",
                        obj_expr=_df_iri_expr(child_iri(target.dataset["id"], "row"), tgt_exprs),
                        graph_iri=graph_iri,
                        from_where_sql=from_where,
                    )
                )

        for path in dict.fromkeys([*each_links, *each_object_links]):
            ds_notes.append(f"Links through {_column(path)} are not mapped: it is not a declared array field.")

        # 5. Concept subPropertyOf statements
        for (owner, path), concept in sorted(context.concepts.items()):
            if owner == alias:
                branches.append(
                    _quad_branch(
                        subj_expr=_sql_text(field_predicate(dataset_id, path)),
                        subj_is_bnode=False,
                        pred_iri=SUBPROPERTY,
                        obj_kind="iri",
                        obj_expr=_sql_text(concept),
                        graph_iri=graph_iri,
                    )
                )

        # 6. Match decisions (`skos:exactMatch`, `skos:closeMatch`, `ddkv:noMatch`)
        decisions = next(iter(ddk_annotations(definition, "matchDecisions")), None)
        if decisions and not public:
            col_name, pair_ids = _decision_spec(decisions)
            by_name = {prop["name"]: prop for prop in definition.get("properties", ())}
            candidates = {}
            for relationship in sorted(outgoing[alias], key=lambda item: item["id"]):
                fields, target = _target(relationship, context)
                paths = relationship["source"]["paths"]
                if (
                    target is None
                    or set(fields) != set(target.key)
                    or not all(len(p) == 1 and "field" in p[0] for p in paths)
                ):
                    continue
                scope = relationship.get("scope", "version_pair")
                if not _scope_allows_key_link(relationship["id"], scope, rows, target, context, []):
                    continue
                pairs = dict(zip(fields, paths))
                candidates[relationship["id"]] = (target, [pairs[f][0]["field"] for f in target.key])
            if pair_ids is None:
                chosen_pair = list(candidates.values()) if len(candidates) == 2 else []
            elif len(pair_ids) == 2 and pair_ids[0] != pair_ids[1] and all(rid in candidates for rid in pair_ids):
                chosen_pair = [candidates[pair_ids[0]], candidates[pair_ids[1]]]
            else:
                chosen_pair = []
            if not col_name or col_name not in by_name or len(chosen_pair) != 2:
                ds_notes.append(
                    f"Match decisions are declared on {decisions!r} but need a declared decision column and two valid "
                    "relationships to keyed rows, so they are not mapped."
                )
            else:
                decision_phys = _phys_name(by_name[col_name])
                not_nulls = []
                side_exprs = []
                for target, src_columns in chosen_pair:
                    col_exprs = []
                    for src_col, tgt_col in zip(src_columns, target.key):
                        (src_phys,), src_prop = _resolve_field(rows.properties, (src_col,))
                        _, tgt_prop = _resolve_field(target.properties, (tgt_col,))
                        cast_prop = src_prop if src_prop.get("logicalType") in AS_TEXT else tgt_prop
                        raw_col = _df_field((src_phys,))
                        col_exprs.append(_df_text(raw_col, cast_prop))
                        not_nulls.append(f"{raw_col} IS NOT NULL")
                    side_exprs.append(_df_iri_expr(child_iri(target.dataset["id"], "row"), col_exprs))
                nn_clause = " AND ".join(dict.fromkeys(not_nulls))
                for decision_val, predicate_iri in MATCH_PREDICATES.items():
                    from_where = (
                        f"FROM {rows.reader_ident} "
                        f"WHERE {_sql_name(decision_phys)} = {_sql_text(decision_val)} AND {nn_clause}"
                    )
                    branches.append(
                        _quad_branch(
                            subj_expr=side_exprs[0],
                            subj_is_bnode=False,
                            pred_iri=predicate_iri,
                            obj_kind="iri",
                            obj_expr=side_exprs[1],
                            graph_iri=graph_iri,
                            from_where_sql=from_where,
                        )
                    )

    inputs = []
    numbered_steps = []
    bound_versions = {}
    for alias in sorted(used_aliases):
        rows = df_rows[alias]
        inputs.append({"kind": "parquet", "name": rows.table_ident, "path": rows.path})
        if not rows.key:
            numbered_steps.append({
                "name": rows.reader_ident,
                "sql": f"SELECT ROW_NUMBER() OVER () AS {_sql_name(ROW)}, * FROM {rows.table_ident}",
                "materialize": True,
            })
        bound_versions[alias] = rows.version

    steps = [*numbered_steps, *derived_steps]
    if branches:
        steps.append({"name": "raw_quads", "sql": " UNION ALL ".join(branches), "materialize": False})
        steps.append({
            "name": "distinct_quads",
            "sql": f"SELECT DISTINCT {', '.join(QUAD_COLUMNS)} FROM raw_quads",
            "materialize": False,
        })
    else:
        steps.append({
            "name": "distinct_quads",
            "sql": (
                "SELECT CAST('' AS VARCHAR) AS subject, CAST('' AS VARCHAR) AS predicate, "
                "CAST('' AS VARCHAR) AS object_kind, CAST('' AS VARCHAR) AS object_value, "
                "CAST(NULL AS VARCHAR) AS object_datatype, CAST(NULL AS VARCHAR) AS graph, "
                "CAST('' AS VARCHAR) AS nquad WHERE FALSE"
            ),
            "materialize": False,
        })

    out_path = str(Path(output_parquet_path).resolve())
    job_spec = {
        "scratch": str(Path(scratch_dir).resolve()),
        "inputs": inputs,
        "steps": steps,
        "outputs": [
            {
                "name": "quads",
                "path": out_path,
                "sql": f"SELECT {', '.join(QUAD_COLUMNS)} FROM distinct_quads",
                "settings": {
                    "profile": "whole",
                    "row_group_rows": 65536,
                    "order_by": [
                        {"field": "subject", "direction": "asc", "nulls": "nulls_last"},
                        {"field": "predicate", "direction": "asc", "nulls": "nulls_last"},
                        {"field": "nquad", "direction": "asc", "nulls": "nulls_last"},
                    ],
                    "columns": list(QUAD_COLUMNS),
                    "dictionary_columns": ["predicate", "object_kind", "object_datatype", "graph"],
                    "delta_columns": [],
                    "key_column": None,
                    "created_by": "ddk-catalog-graph",
                    "footer_limit": 4 << 20,
                },
            }
        ],
        "queries": [],
    }
    if job_id is not None:
        job_spec["id"] = str(job_id)

    return {
        "jobSpec": job_spec,
        "boundVersions": bound_versions,
        "branchCount": len(branches),
        "notes": {alias: list(items) for alias, items in sorted(notes.items()) if items},
    }


def materialize_graph_quads(
    catalog,
    adapter,
    *,
    work_dir,
    output_parquet_path,
    output_nquads_path=None,
    datasets=None,
    file_overrides=None,
    input_digests=None,
    job_id=None,
):
    """Materialize row-level RDF quads in DataFusion (`quads.parquet`) and optionally stream `.nq` in Rust."""
    from hashlib import file_digest
    from pathlib import Path

    work = Path(work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    out_parquet = Path(output_parquet_path).resolve()
    out_parquet.parent.mkdir(parents=True, exist_ok=True)

    compiled = compile_graph_quads_job(
        catalog,
        scratch_dir=work / "scratch",
        output_parquet_path=out_parquet,
        datasets=datasets,
        file_overrides=file_overrides,
        job_id=job_id,
    )
    known = _catalog_parquet_digests(catalog)
    if input_digests:
        for raw_p, dig in input_digests.items():
            known[str(Path(raw_p).resolve())] = dig

    digests = {}
    for inp in compiled["jobSpec"]["inputs"]:
        p = inp["path"]
        if p in known:
            digests[p] = known[p]
        else:
            with Path(p).open("rb") as fh:
                digests[p] = file_digest(fh, "sha256").hexdigest()

    job_response = adapter.execute(compiled["jobSpec"], input_digests=digests)
    if job_response["status"] != "succeeded":
        return {"status": job_response["status"], "job": job_response, "compiled": compiled}

    parquet_quad_count = job_response["result"]["outputs"][0]["rows"]
    if output_nquads_path is not None:
        out_nq = Path(output_nquads_path).resolve()
        out_nq.parent.mkdir(parents=True, exist_ok=True)
        nq_response = adapter.export_nquads(out_parquet, out_nq)
        out = {
            "status": nq_response["status"],
            "job": job_response,
            "nquads": nq_response,
            "compiled": compiled,
        }
        if nq_response["status"] == "succeeded":
            out["quadCount"] = nq_response["result"]["output"]["quads"]
        return out

    return {
        "status": "succeeded",
        "quadCount": parquet_quad_count,
        "job": job_response,
        "compiled": compiled,
    }

