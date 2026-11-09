"""Knowledge-graph views of an assembled catalog (DDK-CATALOG-013 and DDK-CATALOG-014).

Both read only the admitted catalog. The graph adds PROV-O, DQV, VoID and SKOS statements to the
unchanged DCAT 3 document. The YARRRML mappings let an RML engine such as Morph-KGC lift one exact
version's rows into RDF; DDK writes the mappings and never runs them.
"""

import json
from urllib.parse import quote, unquote, urlsplit

from .catalog_access import CatalogError
from .catalog_exports import CONTEXT, dcat_document
from .catalog_metadata import check_report, stable_id
from .documents import json_dumps

DETAILS = "urn:ddk:catalog:assembly"
VOCAB = "https://github.com/mikewolfd/data-design-kit/blob/main/vocab/ddk.ttl#"
ODPS = "https://github.com/bitol-io/open-data-product-standard/tree/v1.1.0"
GRAPH_CONTEXT = {
    **CONTEXT, "dqv": "http://www.w3.org/ns/dqv#", "void": "http://rdfs.org/ns/void#",
    "skos": "http://www.w3.org/2004/02/skos/core#", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#", "ddkv": VOCAB,
}
GRAPH_ADAPTER = {"id": "ddk.catalog.graph", "version": "0.1.0"}
RML_ADAPTER = {"id": "ddk.catalog.rml", "version": "0.1.0"}
# Only declarations that pin a representation get a datatype; logical `number` stays plain (DDK-DATA-003).
DATATYPES = {"integer": "xsd:integer", "boolean": "xsd:boolean", "date": "xsd:date", "timestamp": "xsd:dateTime",
             "time": "xsd:time"}
MATCH_PREDICATES = {"same": "http://www.w3.org/2004/02/skos/core#exactMatch",
                    "undecided": "http://www.w3.org/2004/02/skos/core#closeMatch", "not_same": VOCAB + "noMatch"}
FILE_TYPES = {"text/csv": "csv", "application/vnd.apache.parquet": "parquet"}


def child_iri(base, *parts):
    """An IRI under a catalog identifier: URNs extend with ':' and other IRIs with '/'."""
    separator = ":" if base.startswith("urn:") else "/"
    return separator.join([base.rstrip(":/"), *(quote(str(part), safe="") for part in parts)])


def field_predicate(dataset_id, path, prop):
    """A property's canonical URL when its definition gives one, else a predicate scoped to its dataset."""
    canonical = [item["url"] for item in prop.get("authoritativeDefinitions", ())
                 if item.get("type") == "canonicalUrl" and item.get("url")]
    return canonical[0] if canonical else child_iri(dataset_id, "field", *path)


def _definitions(catalog):
    return catalog.get("extensions", {}).get(DETAILS, {}).get("datasetDefinitions", {})


def _fields(properties, path=()):
    for prop in properties:
        yield (*path, prop["name"]), prop
        yield from _fields(prop.get("properties", ()), (*path, prop["name"]))


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


def _row_template(dataset_id, columns):
    separator = ":" if dataset_id.startswith("urn:") else "/"
    return child_iri(dataset_id, "row") + "".join(f"{separator}$({column})" for column in columns)


class _Nodes:
    def __init__(self, graph):
        self.items = {node["@id"]: node for node in graph}

    def node(self, identifier, *types):
        item = self.items.setdefault(identifier, {"@id": identifier})
        self.add(item, "@type", *types)
        return item

    @staticmethod
    def add(item, key, *values):
        values = [value for value in values if value not in (None, "", [])]
        if not values:
            return
        current = item.get(key, [])
        current = current if isinstance(current, list) else [current]
        merged = current + [value for value in values if value not in current]
        item[key] = merged[0] if len(merged) == 1 else merged


def _ref(identifier):
    return {"@id": identifier}


def _concept(prefix, value):
    return _ref(f"ddkv:{prefix}-{value}")


