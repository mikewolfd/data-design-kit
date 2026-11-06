"""Change analysis across explicitly supplied project snapshots."""

from collections import defaultdict, deque
from hashlib import sha256

from .catalog_impact import GROUP as CATALOG_IMPACT, compare_catalogs
from .core import check_inventory, load_project
from .datasets import compare_datasets
from .definitions import enum_values
from .documents import DocumentError, ResourceLimit, json_pointer
from .interfaces import interface_compatibility, json_equal, schema_containment
from .results import diagnostic, location

CONSUMERS = "impact.consumers"
COMPATIBILITY = "impact.compatibility"
NON_WEAKENING = "impact.non-weakening"


def _urn(kind, *parts):
    digest = sha256("\x00".join(parts).encode()).hexdigest()
    return f"urn:ddk:{kind}:{digest}"


def _records(inventory):
    records = defaultdict(dict)
    for alias, artifact in sorted(inventory.artifacts.items()):
        if alias not in inventory.selected_aliases:
            continue
        identity = artifact.identity
        if artifact.kind == "dataset":
            identity = _urn("dataset-definition", identity, artifact.selection)
        elif artifact.kind == "definition":
            identity = _urn("shared-definition", inventory.display_path(artifact.path))
        version = artifact.version
        entry = records[identity].setdefault(version, {
            "kind": artifact.kind, "artifact": artifact, "document": artifact.document,
            "nodes": set(), "version": version,
        })
        entry["nodes"].add(alias)
        if artifact.kind == "definition":
            entry["nodes"].add(f"definition:{inventory.display_path(artifact.path)}")
    for namespace, document in inventory.projects.items():
        entry = records[document.value["id"]].setdefault(document.value["version"], {
            "kind": "project", "document": document, "nodes": set(), "version": document.value["version"],
        })
        entry["nodes"].add(f"project:{namespace or '/'}")
    return records


def _pairs(left, right):
    for version in sorted(left.keys() & right.keys(), key=str):
        yield left[version], right[version]
    removed = sorted(left.keys() - right.keys(), key=str)
    added = sorted(right.keys() - left.keys(), key=str)
    if len(removed) == len(added) == 1:
        yield left[removed[0]], right[added[0]]
    else:
        for version in removed:
            yield left[version], None
        for version in added:
            yield None, right[version]


def _changed(old, new):
    if old is None or new is None:
        return ["added" if old is None else "removed"]
    result = []
    if old["version"] != new["version"]:
        result.append("version")
    if old["document"].sha256 != new["document"].sha256:
        result.append("formatting" if json_equal(old["document"].value, new["document"].value) else "content")
    left, right = old.get("artifact"), new.get("artifact")
    if left and right and left.kind in {"dataset", "definition"} and not json_equal(left.effective, right.effective):
        result.append("effective-definition")
    if old["nodes"] != new["nodes"]:
        result.append("aliases")
    return result


