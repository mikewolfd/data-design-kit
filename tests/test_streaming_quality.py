"""Tiny exact-stream integration; independent metrics, no native build or corpus."""

from hashlib import sha256
from pathlib import Path
import sys

import pytest

pytest.importorskip('duckdb')
pytest.importorskip('datacontract')

from test_docspec_stream import producer
from ddk.adapters import native_quality as quality
from ddk.adapters.native import NativeTools
from ddk.adapters.docspec_stream import NativeStreamError
from ddk.documents import read_json
from ddk.quality import QualityOperationalError, QualityResources


def document(query='SELECT count(*) FROM records', expected=6):
    return {'apiVersion': 'v3.2.0', 'kind': 'DataContract', 'id': 'urn:test:stream-quality',
            'version': '1.0.0', 'status': 'draft', 'schema': [{'name': 'records', 'logicalType': 'object',
                'properties': [{'name': 'value', 'logicalType': 'integer'}],
                'quality': [{'id': 'scalar', 'type': 'sql', 'query': query, 'mustBe': expected}]}]}


def request(producer, mode='valid', *, doc=None, resources=None):
    adapter, workspace, version, payload = producer(mode)
    return {'document': doc or document(), 'target': {'kind': 'native', 'nativeVersion': version['reference'],
        'read': {'executable': str(adapter.executable), 'executableSha256': adapter.tool['distributionSha256'],
                 'workspace': str(workspace), 'limits': {}, 'timeout': 3}},
        'resources': (resources or QualityResources(scratchBytes=32 << 20, readTimeoutSeconds=3)).record()}, version, payload


def evaluate(tmp_path, req):
    folder = tmp_path / 'quality'
    folder.mkdir()
    return quality.evaluate(req, folder), folder


def scalar_check(result):
    return next(check for check in result['checks'] if check.get('qualityId') == 'scalar')


@pytest.mark.parametrize(('sql', 'expected'), [
    ('SELECT count(*) FROM records', 6),
    ('SELECT sum(value) FROM records', 14),
    ('SELECT min(value) FROM records', -4),
    ('SELECT max(value) FROM records', 11),
    ('SELECT count(*) FROM records WHERE value IS NULL', 2),
    ('SELECT count(*) FROM records WHERE value < 0', 2),
])
def test_exact_stream_completed_before_maintained_scalar_metrics(producer, tmp_path, sql, expected):
    req, version, payload = request(producer, doc=document(sql, expected))
    result, folder = evaluate(tmp_path, req)
    assert result['status'] == 'passed', result
    read = result['nativeRead']
    assert read['mapping']['version'] == version
    assert read['observed']['rows'] == read['materialization']['rows'] == 6
    assert read['observed']['ipc_sha256'] == sha256(payload).hexdigest()
    assert read['mapping']['fields'][0]['nativeFieldId'] == 7
    assert read['materialization']['stream']['batches'] == 2
    assert read['decodedBytes'] == 50
    assert not list(folder.glob('.quality-spill-*'))
    assert Path(read['path']).is_file() and Path(result['nativeReport']['path']).is_file()
    native = read_json(result['nativeReport']['path']).value
    raw = next(check for check in native['checks'] if check.get('qualityId') == 'scalar')
    assert raw['diagnostics']['value'] == expected
    manifest = read_json(result['evaluator']['sourceManifest']['path']).value
    assert any(item['path'] == 'ddk/adapters/docspec_stream.py' for item in manifest['files'])
    assert {'ddk/quality.py', 'ddk/documents.py', 'ddk/fixtures.py'} <= {item['path'] for item in manifest['files']}
    assert manifest['dependencies']['sqlglot'] == '30.29.0'
    assert any(item['path'].startswith('sqlglot/') for item in manifest['files'])


@pytest.mark.parametrize('mode', ['bad-hash', 'bad-rows', 'bad-field-id', 'missing-receipt', 'truncated', 'late-trailing', 'exit-fail'])
def test_transport_cannot_run_rules_before_exact_completion(producer, tmp_path, monkeypatch, mode):
    from datacontract.engines.ibis import ibis_check_execute
    monkeypatch.setattr(ibis_check_execute, '_run_model', lambda *a, **kw: pytest.fail('incomplete read must never execute rules'))
    req, _, _ = request(producer, mode)
    with pytest.raises(NativeStreamError):
        evaluate(tmp_path, req)
    assert not list((tmp_path / 'quality').glob('.quality-spill-*'))
    assert not (tmp_path / 'quality' / 'native-report.json').exists()


