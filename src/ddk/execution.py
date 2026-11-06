"""Application use cases for schema-only builds and explicitly selected fixtures."""

from copy import deepcopy
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import shutil
import tempfile

from .arrow_mapping import arrow_schema
from .core import check_inventory, load_project
from .documents import DocumentError, ResourceLimit, json_dumps, read_json, resolve_path, schema_validator, validate_document
from .fixtures import compare_rows
from .locks import evidence_sha256, tool_identities, write_json_atomic
from .quality import QualityEvaluator
from .results import diagnostic


_RESOURCE_CODES = {
    "capacity", "metadata_capacity", "scratch_capacity",
    "DOCSPEC-RECEIPT-LIMIT", "DOCSPEC-DIAGNOSTIC-LIMIT", "DOCSPEC-NATIVE-READ-LIMIT",
}
_RESTRICTED_PLAN_CODES = {"substrait_extensions", "substrait_profile"}
_RESTRICTED_QUERY_MARKERS = (
    "No table named ", "is not supported: function anchor", "unsupported Substrait relation",
    "Substrait reads require", "Substrait scan filters", "Substrait relation extensions",
    "reusable SQL requires immutable functions",
)



_NATIVE_CHECK_CODES = {
    "DOCSPEC-NATIVE-IDENTITY": ("failed", "EXEC-NATIVE-IDENTITY"),
    "no_release": ("not_run", "EXEC-NATIVE-UNAVAILABLE"),
    "release_mismatch": ("not_run", "EXEC-NATIVE-UNAVAILABLE"),
    "DOCSPEC-QUALITY-ACCESS-MISSING": ("not_run", "ADAPTER-QUALITY-ACCESS-MISSING"),
    "qualification_mismatch": ("failed", "EXEC-QUALIFICATION-MISMATCH"),
    "qualification_coverage": ("failed", "EXEC-QUALIFICATION-COVERAGE"),
    "qualification_unknown": ("unknown", "EXEC-QUALIFICATION-UNKNOWN"),
    "qualification_audit_only": ("failed", "EXEC-QUALIFICATION-AUDIT-ONLY"),
    "qualification_failed": ("failed", "EXEC-QUALIFICATION-FAILED"),
    "stale_eligibility": ("failed", "EXEC-SELECTION-STALE"),
    "stale_base": ("failed", "EXEC-SELECTION-STALE"),
    "stale_qualification_authority": ("failed", "EXEC-SELECTION-STALE"),
    "coverage_regression": ("failed", "EXEC-SELECTION-STALE"),
    "operation_conflict": ("failed", "EXEC-REQUEST-CONFLICT"),
    "unsupported_managed_build": ("not_run", "ADAPTER-OPERATION-UNSUPPORTED"),
    "unsupported_managed_update": ("not_run", "ADAPTER-OPERATION-UNSUPPORTED"),
    "DOCSPEC-BACKEND-UNSUPPORTED": ("not_run", "ADAPTER-OPERATION-UNSUPPORTED"),
}

