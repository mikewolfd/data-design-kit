"""Tiny independent transport fixtures; no quality or native lifecycle claims."""

from dataclasses import replace
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from time import monotonic, sleep

import pytest

pa = pytest.importorskip("pyarrow")

from ddk.adapters.docspec import DocSpecAdapter, native_version
from ddk.adapters.docspec_stream import ExactVersionStream, NativeStreamError, StreamLimits


LIMITS = StreamLimits(timeout=2)
SCHEMA = {"fields": [{"name": "value", "data_type": "Int64", "nullable": True,
                       "dict_id": 0, "dict_is_ordered": False, "metadata": {"PARQUET:field_id": "7"}}], "metadata": {}}


@pytest.fixture
def producer(tmp_path):
    def make(mode="valid", *, values=(11, None, -4), width=None, batches=2):
        field = pa.field("value", pa.int64() if width is None else pa.string(),
                         metadata={b"PARQUET:field_id": b"7"})
        schema = pa.schema([field])
        sink = io.BytesIO()
        with pa.ipc.new_stream(sink, schema) as writer:
            for _ in range(batches):
                writer.write_batch(pa.record_batch([pa.array(values, type=field.type)], schema=schema))
        payload = sink.getvalue()
        folder = tmp_path / f"producer-{len(tuple(tmp_path.iterdir()))}"
        folder.mkdir()
        executable = folder / "producer"
        native_schema = json.loads(json.dumps(SCHEMA))
        if width is not None:
            native_schema["fields"][0]["data_type"] = "Utf8"
        body = f"""#!{sys.executable}
import hashlib, json, os, pathlib, subprocess, sys, time
request=json.loads(pathlib.Path(sys.argv[sys.argv.index('--spec')+1]).read_text())
payload={payload!r}
mode={mode!r}
if mode=='no-output': time.sleep(20)
if mode=='stderr-closed':
 os.close(2)
 time.sleep(20)
if mode=='stderr-overflow': os.write(2,b'x'*100000)
if mode=='truncated': payload=payload[:-12]
if mode=='missing-eos': payload=payload[:-8]
os.write(1,payload)
if mode=='late-trailing':
 time.sleep(0.06)
 os.write(1,b'trailing')
if mode=='late-receipt':
 os.close(1)
 time.sleep(0.08)
receipt={{'read_id':'acde0000-0000-4000-8000-000000000001','version':request['version'],
         'schema_id':3,'schema':{native_schema!r},'rows':{len(values)*batches},'ipc_sha256':hashlib.sha256(payload).hexdigest()}}
if mode=='bad-rows': receipt['rows']+=1
if mode=='bool-rows': receipt['rows']=True
if mode=='bad-hash': receipt['ipc_sha256']='0'*64
if mode=='bad-version': receipt['version']['version']='other'
if mode=='bad-schema-id': receipt['schema_id']='3'
if mode=='bad-name': receipt['schema']['fields'][0]['name']='other'
if mode=='bad-type': receipt['schema']['fields'][0]['data_type']='Int32'
if mode=='bad-nullability': receipt['schema']['fields'][0]['nullable']=False
if mode=='bad-field-id': receipt['schema']['fields'][0]['metadata']['PARQUET:field_id']='8'
if mode=='receipt-overflow': receipt['padding']='x'*100000
path=pathlib.Path(request['receipt_path'])
if mode=='receipt-fifo': os.mkfifo(path)
elif mode=='receipt-symlink': path.symlink_to('/dev/null')
elif mode!='missing-receipt': path.write_text(json.dumps(receipt))
if mode=='running-producer': time.sleep(20)
if mode=='exit-fail': sys.exit(3)
if mode=='late-exit':
 os.close(1)
 time.sleep(20)
if mode=='descendant-pipe':
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])
 (path.parent/'descendant.pid').write_text(str(child.pid))
"""
        executable.write_text(body)
        executable.chmod(0o755)
        adapter = DocSpecAdapter(executable, {}, timeout=3, evidence_dir=folder / "evidence")
        workspace = folder / "workspace"
        workspace.mkdir()
        version = native_version(workspace, {"dataset": "records", "version": "candidate",
                    "manifest": {"owner": "records", "path": str(workspace / "manifest.json"), "digest": "a"*64, "bytes": 42}})
        return adapter, workspace, version, payload
    return make