@pytest.mark.parametrize('sql', [
    'SELECT value FROM records',
    'SELECT count(*), sum(value) FROM records',
    "SELECT 'huge'::VARCHAR FROM records LIMIT 1",
    "SELECT repeat('x', 1000000000)",
    'SELECT count(*) FROM records; DELETE FROM records',
    'DELETE FROM records RETURNING value',
    'UPDATE records SET value = 0 RETURNING value',
    'CREATE TABLE other AS SELECT * FROM records',
    "SET memory_limit = '4GB'",
    "SELECT count(*) FROM read_parquet('/outside/exact/binding.parquet')",
    "SELECT nextval('sequence')",
    "SELECT count(*) FROM duckdb_settings()",
    'WITH effect AS (DELETE FROM records RETURNING *) SELECT count(*) FROM records',
    'SELECT count(*) FROM records USING SAMPLE 10 PERCENT',
])
def test_custom_sql_cannot_escape_admission_or_use_first_row(producer, tmp_path, sql):
    req, _, _ = request(producer, doc=document(sql))
    result, _ = evaluate(tmp_path, req)
    # DCC's maintained compiler already refuses statement effects as a failed
    # definition. Queries admitted by that compiler meet this stricter result
    # boundary and remain explicitly not_run when unsupported.
    compiled_refusal = sql.startswith(('DELETE', 'UPDATE', 'CREATE', 'SET')) or '; DELETE' in sql
    status = 'failed' if compiled_refusal else 'not_run'
    assert result['status'] == status, result
    assert scalar_check(result)['status'] == status
    issue = result['operational']['queryIssues']
    assert not issue if compiled_refusal else len(issue) == 1 and issue[0]['code'] in ('QUALITY-SQL-UNSUPPORTED', 'QUALITY-SQL-RESULT-SHAPE')
    raw = read_json(result['nativeReport']['path']).value
    assert next(c for c in raw['checks'] if c.get('qualityId') == 'scalar')['result'] == 'failed'
    assert result['nativeRead']['observed']['rows'] == 6


def test_sql_and_raw_fallback_use_one_bounded_result_and_keep_table_unchanged():
    import duckdb
    con = duckdb.connect()
    try:
        con.execute('CREATE TEMP TABLE records AS SELECT 1 AS value UNION ALL SELECT 2')
        backend = quality._ScalarBackend(None, con, 'records')
        for sql in ('SELECT value FROM records', 'SELECT 1; DELETE FROM records', "SELECT 'x'::VARCHAR"):
            first = backend.sql(sql) if sql == 'SELECT value FROM records' else None
            for fetch in (lambda: (first or backend.sql(sql)).execute(), lambda: backend.raw_sql(sql).fetchone()):
                with pytest.raises(quality._ScalarUnavailable) as exc:
                    fetch()
                assert exc.value.status == 'not_run'
        assert con.execute('SELECT count(*) FROM records').fetchone() == (2,)
        assert len(backend.queries) == 3
    finally:
        con.close()


def test_separate_decoded_input_capacity_failure_is_not_data_violation(producer, tmp_path):
    req, _, _ = request(producer, resources=QualityResources(maxDecodedInputBytes=30, readTimeoutSeconds=3))
    with pytest.raises(QualityOperationalError) as exc:
        evaluate(tmp_path, req)
    assert exc.value.code == 'QUALITY-DECODED-INPUT-LIMIT'
    assert not list((tmp_path / 'quality').glob('.quality-spill-*'))


def test_worker_preserves_transport_resource_uncertainty(producer, tmp_path):
    req, _, _ = request(producer, 'bad-hash')
    result = NativeTools(sys.executable, output=tmp_path / 'worker', timeout=15).invoke('quality', req)
    assert result['status'] == 'unknown', result
    assert result['operationalError']['type'] == 'NativeStreamError'
    assert result['operationalError']['code']


