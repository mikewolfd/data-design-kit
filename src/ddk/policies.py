"""Explicit project rules over declared values and field dependencies."""

from collections import Counter
from pathlib import Path

from .documents import DocumentError, json_pointer, pointer_get
from .interfaces import json_contains
from .results import diagnostic, location

KNOWN_RULES = {"fields-exist", "row-identity", "quality-fields", "vocabulary"}


def _annotations(value, key):
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
            declarations = _annotations(target.effective, "rowIdentity")
            valid = len(declarations) == 1 and _names(declarations[0]) and set(declarations[0]) <= fields
            diagnostics = [] if valid else [
                diagnostic("POLICY-ROW-IDENTITY", "Expected one rowIdentity annotation with distinct existing field names.",
                           **where, related=related)
            ]
            report.add(requirement, "core.policies", subject, "passed" if valid else "failed", diagnostics=diagnostics)
            if valid:
                report.metadata.setdefault("rowIdentityAssumptions", {})[target.alias] = declarations[0]
        else:
            _quality(report, requirement, subject, target, fields, where, related, inventory.display_path)


def _quality(report, requirement, subject, target, fields, where, related, display_path):
    total = 0
    for rule, parts, containing in _quality_rules(target.effective):
        total += 1
        annotations = _annotations(rule, "fieldDependencies")
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
