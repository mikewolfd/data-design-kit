"""Explicit project rules over declared values and field dependencies."""

from collections import Counter
from pathlib import Path

from .catalog_access import CatalogError, row_identity_names
from .documents import DocumentError, json_pointer, pointer_get
from .interfaces import json_contains
from .ports import product_ports
from .results import diagnostic, location

KNOWN_RULES = {"fields-exist", "row-identity", "quality-fields", "vocabulary", "layer-order", "view-sources", "concept-joins"}


def ddk_annotations(value, key):
    """Values of the ODCS custom properties that carry a DDK convention (`vendor: ddk`)."""
    return [entry.get("value") for entry in value.get("customProperties", [])
            if entry.get("vendor") == "ddk" and entry.get("property") == key]



def _names(value, *, empty=False):
    return isinstance(value, list) and (bool(value) or empty) and all(
        isinstance(name, str) and name for name in value
    ) and len(value) == len(set(value))


def _quality_rules(value, parts=(), containing=None):
    for index, rule in enumerate(value.get("quality", [])):
        yield rule, (*parts, "quality", index), containing
    for index, prop in enumerate(value.get("properties", [])):
        yield from _quality_rules(prop, (*parts, "properties", index), prop.get("name"))
    if isinstance(value.get("items"), dict):
        yield from _quality_rules(value["items"], (*parts, "items"), containing)


def check_policy(inventory, artifact):
    report = inventory.report
    path = inventory.display_path(artifact.path)
    rules = artifact.value["rules"]
    duplicate = {name for name, count in Counter(rule["id"] for rule in rules).items() if count > 1}
    for index, rule in enumerate(rules):
        subject = f"{artifact.alias}/rule/{rule['id']}"
        kind = rule["check"]
        pointer = json_pointer(("rules", index))
        where = {"path": path, "pointer": pointer}
        if rule["id"] in duplicate:
            report.add("DDK-POLICY-001", "core.policies", f"{subject}/{index}", "failed", diagnostics=[
                diagnostic("POLICY-RULE-DUPLICATE", f"Policy rule ID {rule['id']!r} is repeated.", **where)
            ])
            continue
        if kind not in KNOWN_RULES:
            reason = "The requested policy extension is unavailable."
            report.add("DDK-POLICY-001", "core.policies", subject, "unknown", reason=reason, diagnostics=[
                diagnostic("POLICY-RULE-UNKNOWN", reason, severity="warning", **where)
            ])
            continue
        if kind == "layer-order":
            _layer_order(inventory, artifact, rule, subject, where)
            continue
        if kind == "view-sources":
            _view_sources(inventory, artifact, rule, subject, where)
            continue
        if kind == "concept-joins":
            _concept_joins(inventory, artifact, rule, subject, where)
            continue
        requirement = {
            "fields-exist": "DDK-POLICY-002", "row-identity": "DDK-POLICY-002",
            "quality-fields": "DDK-POLICY-003", "vocabulary": "DDK-POLICY-004",
        }[kind]
        try:
            target = inventory.resolve(rule.get("artifact", rule.get("dataset")), artifact.namespace,
                                       None if kind == "vocabulary" else "dataset")
        except DocumentError as exc:
            report.add(requirement, "core.policies", subject, "not_run", reason=str(exc),
                       diagnostics=[diagnostic(exc.code, str(exc), **where)])
            continue
        related = [location(inventory.display_path(target.path), target.pointer)]
        if kind == "vocabulary":
            try:
                selected = pointer_get(target.value, rule["pointer"])
                values = selected if rule.get("each", False) else [selected]
                valid = isinstance(values, list) and all(json_contains(rule["allowed"], value) for value in values)
            except (IndexError, KeyError, ValueError):
                valid = False
            diagnostics = [] if valid else [
                diagnostic("POLICY-VOCABULARY", "The selected value is absent or outside the policy vocabulary.",
                           **where, related=related)
            ]
            report.add(requirement, "core.policies", subject, "passed" if valid else "failed", diagnostics=diagnostics)
            continue
        if target.effective is None:
            report.add(requirement, "core.policies", subject, "not_run",
                       reason="The target's effective definition is unavailable.")
            continue
        fields = {prop["name"] for prop in target.effective.get("properties", [])}
        if kind == "fields-exist":
            absent = sorted(set(rule["fields"]) - fields)
            diagnostics = [diagnostic("POLICY-FIELD-MISSING", f"Dataset field {name!r} is missing.",
                                      **where, related=related) for name in absent]
            report.add(requirement, "core.policies", subject, "failed" if absent else "passed", diagnostics=diagnostics)
        elif kind == "row-identity":
            try:
                names = row_identity_names(target.effective)
            except DocumentError:
                names = None
            diagnostics = [] if names else [
                diagnostic("POLICY-ROW-IDENTITY", "Expected a row identity: ODCS primaryKey properties with unambiguous "
                           "positions, or one rowIdentity annotation with distinct existing field names.",
                           **where, related=related)
            ]
            report.add(requirement, "core.policies", subject, "passed" if names else "failed", diagnostics=diagnostics)
            if names:
                report.metadata.setdefault("rowIdentityAssumptions", {})[target.alias] = names
        else:
            _quality(report, requirement, subject, target, fields, where, related, inventory.display_path)


