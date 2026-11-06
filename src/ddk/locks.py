"""Exact input locks and atomic writes."""

from hashlib import sha256
from importlib.metadata import version
import os
from pathlib import Path
import stat
import sys
import tempfile

from .documents import DocumentError, ResourceLimit, json_dumps, read_json, resolve_path, schema_registry, validate_document
from .interfaces import json_equal
from .results import VERSION, ReportBuilder, diagnostic

STANDARDS = {
    "ddk": "0.1",
    "jsonSchema": "2020-12",
    "odcs": "3.2.0@448f7b93329ece7827897d7dd51e827a3e279460",
    "odcsSchemaDialect": "2019-09",
    "odps": "1.1.0@04995037fc003ead1da27f65a40a09eb0664b591",
    "openLineage": "1.55.0@5ec09f180d0857327a58b85531b7447d069abf07",
    "dataContractCliDefinitionSemantics": "34b12923e0366fa4004c2f90644da41769699e0f",
}


def tool_identities():
    resolver = Path(__file__).with_name("definitions.py")
    tools = {
        "ddk": {"version": VERSION},
        "python": {"version": ".".join(map(str, sys.version_info[:3]))},
        "jsonschema": {"version": version("jsonschema")},
        "referencing": {"version": version("referencing")},
        "ddk-local-definition-resolver": {
            "version": "0.1.0",
            "distributionSha256": sha256(resolver.read_bytes()).hexdigest(),
        },
    }
    commit = os.environ.get("DDK_SOURCE_COMMIT")
    digest = os.environ.get("DDK_DISTRIBUTION_SHA256")
    if commit and digest:
        tools["ddk"].update({"commit": commit, "distributionSha256": digest})
    return tools


def _key(entry):
    return (entry["path"], entry["role"], entry.get("selection", ""), entry.get("identity", ""))


def build_lock(inventory, *, tools=None, native_inputs=(), reuse_records=(), extra_files=(), catalog_options=None):
    """Build a lock from admitted bytes and caller-supplied native records."""
    if inventory.root is None:
        raise ValueError("A lock requires a valid root project.")
    identity = inventory.root.value["id"]
    files = [entry.record() for entry in inventory.files]
    files.extend({"path": f"@ddk/{path}", "role": "schema", "sha256": digest}
                 for path, digest in schema_registry()[2].items())
    files.extend(entry.record() if hasattr(entry, "record") else dict(entry) for entry in extra_files)
    keyed = {}
    for entry in files:
        existing = keyed.setdefault(_key(entry), entry)
        if existing != entry:
            raise ValueError(f"Conflicting digests for lock input {entry['path']!r}.")
    lock = {
        "specVersion": "0.1", "kind": "lock",
        "id": f"urn:ddk:lock:{identity.encode().hex()}",
        "version": VERSION,
        "project": identity,
        "files": [keyed[key] for key in sorted(keyed)],
        "tools": {**tool_identities(), **(tools or {})},
        "standards": dict(STANDARDS),
    }
    if native_inputs:
        lock["nativeInputs"] = list(native_inputs)
    if reuse_records:
        lock["reuseRecords"] = list(reuse_records)
    if catalog_options is not None:
        lock["catalogOptions"] = catalog_options
    if issues := validate_document(lock, "lock"):
        raise ValueError(f"Invalid lock at {issues[0].pointer or '/'}: {issues[0].message}")
    return lock