def _check_compatibility(report, left, right, base, candidate, identity):
    subject = f"{identity}/version/{left.version}/{right.version}"
    here = candidate.display_path(right.path)
    if left.kind != "component":
        return
    if f"core.calls/DDK-CALL-004/{left.alias}" in {
        check["id"] for check in base.report.checks if check["status"] != "passed"
    } or f"core.calls/DDK-CALL-004/{right.alias}" in {
        check["id"] for check in candidate.report.checks if check["status"] != "passed"
    }:
        report.add("DDK-IMPACT-003", COMPATIBILITY, subject, "not_run",
                   reason="An interface has an invalid or unresolved parameter schema.")
        return
    left_value, right_value = left.value, right.value
    directions = {}

    def add(label, status, pointer, detail=""):
        directions[label] = status
        if status == "failed":
            items = [diagnostic("IMPACT-BREAKING-INTERFACE", detail or f"Breaking change in {label}.",
                                path=here, pointer=pointer,
                                related=[location(base.display_path(left.path), pointer)])]
        else:
            items = []
        reason = "The required direction uses unresolved definitions or unsupported containment rules." if status in {
            "unknown", "not_run",
        } else None
        report.add("DDK-IMPACT-003", COMPATIBILITY, f"{subject}/{label}", status, diagnostics=items, reason=reason)

    parameter_status = interface_compatibility(left_value["parameters"], right_value["parameters"])
    add("parameters/base-to-candidate", parameter_status, "/parameters",
        "The candidate does not accept every argument object accepted by the base.")

    def dataset(inventory, component, declaration):
        try:
            return inventory.resolve(declaration["dataset"], component.namespace, "dataset")
        except DocumentError:
            return None

    for name in sorted(left_value["inputs"].keys() | right_value["inputs"].keys()):
        old = left_value["inputs"].get(name)
        new = right_value["inputs"].get(name)
        pointer = json_pointer(("inputs", name))
        label = f"input/{name}/base-to-candidate"
        if old is None:
            add(label, "passed" if new.get("optional", False) else "failed", pointer, "The candidate adds a required input.")
        elif new is None:
            add(label, "failed", pointer, "The candidate removed a previously accepted input.")
        elif (old.get("optional", False) and not new.get("optional", False)) or (
            old.get("allowAdditionalFields", True) and not new.get("allowAdditionalFields", True)
        ):
            add(label, "failed", pointer, "The candidate tightened input presence or additional-field requirements.")
        else:
            relation = compare_datasets(dataset(base, left, old), dataset(candidate, right, new),
                                        new.get("allowAdditionalFields", True), path=here, pointer=pointer)
            add(label, relation.status, pointer, "The candidate input rejects a dataset allowed by the base.")
    for name, old in sorted(left_value["outputs"].items()):
        new = right_value["outputs"].get(name)
        pointer = json_pointer(("outputs", name))
        label = f"output/{name}/candidate-to-base"
        if new is None:
            add(label, "failed", pointer, "The candidate removed a previously promised output.")
            continue
        relation = compare_datasets(dataset(candidate, right, new), dataset(base, left, old), False,
                                    path=here, pointer=pointer)
        add(label, relation.status, pointer, "The candidate output does not satisfy the base promise.")
    report.metadata.setdefault("compatibilityDirections", {})[subject] = directions


LENGTHS = {"minLength", "maxLength"}
NUMERIC = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}
PROPERTY_TYPES = {"string", "integer", "number", "boolean"}


def _property_non_weakening(before, after):
    if before.get("required", False) and not after.get("required", False):
        return "failed"
    old, new = {}, {}
    for prop, schema in ((before, old), (after, new)):
        logical = prop.get("logicalType")
        if logical in PROPERTY_TYPES:
            schema["type"] = logical
        if (values := enum_values(prop)) is not None:
            schema["enum"] = values
        options = prop.get("logicalTypeOptions") or {}
        schema.update({name: value for name, value in options.items() if name in LENGTHS | NUMERIC})
    status = schema_containment(new, old)
    if status == "failed":
        return status
    unresolved_options = set((before.get("logicalTypeOptions") or {})) - LENGTHS - NUMERIC - {"enum"}
    unresolved_options |= set((after.get("logicalTypeOptions") or {})) - LENGTHS - NUMERIC - {"enum"}
    unsupported = unresolved_options or any(
        not json_equal(before.get(key), after.get(key)) for key in ("physicalType", "quality", "unique", "primaryKey", "relationships", "customProperties")
    )
    if unsupported or any(prop.get("logicalType") not in PROPERTY_TYPES for prop in (before, after)):
        return "unknown"
    return status


def _property_pairs(old, new):
    if old.kind == "definition":
        yield (), old.effective, new.effective
        return
    before = {prop["name"]: prop for prop in old.effective.get("properties", [])}
    after = {prop["name"]: prop for prop in new.effective.get("properties", [])}
    for name in sorted(before):
        if name not in after or not json_equal(before[name], after[name]):
            yield ("field", name), before[name], after.get(name)


