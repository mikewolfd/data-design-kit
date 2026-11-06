"""Native Frictionless validation, dlt staging, and typed fixture materialization."""

from copy import deepcopy
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit, unquote

from ddk.arrow_mapping import MappingUnavailable, arrow_schema, typed_rows
from ddk.definitions import enum_values
from .native import file_sha256, write_json

TYPE_MAP = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean", "date": "date"}


def table_schema(dataset, *, missing_values=None):
    missing = [""] if missing_values is None else missing_values
    fields, coverage = [], []
    for prop in dataset["properties"]:
        name = prop["name"]
        logical = prop.get("logicalType")
        supported = logical in TYPE_MAP
        field = {"name": name, "type": TYPE_MAP.get(logical, "any"), "constraints": {}}
        coverage.append({"field": name, "facet": "type", "status": "exact" if supported else "unsupported"})
        for key in ("required", "unique"):
            if key in prop:
                field["constraints"][key] = prop[key]
                coverage.append({"field": name, "facet": key, "status": "exact"})
        values = enum_values(prop)
        if values is not None:
            field["constraints"]["enum"] = values
            ambiguous = any(type(x) is bool for x in values) and any(type(x) in (int, float) for x in values)
            empty = "" in values and "" in missing
            coverage.append({"field": name, "facet": "enum", "status": "unknown" if ambiguous or empty else "exact"})
        for key, value in prop.get("logicalTypeOptions", {}).items():
            translated = {"minLength": "minLength", "maxLength": "maxLength", "pattern": "pattern",
                          "minimum": "minimum", "maximum": "maximum"}.get(key)
            if translated:
                field["constraints"][translated] = value
            elif key != "enum":
                coverage.append({"field": name, "facet": key, "status": "unsupported"})
        if prop.get("quality"):
            coverage.append({"field": name, "facet": "quality", "status": "unsupported",
                             "reason": "File intake does not execute quality SQL; select data.odcs separately"})
        fields.append(field)
    schema = {"fields": fields, "missingValues": missing}
    for custom in dataset.get("customProperties", []):
        if custom.get("vendor") == "ddk" and custom.get("property") == "rowIdentity":
            value = custom["value"]
            if isinstance(value, list) and all(isinstance(x, str) for x in value):
                schema["primaryKey"] = value
                coverage.append({"facet": "rowIdentity", "status": "exact"})
            else:
                coverage.append({"facet": "rowIdentity", "status": "unsupported"})
    coverage.append({"facet": "missing-values", "status": "exact", "values": missing})
    return schema, coverage


def files(request, folder):
    from frictionless import Checklist, Resource, Schema, validate
    schema, coverage = table_schema(request["dataset"], missing_values=request.get("missingValues"))
    reports, inventory = [], []
    checks = request.get("checks", [])
    checklist = {"checks": checks}
    check_coverage = "complete"
    for member in request["files"]:
        path = Path(member["path"]).resolve(strict=True)
        digest = file_sha256(path)
        if member.get("sha256", digest) != digest:
            raise ValueError("File intake digest mismatch")
        resource = Resource(path=path.name, basepath=str(path.parent), format="csv", schema=Schema.from_descriptor(schema),
                            encoding=request.get("encoding", "utf-8"))
        try:
            native = validate(resource, checklist=Checklist.from_descriptor(checklist), pick_errors=None).to_descriptor()
        except Exception as exc:
            native = {"exception": type(exc).__name__, "message": str(exc), "valid": None}
            check_coverage = "incomplete"
        # The pinned native version can remove later checks after a check-start
        # error. Preserve its report but never claim a complete check inventory.
        errors = [*native.get("errors", []), *(error for task in native.get("tasks", []) for error in task.get("errors", []))]
        if any(error.get("type") == "check-error" for error in errors):
            check_coverage = "incomplete"
        reports.append(native)
        if file_sha256(path) != digest:
            raise RuntimeError("Input file changed during validation")
        inventory.append({"path": str(path), "sha256": digest})
    native_ref = write_json(folder / "native-report.json", {"reports": reports})
    descriptor = write_json(folder / "table-schema.json", schema)
    failed = not reports or any(r.get("valid") is False for r in reports)
    unsupported = any(c["status"] in ("unknown", "unsupported") and c["facet"] != "quality" for c in coverage)
    return {"status": "failed" if failed else "unknown" if unsupported or check_coverage != "complete" else "passed",
            "files": inventory, "mappingCoverage": coverage, "descriptor": descriptor,
            "requestedChecks": checks, "checkCoverage": check_coverage,
            "nativeReport": native_ref, "native": reports,
            "tool": {"name": "frictionless", "version": metadata.version("frictionless")}}


