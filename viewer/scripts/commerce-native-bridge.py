"""One bounded read of retained commerce output through the qualified DDK APIs.

This bridge never stages, transforms, checks quality, selects, or publishes data.
"""
from pathlib import Path
from hashlib import sha256
from importlib.resources import files
from zipfile import ZipFile
from urllib.parse import urlsplit, unquote
import json
import signal
import sys
import threading

from ddk.adapters.docspec import DocSpecAdapter
from ddk.catalog_access import run_checked_query
from ddk.documents import json_dumps

PROJECT = Path(__file__).resolve().parent.parent
CAPTURE = PROJECT / 'fixtures/applications/commerce-native'
CAPTURE_SHA = '2b2dfa95deccf0c8240926bcb568d8e396bfdc6128034f6a704df7a7c1510834'
QUALIFIED = Path('/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01')
BINARY = Path('/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/runtime/docspec-ddk-final')
BINARY_SHA = 'b89b43e2d2bf17f8d87ff1d9a779e06c3a024f2777e2327a8f048c6cb00a2532'
WHEEL_SHA = '7c4c6bb481316c95e13c5518089f90c71664ca7387c09eb1ae0f94219fe267b8'
DATA_SHA = 'ff0efd8f35eb3b64e23a2f195cbfd2c9989173020b4681ae783bc0f2301ba4c6'
VERSION = 'urn:ddk:file-version:667e1cdb71e36ebef8639a894100bcc50d3ab83bc4c02f18ab2e3f9a6f71eb24'
DATASET = 'urn:example:commerce:dataset:daily-revenue'
REPRESENTATION = 'urn:ddk:representation:eb5fc8380425c98005ccda57f9ac4f399e348daf008fd0812252028352e4965d'
RECIPE = 'urn:example:commerce:recipe:checked-revenue'
RELEASE = 'urn:example:commerce:release:copy-refresh-20261106'
LIMITS = {'batch_rows': 8192, 'compute_threads': 2, 'max_batch_bytes': 8 << 20,
          'max_metadata_bytes': 2 << 20, 'memory_bytes': 256 << 20, 'scratch_bytes': 64 << 20}
CANCELLED = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: CANCELLED.set())
signal.signal(signal.SIGINT, lambda *_: CANCELLED.set())


def bounded(path, cap=1 << 20):
    with path.open('rb') as stream:
        data = stream.read(cap + 1)
    if len(data) > cap:
        raise ValueError('A pinned bridge input exceeds its byte budget')
    return data