def test_exact_complete_stream_keeps_native_identity_and_counts_without_payload_retention(producer):
    adapter, workspace, version, payload = producer()
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
        count = 0
        for batch in stream:
            assert batch.column(0).to_pylist() == [11, None, -4]
            count += batch.num_rows
            assert stream.result is None
        result = stream.finish()
        assert count == result["result"]["rows"] == 6
        assert result["result"]["ipc_sha256"] == sha256(payload).hexdigest()
        assert result["observations"]["ipcBytes"] == len(payload)
        assert result["nativeRead"]["version"] == version
        assert result["nativeRead"]["fields"] == [{"logicalName": "value", "engineName": "value", "position": 0,
                 "logicalType": "integer", "physicalType": "Int64", "nullable": True, "nativeFieldId": 7}]
        assert "ipc" not in result and not hasattr(stream, "ipc")
        assert stream.finish() is result
    assert stream.process.poll() == 0


def test_pipe_eof_before_receipt_waits_for_native_success(producer):
    adapter, workspace, version, _ = producer("late-receipt")
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
        for _ in stream:
            pass
        result = stream.finish()
    assert result["status"] == "succeeded" and result["result"]["rows"] == 6


def test_successful_finish_and_close_never_signal_the_completed_group(producer, monkeypatch):
    adapter, workspace, version, _ = producer()
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
        for _ in stream:
            pass
        monkeypatch.setattr(stream, "_kill", lambda: pytest.fail("completed native group must not be signalled"))
        assert stream.finish()["status"] == "succeeded"
        stream.close()


def test_one_batch_pause_then_early_close_never_signals_monitor_reaped_child(producer, monkeypatch):
    from ddk.adapters import docspec_stream as module

    adapter, workspace, version, payload = producer()
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
        assert next(stream).column(0).to_pylist() == [11, None, -4]
        # Let the real monitor reap this tiny producer while a complete second
        # batch and EOS remain buffered. The test does not poll/reap the child.
        deadline = monotonic() + 1
        while stream.process.returncode is None and monotonic() < deadline:
            sleep(0.01)
        assert stream.process.returncode == 0
        assert not stream._eos and not stream._transport_complete
        assert stream.input_bytes < len(payload)
        monkeypatch.setattr(module.os, "killpg", lambda *args: pytest.fail("reaped child group must not be signalled"))
        monkeypatch.setattr(stream.process, "kill", lambda: pytest.fail("reaped child must not be signalled"))
        stream.close()
    assert stream.result is None and stream.rows == 3
    assert stream.process.stdout.closed and stream.process.stderr.closed


def test_early_close_still_stops_and_reaps_an_actual_running_producer(producer, monkeypatch):
    from ddk.adapters import docspec_stream as module

    adapter, workspace, version, _ = producer("running-producer")
    signals, killpg = [], module.os.killpg

    def signal_owned_group(group, selected_signal):
        signals.append(group)
        killpg(group, selected_signal)

    with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
        next(stream)
        assert stream.process.poll() is None
        monkeypatch.setattr(module.os, "killpg", signal_owned_group)
        stream.close()
    assert signals == [stream.process.pid]
    assert stream.process.returncode < 0 and stream.result is None


def test_owned_reaping_cannot_race_between_group_check_and_signal(producer, monkeypatch):
    from ddk.adapters import docspec_stream as module
    import signal

    adapter, workspace, version, _ = producer("running-producer")
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
        next(stream)
        signal_entered, allow_signal, reap_entered = threading.Event(), threading.Event(), threading.Event()
        killpg, poll = module.os.killpg, stream.process.poll
        observed = []

        def paused_signal(group, selected_signal):
            assert group == stream.process.pid
            signal_entered.set()
            assert allow_signal.wait(1)
            killpg(group, selected_signal)

        def observed_poll():
            reap_entered.set()
            return poll()

        monkeypatch.setattr(module.os, "killpg", paused_signal)
        monkeypatch.setattr(stream.process, "poll", observed_poll)
        killer = threading.Thread(target=stream._kill)
        reaper = threading.Thread(target=lambda: observed.append(stream._poll()))
        try:
            killer.start()
            assert signal_entered.wait(1)
            # Termination is real, but the leader remains unreaped while the
            # helper owns its group signal. The monitor uses the same lock.
            os.kill(stream.process.pid, signal.SIGTERM)
            reaper.start()
            assert not reap_entered.wait(0.05)
        finally:
            allow_signal.set()
            killer.join(1)
            if reaper.ident is not None:
                reaper.join(1)
        assert not killer.is_alive() and not reaper.is_alive()
        assert reap_entered.is_set() and observed[0] is not None
        assert stream.process.returncode < 0 and stream.result is None