def test_legacy_and_explicit_limits_are_distinct_and_unambiguous():
    old, mode = QualityResources.from_request({'maxBytes': 1024})
    assert mode == 'legacy-maxBytes'
    assert old.maxInputBytes == old.maxDecodedInputBytes == old.engineMemoryBytes == 1024
    explicit, mode = QualityResources.from_request({'resources': {'engineMemoryBytes': 1024, 'scratchBytes': 4096}})
    assert mode == 'separate-allocations' and explicit.maxInputBytes is None
    for value in ({'maxBytes': True}, {'resources': {'scratchBytes': -1}}, {'resources': {'readTimeoutSeconds': float('inf')}},
                  {'resources': {}, 'maxBytes': 1024}, {'resources': {'bogus': 1}}):
        with pytest.raises(ValueError):
            QualityResources.from_request(value)


def test_real_data_violation_stays_failed_with_measured_native_value(producer, tmp_path):
    req, _, _ = request(producer, doc=document(expected=0))
    result, _ = evaluate(tmp_path, req)
    assert result['status'] == scalar_check(result)['status'] == 'failed'
    assert next(c for c in result['checks'] if c['id'] == 'ddk:quality-execution-complete')['status'] == 'passed'
    raw = read_json(result['nativeReport']['path']).value
    check = next(c for c in raw['checks'] if c.get('qualityId') == 'scalar')
    assert check['diagnostics']['value'] == 6


def test_real_duckdb_execution_error_is_unknown_and_retains_raw_failed_report(producer, tmp_path):
    req, _, _ = request(producer, doc=document("SELECT CAST('bad integer' AS INTEGER)"))
    result, _ = evaluate(tmp_path, req)
    assert result['status'] == scalar_check(result)['status'] == 'unknown', result
    assert result['operational']['engineErrors'][0]['type'] == 'ConversionException'
    assert result['operational']['queryIssues'][0]['code'] == 'QUALITY-SQL-INCOMPLETE'
    assert result['nativeRead']['observed']['rows'] == 6
    assert 'ddk:quality-execution-complete' in result['requiredCheckIds']
    assert next(c for c in result['checks'] if c['id'] == 'ddk:quality-execution-complete')['status'] == 'unknown'
    raw = read_json(result['nativeReport']['path']).value
    assert next(c for c in raw['checks'] if c.get('qualityId') == 'scalar')['result'] == 'failed'


def test_swallowed_generic_aggregation_error_cannot_become_data_violation(producer, tmp_path, monkeypatch):
    import ibis.expr.types as ir
    doc = document()
    doc['schema'][0]['properties'][0]['required'] = True
    def unavailable(*args, **kwargs):
        raise RuntimeError('independent injected expression execution failure')
    monkeypatch.setattr(ir.Table, 'execute', unavailable)
    req, _, _ = request(producer, doc=doc)
    result, _ = evaluate(tmp_path, req)
    required = next(c for c in result['checks'] if c['id'].endswith('field_required'))
    assert required['status'] == 'unknown', result
    assert result['status'] == 'unknown'
    assert result['operational']['unmeasuredChecks']
    raw = read_json(result['nativeReport']['path']).value
    assert next(c for c in raw['checks'] if c['key'].endswith('field_required'))['result'] == 'failed'
    assert scalar_check(result)['status'] == 'passed'


def test_real_tiny_engine_exhaustion_is_operational_and_removes_scratch(producer, tmp_path):
    req, _, _ = request(producer, resources=QualityResources(engineMemoryBytes=1, readTimeoutSeconds=3))
    result = NativeTools(sys.executable, output=tmp_path / 'worker', timeout=15).invoke('quality', req)
    assert result['status'] == 'unknown', result
    assert result['operationalError']['code'] == 'QUALITY-ENGINE-INCOMPLETE'
    assert 'Out of Memory' in result['reason']
    root = Path(result['receipt']['path']).parent
    assert (root / 'evaluator-sources.json').is_file()
    assert not list(root.glob('.quality-spill-*'))


