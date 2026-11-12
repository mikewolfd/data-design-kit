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


def _concepts(catalog):
    """{(dataset alias, field names): concept IRI}; an array item's concept applies to the array's values."""
    return {(field["dataset"], tuple(step["field"] for step in field["path"] if "field" in step)): row["concept"]
            for row in catalog.get("concepts", ()) for field in row["fields"]}


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


def _target_id(relationship, aliases):
    """A relationship target's dataset identifier, or the external identifier it keeps."""
    target = relationship["target"]
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
        nodes.add(linkset, "void:objectsTarget", _ref(_target_id(relationship, aliases)))
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
    for subject, target, concept in candidate_links(catalog):
        linkset = nodes.node(stable_id("candidate-linkset", subject, target, concept), "ddkv:CandidateLinkset")
        nodes.add(linkset, "ddkv:subjectsTarget", _ref(aliases[subject]))
        nodes.add(linkset, "ddkv:objectsTarget", _ref(aliases[target]))
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
    declared = {frozenset((row["source"]["dataset"], row["target"].get("dataset"))) for row in catalog["relationships"]}
    joined = {(row[side]["dataset"], json_dumps(path)) for row in catalog["relationships"]
              for side in ("source", "target") if "dataset" in row[side] for path in row[side]["paths"]}
    found = set()
    for row in catalog.get("concepts", ()):
        if not any((field["dataset"], json_dumps(field["path"])) in joined for field in row["fields"]):
            continue
        anchors = {field["dataset"] for field in row["fields"]
                   if keys.get(field["dataset"]) and [[{"field": name}] for name in keys[field["dataset"]]] == [field["path"]]}
        for field in row["fields"]:
            for anchor in sorted(anchors - {field["dataset"]}):
                pair = tuple(sorted((field["dataset"], anchor))) if field["dataset"] in anchors else (field["dataset"], anchor)
                if frozenset(pair) not in declared:
                    found.add((*pair, row["concept"]))
    return sorted(found)


def graph_edges(catalog):
    """The evidence-carrying edges the graph must contain, read straight from the catalog records."""
    aliases = {item["alias"]: item["id"] for item in catalog["datasets"]}
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
        yield linkset, "void:objectsTarget", _target_id(relationship, aliases)
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


# What every dataset's mappings share: each dataset's rows, its concept fields and the catalog's releases.
_Context = namedtuple("_Context", "rows concepts same_release")


def _target(relationship, context):
    """Target fields, when they are top-level fields, and the target's rows when it has a key."""
    target = context.rows.get(relationship["target"].get("dataset"))
    paths = relationship["target"]["paths"] if target else ()
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
    context = _Context(rows, _concepts(catalog), _release_sharing(catalog))
    outgoing = defaultdict(list)
    for relationship in catalog["relationships"]:
        source_alias = relationship["source"]["dataset"]
        if source_alias not in mappable:
            continue
        if public:
            target_alias = relationship["target"].get("dataset")
            if (not all(path in disclosed_paths.get(source_alias, ()) for path in relationship["source"]["paths"])
                    or (target_alias is not None and (
                        target_alias not in mappable
                        or not all(path in disclosed_paths.get(target_alias, ())
                                   for path in relationship["target"]["paths"])))):
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
        mappings[f"{alias}#field:{_path_key(logical_path)}"] = {
            "sources": [{"query": query}], "s": rows.subject(),
            "po": [_value(dataset_id, logical_path, prop, "v0")],
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
    for relationship in relationships:
        link = _link(relationship, rows, context, notes)
        if link is None:
            continue
        kind, value = link
        if kind == "each":
            each_links[value[0]].append(value[1])
        else:
            mappings[f"{alias}#{relationship['id']}"] = value
    for logical_path, phys_path, prop in arrays:
        mappings.update(_array_mappings(dataset_id, alias, logical_path, phys_path, prop, rows,
                                        each_links.pop(logical_path, []), notes))
    for path in each_links:
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


def _array_mappings(dataset_id, alias, logical_path, phys_path, prop, rows, links, notes):
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
        unnested = _text(f"UNNEST({raw_array})", items)
        inner = (f"SELECT {', '.join([*rows.select_keys(), f'{unnested} AS v0'])} "
                 f"FROM {rows.reader} WHERE {rows.where(f'{raw_array} IS NOT NULL')}")
        query = f"SELECT * FROM ({inner}) WHERE v0 IS NOT NULL"
        return {f"{alias}#array:{key}": {"sources": [{"query": query}], "s": rows.subject(),
                                         "po": [_value(dataset_id, logical_path, items, "v0"), *links]}}
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
        result[f"{alias}#item:{key}:{_path_key(leaf_logical)}"] = {
            "sources": [{"query": leaf_query}], "s": subject_element,
            "po": [_value(dataset_id, (*logical_path, *leaf_logical), child, "v0")],
        }
    return result


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
    if len(eaches) > 1 or any(not all("field" in step for step in (path[:-1] if path in eaches else path))
                              for path in source_paths):
        notes.append(f"{identifier} is not mapped: its source path is not fields with at most one array.")
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
