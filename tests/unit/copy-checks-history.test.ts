import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolve } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { CatalogStore } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import { Overview, Evidence, Activity, Compare } from '../../src/components/MetadataPanels';

async function context() {
  const pin = fixturePins.find((p) => p.id === 'watershed')!;
  const snapshot = structuredClone(
    await new CatalogStore([
      { ...pin, mode: 'fixture', directory: resolve('fixtures/watershed') },
    ]).snapshot('watershed'),
  );
  const dataset = snapshot.catalog.datasets[0];
  const version = snapshot.catalog.versions.find(
    (v) => v.dataset === dataset.alias && v.id.endsWith(':v2'),
  )!;
  return { snapshot, dataset, version };
}

test('overview separates listed file availability from this portal reader and preserves exact counts', async () => {
  const props = await context();
  props.snapshot.capabilities.read = false;
  props.version.coverage = [
    {
      scope: 'Saved file only',
      unit: 'records',
      status: 'unknown',
      observed: { $number: '9007199254740993' },
      record: props.version.record,
    },
  ];
  const html = renderToStaticMarkup(createElement(Overview, props));
  assert.match(html, /View records here/);
  assert.match(html, /Not connected/);
  assert.match(html, /File availability/);
  assert.match(html, /available/i);
  assert.match(html, /9007199254740993/);
  assert.match(html, /Expected population total not recorded/);
  assert.match(html, /Coverage: unknown/i);
  props.snapshot.catalog.versions = [];
  const noVersion = renderToStaticMarkup(createElement(Overview, { ...props, version: undefined }));
  assert.doesNotMatch(noVersion, /Choose a data version/);
});

test('compare explains zero and one version and refuses same-version comparison', async () => {
  const props = await context();
  props.snapshot.catalog.versions = [];
  let html = renderToStaticMarkup(createElement(Compare, { ...props, version: undefined }));
  assert.match(html, /No data versions are listed/);
  assert.doesNotMatch(html, /<select/);
  props.snapshot.catalog.versions = [props.version];
  html = renderToStaticMarkup(createElement(Compare, props));
  assert.match(html, /Only one data version is listed/);
  assert.doesNotMatch(html, /<table/);
  assert.match(html, /does not change when you choose data versions above/);
});

test('checks keep unknown and not run separate and show no invented rule name', async () => {
  const props = await context();
  props.snapshot.catalog.checks = ['passed', 'failed', 'unknown', 'not_run'].map((status) => ({
    subject: props.version.id,
    rule: { id: `urn:rule:${status}`, version: 'v1' },
    evaluator: { id: 'urn:evaluator:test', version: 'v2' },
    status: status as 'passed',
    scope: 'Only the saved file',
  }));
  const html = renderToStaticMarkup(createElement(Evidence, props));
  assert.match(html, /4 recorded; 1 passed; 1 failed; 1 unknown; 1 not run/);
  assert.equal((html.match(/Check \d+ · title not supplied/g) ?? []).length, 4);
  assert.match(html, /urn:rule:not_run/);
  assert.match(html, /Passing checks do not establish overall data/);
  assert.match(html, /does not make or refresh acceptance/);
});

test('history keeps original processing identifiers and specific evidence capability', async () => {
  const props = await context();
  props.snapshot.capabilities.evidence = true;
  props.snapshot.catalog.runs = [
    {
      id: 'urn:run:original',
      reference: { scheme: 'test', authority: 'publisher', value: 'exact-run' },
      inputs: [],
      outputs: [props.version.id],
      outcome: 'passed',
      observedAt: '2026-11-06T14:30:00Z',
      record: { uri: 'urn:evidence:run', sha256: 'a'.repeat(64) },
      inputCoverage: { status: 'unknown', scope: 'Saved file only' },
    },
  ];
  const html = renderToStaticMarkup(createElement(Activity, props));
  assert.match(html, /Nov 6, 2026, 2:30 PM UTC/);
  assert.match(html, /Original operation identifiers and timestamp/);
  assert.match(html, /Original processing records can be opened above/);
  assert.doesNotMatch(html, /Native inspection is not connected/);
  assert.match(html, /<summary>Integration status<\/summary>/);
});
