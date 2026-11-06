"""DCAT 3 and pinned OpenLineage mappings for the assembled catalog."""

from collections import defaultdict
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from .catalog_access import CatalogError
from .catalog_metadata import stable_id
from .documents import json_dumps, schema_registry, validate_document

CONTEXT = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "ddk": "https://example.org/ddk/0.1/catalog#",
}
PRODUCER = "https://example.org/ddk/0.1"
DCAT_ADAPTER = {"id": "ddk.catalog.dcat", "version": "0.1.0"}
LINEAGE_ADAPTER = {"id": "ddk.lineage.openlineage", "version": "0.1.0"}


def _ref(identifier):
    return {"@id": identifier}


def _current_versions(catalog, version_datasets):
    selector = catalog.get("currentSelection")
    result = {}
    if selector is None:
        return result
    releases = {item["id"]: item for item in catalog["releases"]}
    for selection in catalog["selections"]:
        if any(selection[key] != value for key, value in selector.items()):
            continue
        release = releases[selection["release"]]
        for member in release["members"]:
            dataset = version_datasets[member]
            if dataset in result:
                raise CatalogError("CATALOG-SELECTION-AMBIGUOUS",
                                   f"More than one current selection or version matches {dataset!r}.")
            result[dataset] = (member, selection)
    return result


def dcat_document(catalog):
    try:
        from rdflib import Graph, RDF, URIRef
    except ImportError as exc:
        raise CatalogError("ADAPTER-CAPABILITY-MISSING", "DCAT validation requires an independent JSON-LD reader.",
                           status="not_run") from exc
    datasets = {item["alias"]: item for item in catalog["datasets"]}
    version_datasets = {item["id"]: datasets[item["dataset"]]["id"] for item in catalog["versions"]}
    selected = _current_versions(catalog, version_datasets)
    version_index = defaultdict(list)
    for version, dataset in version_datasets.items():
        version_index[dataset].append(version)
    release_index = defaultdict(list)
    for release in catalog["releases"]:
        for member in release["members"]:
            release_index[member].append(release["id"])
    distributions = defaultdict(list)
    services = []
    graph = {}
    for record in catalog["representations"]:
        if record["availability"] != "available":
            continue
        identifier, version = record["id"], record["version"]
        node = {"@id": identifier, "dcterms:source": _ref(record["record"]["uri"])}
        if record["kind"] == "service":
            node.update({"@type": "dcat:DataService", "dcat:endpointURL": _ref(record["location"]),
                         "dcat:servesDataset": _ref(version)})
            services.append(identifier)
        else:
            node.update({"@type": "dcat:Distribution", "dcat:accessURL": _ref(record["location"])})
            if record["kind"] == "file":
                node["dcat:downloadURL"] = _ref(record["location"])
            if record.get("mediaType"):
                node["dcat:mediaType"] = _ref("https://www.iana.org/assignments/media-types/" + record["mediaType"])
            distributions[version].append(identifier)
        graph[identifier] = node

    logical = {}
    for dataset in datasets.values():
        logical.setdefault(dataset["id"], []).append(dataset)
    for identifier, revisions in logical.items():
        titles = sorted({item.get("title", identifier) for item in revisions})
        node = {"@id": identifier, "@type": "dcat:Dataset", "dcterms:title": titles,
                "dcterms:source": [_ref(uri) for uri in sorted({item["definition"]["source"]["uri"] for item in revisions})]}
        if version_index[identifier]:
            node["dcat:hasVersion"] = [_ref(version) for version in version_index[identifier]]
        if identifier in selected:
            version, selection = selected[identifier]
            selection_id = stable_id("selection", selection)
            node["dcat:hasCurrentVersion"] = _ref(version)
            node["ddk:currentSelection"] = _ref(selection_id)
            graph[selection_id] = {
                "@id": selection_id, "prov:wasDerivedFrom": _ref(selection["record"]["uri"]),
                "ddk:release": _ref(selection["release"]), "ddk:purpose": selection["purpose"],
                "prov:wasAttributedTo": _ref(selection["authority"]),
                "prov:generatedAtTime": {"@value": selection["observedAt"],
                                        "@type": "http://www.w3.org/2001/XMLSchema#dateTime"},
            }
        graph[identifier] = node
    for version in catalog["versions"]:
        identifier = version["id"]
        native_value = version.get("reference", {}).get("value")
        node = {"@id": identifier, "@type": "dcat:Dataset",
                "dcat:isVersionOf": _ref(version_datasets[identifier]),
                "dcat:version": str(native_value) if isinstance(native_value, (str, int)) else identifier,
                "dcterms:source": _ref(version["record"]["uri"])}
        if distributions[identifier]:
            node["dcat:distribution"] = [_ref(item) for item in distributions[identifier]]
        if release_index[identifier]:
            node["dcterms:isPartOf"] = [_ref(item) for item in release_index[identifier]]
        graph[identifier] = node
    root = {"@id": catalog["id"], "@type": "dcat:Catalog", "dcterms:title": catalog["id"],
            "dcat:dataset": [_ref(identifier) for identifier in sorted(logical)]}
    if services:
        root["dcat:service"] = [_ref(item) for item in services]
    graph[catalog["id"]] = root
    document = {"@context": CONTEXT, "@graph": [graph[key] for key in sorted(graph)]}
    parsed = Graph().parse(data=json_dumps(document), format="json-ld")
    catalog_uri = URIRef(catalog["id"])
    if ((catalog_uri, RDF.type, URIRef(CONTEXT["dcat"] + "Catalog")) not in parsed
            or set(parsed.objects(catalog_uri, URIRef(CONTEXT["dcat"] + "dataset"))) != set(map(URIRef, logical))):
        raise CatalogError("CATALOG-DCAT-VALIDATION", "The JSON-LD reader could not resolve the expected DCAT resources.")
    return document