def main():
    raw = sys.stdin.buffer.read((16 << 10) + 1)
    if len(raw) > 16 << 10:
        raise ValueError('Bridge request exceeds its byte budget')
    request = json.loads(raw)
    binding = request['binding']
    if (binding.get('datasetId'), binding.get('versionId'), binding.get('representationId')) != (DATASET, VERSION, REPRESENTATION):
        raise ValueError('The bounded owner supports only the exact retained revenue version')
    if binding.get('releaseId', RELEASE) != RELEASE or request['operation'] not in {'read', 'query'}:
        raise ValueError('Unsupported bounded owner binding')
    if request.get('parameters', {}) != {} or request.get('recipeId', RECIPE) != RECIPE:
        raise ValueError('Only the exact parameter-free checked recipe is supported')
    if not isinstance(request['limit'], int) or isinstance(request['limit'], bool) or not 3 <= request['limit'] <= 100 or request.get('offset', 0) != 0:
        raise ValueError('The exact unordered three-row read requires limit >= 3 and offset 0')
    attempt = Path(request['attempt']).resolve(strict=True)
    if attempt.parent != (PROJECT / 'work/native-consumer').resolve(strict=True):
        raise ValueError('The bridge output directory is not viewer-owned')
    capture_bytes = bounded(CAPTURE / 'capture.json')
    if sha256(capture_bytes).hexdigest() != CAPTURE_SHA:
        raise ValueError('The retained capture manifest changed')
    capture = json.loads(capture_bytes)
    for record in capture['files']:
        path = CAPTURE / record['path']
        if not path.resolve().is_relative_to(CAPTURE.resolve()) or sha256(bounded(path)).hexdigest() != record['sha256']:
            raise ValueError('The exact retained catalog or evidence bytes changed')
    wheel_path = QUALIFIED / 'wheel-a/data_design_kit-0.1.0.dev4-py3-none-any.whl'
    wheel_bytes = bounded(wheel_path, 8 << 20)
    if sha256(wheel_bytes).hexdigest() != WHEEL_SHA:
        raise ValueError('The qualified DDK distribution changed')
    # Check the owning installed API modules against the exact selected wheel.
    with ZipFile(wheel_path) as wheel:
        for name in ['catalog_access.py', 'documents.py', 'adapters/docspec.py', 'adapters/native.py']:
            if files('ddk').joinpath(name).read_bytes() != wheel.read('ddk/' + name):
                raise ValueError('An installed owning DDK API changed')
    response = None

    def reader(native_binding):
        nonlocal response
        member = native_binding['inputs']['daily_revenue']
        if member['id'] != VERSION or member['reference']['scheme'] != 'urn:ddk:version:local-file-sha256':
            raise ValueError('The maintained resolver returned a different exact version')
        ref = member['reference']['value']
        location = urlsplit(ref['location'])
        if location.scheme != 'file' or location.netloc or ref['sha256'] != DATA_SHA:
            raise ValueError('The native input reference is not the retained local file')
        path = Path(unquote(location.path)).resolve(strict=True)
        expected = Path(capture['sourceRoot']) / 'run/substrait-result.parquet'
        if path != expected.resolve(strict=True) or len(bounded(path, 1024)) != 877 or sha256(bounded(path, 1024)).hexdigest() != DATA_SHA:
            raise ValueError('The exact retained revenue payload changed')
        runtime = DocSpecAdapter(BINARY, LIMITS, timeout=3, evidence_dir=attempt / 'runtime', capture_bytes=128 << 10,
                                 source_commit='b1270b2e964becc5844bb6ca95ee5d605c7a3d79')
        # The maintained constructor already hashes the 395MB binary. Do not hash it twice.
        if runtime.tool['distributionSha256'] != BINARY_SHA:
            raise ValueError('The selected native executable differs from the qualified tuple')
        response = runtime.execute({'scratch': str(attempt / 'scratch'),
                                    'inputs': [{'kind': 'parquet', 'name': 'daily_revenue', 'path': str(path)}],
                                    'steps': [], 'outputs': [],
                                    'queries': [{'name': 'consumer', 'sql': native_binding['sql'].decode()}]},
                                   input_digests={str(path): DATA_SHA}, cancel_event=CANCELLED)
        if response['status'] != 'succeeded':
            raise RuntimeError('Native read completion is not established')
        return {'result': response['result']['queries'][0]['data'], 'receipt': response['evidence']}

    try:
        consumed = run_checked_query(CAPTURE / 'catalog.ddk.json', RECIPE, reader, release=RELEASE, parameters={})
        rows = consumed['result']
        if len(rows) != 3:
            raise ValueError('The retained owner read did not return the admitted three-row result')
        answer = {'status': 'succeeded', 'rows': rows, 'binding': consumed['binding'],
                  'sqlSha256': consumed['sqlSha256'], 'evidence': consumed['receipt'],
                  'operation': response['operation'], 'rowOrder': 'query-result'}
    except Exception:
        answer = {'status': 'unknown' if response else 'refused',
                  'reason': 'The bounded native read did not establish a complete result.',
                  'evidence': response.get('evidence') if response else None,
                  'operation': response.get('operation') if response else None}
    text = json_dumps(answer)
    (attempt / 'bridge-result.json').write_text(text)
    sys.stdout.write(text)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        sys.stdout.write(json_dumps({'status': 'refused', 'reason': str(error)}))
        sys.exit(1)
