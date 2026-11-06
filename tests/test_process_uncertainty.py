"""A started child is not proof of completion after transport failure."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from ddk.adapters import native
from ddk.adapters.docspec import DocSpecAdapter
from ddk.documents import validate_document
from ddk.execution import _record
from ddk.results import ReportBuilder


@pytest.mark.parametrize("mode", ("pipe", "selector", "wait", "close", "interrupt_close"))
@pytest.mark.parametrize("managed", (False, True))
def test_started_child_transport_failure_preserves_uncertainty(tmp_path, monkeypatch, mode, managed):
    marker = tmp_path / "started.json"
    child = tmp_path / "native-child"
    child.write_text(
        f"#!{sys.executable}\n"
        "import json,os,time\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(json.dumps({{'pid':os.getpid()}}))\n"
        "print('READY',flush=True)\n"
        "time.sleep(20)\n"
    )
    child.chmod(0o755)
    real_popen = subprocess.Popen
    children = []

    class ObservedProcess(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            children.append(self)
            ready_by = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < ready_by:
                time.sleep(0.005)
            assert marker.exists(), "The transport fault needs an actually started child"

        def __exit__(self, *args):
            raise AssertionError("Process cleanup entered an unbounded context-manager wait")

        def wait(self, timeout=None):
            assert timeout is not None, "Every process wait needs a finite bound"
            if mode == "wait":
                raise subprocess.TimeoutExpired(self.args, timeout)
            return super().wait(timeout=timeout)

    monkeypatch.setattr(native.subprocess, "Popen", ObservedProcess)
    if mode == "selector":
        def unavailable_selector():
            deadline = time.monotonic() + 1
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            assert marker.exists(), "The child must have actually started"
            raise PermissionError("injected selector setup failure after child startup")
        monkeypatch.setattr(native.selectors, "DefaultSelector", unavailable_selector)
    elif mode in {"pipe", "close", "interrupt_close"}:
        original_read = os.read
        def unreadable_pipe(fd, size):
            data = original_read(fd, size)
            if data == b"READY\n":
                if mode == "interrupt_close":
                    raise KeyboardInterrupt
                raise PermissionError("injected pipe failure after child startup")
            return data
        monkeypatch.setattr(native.os, "read", unreadable_pipe)
        if mode in {"close", "interrupt_close"}:
            real_selector = native.selectors.DefaultSelector
            class FailedCloseSelector(real_selector):
                def close(self):
                    super().close()
                    raise OSError("injected selector close failure")
            monkeypatch.setattr(native.selectors, "DefaultSelector", FailedCloseSelector)

    runtime = DocSpecAdapter(child, {"compute_threads": 1}, timeout=0.2,
                             evidence_dir=tmp_path / "evidence")
    started = time.monotonic()
    try:
        if managed:
            request = {"action": "prepare_update",
                       "update": {"dataset": "observed", "operation": "same-original-id"}}
            response = runtime.managed(tmp_path, request)
        else:
            request = {"scratch": str(tmp_path / "scratch"), "inputs": [], "steps": [],
                       "outputs": [], "queries": [{"name": "answer", "sql": "SELECT 1"}]}
            response = runtime.execute(request)
        assert time.monotonic() - started < 4
        assert json.loads(marker.read_text())["pid"] == children[0].pid
        assert children[0].stdout.closed and children[0].stderr.closed
        if mode == "interrupt_close":
            assert response["error"]["code"] == "DOCSPEC-DIAGNOSTIC-LIMIT"
            assert response["receipt"]["nativeError"]["code"] == "DOCSPEC-CANCELLED"
            assert any("injected selector close failure" in note
                       for note in response["receipt"]["cleanupDiagnostics"])
        else:
            assert response["error"]["code"] == "DOCSPEC-IO"
            assert "exitCode" not in response["receipt"]
        if mode == "close":
            assert response["error"]["message"] == "injected pipe failure after child startup"
            assert any("injected selector close failure" in note
                       for note in response["error"]["cleanupDiagnostics"])
        assert response["receipt"]["nativeOutcome"] == response["operation"]["execution"] == "unknown"
        assert response["operation"]["outputs"] == []
        retained = json.loads(Path(response["evidence"]["path"]).read_text())
        if mode != "interrupt_close":
            assert "exitCode" not in retained
        assert json.loads(Path(retained["request"]["path"]).read_text()) == request
        group = "runtime.managed" if managed else "runtime.job"
        builder = ReportBuilder("urn:ddk:test:transport-loss", required_groups=(group,))
        _record(builder, group, "operation", response)
        report = builder.build(operations=[response["operation"]])
        assert not validate_document(report)
        assert report["decision"] == "error"
        assert report["checks"][0]["status"] == "not_run"
        if managed:
            assert response["operation"]["operationId"] == "same-original-id"
            assert retained["operationContext"]["dataset"] == "observed"
        else:
            assert response["operation"]["reconciliation"] == "unsupported"
    finally:
        # The forced wait failure models uncertain observation. This test owns
        # the real child and explicitly reaps it after checking the caller.
        for process in children:
            real_popen.wait(process, timeout=2)