@pytest.mark.parametrize("mode", ["missing-receipt", "bad-hash", "exit-fail"])
def test_completed_transport_with_invalid_completion_never_signals_reaped_group(producer, monkeypatch, mode):
    adapter, workspace, version, _ = producer(mode)
    with pytest.raises(NativeStreamError) as error:
        with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
            for _ in stream:
                pass
            monkeypatch.setattr(stream, "_kill", lambda: pytest.fail("completed transport must not be signalled"))
            stream.finish()
    assert error.value.status == "unknown"
    assert stream._transport_complete and stream.result is None
    assert stream.process.poll() is not None


def test_empty_candidate_is_a_complete_observed_read(producer):
    adapter, workspace, version, _ = producer(values=())
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
        assert sum(batch.num_rows for batch in stream) == 0
        assert stream.finish()["result"]["rows"] == 0


@pytest.mark.parametrize("mode,code", [
    ("late-trailing", "TRAILING"), ("truncated", "TRUNCATED"), ("missing-eos", "TRUNCATED"),
    ("exit-fail", "EXIT"), ("missing-receipt", "RECEIPT"), ("bad-rows", "IDENTITY"),
    ("bool-rows", "IDENTITY"), ("bad-hash", "IDENTITY"), ("bad-version", "IDENTITY"),
    ("bad-schema-id", "IDENTITY"), ("bad-name", "IDENTITY"), ("bad-type", "IDENTITY"),
    ("bad-nullability", "IDENTITY"), ("bad-field-id", "IDENTITY"),
    ("receipt-overflow", "CAPACITY"), ("receipt-fifo", "CAPACITY"), ("receipt-symlink", "RECEIPT"),
])
def test_incomplete_or_mismatched_reads_never_return_usable_evidence(producer, mode, code):
    adapter, workspace, version, _ = producer(mode)
    limits = replace(LIMITS, max_metadata_bytes=4096)
    with pytest.raises(NativeStreamError) as error:
        with ExactVersionStream(adapter, workspace, version, limits=limits) as stream:
            for _ in stream:
                pass
            stream.finish()
    assert code in error.value.code
    assert error.value.status == "unknown"
    assert stream.result is None and stream.process.poll() is not None


@pytest.mark.parametrize("mode", ["no-output", "late-exit", "stderr-closed"])
def test_deadline_applies_before_schema_and_after_eos_and_stderr_eof(producer, mode):
    adapter, workspace, version, _ = producer(mode)
    started = monotonic()
    with pytest.raises(NativeStreamError, match="deadline"):
        with ExactVersionStream(adapter, workspace, version, limits=replace(LIMITS, timeout=0.3)) as stream:
            for _ in stream:
                pass
            stream.finish()
    assert monotonic() - started < 2


@pytest.mark.parametrize("limit", ["max_read_bytes", "max_message_bytes", "max_metadata_bytes",
                                  "max_batch_bytes", "max_input_bytes"])
def test_separate_encoded_batch_metadata_and_input_capacities(producer, limit):
    adapter, workspace, version, _ = producer()
    with pytest.raises(NativeStreamError) as error:
        with ExactVersionStream(adapter, workspace, version, limits=replace(LIMITS, **{limit: 16})) as stream:
            for _ in stream:
                pass
            stream.finish()
    assert "CAPACITY" in error.value.code


def test_bounded_stderr_failure_remains_operational(producer):
    adapter, workspace, version, _ = producer("stderr-overflow")
    stream = ExactVersionStream(adapter, workspace, version, limits=replace(LIMITS, max_stderr_bytes=100))
    with pytest.raises(NativeStreamError) as error:
        with stream:
            for _ in stream:
                pass
            stream.finish()
    assert "DIAGNOSTICS" in error.value.code
    assert (stream.folder / "stderr.log").stat().st_size == 100


def test_cancel_and_early_close_reap_direct_child_in_inherited_group(producer):
    adapter, workspace, version, _ = producer(batches=1000)
    cancelled = threading.Event()
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS, cancel_event=cancelled,
                            new_process_group=False) as stream:
        assert os.getpgid(stream.process.pid) == os.getpgrp()
        assert next(stream).num_rows == 3
        cancelled.set()
        with pytest.raises(NativeStreamError, match="cancelled"):
            next(stream)
    assert stream.process.poll() is not None and stream.result is None


