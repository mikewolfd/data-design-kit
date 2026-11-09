import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { CatalogSnapshot } from '../../src/domain/types';
import {
  AttributionContext,
  Cautions,
  CoverageContext,
  DateContext,
  HistoryNotes,
  ProvenanceContext,
  PublisherMetadataNotice,
} from '../../src/features/dataset-context';
import { citationWithReference } from '../../src/features/dataset-context/Sources';
import { PUBLISHER_DISCOVERY, type PublisherRecord } from '../../src/features/publisher-metadata';
import { CatalogStore } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import { applicationRegistrations } from '../../src/server/registry';

const assemblyKey = 'urn:ddk:catalog:assembly';

async function watershed() {
  const registration = fixturePins.find(({ id }) => id === 'watershed')!;
  const snapshot = structuredClone(
    await new CatalogStore([
      { ...registration, mode: 'fixture', directory: resolve('fixtures/watershed') },
    ]).snapshot('watershed'),
  );
  const dataset = snapshot.catalog.datasets.find(({ alias }) => alias === 'observations')!;
  const version = snapshot.catalog.versions.find(({ id }) => id.endsWith('observations:v1'))!;
  const representation = snapshot.catalog.representations.find(
    (row) => row.version === version.id,
  )!;
  const releaseId = snapshot.catalog.releases.find(({ members }) =>
    members.includes(version.id),
  )!.id;
  return { snapshot, dataset, version, representation, releaseId };
}

function withExtension(snapshot: CatalogSnapshot, records: unknown[]) {
  const assembly = snapshot.catalog.extensions![assemblyKey] as Record<string, unknown>;
  assembly.projectExtensions = [
    {
      namespace: '',
      project: snapshot.catalog.project,
      extensions: { [PUBLISHER_DISCOVERY]: { schemaVersion: 1, records } },
    },
  ];
}

function datasetTarget(dataset: CatalogSnapshot['catalog']['datasets'][number]) {
  const { contractId, version, object, source } = dataset.definition;
  return {
    kind: 'dataset',
    datasetId: dataset.id,
    definition: { contractId, version, object, sourceSha256: source.sha256 },
  } as const;
}

test('admitted Spicy notes show dataset coverage and coverage observation without implying updates', async () => {
  const registration = applicationRegistrations.find(({ id }) => id === 'spicy-regs')!;
  const snapshot = await new CatalogStore([registration]).snapshot('spicy-regs');
  const dataset = snapshot.catalog.datasets.find(({ alias }) => alias === 'current-cftc-comments')!;
  const props = { snapshot, dataset };
  const coverage = renderToStaticMarkup(createElement(CoverageContext, props));
  assert.match(coverage, /Sampled\. Selected retained listing observations/);
  assert.match(coverage, /Version coverage is unknown/);
  assert.doesNotMatch(coverage, /Coverage: complete/i);
  const dates = renderToStaticMarkup(createElement(DateContext, props));
  assert.match(
    dates,
    /Coverage observation date<\/dt><dd><time dateTime="2026-10-13">Oct 13, 2026/,
  );
  assert.match(dates, /Source publication date<\/dt><dd>Not supplied/);
  assert.match(dates, /Data update date<\/dt><dd>Not supplied/);
  assert.match(dates, /Source retrieval date<\/dt><dd>Not supplied/);
  const sources = renderToStaticMarkup(createElement(ProvenanceContext, props));
  assert.match(sources, /Commodity Futures Trading Commission comments/);
  assert.match(sources, /href="https:\/\/comments\.cftc\.gov\/"/);
  assert.match(sources, /Declared source publishers/);
  assert.match(sources, /Independent writer declaration checked; no data version implied/);
  assert.match(sources, /How records were processed remains unknown/);
  assert.equal(renderToStaticMarkup(createElement(PublisherMetadataNotice, { snapshot })), '');
  const comments = snapshot.catalog.datasets.find(({ alias }) => alias === 'current-comments')!;
  assert.match(
    renderToStaticMarkup(createElement(Cautions, { snapshot, dataset: comments })),
    /posted_date.*Full data-quality note/,
  );
  assert.equal(renderToStaticMarkup(createElement(Cautions, props)), '');
});

