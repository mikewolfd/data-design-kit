"""Explicit application bindings from authored facets to accepted native counters.

Profiles are supplied by composition, never discovered from metadata. Their
source pins identify code; independent qualification remains a release duty.
"""

import base64
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Protocol

from .catalog_access import CatalogError
from .catalog_semantics import admit_profile
from .docspec_job_evidence import JobEvidenceError, _decode, _digest, _json, _named, _object
from .documents import DEFAULT_LIMITS, freeze_json, json_dumps, read_json


@dataclass(frozen=True)
class NativeRuleBinding:
    dataset: str
    output: str
    facet: Literal["required", "key_unique", "key_not_null"]
    paths: tuple[tuple[Mapping, ...], ...]
    report: str
    column: str


@dataclass(frozen=True)
class NativeRuleContext:
    production: Mapping
    datasets: Mapping
    identities: tuple[Mapping, ...]
    inputs: Mapping
    outputs: Mapping
    out_of_catalog: Mapping
    schema_profiles: Mapping = field(default_factory=lambda: freeze_json({}))


class NativeRuleProfile(Protocol):
    identity: Mapping
    source: str | Path | None

    def bindings(self, context: NativeRuleContext, original_job: Mapping) -> Sequence[NativeRuleBinding]: ...


@dataclass(frozen=True)
class SelectedNativeRuleProfile:
    identity: Mapping
    source: object
    callback: object

    def record(self):
        from .catalog_metadata import owner_record

        return {"identity": deepcopy(self.identity), **({"source": owner_record(self.source)} if self.source else {})}

    def bindings(self, context, job):
        try:
            result = self.callback(context, freeze_json(deepcopy(job)))
        except Exception as exc:
            raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "The explicit generator could not verify original writer/check coverage.",
                               status="unknown") from exc
        if not isinstance(result, (tuple, list)):
            raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "The explicit generator must return typed facet bindings.", status="unknown")
        records = [_binding_record(binding, context) for binding in result]
        if len({json_dumps(row) for row in records}) != len(records):
            raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "The explicit generator repeated a facet binding.", status="unknown")
        allowed = _authored_facets(context)
        if any(json_dumps((row["dataset"], row["output"], row["facet"], row["paths"])) not in allowed for row in records):
            raise CatalogError("CATALOG-NATIVE-RULE-SCOPE", "The explicit generator supplied a binding outside the complete authored facet inventory.",
                               status="unknown")
        return records


def select_native_rule_profile(profile, inventory=None):
    """Apply the existing explicit-profile provenance admission, without imports."""
    if profile is None or isinstance(profile, SelectedNativeRuleProfile):
        return profile
    try:
        wrapper = SimpleNamespace(identity=profile.identity, source=profile.source, assess=profile.bindings)
    except AttributeError as exc:
        raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "An explicit native rule generator needs identity, source and bindings.",
                           status="unknown") from exc
    if inventory is None:
        source = Path(wrapper.source) if wrapper.source is not None else None
        if source is not None and not source.is_absolute():
            raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "Definition capture needs an explicit absolute generator source path.",
                               status="unknown")
        inventory = SimpleNamespace(path=source or Path("/explicit-native-rule-profile"),
                                    permitted_roots=(source.parent if source else Path("/"),), limits=dict(DEFAULT_LIMITS))
    selected = admit_profile(wrapper, inventory)
    return SelectedNativeRuleProfile(selected.identity, selected.source, selected.callback)


def rule_context(production, datasets, identities, entry, schema_profiles=None):
    return NativeRuleContext(freeze_json(deepcopy(production)), freeze_json(deepcopy(datasets)),
                             tuple(freeze_json(deepcopy(row)) for row in identities),
                             freeze_json(deepcopy(entry["inputs"])), freeze_json(deepcopy(entry["outputs"])),
                             freeze_json(deepcopy(entry["outOfCatalog"])),
                             freeze_json({alias: schema_profiles[alias] for alias in sorted(set(entry["outputs"].values()))
                                          if alias in (schema_profiles or {})}))


def _authored_facets(context):
    from .catalog_managed_jobs import _key_obligations

    allowed = set()
    for output, dataset in context.outputs.items():
        schema = context.datasets[dataset]

        def add(facet, paths):
            allowed.add(json_dumps((dataset, output, facet, paths)))

        def visit(node, path):
            if path and node.get("required") is True:
                add("required", [path])
            if path and node.get("unique") is True:
                add("key_unique", [path])
            for child in node.get("properties", []):
                visit(child, [*path, {"field": child["name"]}])
            if isinstance(node.get("items"), dict):
                visit(node["items"], [*path, {"each": True}])

        visit(schema, [])
        for obligation in _key_obligations(schema, context.identities, dataset, ()):
            if obligation["facet"] in {"key_unique", "key_not_null"}:
                add(obligation["facet"], obligation["paths"])
    return allowed


