"""Project, artifact and followed-input inventory."""

from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
import re
from types import MappingProxyType

from .definitions import DefinitionResolver, RemoteDefinition, duplicate_properties, select_named
from .documents import DEFAULT_LIMITS, Document, DocumentError, ResourceLimit, freeze_json, json_pointer, read_json, resolve_path, validate_document
from .results import CORE_GROUPS, ReportBuilder, diagnostic, location

ARTIFACT_REFERENCE = re.compile(r"/?[a-z][a-z0-9-]*(?:/[a-z][a-z0-9-]*)*")


def scoped_alias(reference, namespace):
    if not ARTIFACT_REFERENCE.fullmatch(reference):
        raise DocumentError("REF-ARTIFACT-INVALID", "Invalid artifact alias.")
    if reference.startswith("/"):
        return reference[1:]
    return f"{namespace}/{reference}" if namespace else reference


@dataclass(frozen=True)
class Artifact:
    alias: str
    namespace: str
    kind: str
    document: Document
    identity: str
    version: str | None
    registration: dict
    selected: dict | None = None
    effective: dict | None = None
    selection: str | None = None
    pointer: str = ""
    provenance: dict = field(default_factory=dict)
    definitions: tuple = ()
    definition_status: str = "passed"
    definition_sources: tuple = ()

    @property
    def value(self):
        return self.document.value

    @property
    def path(self):
        return self.document.path


@dataclass(frozen=True, order=True)
class InputFile:
    path: str
    sha256: str
    role: str
    selection: str = ""
    identity: str = ""

    def record(self):
        result = {"path": self.path, "sha256": self.sha256, "role": self.role}
        if self.selection:
            result["selection"] = self.selection
        if self.identity:
            result["identity"] = self.identity
        return result


