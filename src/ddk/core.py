"""Offline checking of project declarations."""

from collections import defaultdict
import heapq

from .capabilities import discover_capabilities
from .datasets import check_view_properties, record_comparison
from .documents import DocumentError, RegistryError, ResourceLimit, json_pointer, schema_registry
from .interfaces import check_arguments, check_interface
from .inventory import ProjectInventory
from .policies import check_policy, record_definition_uses
from .results import CORE_GROUPS, diagnostic, location

PLAN_GROUPS = {"plan.compile", "plan.output", "plan.consumer", "plan.standard"}


def _reference_sites(artifact):
    value = artifact.value
    if artifact.kind == "component":
        for group in ("inputs", "outputs"):
            for name, binding in sorted(value[group].items()):
                yield (group, name, "dataset"), binding["dataset"], "dataset"
    elif artifact.kind == "design":
        for group in ("sources", "exports"):
            for name, binding in sorted(value[group].items()):
                yield (group, name, "dataset"), binding["dataset"], "dataset"
        for name, step in sorted(value["steps"].items()):
            yield ("steps", name, "component"), step["component"], "component"
    elif artifact.kind == "policy":
        for index, rule in enumerate(value["rules"]):
            for key in ("artifact", "dataset"):
                if key in rule:
                    yield ("rules", index, key), rule[key], "dataset" if key == "dataset" else None


def _catalog_dependencies(inventory):
    # These authored relations are useful to impact. Resolution and catalog
    # diagnostics belong to an explicitly invoked catalog profile.
    for namespace, doc in inventory.projects.items():
        configuration = doc.value.get("catalog", {})
        for binding in configuration.get("ports", []):
            owner = inventory.scoped(binding["product"], namespace)
            inventory.dependency(owner, inventory.scoped(binding["dataset"], namespace))
        for group, items in (("recipe", configuration.get("recipes", [])),
                             ("relationship", configuration.get("relationships", []))):
            for item in items:
                if group == "recipe":
                    references = list(item["inputs"].values())
                    if "resultDataset" in item:
                        references.append(item["resultDataset"])
                else:
                    references = [endpoint["dataset"] for endpoint in (item["source"], item["target"])
                                  if "dataset" in endpoint]
                for reference in references:
                    inventory.dependency(item["id"], inventory.scoped(reference, namespace))
                for relationship in (*item.get("relationships", ()), *item.get("contextualRelationships", ())):
                    inventory.dependency(item["id"], relationship)


def _prepare_references(inventory):
    for alias, artifact in sorted(inventory.artifacts.items()):
        for parts, reference, kind in _reference_sites(artifact):
            pointer = json_pointer(parts)
            try:
                inventory.dependency(alias, inventory.scoped(reference, artifact.namespace), artifact.path, pointer)
                inventory.resolve(reference, artifact.namespace, kind)
            except DocumentError as exc:
                invalid = exc.code == "DOC-PREREQUISITE-INVALID"
                inventory.report.add("DDK-REF-001", "core.references", f"{alias}{pointer}",
                                     "not_run" if invalid else "failed", reason=str(exc) if invalid else None,
                                     diagnostics=[diagnostic(exc.code, str(exc), path=inventory.display_path(artifact.path),
                                                             pointer=pointer)])


def _resource_error(inventory, exc):
    record = diagnostic("EXEC-RESOURCE-LIMIT", str(exc), path=inventory.display_path(inventory.path))
    inventory.report.error(record)
    inventory.report.add("DDK-SAFE-003", "core.documents", "project-resource-limit", "not_run",
                         reason=str(exc), diagnostics=[record])


def load_project(path, permitted_roots=(), limits=None):
    inventory = ProjectInventory(path, permitted_roots, limits)
    try:
        schema_registry.cache_clear()
        inventory.visit(inventory.path)
        if inventory.import_aliases:
            inventory.report.metadata["importAliases"] = dict(sorted(inventory.import_aliases.items()))
        for alias, (namespace, project, entry) in sorted(inventory.registrations.items()):
            inventory.index(alias, namespace, project, entry)
        inventory.resolve_definitions()
        _prepare_references(inventory)
        _catalog_dependencies(inventory)
    except ResourceLimit as exc:
        _resource_error(inventory, exc)
    except RegistryError as exc:
        record = diagnostic("DOC-SCHEMA-REGISTRY", str(exc), path=inventory.display_path(inventory.path))
        inventory.report.error(record)
        inventory.report.add("DDK-SYNTAX-002", "core.documents", "schema-registry", "not_run",
                             reason=str(exc), diagnostics=[record])
    inventory.report.scope = inventory.scope
    inventory.freeze_inputs()
    return inventory


