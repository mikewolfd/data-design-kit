"""Map pinned retained native jobs into the ordinary catalog facts.

The native job remains complete even when the catalog includes fewer datasets.
Every input and output outside that catalog scope has an explicit disposition.
"""

import base64
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from .catalog_access import CatalogError
from .docspec_job_evidence import (
    CANDIDATE_SCHEME, COUNTER_EVALUATOR, JobEvidenceError, interpret_output_schema,
    verify_completed_job, verify_completed_outputs,
)
from .documents import json_dumps

DEFINITION_SCHEME = "urn:ddk:managed-production:sha256"
INTERPRETER = {"id": "urn:ddk:metadata:arrow-odcs", "version": "1"}
INTERPRETATION_RULE = "urn:ddk:check:managed-output-interpretation:1"


def _definition_identity(production, datasets, schemas, sources, entry):
    aliases = set((*entry["inputs"].values(), *entry["outputs"].values()))
    binding = {
        "profile": "urn:ddk:managed-production-definition:1", "production": production,
        "datasets": {alias: {"id": datasets[alias]["id"], "definition": datasets[alias]["definition"],
                             "resolvedSha256": sha256(json_dumps(schemas[alias]).encode()).hexdigest()}
                     for alias in sorted(aliases)},
        "sources": sorted(sources, key=json_dumps),
        "inputs": entry["inputs"], "outputs": entry["outputs"], "outOfCatalog": {
            section: sorted(entry["outOfCatalog"][section], key=json_dumps) for section in ("inputs", "outputs")},
    }
    return f"{DEFINITION_SCHEME}:{sha256(json_dumps(binding).encode()).hexdigest()}"


def managed_job_definition(catalog_result, *, production, inputs, outputs, out_of_catalog):
    """Bind native prepare.definition to one admitted definition capture.

    Source custody and resolved definitions qualify interpretation. This opaque
    DDK identity is never a native computation or phase-reuse key. Native code
    retains it unchanged in the original prepare request.
    """
    catalog = catalog_result.local_catalog
    if (catalog_result.local_report.get("decision") != "passed" or not isinstance(catalog, dict)
            or catalog.get("audience") != "local"):
        raise CatalogError("CATALOG-DEFINITION-CAPTURE", "Managed definition capture requires an admitted complete local catalog.")
    productions = {row["alias"]: row for row in catalog["productions"]}
    if production not in productions:
        raise CatalogError("CATALOG-PRODUCTION-MISSING", "The captured production is outside the admitted catalog.")
    datasets = {row["alias"]: row for row in catalog["datasets"]}
    schemas = catalog["extensions"]["urn:ddk:catalog:assembly"]["datasetDefinitions"]
    entry = {"inputs": inputs, "outputs": outputs, "outOfCatalog": out_of_catalog}
    for section in ("inputs", "outputs"):
        _mapping(entry, section, None, productions[production][section])
    sources = [{"uri": row["uri"], "sha256": row["sha256"]} for row in catalog["sourceInventory"]
               if row["role"] in {"project", "definition"}]
    return _definition_identity(productions[production], datasets, schemas, sources, entry)


def _current_definition(metadata, production, entry):
    from .catalog_metadata import owner_record

    inventory = metadata.inventory
    documents = {document.path: document for document in inventory.projects.values()}
    schemas = {}
    for artifact in inventory.artifacts.values():
        documents[artifact.document.path] = artifact.document
        for source in artifact.definition_sources:
            documents[source.path] = inventory.documents[source.path]
        if artifact.kind == "dataset":
            schemas[artifact.alias] = artifact.effective
    aliases = set((*entry["inputs"].values(), *entry["outputs"].values()))
    if any(alias not in schemas or schemas[alias] is None for alias in aliases):
        raise CatalogError("CATALOG-DEFINITION-CAPTURE", "A managed dataset definition has unresolved source interpretation.", status="unknown")
    identity = _definition_identity(production, metadata.datasets, schemas,
                                    [owner_record(document) for document in documents.values()], entry)
    return identity, schemas


def managed_job_metadata(*, receipt, production, inputs, outputs, out_of_catalog):
    """Return explicit local metadata for the maintained catalog assembler.

    ``inputs`` and ``outputs`` map exact native names to registered DDK dataset
    aliases. ``out_of_catalog`` names all remaining input/output members as
    ``{name, reason}`` records. Validation occurs when the assembler admits the
    pinned receipt; this helper does not run or accept a native job.
    """
    return {"managedExecutions": [{
        "receipt": deepcopy(receipt), "production": production,
        "inputs": deepcopy(inputs), "outputs": deepcopy(outputs),
        "outOfCatalog": deepcopy(out_of_catalog),
    }]}