def _arrow(dataset):
    import pyarrow as pa
    types = {"string": pa.string(), "integer": pa.int64(), "number": pa.float64(),
             "boolean": pa.bool_(), "date": pa.date32()}
    _, mapping = arrow_schema(dataset)
    if any(c["status"] != "exact" for c in mapping):
        raise MappingUnavailable("Unsupported Arrow fixture mapping")
    return pa.schema([pa.field(p["name"], types[p["logicalType"]], nullable=not p.get("required", False))
                      for p in dataset["properties"]])


def _observed_arrow(schema):
    import pyarrow as pa
    names = {pa.string(): "Utf8", pa.large_string(): "LargeUtf8", pa.int64(): "Int64",
             pa.float64(): "Float64", pa.bool_(): "Boolean", pa.date32(): "Date32"}
    fields = []
    for field in schema:
        if field.type not in names:
            raise ValueError(f"Unqualified staged Arrow type {field.type}")
        fields.append({"name": field.name, "data_type": names[field.type], "nullable": field.nullable,
                       "dict_id": 0, "dict_is_ordered": False, "metadata": {}})
    return {"fields": fields, "metadata": {}}


def fixture_files(request, folder):
    import pyarrow as pa
    import pyarrow.parquet as pq
    outputs = []
    for name, item in request["inputs"].items():
        if not name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Fixture table names must be simple identifiers")
        table = pa.Table.from_pylist(typed_rows(item["rows"], item["dataset"]), schema=_arrow(item["dataset"]))
        path = folder / (name + ".parquet")
        pq.write_table(table, path)
        outputs.append({"name": name, "path": str(path), "sha256": file_sha256(path), "rows": len(table),
                        "schema": arrow_schema(item["dataset"])[0]})
    return {"status": "passed", "files": outputs, "tool": {"name": "pyarrow", "version": metadata.version("pyarrow")}}


