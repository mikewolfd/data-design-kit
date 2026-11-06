"""Assemble a local product catalog from loaded definitions and admitted metadata."""

from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from .catalog_access import (
    CatalogError, compare_equal, field_at, field_type, relationship_keys,
    resolve_query, resolve_relationship, run_checked_query,
)
from .catalog_exports import DCAT_ADAPTER, LINEAGE_ADAPTER, dcat_document, lineage_documents
from .catalog_metadata import EXAMPLE_ADAPTER, LOCAL_ADAPTER, SECTIONS, LocalMetadata, owner_record, stable_id
from .catalog_output import prepare_output_set, public_report, public_view, read_disclosure, write_output_set
from .catalog_semantics import admit_profile, resolved_key, resolved_relationship
from .core import check_inventory, load_project
from .documents import (
    FORMAT_CHECKER, OPENLINEAGE_SCHEMA, OPENLINEAGE_VERSION_FACET, ODCS_SCHEMA, ODPS_SCHEMA, REPOSITORY,
    DocumentError, ResourceLimit, json_dumps, resolve_path, schema_registry, validate_document,
)
from .results import VERSION, diagnostic, location

EXPORTS = {
    "dcat": "catalog.dcat", "catalog.dcat": "catalog.dcat",
    "openlineage": "lineage.openlineage", "lineage.openlineage": "lineage.openlineage",
}
METADATA_ADAPTERS = {"local": LOCAL_ADAPTER, "example": EXAMPLE_ADAPTER,
                     "example-commerce-metadata": EXAMPLE_ADAPTER}
GROUPS = ("catalog.assembly", "catalog.relationships", "catalog.qualification")
CHECK_IDS = {name: f"DDK-CATALOG-{number:03d}" for name, number in {
    "assembly": 7, "exports": 7, "metadata": 1, "products": 2, "datasets": 3,
    "relationships": 4, "qualification": 5, "catalog.dcat": 8, "lineage.openlineage": 9,
}.items()}
DETAILS = "urn:ddk:catalog:assembly"


@dataclass(frozen=True)
class CatalogResult:
    """One assembly's report, admitted view, and exact retained companion bytes.

    ``report`` follows the requested audience; ``local_report`` and
    ``local_catalog`` retain private diagnostics and the full admitted metadata
    and must not be published. ``catalog`` is absent when structural
    admission did not complete. Its
    presence does not establish qualification: callers must preserve ``report``
    and its check outcomes. Companions use the paths inventoried by the catalog;
    both the view and its companions have the requested disclosure applied.
    ``artifacts`` contains the complete standard output bytes only for a passed
    result. Inspecting an incomplete result does not make it publishable.
    """

    report: dict
    catalog: dict | None
    companions: Mapping[str, bytes]
    artifacts: Mapping[str, bytes]
    local_report: dict
    local_catalog: dict | None = None


def _result(report, catalog=None, companions=None, artifacts=None, *, public=False, local_catalog=None):
    view_report = public_report(report, catalog) if public else report
    return CatalogResult(view_report, catalog, companions or MappingProxyType({}),
                         artifacts or MappingProxyType({}), report, local_catalog)


def _bytes(value):
    return (json_dumps(value) + "\n").encode("utf-8")


def _schema(value, kind):
    issues = validate_document(value, kind)
    if issues:
        raise CatalogError(issues[0].code, issues[0].message, issues[0].pointer)


