"""Structured access to DocSpec's bounded and retained execution services."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
import re
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4
from time import monotonic

from ddk.adapters.native import SecretRedaction, file_sha256, request_transport, run_bounded, write_json
from ddk.adapters.docspec_schema import (
    PRIMITIVE_PROFILE, RECURSIVE_PROFILE, source_native_read, validate_physical_snapshot,
)


RUNTIME = "docspec"
REQUEST_SCHEME = "urn:ddk:docspec-request:sha256"
VERSION_SCHEME = "urn:docspec:version-ref"
DEFAULT_CAPTURE_BYTES = 8 << 20


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _binary_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _error(code, message):
    return {"code": code, "message": message}



class BindingRefusal(ValueError):
    """An adapter admission refusal before a native request is sent."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

class DocSpecAdapter:
    """Prepare and execute through an explicitly selected DocSpec executable.

    A supervising host can set ``new_process_group=False`` to retain native
    children in its owned process group. That host owns group-wide cleanup;
    adapter timeouts still stop and reap the direct native child.
    """

    def __init__(self, executable, limits, *, timeout=120, evidence_dir=None,
                 capture_bytes=DEFAULT_CAPTURE_BYTES, metadata_bytes=DEFAULT_CAPTURE_BYTES,
                 source_commit=None, secret_values=(), native_mapping_profile=PRIMITIVE_PROFILE,
                 new_process_group=True):
        if not math.isfinite(timeout) or timeout <= 0 or capture_bytes <= 0:
            raise ValueError("DocSpec timeout and capture size must be positive")
        if type(metadata_bytes) is not int or metadata_bytes <= 0:
            raise ValueError("DocSpec recovery metadata size must be a positive byte count")
        if native_mapping_profile not in {PRIMITIVE_PROFILE, RECURSIVE_PROFILE}:
            raise ValueError("Select an explicitly supported native mapping profile")
        if type(new_process_group) is not bool:
            raise ValueError("DocSpec process-group placement must be an explicit boolean")
        self.new_process_group = new_process_group
        self.native_mapping_profile = native_mapping_profile
        self.executable = Path(executable).resolve(strict=True)
        self.timeout = timeout
        self.capture_bytes = capture_bytes
        self.metadata_bytes = metadata_bytes
        self.redaction = SecretRedaction(secret_values)
        self.evidence_dir = (
            Path(evidence_dir).resolve() if evidence_dir is not None
            else Path(tempfile.mkdtemp(prefix="ddk-docspec-")).resolve()
        )
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.limits = dict(limits) if isinstance(limits, Mapping) else json.loads(
            Path(limits).read_bytes()
        )
        self.tool = {"id": RUNTIME, "version": "0.1.0",
                     "distributionSha256": file_sha256(self.executable)}
        if source_commit is not None:
            self.tool["commit"] = source_commit
        self._executable_stat = _binary_identity(self.executable)

    def prepare(self, request):
        """Infer a schema and optionally produce Substrait bytes without input rows."""
        return self._invoke("job-plan", request)

    def inspect_version(self, workspace, version, *, cancel_event=None):
        """Admit one exact protected source schema without a calculation or export.

        The maintained native job input path checks the unchanged VersionRef,
        retention and source-view metadata. Empty steps, outputs and queries
        leave that provider unscanned. This is an observation, not a retained
        lease, complete data read, quality result or permission to select it.
        Subsequent reads must independently pass native admission again.
        """
        scratch = Path(tempfile.mkdtemp(prefix="inspect-version-", dir=self.evidence_dir))
        return self._invoke("job", {
            "scratch": str(scratch),
            "inputs": [{"kind": "native", "name": "source", "workspace": str(workspace),
                        "nativeVersion": version}],
            "steps": [], "outputs": [], "queries": [],
        }, cancel_event=cancel_event)

    def prepare_job(self, request):
        """Prepare an exact complete JobSpec through the native schema-only profile.

        The native result retains inferred schemas and explicit not-run input
        admission/execution. It supplies no candidate or managed acceptance.
        """
        return self._invoke("prepare-job", request)

    def execute(self, request, *, input_digests=None, semantic_profile=None, cancel_event=None):
        """Run a bounded job and preserve exact source and partial output identities."""
        return self._invoke("job", request, input_digests=input_digests, semantic_profile=semantic_profile,
                            cancel_event=cancel_event)

    def managed(self, workspace, request, *, prior=None, backend="local-iceberg", cancel_event=None):
        """Submit or reconcile the original local managed Build or Update."""
        if self.redaction:
            raise ValueError("Managed reconciliation requires its original native request")
        workspace = Path(workspace).resolve(strict=True)
        operation_context = _managed_context(workspace, request)
        previous_operation = _managed_prior(operation_context, prior)
        refusal = None
        if backend != "local-iceberg":
            refusal = BindingRefusal("DOCSPEC-BACKEND-UNSUPPORTED", "The configured managed backend is unavailable")
        elif request["action"] == "accept" and not request.get("evidence", {}).get("native_read"):
            refusal = BindingRefusal("DOCSPEC-QUALITY-ACCESS-MISSING", "Managed quality requires an exact protected native read")
        return self._invoke(
            "managed-build", request, prefix=("--workspace", str(workspace)),
            operation_context=operation_context, prior=previous_operation, refusal=refusal, cancel_event=cancel_event,
        )

    def managed_job(self, workspace, request, *, prior=None, backend="local", snapshot_source=None,
                    cancel_event=None):
        """Call the explicit retained whole-job protocol with its original identity.

        Native phases, prerequisite admission, evidence acceptance and selection
        remain DocSpec-owned. This source API does not claim a qualified profile.
        An optional snapshot source configuration path selects native input access;
        its contents, credentials and durable placement remain native-owned.
        """
        from .docspec_jobs import managed_job_context, managed_job_prior, verify_prepare_intent

        if self.redaction:
            raise ValueError("Retained job reconciliation requires its original native request")
        request = deepcopy(request)
        workspace = Path(workspace).resolve(strict=True)
        context = managed_job_context(workspace, request)
        previous, confirmation, original, constraint = managed_job_prior(context, prior, max_bytes=self.capture_bytes)
        if original is not None and request["action"] == "prepare":
            verify_prepare_intent(original["value"], request)
        refusal = None if backend == "local" else BindingRefusal(
            "DOCSPEC-BACKEND-UNSUPPORTED", "The configured retained-job backend is unavailable",
        )
        prefix = ["--workspace", str(workspace)]
        if snapshot_source is not None:
            prefix.extend(("--snapshot-source", str(Path(snapshot_source).resolve())))
        return self._invoke(
            "managed-job", request, prefix=prefix,
            operation_context=context, prior=previous, confirmation=confirmation, original_request=original,
            identity_constraint=constraint,
            refusal=refusal, cancel_event=cancel_event,
        )

    def publication_intent(self, workspace, request, *, prior=None, backend="local", cancel_event=None):
        """Freeze or inspect native publication metadata without external effects.

        Keep the private request and evidence directory for cold reconciliation.
        After an unconfirmed first freeze, replay that exact request. A standalone
        inspect observes the owner's saved decision, not the caller's proposal.
        """
        from .docspec_publication import publication_context, publication_prior

        if self.redaction:
            raise ValueError("Publication reconciliation requires its original native request")
        request = deepcopy(request)
        workspace = Path(workspace).resolve(strict=True)
        context = publication_context(workspace, request)
        previous, confirmation, original = publication_prior(
            context, request, prior, max_metadata_bytes=self.metadata_bytes, max_native_bytes=self.capture_bytes,
        )
        refusal = None if backend == "local" else BindingRefusal(
            "DOCSPEC-BACKEND-UNSUPPORTED", "The configured publication-intent backend is unavailable",
        )
        return self._invoke(
            "job-publication-intent", request, prefix=("--workspace", str(workspace)),
            operation_context=context, prior=previous, confirmation=confirmation,
            original_request=original, refusal=refusal, cancel_event=cancel_event,
        )

    def read_version(self, workspace, version, *, max_ipc_bytes=DEFAULT_CAPTURE_BYTES,
                     new_process_group=None):
        """Read protected IPC, inheriting process placement unless overridden."""
        if not isinstance(max_ipc_bytes, int) or max_ipc_bytes <= 0:
            raise ValueError("Native Arrow IPC limit must be a positive byte count")
        workspace = Path(workspace).resolve(strict=True)
        reference = _version_reference(workspace, version)
        folder = Path(tempfile.mkdtemp(prefix="read-version-", dir=self.evidence_dir))
        request_path = folder / "request.json"
        limits_path = folder / "limits.json"
        receipt_path = folder / "native-read.json"
        write_json(request_path, {"version": reference, "receipt_path": str(receipt_path)})
        write_json(limits_path, self.limits)
        if _binary_identity(self.executable) != self._executable_stat:
            raise ValueError("Selected DocSpec executable changed after adapter initialization")
        transport = run_bounded(
            [str(self.executable), "--limits", str(limits_path), "--workspace", str(workspace),
             "read-version", "--spec", str(request_path)],
            timeout=self.timeout, limit=max_ipc_bytes, stop_on_stdout_limit=True,
            new_process_group=self.new_process_group if new_process_group is None else new_process_group,
        )
        ipc = transport["stdout"]
        (folder / "stderr.log").write_bytes(transport["stderr"])
        if transport["timedOut"] or transport["stdoutTruncated"]:
            return {"status": "unknown", "error": _error(
                "DOCSPEC-NATIVE-READ-LIMIT", "Exact native read exceeded the adapter time or byte limit",
            )}
        if transport["exitCode"] != 0 or not receipt_path.is_file():
            return {"status": "failed", "error": _error(
                "DOCSPEC-NATIVE-UNAVAILABLE", "Native runtime refused or could not finish the exact read",
            ), "diagnostics": str(folder / "stderr.log")}
        data = receipt_path.read_bytes()
        receipt = json.loads(data)
        if receipt["version"] != reference or receipt["ipc_sha256"] != sha256(ipc).hexdigest():
            return {"status": "unknown", "error": _error(
                "DOCSPEC-NATIVE-READ-IDENTITY", "The read receipt does not match the requested version and observed stream",
            )}
        evidence = {"kind": "native-report", "path": str(receipt_path),
                    "sha256": sha256(data).hexdigest(), "tool": RUNTIME}
        try:
            observed = _native_read(version, receipt, self.native_mapping_profile)
        except ValueError as exc:
            return {"status": "unknown", "result": receipt, "evidence": evidence,
                    "error": _error("DOCSPEC-NATIVE-SCHEMA", str(exc))}
        observed_result = {"result": receipt, "evidence": evidence, "nativeRead": observed}
        if transport["stderrTruncated"] or transport.get("drainIncomplete"):
            return {
                "status": "error", "nativeOutcome": "succeeded", **observed_result,
                "error": _error("DOCSPEC-DIAGNOSTIC-LIMIT", "Native diagnostic capture did not complete"),
            }
        return {"status": "succeeded", "ipc": ipc, **observed_result}

    def _invoke(self, command, request, *, input_digests=None, prefix=(), operation_context=None,
                prior=None, confirmation=None, original_request=None, identity_constraint=None,
                refusal=None, semantic_profile=None, cancel_event=None):
        folder = Path(tempfile.mkdtemp(prefix=f"{command}-", dir=self.evidence_dir))
        request_path = folder / "request.json"
        limits_path = folder / "limits.json"
        request_sha256 = write_json(request_path, self.redaction.data(request) if self.redaction else request)["sha256"]
        if ((command == "managed-job" and request["action"] == "prepare")
                or (command == "job-publication-intent" and request["action"] == "freeze")) and original_request is None:
            original_request = {"reference": {"path": str(request_path), "sha256": request_sha256}, "value": request}
        if (command == "managed-job" and request["action"] in {"accept", "select", "requalify"}
                and identity_constraint is None and request.get("request_digest") and request.get("candidate")):
            identity_constraint = {"reference": {"path": str(request_path), "sha256": request_sha256}, "value": request}
        write_json(limits_path, self.limits)
        bounded = command == "job"
        result = {}
        unverified_result = None
        error = None
        status = "not_submitted"
        known_inputs = []
        native_versions = {}
        native_reads = []
        submitted = False
        transport = None
        native_evidence = None
        started_at = _now()
        started = monotonic()
        try:
            if refusal is not None:
                raise refusal
            if command == "job-publication-intent" and request_path.stat().st_size > self.metadata_bytes:
                raise BindingRefusal("DOCSPEC-REQUEST-LIMIT", "Publication request exceeds its recovery metadata limit")
            if cancel_event is not None and cancel_event.is_set():
                raise BindingRefusal("DOCSPEC-CANCELLED", "Caller cancelled before native submission")
            if _binary_identity(self.executable) != self._executable_stat:
                raise ValueError("Selected DocSpec executable changed after adapter initialization")
            known_inputs = (
                _file_inputs(request, input_digests)
                if bounded or command == "job-plan" else []
            )
            calculation = request.get("calculation", {})
            if self.redaction and (
                calculation.get("format") == "substrait" or calculation.get("save_substrait")
                or any("substrait" in step for step in request.get("steps", ()))
            ):
                raise ValueError("Designated secret parameters require the bounded SQL profile")
            compiled = request
            transport_path = request_path
            if bounded:
                compiled, native_versions = _job_request(request)
                if native_versions:
                    transport_path = folder / "native-request.json"
                    write_json(transport_path, self.redaction.data(compiled) if self.redaction else compiled)
            environment = None if not self.redaction else {
                key: value for key, value in os.environ.items() if value not in self.redaction.values
            }
            with request_transport(folder, compiled, transport_path, self.redaction) as path:
                # Once handed to the process runner, a transport exception does
                # not establish whether native execution began or completed.
                submitted = True
                transport = run_bounded(
                    [str(self.executable), "--limits", str(limits_path), *prefix,
                     command, "--spec", str(path)],
                    timeout=self.timeout, limit=self.capture_bytes, stop_on_stdout_limit=True, env=environment,
                    cancel_event=cancel_event, new_process_group=self.new_process_group,
                )
            stdout = transport["stdout"]
            (folder / "stdout.json").write_bytes(self.redaction.captured(stdout))
            native_evidence = {"kind": "native-report", "path": str(folder / "stdout.json"),
                               "sha256": sha256(stdout).hexdigest(), "tool": RUNTIME}
            (folder / "stderr.log").write_bytes(self.redaction.captured(transport["stderr"]))
            if transport["cancelled"]:
                status = "unknown"
                error = _error("DOCSPEC-CANCELLED", "Caller cancelled the wait for the native result")
            elif transport["timedOut"]:
                status = "unknown"
                error = _error("DOCSPEC-TIMEOUT", "Caller stopped waiting for the native result")
            elif transport["stdoutTruncated"]:
                status = "unknown"
                error = _error("DOCSPEC-RECEIPT-LIMIT", "Native result exceeded the captured output limit")
            else:
                try:
                    response = json.loads(stdout)
                except (ValueError, UnicodeError):
                    response = None
                if (response is None and command == "job-plan" and calculation.get("save_substrait")
                        and transport["exitCode"] == 1
                        and b"unknown field `save_substrait`" in transport["stderr"]):
                    status = "not_submitted"
                    error = _error("DOCSPEC-FORMAT-UNAVAILABLE", "The selected DocSpec build omits Substrait support")
                elif not isinstance(response, dict):
                    status = "unknown"
                    error = _error("DOCSPEC-NO-RECEIPT", "Native process returned no structured result")
                elif transport["exitCode"] == 0:
                    status = "succeeded"
                    result = response
                elif response.get("status") == "failed" and isinstance(response.get("error"), dict):
                    status = "failed"
                    result = response.get("completed") or {}
                    error = response["error"]
                else:
                    status = "unknown"
                    error = _error("DOCSPEC-INVALID-RECEIPT", "Native exit status conflicts with its result")
            if command == "job-publication-intent" and status == "failed":
                if result or not (isinstance(error.get("code"), str) and error["code"]
                                  and isinstance(error.get("message"), str) and error["message"]):
                    unverified_result, result = result or None, {}
                    status = "unknown"
                    error = _error("DOCSPEC-INVALID-RECEIPT", "Native publication refusal conflicts with its protocol")
            for path, digest in {item["path"]: item["sha256"] for item in known_inputs}.items():
                if file_sha256(path) != digest:
                    status = "unknown"
                    error = _error("DOCSPEC-INPUT-CHANGED", "Input bytes changed during the invocation")
            try:
                observed_names = set()
                observations = result.get("native_versions", [])
                if not isinstance(observations, list):
                    raise ValueError("Native version observations must be an array")
                for observation in observations:
                    name = observation["name"]
                    if name in observed_names:
                        raise ValueError("Native job returned duplicate version observations")
                    observed_names.add(name)
                    version = native_versions.get(name)
                    if version is None or observation["version"] != version["reference"]:
                        raise ValueError("Native job observation disagrees with the admitted binding")
                    _version_reference(Path(version["namespace"]), {**version, "reference": observation["version"]})
                    if "physical_snapshot" in observation:
                        validate_physical_snapshot(observation["physical_snapshot"])
                    native_reads.append(_native_read(version, observation, self.native_mapping_profile))
                if status == "succeeded" and len(native_reads) != len(native_versions):
                    raise ValueError("Native job returned incomplete version observations")
            except (ValueError, KeyError, TypeError):
                unverified_result, result, native_reads = result, {}, []
                raise
            if operation_context is not None and (status == "succeeded" or result):
                if (result.get("dataset") != operation_context["dataset"]
                        or result.get("operation") != operation_context["operationId"]):
                    if command == "job-publication-intent":
                        unverified_result = result
                    result = {}
                    raise ValueError("Native response refers to a different managed operation")
                if command == "managed-job":
                    from .docspec_jobs import validate_managed_job_response

                    try:
                        validate_managed_job_response(
                            operation_context, request, result, prior,
                            original_request=original_request["value"] if original_request else None,
                            identity_constraint=identity_constraint["value"] if identity_constraint else None,
                        )
                    except ValueError:
                        unverified_result, result = result, {}
                        raise
                elif command == "job-publication-intent":
                    from .docspec_publication import validate_publication_response

                    try:
                        validate_publication_response(
                            operation_context, request, result,
                            original_request=original_request["value"] if original_request else None,
                            prior_result=confirmation["value"] if confirmation else None,
                        )
                    except (ValueError, KeyError, TypeError):
                        unverified_result, result = result, {}
                        raise
        except BindingRefusal as exc:
            status = "unknown" if submitted else "not_submitted"
            error = _error(exc.code, str(exc))
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = _error("DOCSPEC-IO", str(exc))
            if notes := getattr(exc, "__notes__", None):
                error["cleanupDiagnostics"] = list(notes)
            if submitted:
                status = "unknown"
        except (ValueError, KeyError, TypeError) as exc:
            if command == "job-publication-intent" and result:
                unverified_result, result = result, {}
            status = "unknown" if submitted else "not_submitted"
            error = _error(getattr(exc, "code", "DOCSPEC-BINDING"), str(exc))

        native_outcome = status
        native_error = error
        if transport is not None and (transport["stderrTruncated"] or transport.get("drainIncomplete")):
            status = "error"
            error = _error("DOCSPEC-DIAGNOSTIC-LIMIT", "Native diagnostic capture did not complete")
        receipt_path = folder / "receipt.json"
        receipt = {
            "status": status,
            "nativeOutcome": native_outcome,
            "request": {"path": str(request_path), "sha256": request_sha256},
            "limits": self.limits,
            "tool": self.tool,
            "endpoint": str(self.executable),
            "inputs": known_inputs,
            "nativeReads": native_reads,
            "startedAt": started_at,
            "endedAt": _now(),
            "durationSeconds": monotonic() - started,
            "result": result,
        }
        if semantic_profile is not None:
            receipt["semantics"] = semantic_profile
        if command in {"managed-job", "job-publication-intent"} and original_request is not None:
            receipt["originalRequest"] = original_request["reference"]
        if command == "managed-job" and identity_constraint is not None:
            receipt["identityConstraint"] = identity_constraint["reference"]
        if unverified_result is not None:
            receipt["unverifiedResult"] = unverified_result
        if command == "managed-job" and confirmation is not None and result.get("status") != "completed":
            # One exact prior receipt preserves confirmed computation through
            # later transport loss; the pointer never grows into a retry chain.
            receipt["confirmation"] = confirmation
        if error is not None:
            receipt["error"] = error
        if transport is not None:
            receipt["exitCode"] = transport["exitCode"]
            receipt["stderrTruncated"] = transport["stderrTruncated"]
            receipt["drainIncomplete"] = transport.get("drainIncomplete", False)
            if transport.get("cleanupDiagnostics"):
                receipt["cleanupDiagnostics"] = transport["cleanupDiagnostics"]
        operation = None
        if bounded:
            operation = {
                "runtime": RUNTIME,
                "mode": "bounded_job",
                "requestIdentity": (
                    {"scheme": "urn:ddk:docspec-sensitive-request:opaque", "value": str(uuid4())}
                    if self.redaction else {"scheme": REQUEST_SCHEME, "value": request_sha256}
                ),
                "reconciliation": "unsupported",
                "execution": native_outcome,
                "selection": "not_requested",
                "outputs": _observed_outputs(request, result),
            }
            if native_outcome == "unknown":
                operation["reason"] = native_error["message"]
            receipt["operation"] = operation
        if operation_context is not None:
            operation_mapper = _managed_operation
            if command == "managed-job":
                from .docspec_jobs import managed_job_operation

                operation_mapper = managed_job_operation
            if command == "job-publication-intent":
                from .docspec_publication import publication_operation

                operation = publication_operation(
                    operation_context, request["action"], request_sha256, result, native_outcome, native_error, prior,
                    native_evidence,
                )
            else:
                operation = operation_mapper(
                    operation_context, request["action"], request_sha256, result, native_outcome, native_error, prior,
                )
            receipt["operation"] = operation
            receipt["operationContext"] = operation_context
        if status == "error" and native_error is not None:
            receipt["nativeError"] = native_error
        if self.redaction:
            receipt = self.redaction.data(receipt)
            receipt["redaction"] = {"kind": "designated-parameters", "nativeEvidence": "redacted-view",
                                    "requestReusable": False}
            result = receipt["result"]
            error = receipt.get("error")
            operation = receipt.get("operation")
            native_reads = receipt["nativeReads"]
        if command == "job-publication-intent":
            from ddk.documents import json_dumps

            # Native inline controls live once in bounded stdout. The private
            # recovery record keeps only their pin and the compact observation.
            receipt.pop("result")
            receipt["metadataBytes"] = self.metadata_bytes
            receipt["captureBytes"] = self.capture_bytes
            if native_evidence is not None:
                receipt["nativeResponse"] = native_evidence
            if receipt.pop("unverifiedResult", None) is not None:
                receipt["unverifiedResponse"] = native_evidence
            if len((json_dumps(receipt) + "\n").encode()) > self.metadata_bytes:
                # Request and raw response already have stable files. Do not
                # return saved success for a recovery record we cannot admit.
                raise OSError(
                    "Publication recovery receipt exceeds its metadata limit; "
                    f"original request retained at {original_request['reference']['path'] if original_request else request_path}; "
                    f"native response retained at {folder / 'stdout.json'}"
                )
        receipt_sha256 = write_json(receipt_path, receipt)["sha256"]
        response = {
            "status": status,
            "result": result,
            "receipt": receipt,
            "evidence": {"kind": "native-report", "path": str(receipt_path),
                         "sha256": receipt_sha256, "tool": RUNTIME},
        }
        if operation is not None:
            response["operation"] = operation
        if operation_context is not None:
            response["operationContext"] = operation_context
        if native_reads:
            response["nativeReads"] = native_reads
        if error is not None:
            response["error"] = error
        if status == "error":
            response["nativeOutcome"] = native_outcome
        return response