def stage(request, folder):
    import dlt
    from dlt.destinations import filesystem
    from frictionless import Resource, Schema
    import pyarrow.parquet as pq

    dataset = request["dataset"]
    schema, coverage = table_schema(dataset, missing_values=request.get("missingValues"))
    if any(c["status"] in ("unsupported", "unknown") and c["facet"] != "quality" for c in coverage):
        return {"status": "unknown", "reason": "Staging requires a supported flat input mapping", "mappingCoverage": coverage}
    name = request.get("table", dataset["name"])
    if not name.replace("_", "").isalnum() or name.startswith("_dlt"):
        raise ValueError("Staging table name must be a simple, non-system identifier")
    declared = dlt.Schema("ddk_local_stage")
    normalized_name = declared.naming.normalize_table_identifier(name)
    name_mapping = {p["name"]: declared.naming.normalize_identifier(p["name"])
                    for p in dataset["properties"]}
    if normalized_name != name or any(source != target for source, target in name_mapping.items()):
        return {"status": "unknown", "reason": "This staging profile requires table and field names unchanged by native normalization",
                "mappingCoverage": [*coverage, {"facet": "native-name-normalization", "status": "unsupported"}],
                "requestedTable": name, "normalizedTable": normalized_name, "nameMapping": name_mapping}
    data_types = {"string": "text", "integer": "bigint", "number": "double", "boolean": "bool", "date": "date"}
    columns = {p["name"]: {"data_type": data_types[p["logicalType"]], "nullable": not p.get("required", False)}
               for p in dataset["properties"]}
    policy = request.get("schemaPolicy", {"tables": "freeze", "columns": "freeze", "data_type": "freeze"})
    if set(policy) != {"tables", "columns", "data_type"}:
        raise ValueError("Specify table, column and data-type evolution policies independently")
    source_files = []
    input_rows = 0
    def items():
        nonlocal input_rows
        # This native marker materializes the declared schema without inventing
        # a data row, including when the source is empty or all rows are dropped.
        yield dlt.mark.materialize_table_schema()
        if "rows" in request:
            # The declared hints deliberately do not strip unknown fields. dlt
            # must enforce its own evolution policy on what the source yields.
            for row in request["rows"]:
                input_rows += 1
                yield row
        else:
            for member in request["files"]:
                path = Path(member["path"]).resolve(strict=True)
                if file_sha256(path) != member["sha256"]:
                    raise ValueError("Staging source digest mismatch")
                source_files.append({"path": str(path), "sha256": member["sha256"]})
                with Resource(path=path.name, basepath=str(path.parent), format="csv", schema=Schema.from_descriptor(schema)) as resource:
                    for row in resource.row_stream:
                        if not row.valid:
                            raise ValueError("Invalid CSV row cannot be staged")
                        input_rows += 1
                        yield row.to_dict()
                if file_sha256(path) != member["sha256"]:
                    raise ValueError("Staging source changed during read")
    destination = folder / "destination"
    pipeline = dlt.pipeline(pipeline_name="ddk_local_stage", pipelines_dir=str(folder / "pipeline"),
                            destination=filesystem(bucket_url=destination.as_uri()), dataset_name="ddk_stage")
    resource = dlt.resource(items, name=name, columns=columns, schema_contract=policy,
                            write_disposition="append")
    declared.update_table(resource.compute_table_schema())
    try:
        info = pipeline.run(resource, schema=declared, loader_file_format="parquet")
        info.raise_on_failed_jobs()
        if any(package.state != "loaded" for package in info.load_packages):
            raise RuntimeError("dlt returned a package that has not finished loading")
    except Exception as exc:
        # Failed loads and normalization policy errors retain native state in the
        # caller-owned run directory. Nothing is presented as a staged snapshot.
        native = {"exception": type(exc).__name__, "message": str(exc),
                  "pipelineDirectory": str(folder / "pipeline")}
        return {"status": "failed", "reason": "dlt load did not complete", "schemaPolicy": policy,
                "nativeReport": write_json(folder / "native-report.json", native), "files": [],
                "tool": {"name": "dlt", "version": metadata.version("dlt")}}
    from dlt.common import json as native_json
    from ddk.documents import parse_json
    native = parse_json(native_json.dumps(info.asdict()).encode())
    output_files = []
    load_ids = list(info.loads_ids)
    for job in native.get("job_metrics", []):
        if job["table_name"] != name:
            continue
        if job["state"] != "completed" or job["load_id"] not in load_ids:
            raise RuntimeError("dlt did not attest a completed table job in this load")
        location = urlsplit(job["remote_url"] or "")
        if location.scheme != "file" or location.netloc:
            raise RuntimeError("The local staging profile requires file URLs")
        path = Path(unquote(location.path)).resolve(strict=True)
        if not path.is_relative_to(destination) or path.suffix != ".parquet" or path.stat().st_size != job["file_size"]:
            raise RuntimeError("Staged output differs from the native completed-job inventory")
        parquet = pq.ParquetFile(path)
        output_files.append({"path": str(path), "sha256": file_sha256(path),
                             "rows": parquet.metadata.num_rows, "table": name, "loadId": job["load_id"], "size": job["file_size"],
                             "fields": parquet.schema_arrow.names,
                             "schema": _observed_arrow(parquet.schema_arrow),
                             "systemColumns": [n for n in parquet.schema_arrow.names if n.startswith("_dlt_")]})
    normalized = pipeline.last_trace.last_normalize_info
    counts = dict(normalized.row_counts) if normalized is not None else None
    normalize_report = write_json(folder / "native-normalize-report.json",
                                  parse_json(native_json.dumps(normalized.asdict()).encode())) if normalized is not None else None
    normalized_rows = counts.get(name, 0) if counts is not None else None
    observed_rows = sum(member["rows"] for member in output_files)
    if not output_files and normalized_rows != 0:
        raise RuntimeError("dlt returned without an accounted staged Parquet snapshot")
    if normalized_rows is not None and normalized_rows != observed_rows:
        raise RuntimeError("Staged rows differ from the native normalization inventory")
    discarded = input_rows - normalized_rows if normalized_rows is not None else None
    if discarded is not None and discarded < 0:
        raise RuntimeError("The flat staging profile cannot account for amplified rows")
    return {"status": "passed", "sourceFiles": source_files, "files": output_files,
            "snapshotStatus": "materialized" if output_files else "empty-no-file",
            "normalizedTable": normalized_name,
            "loadIds": load_ids, "schemaPolicy": policy, "declaredColumns": columns,
            "nameMapping": name_mapping,
            "inputRows": input_rows, "normalizedRows": normalized_rows,
            "discardedRows": {"status": "observed" if discarded is not None else "unknown", "count": discarded,
                              "method": "source row count minus native normalized table row count"},
            "quarantine": "not_requested", "mappingCoverage": coverage,
            "nativeNormalizeReport": normalize_report,
            "nativeReport": write_json(folder / "native-report.json", native),
            "tool": {"name": "dlt", "version": metadata.version("dlt")}}