class ProjectInventory:
    def __init__(self, path, permitted_roots=(), limits=None):
        self.path = Path(path).resolve()
        self.permitted_roots = (self.path.parent, *map(lambda x: Path(x).resolve(), permitted_roots))
        self.limits = dict(DEFAULT_LIMITS)
        for key, value in (limits or {}).items():
            if key not in self.limits or type(value) is not int or value < 1:
                raise ValueError(f"Invalid resource limit {key!r}")
            self.limits[key] = value
        self.root = None
        self.projects = {}
        self.artifacts = {}
        self.registrations = {}
        self.required_groups = list(CORE_GROUPS)
        self.dependencies = defaultdict(set)
        self.dependency_locations = {}
        self._files = set()
        self.file_owners = defaultdict(set)
        self.source_paths = {}
        self.documents = {}
        self.schema_issues = {}
        self.invalid_aliases = set()
        self.selected_aliases = None
        self.report = ReportBuilder("urn:ddk:unknown-project", scope=self.scope)
        self.report.limits.update(self.limits)
        self._total_bytes = 0
        self._identities = {}
        self._project_paths = {}
        self.import_aliases = {}
        self._definition_resolver = DefinitionResolver(
            self.read, self.permitted_roots, self.limits["maxReferenceDepth"]
        )

    @property
    def scope(self):
        selected = self.registrations if self.selected_aliases is None else self.selected_aliases
        return {
            "projects": [f"{namespace}={doc.value['id']}" if namespace else doc.value["id"]
                         for namespace, doc in self.projects.items()] or [str(self.path)],
            "artifacts": sorted(selected),
            "followedReferences": sorted(f"{owner} -> {dep}" for owner, deps in self.dependencies.items()
                                         for dep in deps if self.selected_aliases is None or owner in selected
                                         or owner.startswith("project:")),
            "excludedConsumers": [],
        }

    def display_path(self, path):
        if path.is_relative_to(self.path.parent):
            return path.relative_to(self.path.parent).as_posix()
        for index, root in enumerate(self.permitted_roots[1:], start=1):
            if path.is_relative_to(root):
                return f"@root-{index}/{path.relative_to(root).as_posix()}"
        return str(path)

    def read(self, path):
        path = Path(path).resolve()
        if path not in self.documents:
            try:
                document = read_json(path, max_bytes=self.limits["maxDocumentBytes"],
                                     max_nesting=self.limits["maxNesting"])
                self._total_bytes += len(document.data)
                if self._total_bytes > self.limits["maxProjectBytes"]:
                    raise ResourceLimit(f"Authored project bytes exceed {self.limits['maxProjectBytes']}.")
                self.documents[path] = document
            except (DocumentError, OSError, ResourceLimit) as exc:
                self.documents[path] = exc
        document = self.documents[path]
        if isinstance(document, Exception):
            raise document
        return document

    def add_file(self, document, role, *, selection="", identity="", owner=""):
        entry = InputFile(self.display_path(document.path), document.sha256, role, selection, identity)
        self._files.add(entry)
        self.file_owners[entry].add(owner)

    @property
    def files(self):
        return frozenset(self._files)

    def dependency(self, owner, prerequisite, path=None, pointer=""):
        self.dependencies[owner].add(prerequisite)
        if path is not None:
            self.dependency_locations[(owner, prerequisite)] = location(self.display_path(path), pointer)

    def resolve(self, reference, namespace="", kind=None):
        alias = self.scoped(reference, namespace)
        artifact = self.artifacts.get(alias)
        if artifact is None:
            if alias in self.invalid_aliases:
                raise DocumentError("DOC-PREREQUISITE-INVALID", f"The artifact {alias!r} failed document checking.")
            raise DocumentError("REF-ARTIFACT-MISSING", f"Artifact {alias!r} is not registered in the loaded scope.")
        if kind is not None and artifact.kind != kind:
            raise DocumentError("REF-ARTIFACT-KIND", f"Artifact {alias!r} is {artifact.kind}, expected {kind}.")
        return artifact

    def _issue(self, requirement, group, subject, status, code, message, path, pointer=""):
        self.report.add(requirement, group, subject, status,
                        reason=message if status in {"unknown", "not_run"} else None,
                        diagnostics=[diagnostic(code, message, path=self.display_path(path), pointer=pointer)])

    def _validate(self, doc, kind):
        key = (doc.path, kind)
        if key not in self.schema_issues:
            self.schema_issues[key] = validate_document(doc.value, kind)
        return self.schema_issues[key]

    def _document(self, path, kind, subject):
        self.source_paths[subject] = path
        try:
            doc = self.read(path)
            issues = self._validate(doc, kind)
        except DocumentError as exc:
            self._issue("DDK-SYNTAX-001", "core.documents", subject, "failed", exc.code, str(exc), path, exc.pointer)
            return None
        except OSError:
            self.report.error(diagnostic("DOC-UNREADABLE", "The required input could not be read.", path=self.display_path(path)))
            self._issue("DDK-SYNTAX-001", "core.documents", subject, "not_run",
                        "DOC-UNREADABLE", "The required input could not be read.", path)
            return None
        if issues:
            self.report.add("DDK-SYNTAX-002", "core.documents", subject, "failed", diagnostics=[
                diagnostic(issue.code, issue.message, path=self.display_path(path), pointer=issue.pointer)
                for issue in issues
            ])
            return None
        self.report.add("DDK-SYNTAX-002", "core.documents", subject, "passed")
        return doc

    def _identity(self, doc, subject, identity, version, selection=""):
        key = (identity, version, selection)
        earlier = self._identities.setdefault(key, doc)
        if earlier.sha256 != doc.sha256:
            self.report.add("DDK-REF-002", "core.references", subject, "failed", diagnostics=[
                diagnostic("REF-IDENTITY-CONFLICT", f"Conflicting bytes for {identity} at version {version}.",
                           path=self.display_path(doc.path), related=[location(self.display_path(earlier.path))])
            ])
            return False
        return True

    def canonical(self, alias, *, whole=False):
        """Replace the longest aliased import-namespace prefix until none remains.

        An artifact alias's last segment names the artifact, so only its
        namespace prefixes are rewritten; ``whole`` also rewrites a complete
        namespace reference.
        """
        for _ in range(self.limits["maxReferenceDepth"] + 1):
            parts = alias.split("/")
            longest = len(parts) if whole else len(parts) - 1
            prefix = next((end for end in range(longest, 0, -1)
                           if "/".join(parts[:end]) in self.import_aliases), None)
            if prefix is None:
                return alias
            alias = "/".join(filter(None, (self.import_aliases["/".join(parts[:prefix])], *parts[prefix:])))
        raise ResourceLimit(f"Import namespace aliases exceed depth {self.limits['maxReferenceDepth']}.")

    def scoped(self, reference, namespace="", *, whole=False):
        return self.canonical(scoped_alias(reference, namespace), whole=whole)

    def visit(self, root):
        """Load each project file once, at its shortest import path from the root.

        Breadth-first order over sorted aliases makes the first occurrence the
        shortest path, with ties broken by namespace segments. Later occurrences
        of the same file become namespace aliases; cycles are found afterwards
        on the project-file graph so an alias cannot hide one.
        """
        queue = deque([(root, "", 0)])
        canonical = {}
        imports = defaultdict(list)
        while queue:
            path, namespace, depth = queue.popleft()
            subject = f"project:{namespace or '/'}"
            if depth > self.limits["maxReferenceDepth"]:
                raise ResourceLimit(f"Project import depth exceeds {self.limits['maxReferenceDepth']}.")
            if path in canonical:
                self.import_aliases[namespace] = canonical[path]
                continue
            # A file is attempted once; later paths alias it even when it failed, so the failure is reported once.
            canonical[path] = namespace
            doc = self._document(path, "project", subject)
            if doc is None:
                continue
            value = doc.value
            if not self._identity(doc, subject, value["id"], value["version"]):
                continue
            earlier = self._project_paths.setdefault((value["id"], value["version"]), path)
            if earlier != path:
                self._issue("DDK-REF-002", "core.references", subject, "failed", "REF-IMPORT-LOCATION-CONFLICT",
                            f"{value['id']} at version {value['version']} is also loaded from "
                            f"{self.display_path(earlier)}; its relative paths could resolve differently.", path)
                continue
            self.projects[namespace] = doc
            if not namespace:
                self.root = doc
                self.report.project = value["id"]
            self.required_groups.extend(group for group in value["requiredChecks"] if group not in self.required_groups)
            self.add_file(doc, "project", identity=value["id"], owner=subject)
            for alias, entry in sorted(value["artifacts"].items()):
                full_alias = scoped_alias(alias, namespace)
                if len(self.registrations) >= self.limits["maxArtifacts"]:
                    raise ResourceLimit(f"Artifact count exceeds {self.limits['maxArtifacts']}.")
                if full_alias in self.registrations:
                    self._issue("DDK-REF-002", "core.references", full_alias, "failed",
                                "REF-ALIAS-DUPLICATE", "The fully qualified artifact alias is already registered.", path)
                    continue
                self.registrations[full_alias] = (namespace, doc, entry)
            for alias, reference in sorted(value.get("imports", {}).items()):
                namespace_path = scoped_alias(alias, namespace)
                pointer = json_pointer(("imports", alias, "path"))
                try:
                    target = resolve_path(path, reference["path"], self.permitted_roots)
                except DocumentError as exc:
                    self._issue("DDK-REF-001", "core.references", f"project:{namespace_path}", "failed",
                                exc.code, str(exc), path, pointer)
                    continue
                self.dependency(subject, f"project:{namespace_path}", path, pointer)
                imports[path].append((target, namespace_path))
                queue.append((target, namespace_path, depth + 1))
        # Preserve the earlier depth-first project order: segment tuples sort parents before children.
        self.projects = dict(sorted(self.projects.items(), key=lambda item: item[0].split("/") if item[0] else []))
        self._report_cycles(root, imports)

    def _report_cycles(self, root, imports):
        """Report each back edge of a depth-first walk over loaded project files once."""
        chain, done = [root], set()
        stack = [iter(imports.get(root, ()))]
        while stack:
            step = next(stack[-1], None)
            if step is None:
                stack.pop()
                done.add(chain.pop())
                continue
            target, namespace = step
            if target in chain:
                cycle = " -> ".join(self.display_path(p) for p in (*chain[chain.index(target):], target))
                self._issue("DDK-REF-002", "core.references", f"project:{namespace}", "failed",
                            "REF-IMPORT-CYCLE", f"Import cycle: {cycle}.", chain[-1])
            elif target not in done:
                chain.append(target)
                stack.append(iter(imports.get(target, ())))

    def index(self, alias, namespace, project, entry):
        kind = entry["kind"]
        try:
            path = resolve_path(project.path, entry["path"], self.permitted_roots)
        except DocumentError as exc:
            self._issue("DDK-REF-001", "core.references", alias, "failed", exc.code, str(exc),
                        project.path, json_pointer(("artifacts", alias.rsplit("/", 1)[-1], "path")))
            self.invalid_aliases.add(alias)
            return
        doc = self._document(path, kind, alias)
        if doc is None:
            self.invalid_aliases.add(alias)
            return
        value = doc.value
        if kind == "definition":
            identity = f"urn:ddk:definition:{self.display_path(path).encode().hex()}"
            version = None
        else:
            identity = value.get("id", f"urn:ddk:artifact:{alias.encode().hex()}")
            version = value.get("version")
        selection = None
        selected = None
        pointer = ""
        try:
            if kind == "dataset":
                objects = value.get("schema", [])
                ids = [obj["id"] for obj in objects if "id" in obj]
                if len(ids) != len(set(ids)):
                    raise DocumentError("REF-DATASET-AMBIGUOUS", "Duplicate ODCS schema object IDs.", "/schema")
                index, selected = select_named(objects, entry["object"])
                selection = selected.get("id") or selected["name"]
                pointer = json_pointer(("schema", index))
                duplicates = duplicate_properties(selected.get("properties", []), ("schema", index, "properties"))
                if duplicates:
                    key, name, parts = duplicates[0]
                    raise DocumentError("REF-DATASET-FIELD-DUPLICATE", f"Duplicate ODCS property {key} {name!r}.", json_pointer(parts))
        except DocumentError as exc:
            self._issue("DDK-REF-003", "core.references", alias, "failed", exc.code, str(exc), path, exc.pointer)
            self.invalid_aliases.add(alias)
            return
        if not self._identity(doc, alias, identity, version, selection or ""):
            self.invalid_aliases.add(alias)
            return
        artifact = Artifact(alias, namespace, kind, doc, identity, version, entry,
                            selected, selected, selection, pointer)
        self.artifacts[alias] = artifact
        self.add_file(doc, "definition" if kind == "definition" else "artifact",
                      selection=selection or "", identity=identity, owner=alias)

    def resolve_definitions(self):
        by_file = defaultdict(list)
        for alias, artifact in self.artifacts.items():
            if artifact.kind == "definition":
                by_file[artifact.path].append(alias)
        for alias, artifact in list(self.artifacts.items()):
            if artifact.kind not in {"dataset", "definition"}:
                continue
            try:
                if artifact.kind == "dataset":
                    parts = ("schema", int(artifact.pointer.split("/")[-1]))
                    result = self._definition_resolver.resolve(artifact.selected, artifact.document, parts)
                else:
                    result = self._definition_resolver.resolve(artifact.value, artifact.document, ())
            except DocumentError as exc:
                status = "unknown" if isinstance(exc, RemoteDefinition) else "failed"
                self._issue("DDK-REF-004", "core.references", alias, status,
                            exc.code, str(exc), artifact.path, exc.pointer)
                self.artifacts[alias] = replace(artifact, effective=None, definition_status=status)
                continue
            except OSError:
                self.report.error(diagnostic("DOC-UNREADABLE", "The shared definition could not be read.", path=artifact.path))
                self.artifacts[alias] = replace(artifact, effective=None, definition_status="not_run")
                continue
            for source in result.references:
                reference = self.display_path(source.path) + (f"#{source.fragment}" if source.fragment else "")
                self.add_file(source, "definition", selection=source.fragment, owner=alias)
                self.dependency(alias, f"definition:{reference}")
                for registered in by_file[source.path]:
                    if registered != alias:
                        self.dependency(alias, registered)
            self.artifacts[alias] = replace(artifact, effective=freeze_json(result.value), provenance=freeze_json(result.provenance),
                                            definitions=tuple((source.path, source.fragment) for source in result.references),
                                            definition_sources=result.references)
            if result.references:
                self.report.add("DDK-REF-004", "core.references", alias, "passed")

    def freeze_inputs(self):
        self.projects = MappingProxyType(self.projects)
        self.artifacts = MappingProxyType(self.artifacts)