def _file_inputs(request, input_digests):
    paths = {}
    for binding in request.get("inputs", []):
        kind = binding.get("kind")
        if kind == "parquet":
            paths[binding["path"]] = (binding["name"], "parquet")
        elif kind == "json_lines":
            for member in binding["files"]:
                paths[member["path"]] = (binding["name"], "json_lines")
        elif kind in {"native_table", "iceberg", "version"}:
            raise ValueError("DDK exact native access requires a protected DocSpec version reference")
    for step in request.get("steps", []):
        if plan := step.get("substrait"):
            paths[plan["path"]] = (step["name"], "substrait")
    calculation = request.get("calculation", {})
    if calculation.get("format") == "substrait":
        paths[calculation["path"]] = ("calculation", "substrait")
    expected = {} if input_digests is None else dict(input_digests)
    for plan in [
        *(step["substrait"] for step in request.get("steps", []) if "substrait" in step),
        *([calculation] if calculation.get("format") == "substrait" else []),
    ]:
        if plan["path"] in expected and expected[plan["path"]] != plan["sha256"]:
            raise ValueError("Conflicting saved plan digests")
        expected[plan["path"]] = plan["sha256"]
    if set(expected) - set(paths):
        raise ValueError("Expected input digest supplied for an unbound path")
    inventory = []
    for path, (name, kind) in paths.items():
        file = Path(path)
        if not file.is_absolute() or not file.is_file():
            raise ValueError(f"DocSpec {kind} binding requires one explicit absolute file path")
        digest = file_sha256(file)
        if path in expected and expected[path] != digest:
            raise ValueError(f"SHA-256 mismatch for {name}")
        inventory.append({"name": name, "format": kind, "path": path, "sha256": digest})
    return inventory