def verify_lock(inventory, lock, *, locked=True, tools=None, native_inputs=(), reuse_records=(),
                extra_files=(), catalog_options=None):
    report = inventory.report
    if lock is None and not locked:
        return False
    path = "<lock>"
    details = []
    if lock is None:
        details.append(diagnostic("LOCK-MISSING", "Locked checking requires an explicit lock.", path=path))
    elif not isinstance(lock, dict):
        path = str(Path(lock))
        report.lock["path"] = path
        try:
            lock = read_json(path, max_bytes=inventory.limits["maxDocumentBytes"],
                             max_nesting=inventory.limits["maxNesting"]).value
        except DocumentError as exc:
            details.append(diagnostic(exc.code, str(exc), path=path, pointer=exc.pointer))
        except FileNotFoundError:
            details.append(diagnostic("LOCK-MISSING", "The explicitly named lock does not exist.", path=path))
        except OSError:
            item = diagnostic("LOCK-UNREADABLE", "The lock could not be read.", path=path)
            report.error(item)
            report.add("DDK-LOCK-002", "core.references", "lock", "not_run", reason=item["message"], diagnostics=[item])
            return False

    if not details:
        issues = validate_document(lock, "lock")
        details.extend(diagnostic(issue.code, issue.message, path=path, pointer=issue.pointer) for issue in issues)
    if not details and inventory.root is None:
        report.add("DDK-LOCK-002", "core.references", "lock", "not_run",
                   reason="The root project did not load.")
        return False
    if not details:
        expected = build_lock(inventory, tools=tools, native_inputs=native_inputs,
                              reuse_records=reuse_records, extra_files=extra_files, catalog_options=catalog_options)
        for key in ("project", "tools", "standards", "nativeInputs", "reuseRecords", "catalogOptions"):
            if expected.get(key) != lock.get(key):
                details.append(diagnostic("LOCK-INPUT-MISMATCH", f"Locked {key} differs from the admitted input.",
                                          path=path, pointer=f"/{key}"))
        actual = {}
        for index, entry in enumerate(lock["files"]):
            key = _key(entry)
            if key in actual:
                details.append(diagnostic("LOCK-ENTRY-DUPLICATE", "Duplicate lock input identity.",
                                          path=path, pointer=f"/files/{index}"))
            actual[key] = entry
        needed = {_key(entry): entry for entry in expected["files"]}
        for key in sorted(actual.keys() | needed.keys()):
            if key not in actual:
                details.append(diagnostic("LOCK-ENTRY-MISSING", "An admitted input is absent from the lock.", path=key[0]))
            elif key not in needed:
                details.append(diagnostic("LOCK-ENTRY-UNEXPECTED", "The lock includes an unadmitted input.", path=key[0]))
            elif actual[key]["sha256"] != needed[key]["sha256"]:
                details.append(diagnostic("LOCK-DIGEST-MISMATCH", "Input bytes differ from the lock.", path=key[0]))
    report.add("DDK-LOCK-002", "core.references", "lock", "failed" if details else "passed", diagnostics=details)
    report.lock["verified"] = not details
    return not details


def evidence_sha256(path, *, max_bytes=1 << 30):
    """Hash a retained local artifact without copying or opening a stream device."""
    digest = sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Execution evidence must be a regular file.")
        if info.st_size > max_bytes:
            raise ResourceLimit("Execution evidence exceeds the configured byte limit.")
        remaining = max_bytes
        while chunk := stream.read(min(remaining + 1, 1 << 20)):
            remaining -= len(chunk)
            if remaining < 0:
                raise ResourceLimit("Execution evidence exceeds the configured byte limit.")
            digest.update(chunk)
    return digest.hexdigest()