def test_materialized_row_count_mismatch_blocks_all_rules(producer, tmp_path, monkeypatch):
    import duckdb
    # Exercise the guard with a connection whose count query sees real changed
    # rows immediately after CTAS, before the binder can accept its evidence.
    class Connection:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def execute(self, sql, *a, **kw):
            result = self.connection.execute(sql, *a, **kw)
            if sql.startswith('CREATE TEMP TABLE'):
                count = result.fetchone()
                self.connection.execute('DELETE FROM records WHERE value < 0')
                class Count:
                    def fetchone(self):
                        return count
                return Count()
            return result
    req, _, _ = request(producer)
    folder = tmp_path / 'bind'
    folder.mkdir()
    con = duckdb.connect()
    try:
        with pytest.raises(QualityOperationalError) as exc:
            quality._bind(Connection(con), req['target'], 'records', folder, QualityResources(readTimeoutSeconds=3))
        assert exc.value.code == 'QUALITY-ROW-CONSERVATION'
    finally:
        con.close()


def test_finished_receipt_precedes_first_rule_and_ingress_registration_is_gone(producer, tmp_path, monkeypatch):
    from datacontract.engines.ibis import ibis_check_execute
    original = ibis_check_execute._run_model
    calls = []
    def inspect_completed(run, backend, *args, **kwargs):
        paths = list((tmp_path / 'quality' / 'docspec-read').rglob('native-read.json'))
        assert len(paths) == 1 and read_json(paths[0]).value['rows'] == 6
        assert backend.con.execute('SELECT count(*) FROM records').fetchone() == (6,)
        assert backend.con.execute("SELECT count(*) FROM duckdb_views() WHERE view_name='__ddk_quality_ingress'").fetchone() == (0,)
        calls.append(1)
        return original(run, backend, *args, **kwargs)
    monkeypatch.setattr(ibis_check_execute, '_run_model', inspect_completed)
    req, _, _ = request(producer)
    result, _ = evaluate(tmp_path, req)
    assert result['status'] == 'passed' and len(calls) == 2


def test_fixture_readback_has_byte_limit_in_addition_to_row_limit(tmp_path):
    import duckdb
    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE records AS SELECT repeat('x', 65536) AS value")
        with pytest.raises(QualityOperationalError) as exc:
            quality._fixture_readback(con, 'records', {'expectedRows': []}, {}, tmp_path,
                                      QualityResources(maxDecodedBatchBytes=1024))
        assert exc.value.code == 'QUALITY-FIXTURE-LIMIT'
    finally:
        con.close()


def test_transport_limits_keep_batch_capacity_separate_from_input(producer, tmp_path):
    req, _, _ = request(producer, resources=QualityResources(maxDecodedBatchBytes=16, readTimeoutSeconds=3))
    with pytest.raises(NativeStreamError):
        evaluate(tmp_path, req)
    assert not list((tmp_path / 'quality').glob('.quality-spill-*'))


def test_scalar_boundary_refuses_nonfinite_and_variable_width_before_fetch():
    import duckdb
    con = duckdb.connect()
    try:
        backend = quality._ScalarBackend(None, con, 'records')
        for sql in ("SELECT CAST('NaN' AS DOUBLE)", "SELECT CAST('Infinity' AS DOUBLE)", "SELECT CAST('x' AS BLOB)"):
            with pytest.raises(quality._ScalarUnavailable) as exc:
                backend.sql(sql).execute()
            assert exc.value.status == 'not_run'
    finally:
        con.close()


def transport_result(*, exit_code=0, drain_incomplete=False):
    return {'exitCode': exit_code, 'drainIncomplete': drain_incomplete, 'timedOut': False,
            'stdoutTruncated': False, 'stderrTruncated': False, 'cancelled': False,
            'stdout': b'{"status":"passed"}', 'stderr': b''}


