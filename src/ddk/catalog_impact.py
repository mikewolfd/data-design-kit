"""Compare the scope, declarations, and observed facts in generated catalogs."""

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from .documents import DEFAULT_LIMITS, DocumentError, ResourceLimit, json_dumps, read_json, schema_registry, schema_validator, validate_document
from .interfaces import json_equal
from .locks import tool_identities
from .results import ReportBuilder, diagnostic

GROUP = "impact.catalog"
DETAILS = "urn:ddk:catalog:assembly"
REQUIREMENT = "DDK-CATALOG-010"
METADATA = "metadata-regeneration"
REQUALIFY = "requalification"
COMPUTE = "computation-review"
REBIND = "consumer-rebind"
QUALITY_FIELDS = {"quality", "enum", "unique", "primaryKey", "primaryKeyPosition"}
SCHEMA_FIELDS = {"name", "id", "logicalType", "physicalName", "physicalType", "logicalTypeOptions", "required"}
RULE_FIELDS = ("subject", "rule", "evaluator", "scope")


def _identity(kind, *values):
    """Identify report records that have no publisher-supplied ID."""
    return f"urn:ddk:impact:{kind}:{sha256(json_dumps(values).encode()).hexdigest()}"


def _projection(record, fields):
    return {key: record[key] for key in fields if key in record}


def _without(record, *keys):
    return {key: value for key, value in record.items() if key not in keys}


def _field_projection(value, fields):
    if not isinstance(value, dict) or ("properties" in value and not isinstance(value["properties"], list)):
        raise DocumentError("CATALOG-IMPACT-DEFINITION", "The effective field definition has an invalid shape.")
    return {
        **_projection(value, fields),
        **({"properties": [_field_projection(item, fields) for item in value["properties"]]}
           if "properties" in value else {}),
        **({"items": _field_projection(value["items"], fields)} if isinstance(value.get("items"), dict) else {}),
    }


def _selection_groups(values):
    groups = defaultdict(list)
    for row in values:
        groups[(row["authority"], row["purpose"])].append(row)
    return {key: sorted(rows, key=json_dumps) for key, rows in groups.items()}


def _rule_groups(values):
    groups = defaultdict(list)
    validator = _rule_validator()
    for row in values:
        if not isinstance(row, dict) or set(RULE_FIELDS) - row.keys():
            raise DocumentError("CATALOG-IMPACT-RULE", "A requested rule needs an exact subject, rule, evaluator, and scope.")
        identity = _projection(row, RULE_FIELDS)
        # Reuse the existing checked subject/rule/evaluator/scope grammar.
        if not validator.is_valid({**identity, "status": "unknown", "reason": "Requested rule."}):
            raise DocumentError("CATALOG-IMPACT-RULE", "The requested rule has an invalid version, target, evaluator, or scope.")
        key = (row["subject"], row["rule"]["id"], row["evaluator"]["id"], row["scope"])
        groups[key].append(identity)
    return {key: sorted(rows, key=json_dumps) for key, rows in groups.items()}


def _rule_validator():
    registry, schemas, _ = schema_registry()
    catalog = schemas["catalog"]
    return schema_validator({"$ref": f"{catalog['$id']}#/$defs/check"}, resource_registry=registry)


@dataclass(frozen=True)
class Record:
    identity: str
    value: object
    revision: str | None = None


def _read(value, name, limits):
    if isinstance(value, Mapping):
        return value, f"<{name}-catalog>"
    document = read_json(value, max_bytes=limits["maxDocumentBytes"], max_nesting=limits["maxNesting"])
    return document.value, str(document.path)


