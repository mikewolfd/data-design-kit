import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { CatalogStore, ASSEMBLY, sha256 } from '../../src/server/catalog-store';
import { applicationRegistrations } from '../../src/server/registry';

for (const registration of applicationRegistrations) {
  test(`${registration.id} publisher capture admits exact regenerated metadata with discovery-only scope`, async () => {
    const capture = JSON.parse(
      await readFile(join(registration.directory, 'capture.json'), 'utf8'),
    );
    assert.equal(capture.lockSha256, registration.lockSha256);
    assert.equal(capture.sourceLockUnchangedDuringCapture, true);
    assert.ok(capture.priorCapture.lockSha256);
    for (const file of capture.files) {
      const bytes = await readFile(join(registration.directory, file.path));
      assert.equal(sha256(bytes), file.sha256);
      assert.equal(bytes.byteLength, file.bytes);
    }
    const snapshot = await new CatalogStore([registration]).snapshot(registration.id);
    assert.equal(snapshot.audience, 'public');
    assert.equal(snapshot.capabilities.read, false);
    assert.equal(snapshot.capabilities.query, false);
    assert.equal(snapshot.catalog.datasets.length, capture.datasetCount);
    const definitions = (
      snapshot.catalog.extensions?.[ASSEMBLY] as {
        datasetDefinitions: Record<string, any>;
      }
    ).datasetDefinitions;
    assert.ok(snapshot.catalog.datasets.every((dataset) => dataset.rowMeaning?.trim()));
    if (registration.id === 'congress') {
      assert.equal(snapshot.catalog.datasets.length, 24);
      assert.equal(snapshot.catalog.recipes.length, 16);
      assert.equal(
        snapshot.catalog.datasets.find((dataset) => dataset.alias === 'detail')?.title,
        'Document details',
      );
      assert.equal(
        snapshot.catalog.datasets.find((dataset) => dataset.alias === 'meeting-coverage')?.title,
        'Available materials for each meeting',
      );
      assert.match(
        snapshot.catalog.datasets.find((dataset) => dataset.alias === 'future-data')!.title ?? '',
        /fixture/,
      );
      const checkDescription = (field: any) => {
        assert.ok(field.description?.trim(), field.name ?? 'array item');
        field.properties?.forEach(checkDescription);
        if (field.items) checkDescription(field.items);
      };
      for (const definition of Object.values(definitions) as any[]) {
        assert.ok(definition.description?.trim());
        definition.properties.forEach(checkDescription);
      }
    } else {
      assert.equal(snapshot.catalog.datasets.length, 389);
      assert.equal(snapshot.catalog.versions.length, 0);
      assert.ok(definitions['current-budget-volumes']);
    }
  });
}