def _non_weakening(report, old, new, base, candidate, identity):
    if old.effective is None or new.effective is None:
        report.add("DDK-IMPACT-004", NON_WEAKENING, identity, "not_run",
                   reason="A required effective definition did not resolve.")
        return
    subject = f"{identity}/version/{old.version}/{new.version}"
    for parts, before, after in _property_pairs(old, new):
        status = "failed" if after is None else _property_non_weakening(before, after)
        if status == "failed":
            details = [diagnostic("IMPACT-REQUIREMENT-WEAKENED", "The candidate admits values excluded by the prior effective definition.",
                                  path=candidate.display_path(new.path), pointer=new.pointer,
                                  related=[location(base.display_path(old.path), old.pointer)])]
        else:
            details = []
        reason = "A changed restriction uses type or rule semantics outside non-weakening comparison." if status == "unknown" else None
        report.add("DDK-IMPACT-004", NON_WEAKENING, subject + json_pointer(parts), status,
                   reason=reason, diagnostics=details)
    if old.provenance != new.provenance:
        report.metadata.setdefault("changedDefinitionProvenance", {})[subject] = {
            "base": {json_pointer(key): value for key, value in old.provenance.items()},
            "candidate": {json_pointer(key): value for key, value in new.provenance.items()},
        }


def _followed_file_changes(base, candidate):
    roles = {"schema", "definition"}
    old = {(entry.path, entry.role, entry.selection): entry.sha256 for entry in base.files if entry.role in roles}
    new = {(entry.path, entry.role, entry.selection): entry.sha256 for entry in candidate.files if entry.role in roles}
    for path, role, fragment in sorted(old.keys() | new.keys()):
        key = (path, role, fragment)
        if old.get(key) != new.get(key):
            yield (path, role, fragment), "added" if key not in old else "removed" if key not in new else "content"


def _catalog_items(inventory):
    items = {}
    for document in inventory.projects.values():
        catalog = document.value.get("catalog", {})
        for group in ("relationships", "recipes"):
            for item in catalog.get(group, []):
                items[item["id"]] = (group, item)
    return items


def _affected(base, candidate, seeds):
    consumers = defaultdict(set)
    for inventory in (base, candidate):
        for owner, prerequisites in inventory.dependencies.items():
            if owner in inventory.registrations and owner not in inventory.selected_aliases:
                continue
            for prerequisite in prerequisites:
                consumers[prerequisite].add(owner)
                artifact = inventory.artifacts.get(owner)
                if artifact is not None and artifact.kind == "policy":
                    consumers[owner].add(prerequisite)

    paths = defaultdict(list)
    traversed = 0
    for seed in sorted(seeds):
        queue = deque([(seed, [seed])])
        seen = {seed}
        while queue:
            node, path = queue.popleft()
            for consumer in sorted(consumers[node] - seen):
                seen.add(consumer)
                traversed += 1
                if traversed > candidate.limits["maxGraphEdges"]:
                    raise ResourceLimit("Impact dependency-path traversal exceeds the configured edge limit.")
                route = [*path, consumer]
                paths[consumer].append(route)
                queue.append((consumer, route))
    return [{"consumer": consumer, "paths": sorted(routes)} for consumer, routes in sorted(paths.items())]


def _merge_baseline(report, baseline):
    for item in baseline["checks"]:
        report.add(item["requirement"], item["group"], f"base/{item['subject']}", item["status"],
                   required=item["required"], applicable=item["applicable"], evidence=item["evidence"],
                   reason=item.get("reason"), diagnostics=item["diagnostics"], evidence_records=item.get("evidenceRecords", ()),
                   id=f"base/{item['id']}")
    for item in baseline["operationalErrors"]:
        report.error(item)


def _project_id(inventory):
    return inventory.root.value["id"] if inventory.root else "urn:ddk:unknown-project"