def _quality(report, requirement, subject, target, fields, where, related, display_path):
    total = 0
    for rule, parts, containing in _quality_rules(target.effective):
        total += 1
        annotations = ddk_annotations(rule, "fieldDependencies")
        dependencies = annotations[0] if len(annotations) == 1 else []
        inherited = target.provenance.get(parts[:-1], {})
        origin = inherited.get("source")
        if origin:
            origin = {"path": display_path(Path(origin["path"])),
                      "pointer": f"{origin['pointer']}/{parts[-1]}"}
        else:
            origin = location(display_path(target.path), target.pointer + json_pointer(parts))
        references = [*related, origin]
        reasons = None
        details = []
        status = "passed"
        if len(annotations) > 1 or (annotations and not _names(dependencies, empty=True)):
            status = "failed"
            details.append(diagnostic("POLICY-QUALITY-DEPENDENCIES-INVALID",
                                      "Expected distinct field names in one fieldDependencies annotation.",
                                      **where, related=references))
        elif absent := sorted(set(dependencies) - fields):
            status = "failed"
            details.extend(diagnostic("POLICY-QUALITY-FIELD-MISSING", f"Referenced field {name!r} is missing.",
                                      **where, related=references) for name in absent)
        elif rule.get("type") in {"sql", "custom"} and not annotations:
            status = "unknown"
            reasons = "The SQL or custom quality rule has no declared complete field-dependency list."
            details.append(diagnostic("POLICY-QUALITY-DEPENDENCIES-UNKNOWN", reasons, **where, related=references,
                                      severity="warning"))
        item = f"{subject}{json_pointer(parts)}"
        report.add(requirement, "core.policies", item, status, reason=reasons, diagnostics=details)
        if status == "passed":
            report.metadata.setdefault("qualityFieldDependencies", {})[item] = list(dict.fromkeys(
                ([containing] if containing else []) + dependencies
            ))
    if not total:
        report.add(requirement, "core.policies", subject, "not_run", applicable=False,
                   reason="The selected definition has no quality rules.")


def record_definition_uses(inventory, aliases):
    consumers = {}
    for alias in sorted(aliases):
        artifact = inventory.artifacts.get(alias)
        if artifact is None:
            continue
        for path, fragment in artifact.definitions:
            ref = inventory.display_path(path) + (f"#{fragment}" if fragment else "")
            consumers.setdefault(ref, []).append(alias)
        if artifact.definitions:
            inventory.report.metadata.setdefault("definitionProvenance", {})[alias] = {
                json_pointer(key): item for key, item in sorted(artifact.provenance.items(), key=lambda pair: json_pointer(pair[0]))
            }
    inventory.report.metadata["definitionUses"] = consumers
    for alias in sorted(aliases):
        artifact = inventory.artifacts.get(alias)
        if artifact is None or artifact.kind != "definition":
            continue
        path = inventory.display_path(artifact.path)
        if path not in consumers:
            inventory.report.add("DDK-POLICY-005", "core.policies", alias, "not_run", required=False,
                                 applicable=False, reason="The definition has no loaded consumers.", diagnostics=[
                diagnostic("POLICY-DEFINITION-UNUSED", "The registered definition has no loaded consumers.",
                           path=path, severity="warning")
            ])


