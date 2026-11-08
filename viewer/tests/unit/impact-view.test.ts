import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { CatalogStore, sha256 } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import { impactPins } from '../../src/server/impact-pin';
import { loadImpact } from '../../src/server/impact';
import { selectedVersion } from '../../src/lib/display';
function makeStore() {
  return new CatalogStore(
    fixturePins.map((p) => ({
      ...p,
      mode: 'fixture' as const,
      directory: resolve('fixtures', p.id),
    })),
  );
}

test('DDK impact is bound to exact base/candidate/report and rejects altered files', async () => {
  const store = makeStore(),
    snapshot = await store.snapshot('watershed');
  const result = await loadImpact(store, impactPins, 'watershed', snapshot.identity.catalogSha256);
  assert.equal(result.available, true);
  assert.equal(result.binding.owner, 'ddk.catalog_impact.compare_catalogs');
  assert.equal(result.report.metadata.runtimeReuse.computation.status, 'unknown');
  await assert.rejects(
    loadImpact(store, impactPins, 'watershed', '0'.repeat(64)),
    /another catalog snapshot/,
  );
  assert.equal(
    (await loadImpact(store, [], 'watershed', snapshot.identity.catalogSha256)).available,
    false,
  );
  const dir = await mkdtemp(resolve('work/impact-test-'));
  try {
    await cp('fixtures/impact', dir, { recursive: true });
    const registrations = [{ ...impactPins[0], directory: dir }];
    await writeFile(resolve(dir, 'impact.report.json'), '{}');
    await assert.rejects(
      loadImpact(store, registrations, 'watershed', snapshot.identity.catalogSha256),
      /differs from its exact binding/,
    );
    const binding = JSON.parse(await readFile(resolve(dir, 'binding.json'), 'utf8'));
    binding.candidateCatalogSha256 = '0'.repeat(64);
    const bytes = JSON.stringify(binding);
    await writeFile(resolve(dir, 'binding.json'), bytes);
    await assert.rejects(
      loadImpact(
        store,
        [{ ...registrations[0], bindingSha256: sha256(bytes) }],
        'watershed',
        snapshot.identity.catalogSha256,
      ),
      /different candidate/,
    );
    await assert.rejects(
      loadImpact(store, registrations, 'watershed', snapshot.identity.catalogSha256),
      /differs from its exact binding/,
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('publisher default requires one applicable selection; disjoint selections stay valid', async () => {
  const source = await makeStore().snapshot('watershed');
  const snapshot = structuredClone(source);
  const dataset = snapshot.catalog.datasets[0];
  assert.match(selectedVersion(snapshot, dataset)!.id, /observations:v2$/);
  const current = snapshot.catalog.selections[0];
  snapshot.catalog.selections.push({ ...current, release: 'urn:test:another-release' });
  snapshot.catalog.releases.push({
    ...snapshot.catalog.releases.find((r) => r.id === current.release)!,
    id: 'urn:test:another-release',
  });
  assert.equal(selectedVersion(snapshot, dataset), undefined);
  snapshot.catalog.releases.at(-1)!.members = [];
  assert.match(selectedVersion(snapshot, dataset)!.id, /observations:v2$/);
});