def _record(builder, group, subject, result, *, requirement="DDK-ADAPTER-011", evidence="executed",
            saved_plan=False):
    outcome = result["status"]
    status = {"succeeded": "passed", "not_submitted": "not_run", "error": "unknown"}.get(outcome, outcome)
    reason = result.get("reason") or result.get("error", {}).get("message") or outcome
    reference = result.get("evidence") or result.get("receipt")
    refs = [] if reference is None else [{"kind": "native-report", "path": reference["path"], "sha256": reference["sha256"]}]
    native_code = result.get("error", {}).get("code")
    resource = native_code in _RESOURCE_CODES or (
        native_code == "query" and reason.startswith(("Resources exhausted", "Execution error: Resources exhausted"))
    )
    transport = result.get("transport", {})
    resource = resource or any(transport.get(field) for field in ("stdoutTruncated", "stderrTruncated", "drainIncomplete"))
    restricted = saved_plan and (native_code in _RESTRICTED_PLAN_CODES or (
        native_code == "query" and any(marker in reason for marker in _RESTRICTED_QUERY_MARKERS)
    ))
    if native_code == "DOCSPEC-FORMAT-UNAVAILABLE":
        status, code = "not_run", "ADAPTER-EXPORT-UNAVAILABLE"
    elif resource:
        status, code = "not_run", "EXEC-RESOURCE-LIMIT"
        builder.error(diagnostic(code, reason))
    elif restricted:
        status, code = "failed", "EXEC-PLAN-RESTRICTED"
    elif native_code == "DOCSPEC-CANCELLED":
        status, code = "not_run", "EXEC-CANCELLED"
        builder.error(diagnostic(code, reason))
    elif native_code in _NATIVE_CHECK_CODES:
        status, code = _NATIVE_CHECK_CODES[native_code]
        if code == "EXEC-NATIVE-UNAVAILABLE":
            builder.error(diagnostic(code, reason))
    elif native_code == "query" and reason.startswith("Error during planning: Invalid function"):
        status, code = "not_run", "ADAPTER-FUNCTION-IMPLEMENTATION-MISSING"
    elif status == "failed" and requirement == "DDK-ADAPTER-007":
        code = "EXEC-FIXTURE-MISMATCH"
    elif outcome == "failed" and result.get("operation", {}).get("mode") == "bounded_job" and result["operation"]["outputs"]:
        status, code = "not_run", "EXEC-JOB-FAILED"
        builder.error(diagnostic(code, reason))
    elif group == "data.odcs" and status in {"unknown", "not_run"} and any(
        check.get("id", "").startswith("ddk:unmapped-quality:")
        for check in result.get("checks", ()) if check.get("status") in {"unknown", "not_run"}
    ):
        status, code = "not_run", "ADAPTER-QUALITY-UNSUPPORTED"
        reason = "A required quality rule has no supported native execution"
    elif status == "unknown" and any(
        item.get("status") in {"unsupported", "unknown"} for item in result.get("mappingCoverage", ())
    ):
        code = "ADAPTER-MAPPING-INCOMPLETE"
    elif native_code in {"DOCSPEC-TIMEOUT", "DOCSPEC-NO-RECEIPT", "DOCSPEC-INVALID-RECEIPT",
                         "DOCSPEC-INPUT-CHANGED"}:
        status, code = "not_run", "EXEC-OUTCOME-UNKNOWN"
        builder.error(diagnostic(code, reason))
    elif outcome == "error":
        status, code = "unknown", "ADAPTER-ERROR"
        builder.error(diagnostic(code, reason))
    else:
        code = "ADAPTER-" + status.upper().replace("_", "-")
    builder.add(requirement, group, subject, status, evidence=evidence, reason=reason, evidence_records=refs,
                diagnostics=[] if status == "passed" else [diagnostic(code, reason)])


def _schema_result(expected, observed):
    wanted, coverage = arrow_schema(expected)
    if any(item["status"] != "exact" for item in coverage):
        return {"status": "unknown", "reason": "Output mapping includes an unsupported logical type",
                "mappingCoverage": coverage}
    actual_fields = observed["fields"]
    if [field["name"] for field in actual_fields] != [field["name"] for field in wanted["fields"]]:
        return {"status": "failed", "reason": "Inferred field names or order differ from the declared output"}
    for field, actual in zip(wanted["fields"], actual_fields, strict=True):
        if actual["data_type"] != field["data_type"]:
            return {"status": "failed", "reason": f"Inferred field {field['name']} has a different type"}
        if not field["nullable"] and actual["nullable"]:
            return {"status": "failed", "reason": f"Inferred field {field['name']} is nullable but the output requires a value"}
    return {"status": "passed", "reason": "Inferred names, order, types, and nullability satisfy the declared output"}


def _component(inventory, alias):
    component = inventory.resolve(alias, kind="component")
    value = component.value
    implementation = value.get("implementation", {})
    if implementation.get("format") != "sql":
        raise DocumentError("PLAN-UNSUPPORTED", "This producer profile requires an explicitly selected SQL component")
    if len(value["outputs"]) != 1:
        raise DocumentError("PLAN-UNSUPPORTED", "The initial calculation profile requires exactly one output")
    path = resolve_path(component.path, implementation["path"], inventory.permitted_roots)
    sql = path.read_text()
    schemas, mappings = [], []
    for name, port in value["inputs"].items():
        dataset = inventory.resolve(port["dataset"], component.namespace, kind="dataset")
        schema, coverage = arrow_schema(dataset.effective)
        if any(item["status"] != "exact" for item in coverage):
            raise DocumentError("PLAN-UNSUPPORTED", "Input type mapping is not established")
        schemas.append({"name": name, "schema": schema})
        mappings.append({"dataset": dataset.alias, "fields": [
            {"logicalName": prop["name"], "engineName": field["name"], "position": i,
             "logicalType": prop["logicalType"], "physicalType": field["data_type"], "nullable": field["nullable"]}
            for i, (prop, field) in enumerate(zip(dataset.effective["properties"], schema["fields"]))]})
    output_port, output = next(iter(value["outputs"].items()))
    output_dataset = inventory.resolve(output["dataset"], component.namespace, kind="dataset")
    return component, path, sql, schemas, mappings, output_port, output_dataset