def _layer_edges(inventory):
    """Yield (kind, consumer, consumer namespace, target alias, declaration location) and unresolved reasons."""
    def site(path, parts=()):
        return location(inventory.display_path(path), json_pointer(parts))

    try:
        for product, ports in product_ports(inventory):
            for direction, port, version, dataset in ports:
                index = next(i for i, item in enumerate(product.value[f"{direction}Ports"])
                             if (item["name"], item.get("version")) == (port, version))
                yield ("port", f"{product.alias} {direction} port {port}", product.namespace, dataset.alias,
                       site(product.path, (f"{direction}Ports", index)))
    except (CatalogError, DocumentError) as exc:
        yield str(exc)
    for namespace, document in inventory.projects.items():
        configuration = document.value.get("catalog", {})
        for index, item in enumerate(configuration.get("relationships", ())):
            if any("dataset" not in item[side] for side in ("source", "target")):
                continue
            try:
                source = inventory.resolve(item["source"]["dataset"], namespace, "dataset")
                target = inventory.resolve(item["target"]["dataset"], namespace, "dataset")
            except DocumentError as exc:
                yield f"Relationship {item['id']}: {exc}"
                continue
            yield ("relationship", f"relationship {item['id']}", source.namespace, target.alias,
                   site(document.path, ("catalog", "relationships", index)))
        for index, item in enumerate(configuration.get("recipes", ())):
            for name, reference in sorted(item["inputs"].items()):
                try:
                    target = inventory.resolve(reference, namespace, "dataset")
                except DocumentError as exc:
                    yield f"Recipe {item['id']}: {exc}"
                    continue
                yield ("recipe input", f"recipe {item['id']} input {name}", namespace, target.alias,
                       site(document.path, ("catalog", "recipes", index, "inputs", name)))
    for alias, artifact in sorted(inventory.artifacts.items()):
        group = {"component": "inputs", "design": "sources"}.get(artifact.kind)
        for name, member in sorted(artifact.value.get(group, {}).items()) if group else ():
            try:
                target = inventory.resolve(member["dataset"], artifact.namespace, "dataset")
            except DocumentError as exc:
                yield f"Production {alias}: {exc}"
                continue
            yield ("production input", f"{artifact.kind} {alias} input {name}", artifact.namespace, target.alias,
                   site(artifact.path, (group, name)))


def _layer_order(inventory, artifact, rule, subject, where):
    """Fail when a declared dependency points from a lower layer to a higher one."""
    report = inventory.report
    names = [layer["name"] for layer in rule["layers"]]
    ranks, invalid = {}, [] if len(set(names)) == len(names) else ["Layer names must be unique."]
    for rank, layer in enumerate(rule["layers"]):
        for reference in layer["namespaces"]:
            namespace = inventory.scoped(reference, artifact.namespace, whole=True)
            if namespace not in inventory.projects:
                invalid.append(f"Namespace {reference!r} is not a loaded project namespace.")
            elif namespace in ranks:
                invalid.append(f"Namespace {reference!r} is assigned to more than one layer.")
            else:
                ranks[namespace] = rank
    if invalid:
        report.add("DDK-POLICY-006", "core.policies", subject, "failed", diagnostics=[
            diagnostic("POLICY-LAYER-INVALID", message, **where) for message in invalid])
        return

    def rank_of(namespace):
        while namespace not in ranks and namespace:
            namespace = namespace.rpartition("/")[0]
        return ranks.get(namespace)

    violations, uncertain, checked = [], [], 0
    for edge in _layer_edges(inventory):
        if isinstance(edge, str):
            uncertain.append(edge)
            continue
        kind, consumer, namespace, target, declared = edge
        low, high = rank_of(namespace), rank_of(inventory.artifacts[target].namespace)
        if low is None or high is None:
            uncertain.append(f"The {consumer} -> {target} edge has an endpoint outside every layer.")
            continue
        checked += 1
        if high > low:
            violations.append(diagnostic("POLICY-LAYER-ORDER", f"The {consumer} in layer {names[low]!r} points to "
                                         f"{target} in higher layer {names[high]!r}.", **where, related=[declared]))
    report.metadata.setdefault("layerOrder", {})[subject] = {"layers": names, "checkedEdges": checked}
    details = violations + [diagnostic("POLICY-LAYER-UNASSIGNED", reason, severity="warning", **where)
                            for reason in uncertain]
    status = "failed" if violations else "unknown" if uncertain else "passed"
    report.add("DDK-POLICY-006", "core.policies", subject, status, diagnostics=details,
               reason="Some declared dependencies could not be placed in a layer." if status == "unknown" else None)