def _merge_catalog_impact(report, impact, catalog, base, candidate):
    for item in catalog["checks"]:
        report.add(item["requirement"], item["group"], item["subject"], item["status"],
                   required=item["required"], applicable=item["applicable"], evidence=item["evidence"],
                   reason=item.get("reason"), diagnostics=item["diagnostics"], id=f"catalog/{item['id']}")
    for item in catalog["operationalErrors"]:
        report.error(item)
    report.scope["excludedConsumers"] = sorted(set(
        report.scope["excludedConsumers"] + catalog["scope"]["excludedConsumers"]
    ))
    catalog_metadata = catalog.get("metadata", {})
    report.metadata.update(catalog_metadata)
    scoped = catalog_metadata.get("catalogProjects")
    if scoped and any(
        not json_equal(scoped[side], _project_record(snapshot))
        or (
            catalog_metadata["catalogScopes"][side]
            and snapshot.root.sha256 not in {row["sha256"] for row in catalog_metadata["catalogProjectInputs"][side]}
        )
        for side, snapshot in (("base", base), ("candidate", candidate))
    ):
        report.add("DDK-CATALOG-010", CATALOG_IMPACT, "project-binding", "failed", diagnostics=[
            diagnostic("CATALOG-IMPACT-SNAPSHOT", "A catalog does not describe the corresponding project revision or bytes.")
        ])
        return
    report.completed_profiles.update(catalog["coverage"]["completedProfiles"])
    impact["changed"].extend(catalog["impact"]["changed"])
    by_consumer = {entry["consumer"]: entry["paths"] for entry in impact["affected"]}
    for entry in catalog["impact"]["affected"]:
        by_consumer.setdefault(entry["consumer"], []).extend(entry["paths"])
    impact["affected"] = [{"consumer": consumer, "paths": sorted(paths)}
                          for consumer, paths in sorted(by_consumer.items())]


def _project_record(inventory):
    return {"id": inventory.root.value["id"], "version": inventory.root.value["version"]}


