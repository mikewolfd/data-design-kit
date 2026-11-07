import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Activity } from '../../src/components/MetadataPanels';
import { exactStringify } from '../../src/domain/exact';
import { CatalogStore } from '../../src/server/catalog-store';
import { congressRegistration } from '../../src/server/congress-registration';

async function context() {
  // Reads only the retained catalog metadata, never payloads or the owner reader.
  const snapshot = structuredClone(
    await new CatalogStore([congressRegistration], 'local').snapshot('congress-authored'),
  );
  const run = snapshot.catalog.runs[0];
  const version = snapshot.catalog.versions.find((row) => run.outputs.includes(row.id))!;
  const dataset = snapshot.catalog.datasets.find((row) => row.alias === version.dataset)!;
  const assembly = snapshot.catalog.extensions!['urn:ddk:catalog:assembly'] as any;
  const trace = assembly.managedExecutions[0];
  return { snapshot, run, version, dataset, assembly, trace };
}
const render = (props: Awaited<ReturnType<typeof context>>) =>
  renderToStaticMarkup(createElement(Activity, props));

test('the real retained acceptance remains visible beyond the whole-extension preview limit', async () => {
  const props = await context();
  const identity = props.trace.acceptedQualification;
  assert.ok(exactStringify(props.snapshot.catalog.extensions).indexOf(identity) > 131072);
  const html = render(props);
  assert.match(html, /Recorded processing acceptance/);
  assert.ok(html.includes(identity));
  assert.match(html, /Exact acceptance identity/);
  assert.match(html, /currently accepted, selected or published/);
  assert.match(html, /No release membership is recorded/);
  const card = html.match(/<div class="recorded-acceptance">(.*?)<\/p><\/div>/s)![1];
  assert.doesNotMatch(card, /file:\/|\/Users\/|bytes_base64|badge good|SHA-256/);
});

test('null, missing and malformed acceptance identities retain distinct meanings', async () => {
  const props = await context();
  props.trace.acceptedQualification = null;
  assert.match(render(props), /No acceptance identity is attached to this record/);
  delete props.trace.acceptedQualification;
  assert.match(render(props), /Unknown · the summary supplies no valid acceptance identity/);
  props.trace.acceptedQualification = '/private/producer-proof';
  const invalid = render(props);
  assert.match(invalid, /Unknown · the summary supplies no valid acceptance identity/);
  assert.doesNotMatch(invalid, /\/private\/producer-proof/);
  props.assembly.managedExecutions = [];
  assert.doesNotMatch(render(props), /Recorded processing acceptance/);
});

test('ambiguous runs and mismatched receipt identities cannot display an acceptance', async () => {
  const props = await context();
  const identity = props.trace.acceptedQualification;
  props.assembly.managedExecutions.push({
    ...props.trace,
    record: { uri: 'urn:other', sha256: 'a'.repeat(64) },
  });
  assert.match(render(props), /Unknown · multiple summaries/);
  assert.ok(!render(props).includes(identity));
  props.assembly.managedExecutions.pop();
  for (const record of [
    { ...props.trace.record, uri: 'urn:other' },
    { ...props.trace.record, sha256: 'a'.repeat(64) },
    { uri: props.trace.record.uri },
    { uri: '', sha256: props.trace.record.sha256 },
  ]) {
    props.trace.record = record;
    const html = render(props);
    assert.match(html, /Unknown · the summary does not identify the same evidence file/);
    assert.ok(!html.includes(identity));
  }
});

test('public views never promote the local managed summary', async () => {
  const props = await context();
  props.trace.producerEvidence = { role: 'model' };
  props.snapshot.audience = 'public';
  props.snapshot.catalog.audience = 'public';
  const html = render(props);
  assert.doesNotMatch(html, /Recorded processing acceptance/);
  assert.doesNotMatch(html, /Recorded producer evidence for this event/);
  assert.ok(!html.includes(props.trace.acceptedQualification));
});

test('recorded producer metadata does not depend on acceptance or imply proof availability', async () => {
  const props = await context();
  assert.doesNotMatch(render(props), /Recorded producer evidence for this event/);
  // This only exercises optional metadata disclosure; it is not a native proof fixture.
  props.trace.producerEvidence = { role: 'model' };
  props.trace.acceptedQualification = null;
  const html = render(props);
  assert.match(html, /No acceptance identity is attached to this record/);
  assert.match(html, /Recorded producer evidence for this event/);
  assert.match(html, /which code wrote earlier records or whether proof files are still available/);
  delete props.trace.acceptedQualification;
  assert.match(render(props), /Unknown · the summary supplies no valid acceptance identity/);
  assert.match(render(props), /Recorded producer evidence for this event/);
  props.trace.producerEvidence = null;
  assert.match(render(props), /Recorded producer evidence for this event/);
});

test('producer metadata remains scoped to one exact run and receipt', async () => {
  const props = await context();
  props.trace.producerEvidence = { role: 'model' };
  props.assembly.managedExecutions.push({ ...props.trace });
  assert.doesNotMatch(render(props), /Recorded producer evidence for this event/);
  props.assembly.managedExecutions.pop();
  props.trace.record = { ...props.trace.record, uri: 'urn:other' };
  assert.doesNotMatch(render(props), /Recorded producer evidence for this event/);
});