test('Watershed v1 coverage and trace stay bound to the selected synthetic file', async () => {
  const props = await watershed();
  const coverage = renderToStaticMarkup(createElement(CoverageContext, props));
  assert.match(coverage, /Authored sample rows only/);
  assert.match(coverage, /3<\/span> rows observed/);
  assert.match(coverage, /Expected population total <span class="numeric">3<\/span> rows/);
  assert.match(coverage, /Coverage: complete/i);
  assert.doesNotMatch(coverage, /14<\/span> rows/);
  const provenance = renderToStaticMarkup(createElement(ProvenanceContext, props));
  assert.match(provenance, /synthetic example data/);
  assert.match(provenance, /Example source capture 1/);
  assert.doesNotMatch(provenance, /Example source capture 2/);
  assert.match(provenance, /Recorded input coverage.*Partial/i);
  assert.match(provenance, /Illustrative fixture capture only/);
  const attribution = renderToStaticMarkup(createElement(AttributionContext, props));
  assert.match(attribution, /Copy exact selected-version reference/);
  assert.ok(attribution.includes(props.version.id));
  assert.ok(attribution.includes(props.representation.id));
  assert.ok(attribution.includes(props.releaseId));
  assert.match(attribution, /Publisher citation not supplied/);
  assert.match(attribution, /Data reuse terms not supplied/);
  const dates = renderToStaticMarkup(createElement(DateContext, props));
  assert.match(dates, /Data update date<\/dt><dd>Not supplied/);
  assert.doesNotMatch(dates, /2026-11-06T17:00:00Z/);
});

test('a missing expected count preserves precision and leaves completeness unknown', async () => {
  const props = await watershed();
  props.version.coverage = [
    {
      status: 'complete',
      scope: 'Saved file only',
      unit: 'sample units',
      observed: { $number: '9007199254740993' },
      record: props.version.record,
    },
  ];
  const html = renderToStaticMarkup(createElement(CoverageContext, props));
  assert.match(html, /9007199254740993<\/code> sample units observed/);
  assert.match(html, /Expected population total not recorded/);
  assert.match(html, /Completeness is unknown/);
  assert.match(html, /Reported scope status: complete/);
  assert.doesNotMatch(html, /Coverage: complete/i);
});