def _properties(value, parts=()):
    for index, prop in enumerate(value.get("properties", ())):
        yield prop, (*parts, "properties", index)
        yield from _properties(prop, (*parts, "properties", index))
    if isinstance(value.get("items"), dict):
        yield from _properties(value["items"], (*parts, "items"))


def _concept_joins(inventory, artifact, rule, subject, where):
    """A concept-joins rule's compatible pairs must name registered shared definitions.

    Catalog assembly applies the rule to relationships (DDK-CATALOG-004); here only its references are checked.
    """
    problems = []
    for pair in rule.get("compatible", ()):
        for reference in pair:
            try:
                inventory.resolve(reference, artifact.namespace, "definition")
            except DocumentError as exc:
                problems.append(diagnostic(exc.code, str(exc), **where))
    inventory.report.add("DDK-POLICY-005", "core.policies", subject, "failed" if problems else "passed",
                         diagnostics=problems)


def _view_sources(inventory, artifact, rule, subject, where):
    """In the selected datasets, `transformSourceObjects` names stored siblings: each such property is a view.

    ODCS uses the field for upstream objects in general; this rule applies the
    project's narrower convention only where the policy selects it.
    """
    report = inventory.report
    targets, scope, unavailable = {}, [], []
    for reference in rule.get("datasets", ()):
        try:
            target = inventory.resolve(reference, artifact.namespace, "dataset")
        except DocumentError as exc:
            unavailable.append(str(exc))
            continue
        targets[target.alias] = target
    for reference in rule.get("namespaces", ()):
        namespace = inventory.scoped(reference, artifact.namespace, whole=True)
        if namespace not in inventory.projects:
            scope.append(diagnostic("POLICY-VIEW-SCOPE", f"Namespace {reference!r} is not a loaded project namespace.", **where))
        targets.update((alias, item) for alias, item in inventory.artifacts.items() if item.kind == "dataset"
                       and (item.namespace == namespace or item.namespace.startswith(f"{namespace}/")))
    problems, views = list(scope), 0
    for alias, target in sorted(targets.items()):
        if target.effective is None:
            unavailable.append(f"The effective definition of {alias} is unavailable.")
            continue
        stored = {prop["name"] for prop in target.effective.get("properties", ()) if not prop.get("transformSourceObjects")}
        for prop, parts in _properties(target.effective):
            sources = prop.get("transformSourceObjects")
            if not sources:
                continue
            views += 1
            related = [location(inventory.display_path(target.path), target.pointer + json_pointer(parts))]
            if not prop.get("transformLogic"):
                problems.append(diagnostic("POLICY-VIEW-SOURCE", f"View {alias}.{prop['name']} has no transformLogic.",
                                           **where, related=related))
            problems.extend(diagnostic("POLICY-VIEW-SOURCE", f"View {alias}.{prop['name']} reads {name!r}, which is not "
                                       "a stored property of the same object.", **where, related=related)
                            for name in sources if name not in stored)
    report.metadata.setdefault("viewSources", {})[subject] = {"datasets": len(targets), "views": views}
    status = "failed" if problems else "not_run" if unavailable else "passed"
    report.add("DDK-POLICY-007", "core.policies", subject, status, diagnostics=problems,
               reason=" ".join(unavailable) if status == "not_run" else None)
