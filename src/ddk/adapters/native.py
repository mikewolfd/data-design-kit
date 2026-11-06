"""Opt-in subprocess transport for separately installed native Python tools."""

from contextlib import contextmanager
from hashlib import file_digest, sha256
import json
import os
import math
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
from time import monotonic

from ddk.documents import DocumentError, ResourceLimit, json_dumps, parse_json


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    data = (json_dumps(value, sort_keys=True) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(data)
    return {"path": str(Path(path).resolve()), "sha256": sha256(data).hexdigest()}



class SecretRedaction:
    """Redact explicitly supplied string values in retained text evidence."""

    def __init__(self, values=()):
        values = tuple(values)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("Designated secret parameters must be nonempty strings")
        self.values = frozenset(values)
        self.spellings = sorted({
            form for value in self.values
            for form in (value, value.replace("'", "''"), json.dumps(value, ensure_ascii=True)[1:-1],
                         json.dumps(value, ensure_ascii=False)[1:-1])
        }, key=lambda value: (-len(value), value))

    def __bool__(self):
        return bool(self.values)

    def text(self, value):
        for spelling in self.spellings:
            value = value.replace(spelling, "[REDACTED]")
        return value

    def data(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(key): self.data(member) for key, member in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.data(member) for member in value]
        return value

    def captured(self, value):
        return self.text(value.decode("utf-8", errors="replace")).encode("utf-8") if self else value


@contextmanager
def request_transport(folder, request, retained_path, redaction):
    if not redaction:
        yield retained_path
        return
    with tempfile.TemporaryDirectory(prefix=".private-request-", dir=folder) as directory:
        path = Path(directory) / "request.json"
        write_json(path, request)
        yield path


def _sanitize_artifacts(folder, redaction):
    """Redact worker text artifacts and return digests of the written bytes."""
    changed = {}
    if redaction:
        for path in sorted(folder.rglob("*")):
            if path.suffix not in {".json", ".log"} or path.is_symlink() or not path.is_file():
                continue
            original = path.read_bytes()
            if path.suffix == ".json":
                try:
                    parsed = parse_json(original)
                except (DocumentError, ResourceLimit):
                    public = redaction.captured(original)
                else:
                    clean = redaction.data(parsed)
                    public = original if clean == parsed else (json_dumps(clean) + "\n").encode()
            else:
                public = redaction.captured(original)
            if public != original:
                path.write_bytes(public)
                changed[str(path)] = sha256(public).hexdigest()
    return changed


def _public_response(value, redaction, changed):
    if isinstance(value, dict):
        result = {redaction.text(key): _public_response(item, redaction, changed)
                  for key, item in value.items()}
        if isinstance(value.get("path"), str) and value["path"] in changed and "sha256" in value:
            result["sha256"] = changed[value["path"]]
        return result
    if isinstance(value, list):
        return [_public_response(item, redaction, changed) for item in value]
    return redaction.data(value)

def run_bounded(arguments, *, timeout, limit, env=None, stop_on_stdout_limit=False,
                new_process_group=True, cancel_event=None):
    """Bound process time and capture, with optional caller cancellation."""
    if not math.isfinite(timeout) or timeout <= 0 or type(limit) is not int or limit <= 0:
        raise ValueError("Native timeout and capture limit must be positive")
    captures, truncated = [bytearray(), bytearray()], [False, False]
    proc = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                            start_new_session=new_process_group)
    selector = None
    timed_out, drain_incomplete, stopped, cancelled = False, False, False, False
    deadline = monotonic() + timeout
    drain_deadline = None
    primary_error = None

    def stop():
        nonlocal stopped, drain_deadline
        stopped = True
        if drain_deadline is None:
            drain_deadline = monotonic() + 1
        if proc.returncode is not None:
            return
        try:
            if new_process_group:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass

    def wait_until(bound):
        return proc.wait(timeout=max(0, bound - monotonic()))

    try:
        selector = selectors.DefaultSelector()
        for index, stream in enumerate((proc.stdout, proc.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, index)
        while True:
            now = monotonic()
            if not stopped and cancel_event is not None and cancel_event.is_set():
                cancelled = True
                stop()
            elif not stopped and now >= deadline:
                timed_out = True
                stop()
            if drain_deadline is not None and now >= drain_deadline:
                drain_incomplete = bool(selector.get_map())
                break
            if not selector.get_map():
                try:
                    wait_until(min(now + 0.05, drain_deadline or deadline))
                except subprocess.TimeoutExpired:
                    continue
                break
            # Retain the unreaped child while pipes remain open, so its process
            # group cannot be mistaken for a later process after PID reuse.
            for key, _ in selector.select(0.05):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                index = key.data
                remaining = max(0, limit - len(captures[index]))
                captures[index].extend(chunk[:remaining])
                truncated[index] |= len(chunk) > remaining
                if index == 0 and truncated[0] and stop_on_stdout_limit and not stopped:
                    stop()
        wait_until(drain_deadline or deadline)
    except KeyboardInterrupt as exc:
        primary_error = exc
        cancelled = True
        try:
            stop()
        except OSError as cleanup_error:
            exc.add_note(f"Process termination cleanup: {cleanup_error}")
        try:
            wait_until(drain_deadline)
        except (OSError, subprocess.TimeoutExpired) as cleanup_error:
            exc.add_note(f"Process wait cleanup: {cleanup_error}")
        drain_incomplete = proc.returncode is None or (selector is not None and bool(selector.get_map()))
    except BaseException as exc:
        primary_error = exc
        # Cleanup must not replace the original error or enter Popen.__exit__'s
        # unbounded wait. Unconfirmed termination remains caller uncertainty.
        try:
            stop()
        except OSError as cleanup_error:
            exc.add_note(f"Process termination cleanup: {cleanup_error}")
        try:
            wait_until(drain_deadline)
        except (OSError, subprocess.TimeoutExpired) as cleanup_error:
            exc.add_note(f"Process wait cleanup: {cleanup_error}")
        raise
    finally:
        close_errors = []
        for name, resource in (("selector", selector), ("stdout", proc.stdout), ("stderr", proc.stderr)):
            if resource is not None:
                try:
                    resource.close()
                except OSError as exc:
                    close_errors.append((name, exc))
        if close_errors:
            error = primary_error or close_errors[0][1]
            for name, exc in close_errors:
                error.add_note(f"Process {name} cleanup: {exc}")
            if primary_error is None:
                raise error
    return {"exitCode": proc.returncode, "stdout": bytes(captures[0]),
            "stderr": bytes(captures[1]), "timedOut": timed_out,
            "stdoutTruncated": truncated[0], "stderrTruncated": truncated[1], "drainIncomplete": drain_incomplete,
            "cancelled": cancelled, "cleanupDiagnostics": list(getattr(primary_error, "__notes__", ()))}


class NativeTools:
    """Select a tool environment explicitly; never discover it during core checks."""

    def __init__(self, python, *, output=None, timeout=120, capture_bytes=8 << 20, secret_values=()):
        # Resolving a virtualenv's interpreter symlink loses that environment.
        selected = Path(python).absolute()
        if not selected.is_file():
            raise FileNotFoundError(selected)
        self.python = str(selected)
        self.output = Path(output or tempfile.mkdtemp(prefix="ddk-native-")).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.capture_bytes = capture_bytes
        self.redaction = SecretRedaction(secret_values)

    def invoke(self, action, request):
        folder = Path(tempfile.mkdtemp(prefix=action + "-", dir=self.output))
        request_path = folder / "request.json"
        request_ref = write_json(request_path, self.redaction.data(request) if self.redaction else request)
        environment = {key: value for key, value in os.environ.items() if value not in self.redaction.values}
        environment.update(PYTHONDONTWRITEBYTECODE="1", DLT_TELEMETRY_ENABLED="false", RUNTIME__DLTHUB_TELEMETRY="false")
        # Locate this exact adapter from either an installed tree or checkout.
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        try:
            with request_transport(folder, request, request_path, self.redaction) as transport_path:
                result = run_bounded(
                    [self.python, "-m", "ddk.adapters.native_worker", action,
                     str(transport_path), str(folder)],
                    timeout=self.timeout, limit=self.capture_bytes, env=environment,
                )
            (folder / "stderr.log").write_bytes(self.redaction.captured(result.pop("stderr")))
            stdout = result.pop("stdout")
            (folder / "stdout.json").write_bytes(self.redaction.captured(stdout))
            if result["cancelled"]:
                response = {"status": "error", "error": {"code": "DOCSPEC-CANCELLED",
                            "message": "Caller cancelled the native request"}}
            elif result["timedOut"] or result["stdoutTruncated"] or result["drainIncomplete"]:
                response = {"status": "error", "reason": "Native call did not return a complete bounded result"}
            else:
                response = parse_json(stdout)
                if not isinstance(response, dict):
                    raise ValueError("Native worker returned a non-object")
                if result["exitCode"] and response.get("status") != "error":
                    response = {"status": "error", "reason": "Native worker crashed"}
                if result["stderrTruncated"]:
                    response["nativeOutcome"] = response.get("status")
                    response.update(status="error", reason="Native diagnostic capture exceeded its admitted limit")
            response["transport"] = result
            response["limits"] = {"timeoutSeconds": self.timeout, "captureBytes": self.capture_bytes}
        except (OSError, ValueError, ResourceLimit, subprocess.TimeoutExpired) as exc:
            response = {"status": "error", "reason": str(exc)}
            if notes := getattr(exc, "__notes__", None):
                response["cleanupDiagnostics"] = list(notes)
        if self.redaction:
            changed = _sanitize_artifacts(folder, self.redaction)
            response = _public_response(response, self.redaction, changed)
            response["redaction"] = {"kind": "designated-parameters", "nativeEvidence": "redacted-view"}
        response["request"] = request_ref
        response["receipt"] = write_json(folder / "receipt.json", response)
        return response