def _mapping(source, key):
    mapping = source.get(key, {})
    if not isinstance(mapping, dict):
        raise CatalogError("CATALOG-LINEAGE-MAPPING", f"OpenLineage {key!r} mappings must be objects.")
    return mapping


def _pair(item):
    if (not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key]
                                         for key in ("namespace", "name"))):
        raise CatalogError("CATALOG-LINEAGE-MAPPING", "An OpenLineage mapping needs a namespace and name.")
    return {key: item[key] for key in ("namespace", "name")}


def _physical_identity(version, representations):
    for record in representations:
        location = record.get("location")
        if not location:
            continue
        uri = urlsplit(location)
        if uri.scheme == "file":
            from urllib.parse import unquote
            return {"namespace": "file" if not uri.netloc else f"file://{uri.netloc}", "name": unquote(uri.path)}
        if uri.scheme in {"s3", "gs", "hdfs"} and uri.netloc and uri.path:
            return {"namespace": f"{uri.scheme}://{uri.netloc}", "name": uri.path.lstrip("/")}
    # Keep opaque or unmapped versions distinct when physical continuity is unresolved.
    reference = version["reference"]
    return {"namespace": reference["authority"], "name": stable_id("physical-version", reference, version["id"])}


def _validate_event(event):
    issues = validate_document(event, "openlineage")
    for item in (*event.get("inputs", ()), *event.get("outputs", ())):
        if facet := item.get("facets", {}).get("version"):
            issues.extend(validate_document(facet, "openlineage-version-facet"))
    if issues:
        raise CatalogError("CATALOG-LINEAGE-SCHEMA", issues[0].message, issues[0].pointer)