def _mapping(entry, section, names, permitted):
    from .catalog_metadata import _need

    mapping = _need(entry[section], set(), f"managed-job {section} mapping")
    if (not all(isinstance(name, str) and isinstance(alias, str) for name, alias in mapping.items())
            or not set(mapping.values()) <= set(permitted)):
        raise CatalogError("CATALOG-NATIVE-RECEIPT", "A managed-job mapping falls outside its production interface.")
    dispositions = entry["outOfCatalog"].get(section)
    if not isinstance(dispositions, list):
        raise CatalogError("CATALOG-METADATA-SHAPE", "Managed inputs and outputs need explicit out-of-catalog arrays.")
    excluded = []
    for item in dispositions:
        _need(item, {"name", "reason"}, "out-of-catalog member")
        if (set(item) != {"name", "reason"} or not isinstance(item["name"], str)
                or not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise CatalogError("CATALOG-METADATA-SHAPE", "An omitted native member needs an exact name and reason.")
        excluded.append(item["name"])
    if (len(excluded) != len(set(excluded)) or set(mapping) & set(excluded)
            or (names is not None and set(mapping) | set(excluded) != set(names))):
        raise CatalogError("CATALOG-NATIVE-MEMBERSHIP", "Every native input/output needs exactly one catalog mapping or explicit disposition.")
    return mapping


def managed_execution(metadata, entry):
    """Admit one managedExecutions entry using LocalMetadata's existing owners.

    Only metadata owner records are read. The complete native receipt keeps the
    authoritative underlying checks; catalog checks summarize accepted policy
    membership and explicitly make no assertion of per-output row coverage.
    """
    from .catalog_metadata import _need, _timestamp, owner_record, stable_id

    _need(entry, {"receipt", "production", "inputs", "outputs", "outOfCatalog"}, "managed execution mapping")
    if set(entry) != {"receipt", "production", "inputs", "outputs", "outOfCatalog"}:
        raise CatalogError("CATALOG-METADATA-SHAPE", "Unknown managed execution mapping member.")
    _need(entry["outOfCatalog"], {"inputs", "outputs"}, "out-of-catalog native membership")
    if set(entry["outOfCatalog"]) != {"inputs", "outputs"}:
        raise CatalogError("CATALOG-METADATA-SHAPE", "Only input/output dispositions define catalog dataset scope.")
    document = metadata.read_pinned_owner(metadata.document, entry["receipt"], "DDK managed-job receipt")
    receipt = _need(document.value, {"tool", "result", "endedAt", "operationContext"}, "DDK managed-job receipt")
    context = _need(receipt["operationContext"], {"runtime", "workspace", "dataset", "operationId"}, "managed-job context")
    result = _need(receipt["result"], {"dataset", "operation", "request_digest", "status"}, "native managed-job observation")
    if (context["runtime"] != "docspec" or context.get("kind") != "whole_job" or context["dataset"] != result["dataset"]
            or context["operationId"] != result["operation"] or not isinstance(context["workspace"], str)
            or not Path(context["workspace"]).is_absolute()):
        raise CatalogError("CATALOG-NATIVE-RECEIPT", "The retained native job belongs to another operation context.")
    alias = entry["production"]
    if not isinstance(alias, str):
        raise CatalogError("CATALOG-METADATA-SHAPE", "A managed execution needs a production alias.")
    production = metadata.productions.get(alias)
    if production is None:
        raise CatalogError("CATALOG-PRODUCTION-MISSING", f"Production {alias!r} is outside the loaded scope.")
    observed_at = _timestamp(receipt["endedAt"], "native managed-job observation")
    record = owner_record(document)
    metadata._record_tool(receipt["tool"], "DocSpec tool")
    if (receipt.get("status") == "error" and receipt.get("error", {}).get("code") == "DOCSPEC-DIAGNOSTIC-LIMIT"
            and (receipt.get("stderrTruncated") is True or receipt.get("drainIncomplete") is True)):
        metadata.operational_errors.append(("DOCSPEC-DIAGNOSTIC-LIMIT", "DocSpec diagnostic capture did not complete.", document.path))
    if result["status"] != "completed":
        _unresolved(metadata, result, alias, context, observed_at, record, entry, production)
        return
    try:
        evidence = verify_completed_job(result)
    except JobEvidenceError as exc:
        raise CatalogError(exc.code, str(exc), status=exc.status) from exc
    input_mapping = _mapping(entry, "inputs", evidence.view_names["inputs"], production["inputs"])
    output_mapping = _mapping(entry, "outputs", evidence.view_names["outputs"], production["outputs"])
    definition_identity, schemas = _current_definition(metadata, production, entry)
    definition_matches = evidence.admitted_request["definition"] == definition_identity
    outputs = []
    interpretations = []
    for output in evidence.manifest["outputs"]:
        if output["name"] in output_mapping:
            dataset = output_mapping[output["name"]]
            version = metadata._file_version(dataset, {**output, "attributes": {"rows": output["rows"]}}, record, output=True)
            outputs.append(version)
            interpreted = interpret_output_schema(base64.b64decode(evidence.manifest["schemas"][output["schema_sha256"]]), schemas[dataset])
            identity = {"subject": version, "rule": {"id": INTERPRETATION_RULE, "version": definition_identity},
                        "evaluator": INTERPRETER,
                        "scope": "Retained output Arrow schema interpreted against the exact authored ODCS field definitions; no row-value checks."}
            metadata.observations["checks"].append({**identity, "status": interpreted.status, "record": record,
                                                   **({"reason": " ".join(interpreted.reasons)} if interpreted.reasons else {})})
            metadata.qualification.append(identity)
            binding = {"subject": version, "rule": {"id": "urn:ddk:check:managed-definition-capture:1", "version": definition_identity},
                       "evaluator": {"id": "urn:ddk:metadata:managed-definition", "version": "1"},
                       "scope": "Original native prepare definition binds the exact captured production and resolved authored dataset sources."}
            metadata.observations["checks"].append({**binding, "status": "passed" if definition_matches else "unknown", "record": record,
                                                   **({"reason": "Current production or dataset definitions differ from the original captured definition identity."}
                                                      if not definition_matches else {})})
            metadata.qualification.append(binding)
            interpretations.append({"output": output["name"], "dataset": dataset, "schemaSha256": output["schema_sha256"],
                                    "profile": INTERPRETER, "status": interpreted.status, "fields": list(interpreted.fields)})
    inputs, registered_inputs = _input_versions(metadata, evidence, input_mapping, record)
    run_id = stable_id("docspec-managed-job-run", context["workspace"], evidence.candidate)
    run = {
        "id": run_id,
        "reference": {"scheme": CANDIDATE_SCHEME, "authority": Path(context["workspace"]).as_uri(), "value": deepcopy(evidence.candidate)},
        "outcome": "succeeded", "observedAt": observed_at, "endedAt": observed_at, "record": record,
        "inputs": sorted(set(inputs)), "outputs": sorted(set(outputs)),
        "inputCoverage": {"status": "unknown", "scope": "Consumed rows within the complete admitted native job; membership does not establish read coverage."},
    }
    if definition_matches:
        run["production"] = alias
    metadata.observations["runs"].append(run)
    metadata.bound_inputs[run_id] = registered_inputs
    if hasattr(metadata, "managed_jobs"):
        metadata.managed_jobs.append({
            "run": run_id, "record": record, "candidate": deepcopy(evidence.candidate),
            "viewSetDigest": evidence.manifest["view_set_digest"], "policyId": result["policy_id"],
            "acceptedQualification": evidence.accepted["identity"] if evidence.accepted is not None else None,
            "capturedDefinition": evidence.admitted_request["definition"], "currentDefinition": definition_identity,
            "definitionStatus": "passed" if definition_matches else "unknown", "outputInterpretations": interpretations,
            "outOfCatalog": deepcopy(entry["outOfCatalog"]),
        })
    scope = ("Native whole-candidate accepted policy; exact output membership only. "
             "Individual report outcomes and complete private/public view membership remain in the pinned native receipt; "
             "this summary does not assert that every report inspected every output row.")
    rule = {"id": stable_id("docspec-native-policy", result["dataset"], result["policy_id"]),
            "version": result["policy"]["sha256"]}
    for version in sorted(set(outputs)):
        identity = {"subject": version, "rule": rule, "evaluator": deepcopy(COUNTER_EVALUATOR), "scope": scope}
        summary = {**identity, "record": record, "status": "passed" if evidence.accepted is not None else "unknown"}
        if evidence.accepted is None:
            summary["reason"] = "The native execution completed but has no accepted whole-candidate qualification."
        metadata.observations["checks"].append(summary)
        metadata.qualification.append(identity)
    if not outputs:
        metadata.quality_issues.append(CatalogError("CATALOG-EVIDENCE-SCOPE", "The managed-job mapping includes no catalog output version.",
                                                   status="unknown"))
    metadata.limits.add("Native job membership and accepted policy are preserved; data payloads and runtime retention were not rechecked during catalog refresh.")
    metadata.limits.add("Native selection is separate from publisher selection; the managed-job mapper records no publication.")


def _input_versions(metadata, evidence, mapping, record):
    from .catalog_metadata import stable_id

    versions, bindings = [], {}
    for view in evidence.view_set["inputs"]:
        name = view["name"]
        if name not in mapping:
            continue
        files = view["files"]
        if view["kind"] == "version":
            selector = view["selector"]
            reference = {"scheme": "urn:docspec:version-ref", "authority": Path(selector["workspace"]).as_uri(), "value": deepcopy(selector["version"])}
            dataset = metadata.datasets[mapping[name]]
            version = stable_id("docspec-native-version", dataset["id"], dataset["definition"], reference)
            fact = {"id": version, "dataset": mapping[name], "reference": reference, "retention": "unknown",
                    "scope": "Exact original native input selector; current availability was not rechecked.", "record": record, "sources": []}
            old = metadata.version_facts.setdefault(version, fact)
            if old["dataset"] != fact["dataset"] or old["reference"] != reference:
                raise CatalogError("CATALOG-AUTHORITY-CONFLICT", "A native input has conflicting catalog version facts.")
            owners = metadata.owners.setdefault(version, [])
            if record not in owners:
                owners.append(record)
            versions.append(version)
            bindings[name] = version
            continue
        if view["kind"] not in {"parquet", "json_lines"}:
            metadata.limits.add("A native table selector is retained in complete job evidence; no unsupported catalog version scheme was invented.")
            continue
        member_versions = []
        for item in files:
            retained = {"path": item["retained"]["path"], "sha256": item["sha256"]}
            version = metadata._file_version(mapping[name], retained, record)
            if view["kind"] == "json_lines":
                for representation in metadata.observations["representations"]:
                    if representation["version"] == version:
                        representation["mediaType"] = "application/x-ndjson"
            member_versions.append(version)
            versions.append(version)
        if len(member_versions) == 1:
            bindings[name] = member_versions[0]
        elif member_versions:
            metadata.limits.add("A multi-file native input contributes exact member versions; no single-file recipe binding was inferred.")
    return versions, bindings


def _unresolved(metadata, result, production, context, observed_at, record, entry, definition):
    from .catalog_metadata import stable_id

    status = result["status"]
    if not isinstance(status, str) or status not in {"pending", "unknown", "failed"}:
        raise CatalogError("CATALOG-NATIVE-RECEIPT", "Unsupported native job execution outcome.")
    # Without a sealed candidate, completeness is unresolved. Known sealed
    # outputs still retain their exact identities and never become empty facts.
    _mapping(entry, "inputs", None, definition["inputs"])
    output_mapping = _mapping(entry, "outputs", None, definition["outputs"])
    known_names = set(output_mapping) | {item["name"] for item in entry["outOfCatalog"]["outputs"]}
    try:
        completed = verify_completed_outputs(result.get("completed_outputs", []))
    except JobEvidenceError as exc:
        raise CatalogError(exc.code, str(exc), status=exc.status) from exc
    if not {row["name"] for row in completed} <= known_names:
        raise CatalogError("CATALOG-NATIVE-MEMBERSHIP", "A known native output has no mapping or explicit disposition.")
    outputs = [metadata._file_version(output_mapping[row["name"]], {**row, "attributes": {"rows": row["rows"]}},
                                      record, output=True) for row in completed if row["name"] in output_mapping]
    run = {
        "id": stable_id("docspec-managed-job-run", context["workspace"], result["dataset"], result["operation"]),
        "production": production,
        "reference": {"scheme": "urn:ddk:docspec-managed-job-operation", "authority": Path(context["workspace"]).as_uri(),
                      "value": {"dataset": result["dataset"], "operation": result["operation"],
                                "request_digest": result["request_digest"]}},
        "outcome": "failed" if status == "failed" else "unknown", "observedAt": observed_at, "record": record,
        "inputs": [], "outputs": sorted(set(outputs)),
        "inputCoverage": {"status": "unknown", "scope": "Native job has no sealed complete candidate."},
    }
    if status == "failed":
        run["endedAt"] = observed_at
    metadata.observations["runs"].append(run)
    metadata.quality_issues.append(CatalogError("CATALOG-EVIDENCE-MISSING", "The native job has no complete accepted candidate.",
                                               status="not_run" if status == "pending" else "unknown"))
