import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolve } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Connections } from '../../src/components/Connections';
import { CatalogStore } from '../../src/server/catalog-store';
import { congressRegistration } from '../../src/server/congress-registration';
import type { CatalogRelationship } from '../../src/domain/types';

async function context(audience: 'local' | 'public' = 'local') {
  const registration =
    audience === 'local'
      ? congressRegistration
      : {
          id: 'congress',
          mode: 'application' as const,
          directory: resolve('fixtures/applications/congress'),
          lockSha256: '26967938b6e9e5bb067f8be52f798deb38ef2288449498b6cdde1373eddc7801',
        };
  const snapshot = structuredClone(
    await new CatalogStore([registration], audience).snapshot(registration.id),
  );
  snapshot.catalog.recipes = [];
  const assembly = snapshot.catalog.extensions!['urn:ddk:catalog:assembly'] as any;
  return { snapshot, assembly };
}

function render(props: Awaited<ReturnType<typeof context>>, relationship: CatalogRelationship) {
  const dataset = props.snapshot.catalog.datasets.find(
    (row) => row.alias === relationship.source.dataset,
  )!;
  return renderToStaticMarkup(
    createElement(Connections, {
      snapshot: {
        ...props.snapshot,
        catalog: { ...props.snapshot.catalog, relationships: [relationship] },
      },
      dataset,
      onNavigate: () => {},
    }),
  );
}

test('public relationship disclosure stays unknown and withholds individual assessments', async () => {
  const props = await context('public');
  const relationship = props.snapshot.catalog.relationships.find((row) => row.target.external)!;
  props.assembly.relationshipAssessments = [
    {
      relationship: relationship.id,
      profile: props.assembly.relationshipProfile.identity,
      scope: 'declaration-support-only',
      status: 'supported',
      reason: 'Private assessment detail',
    },
  ];
  const html = render(props, relationship);
  assert.match(html, /Matching rule assessment: Unknown/);
  assert.ok(html.includes(props.assembly.relationshipAssessmentScope.reason));
  assert.match(html, /Declared requirement: .*External reference/);
  assert.match(html, /Whether this external target exists is unknown here/);
  assert.doesNotMatch(
    html,
    /Private assessment detail|Matching rule assessment: Supported|Matches have not been checked/,
  );
  delete props.assembly.relationshipAssessmentScope;
  assert.doesNotMatch(
    render(props, relationship),
    /Private assessment detail|Matching rule assessment: Supported/,
  );
});

test('local rule support is separate from declared resolution and actual record matches', async () => {
  const props = await context();
  const rows = props.assembly.relationshipAssessments as any[];
  const relationship = props.snapshot.catalog.relationships.find(
    (r) => r.resolution === 'required' && rows.some((row) => row.relationship === r.id),
  )!;
  assert.ok(relationship);
  const assessment = rows.find((row) => row.relationship === relationship.id);
  for (const status of ['supported', 'failed', 'unknown']) {
    assessment.status = status;
    assessment.reason = `Publisher reason for ${status}`;
    const html = render(props, relationship);
    assert.ok(
      html.includes(`Matching rule assessment: ${status[0].toUpperCase()}${status.slice(1)}`),
    );
    assert.ok(html.includes(assessment.reason));
    assert.match(html, /Declared requirement: .*Matching records required/);
    assert.match(html, /do not establish which records match/);
    assert.doesNotMatch(html, /badge good|Matches have not been checked/);
  }
  const missing = props.snapshot.catalog.relationships.find(
    (r) => r.resolution === 'unresolved_allowed' && !rows.some((row) => row.relationship === r.id),
  )!;
  assert.ok(missing);
  const html = render(props, missing);
  assert.match(html, /Unmatched records allowed/);
  assert.match(html, /Matching rule assessment: Unknown/);
  assert.match(html, /No usable matching-rule assessment is supplied/);
});

test('external existence preserves recorded not-assessed and unknown states', async () => {
  const props = await context();
  const assessment = props.assembly.relationshipAssessments.find(
    (row: any) => row.externalExistence === 'not_assessed',
  );
  const relationship = props.snapshot.catalog.relationships.find(
    (row) => row.id === assessment.relationship,
  )!;
  assert.match(
    render(props, relationship),
    /Whether this external target exists has not been assessed/,
  );
  props.assembly.relationshipAssessments = [];
  assert.match(render(props, relationship), /Whether this external target exists is unknown here/);
});

test('conflicting and malformed local assessments cannot be presented as rule support', async () => {
  const props = await context();
  const assessment = props.assembly.relationshipAssessments[0];
  const relationship = props.snapshot.catalog.relationships.find(
    (row) => row.id === assessment.relationship,
  )!;
  for (const patch of [
    { profile: { ...assessment.profile, commit: 'different-source' } },
    { scope: 'all-records-verified' },
    { status: 'passed' },
    { reason: { private: 'Unusable assessment detail' } },
    { externalExistence: 'verified' },
  ]) {
    props.assembly.relationshipAssessments = [
      { ...assessment, reason: 'Unusable assessment detail', ...patch },
    ];
    const html = render(props, relationship);
    assert.match(html, /Matching rule assessment: Unknown/);
    assert.doesNotMatch(html, /Matching rule assessment: Supported|Unusable assessment detail/);
  }
  props.assembly.relationshipAssessments = [assessment, { ...assessment }];
  assert.match(render(props, relationship), /Multiple assessments identify this relationship/);
  props.assembly.relationshipAssessmentScope = {
    status: 'unknown',
    reason: 'Assessment details are withheld.',
  };
  const scoped = render(props, relationship);
  assert.match(scoped, /Assessment details are withheld/);
  assert.doesNotMatch(
    scoped,
    /Matching rule assessment: Supported|Multiple assessments identify this relationship/,
  );
});