def verify_execution_inputs(receipt_path, *, current_inputs=None, expected_tool=None, permitted_roots=(),
                            current_native_reads=None, expected_semantics=None, max_file_bytes=1 << 30):
    """Revalidate captured local input bytes before a caller reuses executed evidence."""
    group = "runtime.inputs"
    report = ReportBuilder("urn:ddk:execution-inputs", (group,))
    report.limits["maxFileBytes"] = max_file_bytes
    receipt_path = Path(receipt_path).resolve()
    roots = (receipt_path.parent, *permitted_roots)
    diagnostics = []

    def mismatch(message, pointer=""):
        diagnostics.append(diagnostic("LOCK-EXECUTION-INPUT-MISMATCH", message, path=receipt_path, pointer=pointer))

    try:
        receipt = read_json(receipt_path).value
        inputs = receipt.get("inputs") if isinstance(receipt, dict) else None
        if not isinstance(inputs, list) or not (inputs or receipt.get("nativeReads")):
            mismatch("The retained receipt does not identify its exact execution inputs.", "/inputs")
        elif receipt.get("status") != "succeeded":
            mismatch("Only a succeeded native receipt can establish reusable execution evidence.", "/status")
        else:
            keys = set()
            for index, item in enumerate(inputs):
                pointer = f"/inputs/{index}"
                if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key]
                                                     for key in ("path", "sha256", "format", "name")):
                    mismatch("An execution input has no exact identity.", pointer)
                    continue
                key = (item["format"], item["name"], item["path"])
                if key in keys:
                    mismatch("The execution receipt repeats an input identity.", pointer)
                    continue
                keys.add(key)
                try:
                    path = resolve_path(receipt_path, item["path"], roots)
                    if evidence_sha256(path, max_bytes=max_file_bytes) != item["sha256"]:
                        mismatch(f"Execution input bytes changed for {item['name']!r}.", pointer)
                except (DocumentError, OSError):
                    mismatch(f"Recorded execution input {item['name']!r} is missing or outside admitted roots.", pointer)
            if current_inputs is not None and sorted(map(json_dumps, inputs)) != sorted(map(json_dumps, current_inputs)):
                mismatch("The admitted current file inventory differs from the retained receipt.", "/inputs")
            if expected_tool is not None and not json_equal(receipt.get("tool"), expected_tool):
                mismatch("The native tool identity differs from the current execution tool.", "/tool")
            if expected_semantics is not None and not json_equal(receipt.get("semantics"), expected_semantics):
                diagnostics.append(diagnostic("EXEC-SEMANTICS-MISMATCH", "The execution semantic profile differs from the admitted profile.",
                                              path=receipt_path, pointer="/semantics"))
            if current_native_reads is not None and not json_equal(receipt.get("nativeReads"), current_native_reads):
                mismatch("The admitted exact native input identities differ from the retained receipt.", "/nativeReads")
            request = receipt.get("request")
            if not isinstance(request, dict) or any(not isinstance(request.get(key), str) or not request[key]
                                                     for key in ("path", "sha256")):
                mismatch("The retained receipt does not identify its effective request bytes.", "/request")
            else:
                try:
                    path = resolve_path(receipt_path, request["path"], roots)
                    if evidence_sha256(path, max_bytes=max_file_bytes) != request["sha256"]:
                        mismatch("The retained request bytes changed.", "/request")
                except (DocumentError, OSError):
                    mismatch("The retained request is missing or outside admitted roots.", "/request")
        if not diagnostics and isinstance(receipt, dict) and receipt.get("nativeReads") and current_native_reads is None:
            report.add("DDK-LOCK-003", group, "execution-inputs", "not_run",
                       reason="Current runtime evidence is required to verify exact native inputs.")
            return report.build()
    except (DocumentError, OSError, ResourceLimit) as exc:
        record = diagnostic("EXEC-RESOURCE-LIMIT" if isinstance(exc, ResourceLimit) else "LOCK-EXECUTION-INPUT-MISMATCH",
                            str(exc), path=receipt_path)
        if isinstance(exc, (OSError, ResourceLimit)):
            report.error(record)
            report.add("DDK-LOCK-003", group, "execution-inputs", "not_run", reason="The input inventory could not be verified.",
                       diagnostics=[record])
            return report.build()
        diagnostics.append(record)
    report.add("DDK-LOCK-003", group, "execution-inputs", "failed" if diagnostics else "passed",
               diagnostics=diagnostics)
    return report.build()


def write_json_atomic(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json_dumps(value) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def lock_project(path, output=None, *, permitted_roots=(), limits=None, required_groups=(), adapter_manifests=()):
    """Check before producing a lock and preserve existing output on failure."""
    from .core import check_inventory, load_project

    inventory = load_project(path, permitted_roots=permitted_roots, limits=limits)
    result = check_inventory(inventory, required_groups=required_groups, adapter_manifests=adapter_manifests)
    if result["decision"] != "passed":
        return result, None
    try:
        lock = build_lock(inventory)
        if output is not None:
            destination = Path(output).resolve()
            if destination in inventory.documents:
                raise ValueError("Lock output would replace an admitted input.")
            write_json_atomic(output, lock)
    except (OSError, ValueError, ResourceLimit) as exc:
        inventory.report.error(diagnostic("LOCK-WRITE-FAILED", f"Could not produce the lock: {exc}", path=output or path))
        return inventory.report.build(), None
    return result, lock