def test_outer_owner_cleans_exact_spill_after_forced_worker_kill_and_keeps_evidence(tmp_path, monkeypatch):
    from ddk.adapters import native
    bounded = native.run_bounded
    captured = {}
    def run(arguments, **kwargs):
        scratch, folder = Path(arguments[-1]), Path(arguments[-2])
        captured['scratch'], captured['folder'] = scratch, folder
        script = """import pathlib,sys,time
scratch=pathlib.Path(sys.argv[1]); (scratch/'pages').write_bytes(b'x'*1048576)
(scratch.parent/'completed-report.json').write_text('{"retained":true}')
(scratch.parent/'native-read.json').write_text('{"receipt":"retained"}')
time.sleep(20)
"""
        return bounded([sys.executable, '-c', script, str(scratch)], timeout=0.5, limit=1024, env=kwargs['env'])
    monkeypatch.setattr(native, 'run_bounded', run)
    prior = tmp_path / 'prior-invocation'
    prior.mkdir()
    (prior / 'protected').write_bytes(b'prior')
    result = NativeTools(sys.executable, output=tmp_path / 'worker').invoke('quality', {})
    assert result['transport']['timedOut'] and result['status'] == 'error', result
    assert result['scratchCleanup']['status'] == 'removed'
    assert not captured['scratch'].exists()
    assert (captured['folder'] / 'completed-report.json').read_text() == '{"retained":true}'
    assert (captured['folder'] / 'native-read.json').is_file()
    assert (prior / 'protected').read_bytes() == b'prior'


@pytest.mark.parametrize(('exit_code', 'drain'), [(None, False), (0, True)])
def test_uncertain_worker_termination_retains_and_reports_scratch(tmp_path, monkeypatch, exit_code, drain):
    from ddk.adapters import native
    captured = {}
    def run(arguments, **kwargs):
        scratch = Path(arguments[-1])
        captured['scratch'] = scratch
        (scratch / 'pending-pages').write_bytes(b'pending')
        return transport_result(exit_code=exit_code, drain_incomplete=drain)
    monkeypatch.setattr(native, 'run_bounded', run)
    result = NativeTools(sys.executable, output=tmp_path / 'worker').invoke('quality', {})
    assert result['status'] == 'unknown'
    assert result['scratchCleanup']['status'] == 'incomplete'
    assert result['operationalError']['code'] == 'QUALITY-SCRATCH-CLEANUP'
    assert (captured['scratch'] / 'pending-pages').read_bytes() == b'pending'


@pytest.mark.parametrize('replacement', ['symlink', 'directory'])
def test_changed_spill_ownership_never_deletes_foreign_or_prior_path(tmp_path, monkeypatch, replacement):
    from ddk.adapters import native
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    (foreign / 'protected').write_bytes(b'foreign')
    captured = {}
    def run(arguments, **kwargs):
        scratch = Path(arguments[-1])
        captured['scratch'] = scratch
        if replacement == 'symlink':
            scratch.rmdir()
            scratch.symlink_to(foreign, target_is_directory=True)
        else:
            scratch.rename(scratch.with_name('prior-owned-allocation'))
            scratch.mkdir()
            (scratch / 'foreign-marker').write_bytes(b'replacement')
        return transport_result()
    monkeypatch.setattr(native, 'run_bounded', run)
    result = NativeTools(sys.executable, output=tmp_path / 'worker').invoke('quality', {})
    assert result['status'] == 'unknown' and result['nativeOutcome'] == 'passed'
    assert result['scratchCleanup']['status'] == 'incomplete'
    assert (foreign / 'protected').read_bytes() == b'foreign'
    assert captured['scratch'].exists()
    if replacement == 'directory':
        assert (captured['scratch'] / 'foreign-marker').read_bytes() == b'replacement'
        assert captured['scratch'].with_name('prior-owned-allocation').is_dir()


def test_inner_spill_symlink_is_unlinked_without_following_target(tmp_path, monkeypatch):
    from ddk.adapters import native
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    (foreign / 'protected').write_bytes(b'foreign')
    def run(arguments, **kwargs):
        (Path(arguments[-1]) / 'link').symlink_to(foreign, target_is_directory=True)
        return transport_result()
    monkeypatch.setattr(native, 'run_bounded', run)
    result = NativeTools(sys.executable, output=tmp_path / 'worker').invoke('quality', {})
    assert result['status'] == 'passed' and result['scratchCleanup']['status'] == 'removed'
    assert (foreign / 'protected').read_bytes() == b'foreign'


def test_actual_worker_preserves_fractional_resource_times_and_removes_owned_spill(producer, tmp_path):
    req, _, _ = request(producer, resources=QualityResources(readTimeoutSeconds=3.5, cleanupTimeoutSeconds=0.5))
    result = NativeTools(sys.executable, output=tmp_path / 'worker', timeout=15).invoke('quality', req)
    assert result['status'] == 'passed', result
    assert result['scratchCleanup']['status'] == 'removed'
    assert result['resources']['limits']['cleanupTimeoutSeconds'] == 0.5
    assert Path(result['nativeRead']['path']).is_file()
    assert Path(result['nativeReport']['path']).is_file()