class Snapshot:
    def __init__(self, value, rules, peer_catalogs=None):
        self.value = value
        details = value.get("extensions", {}).get(DETAILS, {})
        if not isinstance(details, dict):
            raise DocumentError("CATALOG-IMPACT-SCOPE", "The catalog assembly scope has an invalid shape.")
        self.definitions = details.get("datasetDefinitions", {})
        self.scope = details.get("scope", {})
        if not isinstance(self.scope, dict) or not isinstance(self.definitions, dict):
            raise DocumentError("CATALOG-IMPACT-SCOPE", "The catalog assembly scope or effective definitions have an invalid shape.")
        excluded = self.scope.get("excludedConsumers", [])
        if not isinstance(excluded, list) or not all(isinstance(item, str) for item in excluded):
            raise DocumentError("CATALOG-IMPACT-SCOPE", "Excluded consumers must be listed by name.")
        self.quality_inventory = rules if rules is not None else details.get("requiredQualityChecks")
        self.records = {}
        self.dependents = defaultdict(set)
        self.contextual_dependents = defaultdict(set)
        self.unresolved = set()
        self.datasets = {}
        self.peer_catalogs = {}
        self.peer_datasets = {}
        self.peer_definitions = {}
        self.versions = {}
        self.releases = {}
        self.unevidenced_rules = set()
        recipe_digests = {row["path"]: row["sha256"] for row in value["files"]}
        peer_summaries = dict(details.get("peerCatalogs") or {})
        if peer_catalogs:
            from .catalog import _peer_summary
            from .catalog_delivery import CatalogArtifacts, CatalogError, load_catalog_artifacts
            for peer_alias, decl in sorted((value.get("imports") or {}).items()):
                if peer_alias in peer_summaries or peer_alias not in peer_catalogs:
                    continue
                entry = peer_catalogs[peer_alias]
                try:
                    captured = (entry if isinstance(entry, CatalogArtifacts)
                                else load_catalog_artifacts(entry, expected_lock_sha256=decl["lockSha256"],
                                                            audience=decl["audience"]))
                    if captured.catalog.get("id") == decl["id"] and captured.lock_sha256 == decl["lockSha256"]:
                        peer_summaries[peer_alias] = _peer_summary(captured)
                except (CatalogError, OSError, ValueError):
                    pass

        for peer_alias, decl in sorted((value.get("imports") or {}).items()):
            peer_node = self.add("peer-catalog", peer_alias, decl["id"], decl, decl["lockSha256"])
            self.peer_catalogs[peer_alias] = peer_node
            summary = peer_summaries.get(peer_alias)
            if isinstance(summary, Mapping):
                peer_defs = summary.get("datasetDefinitions") or {}
                peer_ids = summary.get("identities") or ()
                for ds_alias, ds_id in sorted((summary.get("datasets") or {}).items()):
                    pds_key = f"{peer_alias}:{ds_alias}"
                    pds_node = self.add("peer-dataset", pds_key, ds_id, {
                        "catalog": peer_alias, "alias": ds_alias, "id": ds_id,
                        "identities": [i for i in peer_ids if i.get("dataset") == ds_alias],
                    })
                    self.peer_datasets[(peer_alias, ds_alias)] = pds_node
                    if ds_alias in peer_defs:
                        self.peer_definitions[pds_key] = peer_defs[ds_alias]
                    self.link(peer_node, pds_node, decl["id"])
            else:
                self.unresolved.add(decl["id"])

        extensions = details.get("projectExtensions", [])
        if not isinstance(extensions, list):
            raise DocumentError("CATALOG-IMPACT-SCOPE", "Scoped project extensions must be listed separately by source project.")
        for source in extensions:
            if (not isinstance(source, dict) or not isinstance(source.get("project"), dict)
                    or not isinstance(source.get("namespace"), str) or not isinstance(source.get("extensions"), dict)):
                raise DocumentError("CATALOG-IMPACT-SCOPE", "A project extension needs its declaring project, namespace, and values.")
            for namespace, meaning in source["extensions"].items():
                identity = _identity("project-extension", source["project"], source["namespace"], namespace)
                self.add("project-extension", identity, identity, {
                    "project": source["project"], "namespace": source["namespace"], "extension": namespace, "value": meaning,
                })
                # DDK preserves unknown extension meaning without inventing
                # domain consumers, execution dependencies, or reuse decisions.
                self.unresolved.add(identity)

        for row in value["datasets"]:
            alias = row["alias"]
            node = self.add("dataset", alias, row["id"], row, row["definition"]["version"])
            self.datasets[alias] = node
        for row in value.get("concepts", ()):
            node = self.add("concept", row["concept"], row["concept"], row)
            for field in row["fields"]:
                if "catalog" in field:
                    peer_key = (field["catalog"], field["dataset"])
                    source = self.peer_datasets.get(peer_key) or self.peer_catalogs.get(field["catalog"])
                    self.link(source, node, f"{field['catalog']}:{field['dataset']}")
                else:
                    self.link(node, self.datasets.get(field["dataset"]), field["dataset"])
        for row in value["versions"]:
            node = self.add("native-version", row["id"], row["id"], row)
            self.versions[row["id"]] = node
            self.link(node, self.datasets.get(row["dataset"]), row["dataset"])
            if row.get("referenceDisclosure") == "withheld":
                self.unresolved.add(row["id"])
        for row in value["releases"]:
            node = self.add("publisher-release", row["id"], row["id"], row)
            self.releases[row["id"]] = node
            for version in row["members"]:
                known = self.versions.get(version)
                self.link(known, node, version)
                self.link(node, self._dataset_for(known), version)
        for row in value["representations"]:
            node = self.add("representation", row["id"], row["id"], row)
            self.link(node, self.versions.get(row["version"]), row["version"])
        for row in value["relationships"]:
            node = self.add("relationship", row["id"], row["id"], row)
            for side in ("source", "target"):
                endpoint = row[side]
                if "catalog" in endpoint:
                    peer_key = (endpoint["catalog"], endpoint["dataset"])
                    source = self.peer_datasets.get(peer_key) or self.peer_catalogs.get(endpoint["catalog"])
                    self.link(source, node, f"{endpoint['catalog']}:{endpoint['dataset']}")
                elif (alias := endpoint.get("dataset")) is not None:
                    self.link(self.datasets.get(alias), node, alias)
                else:
                    self.unresolved.add(endpoint.get("externalDataset", row["id"]))
        self.relationship_semantics(details)
        for row in value["recipes"]:
            node = self.add("recipe", row["id"], row["id"], {
                **row, "sqlDigest": recipe_digests.get(row["sql"]),
            })
            if row["sql"] not in recipe_digests:
                self.unresolved.add(row["id"])
            for ref in row["inputs"].values():
                if isinstance(ref, Mapping):
                    peer_key = (ref["catalog"], ref["dataset"])
                    source = self.peer_datasets.get(peer_key) or self.peer_catalogs.get(ref["catalog"])
                    self.link(source, node, f"{ref['catalog']}:{ref['dataset']}")
                else:
                    self.link(self.datasets.get(ref), node, ref)
            if alias := row.get("resultDataset"):
                self.link(self.datasets.get(alias), node, alias)
            for relationship in row["relationships"]:
                target = ("relationship", relationship)
                self.link(target if target in self.records else None, node, relationship)
            for relationship in row.get("contextualRelationships", ()):
                target = ("relationship", relationship)
                self.link(target if target in self.records else None, node, relationship, contextual=True)
        for row in value["productions"]:
            node = self.add("production", row["alias"], row["identity"]["id"], row, row["identity"]["version"])
            for alias in (*row["inputs"], *row["outputs"]):
                self.link(self.datasets.get(alias), node, alias)
        for row in value["products"]:
            node = self.add("product", row["alias"], row["id"], row, row["version"])
            for port in row["ports"]:
                self.link(self.datasets.get(port["dataset"]), node, port["dataset"])
        for key, rows in _selection_groups(value["selections"]).items():
            identity = _identity("publisher-selection", *key)
            node = self.add("publisher-selection", identity, identity, rows)
            for row in rows:
                release = self.releases.get(row["release"])
                self.link(release, node, row["release"])
                if release is not None:
                    for version in self.records[release].value["members"]:
                        self.link(node, self._dataset_for(self.versions.get(version)), version)
        selector = value.get("currentSelection")
        if selector:
            identity = _identity("discovery-selector", value["id"])
            node = self.add("discovery-selector", identity, identity, selector)
            selection = _identity("publisher-selection", selector["authority"], selector["purpose"])
            target = ("publisher-selection", selection)
            if target in self.records:
                self.link(node, target, selection)

        check_groups = defaultdict(list)
        for row in value["checks"]:
            key = (row["subject"], row["rule"]["id"], row["evaluator"]["id"], row["scope"])
            check_groups[key].append(row)
        for key, rows in check_groups.items():
            identity = _identity("quality-observation", *key)
            node = self.add("qualification-evidence", identity, identity, sorted(rows, key=json_dumps))
            self.link(node, self.versions.get(key[0]), key[0])
        if self.quality_inventory is not None and not isinstance(self.quality_inventory, (list, tuple)):
            raise DocumentError("CATALOG-IMPACT-RULE", "The requested quality inventory must list exact obligations.")
        for key, rows in _rule_groups(self.quality_inventory or ()).items():
            identity = _identity("requested-quality", *key)
            observed = check_groups.get(key, ())
            qualified = all(any(row["status"] == "passed" and json_equal(_projection(row, RULE_FIELDS), obligation)
                                for row in observed) for obligation in rows)
            node = self.add("requested-quality", identity, identity, {"rules": rows, "matchingPasses": qualified})
            version = self.versions.get(key[0])
            self.link(node, version, key[0])
            if not qualified:
                self.unevidenced_rules.add(identity)
                self.unresolved.add(identity)

    def relationship_semantics(self, details):
        profile = details.get("relationshipProfile")
        assessments = details.get("relationshipAssessments", [])
        assessment_scope = details.get("relationshipAssessmentScope")
        if not isinstance(assessments, list) or (profile is None and (assessments or assessment_scope is not None)):
            raise DocumentError("CATALOG-IMPACT-PROFILE", "Relationship assessments need an explicitly selected profile.")
        if profile is None:
            return
        registry, schemas, _ = schema_registry()
        tool = schema_validator({"$ref": f"{schemas['common']['$id']}#/$defs/toolIdentity"}, resource_registry=registry)
        source = schema_validator({"$ref": f"{schemas['catalog']['$id']}#/$defs/inputFile"}, resource_registry=registry)
        if (not isinstance(profile, dict) or not tool.is_valid(profile.get("identity"))
                or profile.get("scope") != "declaration-support-only"):
            raise DocumentError("CATALOG-IMPACT-PROFILE", "A selected relationship profile needs its exact identity and declaration scope.")
        identity = profile["identity"]
        if "source" in profile:
            if not isinstance(profile["source"], dict) or not source.is_valid({**profile["source"], "role": "implementation"}):
                raise DocumentError("CATALOG-IMPACT-PROFILE", "A profile source needs its original URI and byte digest.")
        elif not {"commit", "distributionSha256"} & identity.keys():
            raise DocumentError("CATALOG-IMPACT-PROFILE", "A selected relationship profile lacks implementation provenance.")
        profile_value = profile
        if assessment_scope is not None:
            if (not isinstance(assessment_scope, dict) or assessment_scope.get("status") != "unknown" or assessments
                    or not isinstance(assessment_scope.get("reason"), str) or not assessment_scope["reason"].strip()):
                raise DocumentError("CATALOG-IMPACT-PROFILE", "Withheld assessment scope must remain explicitly unknown without individual assessments.")
            profile_value = {**profile, "assessmentScope": assessment_scope}
            self.unresolved.add(_identity("relationship-assessment-scope", identity["id"]))
        profile_node = self.add("relationship-profile", identity["id"], identity["id"], profile_value, identity["version"])
        self.unresolved.add(identity["id"])
        for assessment in assessments:
            if (not isinstance(assessment, dict) or not isinstance(assessment.get("relationship"), str)
                    or not isinstance(assessment.get("status"), str) or assessment["status"] not in {"supported", "failed", "unknown"}
                    or not isinstance(assessment.get("reason"), str) or not assessment["reason"].strip()
                    or assessment.get("scope") != "declaration-support-only"
                    or not json_equal(assessment.get("profile"), identity)
                    or assessment.get("externalExistence", "not_assessed") != "not_assessed"):
                raise DocumentError("CATALOG-IMPACT-PROFILE", "A relationship assessment must retain its selected profile, status, and declaration scope.")
            relationship = assessment["relationship"]
            record_id = _identity("relationship-assessment", relationship)
            node = self.add("relationship-assessment", relationship, record_id, assessment)
            self.link(profile_node, node, identity["id"])
            target = ("relationship", relationship)
            self.link(node, target if target in self.records else None, relationship)
            # Static support identifies affected readers, without establishing
            # domain computation or qualification effects outside this inventory.
            self.unresolved.add(record_id)

    def add(self, kind, key, identity, value, revision=None):
        node = (kind, key)
        if node in self.records:
            raise DocumentError("CATALOG-IMPACT-IDENTITY", f"The catalog repeats a {kind} comparison identity.")
        self.records[node] = Record(identity, value, revision)
        return node

    def link(self, source, target, subject, *, contextual=False):
        if source is None or target is None:
            self.unresolved.add(subject)
        else:
            (self.contextual_dependents if contextual else self.dependents)[source].add(target)

    def _dataset_for(self, version):
        return self.datasets.get(self.records[version].value["dataset"]) if version is not None else None


