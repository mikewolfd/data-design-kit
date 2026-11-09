"""Knowledge-graph views of an assembled catalog (DDK-CATALOG-013 and DDK-CATALOG-014).

Both read only the admitted catalog. The graph adds PROV-O, DQV, VoID and SKOS statements to the
unchanged DCAT 3 document. The YARRRML mappings let an RML engine such as Morph-KGC lift one exact
version's rows into RDF; DDK writes the mappings and never runs them.
"""

import json
import re
from urllib.parse import quote, unquote, urlsplit

from .catalog_access import CatalogError
from .catalog_exports import CONTEXT, dcat_document
from .catalog_metadata import check_report, stable_id
from .documents import json_dumps

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
DATATYPES = {"integer": "xsd:integer", "boolean": "xsd:boolean", "date": "xsd:date", "timestamp": "xsd:dateTime",
             "time": "xsd:time"}
MATCH_PREDICATES = {"same": "http://www.w3.org/2004/02/skos/core#exactMatch",
                    "undecided": "http://www.w3.org/2004/02/skos/core#closeMatch", "not_same": VOCAB + "noMatch"}
FILE_TYPES = {"text/csv": "csv", "application/vnd.apache.parquet": "parquet"}
ROW = "__ddk_row"  # row position, the identity of rows in a dataset without a top-level key
# Morph-KGC 2.10.0 turns Parquet nulls into these strings before it drops missing values, so its configuration
# must list them; a text value that is exactly one of them is then dropped as well.
NULL_MARKERS = ",nan,None,NaT,<NA>"


def child_iri(base, *parts):
    """An IRI under a catalog identifier: URNs extend with ':' and other IRIs with '/'."""
    separator = ":" if base.startswith("urn:") else "/"
    return separator.join([base.rstrip(":/"), *(quote(str(part), safe="") for part in parts)])


def field_predicate(dataset_id, path):
    """The predicate for a field: scoped to its dataset, so two fields never share one by accident."""
    return child_iri(dataset_id, "field", *path)


def _definitions(catalog):
    return catalog.get("extensions", {}).get(DETAILS, {}).get("datasetDefinitions", {})


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


def _blank(prefix, columns):
    """A blank-node template; N-Triples labels allow only letters, digits and a few marks, so others become '_'."""
    label = re.sub(r"[^A-Za-z0-9]", "_", prefix)
    return {"value": label + "".join(f"_$({column})" for column in columns), "type": "blanknode"}


def _template(base, columns):
    separator = ":" if base.startswith("urn:") else "/"
    return base + "".join(f"{separator}$({column})" for column in columns)


class _Nodes:
    def __init__(self, graph):
        self.items = {node["@id"]: node for node in graph}
        self.seen = {}

    def node(self, identifier, *types):
        item = self.items.setdefault(identifier, {"@id": identifier})
        self.add(item, "@type", *types)
        return item

    def add(self, item, key, *values):
        seen = self.seen.setdefault((item["@id"], key), {json_dumps(value) for value in self._values(item, key)})
        for value in values:
            if value in (None, "", []) or json_dumps(value) in seen:
                continue
            seen.add(json_dumps(value))
            current = self._values(item, key)
            item[key] = value if not current else current + [value]

    @staticmethod
    def _values(item, key):
        current = item.get(key, [])
        return current if isinstance(current, list) else [current]


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
            field = nodes.node(field_predicate(dataset["id"], path), "rdf:Property")
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
        nodes.add(linkset, "dcterms:type", *(_concept(key, relationship[key]) for key in (
            "cardinality", "scope", "nulls", "match") if relationship.get(key)))
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


def graph_edges(catalog):
    """The evidence-carrying edges the graph must contain, read straight from the catalog records."""
    aliases = {item["alias"]: item["id"] for item in catalog["datasets"]}
    for run in catalog["runs"]:
        yield from ((run["id"], "prov:used", version) for version in run["inputs"])
        yield from ((version, "prov:wasGeneratedBy", run["id"]) for version in run["outputs"])
    for check in catalog["checks"]:
        measurement = stable_id("measurement", check)
        yield measurement, "dqv:computedOn", check["subject"]
        yield measurement, "dqv:value", f"ddkv:outcome-{check['status']}"
        yield measurement, "dcterms:type", "ddkv:evidence-" + ("executed" if check_report(check) else "declared")
    for relationship in catalog["relationships"]:
        linkset = child_iri(relationship["id"], "linkset")
        yield linkset, "void:subjectsTarget", aliases[relationship["source"]["dataset"]]
        yield linkset, "void:objectsTarget", aliases[relationship["target"]["dataset"]]
        yield linkset, "void:linkPredicate", relationship["id"]
    for product in catalog["products"]:
        for port in product["ports"]:
            yield (product["id"], "dcterms:hasPart" if port["direction"] == "output" else "dcterms:requires",
                   aliases[port["dataset"]])


