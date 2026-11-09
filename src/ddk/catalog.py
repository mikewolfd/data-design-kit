"""Assemble a local product catalog from loaded definitions and admitted metadata."""

import json
from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field as dataclass_field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from urllib.parse import unquote, urlsplit

from .catalog_access import (
    CatalogError, compare_equal, field_at, field_type, relationship_keys, row_identity_names,
    resolve_query, resolve_relationship, run_checked_query,
)
from .catalog_exports import DCAT_ADAPTER, LINEAGE_ADAPTER, dcat_document, lineage_documents
from .catalog_graph import GRAPH_ADAPTER, RML_ADAPTER, child_iri, graph_document, rml_documents, turtle_bytes
from .catalog_delivery import PAIRED_VIEW, paired_view_record
from .catalog_descriptions import dataset_facts, product_facts
from .catalog_metadata import EXAMPLE_ADAPTER, LOCAL_ADAPTER, SECTIONS, LocalMetadata, check_report, owner_record, stable_id
from .catalog_output import prepare_output_set, public_report, public_view, read_disclosure, write_output_set
from .catalog_semantics import admit_profile, resolved_key, resolved_relationship
from .core import check_inventory, load_project
from .definitions import enum_values
from .policies import ddk_annotations
from .ports import product_ports
from .documents import (
    OPENLINEAGE_SCHEMA, OPENLINEAGE_VERSION_FACET, ODCS_SCHEMA, ODPS_SCHEMA, REPOSITORY,
    DocumentError, ResourceLimit, json_dumps, resolve_path, schema_registry, validate_document,
)
from .results import VERSION, diagnostic, location

EXPORTS = {
    "dcat": "catalog.dcat", "catalog.dcat": "catalog.dcat",
    "openlineage": "lineage.openlineage", "lineage.openlineage": "lineage.openlineage",
    "graph": "catalog.graph", "graph.ttl": "catalog.graph", "catalog.graph": "catalog.graph",
    "rml": "catalog.rml", "catalog.rml": "catalog.rml",
}
METADATA_ADAPTERS = {"local": LOCAL_ADAPTER, "example": EXAMPLE_ADAPTER,
                     "example-commerce-metadata": EXAMPLE_ADAPTER}
GROUPS = ("catalog.assembly", "catalog.relationships", "catalog.qualification")
RECIPE_GROUP = "catalog.recipes"
CHECK_IDS = {name: f"DDK-CATALOG-{number:03d}" for name, number in {
    "assembly": 7, "exports": 7, "metadata": 1, "products": 2, "datasets": 3,
    "relationships": 4, "qualification": 5, "catalog.dcat": 8, "lineage.openlineage": 9, "recipes": 11,
    "catalog.graph": 13, "catalog.rml": 14,
}.items()}
DETAILS = "urn:ddk:catalog:assembly"
MODEL_FIELDS = ("id", "version", "configurationSha256", "review")
# A method column's values: the origin vocabulary plus two kinds of rule (DDK-CATALOG-003).
METHOD_VALUES = {"publisher", "third_party", "rule", "human", "model", "publisher_crosswalk", "exact_identifier"}


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
    local_artifacts: Mapping[str, bytes] = dataclass_field(default_factory=lambda: MappingProxyType({}))