def impact_projects(base, candidate, *, required_groups=(), permitted_roots=(), non_weakening=False, selection=None,
                    limits=None, excluded_consumers=(), base_catalog=None, candidate_catalog=None,
                    require_complete_scope=False):
    if (base_catalog is None) != (candidate_catalog is None):
        raise ValueError("Catalog impact requires both base and candidate catalogs.")
    if require_complete_scope and base_catalog is None:
        raise ValueError("Complete catalog scope can only be requested with two catalog snapshots.")
    base = load_project(base, permitted_roots, limits)
    candidate = load_project(candidate, permitted_roots, limits)
    requested = [*required_groups, CONSUMERS, COMPATIBILITY]
    if non_weakening:
        requested.append(NON_WEAKENING)
    handled = [CONSUMERS, COMPATIBILITY, NON_WEAKENING]
    if base_catalog is not None:
        requested.append(CATALOG_IMPACT)
        handled.append(CATALOG_IMPACT)
        if "catalog.qualification" in requested:
            handled.append("catalog.qualification")
    baseline = check_inventory(base, requested, selection=selection, handled_groups=handled)
    check_inventory(candidate, requested, selection=selection, handled_groups=handled)
    report = candidate.report
    _merge_baseline(report, baseline)
    report.scope["excludedConsumers"] = sorted(set(
        report.scope["excludedConsumers"] + baseline["scope"]["excludedConsumers"] + list(excluded_consumers)
    ))
    report.metadata["baseScope"] = baseline["scope"]
    report.metadata["impactScopeLimit"] = "Only consumers in the explicitly loaded snapshots were examined."
    impact = {"baseProject": _project_id(base), "candidateProject": _project_id(candidate), "changed": [], "affected": []}
    if base.root is None or candidate.root is None:
        report.add("DDK-IMPACT-002", CONSUMERS, "project", "not_run", reason="Both project snapshots must load.")
        return report.build(impact=impact)

    before, after = _records(base), _records(candidate)
    seeds = set()
    for (path, role, fragment), kind in _followed_file_changes(base, candidate):
        suffix = f"#{fragment}" if fragment and role == "definition" else ""
        seeds.add(f"{role}:{path}{suffix}")
        if role == "schema" or fragment or _urn("shared-definition", path) not in before.keys() | after.keys():
            impact["changed"].append({"identity": _urn(f"followed-{role}", path, fragment), "kinds": [kind]})
    old_catalog, new_catalog = _catalog_items(base), _catalog_items(candidate)
    for identity in sorted(old_catalog.keys() | new_catalog.keys()):
        old_item, new_item = old_catalog.get(identity), new_catalog.get(identity)
        if old_item is not None and new_item is not None and old_item[0] == new_item[0] and json_equal(old_item[1], new_item[1]):
            continue
        seeds.add(identity)
        change = "added" if old_item is None else "removed" if new_item is None else "content"
        category = (new_item or old_item)[0]
        impact["changed"].append({"identity": identity, "kinds": [f"catalog-{category}", change]})
    compared = set()
    for identity in sorted(before.keys() | after.keys()):
        for old, new in _pairs(before.get(identity, {}), after.get(identity, {})):
            kinds = _changed(old, new)
            if not kinds:
                continue
            record = {"identity": identity, "kinds": kinds}
            for prefix, snapshot in (("base", old), ("candidate", new)):
                if snapshot:
                    seeds.update(snapshot["nodes"])
                    if snapshot["version"]:
                        record[f"{prefix}Version"] = snapshot["version"]
            impact["changed"].append(record)
            if old and new and old["version"] is not None and old["version"] == new["version"] and (
                old["document"].sha256 != new["document"].sha256
            ):
                report.add("DDK-IMPACT-001", CONSUMERS, f"{identity}/{new['version']}", "failed", diagnostics=[
                    diagnostic("IMPACT-VERSION-REUSE", "The same identity and version is attached to different document bytes.",
                               path=candidate.display_path(new["document"].path),
                               related=[location(base.display_path(old["document"].path))])
                ])
            left, right = old.get("artifact") if old else None, new.get("artifact") if new else None
            if left and right:
                _check_compatibility(report, left, right, base, candidate, identity)
                if right.kind == "component":
                    compared.add((left.alias, right.alias))
                if NON_WEAKENING in report.required_groups and right.kind in {"dataset", "definition"}:
                    _non_weakening(report, left, right, base, candidate, identity)
            elif left and left.kind == "component":
                report.add("DDK-IMPACT-003", COMPATIBILITY, f"{identity}/{left.version}/removed", "failed", diagnostics=[
                    diagnostic("IMPACT-BREAKING-INTERFACE", "The candidate removed a previously available component.",
                               path=base.display_path(left.path))
                ])

    try:
        impact["affected"] = _affected(base, candidate, seeds)
    except ResourceLimit as exc:
        report.error(diagnostic("EXEC-RESOURCE-LIMIT", str(exc), path=candidate.path))
        report.add("DDK-IMPACT-002", CONSUMERS, "project", "not_run", reason=str(exc))
        return report.build(impact=impact)
    obligations = {}
    for entry in impact["affected"]:
        alias = entry["consumer"]
        right = candidate.artifacts.get(alias)
        left = base.artifacts.get(alias)
        if left and right and left.kind == right.kind == "component" and (left.alias, right.alias) not in compared:
            _check_compatibility(report, left, right, base, candidate, right.identity)
        if right is None and alias in new_catalog:
            obligations[alias] = "metadata-regeneration"
        elif right is None:
            obligations[alias] = "absent-from-candidate-scope"
        elif right.kind == "policy":
            obligations[alias] = "requalification"
        elif right.kind in {"component", "design"}:
            obligations[alias] = "review-computation-and-requalification"
        else:
            obligations[alias] = "review-metadata-and-requalification"
    report.metadata["affectedObligations"] = obligations
    report.add("DDK-IMPACT-002", CONSUMERS, "project", "passed", evidence="inferred")
    if base_catalog is not None:
        catalog = compare_catalogs(base_catalog, candidate_catalog,
                                   require_complete_scope=require_complete_scope,
                                   excluded_consumers=report.scope["excludedConsumers"],
                                   required_groups=("catalog.qualification",) if "catalog.qualification" in requested else (),
                                   limits=limits)
        _merge_catalog_impact(report, impact, catalog, base, candidate)
    impact["changed"].sort(key=lambda item: (item["identity"], item.get("baseVersion", ""), item.get("candidateVersion", "")))
    if not report.operational_errors and all(
        item["status"] == "passed" or not item["applicable"] for item in report.checks
        if item["group"] in handled and item["required"]
    ):
        report.completed_profiles.add("impact")
    return report.build(impact=impact)
