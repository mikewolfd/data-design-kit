"""Pull-based exact local DocSpec reads; no quality or lifecycle decisions.

Batches are provisional until ``finish()`` verifies pipe EOF, child success and
the native receipt. Limits bound encoded reads/messages and observed decoded
batches, not aggregate process RAM or Arrow's allocations before decode returns.
The pinned read-version command uses threads and must not daemonize. Standalone
sessions own their process group; inherited-group sessions stop/reap the direct
child and leave whole-group cancellation to the existing outer worker owner.
"""

from dataclasses import dataclass
from copy import deepcopy
from hashlib import sha256
import math
import os
from pathlib import Path
import selectors
import signal
import stat
import struct
import subprocess
import tempfile
import threading
from time import monotonic
from uuid import UUID

from ddk.documents import ResourceLimit, parse_json
from .docspec import RUNTIME, _binary_identity, _native_read, _version_reference
from .docspec_schema import RECURSIVE_PROFILE, observed_source_schema, source_arrow_schema
from .native import write_json


class NativeStreamError(RuntimeError):
    """An incomplete native observation, never a failed business-data rule."""

    status = "unknown"

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StreamLimits:
    max_read_bytes: int = 8 << 20
    max_message_bytes: int = 16 << 20
    max_metadata_bytes: int = 2 << 20
    max_batch_bytes: int = 8 << 20
    max_stderr_bytes: int = 64 << 10
    max_input_bytes: int | None = None
    timeout: float = 60
    cleanup_timeout: float = 1

    def __post_init__(self):
        for name in ("max_read_bytes", "max_message_bytes", "max_metadata_bytes", "max_batch_bytes", "max_stderr_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_input_bytes is not None and (type(self.max_input_bytes) is not int or self.max_input_bytes <= 0):
            raise ValueError("max_input_bytes must be absent or a positive integer")
        for value in (self.timeout, self.cleanup_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Timeouts must be finite and positive")


def _arrow_types(pa):
    return {"Boolean": pa.bool_(), "Int8": pa.int8(), "Int16": pa.int16(), "Int32": pa.int32(),
            "Int64": pa.int64(), "Float32": pa.float32(), "Float64": pa.float64(),
            "Utf8": pa.string(), "LargeUtf8": pa.large_string(), "Utf8View": pa.string_view(),
            "Binary": pa.binary(), "LargeBinary": pa.large_binary(), "BinaryView": pa.binary_view(),
            "Date32": pa.date32(), "Date64": pa.date64()}


class _MessageInput:
    """Give Arrow one standard IPC frame with bounded file-like reads.

    Only the standard length prefix is inspected here. Arrow owns message/body
    parsing; its requested body read must fit before bytes are acquired.
    """

    closed = False
    mode = "rb"

    def __init__(self, session, prefix):
        self.session, self.prefix = session, prefix
        self.remaining = session.limits.max_message_bytes

    def read(self, size):
        if type(size) is not int or size < 0 or size > self.remaining or size > self.session.limits.max_read_bytes:
            self.session._fail("DOCSPEC-STREAM-CAPACITY", "Encoded IPC read/message exceeds its byte allocation")
        self.remaining -= size
        head, self.prefix = self.prefix[:size], self.prefix[size:]
        return head + self.session._take(size - len(head))

    def readable(self):
        return True


class ExactVersionStream:
    """Context-managed iterator over provisional Arrow batches.

    ``finish()`` requires the consumer to reach StopIteration. It returns the
    existing native result/evidence/mapping plus byte/batch observations, with no
    payload. Closing early cancels the owned read without claiming completion.
    Consumers own batch retention and must not collect an unbounded batch list.
    This helper is deliberately not integrated with the quality evaluator yet.
    """

    def __init__(self, adapter, workspace, version, *, limits=StreamLimits(), cancel_event=None,
                 new_process_group=True):
        self.adapter = adapter
        self.workspace = Path(workspace).resolve(strict=True)
        self.version = deepcopy(version)
        self.reference = _version_reference(self.workspace, self.version)
        self.limits = limits
        self.cancel_event, self.new_process_group = cancel_event, new_process_group
        self.process = self.schema = self.result = None
        self.rows = self.batches = self.input_bytes = self.max_decoded_batch_bytes = 0
        self._digest = sha256()
        self._error = None
        self._eos = self._closed = False
        self._stop = threading.Event()
        self._stderr = bytearray()
        self._stderr_eof = False
        self._stdout = self._monitor = None
        self._transport_complete = False
        self.cleanup_error = None
        self._process_lock = threading.RLock()

    def _fail(self, code, message):
        error = NativeStreamError(code, message)
        if self._error is None:
            self._error = error
        raise self._error

    def _check(self):
        if self._error:
            raise self._error
        if self.cancel_event is not None and self.cancel_event.is_set():
            self._fail("DOCSPEC-STREAM-CANCELLED", "Caller cancelled the exact native read")
        if monotonic() >= self._deadline:
            self._fail("DOCSPEC-STREAM-TIMEOUT", "Exact native read did not finish before its deadline")

    def __enter__(self):
        if self.process is not None or self._closed:
            raise ValueError("A native stream session can be entered only once")
        if self.adapter.redaction:
            raise ValueError("Exact native streaming does not support redacted native evidence")
        if _binary_identity(self.adapter.executable) != self.adapter._executable_stat:
            raise ValueError("Selected DocSpec executable changed after adapter initialization")
        import pyarrow as pa
        self._pa = pa
        self.folder = Path(tempfile.mkdtemp(prefix="stream-version-", dir=self.adapter.evidence_dir))
        self._receipt_path = self.folder / "native-read.json"
        request = self.folder / "request.json"
        native_limits = self.folder / "limits.json"
        write_json(request, {"version": self.reference, "receipt_path": str(self._receipt_path)})
        write_json(native_limits, self.adapter.limits)
        self._deadline = monotonic() + min(self.limits.timeout, self.adapter.timeout)
        try:
            self.process = subprocess.Popen(
                [str(self.adapter.executable), "--limits", str(native_limits), "--workspace", str(self.workspace),
                 "read-version", "--spec", str(request)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=self.new_process_group, bufsize=0,
            )
            os.set_blocking(self.process.stdout.fileno(), False)
            self._stdout = selectors.DefaultSelector()
            self._stdout.register(self.process.stdout, selectors.EVENT_READ)
            self._monitor = threading.Thread(target=self._watch, name="ddk-read-diagnostics", daemon=True)
            self._monitor.start()
            message = self._message()
            if message is None or message.type != "schema":
                self._fail("DOCSPEC-STREAM-SCHEMA", "The native stream must start with an Arrow schema")
            try:
                self.schema = pa.ipc.read_schema(message)
            except (pa.ArrowException, ValueError) as exc:
                self._fail("DOCSPEC-STREAM-SCHEMA", f"Native Arrow schema could not be decoded: {exc}")
            if self.adapter.native_mapping_profile == RECURSIVE_PROFILE:
                try:
                    observed_source_schema(self.schema, pa)
                except (ValueError, UnicodeError) as exc:
                    self._fail("DOCSPEC-STREAM-SCHEMA", str(exc))
                return self
            ids = []
            supported_types = tuple(_arrow_types(pa).values())
            for field in self.schema:
                if field.type not in supported_types:
                    self._fail("DOCSPEC-STREAM-SCHEMA", "Exact native mapping supports only the existing primitive profile")
                try:
                    value = int((field.metadata or {})[b"PARQUET:field_id"])
                except (KeyError, ValueError):
                    self._fail("DOCSPEC-STREAM-SCHEMA", "An observed Arrow field lacks its exact native field ID")
                ids.append(value)
            if (any(not 0 < value < 1 << 31 for value in ids) or len(set(ids)) != len(ids)
                    or len(set(self.schema.names)) != len(self.schema.names)):
                self._fail("DOCSPEC-STREAM-SCHEMA", "Observed native field names/IDs must be distinct and valid")
            return self
        except NativeStreamError:
            self.close()
            raise
        except Exception as exc:
            try:
                self._fail("DOCSPEC-STREAM-SETUP", f"Native stream initialization failed: {exc}")
            finally:
                self.close()
        except BaseException:
            try:
                self.close()
            except NativeStreamError:
                pass  # Preserve the caller's interruption after closing resources.
            raise

    def _kill(self):
        # Reaping and signalling share ownership synchronization: the monitor
        # cannot release the leader's PID between this check and group signal.
        with self._process_lock:
            self._kill_owned()

    def _poll(self):
        with self._process_lock:
            return self.process.poll()

    def _wait(self, timeout=None):
        with self._process_lock:
            return self.process.wait(timeout=timeout)

    def _kill_owned(self):
        # A recorded return code means Popen already reaped this child. Its
        # former group ID must not be signalled, even if buffered stdout remains
        # unread. Do not poll here: an unreaped leader still anchors its group.
        if self._transport_complete or self.process.returncode is not None:
            return
        try:
            if self.new_process_group:
                os.killpg(self.process.pid, signal.SIGKILL)
            elif self._poll() is None:
                self.process.kill()
        except ProcessLookupError:
            pass
        except PermissionError:
            # Some hosts refuse signalling an already-empty process group.
            # Always reap/stop our direct child; never signal the outer group.
            if self._poll() is None:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass

    def _watch(self):
        selector = None
        ready = False
        try:
            selector = selectors.DefaultSelector()
            os.set_blocking(self.process.stderr.fileno(), False)
            selector.register(self.process.stderr, selectors.EVENT_READ)
            ready = True
            while not self._stop.is_set():
                self._check()
                if self._stderr_eof:
                    if self._poll() is not None:
                        return
                    self._stop.wait(0.02)
                    continue
                for key, _ in selector.select(0.02):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        self._stderr_eof = True
                        selector.unregister(key.fileobj)
                        continue
                    remaining = self.limits.max_stderr_bytes - len(self._stderr)
                    self._stderr.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        self._fail("DOCSPEC-STREAM-DIAGNOSTICS", "Native stderr exceeded its finite capture allocation")
        except NativeStreamError:
            self._kill()
        except Exception as exc:
            if not self._stop.is_set():
                self._error = self._error or NativeStreamError(
                    "DOCSPEC-STREAM-DIAGNOSTICS" if ready else "DOCSPEC-STREAM-MONITOR",
                    f"Native diagnostic monitor {'capture' if ready else 'initialization'} failed: {exc}",
                )
                self._kill()
        finally:
            if selector is not None:
                selector.close()

    def _take(self, size, *, allow_eof=False):
        if size > self.limits.max_read_bytes:
            self._fail("DOCSPEC-STREAM-CAPACITY", "Encoded IPC read exceeds its byte allocation")
        data = bytearray()
        while len(data) < size:
            self._check()
            if not self._stdout.select(0.02):
                continue
            try:
                chunk = os.read(self.process.stdout.fileno(), min(size - len(data), 65536))
            except BlockingIOError:
                continue
            if not chunk:
                if allow_eof and not data:
                    return b""
                self._fail("DOCSPEC-STREAM-TRUNCATED", "Native pipe ended before a complete IPC message/EOS")
            self.input_bytes += len(chunk)
            if self.limits.max_input_bytes is not None and self.input_bytes > self.limits.max_input_bytes:
                self._fail("DOCSPEC-STREAM-CAPACITY", "Complete native input exceeds its separate input-byte allocation")
            self._digest.update(chunk)
            data.extend(chunk)
        return bytes(data)

    def _message(self):
        prefix = self._take(4)
        length, = struct.unpack("<I", prefix)
        if length == 0xFFFFFFFF:
            extra = self._take(4)
            prefix += extra
            length, = struct.unpack("<I", extra)
        if length == 0:
            self._eos = True
            return None
        if length > self.limits.max_metadata_bytes or length + len(prefix) > self.limits.max_message_bytes:
            self._fail("DOCSPEC-STREAM-CAPACITY", "Arrow IPC metadata/message exceeds its byte allocation")
        try:
            return self._pa.ipc.read_message(_MessageInput(self, prefix))
        except NativeStreamError:
            raise
        except (self._pa.ArrowException, OSError, ValueError) as exc:
            self._fail("DOCSPEC-STREAM-INVALID", f"Invalid or incomplete Arrow IPC message: {exc}")

    def __iter__(self):
        return self

    def __next__(self):
        if self.process is None or self._closed:
            raise ValueError("Enter an open native stream before consuming batches")
        self._check()
        if self._eos:
            raise StopIteration
        message = self._message()
        if message is None:
            raise StopIteration
        if message.type != "record batch":
            self._fail("DOCSPEC-STREAM-SCHEMA", "Only one schema and record batches from the selected profile are supported")
        try:
            batch = self._pa.ipc.read_record_batch(message, self.schema)
        except (self._pa.ArrowException, ValueError) as exc:
            self._fail("DOCSPEC-STREAM-INVALID", f"Arrow batch could not be decoded: {exc}")
        size = max(batch.nbytes, batch.get_total_buffer_size())
        if size > self.limits.max_batch_bytes:
            self._fail("DOCSPEC-STREAM-CAPACITY", "Decoded Arrow batch exceeds its byte allocation")
        self.rows += batch.num_rows
        if self.rows > (1 << 64) - 1:
            self._fail("DOCSPEC-STREAM-CAPACITY", "Native row count exceeds its unsigned 64-bit representation")
        self.batches += 1
        self.max_decoded_batch_bytes = max(self.max_decoded_batch_bytes, size)
        return batch

    def _validate_schema(self, receipt):
        pa = self._pa
        if self.adapter.native_mapping_profile == RECURSIVE_PROFILE:
            expected = source_arrow_schema(receipt["schema"], pa)
            if not self.schema.equals(expected, check_metadata=True):
                self._fail("DOCSPEC-STREAM-IDENTITY", "Receipt recursive schema differs from the complete observed stream")
            return _native_read(self.version, receipt, self.adapter.native_mapping_profile)
        types = _arrow_types(pa)
        native_schema = receipt["schema"]
        if any(type(field["nullable"]) is not bool for field in native_schema["fields"]):
            self._fail("DOCSPEC-STREAM-IDENTITY", "Native receipt nullability must be boolean")
        fields = [pa.field(f["name"], types[f["data_type"]], nullable=f["nullable"], metadata=f["metadata"])
                  for f in native_schema["fields"]]
        expected = pa.schema(fields, metadata=native_schema["metadata"])
        if not self.schema.equals(expected, check_metadata=True):
            self._fail("DOCSPEC-STREAM-IDENTITY", "Receipt schema/name/order/type/metadata differs from the observed stream")
        mapping = _native_read(self.version, receipt)
        ids = [field["nativeFieldId"] for field in mapping["fields"]]
        if any(value <= 0 for value in ids) or len(set(ids)) != len(ids):
            self._fail("DOCSPEC-STREAM-IDENTITY", "Native field IDs must be positive and distinct")
        return mapping

    def finish(self):
        if self.result is not None:
            return self.result
        if self.process is None or self._closed or not self._eos:
            self._fail("DOCSPEC-STREAM-INCOMPLETE", "Consume through Arrow EOS before finishing the native observation")
        try:
            # EOS is not process/pipe completion: detect even delayed trailing bytes.
            if self._take(1, allow_eof=True):
                self._fail("DOCSPEC-STREAM-TRAILING", "Native pipe contains bytes after Arrow EOS")
            while self._poll() is None or self._monitor.is_alive():
                self._check()
                self._monitor.join(0.02)
            # Both pipes and the child have completed. Receipt failure is no
            # reason to signal a reaped process group whose ID may be reused.
            self._transport_complete = self._stderr_eof
            self._check()
            if self._wait() != 0:
                self._fail("DOCSPEC-STREAM-EXIT", "Native read process did not exit successfully")
            descriptor = os.open(self._receipt_path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > self.limits.max_metadata_bytes:
                    self._fail("DOCSPEC-STREAM-CAPACITY", "Native receipt is not a bounded regular file")
                data = stream.read(self.limits.max_metadata_bytes + 1)
                if len(data) > self.limits.max_metadata_bytes:
                    self._fail("DOCSPEC-STREAM-CAPACITY", "Native receipt exceeded its byte allocation")
            receipt = parse_json(data)
            if (receipt["version"] != self.reference or type(receipt["rows"]) is not int or receipt["rows"] != self.rows
                    or type(receipt["schema_id"]) is not int or not 0 <= receipt["schema_id"] < 1 << 31
                    or receipt["ipc_sha256"] != self._digest.hexdigest() or type(receipt["read_id"]) is not str
                    or UUID(receipt["read_id"]).int == 0):
                self._fail("DOCSPEC-STREAM-IDENTITY", "Native receipt version/rows/hash/schema identity does not match the complete read")
            mapping = self._validate_schema(receipt)
            result = {"status": "succeeded", "result": receipt, "nativeRead": mapping,
                      "evidence": {"kind": "native-report", "path": str(self._receipt_path),
                                   "sha256": sha256(data).hexdigest(), "tool": RUNTIME},
                      "observations": {"ipcBytes": self.input_bytes, "batches": self.batches,
                                       "rows": self.rows, "maxDecodedBatchBytes": self.max_decoded_batch_bytes}}
        except NativeStreamError:
            raise
        except (OSError, ValueError, KeyError, TypeError, ResourceLimit) as exc:
            self._fail("DOCSPEC-STREAM-RECEIPT", f"Native completion receipt is unavailable or invalid: {exc}")
        finally:
            self.close()
        self.result = result
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        failures = []
        try:
            if self.process is not None:
                if not self._transport_complete:
                    self._kill()
                self._wait(timeout=self.limits.cleanup_timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(str(exc))
        finally:
            self._stop.set()
            # Thread.start may fail, leaving an unstarted Thread object.
            if self._monitor is not None and self._monitor.ident is not None:
                self._monitor.join(self.limits.cleanup_timeout)
                if self._monitor.is_alive():
                    failures.append("Native diagnostic monitor did not stop within cleanup allocation")
            resources = [self._stdout]
            if self.process is not None:
                resources.extend((self.process.stdout, self.process.stderr))
            for resource in resources:
                if resource is not None:
                    try:
                        resource.close()
                    except OSError as exc:
                        failures.append(str(exc))
            if hasattr(self, "folder"):
                try:
                    (self.folder / "stderr.log").write_bytes(self._stderr)
                except OSError as exc:
                    failures.append(str(exc))
        if failures:
            self.cleanup_error = NativeStreamError("DOCSPEC-STREAM-CLEANUP", "; ".join(failures))
            if self._error is None:
                self._error = self.cleanup_error
                raise self.cleanup_error
            self._error.add_note(str(self.cleanup_error))

    def __exit__(self, kind, value, traceback):
        try:
            self.close()
        except NativeStreamError as exc:
            if value is None:
                raise
            value.add_note(str(exc))