def _check_artifact(builder, path, value, kind):
    issues = validate_document(value, kind)
    for index, issue in enumerate(issues):
        builder.add("DDK-ADAPTER-010", "core.documents", f"{path}:{index}", "failed",
                    diagnostics=[diagnostic(issue.code, issue.message, path=path, pointer=issue.pointer)])
    return not issues


def _export_settings(dataset):
    return {"profile": "whole", "row_group_rows": 8192,
            "order_by": [{"field": p["name"], "direction": "asc", "nulls": "nulls_last"} for p in dataset["properties"]],
            "columns": [p["name"] for p in dataset["properties"]], "dictionary_columns": [],
            "delta_columns": [], "key_column": None, "created_by": "ddk-reference-workflow",
            "footer_limit": 1 << 20}


def _stage_bindings(inventory, binding_path, fixture, component, tools, builder):
    binding = read_json(binding_path)
    if not _check_artifact(builder, binding.path, binding.value, "bindings"):
        return None, []
    design = inventory.resolve(binding.value["design"], kind="design")
    if list(schema_validator(design.value["parameters"]).iter_errors(binding.value["parameters"])):
        raise DocumentError("BINDING-PARAMETERS", "Binding parameters do not satisfy the design")
    origins, datasets = set(), {}
    for entry in binding.value["data"]:
        origin = entry["origin"]
        key = json_dumps(origin, sort_keys=True)
        if key in origins:
            raise DocumentError("EXEC-BINDING-DUPLICATE", "A binding origin occurs more than once")
        origins.add(key)
        if "source" in origin:
            expected = design.value["sources"].get(origin["source"], {}).get("dataset")
        else:
            step = design.value["steps"].get(origin["step"])
            if step is None:
                raise DocumentError("BINDING-ORIGIN", "The bound step does not exist")
            source_component = inventory.resolve(step["component"], design.namespace, kind="component")
            expected = source_component.value["outputs"].get(origin["output"], {}).get("dataset")
        if expected is None or inventory.resolve(expected, design.namespace).alias != inventory.resolve(entry["dataset"], design.namespace).alias:
            raise DocumentError("BINDING-DATASET", "The bound origin does not declare this dataset")
        alias = inventory.resolve(entry["dataset"], design.namespace).alias
        if alias in datasets:
            raise DocumentError("BINDING-AMBIGUOUS", "The fixture needs an unambiguous dataset binding")
        datasets[alias] = entry
    inputs, staged = [], []
    wanted_aliases = {inventory.resolve(item["dataset"], component.namespace).alias for item in fixture.value["inputs"].values()}
    if set(datasets) != wanted_aliases:
        raise DocumentError("BINDING-SCOPE", "Every supplied dataset binding must belong to this explicitly selected fixture")
    for name, expected in fixture.value["inputs"].items():
        artifact = inventory.resolve(expected["dataset"], component.namespace, kind="dataset")
        entry = datasets.get(artifact.alias)
        if entry is None or entry["kind"] != "files":
            builder.add("DDK-ADAPTER-010", "test.fixtures", name, "not_run", reason="This fixture binding requires exact local files")
            return None, staged
        files = []
        for member in entry["files"]:
            path = resolve_path(binding.path, member["path"], inventory.permitted_roots)
            files.append({"path": str(path), "sha256": member["sha256"]})
        if entry["format"] == "csv":
            intake = tools.invoke("files", {"dataset": artifact.effective, "files": files})
            _record(builder, "files.structure", name, intake, requirement="DDK-ADAPTER-004")
            if intake["status"] != "passed":
                return None, staged
            receipt = tools.invoke("stage", {"dataset": artifact.effective, "files": files, "table": name})
            _record(builder, "ingest.receipt", name, receipt, requirement="DDK-ADAPTER-004")
            staged.append({"dataset": artifact.alias, "receipt": receipt})
            if receipt["status"] != "passed":
                return None, staged
            files = receipt["files"]
        elif entry["format"] != "parquet":
            builder.add("DDK-ADAPTER-010", "test.fixtures", name, "not_run", reason="The selected fixture profile supports CSV staging or Parquet")
            return None, staged
        if len(files) != 1:
            builder.add("DDK-ADAPTER-010", "test.fixtures", name, "not_run", reason="This local profile requires one exact file per input table")
            return None, staged
        inputs.append({**files[0], "name": name})
    return inputs, staged