def _binding_record(binding, context):
    if not isinstance(binding, NativeRuleBinding):
        raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "Only typed native facet bindings are supported.", status="unknown")
    if (binding.facet not in {"required", "key_unique", "key_not_null"}
            or not all(isinstance(value, str) and value for value in (binding.dataset, binding.output, binding.report, binding.column))
            or context.outputs.get(binding.output) != binding.dataset
            or not isinstance(binding.paths, (tuple, list)) or not binding.paths
            or (binding.facet == "required" and len(binding.paths) != 1)):
        raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "A native binding has invalid facet, path or output scope.", status="unknown")
    paths = []
    for path in binding.paths:
        if not isinstance(path, (tuple, list)) or not path:
            raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "A native binding needs complete DDK field paths.", status="unknown")
        for segment in path:
            if not (isinstance(segment, Mapping) and (
                (set(segment) == {"field"} and isinstance(segment["field"], str) and segment["field"])
                or (set(segment) == {"each"} and segment["each"] is True)
            )):
                raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "A native binding has an unsupported field path.", status="unknown")
        paths.append([deepcopy(dict(segment)) for segment in path])
    if len({json_dumps(path) for path in paths}) != len(paths):
        raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "A native key binding repeats a field path.", status="unknown")
    return {"dataset": binding.dataset, "output": binding.output, "facet": binding.facet, "paths": paths,
            "report": binding.report, "column": binding.column}


def _original_job(witness, *, expected_sha256=None, expected_size=None):
    try:
        _object(witness, ("sha256", "bytes_base64"), "native rule original job")
        raw = _decode(witness["bytes_base64"], "native rule original job")
        if (not _digest(witness["sha256"]) or sha256(raw).hexdigest() != witness["sha256"]
                or (expected_sha256 is not None and witness["sha256"] != expected_sha256)
                or (expected_size is not None and len(raw) != expected_size)):
            raise CatalogError("CATALOG-NATIVE-RULE-JOB", "Native rule bindings refer to different original JobSpec bytes.", status="unknown")
        job = _json(raw, "native rule original job")
        _object(job, ("inputs", "steps", "outputs"), "native rule original JobSpec")
        for section in ("inputs", "steps", "outputs"):
            _named(job[section], f"original job {section}")
        _named(job.get("queries", []), "original job reports")
        return job
    except JobEvidenceError as exc:
        raise CatalogError(exc.code, str(exc), status=exc.status) from exc


def native_rule_artifact(catalog_result, original_job_bytes, *, native_rule_profile,
                         production, inputs, outputs, out_of_catalog):
    """Generate metadata bindings with the explicit deterministic application owner."""
    from .catalog_managed_jobs import managed_job_definition

    if not isinstance(original_job_bytes, bytes):
        raise CatalogError("CATALOG-NATIVE-RULE-JOB", "Native rule capture requires exact original JobSpec bytes.")
    if len(original_job_bytes) > DEFAULT_LIMITS["maxDocumentBytes"]:
        raise CatalogError("CATALOG-NATIVE-RULE-JOB", "Original JobSpec metadata exceeds the bounded document allocation.", status="unknown")
    mapping = dict(production=production, inputs=inputs, outputs=outputs, out_of_catalog=out_of_catalog)
    definition = managed_job_definition(catalog_result, **mapping)
    catalog = catalog_result.local_catalog
    declarations = catalog["extensions"]["urn:ddk:catalog:assembly"]["datasetDefinitions"]
    context = rule_context(next(row for row in catalog["productions"] if row["alias"] == production),
                           declarations, catalog["identities"], {"inputs": inputs, "outputs": outputs, "outOfCatalog": out_of_catalog},
                           catalog["extensions"]["urn:ddk:catalog:assembly"].get("managedSchemaProfiles"))
    selected = select_native_rule_profile(native_rule_profile)
    if selected is None:
        raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "Native rule capture requires an explicitly selected generator.", status="unknown")
    job = {"sha256": sha256(original_job_bytes).hexdigest(), "bytes_base64": base64.b64encode(original_job_bytes).decode()}
    bindings = selected.bindings(context, _original_job(job))
    return {"profile": selected.record(), "definition": definition, "job": job, "bindings": bindings}


def verify_native_rule_artifact(value, *, definition, context, profile, expected_sha256=None, expected_size=None):
    """Reproduce saved bindings from exact definitions and original SQL metadata."""
    if profile is None:
        raise CatalogError("CATALOG-NATIVE-RULE-PROFILE", "Native facet bindings require an explicitly selected generator.", status="unknown")
    if (not isinstance(value, dict) or set(value) != {"profile", "definition", "job", "bindings"}
            or value["profile"] != profile.record() or value["definition"] != definition):
        raise CatalogError("CATALOG-NATIVE-RULE-SCOPE", "Native facet bindings have different captured definitions or generator source.", status="unknown")
    job = _original_job(value["job"], expected_sha256=expected_sha256, expected_size=expected_size)
    records = profile.bindings(context, job)
    if records != value["bindings"]:
        raise CatalogError("CATALOG-NATIVE-RULE-SCOPE", "Saved facet bindings do not match the explicit generator's original writer/check mapping.",
                           status="unknown")
    return job, records


def read_native_rule_pin(reference):
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"} or not _digest(reference["sha256"]):
        raise CatalogError("CATALOG-NATIVE-RULE-SCOPE", "Native rules need a pinned metadata artifact.")
    document = read_json(reference["path"])
    if document.sha256 != reference["sha256"]:
        raise CatalogError("CATALOG-OWNER-DIGEST", "Native rule metadata differs from its captured SHA-256.")
    return document