def _resolve(inventory, reference, artifact, kind):
    try:
        return inventory.resolve(reference, artifact.namespace, kind)
    except DocumentError:
        return None


def _select(inventory, selection):
    if not selection:
        return set(inventory.registrations), set()
    filters = (selection,) if isinstance(selection, str) else tuple(selection)
    selected = set()
    for entry in filters:
        try:
            key = inventory.scoped(entry, "")
        except DocumentError:
            key = ""
        matches = {alias for alias in inventory.registrations if key and (alias == key or alias.startswith(f"{key}/"))}
        if not matches:
            inventory.report.add("DDK-CHECK-002", "core.references", f"selection:{entry}", "failed",
                                 diagnostics=[diagnostic("REF-SELECTION-MISSING", "The requested selection did not match an artifact or namespace.",
                                                         path=inventory.display_path(inventory.path))])
        selected.update(matches)
    # Policies that gate any selected target travel with that target.
    pending = list(selected)
    reverse_policies = defaultdict(set)
    for alias, artifact in inventory.artifacts.items():
        if artifact.kind == "policy":
            for prerequisite in inventory.dependencies.get(alias, ()):
                reverse_policies[prerequisite].add(alias)
    while pending:
        alias = pending.pop()
        related = inventory.dependencies.get(alias, set()) | reverse_policies[alias]
        for prerequisite in related & inventory.registrations.keys() - selected:
            selected.add(prerequisite)
            pending.append(prerequisite)
    return selected, set(inventory.registrations) - selected


def _selection_scope(inventory, selection, excluded):
    report = inventory.report
    selected = inventory.selected_aliases
    namespaces = {""}
    for alias in selected:
        namespace = inventory.registrations[alias][0]
        while namespace:
            namespaces.add(namespace)
            namespace = namespace.rpartition("/")[0]

    def owner(subject):
        while subject:
            if subject in inventory.registrations:
                return subject
            subject = subject.rpartition("/")[0]
        return None

    def checked(subject):
        if subject.startswith("project:"):
            namespace = subject.removeprefix("project:")
            return namespace == "/" or namespace in namespaces
        return owner(subject) not in excluded

    report.checks[:] = [item for item in report.checks if checked(item["subject"])]
    paths = {inventory.display_path(path) for subject, path in inventory.source_paths.items() if checked(subject)}
    excluded_paths = {inventory.display_path(path) for subject, path in inventory.source_paths.items() if not checked(subject)}
    report.operational_errors[:] = [item for item in report.operational_errors
                                    if item["location"]["path"] not in excluded_paths - paths]
    report.metadata["selection"] = [selection] if isinstance(selection, str) else list(selection)
    return namespaces