def turtle_bytes(graph):
    for prefix, namespace in GRAPH_CONTEXT.items():
        graph.bind(prefix, namespace, override=True)
    return graph.serialize(format="turtle").encode("utf-8")


# RML mappings. DuckDB views, which Morph-KGC runs for `query` sources over files, reach what plain tabular
# sources cannot: nested fields, array elements, rows without a key and joins that are not on the target key.

def _sql_name(name):
    return '"' + str(name).replace('"', '""') + '"'


def _sql_text(value):
    return "'" + str(value).replace("'", "''") + "'"


def _sql_field(path, table=None):
    expression = (f"{table}." if table else "") + _sql_name(path[0])
    return expression + "".join(f"[{_sql_text(part)}]" for part in path[1:])


def _column(path):
    return ".".join(path)


def _iri(value):
    """An IRI term map. Readers that guess IRIs from the scheme would read a `urn:` constant as a literal."""
    return {"value": value, "type": "iri"}


def _value(dataset_id, path, prop, column):
    datatype = DATATYPES.get(prop.get("logicalType"))
    return {"p": _iri(field_predicate(dataset_id, path)),
            "o": {"value": f"$({column})", "datatype": datatype} if datatype else f"$({column})"}


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


def _custom(definition, name):
    """A `vendor: ddk` custom property of an ODCS object, the declared place for DDK conventions."""
    return next((item.get("value") for item in definition.get("customProperties", ())
                 if item.get("vendor") == "ddk" and item.get("property") == name), None)


class _Rows:
    """How one dataset's rows are read and named: by key, or by position in the file when it has none."""

    def __init__(self, dataset, key, path):
        self.dataset, self.key, self.path = dataset, key, path
        self.columns = key or [ROW]
        self.table = (_sql_text(path) if key else
                      f"(SELECT row_number() OVER () AS {_sql_name(ROW)}, * FROM {_sql_text(path)})")

    def subject(self, prefix=""):
        columns = [prefix + column for column in self.columns]
        if self.key:
            return _template(child_iri(self.dataset["id"], "row"), columns)
        return _blank(self.dataset["alias"], columns)

    def select(self, *expressions, table=None):
        return ", ".join([_sql_field((column,), table) for column in self.columns] + list(expressions))


def _target(relationship, catalog_rows):
    """Target fields, when they are top-level fields, and the target's rows when it has a key."""
    target = catalog_rows.get(relationship["target"]["dataset"])
    paths = relationship["target"]["paths"]
    if target is None or not target.key or not all(len(path) == 1 and "field" in path[0] for path in paths):
        return None, None
    return [path[0]["field"] for path in paths], target


def rml_mappings(catalog):
    """One YARRRML document per dataset: {alias: (document, notes)}. Notes name what it leaves out and why."""
    definitions = _definitions(catalog)
    if not definitions:
        raise CatalogError("ADAPTER-CAPABILITY-MISSING", "RML mappings need the catalog's dataset definitions.",
                           status="not_run")
    datasets = {item["alias"]: item for item in catalog["datasets"]}
    keys, sources = _row_keys(catalog), _sources(catalog)
    chosen, notes = {}, {alias: [] for alias in datasets}
    for alias, dataset in datasets.items():
        found = sources.get(alias, [])
        chosen[alias] = found[0] if found else (dataset["id"], alias.rpartition("/")[2] + ".parquet")
        if not found:
            notes[alias].append("No exact version with a Parquet or CSV file is known; point the paths at one.")
        elif len(found) > 1:
            notes[alias].append("Other exact versions with files: " + ", ".join(item for item, _ in found[1:]) + ".")
    rows = {alias: _Rows(dataset, keys.get(alias), chosen[alias][1]) for alias, dataset in datasets.items()}
    outgoing = {}
    for relationship in catalog["relationships"]:
        outgoing.setdefault(relationship["source"]["dataset"], []).append(relationship)
    documents = {}
    for alias, dataset in sorted(datasets.items()):
        definition, here, version = definitions.get(alias, {}), rows[alias], chosen[alias][0]
        mappings = _dataset_mappings(dataset, definition, here, outgoing.get(alias, ()), rows, notes[alias])
        for mapping in mappings.values():
            mapping["graphs"] = _iri(version)
        documents[alias] = ({"prefixes": {"xsd": "http://www.w3.org/2001/XMLSchema#"}, "mappings": mappings},
                            notes[alias])
    return documents