def _observed_outputs(request, result):
    paths = {output["name"]: output["path"] for output in request.get("outputs", [])}
    return [
        {
            "kind": "dataset-snapshot",
            "path": paths[output["name"]],
            "sha256": output["sha256"],
            "tool": RUNTIME,
            "attributes": {"name": output["name"], "rows": output["rows"], "size": output["size"]},
        }
        for output in result.get("outputs", [])
    ]


def _job_request(request):
    if request.get("catalog_root") is not None or request.get("table_operations"):
        raise ValueError("The DDK bounded calculation profile does not admit catalog operations")
    native_versions = {}
    inputs = []
    for binding in request.get("inputs", []):
        if binding.get("kind") != "native":
            inputs.append(binding)
            continue
        if set(binding) != {"kind", "name", "workspace", "nativeVersion"}:
            raise ValueError("Native input requires only name, workspace, and exact nativeVersion")
        workspace = Path(binding["workspace"]).resolve(strict=True)
        version = binding["nativeVersion"]
        reference = _version_reference(workspace, version)
        name = binding["name"]
        if name in native_versions:
            raise ValueError("Duplicate native input name")
        native_versions[name] = version
        inputs.append({"kind": "version", "name": name, "workspace": str(workspace), "version": reference})
    return {**request, "inputs": inputs}, native_versions