def _graph(inventory, design, edge_count):
    report = inventory.report
    value = design.value
    steps = value["steps"]
    path = inventory.display_path(design.path)
    components = {name: _resolve(inventory, step["component"], design, "component") for name, step in steps.items()}
    sources = {name: _resolve(inventory, item["dataset"], design, "dataset") for name, item in value["sources"].items()}
    children = {name: set() for name in steps}
    indegree = dict.fromkeys(steps, 0)
    used = set()

    def inspect(origin, subject, parts, consumer=None):
        nonlocal edge_count
        pointer = json_pointer(parts)
        where = {"path": path, "pointer": pointer}
        if "source" in origin:
            name = origin["source"]
            if name not in sources:
                report.add("DDK-GRAPH-001", "core.graph", subject, "failed", diagnostics=[
                    diagnostic("REF-SOURCE-MISSING", f"Design source {name!r} does not exist.", **where)
                ])
            elif sources[name] is None:
                report.add("DDK-GRAPH-001", "core.graph", subject, "not_run",
                           reason="The source dataset declaration did not resolve.")
            else:
                return ("source", name, None)
            return None

        name, output = origin["step"], origin["output"]
        if name not in steps:
            report.add("DDK-GRAPH-001", "core.graph", subject, "failed", diagnostics=[
                diagnostic("REF-STEP-MISSING", f"Producing step {name!r} does not exist.", **where)
            ])
            return None
        used.add(name)
        if consumer is not None and consumer not in children[name]:
            children[name].add(consumer)
            indegree[consumer] += 1
            edge_count += 1
            if edge_count > inventory.limits["maxGraphEdges"]:
                raise ResourceLimit(f"Design step edges exceed {inventory.limits['maxGraphEdges']}.")
        producer = components[name]
        if producer is None:
            report.add("DDK-GRAPH-001", "core.graph", subject, "not_run",
                       reason="The producing component did not resolve.")
            return None
        if output not in producer.value["outputs"]:
            report.add("DDK-GRAPH-001", "core.graph", subject, "failed", diagnostics=[
                diagnostic("REF-OUTPUT-MISSING", f"Output port {output!r} is not declared.", **where,
                           related=[location(inventory.display_path(producer.path), "/outputs")])
            ])
            return None
        return ("step", name, output)

    inputs = {}
    for name, step in sorted(steps.items()):
        inputs[name] = {port: inspect(origin, f"{design.alias}/step/{name}/input/{port}",
                                      ("steps", name, "inputs", port), name)
                        for port, origin in sorted(step["inputs"].items())}
    exports = {name: inspect(item["from"], f"{design.alias}/export/{name}", ("exports", name, "from"))
               for name, item in sorted(value["exports"].items())}
    ready = [name for name, count in indegree.items() if count == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for child in children[name]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    blocked = {name for name, count in indegree.items() if count}
    disconnected = sorted(steps.keys() - used)
    details = [diagnostic("GRAPH-STEP-UNCONNECTED", f"Step {name!r} has no consuming step or export.",
                          path=path, pointer=json_pointer(("steps", name)), severity="warning")
               for name in disconnected]
    if blocked:
        details.append(diagnostic("GRAPH-CYCLE", f"A step cycle blocks {', '.join(sorted(blocked))}.",
                                  path=path, pointer="/steps"))
    report.add("DDK-GRAPH-001", "core.graph", design.alias, "failed" if blocked else "passed", diagnostics=details)
    report.metadata.setdefault("stepOrder", {})[design.alias] = order
    return components, sources, inputs, exports, blocked, edge_count


def _check_design(inventory, design, validators, edge_count):
    report = inventory.report
    path = inventory.display_path(design.path)
    components, sources, inputs, exports, blocked, edge_count = _graph(inventory, design, edge_count)
    invalid_producers = {name for name, component in components.items() if component is None}
    invalid_producers.update(name for name, origins in inputs.items() if None in origins.values())
    for name in report.metadata["stepOrder"][design.alias]:
        if any(origin and origin[0] == "step" and origin[1] in invalid_producers for origin in inputs[name].values()):
            invalid_producers.add(name)

    def dataset_for(origin):
        if origin is None:
            return None
        group, name, output = origin
        if group == "source":
            return sources[name]
        if name in blocked or name in invalid_producers:
            return None
        component = components[name]
        return _resolve(inventory, component.value["outputs"][output]["dataset"], component, "dataset")

    for name, step in sorted(design.value["steps"].items()):
        component = components[name]
        subject = f"{design.alias}/step/{name}"
        if component is None or name in blocked:
            report.add("DDK-CALL-002", "core.calls", subject, "not_run",
                       reason="The step component or its acyclic dependencies did not resolve.")
            for port in sorted(step["inputs"]):
                record_comparison(inventory, f"{subject}/input/{port}", None, None, True,
                                  path, json_pointer(("steps", name, "inputs", port)))
            continue

        check_arguments(inventory, design, name, step, component,
                        validators.get(component.alias), validators.get(design.alias))
        ports = component.value["inputs"]
        supplied = step["inputs"]
        related = [location(inventory.display_path(component.path), "/inputs")]
        kwargs = {"path": path, "pointer": json_pointer(("steps", name, "inputs")), "related": related}
        missing = sorted(port for port, declaration in ports.items() if not declaration.get("optional", False)
                         and port not in supplied)
        extra = sorted(supplied.keys() - ports.keys())
        diagnostics = [diagnostic("CALL-INPUT-MISSING", f"Required input port {port!r} is absent.", **kwargs)
                       for port in missing]
        diagnostics.extend(diagnostic("CALL-INPUT-UNKNOWN", f"Input port {port!r} is undeclared.", **kwargs)
                           for port in extra)
        report.add("DDK-CALL-002", "core.calls", subject, "failed" if diagnostics else "passed", diagnostics=diagnostics)
        for port in sorted(supplied.keys() & ports.keys()):
            declaration = ports[port]
            required = _resolve(inventory, declaration["dataset"], component, "dataset")
            record_comparison(inventory, f"{subject}/input/{port}", dataset_for(inputs[name][port]), required,
                              declaration.get("allowAdditionalFields", True), path,
                              json_pointer(("steps", name, "inputs", port)))
    for name, export in sorted(design.value["exports"].items()):
        required = _resolve(inventory, export["dataset"], design, "dataset")
        record_comparison(inventory, f"{design.alias}/export/{name}", dataset_for(exports[name]), required,
                          export.get("allowAdditionalFields", False), path, json_pointer(("exports", name)), export=True)
    return edge_count


def _inventory_unavailable(inventory, handled_groups):
    report = inventory.report
    for group in report.required_groups:
        if group in CORE_GROUPS or group in handled_groups:
            continue
        report.missing_capabilities.add(group)
        inventory_subjects = []
        if group in PLAN_GROUPS:
            for alias in sorted(inventory.selected_aliases):
                design = inventory.artifacts.get(alias)
                if design is None or design.kind != "design":
                    continue
                for name, export in sorted(design.value["exports"].items()):
                    origin = export["from"]
                    step = design.value["steps"].get(origin.get("step"))
                    component = _resolve(inventory, step["component"], design, "component") if step else None
                    code = "ADAPTER-IMPLEMENTATION-MISSING" if component and "implementation" not in component.value else "ADAPTER-CAPABILITY-MISSING"
                    inventory_subjects.append((f"{alias}/export/{name}", code))
        if not inventory_subjects:
            inventory_subjects = [("project", "ADAPTER-CAPABILITY-MISSING")]
        for subject, code in inventory_subjects:
            reason = "No supported implementation is declared." if code == "ADAPTER-IMPLEMENTATION-MISSING" else (
                "The requested check group has no explicitly selected adapter."
            )
            report.add("DDK-ADAPTER-001", group, subject, "not_run", evidence="inferred" if group in PLAN_GROUPS else "declared",
                       reason=reason, diagnostics=[diagnostic(code, reason, path=inventory.display_path(inventory.path),
                                                              severity="warning")])


def check_inventory(inventory, required_groups=(), *, selection=None, handled_groups=(), lock=None, locked=False,
                    adapter_manifests=(), verified_release=None):
    """Check one freshly loaded inventory. Adapters can fill explicitly handled groups."""
    report = inventory.report
    from .locks import tool_identities

    report.tools = tool_identities()
    inventory.selected_aliases, excluded = _select(inventory, selection)
    namespaces = _selection_scope(inventory, selection, excluded) if selection else inventory.projects.keys()
    report.scope = inventory.scope
    report.scope["excludedConsumers"] = sorted(excluded)
    requested = [group for namespace, doc in inventory.projects.items() if namespace in namespaces
                 for group in doc.value["requiredChecks"]]
    report.required_groups = list(dict.fromkeys([*CORE_GROUPS, *requested, *required_groups]))
    validators = {}
    try:
        # These references are additional lock inputs. Build their inventory
        # before evaluating call arguments or reading a supplied lock.
        for alias in sorted(inventory.selected_aliases):
            artifact = inventory.artifacts.get(alias)
            if artifact and artifact.kind in {"component", "design"}:
                validators[alias] = check_interface(inventory, artifact)
        if adapter_manifests:
            discover_capabilities(inventory, adapter_manifests, verified_release)
        if locked or lock is not None:
            from .locks import verify_lock
            verify_lock(inventory, lock, locked=locked)
        edge_count = 0
        for alias in sorted(inventory.selected_aliases):
            artifact = inventory.artifacts.get(alias)
            if artifact and artifact.kind == "design":
                edge_count = _check_design(inventory, artifact, validators, edge_count)
        for alias in sorted(inventory.selected_aliases):
            artifact = inventory.artifacts.get(alias)
            if artifact and artifact.kind == "dataset":
                check_view_properties(inventory, artifact)
            elif artifact and artifact.kind == "policy":
                check_policy(inventory, artifact)
        record_definition_uses(inventory, inventory.selected_aliases)
    except ResourceLimit as exc:
        _resource_error(inventory, exc)
    _inventory_unavailable(inventory, handled_groups)
    report.scope["followedReferences"] = inventory.scope["followedReferences"]
    if not report.operational_errors and all(
        item["status"] == "passed" or not item["applicable"] or not item["required"]
        for item in report.checks if item["group"] in CORE_GROUPS
    ):
        report.completed_profiles.add("core")
    return report.build()


def check_project(path, required_groups=(), permitted_roots=(), lock=None, locked=False, selection=None, limits=None,
                  *, adapter_manifests=(), verified_release=None):
    inventory = load_project(path, permitted_roots, limits)
    return check_inventory(inventory, required_groups, selection=selection, lock=lock, locked=locked,
                           adapter_manifests=adapter_manifests, verified_release=verified_release)