def run_fixture(project, fixture_path, *, runtime, tools, output=None, required_groups=(),
                permitted_roots=(), formats=("sql", "substrait"), input_files=None, lock=None, locked=False, bindings=None,
                secret_parameters=None):
    """Execute independently supplied expectations using actual saved plan bytes."""
    requested = tuple(dict.fromkeys(("plan.compile", "plan.output", "runtime.job", "test.fixtures", "data.odcs",
                                    *(('plan.consumer',) if "substrait" in formats else ()),
                                    *(("files.structure", "ingest.receipt") if bindings else ()), *required_groups)))
    inventory = load_project(project, permitted_roots=permitted_roots)
    check_inventory(inventory, required_groups=requested, handled_groups=("plan.compile", "plan.output", "runtime.job", "test.fixtures", "data.odcs", "plan.consumer", "files.structure", "ingest.receipt"),
                    lock=lock, locked=locked)
    builder = inventory.report
    if builder.build()["decision"] in ("failed", "error"):
        return builder.build()
    if secret_parameters and "substrait" in formats:
        reason = "Saved plans may include bound literals. Designated secret parameters require the SQL-only fixture profile."
        builder.add("DDK-SAFE-002", "plan.compile", "substrait", "not_run", reason=reason,
                    diagnostics=[diagnostic("ADAPTER-EXPORT-UNAVAILABLE", reason)])
        return builder.build()
    if runtime is None or tools is None:
        for group in requested:
            if group in ("plan.compile", "plan.output", "runtime.job", "test.fixtures", "data.odcs", "plan.consumer"):
                builder.add("DDK-CLI-004", group, "fixture", "not_run", reason="Explicit DocSpec and native tool environment are required")
        return builder.build()
    folder = Path(output or tempfile.mkdtemp(prefix="ddk-fixture-")).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    fixture = read_json(fixture_path)
    if not _check_artifact(builder, fixture.path, fixture.value, "fixture"):
        return builder.build()
    component, sql_path, sql, schemas, mappings, output_port, output_dataset = _component(inventory, fixture.value["component"])
    parameters = {**fixture.value["parameters"], **(secret_parameters or {})}
    if not schema_validator(component.value["parameters"]).is_valid(parameters):
        raise DocumentError("FIXTURE-PARAMETERS", "Effective fixture arguments do not satisfy the component parameters")
    if set(fixture.value["inputs"]) != set(component.value["inputs"]) or set(fixture.value["expected"]) != {output_port}:
        builder.add("DDK-ADAPTER-010", "test.fixtures", "ports", "failed",
                    diagnostics=[diagnostic("FIXTURE-PORTS", "Fixture inputs and expected outputs must match the selected component", path=fixture.path)])
        return builder.build()
    if any(inventory.resolve(item["dataset"], component.namespace).alias != inventory.resolve(component.value["inputs"][name]["dataset"], component.namespace).alias
           for name, item in fixture.value["inputs"].items()):
        builder.add("DDK-ADAPTER-010", "test.fixtures", "datasets", "failed",
                    diagnostics=[diagnostic("FIXTURE-DATASET", "Fixture dataset differs from the selected input port", path=fixture.path)])
        return builder.build()
    staged = []
    if bindings:
        input_files, staged = _stage_bindings(inventory, bindings, fixture, component, tools, builder)
        if input_files is None:
            builder.add("DDK-ADAPTER-010", "test.fixtures", "bindings", "not_run", reason="Input staging did not complete")
            return builder.build()
    if input_files is None:
        materialized = tools.invoke("fixture-files", {"inputs": {
            name: {"rows": item["rows"], "dataset": inventory.resolve(item["dataset"], component.namespace).effective}
            for name, item in fixture.value["inputs"].items()}})
        _record(builder, "test.fixtures", "input-mapping", materialized)
        if materialized["status"] != "passed":
            return builder.build()
        input_files = materialized["files"]
    if {item["name"] for item in input_files} != set(component.value["inputs"]):
        raise ValueError("Exact input file names differ from fixture ports")
    if any("schema" in item for item in input_files):
        schemas = [{"name": item["name"], "schema": item.get("schema", next(s["schema"] for s in schemas if s["name"] == item["name"]))}
                   for item in input_files]
    plan_path, readable = folder / "calculation.substrait", folder / "calculation.substrait.json"
    calculation = {"format": "sql", "sql": sql, "parameters": parameters}
    if "substrait" in formats:
        calculation["save_substrait"] = {"path": str(plan_path), "readable_path": str(readable)}
    prepared = runtime.prepare({"scratch": str(folder / "prepare-scratch"), "inputs": schemas, "calculation": calculation})
    _record(builder, "plan.compile", component.alias, prepared, evidence="inferred")
    if prepared["status"] != "succeeded":
        return builder.build()
    inferred = _schema_result(output_dataset.effective, prepared["result"]["schema"])
    inferred["evidence"] = prepared["evidence"]
    _record(builder, "plan.output", component.alias, inferred, evidence="inferred")
    if inferred["status"] != "passed":
        return builder.build()
    receipts, operations, comparisons, quality = {}, [], {}, {}
    for fmt in formats:
        if fmt not in ("sql", "substrait"):
            raise ValueError("Unsupported fixture implementation format")
        step = {"name": "ddk_result"}
        digests = {item["path"]: item["sha256"] for item in input_files}
        if fmt == "sql":
            step.update(sql=sql, parameters=parameters)
        else:
            plan = prepared["result"]["substrait"]
            consumed = runtime.prepare({"scratch": str(folder / "consumer-scratch"), "inputs": schemas,
                                        "calculation": {"format": "substrait", "path": plan["path"], "sha256": plan["sha256"]}})
            _record(builder, "plan.consumer", component.alias, consumed, evidence="inferred", saved_plan=True)
            if consumed["status"] != "succeeded":
                continue
            if consumed["result"]["schema"] != prepared["result"]["schema"]:
                builder.add("DDK-ADAPTER-005", "plan.consumer", "replay-schema", "failed",
                            diagnostics=[diagnostic("PLAN-SCHEMA-CHANGED", "Saved-plan inference differs from SQL inference")])
                continue
            step["substrait"] = {"path": plan["path"], "sha256": plan["sha256"]}
            digests[plan["path"]] = plan["sha256"]
        output_path = folder / (fmt + "-result.parquet")
        executed = runtime.execute({"scratch": str(folder / (fmt + "-scratch")),
                                    "inputs": [{"kind": "parquet", "name": item["name"], "path": item["path"]} for item in input_files],
                                    "steps": [step], "outputs": [{"name": output_port, "path": str(output_path), "sql": "SELECT * FROM ddk_result",
                                                                   "settings": _export_settings(output_dataset.effective)}],
                                    "queries": []}, input_digests=digests,
                                   semantic_profile=component.value["implementation"]["semantics"])
        _record(builder, "runtime.job", fmt, executed, saved_plan=fmt == "substrait")
        receipts[fmt] = executed
        if executed.get("operation"):
            operations.append(executed["operation"])
        if executed["status"] != "succeeded":
            continue
        file = executed["operation"]["outputs"][0]
        # The native adapter preserves output identity in its file-reference form.
        target = {"kind": "files", "files": [{"path": str(output_path), "sha256": file["sha256"]}]}
        evaluated = QualityEvaluator(tools).evaluate(output_dataset, target,
                      expected_rows=fixture.value["expected"][output_port], comparison=fixture.value["comparison"])
        _record(builder, "data.odcs", fmt, evaluated, requirement="DDK-ADAPTER-013")
        comparison = evaluated.get("fixtureComparison") or {"status": "not_run", "reason": "Exact output readback did not complete"}
        _record(builder, "test.fixtures", fmt, comparison, requirement="DDK-ADAPTER-007")
        comparisons[fmt] = comparison
        quality[fmt] = evaluated
    builder.metadata["fixture"] = {"source": {"path": str(fixture.path), "sha256": fixture.sha256},
                                   "implementation": {"path": str(sql_path), "sha256": sha256(sql.encode()).hexdigest()},
                                   "inputs": list(input_files), "preparation": prepared,
                                   "executions": receipts, "comparisons": comparisons, "quality": quality,
                                   "staging": staged, "readerExecution": "injected-data"}
    report = builder.build(operations=operations)
    write_json_atomic(folder / "report.ddk.json", report)
    return report