def native_version(workspace, reference):
    """Wrap the runtime's unchanged VersionRef using the local profile."""
    return {
        "runtime": RUNTIME, "scheme": VERSION_SCHEME, "schemeVersion": "1",
        "namespace": str(Path(workspace).resolve()), "digestAlgorithm": "blake3",
        "reference": reference,
    }


def _version_reference(workspace, version):
    reference = version.get("reference")
    if not isinstance(reference, dict) or native_version(workspace, reference) != version:
        raise BindingRefusal("DOCSPEC-NATIVE-IDENTITY", "Expected an exact local DocSpec VersionRef with native BLAKE3")
    manifest = reference.get("manifest")
    if (set(reference) != {"dataset", "version", "manifest"}
            or not isinstance(manifest, dict)
            or set(manifest) != {"owner", "path", "digest", "bytes"}
            or not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)
                       for value in (reference["dataset"], reference["version"], manifest["owner"]))
            or not isinstance(manifest["path"], str) or not Path(manifest["path"]).is_absolute()
            or not isinstance(manifest["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["digest"])
            or type(manifest["bytes"]) is not int or manifest["bytes"] <= 0):
        raise BindingRefusal("DOCSPEC-NATIVE-IDENTITY", "Invalid DocSpec VersionRef")
    return reference


_LOGICAL_TYPES = {
    "Boolean": "boolean", "Int8": "integer", "Int16": "integer",
    "Int32": "integer", "Int64": "integer", "Float32": "number", "Float64": "number",
    "Utf8": "string", "LargeUtf8": "string", "Utf8View": "string",
    "Binary": "binary", "LargeBinary": "binary", "BinaryView": "binary",
    "Date32": "date", "Date64": "date",
}


def _native_read(version, receipt, profile=PRIMITIVE_PROFILE):
    if profile == RECURSIVE_PROFILE:
        return source_native_read(version, receipt)
    if profile != PRIMITIVE_PROFILE:
        raise ValueError("Unsupported native mapping profile")
    fields = []
    for position, field in enumerate(receipt["schema"]["fields"]):
        physical = field["data_type"]
        native_id = field["metadata"].get("PARQUET:field_id")
        if not isinstance(physical, str) or physical not in _LOGICAL_TYPES or native_id is None:
            raise ValueError(f"Exact mapping unavailable for native field {field['name']!r}")
        fields.append({
            "logicalName": field["name"], "engineName": field["name"], "position": position,
            "logicalType": _LOGICAL_TYPES[physical], "physicalType": physical,
            "nullable": field["nullable"], "nativeFieldId": int(native_id),
        })
    digest = version["reference"]["manifest"]["digest"]
    return {
        "version": version,
        "schemaIdentity": {
            "scheme": "urn:docspec:iceberg-schema",
            "value": f"blake3:{digest}:{receipt['schema_id']}",
        },
        "fields": fields,
    }


def _managed_context(workspace, request):
    action = request.get("action")
    if action == "prepare":
        operation = request.get("build", {})
    elif action == "prepare_update":
        operation = request.get("update", {})
    elif action in {"inspect", "accept", "requalify", "select"}:
        operation = request
    else:
        raise ValueError("Unsupported local managed action")
    dataset, operation_id = operation.get("dataset"), operation.get("operation")
    if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)
               for value in (dataset, operation_id)):
        raise ValueError("Managed operation requires exact dataset and operation identifiers")
    return {"runtime": RUNTIME, "workspace": str(workspace), "dataset": dataset, "operationId": operation_id}