def _dataset_mappings(dataset, definition, rows, relationships, catalog_rows, notes):
    alias, dataset_id = dataset["alias"], dataset["id"]
    flat, nested, arrays = [], [], []
    for path, prop in _walk(definition.get("properties", ())):
        kind = prop.get("logicalType")
        (arrays if kind == "array" else nested if len(path) > 1 else flat).append((path, prop))
        if kind == "object":
            notes.append(f"{_column(path)} is an object without declared fields, so it is not mapped.")
    main = {"sources": [[rows.path]] if rows.key else [{"query": f"SELECT * FROM {rows.table}"}], "s": rows.subject(),
            "po": [_value(dataset_id, path, prop, path[0]) for path, prop in flat if prop.get("logicalType") != "object"]}
    mappings = {alias: main}
    if nested:
        expressions = [f"{_sql_field(path)} AS {_sql_name(_column(path))}" for path, _ in nested]
        mappings[f"{alias}#fields"] = {
            "sources": [{"query": f"SELECT {rows.select(*expressions)} FROM {rows.table}"}], "s": rows.subject(),
            "po": [_value(dataset_id, path, prop, _column(path)) for path, prop in nested]}
    each_links = {}
    for relationship in relationships:
        if relationship.get("match") == "project_rule":
            notes.append(f"{relationship['id']} is not mapped: a project rule, not equal values, decides its matches.")
            continue
        link = _link(relationship, rows, catalog_rows, notes)
        if link is None:
            continue
        kind, value = link
        if kind == "row":
            main["po"].append(value)
        elif kind == "each":
            each_links.setdefault(value[0], []).append(value[1])
        else:
            mappings[f"{alias}#{relationship['id']}"] = value
    for path, prop in arrays:
        mappings.update(_array_mappings(dataset_id, alias, path, prop, rows, each_links.pop(path, []), notes))
    for path in each_links:
        notes.append(f"Links through {_column(path)} are not mapped: it is not a declared array field.")
    decisions = _custom(definition, "matchDecisions")
    if decisions:
        mappings.update(_decision_mappings(alias, decisions, definition, relationships, rows, catalog_rows, notes))
    return mappings


def _walk(properties, path=()):
    """Scalar leaves, arrays and empty objects under struct nesting; array items are handled with their array."""
    for prop in properties:
        here = (*path, prop["name"])
        if prop.get("logicalType") == "object" and prop.get("properties"):
            yield from _walk(prop["properties"], here)
        else:
            yield here, prop


def _array_mappings(dataset_id, alias, path, prop, rows, links, notes):
    """Unnest one array: scalar items become repeated values, object items become nodes under the row."""
    column, items = _column(path), prop.get("items") if isinstance(prop.get("items"), dict) else {}
    if items.get("logicalType") != "object":
        if items.get("logicalType") == "array":
            notes.append(f"{column} is not mapped: arrays of arrays need a view of their own.")
            return {}
        query = f"SELECT {rows.select(f'UNNEST({_sql_field(path)}) AS {_sql_name(column)}')} FROM {rows.table}"
        return {f"{alias}#{column}": {"sources": [{"query": query}], "s": rows.subject(),
                                      "po": [_value(dataset_id, path, items, column), *links]}}
    index, leaves = f"{column}.__index", []
    for leaf, child in _walk(items.get("properties", ())):
        if child.get("logicalType") in {"array", "object"}:
            notes.append(f"{column}.{_column(leaf)} is not mapped: it nests inside an array element.")
        else:
            leaves.append((leaf, child))
    inner = (f"SELECT {rows.select('UNNEST(' + _sql_field(path) + ') AS __ddk_item', 'UNNEST(range(1, len(' + _sql_field(path) + ') + 1)) AS __ddk_index')} "
             f"FROM {rows.table}")
    outer = rows.select(f"__ddk_index AS {_sql_name(index)}",
                        *(f"{_sql_field(('__ddk_item', *leaf))} AS {_sql_name(column + '.' + _column(leaf))}"
                          for leaf, _ in leaves))
    query = f"SELECT {outer} FROM ({inner})"
    if rows.key:  # an item is named under its row: <row>:<array>:<position>
        separator = ":" if dataset_id.startswith("urn:") else "/"
        element = _template(child_iri(dataset_id, "row"), rows.columns) + separator + quote(column, safe="")
        element = _template(element, [index])
    else:
        element = _blank(f"{alias}_{column}", [*rows.columns, index])
    if links:
        notes.append(f"Links through {column} are not mapped: its items are objects.")
    return {f"{alias}#{column}": {"sources": [{"query": query}], "s": rows.subject(),
                                  "po": [{"p": _iri(field_predicate(dataset_id, path)),
                                          "o": _iri(element) if rows.key else element}]},
            f"{alias}#{column}.items": {"sources": [{"query": query}], "s": element,
                                        "po": [_value(dataset_id, (*path, *leaf), child, f"{column}.{_column(leaf)}")
                                               for leaf, child in leaves]}}