def test_large_variable_width_scalar_is_refused_without_result_fetch(producer, tmp_path, monkeypatch):
    import duckdb
    adapter, workspace, version, _ = producer(values=('x' * 65536,), width=65536, batches=1)
    doc = document('SELECT value FROM records', 0)
    doc['schema'][0]['properties'][0]['logicalType'] = 'string'
    req = {'document': doc, 'target': {'kind': 'native', 'nativeVersion': version['reference'],
        'read': {'executable': str(adapter.executable), 'executableSha256': adapter.tool['distributionSha256'],
                 'workspace': str(workspace), 'limits': {}}}}
    original = quality._AuditedDuckDB.__getattr__
    def guard(self, name):
        if isinstance(self.value, duckdb.DuckDBPyRelation) and name == 'fetchall':
            pytest.fail('variable-width scalar result must never be fetched')
        return original(self, name)
    monkeypatch.setattr(quality._AuditedDuckDB, '__getattr__', guard)
    result, _ = evaluate(tmp_path, req)
    assert scalar_check(result)['status'] == result['status'] == 'not_run'
    assert result['nativeRead']['observed']['rows'] == 1


def test_scalar_fallback_does_not_execute_the_same_rejected_result_twice():
    import duckdb
    con = duckdb.connect()
    calls = []
    class Relation:
        columns = ['value']
        types = [duckdb.sqltypes.INTEGER]
        def limit(self, rows):
            assert rows == 2
            return self
        def fetchall(self):
            calls.append('fetch')
            return [(1,), (2,)]
    class Connection:
        def extract_statements(self, query):
            return con.extract_statements(query)
        def sql(self, query):
            calls.append('bind')
            return Relation()
    try:
        backend = quality._ScalarBackend(None, Connection(), 'records')
        from datacontract.engines.ibis.ibis_check_execute import _run_scalar
        with pytest.raises(quality._ScalarUnavailable):
            _run_scalar(backend, 'SELECT value FROM records', 'duckdb')
        assert calls == ['bind', 'fetch']
    finally:
        con.close()


def test_ingress_cleanup_failure_preserves_primary_transport_uncertainty(producer, tmp_path):
    import duckdb
    req, _, _ = request(producer, 'bad-hash')
    folder = tmp_path / 'bind'
    folder.mkdir()
    con = duckdb.connect()
    class Connection:
        def __getattr__(self, name):
            return getattr(con, name)
        def unregister(self, name):
            raise duckdb.IOException('independent cleanup failure')
    try:
        with pytest.raises(NativeStreamError) as exc:
            quality._bind(Connection(), req['target'], 'records', folder, QualityResources(readTimeoutSeconds=3))
        assert exc.value.code != 'QUALITY-ENGINE-INCOMPLETE'
    finally:
        con.close()


def test_uncertain_cleanup_preserves_existing_operational_cause(tmp_path, monkeypatch):
    from ddk.adapters import native
    import json
    def run(arguments, **kwargs):
        value = transport_result(exit_code=None)
        value['stdout'] = json.dumps({'status': 'unknown', 'reason': 'original transport refusal',
            'operationalError': {'code': 'ORIGINAL-TRANSPORT', 'message': 'original cause'}}).encode()
        return value
    monkeypatch.setattr(native, 'run_bounded', run)
    result = NativeTools(sys.executable, output=tmp_path / 'worker').invoke('quality', {})
    assert result['status'] == 'unknown'
    assert result['operationalError']['code'] == 'ORIGINAL-TRANSPORT'
    assert result['cleanupError']['code'] == 'QUALITY-SCRATCH-CLEANUP'
    assert 'original transport refusal' in result['reason']