def _managed_prior(context, prior):
    if prior is None:
        return None
    if "operationContext" in prior:
        prior_context = prior["operationContext"]
        operation = prior.get("operation", {})
    elif candidate := prior.get("candidate"):
        operation = prior
        prior_context = {
            "runtime": prior.get("runtime"), "workspace": candidate.get("namespace"),
            "dataset": candidate.get("reference", {}).get("dataset"), "operationId": prior.get("operationId"),
        }
    else:
        raise ValueError("Previous managed receipt must retain its workspace and dataset")
    if (prior_context != context or operation.get("runtime") != RUNTIME
            or operation.get("mode") != "managed_operation"
            or operation.get("operationId") != context["operationId"]):
        raise ValueError("Previous managed receipt refers to another workspace, dataset or operation")
    return operation


def _managed_operation(context, action, request_sha256, result, status, error, prior):
    native_request = result.get("request_digest")
    candidate = result.get("candidate")
    prior_candidate = prior.get("candidate") if prior else None
    execution = "succeeded" if candidate or prior_candidate else (
        "not_submitted" if status == "not_submitted" else "unknown"
    )
    selection = result.get("selection", "unknown")
    if execution == "not_submitted":
        selection = "not_requested"
    elif status == "failed" and action == "select":
        selection = "refused"
    operation = {
        "runtime": RUNTIME, "mode": "managed_operation", "operationId": context["operationId"],
        "qualificationRequired": True,
        "requestIdentity": (
            {"scheme": "urn:docspec:managed-build-request:blake3", "value": native_request}
            if native_request else prior["requestIdentity"] if prior else
            {"scheme": REQUEST_SCHEME, "value": request_sha256}
        ),
        "reconciliation": "supported", "execution": execution,
        "selection": selection, "outputs": [],
    }
    if candidate or prior_candidate:
        version = native_version(context["workspace"], candidate) if candidate else prior_candidate
        operation["candidate"] = version
        operation["outputs"] = [{"kind": "dataset-snapshot", "nativeVersion": version, "tool": RUNTIME}]
    if accepted := result.get("accepted_qualification"):
        operation["acceptedQualification"] = {
            "scheme": "urn:docspec:accepted-qualification:blake3", "value": accepted,
        }
    if "unknown" in (execution, selection):
        operation["reason"] = error["message"] if error else "Native candidate preparation has no retained completion"
    return operation