def lineage_documents(catalog, metadata):
    """Return mapped events, the reversible version mapping, and explicit mapping limits."""
    _, schemas, _ = schema_registry()
    event_schema = schemas["openlineage"]["$id"]
    facet_schema = schemas["openlineage-version-facet"]["$id"]
    source = metadata.lineage if metadata is not None else {}
    if source.keys() - {"jobs", "datasets", "runs", "declaredDatasets"}:
        raise CatalogError("CATALOG-LINEAGE-MAPPING", "The OpenLineage input includes an unknown mapping class.")
    jobs = _mapping(source, "jobs")
    mapped_versions = _mapping(source, "datasets")
    mapped_runs = _mapping(source, "runs")
    declared_datasets = _mapping(source, "declaredDatasets")
    productions = {item["alias"]: item for item in catalog["productions"]}
    datasets = {item["alias"]: item for item in catalog["datasets"]}
    versions = {item["id"]: item for item in catalog["versions"]}
    runs = {item["id"]: item for item in catalog["runs"]}
    for mapping, targets in ((jobs, productions), (mapped_versions, versions),
                             (mapped_runs, runs), (declared_datasets, datasets)):
        if mapping.keys() - targets.keys():
            raise CatalogError("CATALOG-LINEAGE-MAPPING", "An OpenLineage mapping references an unloaded identity.")
    representations = defaultdict(list)
    for row in catalog["representations"]:
        representations[row["version"]].append(row)

    physical_by_pair = {}
    version_ids = {}
    version_mappings = {}
    for identifier, version in versions.items():
        explicit = mapped_versions.get(identifier)
        owner_physical = metadata.physical_datasets.get(identifier) if metadata else None
        pair = _pair(explicit or owner_physical or _physical_identity(version, representations[identifier]))
        pair_key = tuple(pair.values())
        if owner_physical:
            physical_key = tuple(owner_physical.values())
            if physical_by_pair.setdefault(pair_key, physical_key) != physical_key:
                raise CatalogError("CATALOG-LINEAGE-CONFLICT", "One dataset identity would combine distinct physical files.")
        native_value = version.get("reference", {}).get("value")
        native_facet = explicit.get("version") if explicit else None
        facet = native_facet if native_facet is not None else native_value if isinstance(native_value, str) else identifier
        if not isinstance(facet, str) or not facet:
            raise CatalogError("CATALOG-LINEAGE-MAPPING", "A version facet must carry a nonempty native string.")
        key = (*pair_key, facet)
        if version_ids.setdefault(key, identifier) != identifier:
            raise CatalogError("CATALOG-LINEAGE-CONFLICT", "A dataset and version facet would resolve to multiple versions.")
        version_mappings[identifier] = {**pair, "datasetVersion": facet}

    job_pairs = {}
    jobs_by_pair = {}
    for alias, production in productions.items():
        identity = production["identity"]["id"]
        pair = _pair(jobs.get(alias, {"namespace": catalog["project"]["id"], "name": identity}))
        if jobs_by_pair.setdefault(tuple(pair.values()), identity) != identity:
            raise CatalogError("CATALOG-LINEAGE-CONFLICT", "One job identity would combine different productions.")
        job_pairs[alias] = pair

    def declared(alias):
        return _pair(declared_datasets.get(alias, {"namespace": catalog["project"]["id"],
                                                   "name": datasets[alias]["id"]}))

    def observed(version):
        mapping = version_mappings[version]
        return {**_pair(mapping), "facets": {"version": {
            "_producer": PRODUCER, "_schemaURL": facet_schema, "datasetVersion": mapping["datasetVersion"],
        }}}

    events, limits = [], set()
    for alias, production in productions.items():
        observation = metadata.production_times.get(alias) if metadata else None
        if observation is None:
            limits.add("A declared production has no supplied event time and emits no JobEvent.")
            continue
        events.append({
            "eventTime": observation["observedAt"], "producer": PRODUCER,
            "schemaURL": event_schema + "#/$defs/JobEvent", "job": job_pairs[alias],
            "inputs": [declared(dataset) for dataset in production["inputs"]],
            "outputs": [declared(dataset) for dataset in production["outputs"]],
        })
    operation_ids = {}
    for run in runs.values():
        alias = run.get("production")
        if alias is None:
            limits.add("An observed run without a production link emits no OpenLineage events.")
            continue
        native = mapped_runs.get(run["id"], run.get("openLineageRunId"))
        if native is not None:
            try:
                UUID(native)
            except (ValueError, TypeError, AttributeError) as exc:
                raise CatalogError("CATALOG-LINEAGE-MAPPING", "An existing OpenLineage run ID must be a UUID.") from exc
        run_id = native or str(uuid5(NAMESPACE_URL, json_dumps((job_pairs[alias], run["reference"]))))
        if operation_ids.setdefault(str(UUID(run_id)), run["reference"]) != run["reference"]:
            raise CatalogError("CATALOG-LINEAGE-CONFLICT", "One OpenLineage run ID would combine different native operations.")
        run["openLineageRunId"] = run_id
        common = {"producer": PRODUCER, "schemaURL": event_schema + "#/$defs/RunEvent",
                  "run": {"runId": run_id}, "job": job_pairs[alias]}
        if run.get("startedAt"):
            events.append({**common, "eventType": "START", "eventTime": run["startedAt"]})
        else:
            limits.add("An observed run has no native START time.")
        terminal = {"succeeded": "COMPLETE", "failed": "FAIL", "aborted": "ABORT"}.get(run["outcome"])
        if terminal and run.get("endedAt"):
            events.append({**common, "eventType": terminal, "eventTime": run["endedAt"],
                           "inputs": [observed(version) for version in run["inputs"]],
                           "outputs": [observed(version) for version in run["outputs"]]})
        elif run["outcome"] == "running" and not run.get("startedAt"):
            events.append({**common, "eventType": "RUNNING", "eventTime": run["observedAt"],
                           "inputs": [observed(version) for version in run["inputs"]],
                           "outputs": [observed(version) for version in run["outputs"]]})
        else:
            limits.add("An observed run has no supported terminal event.")
    for event in events:
        _validate_event(event)
    return events, version_mappings, limits