def _change(kind, key, old, new, base, candidate):
    consequences = {METADATA}
    if kind in {"representation", "publisher-release", "publisher-selection", "discovery-selector", "recipe", "relationship",
                "relationship-profile", "relationship-assessment", "concept", "peer-catalog", "peer-dataset"}:
        consequences.add(REBIND)
    if kind == "peer-dataset":
        left = base.peer_definitions.get(key)
        right = candidate.peer_definitions.get(key)
        if old is None or new is None:
            consequences.update((COMPUTE, REQUALIFY))
        elif isinstance(left, dict) and isinstance(right, dict):
            if not json_equal(_field_projection(left, SCHEMA_FIELDS), _field_projection(right, SCHEMA_FIELDS)):
                consequences.add(COMPUTE)
            if not json_equal(_field_projection(left, QUALITY_FIELDS), _field_projection(right, QUALITY_FIELDS)):
                consequences.add(REQUALIFY)
        elif left != right:
            consequences.update((COMPUTE, REQUALIFY))
    if kind == "requested-quality" and new is not None and (
        old is None or not json_equal(old.value["rules"], new.value["rules"]) or not new.value["matchingPasses"]
    ):
        consequences.add(REQUALIFY)
    if kind == "production":
        def meaning(record):
            return {**_without(record.value, "definition"), "definition": record.value["definition"]["sha256"]}
        if old is None or new is None or not json_equal(meaning(old), meaning(new)):
            consequences.add(COMPUTE)
    if kind == "native-version":
        exact = {"reference", "referenceDisclosure", "dataset"}
        if old is None or new is None or not json_equal(_projection(old.value, exact), _projection(new.value, exact)):
            consequences.update((COMPUTE, REQUALIFY))
    if kind == "dataset":
        left = base.definitions.get(key)
        right = candidate.definitions.get(key)
        if old is None or new is None:
            consequences.update((COMPUTE, REQUALIFY))
        elif isinstance(left, dict) and isinstance(right, dict):
            same_object = json_equal(_projection(old.value["definition"], {"contractId", "object"}),
                                     _projection(new.value["definition"], {"contractId", "object"}))
            if not same_object or not json_equal(_field_projection(left, SCHEMA_FIELDS), _field_projection(right, SCHEMA_FIELDS)):
                consequences.add(COMPUTE)
            if not json_equal(_field_projection(left, QUALITY_FIELDS), _field_projection(right, QUALITY_FIELDS)):
                consequences.add(REQUALIFY)
        elif not json_equal(old.value["definition"], new.value["definition"]):
            consequences.update((COMPUTE, REQUALIFY))
    return sorted(consequences)