def test_early_finish_and_early_close_do_not_claim_completion(producer):
    adapter, workspace, version, _ = producer(batches=1000)
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS) as stream:
        next(stream)
        with pytest.raises(NativeStreamError, match="EOS"):
            stream.finish()
    assert stream.process.poll() is not None and stream.result is None


def test_owned_group_with_inherited_descendant_pipe_stops_without_harming_unrelated_group(producer, monkeypatch):
    adapter, workspace, version, _ = producer("descendant-pipe")
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True)
    kills = []
    try:
        with pytest.raises(NativeStreamError, match="deadline"):
            with ExactVersionStream(adapter, workspace, version, limits=replace(LIMITS, timeout=0.5)) as stream:
                original_kill = stream._kill
                def record_owned_cleanup():
                    kills.append(stream.process.pid)
                    original_kill()
                monkeypatch.setattr(stream, "_kill", record_owned_cleanup)
                for _ in stream:
                    pass
                stream.finish()
        assert stream.process.poll() == 0
        assert kills
        assert unrelated.poll() is None
        descendant = int((stream.folder / "descendant.pid").read_text())
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(descendant)], capture_output=True, text=True).stdout.strip()
        assert not state or state.startswith("Z")  # Grandchildren are reaped by their OS parent, not this helper.
    finally:
        unrelated.kill()
        unrelated.wait()


def test_input_size_can_exceed_batch_budget_without_candidate_retention(producer):
    adapter, workspace, version, payload = producer(batches=300)
    with ExactVersionStream(adapter, workspace, version,
                            limits=replace(LIMITS, max_batch_bytes=32, max_input_bytes=len(payload))) as stream:
        batches = sum(1 for _ in stream)
        result = stream.finish()
    assert batches == 300 and result["observations"]["ipcBytes"] > 1000 * 32


@pytest.mark.parametrize("name", ["max_message_bytes", "max_read_bytes"])
def test_large_body_is_rejected_before_acquiring_it(producer, name):
    adapter, workspace, version, _ = producer(values=("x" * 10000,), width=10000, batches=1)
    stream = ExactVersionStream(adapter, workspace, version, limits=replace(LIMITS, **{name: 1024}))
    with pytest.raises(NativeStreamError) as error:
        with stream:
            next(stream)
    assert "CAPACITY" in error.value.code
    assert stream.input_bytes < 1024


def test_deadline_stops_owned_child_while_consumer_pauses(producer):
    adapter, workspace, version, _ = producer(batches=1000)
    with ExactVersionStream(adapter, workspace, version, limits=replace(LIMITS, timeout=0.3)) as stream:
        next(stream)
        sleep(0.4)
        assert stream.process.poll() is not None
        with pytest.raises(NativeStreamError, match="deadline"):
            next(stream)


@pytest.mark.parametrize("fault", ["stdout-selector", "stdout-register", "thread-start",
                                   "monitor-selector", "monitor-register", "monitor-blocking"])
def test_partial_owned_setup_failure_closes_resources_and_reaps_child(producer, monkeypatch, fault):
    from ddk.adapters import docspec_stream as module

    adapter, workspace, version, _ = producer("no-output")
    stream = ExactVersionStream(adapter, workspace, version, limits=LIMITS, new_process_group=False)
    real_selector, real_blocking = module.selectors.DefaultSelector, module.os.set_blocking
    selectors, calls, blocking_calls = [], 0, 0

    class ProbeSelector:
        def __init__(self, delegate, number):
            self.delegate, self.number, self.closed = delegate, number, False

        def register(self, *args):
            if (fault == "stdout-register" and self.number == 1
                    or fault == "monitor-register" and self.number == 2):
                raise OSError("injected selector registration failure")
            return self.delegate.register(*args)

        def close(self):
            self.closed = True
            self.delegate.close()

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    def selector():
        nonlocal calls
        calls += 1
        if fault == "stdout-selector" and calls == 1 or fault == "monitor-selector" and calls == 2:
            raise OSError("injected selector initialization failure")
        result = ProbeSelector(real_selector(), calls)
        selectors.append(result)
        return result

    def blocking(*args):
        nonlocal blocking_calls
        blocking_calls += 1
        if fault == "monitor-blocking" and blocking_calls == 2:
            raise OSError("injected monitor descriptor setup failure")
        return real_blocking(*args)

    monkeypatch.setattr(module.selectors, "DefaultSelector", selector)
    monkeypatch.setattr(module.os, "set_blocking", blocking)
    if fault == "thread-start":
        def cannot_start(thread):
            raise RuntimeError("injected thread start failure")
        monkeypatch.setattr(module.threading.Thread, "start", cannot_start)
    with pytest.raises(NativeStreamError) as error:
        stream.__enter__()
    assert error.value.status == "unknown"
    assert error.value.code == ("DOCSPEC-STREAM-MONITOR" if fault.startswith("monitor") else "DOCSPEC-STREAM-SETUP")
    assert stream.process.poll() is not None
    assert stream.process.stdout.closed and stream.process.stderr.closed
    assert stream._stop.is_set() and all(item.closed for item in selectors)
    assert stream._monitor is None or stream._monitor.ident is None or not stream._monitor.is_alive()


