"""Exercise host termination and SDK timeouts with harmless native stand-ins."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from ddk.adapters import docspec


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process-group placement")


HOST = '''
import json, os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from ddk.adapters.docspec import DocSpecAdapter, native_version
config = json.loads(pathlib.Path(sys.argv[2]).read_bytes())
options = {"timeout": config["timeout"], "evidence_dir": config["evidence"]}
if "new_process_group" in config:
    options["new_process_group"] = config["new_process_group"]
adapter = DocSpecAdapter(config["binary"], {}, **options)
workspace = pathlib.Path(config["workspace"])
if config["mode"] == "managed":
    response = adapter.managed_job(workspace, {
        "action": "inspect", "dataset": "archive", "operation": "original",
    })
else:
    version = native_version(workspace, {
        "dataset": "archive", "version": "original",
        "manifest": {"owner": "archive", "path": str(workspace / "manifest"),
                     "digest": "a" * 64, "bytes": 1},
    })
    read_options = ({"new_process_group": config["read_group"]}
                    if "read_group" in config else {})
    response = adapter.read_version(workspace, version, **read_options)
pathlib.Path(config["result"]).write_text(json.dumps({
    "response": response, "hostGroup": os.getpgrp(),
}))
'''


def _start_host(tmp_path, mode, *, placement=None, timeout=30, read_group=None):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ready = tmp_path / "native-ready.json"
    binary = tmp_path / "native-stand-in"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, time\n"
        f"target = pathlib.Path({str(ready)!r})\n"
        "temporary = target.with_suffix('.partial')\n"
        "temporary.write_text(json.dumps({'pid': os.getpid(), 'group': os.getpgrp()}))\n"
        "temporary.replace(target)\n"
        "time.sleep(60)\n"
    )
    binary.chmod(0o755)
    result = tmp_path / "result.json"
    config = {
        "mode": mode, "timeout": timeout, "binary": str(binary),
        "workspace": str(workspace), "evidence": str(tmp_path / "evidence"),
        "result": str(result),
    }
    if placement is not None:
        config["new_process_group"] = placement
    if read_group is not None:
        config["read_group"] = read_group
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    script = tmp_path / "host.py"
    script.write_text(HOST)
    # The child uses the same source or installed package as this test. -I
    # excludes ambient PYTHONPATH; no test checkout source is discovered.
    host = subprocess.Popen(
        [sys.executable, "-I", "-B", str(script),
         str(Path(docspec.__file__).resolve().parents[2]), str(path)],
        start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    return host, ready, result


def _wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate(), "Owned process did not reach the expected state"


def _pid_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _running(pid):
    # Orphan zombies have stopped but depend on the host's PID 1 for reaping.
    status = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                            capture_output=True, text=True, timeout=2)
    if status.returncode == 1 and not status.stdout.strip():
        return False
    assert status.returncode == 0, status.stderr
    return bool(status.stdout.strip()) and not status.stdout.strip().startswith("Z")


def _cleanup(host, ready):
    errors = []
    try:
        if host.poll() is None:
            try:
                os.killpg(host.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except BaseException as error:
        errors.append(error)
    try:
        host.wait(timeout=5)
    except BaseException as error:
        errors.append(error)
    try:
        if ready.exists():
            child = json.loads(ready.read_bytes())
            try:
                if os.getpgid(child["pid"]) == child["group"]:
                    os.kill(child["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
            _wait_for(lambda: not _running(child["pid"]))
    except BaseException as error:
        errors.append(error)
    finally:
        try:
            host.stderr.close()
        except BaseException as error:
            errors.append(error)
    if errors:
        raise BaseExceptionGroup("Owned process cleanup failed", errors)


@pytest.mark.parametrize("mode", ["managed", "read"])
@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGKILL])
def test_host_group_stop_reaches_native_child(tmp_path, mode, stop_signal):
    host, ready, result = _start_host(tmp_path, mode, placement=False)
    try:
        _wait_for(ready.exists)
        child = json.loads(ready.read_bytes())
        assert child["group"] == host.pid
        os.killpg(host.pid, stop_signal)
        assert host.wait(timeout=5) == -stop_signal
        _wait_for(lambda: not _running(child["pid"]))
        assert not result.exists()
        requests = list((tmp_path / "evidence").glob("*/request.json"))
        assert len(requests) == 1
        request = json.loads(requests[0].read_bytes())
        if mode == "managed":
            assert request == {"action": "inspect", "dataset": "archive", "operation": "original"}
        else:
            assert request["version"]["version"] == "original"
    finally:
        _cleanup(host, ready)


@pytest.mark.parametrize("mode", ["managed", "read"])
@pytest.mark.parametrize("placement", [None, False], ids=["standalone-default", "host-owned"])
def test_adapter_timeout_reaps_child_and_preserves_uncertainty(tmp_path, mode, placement):
    host, ready, result = _start_host(tmp_path, mode, placement=placement, timeout=0.5)
    try:
        _, error = host.communicate(timeout=10)
        assert host.returncode == 0, error.decode()
        child = json.loads(ready.read_bytes())
        record = json.loads(result.read_bytes())
        assert child["group"] == (child["pid"] if placement is None else host.pid)
        assert record["hostGroup"] == host.pid
        assert not _pid_exists(child["pid"])
        response = record["response"]
        assert response["status"] == "unknown"
        if mode == "managed":
            assert response["error"]["code"] == "DOCSPEC-TIMEOUT"
            assert response["operation"]["operationId"] == "original"
            assert response["operation"]["execution"] == "unknown"
        else:
            assert response["error"]["code"] == "DOCSPEC-NATIVE-READ-LIMIT"
    finally:
        _cleanup(host, ready)


def test_read_can_explicitly_override_host_process_placement(tmp_path):
    host, ready, result = _start_host(tmp_path, "read", placement=False,
                                      read_group=True, timeout=0.5)
    try:
        _, error = host.communicate(timeout=10)
        assert host.returncode == 0, error.decode()
        child = json.loads(ready.read_bytes())
        assert child["group"] == child["pid"] != host.pid
        assert not _pid_exists(child["pid"])
        assert json.loads(result.read_bytes())["response"]["status"] == "unknown"
    finally:
        _cleanup(host, ready)