def _routes(base, candidate, changed, limit):
    dependencies = defaultdict(set)
    contextual = defaultdict(set)
    for snapshot in (base, candidate):
        for source, consumers in snapshot.dependents.items():
            dependencies[source].update(consumers)
        for source, consumers in snapshot.contextual_dependents.items():
            contextual[source].update(consumers)

    def label(node):
        return f"{node[0]}:{node[1]}"

    reached = defaultdict(list)
    traversed = 0
    for source in sorted(changed):
        initial = frozenset(changed[source])
        queue = deque([(source, [label(source)], initial)])
        seen = {(source, initial)}
        while queue:
            node, path, obligations = queue.popleft()
            for consumer in sorted(dependencies[node] | contextual[node]):
                # Informational references require a reader/metadata refresh,
                # without claiming that the referenced table was consumed.
                next_obligations = (frozenset((METADATA, REBIND))
                                    if consumer not in dependencies[node] else obligations)
                state = (consumer, next_obligations)
                if state in seen or label(consumer) in path:
                    continue
                traversed += 1
                if traversed > limit:
                    raise ResourceLimit("Catalog impact dependency paths exceed the configured graph edge limit.")
                seen.add(state)
                route = [*path, label(consumer)]
                reached[label(consumer)].append((route, next_obligations))
                queue.append((consumer, route, next_obligations))
    return reached