def graph_document(catalog):
    """DCAT 3 plus PROV-O, DQV, VoID and SKOS for the catalog's facts, checked by an independent reader.

    Returns the JSON-LD document and the graph the reader parsed from it, so Turtle reuses that parse.
    """
    try:
        from rdflib import Graph, RDF, URIRef
    except ImportError as exc:
        raise CatalogError("ADAPTER-CAPABILITY-MISSING", "The graph export requires an independent JSON-LD reader.",
                           status="not_run") from exc
    nodes = _Nodes(dcat_document(catalog)["@graph"])
    root = nodes.node(catalog["id"])
    aliases = {item["alias"]: item["id"] for item in catalog["datasets"]}
    definitions = _definitions(catalog)

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
            agent = nodes.node(stable_id("origin-agent", dataset["id"], dataset["origin"]), "prov:Agent")
            nodes.add(agent, "dcterms:type", _concept("origin", dataset["origin"]))
            nodes.add(item, "prov:wasAttributedTo", _ref(agent["@id"]))
        for path, prop in _fields(definitions.get(dataset["alias"], {}).get("properties", ())):
            field = nodes.node(field_predicate(dataset["id"], path, prop), "rdf:Property")
            nodes.add(field, "rdfs:label", ".".join(path))
            nodes.add(field, "skos:definition", prop.get("description"))
            nodes.add(field, "rdfs:isDefinedBy", _ref(dataset["id"]))
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
        nodes.add(measurement, "dqv:value", _concept("outcome", check["status"]))
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
        nodes.add(linkset, "void:objectsTarget", _ref(aliases[relationship["target"]["dataset"]]))
        nodes.add(linkset, "dcterms:description", relationship.get("meaning"))
        nodes.add(linkset, "dcterms:type", *(_concept(prefix, relationship[key]) for key, prefix in (
            ("cardinality", "cardinality"), ("scope", "scope"), ("nulls", "nulls"), ("match", "match"))
            if relationship.get(key)))
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

    def expand(term):
        prefix, _, local = term.partition(":")
        return GRAPH_CONTEXT[prefix] + local if prefix in GRAPH_CONTEXT else term

    found = {
        "datasets": len(set(parsed.objects(URIRef(catalog["id"]), URIRef(expand("dcat:dataset"))))),
        "versions": len(set(parsed.subjects(URIRef(expand("dcat:isVersionOf"))))),
        "relationships": len(set(parsed.subjects(RDF.type, URIRef(expand("void:Linkset"))))),
        "checks": len(set(parsed.subjects(RDF.type, URIRef(expand("dqv:QualityMeasurement"))))),
        "products": len(set(parsed.subjects(URIRef(expand("dcterms:conformsTo")), URIRef(ODPS)))),
    }
    expected = graph_counts(catalog)
    if found != expected:
        raise CatalogError("CATALOG-GRAPH-VALIDATION",
                           f"The JSON-LD reader found {found}; the catalog holds {expected}.")
    return document, parsed


def graph_counts(catalog):
    """What the graph must hold, counted from the catalog itself."""
    return {"datasets": len({item["id"] for item in catalog["datasets"]}), "versions": len(catalog["versions"]),
            "relationships": len(catalog["relationships"]),
            "checks": len({json_dumps(item) for item in catalog["checks"]}),
            "products": len({item["id"] for item in catalog["products"]})}


def turtle_bytes(graph):
    for prefix, namespace in GRAPH_CONTEXT.items():
        graph.bind(prefix, namespace, override=True)
    return graph.serialize(format="turtle").encode("utf-8")


def _local_path(location):
    parts = urlsplit(location)
    return unquote(parts.path) if parts.scheme == "file" else location


def _sources(catalog):
    """Per dataset alias, the exact versions that have an available Parquet or CSV file, in version order."""
    versions = {item["id"]: item["dataset"] for item in catalog["versions"]}
    found = {}
    for record in sorted(catalog["representations"], key=lambda item: (item["version"], item["id"])):
        if (record["kind"] == "file" and record["availability"] == "available"
                and record.get("mediaType") in FILE_TYPES and record["version"] in versions):
            found.setdefault(versions[record["version"]], []).append((record["version"], _local_path(record["location"])))
    return found


def _iri(value):
    """An IRI term map. Readers that guess IRIs from the scheme would read a `urn:` constant as a literal."""
    return {"value": value, "type": "iri"}


def _yaml(value, depth=0):
    """Block YAML whose scalars, sequences and term maps are JSON, which YAML 1.2 reads unchanged."""
    pad, lines = "  " * depth, []
    for key, item in value.items():
        if isinstance(item, dict) and "value" in item:
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


