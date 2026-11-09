"""Shape-only verification using the existing immutable qualified DDK environment."""
from pathlib import Path
from hashlib import sha256
from importlib.resources import files
from zipfile import ZipFile
import json
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
WHEEL = Path('/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/wheel-a/data_design_kit-0.1.0.dev4-py3-none-any.whl')
EXPECTED = '7c4c6bb481316c95e13c5518089f90c71664ca7387c09eb1ae0f94219fe267b8'
assert sha256(WHEEL.read_bytes()).hexdigest() == EXPECTED
base = files('ddk').joinpath('resources/schemas/0.1')
registry, schema_pins = Registry(), {}
with ZipFile(WHEEL) as wheel:
    for path in base.iterdir():
        if path.name.endswith('.json'):
            original = path.read_bytes()
            assert original == wheel.read('ddk/resources/schemas/0.1/' + path.name)
            schema = json.loads(original)
            registry = registry.with_resource(schema['$id'], Resource.from_contents(schema))
            schema_pins[path.name] = sha256(original).hexdigest()
results = []
for root in [ROOT / 'watershed', ROOT / 'grants']:
    for name, kind in [('catalog.ddk.json', 'catalog'), ('catalog.report.json', 'report'), ('catalog.lock.json', 'lock')]:
        schema = json.loads(base.joinpath(kind + '.schema.json').read_text())
        errors = list(Draft202012Validator(schema, registry=registry).iter_errors(json.loads((root / name).read_bytes())))
        assert not errors, [(list(error.path), error.message) for error in errors]
        results.append({'path': str((root / name).relative_to(ROOT.parent)), 'sha256': sha256((root / name).read_bytes()).hexdigest(), 'shapeErrors': 0})
report = {'scope': 'Document shapes only against immutable installed DDK dev4 schemas; no native execution, DDK assembly, producer conformance or accepted-candidate claim.', 'wheelSha256': EXPECTED, 'schemaSha256': schema_pins, 'results': results}
(ROOT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(f'{len(results)} document shapes passed; installed schemas exactly match the pinned dev4 wheel.')