def _reuse(base, candidate):
    registry, schemas, _ = schema_registry()
    common = schemas["common"]
    validator = schema_validator({"$ref": f"{common['$id']}#/$defs/reuseRecord"}, resource_registry=registry)
    base, candidate = list(base), list(candidate)
    if any(not validator.is_valid(row) for row in (*base, *candidate)):
        raise DocumentError("CATALOG-IMPACT-REUSE", "Runtime reuse records must preserve the native reuse-record shape.")

    def comparison(required, context):
        old = [row for row in base if required in row]
        new = [row for row in candidate if required in row]
        if not old or not new:
            return {"status": "unknown", "reason": "Both snapshots need runtime-issued identities for this comparison."}
        if len(old) != 1 or len(new) != 1 or old[0]["authority"] != new[0]["authority"]:
            return {"status": "unknown", "reason": "There is no unique comparable identity from one runtime authority."}
        if not json_equal(old[0][required], new[0][required]):
            return {"status": "changed-recorded-identity"}
        if not json_equal(context(old[0]), context(new[0])):
            return {"status": "unknown", "reason": "One runtime identity appears with conflicting inputs or semantics."}
        return {"status": "same-recorded-identity"}

    return {
        "base": base, "candidate": candidate,
        "computation": comparison("computationKey", lambda row: row["semantics"]),
        "qualification": comparison("qualificationKey", lambda row: {
            "candidate": row["candidate"], "rulesSha256": row["rules"]["sha256"],
        }),
    }