@pytest.mark.parametrize("original_failure", [False, True])
def test_cleanup_wait_timeout_closes_resources_and_preserves_original_unknown(producer, monkeypatch, original_failure):
    adapter, workspace, version, _ = producer(batches=1000)
    cancelled = threading.Event()
    stream = ExactVersionStream(adapter, workspace, version,
                                limits=replace(LIMITS, cleanup_timeout=1e-9), cancel_event=cancelled)
    real_wait = None

    def wait_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("injected child wait", stream.limits.cleanup_timeout)

    try:
        with pytest.raises(NativeStreamError) as error:
            with stream:
                next(stream)
                real_wait = stream.process.wait
                monkeypatch.setattr(stream.process, "wait", wait_timeout)
                if original_failure:
                    cancelled.set()
                    next(stream)
        assert error.value.status == "unknown"
        assert error.value.code == ("DOCSPEC-STREAM-CANCELLED" if original_failure else "DOCSPEC-STREAM-CLEANUP")
        assert stream.cleanup_error.code == "DOCSPEC-STREAM-CLEANUP"
        assert stream._stop.is_set()
        assert stream.process.stdout.closed and stream.process.stderr.closed
        assert stream._stdout.get_map() is None and stream.result is None
    finally:
        # The deliberately injected wait failure must not leak a fixture process.
        if real_wait is not None:
            real_wait(timeout=2)
            stream._monitor.join(2)


def test_actual_tiny_exact_native_read_uses_unchanged_protocol(tmp_path):
    binary = os.environ.get("DDK_STREAM_NATIVE_BINARY")
    if not binary:
        pytest.skip("Set DDK_STREAM_NATIVE_BINARY to an unchanged qualified DocSpec executable")
    import pyarrow.parquet as pq
    settings = {"compute_threads": 1, "memory_bytes": 128 << 20, "scratch_bytes": 32 << 20,
                "batch_rows": 2, "max_batch_bytes": 1 << 20, "max_metadata_bytes": 2 << 20}
    adapter = DocSpecAdapter(binary, settings, evidence_dir=tmp_path / "evidence")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data, spec, limits = (tmp_path / name for name in ("rows.parquet", "build.json", "limits.json"))
    pq.write_table(pa.table({"value": pa.array([11, -4], pa.int64())}), data)
    native_digest = json.loads(subprocess.check_output([binary, "hash", "--input", str(data)]))["digest"]
    limits.write_text(json.dumps(settings))
    spec.write_text(json.dumps({"dataset": "records", "operation": "candidate", "input": str(data),
                               "expected_digest": native_digest, "sql": "SELECT value FROM input", "definition": "one"}))
    release = json.loads(subprocess.check_output([binary, "--workspace", str(workspace), "--limits", str(limits),
                                                 "run", "--spec", str(spec)]))
    version = native_version(workspace, {"dataset": "records", "version": "candidate", "manifest": release["manifest"]})
    with ExactVersionStream(adapter, workspace, version, limits=LIMITS, new_process_group=False) as stream:
        values = [value for batch in stream for value in batch.column(0).to_pylist()]
        result = stream.finish()
    assert values == [11, -4]
    assert result["result"]["rows"] == 2
    assert result["nativeRead"]["fields"][0]["nativeFieldId"] == 1


@pytest.mark.parametrize("field,value", [("max_read_bytes", 0), ("max_batch_bytes", True),
                                       ("max_input_bytes", -1), ("timeout", float("inf")), ("cleanup_timeout", 0)])
def test_limits_require_explicit_finite_positive_allocations(field, value):
    with pytest.raises(ValueError):
        replace(LIMITS, **{field: value})