class Assembly:
    def __init__(self, inventory, exports):
        self.inventory = inventory
        self.report = inventory.report
        self.exports = exports
        self.records = {}
        self.datasets = {}
        self.dataset_schemas = {}
        self.productions = {}
        self.identities = defaultdict(list)
        self.relationships = {}
        self.queries = {}
        self.metadata = None
        self.policy = None
        self.catalog = None
        self.files = {}
        self.relationship_profile = None
        self.relationship_assessments = []

    def select_relationship_profile(self, profile):
        if profile is None:
            return
        self.relationship_profile = admit_profile(profile, self.inventory)
        selected = self.relationship_profile
        record = {"identity": deepcopy(selected.identity), "scope": "declaration-support-only"}
        if selected.source is not None:
            record["source"] = owner_record(selected.source)
            self.remember(record["source"], "implementation")
        self.report.metadata["relationshipProfile"] = record
        self.report.metadata["relationshipAssessments"] = self.relationship_assessments
        self.report.mapping_limits.add(
            "Selected relationship profiles assess declared semantics only. Actual matches, cardinality, external existence, "
            "and data qualification require separate evidence. Supplied implementation provenance does not establish its dependency closure."
        )

    def check(self, step, subject, error=None, *, path=None, required=None, evidence="inferred",
              related=(), evidence_records=()):
        group = {"relationships": "catalog.relationships", "qualification": "catalog.qualification",
                 "catalog.dcat": "catalog.dcat", "lineage.openlineage": "lineage.openlineage"}.get(step, "catalog.assembly")
        status = error.status if error is not None else "passed"
        description = str(error) if error is not None else None
        if required is None:
            required = group in self.report.required_groups or step not in {"relationships", "qualification"}
        source = self.inventory.display_path(Path(path)) if path is not None else self.inventory.display_path(self.inventory.path)
        self.report.add(CHECK_IDS[step], group, subject, status, required=required, evidence=evidence,
                        reason=description if status in {"unknown", "not_run"} else None,
                        evidence_records=evidence_records, diagnostics=[
                            diagnostic(error.code, description, path=source, pointer=error.pointer,
                                       related=related, severity="error" if status == "failed" else "warning")
                        ] if error is not None else [])

    def project_records(self):
        projects = set(doc.path for doc in self.inventory.projects.values())
        for path, document in self.inventory.documents.items():
            if not isinstance(document, Exception):
                self.remember(owner_record(document), "project" if path in projects else "definition")

    def remember(self, record, role):
        self.records[(record["uri"], role)] = {**record, "role": role}

    def definitions(self):
        index = defaultdict(list)
        for artifact in self.inventory.artifacts.values():
            if artifact.kind == "dataset":
                index[(artifact.identity, artifact.version)].append(artifact)
        selections = {}
        for namespace, document in self.inventory.projects.items():
            for entry in document.value.get("catalog", {}).get("ports", ()):
                product = self.inventory.resolve(entry["product"], namespace, "product")
                dataset = self.inventory.resolve(entry["dataset"], namespace, "dataset")
                key = (product.alias, entry["direction"], entry["port"], entry["version"])
                if key in selections:
                    raise CatalogError("CATALOG-PORT-AMBIGUOUS", "A product port has multiple explicit bindings.")
                selections[key] = dataset
        products = []
        for artifact in self.inventory.artifacts.values():
            if artifact.kind != "product":
                continue
            value = artifact.value
            if not value.get("version") or not FORMAT_CHECKER.conforms(artifact.identity, "uri"):
                raise CatalogError("CATALOG-PRODUCT-IDENTITY", "A catalog product needs an absolute ID and explicit version.")
            resolved = []
            seen = set()
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
                    self.dataset(explicit)
                    resolved.append({"product": artifact.alias, "direction": direction, "port": port["name"],
                                     "version": port["version"], "dataset": explicit.alias})
            if not any(port["direction"] == "output" for port in resolved):
                raise CatalogError("CATALOG-PORT-MISSING", "The product needs at least one participating output port.")
            products.append({"alias": artifact.alias, "id": artifact.identity, "version": artifact.version,
                             "definition": owner_record(artifact.document), "ports": resolved})
        if selections:
            raise CatalogError("CATALOG-PORT-VERSION", "An explicit binding has no corresponding versioned product port.")
        if not products:
            raise CatalogError("CATALOG-PRODUCT-MISSING", "The loaded scope contains no registered ODPS product.")
        for artifact in self.inventory.artifacts.values():
            if artifact.kind == "dataset" and artifact.registration.get("catalogId"):
                self.dataset(artifact)
        return products

    def dataset(self, artifact):
        if artifact.alias in self.datasets:
            return
        catalog_id = artifact.registration.get("catalogId")
        if not catalog_id:
            raise CatalogError("CATALOG-DATASET-IDENTITY", f"Dataset {artifact.alias!r} needs an explicit catalogId.")
        selected = artifact.effective
        if selected is None:
            raise CatalogError("CATALOG-DATASET-UNRESOLVED", "The selected ODCS object needs unresolved shared definitions.",
                               status="unknown")
        result = {"alias": artifact.alias, "id": catalog_id, "definition": {
            "contractId": artifact.identity, "version": artifact.version,
            "object": artifact.selection, "source": owner_record(artifact.document),
        }}
        for output, source, key in (("role", artifact.registration, "role"), ("title", selected, "businessName"),
                                    ("rowMeaning", selected, "dataGranularityDescription")):
            if source.get(key):
                result[output] = source[key]
        result.setdefault("title", selected["name"])
        self.datasets[artifact.alias] = result
        self.dataset_schemas[artifact.alias] = selected

    def alias(self, reference, namespace):
        artifact = self.inventory.resolve(reference, namespace, "dataset")
        self.dataset(artifact)
        return artifact.alias

    def declarations(self):
        for namespace, document in self.inventory.projects.items():
            configuration = document.value.get("catalog", {})
            for declaration in configuration.get("identities", ()):
                identity = deepcopy(declaration)
                alias = self.alias(identity["dataset"], namespace)
                identity["dataset"] = alias
                fields = [json_dumps(field["path"]) for field in identity["fields"]]
                if len(fields) != len(set(fields)):
                    raise CatalogError("CATALOG-KEY-INCOMPLETE", "An identity repeats a key path.")
                for field in identity["fields"]:
                    if not field["virtual"] and field_at(self.dataset_schemas[alias], field["path"]) is None:
                        raise CatalogError("CATALOG-KEY-PATH", "A declared identity path is missing from its ODCS object.")
                if identity in self.identities[alias]:
                    raise CatalogError("CATALOG-AUTHORITY-CONFLICT", "The same scoped identity is declared twice.")
                self.identities[alias].append(identity)
        for alias, definition in self.dataset_schemas.items():
            self.derive_identity(alias, definition)
        for namespace, document in self.inventory.projects.items():
            configuration = document.value.get("catalog", {})
            for declaration in configuration.get("relationships", ()):
                self.relationship(declaration, namespace, document.path)
            for declaration in configuration.get("recipes", ()):
                self.recipe(declaration, namespace, document.path)
        for recipe, _ in self.queries.values():
            if any(link not in self.relationships for link in recipe.get("contextualRelationships", ())):
                raise CatalogError("CATALOG-RECIPE-RELATIONSHIP", "A recipe references an unknown contextual relationship.")
            for link in recipe["relationships"]:
                relationship = self.relationships.get(link)
                if relationship is None:
                    raise CatalogError("CATALOG-RECIPE-RELATIONSHIP", "A recipe references an unknown relationship.")
                if any(relationship[side].get("dataset") not in recipe["inputs"].values()
                       for side in ("source", "target") if "dataset" in relationship[side]):
                    raise CatalogError("CATALOG-RECIPE-RELATIONSHIP", "The recipe does not bind both relationship endpoints.")
        self.production_definitions()

    def derive_identity(self, alias, schema):
        authored = [identity for identity in self.identities[alias] if identity["kind"] == "key"]
        if authored:
            return
        fields = [item for item in schema.get("customProperties", ())
                  if item.get("vendor") == "ddk" and item.get("property") == "rowIdentity"]
        if fields:
            names = fields[0]["value"]
        else:
            primary = [field for field in schema.get("properties", ()) if field.get("primaryKey") is True]
            if not primary:
                return
            positions = [field.get("primaryKeyPosition", -1) for field in primary]
            if len(primary) > 1 and (any(position < 1 for position in positions) or len(set(positions)) != len(positions)):
                raise CatalogError("CATALOG-KEY-INCOMPLETE", "A composite ODCS key needs unambiguous positions.")
            names = [field["name"] for field in sorted(primary, key=lambda field: field.get("primaryKeyPosition", -1))]
        if (len(fields) > 1 or not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names)
                or len(set(names)) != len(names)):
            raise CatalogError("CATALOG-KEY-INCOMPLETE", "An ODCS row identity needs unique ordered field names.")
        identity = {"dataset": alias, "kind": "key", "scope": "dataset_version",
                    "meaning": "Declared row identity from the selected ODCS object.", "fields": []}
        for name in names:
            path = [{"field": name}]
            field = field_at(schema, path)
            if field is None:
                raise CatalogError("CATALOG-KEY-PATH", f"Declared identity field {name!r} is missing.")
            identity["fields"].append({"path": path, "virtual": False,
                                       "physicalType": field.get("physicalType") or field.get("logicalType", "unknown")})
        self.identities[alias].append(identity)

    def relationship(self, declaration, namespace, path):
        row = deepcopy(declaration)
        identifier = row["id"]
        if identifier in self.relationships:
            raise CatalogError("CATALOG-AUTHORITY-CONFLICT", "A relationship ID is declared more than once.")
        keys = {}
        for side in ("source", "target"):
            endpoint = row[side]
            if "external" in endpoint:
                continue
            alias = self.alias(endpoint["dataset"], namespace)
            endpoint["dataset"] = alias
            fields = []
            for key_path in endpoint["paths"]:
                field = field_at(self.dataset_schemas[alias], key_path)
                if field is not None:
                    fields.append(resolved_key(key_path, field))
                    continue
                virtual = {(identity["scope"], item["physicalType"]) for identity in self.identities[alias]
                           for item in identity["fields"] if item["virtual"] and item["path"] == key_path}
                if len(virtual) > 1:
                    raise CatalogError("CATALOG-AUTHORITY-CONFLICT", "A virtual field has conflicting scope or type declarations.")
                if not virtual:
                    raise CatalogError("CATALOG-KEY-PATH", "A relationship endpoint does not resolve to one declared field.")
                scope, physical = next(iter(virtual))
                if scope == "release" and row["scope"] != "same_release":
                    raise CatalogError("CATALOG-RELEASE-SCOPE", "A release-local identity requires the same exact release.")
                fields.append(resolved_key(key_path, {"physicalType": physical, "logicalType": physical}, scope))
            keys[side] = fields
        if "target" in keys:
            if len(keys["source"]) != len(keys["target"]):
                raise CatalogError("CATALOG-KEY-INCOMPLETE", "Both endpoints must supply every ordered key component.")
            for side, cardinalities in (("source", {"one_to_one", "one_to_many"}),
                                        ("target", {"one_to_one", "many_to_one"})):
                endpoint = row[side]
                identities = [identity for identity in self.identities[endpoint["dataset"]] if identity["kind"] == "key"]
                if row["cardinality"] in cardinalities and identities and not any(
                    endpoint["paths"] == [field["path"] for field in identity["fields"]] for identity in identities
                ):
                    raise CatalogError("CATALOG-KEY-INCOMPLETE", "The unique endpoint needs its full declared key in order.")
            if row["match"] == "equal" and any(
                left.shared_type is not None and right.shared_type is not None and left.shared_type != right.shared_type
                for left, right in zip(keys["source"], keys["target"])
            ):
                raise CatalogError("CATALOG-KEY-TYPE", "Equal key components need compatible declared types.")
        error = None
        if row["match"] == "project_rule" or row["nulls"] == "unknown" or any(
            field.shared_type is None for parts in keys.values() for field in parts
        ) or "target" not in keys:
            error = CatalogError("CATALOG-MATCH-UNSUPPORTED", "The relationship needs reasoning beyond the shared equality profile.",
                                 status="unknown")
            if self.relationship_profile is not None and row["nulls"] != "unknown":
                try:
                    assessment = self.relationship_profile.assess(resolved_relationship(row, keys))
                    error = None if assessment.status == "supported" else CatalogError(
                        "CATALOG-PROFILE-INCOMPATIBLE" if assessment.status == "failed" else "CATALOG-PROFILE-UNSUPPORTED",
                        assessment.reason, status="failed" if assessment.status == "failed" else "unknown",
                    )
                    status, reason = assessment.status, assessment.reason
                except CatalogError as exc:
                    error = exc
                    status, reason = "unknown", str(exc)
                self.relationship_assessments.append({
                    "relationship": identifier, "profile": deepcopy(self.relationship_profile.identity),
                    "status": status, "reason": reason, "scope": "declaration-support-only",
                    **({"externalExistence": "not_assessed"} if "target" not in keys else {}),
                })
        self.check("relationships", identifier, error, path=path)
        self.relationships[identifier] = row

    def recipe(self, declaration, namespace, path):
        row = deepcopy(declaration)
        if row["id"] in self.queries:
            raise CatalogError("CATALOG-AUTHORITY-CONFLICT", "A recipe ID is declared more than once.")
        if "parameterOrder" in row and set(row["parameterOrder"]) != row["parameters"].get("properties", {}).keys():
            raise CatalogError("CATALOG-RECIPE-PARAMETERS", "Parameter order must name every parameter property exactly once.")
        row["inputs"] = {name: self.alias(alias, namespace) for name, alias in row["inputs"].items()}
        if "resultDataset" in row:
            row["resultDataset"] = self.alias(row["resultDataset"], namespace)
        source = resolve_path(path, row["sql"], self.inventory.permitted_roots)
        limit = self.inventory.limits["maxDocumentBytes"]
        with source.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ResourceLimit("Recipe SQL exceeds the document byte limit.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CatalogError("CATALOG-RECIPE-UTF8", "Recipe SQL requires UTF-8.") from exc
        record = {"uri": source.as_uri(), "sha256": sha256(data).hexdigest()}
        self.remember(record, "recipe")
        row["sql"] = "queries/" + sha256(row["id"].encode()).hexdigest() + ".sql"
        self.queries[row["id"]] = (row, data)

    def production_definitions(self):
        for artifact in self.inventory.artifacts.values():
            if artifact.kind == "component":
                inputs, outputs = artifact.value["inputs"], artifact.value["outputs"]
            elif artifact.kind == "design":
                inputs, outputs = artifact.value["sources"], artifact.value["exports"]
            else:
                continue
            aliases = []
            for members in (inputs, outputs):
                aliases.append(sorted({self.inventory.resolve(member["dataset"], artifact.namespace, "dataset").alias
                                       for member in members.values()}))
            if not set((*aliases[0], *aliases[1])) <= self.datasets.keys() or not aliases[1]:
                continue
            self.productions[artifact.alias] = {
                "alias": artifact.alias, "identity": {"id": artifact.identity, "version": artifact.version},
                "definition": owner_record(artifact.document), "inputs": aliases[0], "outputs": aliases[1],
            }

    def create(self, products):
        project = self.inventory.root
        details = {
            "datasetDefinitions": {alias: self.dataset_schemas[alias] for alias in sorted(self.datasets)},
            "scope": self.inventory.scope,
            "projectExtensions": [
                {"project": {"id": document.value["id"], "version": document.value["version"]},
                 "namespace": namespace, "extensions": deepcopy(document.value["extensions"])}
                for namespace, document in sorted(self.inventory.projects.items()) if document.value.get("extensions")
            ],
        }
        if self.relationship_profile is not None:
            details["relationshipProfile"] = deepcopy(self.report.metadata["relationshipProfile"])
            details["relationshipAssessments"] = sorted(self.relationship_assessments, key=json_dumps)
            self.report.metadata["relationshipAssessments"] = details["relationshipAssessments"]
        if self.metadata:
            details["recordOwners"] = self.metadata.owners
            details["registeredRunInputs"] = self.metadata.bound_inputs
            details["stagingObservations"] = sorted(self.metadata.staging_observations, key=json_dumps)
            if self.metadata.managed_jobs:
                details["managedExecutions"] = deepcopy(self.metadata.managed_jobs)
            details["requiredQualityChecks"] = sorted(self.metadata.qualification, key=json_dumps)
            details["productionObservations"] = self.metadata.production_times
            if self.metadata.illustrative:
                details["illustrativeMetadata"] = True
        self.catalog = {
            "kind": "catalog", "specVersion": "0.1", "version": VERSION,
            "id": project.value.get("catalog", {}).get("id", stable_id("catalog", project.value["id"])),
            "project": {"id": project.value["id"], "version": project.value["version"]}, "audience": "local",
            "sourceInventory": [], "adapters": [], "products": products,
            "datasets": list(self.datasets.values()),
            "identities": [item for aliases in self.identities.values() for item in aliases],
            "relationships": list(self.relationships.values()),
            "recipes": [recipe for recipe, _ in self.queries.values()],
            "productions": list(self.productions.values()), "files": [],
            **{section: self.metadata.observations[section] if self.metadata else [] for section in SECTIONS},
            "extensions": {DETAILS: details},
        }
        for section in (*SECTIONS, "products", "datasets", "identities", "relationships", "recipes", "productions"):
            self.catalog[section].sort(key=json_dumps)
        self.refresh_inventory()

    def refresh_inventory(self):
        self.catalog["sourceInventory"] = [self.records[key] for key in sorted(self.records)]
        self.catalog["adapters"] = list(self.adapters())

    def adapters(self):
        yield {"id": "ddk.catalog", "version": VERSION}
        if self.relationship_profile is not None:
            yield deepcopy(self.relationship_profile.identity)
        if self.metadata:
            yield self.metadata.adapter
        if "catalog.dcat" in self.exports:
            yield DCAT_ADAPTER
        if "lineage.openlineage" in self.exports:
            yield LINEAGE_ADAPTER

    def verify(self):
        _schema(self.catalog, "catalog")
        global_ids = dict.fromkeys((self.catalog["id"], self.catalog["project"]["id"]))

        def conflict(message, *rows):
            origins = [location(row["record"]["uri"]) for row in rows if row and "record" in row]
            raise CatalogError("CATALOG-AUTHORITY-CONFLICT", message, related=origins)
        datasets = {row["alias"] for row in self.catalog["datasets"]}
        dataset_ids = {row["id"] for row in self.catalog["datasets"]}
        if global_ids.keys() & dataset_ids:
            conflict("Dataset identifiers overlap the catalog or project.")
        global_ids.update(dict.fromkeys(dataset_ids))
        for section in ("sources", "versions", "representations", "releases", "runs", "relationships", "recipes"):
            for row in self.catalog[section]:
                if row["id"] in global_ids:
                    conflict("An identity is claimed by more than one record.", global_ids[row["id"]], row)
                global_ids[row["id"]] = row

        facts = {}
        for section in ("sources", "versions", "releases", "runs"):
            for row in self.catalog[section]:
                key = (section, json_dumps(row["reference"]), row.get("scope", ""), row.get("dataset", ""))
                old = facts.setdefault(key, row)
                if old != row:
                    conflict("One native identity has conflicting observations.", old, row)
        versions = {row["id"]: row for row in self.catalog["versions"]}
        sources = {row["id"] for row in self.catalog["sources"]}
        releases = {row["id"] for row in self.catalog["releases"]}
        for version in versions.values():
            if version["dataset"] not in datasets or not set(version["sources"]) <= sources:
                raise CatalogError("CATALOG-REFERENCE-UNRESOLVED", "A version has an unresolved definition or source occurrence.")
            for coverage in version.get("coverage", ()):
                observed, expected = coverage.get("observed"), coverage.get("expected")
                if ((coverage["status"] == "complete" and observed != expected)
                        or (coverage["status"] == "partial" and observed >= expected)):
                    raise CatalogError("CATALOG-COVERAGE-CONFLICT", "Coverage counts contradict the stated coverage status.")
        for row in self.catalog["representations"]:
            if row["version"] not in versions:
                raise CatalogError("CATALOG-REFERENCE-UNRESOLVED", "A representation has no exact dataset version.")
        for row in self.catalog["releases"]:
            if not set(row["members"]) <= versions.keys():
                raise CatalogError("CATALOG-REFERENCE-UNRESOLVED", "A release has an unresolved member.")
        for row in self.catalog["selections"]:
            if row["release"] not in releases:
                raise CatalogError("CATALOG-REFERENCE-UNRESOLVED", "A publisher selection has an unresolved release.")
        for row in self.catalog["runs"]:
            if not set((*row["inputs"], *row["outputs"])) <= versions.keys():
                raise CatalogError("CATALOG-REFERENCE-UNRESOLVED", "A run has an unresolved dataset version.")
            if "production" in row and row["production"] not in self.productions:
                raise CatalogError("CATALOG-PRODUCTION-MISSING", "A run has an unresolved production definition.")
        for row in self.catalog["checks"]:
            if row["subject"] not in versions:
                raise CatalogError("CATALOG-REFERENCE-UNRESOLVED", "A check has an unresolved target version.")

    def qualify(self):
        if self.metadata is None:
            obligations = []
        else:
            obligations = self.metadata.qualification
        key_fields = ("subject", "rule", "evaluator", "scope")

        def key(item):
            return tuple(json_dumps(item[name]) for name in key_fields)

        observations = defaultdict(list)
        for item in self.catalog["checks"]:
            observations[key(item)].append(item)
        versions = {item["id"]: item["dataset"] for item in self.catalog["versions"]}
        quality_issues = self.metadata.quality_issues if self.metadata else []
        for index, error in enumerate(quality_issues):
            self.check("qualification", f"receipt-{index}", error, required=True)
        if not obligations and not quality_issues and "catalog.qualification" in self.report.required_groups:
            self.check("qualification", "catalog", CatalogError(
                "CATALOG-EVIDENCE-MISSING", "The input contains no requested version-bound quality rules.", status="not_run"))
        for item in sorted(obligations, key=json_dumps):
            if not set(key_fields) <= item.keys() or not isinstance(item["subject"], str):
                raise CatalogError("CATALOG-EVIDENCE-SCOPE", "A quality obligation needs an exact version, rule, evaluator, and scope.")
            identifier = stable_id("quality-obligation", key(item))
            if not any(check["subject"] == identifier for check in self.report.checks):
                candidates = observations[key(item)]
                if item["subject"] not in versions:
                    raise CatalogError("CATALOG-EVIDENCE-SCOPE", "The quality obligation targets an unloaded version.", status="unknown")
                if len({candidate["status"] for candidate in candidates}) > 1:
                    raise CatalogError("CATALOG-AUTHORITY-CONFLICT", "Checks of the same exact scope report contradictory results.")
                if not candidates:
                    similar = any(check["rule"]["id"] == item["rule"]["id"]
                                  and versions.get(check["subject"]) == versions[item["subject"]]
                                  for check in self.catalog["checks"])
                    error = CatalogError("CATALOG-EVIDENCE-SCOPE" if similar else "CATALOG-EVIDENCE-MISSING",
                                         "No check evidence matches the exact target, rule, evaluator, and scope.",
                                         status="unknown" if similar else "not_run")
                    self.check("qualification", identifier, error, required=True)
                    continue
                check = candidates[0]
                status = check["status"]
                error = None if status == "passed" else CatalogError(
                    "CATALOG-EVIDENCE-MISSING" if status in {"unknown", "not_run"} else "CATALOG-QUALITY-FAILED",
                    check.get("reason", "The native quality check reported failure."), status=status,
                )
                evidence = ()
                if status in {"passed", "failed"} and check["record"].get("sha256"):
                    evidence = ({"kind": "native-report", "path": check["record"]["uri"],
                                 "sha256": check["record"]["sha256"], "tool": check["evaluator"]["id"]},)
                self.check("qualification", identifier, error, required=True,
                           evidence="executed" if evidence else "declared", evidence_records=evidence)

    def add_file(self, path, role, data):
        if path in self.files:
            raise CatalogError("CATALOG-OUTPUT-CONFLICT", "A generated companion path is duplicated.")
        self.files[path] = (role, data)

    def output_documents(self):
        for recipe in self.catalog["recipes"]:
            self.add_file(recipe["sql"], "recipe", self.queries[recipe["id"]][1])
        if "catalog.dcat" in self.exports:
            try:
                self.add_file("discovery.dcat.json", "dcat", _bytes(dcat_document(self.catalog)))
                self.check("catalog.dcat", "export")
                self.report.completed_profiles.add("catalog.dcat")
            except CatalogError as error:
                self.check("catalog.dcat", "export", error)
        if "lineage.openlineage" in self.exports:
            try:
                if self.policy is not None:
                    raise CatalogError("ADAPTER-CAPABILITY-MISSING", "Public OpenLineage mapping is unavailable.",
                                       status="not_run")
                events, mappings, limits = lineage_documents(self.catalog, self.metadata)
                self.catalog.setdefault("extensions", {}).setdefault(DETAILS, {})["openLineageVersions"] = mappings
                for index, event in enumerate(events):
                    self.add_file(f"lineage/{index:04d}.openlineage.json", "openlineage", _bytes(event))
                self.report.mapping_limits.update(limits)
                if not events:
                    raise CatalogError("CATALOG-LINEAGE-NO-EVENTS", "No supplied metadata supports an OpenLineage event.",
                                       status="not_run")
                self.check("lineage.openlineage", "export")
                self.report.completed_profiles.add("lineage.openlineage")
            except CatalogError as error:
                self.check("lineage.openlineage", "export", error)


def assemble_catalog(project_path, *, metadata=None, metadata_adapter=None, exports=(), output=None,
                     current_selection=None, disclosure_policy=None, audience=None, required_groups=(),
                     permitted_roots=(), limits=None, relationship_profile=None):
    """Load once and return admitted metadata with its report and companions.

    An admitted view remains inspectable when qualification is incomplete or
    failed. Only a passed report permits atomic publication to ``output``.
    """
    if isinstance(exports, str):
        exports = (exports,)
    profiles = sorted({EXPORTS.get(name, name) for name in exports})
    public = audience == "public" or disclosure_policy is not None
    inventory = load_project(project_path, permitted_roots, limits)
    assembly = Assembly(inventory, profiles)
    report = inventory.report
    report.available_capabilities.update((*GROUPS, *EXPORTS.values()))
    core = check_inventory(inventory, (*required_groups, "catalog.assembly", *profiles),
                           handled_groups=(*GROUPS, *profiles))
    if core["decision"] != "passed":
        return _result(core, public=public)
    for profile in profiles:
        if profile not in EXPORTS.values():
            report.missing_capabilities.add(profile)
            error = CatalogError("ADAPTER-CAPABILITY-MISSING", f"No adapter supports export {profile!r}.", status="not_run")
            assembly.check("exports", profile, error, required=True)
    if report.missing_capabilities:
        return _result(report.build(), public=public)
    admitted = None
    local_admitted = None
    companions = MappingProxyType({})
    artifacts = MappingProxyType({})
    step = "products"
    failure_path = inventory.path
    try:
        assembly.project_records()
        products = assembly.definitions()
        assembly.check("products", "ports")
        step = "relationships"
        assembly.select_relationship_profile(relationship_profile)
        assembly.declarations()
        step = "metadata"
        if metadata is not None or metadata_adapter is not None:
            if metadata is None or metadata_adapter is None:
                raise CatalogError("CATALOG-METADATA-ADAPTER", "Supply a local metadata input and its explicit adapter.")
            if metadata_adapter not in METADATA_ADAPTERS:
                report.missing_capabilities.add(f"metadata:{metadata_adapter}")
                raise CatalogError("ADAPTER-CAPABILITY-MISSING", f"No metadata adapter supports {metadata_adapter!r}.",
                                   status="not_run")
            failure_path = Path(metadata).resolve()
            document = inventory.read(failure_path)
            try:
                assembly.metadata = LocalMetadata(document, inventory, METADATA_ADAPTERS[metadata_adapter],
                                                  assembly.datasets, assembly.productions).read()
            except (KeyError, TypeError, AttributeError) as exc:
                raise CatalogError("CATALOG-METADATA-SHAPE", "An owner record contains malformed fields.") from exc
            for document in assembly.metadata.records.values():
                assembly.remember(owner_record(document), "metadata")
            report.mapping_limits.update(assembly.metadata.limits)
            for code, message, path in assembly.metadata.operational_errors:
                report.error(diagnostic(code, message, path=inventory.display_path(path)))
            if ((assembly.metadata.qualification or assembly.metadata.quality_issues)
                    and "catalog.qualification" not in report.required_groups):
                report.required_groups.append("catalog.qualification")
        else:
            report.mapping_limits.add("Definition-only catalog. Availability, qualification, and observed lineage are unresolved.")
        step = "assembly"
        failure_path = inventory.path
        if audience not in {None, "local", "public"} or (audience == "local" and disclosure_policy is not None):
            raise CatalogError("CATALOG-DISCLOSURE", "Select either a local view or an explicit public disclosure policy.")
        if audience == "public" and disclosure_policy is None:
            raise CatalogError("CATALOG-DISCLOSURE", "A public view needs an explicit disclosure policy.")
        if disclosure_policy is not None:
            policy_doc = inventory.read(Path(disclosure_policy).resolve())
            assembly.policy = read_disclosure(policy_doc)
            assembly.remember(owner_record(policy_doc), "policy")
        _, _, schemas = schema_registry()
        standards = [("odcs", ODCS_SCHEMA), ("odps", ODPS_SCHEMA)]
        if "lineage.openlineage" in profiles:
            standards.extend((("openlineage", OPENLINEAGE_SCHEMA), ("openlineage-facet", OPENLINEAGE_VERSION_FACET)))
        for _, path in standards:
            assembly.remember({"uri": (REPOSITORY / path).as_uri(), "sha256": schemas[path]}, "schema")
        assembly.create(products)
        if current_selection is not None:
            if "catalog.dcat" not in profiles:
                raise CatalogError("CATALOG-SELECTION-UNUSED", "A current selection requires the DCAT export.")
            if isinstance(current_selection, (tuple, list)) and len(current_selection) == 2:
                current_selection = dict(zip(("authority", "purpose"), current_selection))
            assembly.catalog["currentSelection"] = current_selection
        assembly.verify()
        assembly.check("assembly", "scope")
        report.completed_profiles.add("catalog")
        step = "qualification"
        assembly.qualify()
        local_admitted = assembly.catalog
        step = "assembly"
        if assembly.policy is not None:
            assembly.catalog, omitted_recipes = public_view(assembly.catalog, assembly.policy, DETAILS)
            for identifier in omitted_recipes:
                assembly.check("assembly", stable_id("withheld-recipe", identifier),
                               CatalogError("CATALOG-RECIPE-WITHHELD", "A recipe was withheld by the public disclosure policy.",
                                            status="not_run"), required=False)
            _schema(assembly.catalog, "catalog")
        assembly.output_documents()
        assembly.catalog["files"] = [{"path": name, "role": role, "sha256": sha256(data).hexdigest()}
                                     for name, (role, data) in sorted(assembly.files.items())]
        _schema(assembly.catalog, "catalog")
        admitted = assembly.catalog
        companions = MappingProxyType({name: data for name, (_, data) in assembly.files.items()})
        result = report.build()
        prepared = None
        if result["decision"] == "passed":
            prepared = prepare_output_set(
                assembly.catalog, assembly.files, result, profiles,
                assembly.metadata.adapter if assembly.metadata else None, inventory,
            )
            artifacts = MappingProxyType({name: data for name, (_, data) in prepared.items()})
        # Qualification can remain unresolved while the assembled discovery record is inspectable.
        if output is None or result["decision"] != "passed":
            report.metadata["catalog"] = assembly.catalog
        if output is not None and result["decision"] == "passed":
            report.metadata["generatedFiles"] = write_output_set(
                output, assembly.catalog, assembly.files, result, profiles,
                assembly.metadata.adapter if assembly.metadata else None, inventory,
                prepared=prepared,
            )
        return _result(report.build(), admitted, companions, artifacts, public=public, local_catalog=local_admitted)
    except (CatalogError, DocumentError) as exc:
        error = exc if isinstance(exc, CatalogError) else CatalogError(exc.code, str(exc), exc.pointer)
        assembly.check(step, "build", error, path=failure_path, required=True, related=error.related)
    except (OSError, ResourceLimit) as exc:
        report.error(diagnostic("EXEC-RESOURCE-LIMIT" if isinstance(exc, ResourceLimit) else "CATALOG-IO",
                                str(exc), path=failure_path))
    if admitted is not None:
        admitted["files"] = [{"path": name, "role": role, "sha256": sha256(data).hexdigest()}
                             for name, (role, data) in sorted(assembly.files.items())]
    return _result(report.build(), admitted, companions, public=public, local_catalog=local_admitted)


def build_catalog(project_path, *, metadata=None, metadata_adapter=None, exports=(), output=None,
                  current_selection=None, disclosure_policy=None, audience=None, required_groups=(),
                  permitted_roots=(), limits=None, relationship_profile=None):
    """Build and optionally publish a catalog; return its checking report."""
    return assemble_catalog(
        project_path, metadata=metadata, metadata_adapter=metadata_adapter, exports=exports, output=output,
        current_selection=current_selection, disclosure_policy=disclosure_policy, audience=audience,
        required_groups=required_groups, permitted_roots=permitted_roots, limits=limits,
        relationship_profile=relationship_profile,
    ).local_report