def _scope(report, old, new, excluded, require_complete):
    omitted = set(excluded)
    for snapshot in (old, new):
        omitted.update(snapshot.scope.get("excludedConsumers", ()))
    report.scope["excludedConsumers"] = sorted(omitted)
    unresolved = sorted(old.unresolved | new.unresolved | omitted)
    report.metadata["unresolvedCatalogScope"] = unresolved
    report.metadata["catalogScopeLimit"] = "Impact covers consumers and evidence in the supplied snapshots."
    reason = "The supplied catalogs do not establish complete external consumer and evidence scope."
    report.add(REQUIREMENT, GROUP, "complete-scope", "unknown", required=require_complete,
               evidence="inferred", reason=reason, diagnostics=[
                   diagnostic("CATALOG-IMPACT-SCOPE", reason, severity="warning")
               ])


def compare_catalogs(base_catalog, candidate_catalog, *, required_groups=(), require_complete_scope=False,
                     excluded_consumers=(), base_rules=None, candidate_rules=None, base_reuse_records=(),
                     candidate_reuse_records=(), limits=None, peer_catalogs=None):
    """Compare explicit local snapshots and preserve runtime-issued identities."""
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    report = ReportBuilder("urn:ddk:catalog-impact", [GROUP, *required_groups])
    report.limits.update(limits)
    report.tools = tool_identities()
    for group in sorted(set(required_groups) - {GROUP, "catalog.qualification"}):
        reason = "Catalog comparison does not run this requested profile."
        report.missing_capabilities.add(group)
        report.add("DDK-ADAPTER-001", group, "catalog", "not_run", reason=reason,
                   diagnostics=[diagnostic("ADAPTER-CAPABILITY-MISSING", reason, severity="warning")])
    impact = {
        "baseProject": "urn:ddk:unknown-project", "candidateProject": "urn:ddk:unknown-project",
        "changed": [], "affected": [],
    }
    path = "<catalog-impact>"
    try:
        snapshots = []
        for side, input_, rules in (("base", base_catalog, base_rules), ("candidate", candidate_catalog, candidate_rules)):
            value, path = _read(input_, side, limits)
            if issues := validate_document(value, "catalog"):
                report.add(REQUIREMENT, GROUP, f"{side}-catalog", "failed", diagnostics=[
                    diagnostic(issue.code, issue.message, path=path, pointer=issue.pointer) for issue in issues
                ])
                continue
            impact[f"{side}Project"] = value["project"]["id"]
            snapshots.append(Snapshot(value, rules, peer_catalogs=peer_catalogs))
        if len(snapshots) != 2:
            report.add(REQUIREMENT, GROUP, "comparison", "not_run", reason="Both catalog snapshots must validate.")
            return report.build(impact=impact)

        old, new = snapshots
        report.scope["projects"] = sorted({impact["baseProject"], impact["candidateProject"]})
        report.scope["artifacts"] = sorted(set(old.datasets) | set(new.datasets))
        report.metadata["catalogProjects"] = {"base": old.value["project"], "candidate": new.value["project"]}
        report.metadata["catalogScopes"] = {"base": old.scope, "candidate": new.scope}
        report.metadata["catalogProjectInputs"] = {
            side: [row for row in snapshot.value["sourceInventory"] if row["role"] == "project"]
            for side, snapshot in (("base", old), ("candidate", new))
        }
        _scope(report, old, new, excluded_consumers, require_complete_scope)
        report.metadata["runtimeReuse"] = _reuse(base_reuse_records, candidate_reuse_records)
        if old.quality_inventory is None or new.quality_inventory is None:
            reason = "At least one catalog omits the requested quality inventory."
            quality_requested = "catalog.qualification" in required_groups
            report.add(REQUIREMENT, "catalog.qualification" if quality_requested else GROUP,
                       "requested-quality-inventory", "unknown", required=quality_requested, reason=reason,
                       diagnostics=[diagnostic("CATALOG-IMPACT-QUALITY-SCOPE", reason, path=path, severity="warning")])
        if "catalog.qualification" in required_groups and new.quality_inventory is not None:
            if not new.quality_inventory:
                reason = "The candidate catalog declares no required quality obligations."
                report.add(REQUIREMENT, "catalog.qualification", "candidate-obligations", "not_run", reason=reason)
            elif new.unevidenced_rules:
                reason = "The candidate has required rules without matching passing observations."
                report.add(REQUIREMENT, "catalog.qualification", "candidate-obligations", "unknown", reason=reason,
                           diagnostics=[diagnostic("CATALOG-IMPACT-QUALITY-SCOPE", reason, path=path, severity="warning")])
            else:
                report.add(REQUIREMENT, "catalog.qualification", "candidate-obligations", "passed", evidence="inferred")
        if old.value["audience"] != new.value["audience"]:
            reason = "The two disclosure audiences expose different information."
            report.add(REQUIREMENT, GROUP, "disclosure-scope", "unknown", reason=reason,
                       diagnostics=[diagnostic("CATALOG-IMPACT-SCOPE", reason, path=path, severity="warning")])

        changes = {}
        details = {}
        for node in sorted(old.records.keys() | new.records.keys()):
            kind, key = node
            base_record, candidate_record = old.records.get(node), new.records.get(node)
            effective_changed = (
                (kind == "dataset" and not json_equal(old.definitions.get(key), new.definitions.get(key)))
                or (kind == "peer-dataset" and not json_equal(old.peer_definitions.get(key), new.peer_definitions.get(key)))
            )
            if base_record and candidate_record and json_equal(base_record.value, candidate_record.value) and not effective_changed:
                continue
            identity = (candidate_record or base_record).identity
            action = "added" if base_record is None else "removed" if candidate_record is None else "changed"
            entry = {"identity": identity, "kinds": [kind, action]}
            if base_record and base_record.revision:
                entry["baseVersion"] = base_record.revision
            if candidate_record and candidate_record.revision:
                entry["candidateVersion"] = candidate_record.revision
            impact["changed"].append(entry)
            consequences = _change(kind, key, base_record, candidate_record, old, new)
            changes[node] = consequences
            details[f"{kind}:{key}"] = {
                "identity": identity, "obligations": consequences,
                "computation": "review-required" if COMPUTE in consequences else "unaffected-by-this-change",
            }
            if kind in {"relationship-profile", "relationship-assessment"}:
                details[f"{kind}:{key}"].update({
                    "computation": "unknown",
                    "domainEffects": {"status": "unknown", "reason":
                                      "Declaration reasoning identifies reader rechecks; domain computation and qualification effects require their owners."},
                })
            if kind in {"native-version", "representation", "publisher-release", "publisher-selection", "requested-quality",
                        "project-extension", "relationship-profile", "relationship-assessment", "concept",
                        "peer-catalog", "peer-dataset"}:
                details[f"{kind}:{key}"].update({
                    "baseRecord": base_record.value if base_record else None,
                    "candidateRecord": candidate_record.value if candidate_record else None,
                })
        reached = _routes(old, new, changes, limits["maxGraphEdges"])
        impact["affected"] = [{"consumer": name, "paths": sorted({tuple(path) for path, _ in causes})}
                              for name, causes in sorted(reached.items())]
        for entry in impact["affected"]:
            entry["paths"] = [list(path) for path in entry["paths"]]
        report.metadata["catalogChanges"] = details
        report.metadata["catalogAffectedObligations"] = {
            name: sorted({item for _, obligations in causes for item in obligations})
            for name, causes in sorted(reached.items())
        }
        report.add(REQUIREMENT, GROUP, "comparison", "passed", evidence="inferred")
        if not any(check["required"] and check["status"] != "passed" for check in report.checks):
            report.completed_profiles.add("impact.catalog")
    except DocumentError as exc:
        report.add(REQUIREMENT, GROUP, "comparison", "failed",
                   diagnostics=[diagnostic(exc.code, str(exc), path=path, pointer=exc.pointer)])
    except (OSError, ResourceLimit) as exc:
        code = "EXEC-RESOURCE-LIMIT" if isinstance(exc, ResourceLimit) else "DOC-UNREADABLE"
        report.error(diagnostic(code, str(exc), path=path))
        report.add(REQUIREMENT, GROUP, "comparison", "not_run", reason="A catalog snapshot could not be checked.")
    return report.build(impact=impact)