def _confirm_previous_bundle(path, bundle):
    if path.is_symlink() or not path.is_dir():
        raise ValueError("The previous output is not a generated bundle directory")
    manifest = path / "bundle.ddk.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("The previous output lacks an intact generated bundle manifest")
    previous = read_json(manifest).value
    if validate_document(previous, "bundle") or any(previous[key] != bundle[key] for key in ("id", "project")):
        raise ValueError("The previous output has a different bundle identity or an invalid manifest")
    expected = {item["path"]: item["sha256"] for item in previous["files"]}
    if len(expected) != len(previous["files"]) or any(
        Path(name).name != name or name == manifest.name for name in expected
    ):
        raise ValueError("The previous bundle manifest has an invalid file inventory")
    actual = {entry.name: entry for entry in path.iterdir()}
    if actual.keys() != {*expected, manifest.name}:
        raise ValueError("The previous output contains unmanaged or missing files")
    for name, digest in expected.items():
        entry = actual[name]
        if entry.is_symlink() or not entry.is_file():
            raise ValueError("The previous output contains unmanaged paths")
        if evidence_sha256(entry) != digest:
            raise ValueError("The previous output contains modified files")
    return tuple(actual)


def build_project(project, component_alias, *, runtime, output, formats=("sql", "substrait"),
                  required_groups=(), permitted_roots=(), lock=None, locked=False):
    """Prepare declared schemas only and atomically write an identified bundle."""
    required = tuple(dict.fromkeys(("plan.compile", "plan.output", *required_groups)))
    inventory = load_project(project, permitted_roots=permitted_roots)
    check_inventory(inventory, required_groups=required, handled_groups=("plan.compile", "plan.output", "plan.consumer"),
                    lock=lock, locked=locked)
    builder = inventory.report
    if builder.build()["decision"] != "passed":
        return builder.build()
    if runtime is None:
        for group in required:
            builder.add("DDK-CLI-004", group, "build", "not_run", reason="An explicit DocSpec executable is required")
        return builder.build()
    unknown = set(formats) - {"sql", "substrait"}
    if unknown:
        for name in sorted(unknown):
            reason = "Requested export format is unavailable"
            builder.add("DDK-CLI-004", "plan.compile", name, "not_run", reason=reason,
                        diagnostics=[diagnostic("ADAPTER-EXPORT-UNAVAILABLE", reason)])
        return builder.build()
    component, sql_path, sql, schemas, mappings, port, dataset = _component(inventory, component_alias)
    destination = Path(output).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".ddk-build-", dir=destination.parent))
    clean_staging = True
    try:
        calculation = {"format": "sql", "sql": sql, "parameters": {}}
        if "substrait" in formats:
            calculation["save_substrait"] = {"path": str(staging / "calculation.substrait"), "readable_path": str(staging / "calculation.substrait.json")}
        prepared = runtime.prepare({"scratch": str(runtime.evidence_dir / "build-scratch"), "inputs": schemas, "calculation": calculation})
        if prepared["status"] != "succeeded" and (staging / "calculation.substrait").is_file():
            reason = "Native preparation stopped after producing only part of the requested output set"
            record = diagnostic("EXEC-BUILD-INTERRUPTED", reason)
            builder.error(record)
            builder.add("DDK-ADAPTER-009", "plan.compile", component.alias, "not_run",
                        reason=reason, diagnostics=[record], evidence_records=[prepared["evidence"]])
            return builder.build()
        _record(builder, "plan.compile", component.alias, prepared, evidence="inferred")
        if prepared["status"] != "succeeded":
            return builder.build()
        inferred = {**_schema_result(dataset.effective, prepared["result"]["schema"]), "evidence": prepared["evidence"]}
        _record(builder, "plan.output", component.alias, inferred, evidence="inferred")
        if "plan.consumer" in builder.required_groups:
            if "substrait" not in formats:
                builder.add("DDK-CLI-004", "plan.consumer", component.alias, "not_run", reason="No saved plan was requested")
            else:
                saved = prepared["result"]["substrait"]
                consumed = runtime.prepare({"scratch": str(runtime.evidence_dir / "consumer-scratch"), "inputs": schemas,
                                            "calculation": {"format": "substrait", "path": saved["path"], "sha256": saved["sha256"]}})
                _record(builder, "plan.consumer", component.alias, consumed, evidence="inferred", saved_plan=True)
        report = builder.build()
        if report["decision"] != "passed":
            return report
        files, exports = [], {}
        if "sql" in formats:
            (staging / "calculation.sql").write_text(sql)
            exports["sql"] = {"dataset": dataset.alias, "implementation": {**deepcopy(component.value["implementation"]), "path": "calculation.sql"}}
        if "substrait" in formats:
            exports["substrait"] = {"dataset": dataset.alias, "implementation": {"format": "substrait", "path": "calculation.substrait",
                                                                                 "semantics": deepcopy(component.value["implementation"]["semantics"])}}
        (staging / "preparation.json").write_text(json_dumps(prepared))
        (staging / "report.ddk.json").write_text(json_dumps(report))
        for path in sorted(staging.iterdir()):
            role = "sql" if path.suffix == ".sql" else "plan" if path.suffix == ".substrait" else "plan-json" if path.name.endswith("substrait.json") else "report"
            files.append({"path": path.name, "sha256": sha256(path.read_bytes()).hexdigest(), "role": role})
        tool = {k: value for k, value in runtime.tool.items() if k != "id"}
        bundle = {"specVersion": "0.1", "kind": "bundle", "id": "urn:ddk:bundle:" + component.identity.encode().hex(), "version": "0.1.0",
                  "project": inventory.root.value["id"], "exports": exports,
                  "sourceInventory": [item.record() for item in inventory.files], "files": files,
                  "inputMappings": mappings, "capabilityManifests": [], "mappingCoverage": {"inputs": "explicit-flat-arrow"},
                  "obligations": [{"group": "plan.standard", "status": "unknown", "reason": "No independent compatible Substrait validator was selected"}] if "substrait" in formats else [],
                  "tools": {**tool_identities(), "docspec": tool}}
        issues = validate_document(bundle, "bundle")
        if issues:
            raise ValueError(f"Invalid generated bundle {issues[0].pointer}: {issues[0].message}")
        (staging / "bundle.ddk.json").write_text(json_dumps(bundle))
        from .catalog_output import _rename_exchange

        parent = os.open(destination.parent, os.O_RDONLY)
        try:
            fcntl.flock(parent, fcntl.LOCK_EX)
            if os.path.lexists(destination):
                try:
                    _confirm_previous_bundle(destination, bundle)
                except (DocumentError, OSError, ValueError, ResourceLimit) as exc:
                    builder.error(diagnostic("EXEC-BUNDLE-UNOWNED", str(exc), path=destination))
                    return builder.build()
                clean_staging = False
                try:
                    _rename_exchange(staging, destination)
                except OSError:
                    clean_staging = True
                    raise
                try:
                    displaced = _confirm_previous_bundle(staging, bundle)
                except (DocumentError, OSError, ValueError, ResourceLimit) as exc:
                    _rename_exchange(staging, destination)
                    clean_staging = True
                    builder.error(diagnostic("EXEC-BUNDLE-UNOWNED", str(exc), path=destination))
                    return builder.build()
                try:
                    for name in displaced:
                        (staging / name).unlink()
                    staging.rmdir()
                except OSError:
                    # Leave any new user-owned entries in the displaced directory.
                    builder.metadata["priorOutputRecovery"] = {"path": str(staging)}
            else:
                staging.rename(destination)
        finally:
            os.close(parent)
        builder.metadata["bundle"] = {"path": str(destination / "bundle.ddk.json"),
                                      "sha256": sha256((destination / "bundle.ddk.json").read_bytes()).hexdigest()}
        return builder.build()
    finally:
        if clean_staging and staging.exists():
            shutil.rmtree(staging)