def _result(report, catalog=None, companions=None, artifacts=None, *, public=False, local_catalog=None,
            local_artifacts=None):
    view_report = public_report(report, catalog) if public else report
    return CatalogResult(view_report, catalog, companions or MappingProxyType({}),
                         artifacts or MappingProxyType({}), report, local_catalog,
                         local_artifacts or MappingProxyType({}))


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
        self.graph_turtle = False
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
        self.native_rule_profile = None
        self.managed_schema_profiles = {}
        self.relationship_assessments = []
        self.unknown_sla = set()
        self.concept_fields = {}
        self.registered_definitions = None
        self.concept_rules = None
        self.recipe_sources = {}
        self.recipe_parser = None

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
              related=(), evidence_records=(), severity=None):
        group = {"relationships": "catalog.relationships", "qualification": "catalog.qualification", "recipes": RECIPE_GROUP,
                 "catalog.dcat": "catalog.dcat", "lineage.openlineage": "lineage.openlineage",
                 "catalog.graph": "catalog.graph", "catalog.rml": "catalog.rml"}.get(step, "catalog.assembly")
        status = error.status if error is not None else "passed"
        description = str(error) if error is not None else None
        if required is None:
            required = group in self.report.required_groups or step not in {"relationships", "qualification"}
        source = self.inventory.display_path(Path(path)) if path is not None else self.inventory.display_path(self.inventory.path)
        self.report.add(CHECK_IDS[step], group, subject, status, required=required, evidence=evidence,
                        reason=description if status in {"unknown", "not_run"} else None,
                        evidence_records=evidence_records, diagnostics=[
                            diagnostic(error.code, description, path=source, pointer=error.pointer, related=related,
                                       severity=severity or ("error" if status == "failed" else "warning"))
                        ] if error is not None else [])

    def project_records(self):
        projects = set(doc.path for doc in self.inventory.projects.values())
        for path, document in self.inventory.documents.items():
            if not isinstance(document, Exception):
                self.remember(owner_record(document), "project" if path in projects else "definition")

    def remember(self, record, role):
        self.records[(record["uri"], role)] = {**record, "role": role}

    def definitions(self):
        products = []
        for artifact, ports in product_ports(self.inventory):
            for *_, dataset in ports:
                self.dataset(dataset)
            products.append({"alias": artifact.alias, "id": artifact.identity, "version": artifact.version,
                             "definition": owner_record(artifact.document), "ports": [
                                 {"product": artifact.alias, "direction": direction, "port": port,
                                  "version": version, "dataset": dataset.alias}
                                 for direction, port, version, dataset in ports],
                             **product_facts(artifact.value)})
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
        for output, source, key in (("role", artifact.registration, "role"), ("origin", artifact.registration, "origin"),
                                    ("model", artifact.registration, "model"),
                                    ("title", selected, "businessName"), ("rowMeaning", selected, "dataGranularityDescription")):
            if source.get(key):
                result[output] = deepcopy(source[key])
        result.setdefault("title", selected["name"])
        facts, unknown_sla = dataset_facts(artifact.value, selected)
        result.update(facts)
        for index in unknown_sla:
            self.unknown_sla.add((artifact.identity, artifact.version, index, artifact.path))
        self.datasets[artifact.alias] = result
        self.dataset_schemas[artifact.alias] = selected
        self.origin_evidence(artifact, result)
        self.method_column(artifact, selected, result)

    def origin_evidence(self, artifact, result):
        """DDK-CATALOG-003: `derived` lacks the rule-or-person detail, and a model needs its method record."""
        origin, subject = result.get("origin"), f"{artifact.alias}/origin"
        if origin == "derived":
            self.check("datasets", subject, CatalogError(
                "CATALOG-ORIGIN-DETAIL", "Origin `derived` does not say whether a rule or a person derived the content; "
                "declare `rule` or `human`.", status="unknown"), path=artifact.path, required=False, evidence="declared")
        elif origin == "model":
            missing = [key for key in MODEL_FIELDS if key not in result.get("model", {})]
            self.check("datasets", subject, CatalogError(
                "CATALOG-ORIGIN-METHOD", f"The model method record lacks {', '.join(missing)}, so the origin evidence "
                "is unknown.", status="unknown") if missing else None, path=artifact.path, required=False,
                evidence="declared")

    def method_column(self, artifact, selected, result):
        """A declared method column must exist, and any values it declares must come from the method vocabulary."""
        names = ddk_annotations(selected, "methodColumn")
        if not names:
            return
        column = names[0]
        prop = next((item for item in selected.get("properties", ()) if item["name"] == column), None)
        outside = sorted(set(enum_values(prop) or ()) - METHOD_VALUES) if prop else []
        error = (CatalogError("CATALOG-METHOD-COLUMN", f"The declared method column {column!r} is not a top-level field.")
                 if prop is None else CatalogError(
                     "CATALOG-METHOD-COLUMN", f"Method column {column!r} declares values outside the method vocabulary: "
                     + ", ".join(map(str, outside)) + ".") if outside else None)
        if error is None:
            result["methodColumn"] = column
        self.check("datasets", f"{artifact.alias}/method-column", error, path=artifact.path, evidence="declared")

    def catalog_id(self):
        root = self.inventory.root.value
        return root.get("catalog", {}).get("id", stable_id("catalog", root["id"]))

    def field_definitions(self, alias):
        """Fields of one dataset that reference a registered shared definition: {path as JSON: definition alias}."""
        if alias not in self.concept_fields:
            if self.registered_definitions is None:
                self.registered_definitions = {}
                for item in self.inventory.artifacts.values():
                    if item.kind == "definition":
                        self.registered_definitions.setdefault(item.path, item.alias)
            artifact, registered, found = self.inventory.artifacts[alias], self.registered_definitions, {}

            def walk(prop, path):
                for link in prop.get("authoritativeDefinitions", ()):
                    if link.get("type") != "definition" or not link.get("url") or "#" in link["url"]:
                        continue
                    try:  # properties and items are never inherited, so links resolve from the dataset file
                        target = resolve_path(artifact.path, unquote(urlsplit(link["url"]).path),
                                              self.inventory.permitted_roots)
                    except DocumentError:
                        continue
                    if target in registered:
                        found[json_dumps(path)] = registered[target]
                        break
                for child in prop.get("properties", ()):
                    walk(child, [*path, {"field": child["name"]}])
                if isinstance(prop.get("items"), dict):
                    walk(prop["items"], [*path, {"each": True}])

            for prop in self.dataset_schemas[alias].get("properties", ()):
                walk(prop, [{"field": prop["name"]}])
            self.concept_fields[alias] = found
        return self.concept_fields[alias]

    def concept_iri(self, definition):
        value = self.inventory.artifacts[definition].value
        return (ddk_annotations(value, "concept") or [child_iri(self.catalog_id(), "concept", definition)])[0]

    def concepts(self):
        """DDK-CATALOG-004 discovery by concept: each shared definition with the dataset fields that inherit it."""
        uses = defaultdict(list)
        for alias in sorted(self.datasets):
            for path, definition in sorted(self.field_definitions(alias).items()):
                uses[definition].append({"dataset": alias, "path": json.loads(path)})
        rows = []
        for definition, fields in sorted(uses.items()):
            value = self.inventory.artifacts[definition].value
            row = {"concept": self.concept_iri(definition), "definition": definition, "fields": fields}
            if isinstance(value.get("description"), str):
                row["description"] = value["description"]
            for key in ("exactMatch", "closeMatch"):
                matches = sorted({iri for entry in ddk_annotations(value, key)
                                  for iri in (entry if isinstance(entry, list) else [entry])})
                if matches:
                    row[key] = matches
            urls = sorted({link["url"] for link in value.get("authoritativeDefinitions", ())
                           if link.get("type") == "canonicalUrl" and link.get("url")})
            if urls:
                row["canonicalUrls"] = urls
            rows.append(row)
        return rows

    def concept_policy(self):
        """Severity and compatible definition pairs from `concept-joins` policy rules; warning by default."""
        if self.concept_rules is None:
            severity, compatible = "warning", set()
            for artifact in self.inventory.artifacts.values():
                if artifact.kind != "policy":
                    continue
                for rule in artifact.value.get("rules", ()):
                    if rule.get("check") != "concept-joins":
                        continue
                    severity = "error" if rule["severity"] == "error" else severity
                    for pair in rule.get("compatible", ()):
                        try:
                            compatible.add(frozenset(self.inventory.resolve(reference, artifact.namespace, "definition").alias
                                                     for reference in pair))
                        except DocumentError:
                            continue
            self.concept_rules = (severity, compatible)
        return self.concept_rules

    def concept_join(self, row, path):
        """Both endpoints of an equal-value join that inherit shared definitions must inherit the same one."""
        if "dataset" not in row["target"] or row["match"] != "equal":
            return
        severity, compatible = self.concept_policy()
        pairs = [(self.field_definitions(row["source"]["dataset"]).get(json_dumps(left)),
                  self.field_definitions(row["target"]["dataset"]).get(json_dumps(right)))
                 for left, right in zip(row["source"]["paths"], row["target"]["paths"])]
        pairs = [(left, right) for left, right in pairs if left and right]
        if not pairs:
            return

        def exact(definition):
            return {iri for entry in ddk_annotations(self.inventory.artifacts[definition].value, "exactMatch")
                    for iri in (entry if isinstance(entry, list) else [entry])}

        def same(left, right):  # skos:exactMatch is symmetric, so either side may declare it
            return (left == right or frozenset((left, right)) in compatible
                    or self.concept_iri(left) == self.concept_iri(right)
                    or self.concept_iri(right) in exact(left) or self.concept_iri(left) in exact(right))

        mismatched = [f"{left} to {right}" for left, right in pairs if not same(left, right)]
        error = CatalogError("CATALOG-RELATIONSHIP-CONCEPT", f"{row['id']} joins fields of different shared definitions "
                             f"({'; '.join(mismatched)}). A concept-joins policy rule can declare the pair compatible.",
                             status="failed") if mismatched else None
        # A mismatch is definite; by default it is a non-blocking failure with a warning, and a policy can require it.
        self.check("relationships", f"{row['id']}/concepts", error, path=path, required=severity == "error",
                   evidence="declared", severity=severity)

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
        names = row_identity_names(schema)
        if names is None or any(identity["kind"] == "key" for identity in self.identities[alias]):
            return
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
                release_position = any(identity["kind"] == "row_position" and identity["scope"] == "release"
                                       and any(item["path"] == key_path for item in identity["fields"])
                                       for identity in self.identities[alias])
                if release_position and row["scope"] != "same_release":
                    raise CatalogError("CATALOG-RELEASE-SCOPE", "A release-local row position requires the same exact release.")
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
            if row["match"] == "equal" and len(keys["source"]) != len(keys["target"]):
                raise CatalogError("CATALOG-KEY-INCOMPLETE", "Both endpoints must supply every ordered key component.")
            for side, cardinalities in (("source", {"one_to_one", "one_to_many"}),
                                        ("target", {"one_to_one", "many_to_one"})):
                endpoint = row[side]
                identities = [identity for identity in self.identities[endpoint["dataset"]]
                              if identity["kind"] in {"key", "row_position"}]
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
        self.concept_join(row, path)

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
        self.recipe_sources[row["id"]] = source
        row["sql"] = "queries/" + sha256(row["id"].encode()).hexdigest() + ".sql"
        self.queries[row["id"]] = (row, data)

    def bind_recipes(self, tools):
        """Bind each recipe's SQL to its declared inputs and result through an explicitly selected tool.

        The tool parses and types the SQL offline; it never runs the query or reads data.
        """
        report = self.report
        if not self.queries:
            report.add(CHECK_IDS["recipes"], RECIPE_GROUP, "recipes", "not_run", applicable=False, evidence="inferred",
                       reason="The loaded scope declares no recipes.")
            return
        if tools is None:
            report.missing_capabilities.add(RECIPE_GROUP)
            for identifier in sorted(self.queries):
                self.check("recipes", identifier, CatalogError(
                    "ADAPTER-CAPABILITY-MISSING", "Recipe SQL binding needs an explicitly selected tool environment.",
                    status="not_run"), path=self.recipe_sources[identifier], required=True)
            return
        response = tools.invoke("recipe-sql", {"recipes": [{
            "id": identifier, "sql": data.decode("utf-8"), "dialect": row["dialect"],
            "inputs": {name: self.dataset_schemas[alias] for name, alias in row["inputs"].items()},
            "parameters": row["parameters"], **({"parameterOrder": row["parameterOrder"]} if "parameterOrder" in row else {}),
            "result": self.dataset_schemas.get(row.get("resultDataset")),
        } for identifier, (row, data) in sorted(self.queries.items())]})
        receipt = response.get("receipt")
        evidence = ({"kind": "native-report", "path": receipt["path"], "sha256": receipt["sha256"]},) if receipt else ()
        results = response.get("results", {}) if response.get("status") == "completed" else {}
        if response.get("status") == "completed":
            self.recipe_parser = {"id": response["parser"]["id"], "version": response["parser"]["version"]}
        bindings = report.metadata.setdefault("recipeBindings", {})
        for identifier in sorted(self.queries):
            path = self.inventory.display_path(self.recipe_sources[identifier])
            result = results.get(identifier)
            if result is None:
                reason = response.get("reason") or "The recipe tool returned no result for this recipe."
                report.add(CHECK_IDS["recipes"], RECIPE_GROUP, identifier, "not_run", required=True, evidence="inferred",
                           reason=reason, evidence_records=evidence,
                           diagnostics=[diagnostic("EXEC-NATIVE-UNAVAILABLE", reason, path=path)])
                continue
            report.add(CHECK_IDS["recipes"], RECIPE_GROUP, identifier, result["status"], required=True, evidence="inferred",
                       reason=result.get("reason"), evidence_records=evidence, diagnostics=[
                           diagnostic(item["code"], item["message"], path=path, severity=item["severity"])
                           for item in result["diagnostics"]])
            bindings[identifier] = {"parser": {**self.recipe_parser, **result.get("parser", {})},
                                    **({"output": result["output"]} if "output" in result else {})}

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
        if self.inventory.import_aliases:
            details["importAliases"] = dict(sorted(self.inventory.import_aliases.items()))
        if self.relationship_profile is not None:
            details["relationshipProfile"] = deepcopy(self.report.metadata["relationshipProfile"])
            details["relationshipAssessments"] = sorted(self.relationship_assessments, key=json_dumps)
            self.report.metadata["relationshipAssessments"] = details["relationshipAssessments"]
        if self.native_rule_profile is not None:
            details["nativeRuleProfile"] = self.native_rule_profile.record()
        if self.managed_schema_profiles:
            details["managedSchemaProfiles"] = deepcopy(self.managed_schema_profiles)
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
            "productions": list(self.productions.values()), "files": [], "concepts": self.concepts(),
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
        if self.recipe_parser is not None:
            yield dict(self.recipe_parser)
        if self.native_rule_profile is not None:
            yield deepcopy(self.native_rule_profile.identity)
        if self.metadata:
            yield self.metadata.adapter
        if "catalog.dcat" in self.exports:
            yield DCAT_ADAPTER
        if "catalog.graph" in self.exports:
            yield GRAPH_ADAPTER
        if "catalog.rml" in self.exports:
            yield RML_ADAPTER
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
                if "reference" not in row:
                    raise CatalogError("CATALOG-NATIVE-REFERENCE", "Local owner observations need exact references before public disclosure.")
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
                evidence = (report,) if (report := check_report(check)) else ()
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
        if "catalog.graph" in self.exports:
            try:
                document, parsed = graph_document(self.catalog)
                self.add_file("discovery.graph.jsonld", "graph", _bytes(document))
                if self.graph_turtle:
                    self.add_file("discovery.graph.ttl", "graph", turtle_bytes(parsed))
                self.check("catalog.graph", "export")
                self.report.completed_profiles.add("catalog.graph")
            except CatalogError as error:
                self.check("catalog.graph", "export", error)
        if "catalog.rml" in self.exports:
            try:
                for path, data in rml_documents(self.catalog).items():
                    self.add_file(path, "mapping", data)
                self.check("catalog.rml", "export")
                self.report.completed_profiles.add("catalog.rml")
            except CatalogError as error:
                self.check("catalog.rml", "export", error)
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
                     permitted_roots=(), limits=None, relationship_profile=None, native_rule_profile=None,
                     include_private_artifacts=False, managed_schema_profiles=None, recipe_tools=None):
    """Load once and return admitted metadata with its report and companions.

    ``recipe_tools`` is an explicitly selected native tool environment; it binds
    recipe SQL only when ``catalog.recipes`` is requested.

    An admitted view remains inspectable when qualification is incomplete or
    failed. Only a passed report permits atomic publication to ``output``.
    """
    if isinstance(exports, str):
        exports = (exports,)
    profiles = sorted({EXPORTS.get(name, name) for name in exports})
    public = audience == "public" or disclosure_policy is not None
    if type(include_private_artifacts) is not bool or (include_private_artifacts and not public):
        raise ValueError("Private access artifacts require an explicitly requested public assembly")
    inventory = load_project(project_path, permitted_roots, limits)
    assembly = Assembly(inventory, profiles)
    assembly.graph_turtle = "graph.ttl" in exports  # the JSON-LD graph, also written as Turtle on request
    report = inventory.report
    report.available_capabilities.update((*GROUPS, *EXPORTS.values(), *((RECIPE_GROUP,) if recipe_tools else ())))
    core = check_inventory(inventory, (*required_groups, "catalog.assembly", *profiles),
                           handled_groups=(*GROUPS, RECIPE_GROUP, *profiles))
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
    local_artifacts = MappingProxyType({})
    step = "products"
    failure_path = inventory.path
    try:
        assembly.project_records()
        products = assembly.definitions()
        if managed_schema_profiles is not None:
            from .arrow_observation import MANAGED_SCHEMA_PROFILES
            if (not isinstance(managed_schema_profiles, Mapping)
                    or set(managed_schema_profiles) - assembly.datasets.keys()
                    or any(not isinstance(value, str) or value not in MANAGED_SCHEMA_PROFILES
                           for value in managed_schema_profiles.values())):
                raise CatalogError("CATALOG-SCHEMA-PROFILE", "Select supported managed schema profiles for registered dataset aliases.", status="unknown")
            assembly.managed_schema_profiles = deepcopy(dict(managed_schema_profiles))
        assembly.check("products", "ports")
        for identity, version, index, path in sorted(assembly.unknown_sla):
            assembly.check("datasets", f"{identity}@{version}/slaProperties/{index}", CatalogError(
                "CATALOG-SLA-ELEMENT-UNKNOWN", "The SLA element does not identify a selected object; no dataset carries it.",
                f"/slaProperties/{index}", status="unknown"), path=path, required=False)
        step = "relationships"
        assembly.select_relationship_profile(relationship_profile)
        assembly.declarations()
        if RECIPE_GROUP in report.required_groups:
            assembly.bind_recipes(recipe_tools)
        from .catalog_native_rules import select_native_rule_profile

        selected_native_rules = select_native_rule_profile(native_rule_profile, inventory)
        assembly.native_rule_profile = selected_native_rules
        if selected_native_rules is not None and selected_native_rules.source is not None:
            assembly.remember(owner_record(selected_native_rules.source), "implementation")
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
                                                  assembly.datasets, assembly.productions, native_rule_profile=selected_native_rules,
                                                  schema_profiles=assembly.managed_schema_profiles,
                                                  identities=[row for rows in assembly.identities.values() for row in rows]).read()
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
            if include_private_artifacts:
                if set(profiles) - {"catalog.dcat"}:
                    raise CatalogError("CATALOG-PRIVATE-EXPORT-UNSUPPORTED",
                                       "Paired private preparation supports the declared DCAT export only.")
                # Reuse the same admitted source and SQL bytes. No second load,
                # row scan, public-to-private guess or publication takes place.
                private_catalog = deepcopy(local_admitted)
                private_files = {recipe["sql"]: ("recipe", assembly.queries[recipe["id"]][1])
                                 for recipe in private_catalog["recipes"]}
                if "catalog.dcat" in profiles:
                    private_files["discovery.dcat.json"] = ("dcat", _bytes(dcat_document(private_catalog)))
                private_prepared = prepare_output_set(
                    private_catalog, private_files, result, profiles,
                    assembly.metadata.adapter if assembly.metadata else None, inventory,
                )
                from .documents import parse_json

                private_lock = parse_json(private_prepared["catalog.lock.json"][1])
                private_lock["extensions"][PAIRED_VIEW] = paired_view_record(
                    assembly.catalog, private_catalog, artifacts["catalog.lock.json"],
                )
                _schema(private_lock, "lock")
                private_prepared["catalog.lock.json"] = ("lock", _bytes(private_lock))
                local_artifacts = MappingProxyType({name: data for name, (_, data) in private_prepared.items()})
        # Qualification can remain unresolved while the assembled discovery record is inspectable.
        if output is None or result["decision"] != "passed":
            report.metadata["catalog"] = assembly.catalog
        if output is not None and result["decision"] == "passed":
            report.metadata["generatedFiles"] = write_output_set(
                output, assembly.catalog, assembly.files, result, profiles,
                assembly.metadata.adapter if assembly.metadata else None, inventory,
                prepared=prepared,
            )
        return _result(report.build(), admitted, companions, artifacts, public=public, local_catalog=local_admitted,
                       local_artifacts=local_artifacts)
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
                  permitted_roots=(), limits=None, relationship_profile=None, recipe_tools=None):
    """Build and optionally publish a catalog; return its checking report."""
    return assemble_catalog(
        project_path, metadata=metadata, metadata_adapter=metadata_adapter, exports=exports, output=output,
        current_selection=current_selection, disclosure_policy=disclosure_policy, audience=audience,
        required_groups=required_groups, permitted_roots=permitted_roots, limits=limits,
        relationship_profile=relationship_profile, recipe_tools=recipe_tools,
    ).local_report
