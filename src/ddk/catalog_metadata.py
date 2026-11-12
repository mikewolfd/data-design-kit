"""Map admitted owner records to exact catalog observations without opening data files."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re

from .catalog_access import CatalogError
from .documents import FORMAT_CHECKER, json_dumps, resolve_path
from .quality import dataset_rules

SECTIONS = ("versions", "sources", "representations", "releases", "selections", "runs", "checks")
AUXILIARY = ("productionObservations", "lineage", "qualification", "publications", "executions", "managedExecutions", "quality", "staging")
FILE_SCHEME = "urn:ddk:version:local-file-sha256"
EXACT_FIELD_CHECK = "ddk:exact-field-names"
QUALITY_COMPLETE_CHECK = "ddk:quality-execution-complete"
DLT_SYSTEM_TABLES = {"_dlt_version", "_dlt_loads", "_dlt_pipeline_state"}
DCC_STATUS = {"passed": "passed", "failed": "failed", "warning": "unknown",
              "info": "unknown", "unknown": "unknown", "skipped": "not_run", "error": "unknown"}
LOCAL_ADAPTER = {"id": "ddk.metadata.local", "version": "0.2.0"}
EXAMPLE_ADAPTER = {"id": "ddk.metadata.example", "version": "0.1.0"}


def stable_id(kind, *parts):
    return f"urn:ddk:{kind}:{sha256(json_dumps(parts).encode()).hexdigest()}"


def check_report(check):
    """The retained native report behind a passed or failed check, or None. Executed evidence needs one."""
    record = check.get("record", {})
    if check["status"] in {"passed", "failed"} and record.get("sha256"):
        return {"kind": "native-report", "path": record["uri"], "sha256": record["sha256"],
                "tool": check["evaluator"]["id"]}
    return None


def owner_record(document):
    return {"uri": document.path.as_uri(), "sha256": document.sha256}


def _quality_reason(check, declared):
    """Explain the native outcome without guessing among repeated rule IDs."""
    label = check.get("name")
    if check.get("qualityId"):
        pending = list(declared.get("schema", []))
        descriptions = set()
        while pending:
            node = pending.pop()
            descriptions.update(rule["description"] for rule in node.get("quality", [])
                                if rule.get("id") == check["qualityId"] and rule.get("description"))
            pending.extend(node.get("properties", []))
        if len(descriptions) == 1:
            label = descriptions.pop()
    reason = check.get("reason") or check["result"]
    return f"{label} — {reason}" if label else reason


def _need(value, keys, context):
    if not isinstance(value, dict) or not keys <= value.keys():
        raise CatalogError("CATALOG-METADATA-SHAPE", f"The {context} record lacks required fields.")
    return value


def _digest(value):
    return isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value) is not None


def _artifact_uri(item):
    path, digest = item.get("path"), item.get("sha256")
    if not isinstance(path, str) or not Path(path).is_absolute() or not _digest(digest):
        raise CatalogError("CATALOG-NATIVE-REFERENCE", "The receipt needs an absolute artifact path and SHA-256.")
    return Path(path).as_uri(), digest


def _timestamp(value, context):
    if not isinstance(value, str) or not FORMAT_CHECKER.conforms(value, "date-time"):
        raise CatalogError("CATALOG-METADATA-SHAPE", f"The {context} needs an explicit date-time.")
    return value


def _tool(value, context):
    value = _need(value, {"version"}, context)
    identifier = value.get("id", value.get("name"))
    if not isinstance(identifier, str) or not identifier:
        raise CatalogError("CATALOG-METADATA-SHAPE", f"The {context} has no tool identity.")
    return {"id": identifier, **{key: value[key] for key in ("version", "commit", "distributionSha256")
                                  if key in value}}


def _staging_metrics(report, table, loads):
    _need(report, {"loads_ids", "load_packages", "job_metrics"}, "dlt native job inventory")
    if set(report["loads_ids"]) != loads or {item["load_id"] for item in report["load_packages"]} != loads:
        raise CatalogError("CATALOG-STAGING-LOAD", "The dlt report covers a different load.")
    permitted_tables = {table} | DLT_SYSTEM_TABLES
    package_jobs = []
    for package in report["load_packages"]:
        for job in package["jobs"]:
            _need(job, {"table_name", "job_id"}, "dlt package job")
            package_jobs.append((package["load_id"], job["table_name"], job["job_id"]))
    measured_jobs = []
    for metric in report["job_metrics"]:
        _need(metric, {"load_id", "table_name", "job_id"}, "dlt job metric")
        measured_jobs.append((metric["load_id"], metric["table_name"], metric["job_id"]))
    expected, measured = set(package_jobs), set(measured_jobs)
    if (not expected or expected != measured or len(expected) != len(package_jobs)
            or len(measured) != len(measured_jobs)):
        raise CatalogError("CATALOG-STAGING-LOAD", "dlt job metrics do not cover the native package jobs.")
    if any(name not in permitted_tables for _, name, _ in measured):
        raise CatalogError("CATALOG-STAGING-LOAD", "dlt reported a data job for a table outside the requested scope.")
    return [metric for metric in report["job_metrics"] if metric["table_name"] == table]


class LocalMetadata:
    def __init__(self, document, inventory, adapter, datasets, productions, *, native_rule_profile=None, identities=(),
                 schema_profiles=None, job_specs=None):
        self.document = document
        self.inventory = inventory
        self.adapter = adapter
        self.datasets = datasets
        self.productions = productions
        self.native_rule_profile = native_rule_profile
        self.schema_profiles = deepcopy(schema_profiles or {})
        self.identities = tuple(identities)
        self.job_specs = dict(job_specs or {})
        self.observations = {section: [] for section in SECTIONS}
        self.records = {document.path: document}
        self.lineage = {}
        self.qualification = []
        self.production_times = {}
        self.physical_datasets = {}
        self.version_facts = {}
        self.limits = set()
        self.owners = {}
        self.bound_inputs = {}
        self.staging_observations = []
        self.managed_jobs = []
        self.quality_issues = []
        self.operational_errors = []
        self.illustrative = False

    def read_owner(self, origin, path, expected=None):
        if not isinstance(path, str):
            raise CatalogError("CATALOG-METADATA-SHAPE", "Expected a local owner-record path.")
        roots = (*self.inventory.permitted_roots, self.document.path.parent)
        target = resolve_path(origin.path, path, roots)
        document = self.inventory.read(target)
        if expected is not None and document.sha256 != expected:
            raise CatalogError("CATALOG-OWNER-DIGEST", "Owner-record bytes differ from their receipt digest.")
        self.records[target] = document
        return document

    def read_pinned_owner(self, origin, reference, context):
        reference = _need(reference, {"path", "sha256"}, context)
        if not _digest(reference["sha256"]):
            raise CatalogError("CATALOG-OWNER-DIGEST", f"The {context} needs an exact SHA-256 digest.")
        return self.read_owner(origin, reference["path"], reference["sha256"])

    def read(self):
        raw = _need(self.document.value, set(), "local metadata")
        unexpected = raw.keys() - {*SECTIONS, *AUXILIARY, "illustrative"}
        if unexpected:
            raise CatalogError("CATALOG-METADATA-SHAPE", f"Unknown metadata member {min(unexpected)!r}.")
        for key in set(raw) & set((*SECTIONS, *AUXILIARY)) - {"lineage"}:
            if not isinstance(raw[key], list) or any(not isinstance(row, dict) for row in raw[key]):
                raise CatalogError("CATALOG-METADATA-SHAPE", f"Metadata member {key!r} needs an array of objects.")
        self.illustrative = raw.get("illustrative") is True
        if self.illustrative != (self.adapter == EXAMPLE_ADAPTER):
            raise CatalogError("CATALOG-METADATA-ADAPTER", "Use the example adapter only for illustrative inputs.")
        if self.illustrative and any(raw.get(key) for key in ("executions", "managedExecutions", "quality", "staging")):
            raise CatalogError("CATALOG-METADATA-ADAPTER", "Illustrative inputs cannot admit runtime receipts.")
        for section in SECTIONS:
            self.observations[section].extend(deepcopy(raw.get(section, [])))
        for section in ("lineage",):
            if section in raw:
                self.lineage = deepcopy(_need(raw[section], set(), "lineage mapping"))
        self.qualification.extend(deepcopy(raw.get("qualification", ())))
        for item in raw.get("productionObservations", ()):
            _need(item, {"production", "observedAt"}, "production observation")
            self._production_time(item["production"], item["observedAt"], owner_record(self.document))
        for item in raw.get("executions", ()):
            self.execution(item)
        for item in raw.get("managedExecutions", ()):
            from .catalog_managed_jobs import managed_execution

            managed_execution(self, item)
        for item in raw.get("staging", ()):
            self.staging(item)
        for item in raw.get("quality", ()):
            try:
                self.quality(item)
            except CatalogError as error:
                if error.status not in {"unknown", "not_run"}:
                    raise
                self.quality_issues.append(error)
        for item in raw.get("publications", ()):
            self.publication(item)
        self.observations["versions"].extend(self.version_facts.values())
        if self.illustrative:
            for item in self.observations["checks"]:
                if item.get("status") in {"passed", "failed"}:
                    item.update(status="not_run", reason="The supplied observation is illustrative.")
                    item.pop("record", None)
            self.limits.add("Illustrative metadata describes a fixture and carries no execution or qualification assurance.")
        return self

    def _production_time(self, alias, observed_at, record):
        if alias not in self.productions:
            raise CatalogError("CATALOG-PRODUCTION-MISSING", f"Production {alias!r} is outside the loaded scope.")
        observation = {"observedAt": _timestamp(observed_at, "production observation"), "record": record}
        old = self.production_times.setdefault(alias, observation)
        if old != observation:
            raise CatalogError("CATALOG-AUTHORITY-CONFLICT", f"Production {alias!r} has multiple declaration times.")

    def _file_version(self, alias, item, record, *, output=False):
        if alias not in self.datasets:
            raise CatalogError("CATALOG-VERSION-MISMATCH", f"The receipt maps to unknown dataset {alias!r}.")
        uri, digest = _artifact_uri(item)
        dataset = self.datasets[alias]
        version = stable_id("file-version", dataset["id"], dataset["definition"], uri, digest)
        reference = {"scheme": FILE_SCHEME, "authority": "urn:ddk:local-file",
                     "value": {"location": uri, "sha256": digest}}
        version_record = {"id": version, "dataset": alias, "reference": reference, "retention": "present",
                          "scope": "Exact local file named by its owner receipt.", "record": record, "sources": []}
        attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        byte_size = (item["size"] if type(item.get("size")) is int else (
            item["bytes"] if type(item.get("bytes")) is int else (
                attrs["size"] if type(attrs.get("size")) is int else None
            )
        ))
        row_count = item["rows"] if type(item.get("rows")) is int else (
            attrs["rows"] if type(attrs.get("rows")) is int else None
        )
        representation = {
            "id": stable_id("representation", version, uri), "version": version, "kind": "file",
            "location": uri, "mediaType": "application/vnd.apache.parquet", "availability": "available",
            "record": record,
        }
        if byte_size is not None and byte_size >= 0:
            representation["byteSize"] = byte_size
        if row_count is not None and row_count >= 0:
            representation["rowCount"] = row_count
        old = self.version_facts.get(version)
        if old is None:
            self.version_facts[version] = version_record
            self.observations["representations"].append(representation)
        elif old["dataset"] != alias:
            raise CatalogError("CATALOG-AUTHORITY-CONFLICT", "The same exact file version maps to conflicting aliases.")
        else:
            for existing in self.observations["representations"]:
                if existing["id"] == representation["id"]:
                    if "byteSize" in representation and "byteSize" not in existing:
                        existing["byteSize"] = representation["byteSize"]
                    if "rowCount" in representation and "rowCount" not in existing:
                        existing["rowCount"] = representation["rowCount"]
        self.physical_datasets[version] = {"namespace": "file", "name": str(Path(item["path"]))}
        self.owners.setdefault(version, [])
        if record not in self.owners[version]:
            self.owners[version].append(record)
        if output and row_count is not None and row_count >= 0:
            self.version_facts[version].setdefault("coverage", [])
            facts = self.version_facts[version]["coverage"]
            observation = {"scope": "Materialized output file.", "unit": "rows", "status": "unknown",
                           "observed": row_count, "record": record}
            if observation not in facts:
                facts.append(observation)
        return version

    def _verify_job_request(self, alias, production, request, result, request_sha256, *, exact_spec=False):
        _, spec_doc, _, _ = self.job_specs[alias]
        spec = spec_doc.value
        expected_id = production["identity"]["id"]
        if "id" in request and request["id"] != expected_id:
            raise CatalogError("CATALOG-JOB-SPEC-MISMATCH",
                               f"Pinned request id {request['id']!r} differs from job production id {expected_id!r}.",
                               step="jobs")
        if "job_id" in result and result["job_id"] is not None and result["job_id"] != expected_id:
            raise CatalogError("CATALOG-JOB-SPEC-MISMATCH",
                               f"Observed DocSpec job_id {result['job_id']!r} differs from job production id {expected_id!r}.",
                               step="jobs")
        if "job_spec_sha256" in result:
            if result["job_spec_sha256"] != request_sha256:
                raise CatalogError("CATALOG-JOB-SPEC-MISMATCH",
                                   "Observed DocSpec job_spec_sha256 disagrees with the pinned request digest.",
                                   step="jobs")
            if exact_spec and result["job_spec_sha256"] != spec_doc.sha256:
                raise CatalogError("CATALOG-JOB-SPEC-MISMATCH",
                                   "Observed DocSpec job_spec_sha256 differs from the declared JobSpec SHA-256.",
                                   step="jobs")
        allowed_keys = {"id", "scratch", "inputs", "steps", "outputs", "queries"}
        extra_keys = (set(request) | set(spec)) - allowed_keys
        if any(request.get(key) != spec.get(key) for key in extra_keys):
            raise CatalogError("CATALOG-NATIVE-RECEIPT",
                               "The pinned job request modifies non-binding JobSpec fields.", step="jobs")
        req_inputs = request.get("inputs", ())
        spec_inputs = spec.get("inputs", ())
        if (not isinstance(req_inputs, list) or len(req_inputs) != len(spec_inputs)
                or {row.get("name") for row in req_inputs if isinstance(row, dict)} != {row["name"] for row in spec_inputs}):
            raise CatalogError("CATALOG-NATIVE-RECEIPT",
                               "The pinned job request inputs differ from the declared job production.", step="jobs")
        req_steps = [
            (row.get("name"), row.get("sql"), row.get("parameters"), bool(row.get("materialize", False)))
            for row in request.get("steps", ()) if isinstance(row, dict)
        ]
        spec_steps = [
            (row["name"], row["sql"], row.get("parameters"), bool(row.get("materialize", False)))
            for row in spec.get("steps", ())
        ]
        if len(req_steps) != len(request.get("steps", ())) or req_steps != spec_steps:
            raise CatalogError("CATALOG-NATIVE-RECEIPT",
                               "The pinned job request steps differ in order, SQL, parameters, or materialization from the job production.",
                               step="jobs")
        req_outputs = [
            (row.get("name"), row.get("sql"), row.get("settings"))
            for row in request.get("outputs", ()) if isinstance(row, dict)
        ]
        spec_outputs = [
            (row["name"], row.get("sql"), row.get("settings"))
            for row in spec.get("outputs", ())
        ]
        if len(req_outputs) != len(request.get("outputs", ())) or req_outputs != spec_outputs:
            raise CatalogError("CATALOG-NATIVE-RECEIPT",
                               "The pinned job request outputs differ from the declared job production.", step="jobs")
        req_queries = [
            (row.get("name"), row.get("sql"), row.get("parameters"))
            for row in request.get("queries", ()) if isinstance(row, dict)
        ]
        spec_queries = [
            (row["name"], row.get("sql"), row.get("parameters"))
            for row in spec.get("queries", ())
        ]
        if len(req_queries) != len(request.get("queries", ())) or req_queries != spec_queries:
            raise CatalogError("CATALOG-NATIVE-RECEIPT",
                               "The pinned job request queries differ from the declared job production.", step="jobs")

    def _run_job_quality_queries(self, alias, native_queries, output_versions_by_alias, tool, record):
        from .odcs_sql_counters import evaluate_job_quality_queries

        job_artifact, spec_doc, _, _ = self.job_specs[alias]
        checks, obligations = evaluate_job_quality_queries(
            job_artifact=job_artifact,
            job_spec=spec_doc.value,
            native_queries=native_queries,
            output_versions_by_alias=output_versions_by_alias,
            datasets=self.datasets,
            inventory=self.inventory,
            evaluator=tool,
            record=record,
            stable_id_fn=stable_id,
        )
        self.observations["checks"].extend(checks)
        self.qualification.extend(obligations)

    def _direct_job_result_execution(self, entry, receipt_doc, alias, production):
        if alias not in self.job_specs:
            raise CatalogError("CATALOG-NATIVE-RECEIPT",
                               "Direct DocSpec JobResult receipts require a declared job production.")
        _, spec_doc, default_in, default_out = self.job_specs[alias]
        spec = spec_doc.value
        raw = _need(receipt_doc.value, {"job_spec_sha256", "inputs", "steps", "outputs"},
                    "DocSpec JobResult")
        expected_id = production["identity"]["id"]
        if raw.get("job_id") != expected_id:
            raise CatalogError("CATALOG-JOB-SPEC-MISMATCH",
                               f"Observed DocSpec job_id {raw.get('job_id')!r} differs from job production id {expected_id!r}.",
                               step="jobs")
        if raw.get("job_spec_sha256") != spec_doc.sha256:
            raise CatalogError("CATALOG-JOB-SPEC-MISMATCH",
                               "Observed DocSpec job_spec_sha256 differs from the declared JobSpec SHA-256.",
                               step="jobs")
        obs_steps = [
            (row.get("name"), row.get("sql_sha256"), bool(row.get("materialize", False)))
            for row in raw.get("steps", ()) if isinstance(row, dict)
        ]
        exp_steps = [
            (row["name"], sha256(row["sql"].encode("utf-8")).hexdigest(), bool(row.get("materialize", False)))
            for row in spec.get("steps", ())
        ]
        if obs_steps != exp_steps:
            raise CatalogError("CATALOG-JOB-SPEC-MISMATCH",
                               "Observed DocSpec step digests differ from the declared JobSpec.",
                               step="jobs")
        observed_at = _timestamp(
            entry.get("observedAt") or entry.get("endedAt") or raw.get("endedAt"),
            "DocSpec terminal observation",
        )
        started_at = (
            _timestamp(entry.get("startedAt") or raw.get("startedAt"), "DocSpec start observation")
            if (entry.get("startedAt") or raw.get("startedAt")) is not None
            else None
        )
        tool = self._record_tool(entry.get("tool") or raw.get("tool") or {"id": "docspec", "version": "0.1.0"},
                                 "DocSpec tool")
        record = owner_record(receipt_doc)
        input_mapping = _need(entry.get("inputs", default_in), set(), "DocSpec input mapping")
        output_mapping = _need(entry.get("outputs", default_out), set(), "DocSpec output mapping")
        spec_inputs = {row["name"]: row for row in spec.get("inputs", ())}
        spec_outputs = {row["name"]: row for row in spec.get("outputs", ())}
        if not input_mapping.keys() <= spec_inputs.keys() or not output_mapping.keys() <= spec_outputs.keys():
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "An input or output name is absent from the JobSpec.", step="jobs")
        if not set(input_mapping.values()) <= set(production["inputs"]) or not set(output_mapping.values()) <= set(production["outputs"]):
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "A receipt mapping falls outside the selected production interface.", step="jobs")
        bound_inputs, observed_inputs = {}, []
        for item in raw.get("inputs", ()):
            _need(item, {"name", "kind"}, "DocSpec JobResult input")
            name = item["name"]
            if item["kind"] != "parquet" or name not in input_mapping:
                continue
            _need(item, {"path", "sha256"}, "DocSpec JobResult parquet input")
            version = self._file_version(input_mapping[name], item, record)
            if name in bound_inputs:
                raise CatalogError("CATALOG-NATIVE-RECEIPT", "The job repeats an exact input binding.", step="jobs")
            bound_inputs[name] = version
            observed_inputs.append(version)
        output_paths = entry.get("outputPaths") if isinstance(entry.get("outputPaths"), dict) else {}
        outputs = []
        output_versions_by_alias = {}
        mapped_outputs = set()
        for item in raw.get("outputs", ()):
            _need(item, {"name", "sha256", "rows", "size"}, "DocSpec JobResult output")
            name = item["name"]
            if name not in output_mapping:
                continue
            if name in mapped_outputs:
                raise CatalogError("CATALOG-NATIVE-RECEIPT", "The native job repeats an output identity.", step="jobs")
            raw_path = item.get("path") or output_paths.get(name) or spec_outputs[name].get("path")
            if not isinstance(raw_path, str):
                raise CatalogError("CATALOG-NATIVE-REFERENCE", f"Output {name!r} needs an absolute artifact path.")
            resolved_out_path = Path(raw_path) if Path(raw_path).is_absolute() else (spec_doc.path.parent / raw_path).resolve()
            version = self._file_version(
                output_mapping[name],
                {**item, "path": str(resolved_out_path), "attributes": {"name": name, "rows": item["rows"], "size": item["size"]}},
                record, output=True,
            )
            mapped_outputs.add(name)
            outputs.append(version)
            output_versions_by_alias[output_mapping[name]] = version
        if mapped_outputs != set(output_mapping):
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "The JobResult omits a mapped output.", step="jobs")
        coverage_status = (
            "complete" if set(input_mapping) == set(spec_inputs) and len(observed_inputs) == len(spec_inputs)
            else ("partial" if observed_inputs else "unknown")
        )
        run = {
            "id": stable_id("docspec-run", receipt_doc.sha256),
            "production": alias,
            "reference": {"scheme": "urn:ddk:docspec-request:sha256", "authority": "urn:ddk:docspec:bounded-job",
                          "value": raw["job_spec_sha256"]},
            "outcome": "succeeded",
            "observedAt": observed_at,
            **({"startedAt": started_at} if started_at is not None else {}),
            "endedAt": observed_at,
            "record": record,
            "inputs": sorted(set(observed_inputs)),
            "outputs": sorted(set(outputs)),
            "inputCoverage": {"status": coverage_status, "scope": "Consumption within the native bounded job."},
        }
        self.observations["runs"].append(run)
        self.bound_inputs[run["id"]] = bound_inputs
        self.limits.add("The local DocSpec receipt supplies a terminal observation without a native START event.")
        self._run_job_quality_queries(alias, raw.get("queries", ()), output_versions_by_alias, tool, record)

    def execution(self, entry):
        _need(entry, {"path", "production"}, "execution mapping")
        alias = entry["production"]
        if not isinstance(alias, str):
            raise CatalogError("CATALOG-METADATA-SHAPE", "An execution mapping needs a production alias.")
        production = self.productions.get(alias)
        if production is None:
            raise CatalogError("CATALOG-PRODUCTION-MISSING", f"Production {alias!r} is outside the loaded scope.")
        receipt_doc = self.read_owner(self.document, entry["path"], entry.get("sha256"))
        if isinstance(receipt_doc.value, dict) and "operation" not in receipt_doc.value and "job_spec_sha256" in receipt_doc.value:
            self._direct_job_result_execution(entry, receipt_doc, alias, production)
            return
        if alias not in self.job_specs:
            _need(entry, {"path", "production", "inputs", "outputs"}, "execution mapping")
        receipt = _need(receipt_doc.value, {"request", "operation", "tool", "status", "inputs", "result", "endedAt"},
                        "DocSpec bounded-job receipt")
        operation = _need(receipt["operation"], {"runtime", "mode", "requestIdentity", "execution", "outputs"},
                          "DocSpec operation")
        request_record = _need(receipt["request"], {"path", "sha256"}, "DocSpec request identity")
        request_identity = _need(operation["requestIdentity"], {"scheme", "value"}, "DocSpec operation identity")
        status = receipt["status"]
        outcome = receipt.get("nativeOutcome", status)
        diagnostic_limit = (
            status == "error" and receipt.get("error", {}).get("code") == "DOCSPEC-DIAGNOSTIC-LIMIT"
            and (receipt.get("stderrTruncated") is True or receipt.get("drainIncomplete") is True)
        )
        if (operation["runtime"] != "docspec" or operation["mode"] != "bounded_job"
                or outcome != operation["execution"] or (status != outcome and not diagnostic_limit)
                or request_identity["scheme"] != "urn:ddk:docspec-request:sha256"
                or not _digest(request_record["sha256"]) or request_identity["value"] != request_record["sha256"]):
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "The selected receipt is not a consistent DocSpec bounded job.")
        request_doc = self.read_pinned_owner(receipt_doc, request_record, "DocSpec job request")
        request = request_doc.value
        _need(request, set(), "DocSpec job request")
        if outcome not in {"succeeded", "failed", "unknown", "not_submitted"}:
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "The DocSpec outcome is unsupported.")
        if alias in self.job_specs:
            _, spec_doc, default_in, default_out = self.job_specs[alias]
            exact_spec = (request_doc.path == spec_doc.path) or bool(entry.get("requireExactJobSpec"))
            self._verify_job_request(alias, production, request, receipt["result"] or {}, request_record["sha256"],
                                     exact_spec=exact_spec)
            raw_in_map = entry.get("inputs", default_in)
            raw_out_map = entry.get("outputs", default_out)
        else:
            raw_in_map = entry["inputs"]
            raw_out_map = entry["outputs"]
        if diagnostic_limit:
            self.operational_errors.append(("DOCSPEC-DIAGNOSTIC-LIMIT",
                                            "DocSpec diagnostic capture did not complete.", receipt_doc.path))
        if outcome == "not_submitted":
            self.limits.add("A DocSpec invocation was not submitted. Its receipt establishes no run.")
            return
        observed_at = _timestamp(receipt["endedAt"], "DocSpec terminal observation")
        record = owner_record(receipt_doc)
        tool = self._record_tool(receipt["tool"], "DocSpec tool")
        input_mapping = _need(raw_in_map, set(), "DocSpec input mapping")
        output_mapping = _need(raw_out_map, set(), "DocSpec output mapping")
        declared_inputs = {item["name"]: item for item in request.get("inputs", ())}
        declared_outputs = {item["name"]: item for item in request.get("outputs", ())}
        if not input_mapping.keys() <= declared_inputs.keys() or not output_mapping.keys() <= declared_outputs.keys():
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "An input or output name is absent from the pinned job request.")
        if not set(input_mapping.values()) <= set(production["inputs"]) or not set(output_mapping.values()) <= set(production["outputs"]):
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "A receipt mapping falls outside the selected production interface.")
        outputs, bound_inputs = [], {}
        output_versions_by_alias = {}
        for item in receipt["inputs"]:
            _need(item, {"name", "format", "path", "sha256"}, "DocSpec input observation")
            name = item["name"]
            if item["format"] != "parquet" or name not in input_mapping:
                continue
            binding = declared_inputs[name]
            if binding.get("kind") != "parquet" or binding.get("path") != item["path"]:
                raise CatalogError("CATALOG-NATIVE-RECEIPT", "An exact input differs from the pinned job request.")
            if outcome in {"succeeded", "failed"}:
                version = self._file_version(input_mapping[name], item, record)
                if name in bound_inputs:
                    raise CatalogError("CATALOG-NATIVE-RECEIPT", "The job repeats an exact input binding.")
                bound_inputs[name] = version
        native_input_rows = receipt["result"].get("inputs") if isinstance(receipt["result"], dict) else None
        has_dr297r_inputs = (
            outcome in {"succeeded", "failed"}
            and isinstance(native_input_rows, list)
            and (bool(native_input_rows) or (not declared_inputs and "job_spec_sha256" in receipt["result"]))
            and all(
                isinstance(row, dict) and isinstance(row.get("name"), str) and isinstance(row.get("kind"), str)
                and (row["kind"] not in {"parquet", "jsonl"} or (_digest(row.get("sha256")) and isinstance(row.get("path"), str)))
                for row in native_input_rows
            )
        )
        observed_run_inputs = []
        input_coverage_status = "unknown"
        if has_dr297r_inputs:
            seen_native_inputs = set()
            for row in native_input_rows:
                name = row["name"]
                if name in seen_native_inputs or name not in declared_inputs:
                    raise CatalogError("CATALOG-NATIVE-RECEIPT", "Native input observations disagree with the pinned request.")
                seen_native_inputs.add(name)
                if row["kind"] == "parquet" and name in input_mapping:
                    if row["path"] != declared_inputs[name].get("path"):
                        raise CatalogError("CATALOG-NATIVE-RECEIPT", "Native input path differs from the pinned request.")
                    version = self._file_version(input_mapping[name], row, record)
                    if name in bound_inputs and bound_inputs[name] != version:
                        raise CatalogError("CATALOG-NATIVE-RECEIPT", "Native input digest disagrees with receipt input custody.")
                    bound_inputs[name] = version
                    observed_run_inputs.append(version)
            if not declared_inputs or (set(input_mapping) == set(declared_inputs) and len(observed_run_inputs) == len(declared_inputs)):
                input_coverage_status = "complete"
            elif observed_run_inputs:
                input_coverage_status = "partial"
        native_rows = receipt["result"].get("outputs", ())
        native_outputs = {item["name"]: item for item in native_rows}
        if len(native_rows) != len(native_outputs):
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "The native job repeats an output identity.")
        mapped_outputs = set()
        for item in operation["outputs"]:
            name = item.get("attributes", {}).get("name")
            if name not in output_mapping:
                continue
            native = native_outputs.get(name, {})
            if (name in mapped_outputs or not native or item.get("path") != declared_outputs[name].get("path")
                    or item.get("sha256") != native.get("sha256") or item["attributes"].get("rows") != native.get("rows")
                    or item["attributes"].get("size") != native.get("size")):
                raise CatalogError("CATALOG-NATIVE-RECEIPT", "An output differs from the pinned request or native result.")
            mapped_outputs.add(name)
            version = self._file_version(output_mapping[name], item, record, output=True)
            outputs.append(version)
            output_versions_by_alias[output_mapping[name]] = version
        if mapped_outputs != native_outputs.keys() & output_mapping.keys():
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "The receipt omits an observed native output in the requested mapping.")
        reference = {"scheme": request_identity["scheme"], "authority": "urn:ddk:docspec:bounded-job",
                     "value": request_identity["value"]}
        run = {"id": stable_id("docspec-run", receipt_doc.sha256), "production": alias,
               "reference": reference, "outcome": outcome, "observedAt": observed_at, "record": record,
               "inputs": sorted(set(observed_run_inputs)), "outputs": sorted(set(outputs)),
               "inputCoverage": {"status": input_coverage_status, "scope": "Consumption within the native bounded job."}}
        if outcome in {"succeeded", "failed"}:
            run["endedAt"] = observed_at
        self.observations["runs"].append(run)
        self.bound_inputs[run["id"]] = bound_inputs
        if not has_dr297r_inputs:
            self.limits.add("DocSpec bound inputs without native input observations remain outside observed run lineage.")
        self.limits.add("The local DocSpec receipt supplies a terminal observation without a native START event.")
        if alias in self.job_specs and outcome == "succeeded":
            self._run_job_quality_queries(alias, receipt["result"].get("queries", ()), output_versions_by_alias, tool, record)

    def _record_tool(self, value, context):
        tool = _tool(value, context)
        previous = self.owners.setdefault("tools", [])
        if tool not in previous:
            previous.append(tool)
        return tool

    def staging(self, entry):
        _need(entry, {"path", "dataset"}, "dlt staging mapping")
        document = self.read_owner(self.document, entry["path"], entry.get("sha256"))
        receipt = _need(document.value, {"sourceFiles", "files", "loadIds", "request", "tool", "nativeReport"},
                        "dlt staging receipt")
        tool = self._record_tool(receipt["tool"], "staging tool")
        if tool["id"] != "dlt" or receipt.get("status") != "passed" or not receipt["loadIds"]:
            raise CatalogError("CATALOG-NATIVE-RECEIPT", "Staging evidence needs an observed dlt load.")
        report = self.read_pinned_owner(document, receipt["nativeReport"], "dlt native report")
        staged = self.inventory.artifacts.get(entry["dataset"])
        request = self.read_pinned_owner(document, receipt["request"], "dlt staging request").value
        if (staged is None or staged.kind != "dataset" or request.get("dataset") != staged.effective
                or request.get("files", []) != receipt["sourceFiles"]):
            raise CatalogError("CATALOG-EVIDENCE-SCOPE", "The completed dlt load differs from its pinned dataset or source scope.")
        table = request.get("table", staged.effective["name"])
        if not isinstance(table, str) or not table or table in DLT_SYSTEM_TABLES or receipt.get("normalizedTable") != table:
            raise CatalogError("CATALOG-EVIDENCE-SCOPE", "Staging requires the exact requested table name after dlt normalization.")
        tables = {item["table"] for item in receipt["files"]}
        snapshot = receipt.get("snapshotStatus", "materialized")
        if (snapshot == "materialized" and tables != {table}
                or snapshot == "empty-no-file" and tables
                or snapshot not in {"materialized", "empty-no-file"}):
            raise CatalogError("CATALOG-EVIDENCE-SCOPE", "The dlt receipt does not identify the requested table snapshot.")
        self._verify_staging_inventory(receipt, report.value, table)
        normalize = self._staging_normalize(document, receipt, request, table, snapshot)
        record = owner_record(document)
        sources = []
        for index, source in enumerate(receipt["sourceFiles"]):
            uri, digest = _artifact_uri(source)
            occurrence = stable_id("dlt-source-occurrence", document.sha256, uri, index)
            self.observations["sources"].append({
                "id": occurrence, "reference": {"scheme": "urn:ddk:dlt:source-occurrence",
                                                 "authority": "urn:ddk:dlt", "value": occurrence},
                "content": {"scheme": "urn:ddk:content:sha256", "authority": "urn:ddk:local-file", "value": digest},
                "outcome": "retained",
                "scope": f"{staged.effective.get('businessName') or table}: {Path(source['path']).name}. Source file recorded for this data load.",
                "record": record,
            })
            sources.append(occurrence)
        versions = []
        for item in receipt["files"]:
            version = self._file_version(entry["dataset"], {**item, "attributes": {"rows": item["rows"]}},
                                         record, output=True)
            prior = self.version_facts[version]["sources"]
            self.version_facts[version]["sources"] = sorted(set((*prior, *sources)))
            versions.append(version)
        self.staging_observations.append({
            "dataset": entry["dataset"], "table": table, "loadIds": receipt["loadIds"],
            "snapshotStatus": snapshot, "record": record, "nativeLoadRecord": owner_record(report),
            "sources": sources, "versions": sorted(versions), **normalize,
        })
        if snapshot == "empty-no-file":
            self.limits.add("A completed dlt load recorded zero normalized rows and produced no queryable snapshot.")

    def _staging_normalize(self, document, receipt, request, table, snapshot):
        reference = receipt.get("nativeNormalizeReport")
        if reference is None:
            if snapshot == "empty-no-file" or receipt.get("normalizedRows") is not None:
                raise CatalogError("CATALOG-STAGING-LOAD", "A normalized row count needs its native evidence.")
            if "inputRows" not in receipt:
                return {}
            observed = receipt["inputRows"]
            discarded = receipt.get("discardedRows", {})
            if (type(observed) is not int or observed < 0 or discarded.get("status") != "unknown"
                    or discarded.get("count") is not None):
                raise CatalogError("CATALOG-STAGING-LOAD", "The staging receipt misstates unknown normalization counts.")
            return {"inputRows": observed, "normalizedRows": None, "discardedRows": discarded}
        report = self.read_pinned_owner(document, reference, "dlt native normalization report")
        loads = set(receipt["loadIds"])
        normalized = 0
        for job in _staging_metrics(report.value, table, loads):
            count = job.get("items_count")
            if type(count) is not int or count < 0:
                raise CatalogError("CATALOG-STAGING-LOAD", "A normalization job lacks a valid row count.")
            normalized += count
        rows = [item["rows"] for item in receipt["files"]]
        observed = receipt.get("inputRows")
        discarded = receipt.get("discardedRows", {})
        if (type(observed) is not int or observed < normalized
                or ("rows" in request and observed != len(request["rows"]))
                or any(type(count) is not int or count < 0 for count in rows)
                or normalized != receipt.get("normalizedRows") or normalized != sum(rows)
                or discarded.get("status") != "observed" or discarded.get("count") != observed - normalized):
            raise CatalogError("CATALOG-STAGING-LOAD", "Staging row counts disagree with the native normalization inventory.")
        return {"inputRows": observed, "normalizedRows": normalized,
                "discardedRows": discarded, "nativeNormalizeRecord": owner_record(report)}

    @staticmethod
    def _verify_staging_inventory(receipt, report, table):
        load_ids = set(receipt["loadIds"])
        metrics = _staging_metrics(report, table, load_ids)
        packages = {item["load_id"] for item in report["load_packages"] if item.get("state") == "loaded"}
        if (len(load_ids) != len(receipt["loadIds"]) or load_ids != packages
                or len(load_ids) != len(report["load_packages"])
                or any(job.get("state") != "completed" for job in report["job_metrics"])):
            raise CatalogError("CATALOG-STAGING-LOAD", "Staging load IDs disagree with the completed dlt packages.")
        expected = {}
        for metric in metrics:
            _need(metric, {"remote_url", "file_size"}, "dlt load metric")
            uri, size = metric["remote_url"], metric["file_size"]
            if (not isinstance(uri, str) or not uri.startswith("file:///")
                    or type(size) is not int or size < 0 or uri in expected):
                raise CatalogError("CATALOG-STAGING-LOAD", "A staged table job lacks one completed local file observation.")
            expected[uri] = (metric["load_id"], size)
        declared = {}
        for item in receipt["files"]:
            _need(item, {"loadId", "size"}, "staged file identity")
            uri, _ = _artifact_uri(item)
            if uri in declared or type(item["size"]) is not int:
                raise CatalogError("CATALOG-STAGING-LOAD", "A staged file has duplicate identity or an invalid size.")
            declared[uri] = (item["loadId"], item["size"])
        if declared != expected:
            raise CatalogError("CATALOG-STAGING-LOAD", "Staged paths, load IDs, or sizes disagree with native dlt job metrics.")

    def quality(self, entry):
        _need(entry, {"path", "dataset", "scope"}, "quality mapping")
        document = self.read_owner(self.document, entry["path"], entry.get("sha256"))
        receipt = _need(document.value, {"evaluator", "target", "request", "rules", "requiredCheckIds", "checks", "nativeReport", "status"},
                        "quality receipt")
        evaluator = self._record_tool(receipt["evaluator"], "quality evaluator")
        target = _need(receipt["target"], {"kind"}, "quality target")
        if target["kind"] != "files" or len(target.get("files", ())) != 1:
            raise CatalogError("CATALOG-EVIDENCE-SCOPE", "The local quality mapper needs one exact checked file.",
                               status="unknown")
        uri, digest = _artifact_uri(target["files"][0])
        version = self._file_match(entry["dataset"], digest, uri=uri)
        selected = self.inventory.artifacts[entry["dataset"]]
        expected_rules = dataset_rules(selected)
        request = self.read_pinned_owner(document, receipt["request"], "quality request").value
        rule_source = self.read_pinned_owner(document, receipt["rules"], "resolved quality rules")
        rules = rule_source.value
        definition = self.datasets[entry["dataset"]]["definition"]
        declared = rules.get("document", {})
        if (request.get("target") != target
                or request.get("document") != expected_rules["document"]
                or request.get("sourceDefinitions") != expected_rules["sourceDefinitions"]
                or rules.get("sourceDefinitions") != expected_rules["sourceDefinitions"]
                or declared.get("id") != definition["contractId"] or declared.get("version") != definition["version"]
                or rules.get("mappingSemantics") != receipt.get("mappingSemantics")
                or rules.get("requiredCheckIds") != receipt["requiredCheckIds"]):
            raise CatalogError("CATALOG-EVIDENCE-SCOPE", "Quality used a different ODCS definition revision or rule scope.",
                               status="unknown")
        report = self.read_pinned_owner(document, receipt["nativeReport"], "native quality report")
        checks = self._verify_quality_checks(document, receipt, report.value, rules, evaluator)
        for check in checks:
            check_id = check["id"]
            identity = {"subject": version, "evaluator": evaluator, "scope": entry["scope"],
                        "rule": {"id": stable_id("quality-rule", definition["contractId"],
                                                definition["object"], check_id),
                                 "version": rule_source.sha256}}
            summary = {**identity, "status": check["status"], "record": owner_record(document)}
            if check.get("reason"):
                summary["reason"] = check["reason"]
            self.observations["checks"].append(summary)
            if check_id in receipt["requiredCheckIds"]:
                self.qualification.append(identity)

    def _verify_quality_checks(self, document, receipt, report, rules, evaluator):
        declared = rules["document"]
        _need(report, {"checks", "dataContractId", "dataContractVersion", "datacontractCliVersion",
                       "dryRun", "timestampEnd", "result"}, "native Data Contract CLI run")
        if (report["dataContractId"] != declared["id"] or report["dataContractVersion"] != declared["version"]
                or report["datacontractCliVersion"] != evaluator["version"] or report["dryRun"] is not False
                or not isinstance(report["timestampEnd"], str)
                or not FORMAT_CHECKER.conforms(report["timestampEnd"], "date-time")):
            raise CatalogError("CATALOG-EVIDENCE-SCOPE", "The native quality run does not cover this contract revision and evaluator.")
        required = receipt["requiredCheckIds"]
        if (not isinstance(required, list) or any(not isinstance(key, str) or not key for key in required)
                or len(set(required)) != len(required) or EXACT_FIELD_CHECK not in required):
            raise CatalogError("CATALOG-QUALITY-COVERAGE", "The pinned required-check inventory is invalid.")
        native_by_key, native_ids = {}, set()
        for check in report["checks"]:
            _need(check, {"id", "key", "result"}, "native quality check")
            identifier, key = check["id"], check["key"]
            if (not isinstance(identifier, str) or not identifier or identifier in native_ids
                    or key in native_by_key or key not in required
                    or key in {EXACT_FIELD_CHECK, QUALITY_COMPLETE_CHECK}
                    or check["result"] not in DCC_STATUS):
                raise CatalogError("CATALOG-QUALITY-COVERAGE", "Native quality checks do not resolve uniquely to required rules.")
            native_by_key[key] = check
            native_ids.add(identifier)
        native_outcomes = {check["result"] for check in native_by_key.values()}
        native_aggregate = next((status for status in ("error", "failed", "warning", "passed", "skipped")
                                 if status in native_outcomes), "unknown")
        if report["result"] != native_aggregate:
            raise CatalogError("CATALOG-QUALITY-CONTRADICTION", "The native run result disagrees with its check outcomes.")
        seen, statuses, verified = set(), set(), []
        for check in receipt["checks"]:
            _need(check, {"id", "status", "nativeCheckIds"}, "normalized quality check")
            check_id, status = check["id"], check["status"]
            if check_id in seen or check_id not in required:
                raise CatalogError("CATALOG-QUALITY-COVERAGE", "A normalized quality check is repeated or outside the rule inventory.")
            seen.add(check_id)
            statuses.add(status)
            native_check = native_by_key.get(check_id)
            if native_check is not None:
                native_result = native_check["result"]
                expected_status = DCC_STATUS[native_result]
                if (check["nativeCheckIds"] != [native_check["id"]]
                        or check.get("qualityId") != native_check.get("qualityId")
                        or (status != expected_status and not (status == native_result == "error"))):
                    raise CatalogError("CATALOG-QUALITY-CONTRADICTION",
                                       "A normalized outcome disagrees with its native quality check.")
                verified.append({**check, "status": expected_status,
                                 "reason": _quality_reason(native_check, declared)})
            elif check_id == EXACT_FIELD_CHECK and check["nativeCheckIds"] == []:
                verified.append(self._verify_exact_fields(document, receipt, declared, check))
            elif check_id == QUALITY_COMPLETE_CHECK and check["nativeCheckIds"] == []:
                verified.append(self._verify_quality_execution_complete(receipt, check))
            elif check["nativeCheckIds"] == [] and status == "not_run" and check.get("reason"):
                verified.append(check)
            else:
                raise CatalogError("CATALOG-QUALITY-CONTRADICTION", "A normalized outcome has no matching native quality check.")
        if seen != set(required):
            raise CatalogError("CATALOG-QUALITY-COVERAGE", "The receipt omits one or more required check outcomes.")
        aggregate = next((status for status in ("error", "failed", "unknown", "not_run") if status in statuses), "passed")
        if receipt["status"] != aggregate:
            raise CatalogError("CATALOG-QUALITY-CONTRADICTION", "The receipt result disagrees with its normalized outcomes.")
        return verified

    def _verify_quality_execution_complete(self, receipt, check):
        status = check["status"]
        if status not in {"passed", "unknown"}:
            raise CatalogError("CATALOG-QUALITY-CONTRADICTION",
                               "The quality execution completeness check has an invalid outcome.")
        operational = receipt.get("operational")
        if isinstance(operational, dict):
            incomplete = bool(
                operational.get("engineErrors")
                or operational.get("diagnosticsTruncated")
                or operational.get("unmeasuredChecks")
                or any(isinstance(item, dict) and item.get("status") == "unknown"
                       for item in operational.get("queryIssues", ()))
            )
            expected = "unknown" if incomplete else "passed"
            if status != expected:
                raise CatalogError("CATALOG-QUALITY-CONTRADICTION",
                                   "The quality execution completeness outcome disagrees with operational evidence.")
        return check

    def _verify_exact_fields(self, document, receipt, declared, check):
        schema = receipt.get("schemaObservation")
        if schema is None:
            return {**check, "status": "not_run", "reason": "The receipt lacks a pinned exact field-name observation."}
        observation = self.read_pinned_owner(document, schema, "exact schema observation").value
        _need(observation, {"target", "fields", "model"}, "observed schema")
        [model] = declared["schema"]
        fields = observation["fields"]
        if (observation["target"] != receipt["target"] or observation["model"] != (model.get("physicalName") or model["name"])
                or not isinstance(fields, list) or any(not isinstance(field, str) for field in fields)
                or len(fields) != len(set(fields)) or receipt.get("observedFields", fields) != fields):
            raise CatalogError("CATALOG-QUALITY-CONTRADICTION", "The exact schema observation has a different target, model, or fields.")
        expected = {field.get("physicalName") or field["name"] for field in model["properties"]}
        status = "passed" if expected <= set(fields) else "failed"
        if check["status"] != status:
            raise CatalogError("CATALOG-QUALITY-CONTRADICTION", "The exact field-name outcome disagrees with the observed schema.")
        return check

    def _file_match(self, alias, digest, *, uri=None):
        versions = [row for row in self.version_facts.values() if row["dataset"] == alias
                    and row["reference"]["value"]["sha256"] == digest
                    and (uri is None or row["reference"]["value"]["location"] == uri)]
        if len(versions) != 1:
            raise CatalogError("CATALOG-EVIDENCE-SCOPE", f"Expected one exact observed file version for {alias!r}.",
                               status="unknown")
        return versions[0]["id"]

    def publication(self, entry):
        _need(entry, {"id", "authority", "purpose", "observedAt", "members"}, "publisher selection")
        record = owner_record(self.document)
        members = _need(entry["members"], set(), "release membership")
        resolved = sorted(self._file_match(alias, digest) for alias, digest in members.items())
        self.observations["releases"].append({
            "id": entry["id"], "reference": {"scheme": "urn:ddk:local-release", "authority": entry["authority"],
                                             "value": entry["id"]},
            "members": resolved, "membership": "complete", "record": record,
        })
        self.observations["selections"].append({
            "authority": entry["authority"], "purpose": entry["purpose"], "release": entry["id"],
            "observedAt": _timestamp(entry["observedAt"], "publisher observation"), "record": record,
        })
