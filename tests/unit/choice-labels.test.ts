import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import type { CatalogSnapshot } from '../../src/domain/types';
import { representationChoices, versionChoices } from '../../src/lib/choice-labels';
import { selectedVersion } from '../../src/lib/display';

function snapshot(path = 'fixtures/applications/commerce-native/catalog.ddk.json') {
  return { catalog: JSON.parse(readFileSync(path, 'utf8')) } as CatalogSnapshot;
}

test('application choices lead with supplied dataset title and recorded format, preserving exact IDs', () => {
  const input = snapshot();
  const dataset = input.catalog.datasets.find((row) => row.alias === 'orders')!;
  const versions = input.catalog.versions.filter((row) => row.dataset === dataset.alias);
  const original = structuredClone(input);
  const choices = versionChoices(input, dataset, versions);
  assert.deepEqual(
    choices.map((row) => row.id),
    versions.map((row) => row.id),
  );
  for (const choice of choices) {
    assert.match(choice.label, /Example orders · Version label not supplied · Parquet file/);
    assert.doesNotMatch(choice.label, /[a-f0-9]{32}/);
    assert.doesNotMatch(choice.label, /latest|current|refresh|2026/i);
  }
  assert.deepEqual(input, original);
  const files = input.catalog.representations.filter((row) => row.version === versions[0].id);
  assert.equal(
    representationChoices(dataset, files)[0].label,
    'Example orders · Parquet file · Available',
  );
});

test('opaque release references stay in details rather than primary choice labels', () => {
  const input = snapshot('fixtures/watershed/catalog.ddk.json');
  const dataset = input.catalog.datasets[0];
  const version = input.catalog.versions[0];
  for (const value of [
    'a'.repeat(64),
    'urn:example:release:current',
    { observedAt: '2026-11-06' },
    'a\nb',
    '2026-11-06T12:34:56Z',
    '2026-11-06',
    'opaque_ZyX987',
    'release-1',
  ]) {
    input.catalog.releases[0].reference.value = value;
    assert.equal(
      versionChoices(input, dataset, [version])[0].label,
      'Watershed observations · Version label not supplied · JSON file',
    );
  }
  input.catalog.releases[0].reference.value = 'release-1';
  assert.match(
    versionChoices(input, dataset, [{ ...version, referenceDisclosure: 'withheld' }])[0].label,
    /Details withheld/,
  );
  assert.doesNotMatch(
    versionChoices(input, dataset, [{ ...version, referenceDisclosure: 'withheld' }])[0].label,
    /release-1/,
  );
});

test('duplicate descriptions have list discriminators and never create a publisher selection', () => {
  const input = snapshot();
  delete input.catalog.currentSelection;
  const dataset = input.catalog.datasets.find((row) => row.alias === 'orders')!;
  const versions = input.catalog.versions.filter((row) => row.dataset === dataset.alias);
  const choices = versionChoices(input, dataset, versions);
  assert.ok(choices.length > 1);
  assert.match(choices[0].label, /Choice 1$/);
  assert.match(choices[1].label, /Choice 2$/);
  assert.equal(selectedVersion(input, dataset), undefined);
  const files = input.catalog.representations.filter((row) => row.version === versions[0].id);
  const duplicate = { ...files[0], id: 'other-exact-file-id' };
  assert.match(representationChoices(dataset, [files[0], duplicate])[1].label, /Choice 2$/);
  assert.equal(
    representationChoices(dataset, [{ ...files[0], availability: 'unknown' }])[0].label,
    'Example orders · Parquet file · Availability unknown',
  );
});