test('publisher resource facts stay separate from collection facts and recipe cautions', async () => {
  const props = await watershed();
  const { dataset, snapshot, version, representation } = props;
  const recipe = snapshot.catalog.recipes[0];
  const records: PublisherRecord[] = [
    {
      target: datasetTarget(dataset),
      coverage: { geography: 'Worldwide extent', exclusions: 'Uneven sampling' },
      dates: [{ kind: 'metadataUpdated', value: '2026-11-07' }],
      updateFrequency: 'Daily',
      terms: [{ label: 'Portal editorial terms', scope: 'portalText' }],
      unknowns: [{ fact: 'Observation timezone', reason: 'The metadata supplies no timezone.' }],
    },
    {
      target: {
        kind: 'representation',
        datasetId: dataset.id,
        versionId: version.id,
        representationId: representation.id,
      },
      coverage: { period: { start: '2024-03-01', end: '2024-03-02' } },
      dates: [{ kind: 'dataUpdated', value: '2026-10-07T12:34:56-05:00' }],
      terms: [{ label: 'Selected file terms', scope: 'data', url: 'https://source.example/terms' }],
      support: [{ label: 'Ask about the data', url: 'mailto:help@source.example' }],
      citation: {
        text: 'Original citation wording.',
        originalIdentifier: 'urn:source:selected-file',
      },
      cautions: [{ summary: 'Resource-specific interpretation.' }],
      history: [
        {
          kind: 'renamedField',
          description: 'The publisher changed the label shown for readings.',
          date: '2026-10-07',
          evidence: [{ label: 'Publisher notice', url: 'https://source.example/notice' }],
        },
      ],
    },
    {
      target: { kind: 'recipe', recipeId: recipe.id },
      cautions: [{ summary: 'Transfers and releases can count the same material.' }],
    },
  ];
  withExtension(snapshot, records);
  const coverage = renderToStaticMarkup(createElement(CoverageContext, props));
  assert.match(
    coverage,
    /Worldwide extent.*Uneven sampling.*Selected resource.*Mar 1, 2024.*Mar 2, 2024/,
  );
  const dates = renderToStaticMarkup(createElement(DateContext, props));
  assert.match(dates, /Data update date<\/dt><dd>Not supplied/);
  assert.match(dates, /Metadata update date<\/dt><dd><time dateTime="2026-11-07"/);
  assert.match(
    dates,
    /Selected resource.*Data update date<\/dt><dd><time dateTime="2026-10-07T12:34:56-05:00"/,
  );
  assert.match(dates, /expected update schedule.*Daily/);
  assert.doesNotMatch(dates, /up to date/i);
  const rights = renderToStaticMarkup(createElement(AttributionContext, props));
  assert.match(
    rights,
    /Portal text reuse terms.*Portal editorial terms.*Selected resource.*Data reuse terms.*Selected file terms/,
  );
  assert.match(rights, /href="mailto:help@source\.example"/);
  assert.match(rights, /Original citation wording\./);
  assert.match(rights, /Copy publisher citation for selected resource with selected reference/);
  assert.match(
    rights,
    /&quot;originalCitationIdentifier&quot;: &quot;urn:source:selected-file&quot;/,
  );
  const history = renderToStaticMarkup(createElement(HistoryNotes, props));
  assert.match(history, /Selected resource.*Field rename.*Publisher notice/);
  const cautions = renderToStaticMarkup(createElement(Cautions, props));
  assert.match(cautions, /Observation timezone/);
  assert.match(cautions, /Resource-specific interpretation/);
  assert.doesNotMatch(cautions, /Transfers and releases/);
  const query = renderToStaticMarkup(createElement(Cautions, { snapshot, recipe }));
  assert.match(query, /This query.*Transfers and releases/);
  assert.doesNotMatch(query, /Resource-specific|Observation timezone/);
  const noResource = renderToStaticMarkup(
    createElement(AttributionContext, { ...props, representation: undefined }),
  );
  assert.doesNotMatch(noResource, /Selected file terms|Original citation wording/);
});

test('the citation copy keeps publisher wording intact and labels the exact identifier and viewer reference', () => {
  const text = 'Original citation wording.\nPublisher footnote.';
  const originalIdentifier = 'urn:source:2026.1';
  const reference =
    '{"versionId":"original-version","originalVersionReference":{"value":"edition-1"}}';
  assert.equal(
    citationWithReference({ text, originalIdentifier }, reference),
    `${text}\n\nOriginal publisher identifier\n${originalIdentifier}\n\nExact selected-version reference from the viewer\n${reference}`,
  );
  assert.equal(citationWithReference({ text }), text);
});

test('refused extension metadata leaves standard facts and absent and withheld states distinct', async () => {
  const props = await watershed();
  const { snapshot, dataset, version } = props;
  withExtension(snapshot, [
    {
      target: datasetTarget(dataset),
      dates: [{ kind: 'dataUpdated', value: '2026-11-07T12:00:00' }],
      terms: [{ label: 'Bogus terms', scope: 'data', url: 'javascript:alert(1)' }],
    },
  ]);
  const notice = renderToStaticMarkup(createElement(PublisherMetadataNotice, { snapshot }));
  assert.match(notice, /Some publisher metadata could not be shown/);
  assert.match(notice, /urn:ddk:publisher:discovery/);
  const coverage = renderToStaticMarkup(createElement(CoverageContext, props));
  assert.match(coverage, /Authored sample rows only/);
  version.referenceDisclosure = 'withheld';
  const rights = renderToStaticMarkup(createElement(AttributionContext, props));
  assert.match(rights, /The original version reference is withheld/);
  assert.match(rights, /Publisher citation not supplied/);
  assert.doesNotMatch(rights, /originalVersionReference|Bogus terms|javascript:/);
  assert.match(
    renderToStaticMarkup(createElement(HistoryNotes, props)),
    /Publisher change notes are not supplied/,
  );
});