def test_global_duplicate_and_null_metrics_cross_batch_boundary(producer, tmp_path):
    doc = document()
    doc['schema'][0]['properties'][0].update(unique=True, required=True)
    req, _, _ = request(producer, doc=doc)
    result, _ = evaluate(tmp_path, req)
    raw = read_json(result['nativeReport']['path']).value
    duplicate = next(c for c in raw['checks'] if c['key'].endswith('field_unique'))
    missing = next(c for c in raw['checks'] if c['key'].endswith('field_required'))
    # Input is [11, NULL, -4] twice. Two non-null keys cross the batch
    # boundary, covering four rows; NULL contributes two missing rows.
    assert duplicate['result'] == missing['result'] == 'failed'
    assert duplicate['diagnostics']['value'] == 2
    assert duplicate['diagnostics']['failed_rows'] == 4
    assert missing['diagnostics']['value'] == 2
    assert missing['diagnostics']['row_count'] == 6
    assert result['status'] == 'failed' and scalar_check(result)['status'] == 'passed'
    assert next(c for c in result['checks'] if c['id'] == 'ddk:quality-execution-complete')['status'] == 'passed'


def test_exact_empty_native_candidate_is_complete_zero_not_missing(producer, tmp_path):
    adapter, workspace, version, payload = producer(values=(), batches=2)
    req = {'document': document(expected=0), 'target': {'kind': 'native', 'nativeVersion': version['reference'],
        'read': {'executable': str(adapter.executable), 'executableSha256': adapter.tool['distributionSha256'],
                 'workspace': str(workspace), 'limits': {}}}}
    result, _ = evaluate(tmp_path, req)
    assert result['status'] == 'passed'
    assert result['nativeRead']['observed']['rows'] == result['nativeRead']['materialization']['rows'] == 0
    assert result['nativeRead']['observed']['ipc_sha256'] == sha256(payload).hexdigest()


def test_same_model_cte_shadow_is_rejected_by_cached_sql_and_raw_fallback():
    import duckdb
    from datacontract.engines.ibis.ibis_check_execute import _run_scalar
    con = duckdb.connect()
    con.execute('CREATE TEMP TABLE records AS SELECT 1 AS value UNION ALL SELECT 2 UNION ALL SELECT 3')
    bound, entry_points = [], []
    class Connection:
        def __getattr__(self, name):
            return getattr(con, name)
        def sql(self, query):
            bound.append(query)
            return con.sql(query)
    class Backend(quality._ScalarBackend):
        def sql(self, *args, **kwargs):
            entry_points.append('sql')
            return super().sql(*args, **kwargs)
        def raw_sql(self, *args, **kwargs):
            entry_points.append('raw_sql')
            return super().raw_sql(*args, **kwargs)
    try:
        backend = Backend(None, Connection(), 'records')
        shadow = 'WITH records AS (SELECT 0 AS value) SELECT count(*) FROM records'
        with pytest.raises(quality._ScalarUnavailable) as failure:
            _run_scalar(backend, shadow, 'duckdb')
        assert failure.value.status == 'not_run'
        assert failure.value.code == 'QUALITY-SQL-UNSUPPORTED'
        assert entry_points == ['sql', 'raw_sql', 'sql']
        assert backend.queries[shadow].issue is failure.value
        assert bound == []  # Neither fallback reaches native binding/execution.
        assert con.execute('SELECT count(*) FROM records').fetchone() == (3,)
    finally:
        con.close()


@pytest.mark.parametrize(('sql', 'expected', 'status'), [
    ('WITH records AS (SELECT 0 AS value) SELECT count(*) FROM records', 1, 'not_run'),
    ('SELECT count(*) FROM records', 6, 'passed'),
])
def test_native_scalar_cte_shadow_refusal_and_count_control(producer, tmp_path, sql, expected, status):
    req, _, _ = request(producer, doc=document(sql, expected))
    result, _ = evaluate(tmp_path, req)
    assert result['status'] == scalar_check(result)['status'] == status
    assert result['nativeRead']['observed']['rows'] == 6
    raw = read_json(result['nativeReport']['path']).value
    check = next(c for c in raw['checks'] if c.get('qualityId') == 'scalar')
    if status == 'not_run':
        assert check['result'] == 'failed' and check['diagnostics'] is None
        assert result['operational']['queryIssues'][0]['code'] == 'QUALITY-SQL-UNSUPPORTED'
    else:
        assert check['result'] == 'passed' and check['diagnostics']['value'] == 6
        assert result['operational']['queryIssues'] == []