def rml_mappings(catalog):
    """One YARRRML mapping per dataset: {alias: (structure, notes)}. Notes name what the mapping leaves out."""
    definitions = _definitions(catalog)
    if not definitions:
        raise CatalogError("ADAPTER-CAPABILITY-MISSING", "RML mappings need the catalog's dataset definitions.",
                           status="not_run")
    datasets = {item["alias"]: item for item in catalog["datasets"]}
    keys, sources = _row_keys(catalog), _sources(catalog)
    outgoing = {}
    for relationship in catalog["relationships"]:
        outgoing.setdefault(relationship["source"]["dataset"], []).append(relationship)
    mappings = {}
    for alias, dataset in sorted(datasets.items()):
        properties = definitions.get(alias, {}).get("properties", ())
        notes = []
        mapping = {"sources": [["$(_source)"]], "graphs": _iri("$(_version)")}
        if alias in keys:
            mapping["s"] = _row_template(dataset["id"], keys[alias])
        else:
            notes.append("No top-level row key, so rows are blank nodes.")
        po = []
        for prop in properties:
            if prop.get("logicalType") in {"object", "array"}:
                notes.append(f"{prop['name']} ({prop['logicalType']}) is not mapped: nested values need a flattening view.")
                continue
            value = f"$({prop['name']})"
            datatype = DATATYPES.get(prop.get("logicalType"))
            po.append({"p": _iri(field_predicate(dataset["id"], (prop["name"],), prop)),
                       "o": {"value": value, "datatype": datatype} if datatype else value})
        for relationship in outgoing.get(alias, ()):
            link = _link(relationship, datasets, keys, notes)
            if link is not None:
                po.append(link)
        mapping["po"] = po
        found = sources.get(alias, [])
        version, source = found[0] if found else (dataset["id"], alias.rpartition("/")[2] + ".parquet")
        if len(found) > 1:
            notes.append("Other exact versions with files: " + ", ".join(item for item, _ in found[1:]) + ".")
        document = {"prefixes": {"xsd": "http://www.w3.org/2001/XMLSchema#",
                                 "skos": GRAPH_CONTEXT["skos"], "ddkv": VOCAB},
                    "external": {"source": source, "version": version},
                    "mappings": {alias: mapping}}
        decisions = _decision_mappings(alias, dataset, properties, outgoing.get(alias, ()), datasets, keys, source)
        if decisions:
            document["mappings"].update(decisions)
            notes.append("Match decisions read the source through DuckDB views; when external.source changes, "
                         "change the path in their queries too.")
        mappings[alias] = (document, notes)
    return mappings


def _link(relationship, datasets, keys, notes):
    """A relationship as an object property: a row IRI when the join names the target's key, else a join."""
    source, target = relationship["source"], relationship["target"]
    if not all(len(path) == 1 and "field" in path[0] for path in source["paths"] + target["paths"]):
        notes.append(f"{relationship['id']} is not mapped: it joins nested or repeated values.")
        return None
    pairs = dict(zip((path[0]["field"] for path in target["paths"]), (path[0]["field"] for path in source["paths"])))
    target_key = keys.get(target["dataset"])
    if target_key and set(target_key) == set(pairs):
        template = _row_template(datasets[target["dataset"]]["id"], [pairs[field] for field in target_key])
        return {"p": _iri(relationship["id"]), "o": _iri(template)}
    if not target_key or len(pairs) != 1:
        notes.append(f"{relationship['id']} is not mapped: "
                     + ("its target has no row key to name." if not target_key else "it joins on several columns."))
        return None
    (parent, child), = pairs.items()
    return {"p": _iri(relationship["id"]), "o": {"mapping": target["dataset"], "condition": {
        "function": "equal", "parameters": [["str1", f"$({child})"], ["str2", f"$({parent})"]]}}}


def _decision_mappings(alias, dataset, properties, relationships, datasets, keys, source):
    """A match-decision table: role `evidence`, a string `decision` column, and two links to the matched rows."""
    names = {prop["name"]: prop for prop in properties}
    if (dataset["role"] != "evidence" or names.get("decision", {}).get("logicalType") != "string"
            or len(relationships) != 2):
        return {}
    sides = []
    for relationship in sorted(relationships, key=lambda item: item["id"]):
        link = _link(relationship, datasets, keys, [])
        if link is None or "mapping" in link["o"]:
            return {}
        sides.append(link["o"]["value"])
    query_source = source.replace("'", "''")
    return {f"{alias}#{decision}": {
        "sources": [{"query": f"SELECT * FROM '{query_source}' WHERE decision = '{decision}'"}],
        "graphs": _iri("$(_version)"), "s": sides[0], "po": [{"p": _iri(predicate), "o": _iri(sides[1])}],
    } for decision, predicate in MATCH_PREDICATES.items()}


def rml_documents(catalog):
    """YAML files named rml/<alias>.yarrrml.yml, each headed by what it maps and what it leaves out."""
    files = {}
    for alias, (document, notes) in rml_mappings(catalog).items():
        dataset = next(item for item in catalog["datasets"] if item["alias"] == alias)
        header = [f"# YARRRML for {dataset['id']} from DDK catalog {catalog['id']}.",
                  "# Set external.source to one exact version's Parquet or CSV file and external.version to that",
                  "# version's catalog IRI; an RML engine such as Morph-KGC then lifts its rows into that graph.",
                  *(f"# {note}" for note in notes)]
        files[f"rml/{alias.strip('/')}.yarrrml.yml"] = ("\n".join(header) + "\n" + _yaml(document) + "\n").encode("utf-8")
    return files