def _link(relationship, rows, catalog_rows, notes):
    """A relationship as ('row', po) on the main mapping, ('each', (array path, po)) on an array mapping,
    or ('view', mapping) that joins the two exact versions in DuckDB."""
    fields, target = _target(relationship, catalog_rows)
    if target is None:
        notes.append(f"{relationship['id']} is not mapped: its target has no top-level key to name its rows.")
        return None
    source_paths = relationship["source"]["paths"]
    flat = all(len(path) == 1 and "field" in path[0] for path in source_paths)
    pairs = dict(zip(fields, source_paths))
    if flat and set(fields) == set(target.key):
        columns = [pairs[field][0]["field"] for field in target.key]
        return "row", {"p": _iri(relationship["id"]), "o": _iri(_template(child_iri(target.dataset["id"], "row"), columns))}
    eaches = [path for path in source_paths if path[-1].get("each")]
    if (len(source_paths) == 1 and len(eaches) == 1 and fields == target.key
            and all("field" in step for step in eaches[0][:-1])):
        array = tuple(step["field"] for step in eaches[0][:-1])
        return "each", (array, {"p": _iri(relationship["id"]),
                                "o": _iri(_template(child_iri(target.dataset["id"], "row"), [_column(array)]))})
    if len(eaches) > 1 or any(not all("field" in step for step in (path[:-1] if path in eaches else path))
                              for path in source_paths):
        notes.append(f"{relationship['id']} is not mapped: its source path is not fields with at most one array.")
        return None
    child = rows.table
    if eaches:
        array = tuple(step["field"] for step in eaches[0][:-1])
        child = f"(SELECT *, UNNEST({_sql_field(array)}) AS __ddk_each FROM {rows.table})"
    conditions = [(_sql_name("__ddk_each") if path in eaches else _sql_field(tuple(step["field"] for step in path)),
                   _sql_field((field,), "p")) for field, path in pairs.items()]
    selected = rows.select(*(f"p.{_sql_name(column)} AS {_sql_name('target.' + column)}" for column in target.key),
                           table="c")
    query = (f"SELECT {selected} FROM {child} AS c JOIN {target.table} AS p ON "
             + " AND ".join(f"c.{left} = {right}" for left, right in conditions))
    return "view", {"sources": [{"query": query}], "s": rows.subject(),
                    "po": [{"p": _iri(relationship["id"]),
                            "o": _iri(_template(child_iri(target.dataset["id"], "row"),
                                                ["target." + column for column in target.key]))}]}


def _decision_mappings(alias, column, definition, relationships, rows, catalog_rows, notes):
    """A declared match-decision table: each row links the two rows it judges, by its decision."""
    names = {prop["name"] for prop in definition.get("properties", ())}
    sides = []
    for relationship in sorted(relationships, key=lambda item: item["id"]):
        fields, target = _target(relationship, catalog_rows)
        paths = relationship["source"]["paths"]
        if target is None or set(fields) != set(target.key) or not all(len(p) == 1 and "field" in p[0] for p in paths):
            continue
        pairs = dict(zip(fields, paths))
        sides.append(_template(child_iri(target.dataset["id"], "row"), [pairs[f][0]["field"] for f in target.key]))
    if column not in names or len(sides) != 2:
        notes.append(f"Match decisions are declared on {column!r} but need that column and exactly two links "
                     "to keyed rows, so they are not mapped.")
        return {}
    return {f"{alias}#{decision}": {
        "sources": [{"query": f"SELECT * FROM {rows.table} WHERE {_sql_name(column)} = {_sql_text(decision)}"}],
        "s": sides[0], "po": [{"p": _iri(predicate), "o": _iri(sides[1])}],
    } for decision, predicate in MATCH_PREDICATES.items()}


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


def rml_documents(catalog):
    """YAML files named rml/<alias>.yarrrml.yml, each headed by what it reads and what it leaves out."""
    datasets = {item["alias"]: item for item in catalog["datasets"]}
    files = {}
    for alias, (document, notes) in rml_mappings(catalog).items():
        graph = next(iter(document["mappings"].values()))["graphs"]["value"]
        header = [f"# YARRRML for {datasets[alias]['id']} from DDK catalog {catalog['id']}.",
                  f"# Rows of exact version {graph} land in that named graph. Every source names the same file;",
                  "# DuckDB views (`query` sources, run by Morph-KGC) reach nested fields, array items and joins.",
                  f"# Morph-KGC needs `na_values = {NULL_MARKERS}`, or it writes Parquet nulls as text such as \"None\".",
                  *(f"# {note}" for note in notes)]
        files[f"rml/{alias.strip('/')}.yarrrml.yml"] = ("\n".join(header) + "\n" + _yaml(document) + "\n").encode("utf-8")
    return files
