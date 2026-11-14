import { createHash } from 'node:crypto';
import { test, expect, type Page, type APIRequestContext } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type {
  CatalogSnapshot,
  ExactBinding,
  ExactObject,
  QueryRequest,
} from '../../src/domain/types';

const extension = 'urn:ddk:publisher:discovery';
const assemblyKey = 'urn:ddk:catalog:assembly';
const commentRecipe = 'urn:test:workflow:comments-by-docket';
const ruleRecipe = 'urn:test:workflow:rule-by-id';
const rawComment =
  'A first paragraph.<br/>A &ldquo;quoted&rdquo; comment. <img src=x onerror="window.publisherInjected=true">';
const readableComment = 'A first paragraph.\nA “quoted” comment. Literal <b>text</b> remains text.';
const originalDocument = { id: 'COMMENT-001', text: rawComment };
const originalRecord = {
  uri: 'file:///retained/synthetic-comment-001.json',
  sha256: createHash('sha256').update(JSON.stringify(originalDocument)).digest('hex'),
};
const sourceUri = 'https://publisher.example/comments/COMMENT-001';
const sourceVersion = 'native-comment-version-17';

type Variant =
  | 'ordinary'
  | 'missing-original'
  | 'ambiguous-original'
  | 'missing-related-key'
  | 'changed-version';

/** Authored synthetic metadata and rows exercise the shared UI; no live source claims are made. */
async function fixture(page: Page, request: APIRequestContext, variant: Variant = 'ordinary') {
  const snapshot: CatalogSnapshot = await (await request.get('/api/catalogs/watershed')).json();
  const list = await (await request.get('/api/catalogs')).json();
  const comments = snapshot.catalog.datasets.find((item) => item.alias === 'observations')!;
  const rules = snapshot.catalog.datasets.find((item) => item.alias === 'stations')!;
  const commentVersion = snapshot.catalog.versions.find((item) =>
    item.id.endsWith('observations:v1'),
  )!;
  const ruleVersion = snapshot.catalog.versions.find((item) => item.id.endsWith('stations:v1'))!;
  const binding = (datasetId: string, versionId: string): ExactBinding => ({
    datasetId,
    versionId,
    representationId: snapshot.catalog.representations.find((item) => item.version === versionId)!
      .id,
  });
  const commentBinding = binding(
    comments.id,
    variant === 'changed-version'
      ? snapshot.catalog.versions.find((item) => item.id.endsWith('observations:v2'))!.id
      : commentVersion.id,
  );
  const ruleBinding = binding(rules.id, ruleVersion.id);
  comments.title = 'Synthetic retained comments';
  rules.title = 'Synthetic retained rules';
  const assembly = snapshot.catalog.extensions![assemblyKey] as any;
  for (const project of assembly.projectExtensions) delete project.extensions[extension];
  for (const [alias, fields] of [
    [
      comments.alias,
      [
        'comment_id',
        'docket_id',
        'rule_id',
        'raw_comment',
        'readable_comment',
        'source_uri',
        'source_sha256',
        'source_version',
      ],
    ],
    [rules.alias, ['rule_id', 'rule_text']],
  ] as const)
    assembly.datasetDefinitions[alias].properties.push(
      ...fields.map((name) => ({ name, logicalType: 'string' })),
    );
  snapshot.definitions = assembly.datasetDefinitions;
  const base = snapshot.catalog.recipes[0];
  snapshot.catalog.recipes.push(
    {
      ...base,
      id: commentRecipe,
      title: 'Find comments for a docket',
      inputs: { records: comments.alias },
      resultDataset: comments.alias,
      parameterOrder: ['docket_id'],
      parameters: {
        type: 'object',
        properties: { docket_id: { type: 'string', title: 'Docket identifier' } },
        required: ['docket_id'],
        additionalProperties: false,
      },
    },
    {
      ...base,
      id: ruleRecipe,
      title: 'Find the related rule',
      inputs: { rules: rules.alias },
      resultDataset: rules.alias,
      parameterOrder: ['rule_id'],
      parameters: {
        type: 'object',
        properties: { rule_id: { type: 'string', title: 'Rule identifier' } },
        required: ['rule_id'],
        additionalProperties: false,
      },
    },
  );
  snapshot.capabilities.query = true;
  snapshot.capabilities.evidence = true;
  snapshot.capabilities.queryRecipeIds = [commentRecipe, ruleRecipe];
  snapshot.catalog.sources = [
    {
      id: 'urn:test:comment-original:001',
      scope: 'Synthetic comment COMMENT-001, native version 17',
      outcome: 'ok',
      reference: {
        scheme: 'urn:test:source-version',
        authority: 'urn:test:publisher',
        value: { uri: sourceUri, version: sourceVersion },
      },
      content: {
        scheme: 'urn:ddk:version:local-file-sha256',
        authority: 'urn:test:archive',
        value: { location: originalRecord.uri, sha256: originalRecord.sha256 },
      },
      record: { uri: 'urn:test:capture-receipt' },
    },
  ];
  if (variant === 'ambiguous-original')
    snapshot.catalog.sources.push({
      ...snapshot.catalog.sources[0],
      id: 'urn:test:comment-original:duplicate',
    });
  const metadata = {
    schemaVersion: 1,
    workflows: [
      {
        id: 'comments',
        title: 'Find comments for a docket',
        summary: 'Search this synthetic retained cohort by its complete docket identifier.',
        recipeId: commentRecipe,
        bindings: { records: commentBinding },
        emptyMessage: 'No comments in this retained example cohort match this docket.',
      },
      {
        id: 'rule',
        title: 'Find the related rule',
        summary: 'Look up one rule identifier in the selected retained rule version.',
        recipeId: ruleRecipe,
        bindings: { rules: ruleBinding },
      },
    ],
    records: [
      {
        target: { kind: 'version', datasetId: comments.id, versionId: commentVersion.id },
        readableFields: ['readable_comment'],
        rowActions: [
          {
            id: 'original',
            label: 'Inspect this comment’s original',
            kind: 'original',
            fields: { uri: 'source_uri', sha256: 'source_sha256', version: 'source_version' },
            sourceReference: {
              scheme: 'urn:test:source-version',
              uriPath: ['uri'],
              versionPath: ['version'],
            },
          },
          {
            id: 'rule',
            label: 'View the related rule',
            kind: 'recipe',
            workflowId: 'rule',
            parameters: { rule_id: 'rule_id' },
          },
        ],
      },
    ],
  };
  assembly.projectExtensions.push({
    namespace: '',
    project: snapshot.catalog.project,
    extensions: { [extension]: metadata },
  });
  const rows: ExactObject[] = [
    {
      comment_id: 'COMMENT-001',
      docket_id: 'DEMO-42',
      rule_id: variant === 'missing-related-key' ? '' : 'RULE-9',
      raw_comment: rawComment,
      readable_comment: readableComment,
      source_uri: sourceUri,
      source_sha256: originalRecord.sha256,
      source_version: variant === 'missing-original' ? 'different-native-version' : sourceVersion,
    },
    {
      comment_id: 'COMMENT-002',
      docket_id: 'DEMO-42',
      rule_id: 'RULE-10',
      readable_comment: 'Second independently authored example comment.',
    },
  ];
  const queries: QueryRequest[] = [];
  const evidenceRequests: any[] = [];
  await page.route('**/api/catalogs', (route) =>
    route.fulfill({
      json: {
        catalogs: list.catalogs.filter((item: any) => item.id === 'watershed'),
        unavailable: [],
      },
    }),
  );
  await page.route('**/api/catalogs/watershed', (route) => route.fulfill({ json: snapshot }));
  await page.route('**/api/query', async (route) => {
    const body = route.request().postDataJSON() as QueryRequest;
    queries.push(body);
    const requested = body.parameters.docket_id;
    const resultRows =
      body.recipeId === ruleRecipe
        ? [{ rule_id: 'RULE-9', rule_text: 'The independently authored related rule.' }]
        : requested === 'DEMO-42'
          ? rows
          : [];
    const status = requested === 'REFUSED' ? 'refused' : requested === 'UNKNOWN' ? 'unknown' : 'ok';
    await route.fulfill({
      json: {
        status,
        reason:
          status === 'refused'
            ? 'The retained owner refused this exact request.'
            : status === 'unknown'
              ? 'The owner has not established an outcome.'
              : undefined,
        bindings: body.bindings,
        transport: 'ddk-exact-json-v1',
        columns:
          body.recipeId === ruleRecipe ? ['rule_id', 'rule_text'] : ['comment_id', 'docket_id'],
        rows: resultRows,
        returned: resultRows.length,
        total: resultRows.length,
        hasMore: false,
        execution: {
          kind: 'owner',
          recipeId: body.recipeId,
          inputs: Object.keys(body.bindings),
          contextualRelationships: [],
        },
      },
    });
  });
  await page.route('**/api/evidence', async (route) => {
    evidenceRequests.push(route.request().postDataJSON());
    await route.fulfill({
      json: {
        record: originalRecord,
        document: originalDocument,
        scope: 'Synthetic retained original',
      },
    });
  });
  return { snapshot, comments, commentBinding, ruleBinding, queries, evidenceRequests };
}

async function findComments(page: Page, value = 'DEMO-42') {
  await page.getByRole('textbox', { name: 'Docket identifier', exact: true }).fill(value);
  await page.getByRole('button', { name: 'Run lookup', exact: true }).click();
}

async function firstComment(page: Page) {
  await findComments(page);
  await page.getByRole('searchbox', { name: 'Search this page', exact: true }).fill('COMMENT-001');
  await page.getByRole('button', { name: 'Inspect record 01', exact: true }).click();
  return page.getByRole('region', { name: 'Record detail', exact: true });
}

test('fresh entry offers a bounded docket lookup and keeps its answer through dataset navigation and Back', async ({
  page,
  request,
}) => {
  const { commentBinding, queries } = await fixture(page, request);
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Start with a question', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Docket identifier', exact: true })).toHaveValue(
    '',
  );
  expect(queries).toHaveLength(0);
  const detail = await firstComment(page);
  await expect(
    page.getByRole('heading', { name: '2 records returned', exact: true }),
  ).toBeVisible();
  await expect(detail).toContainText(readableComment);
  expect(queries).toHaveLength(1);
  expect(queries[0]).toMatchObject({
    recipeId: commentRecipe,
    bindings: { records: commentBinding },
    parameters: { docket_id: 'DEMO-42' },
    limit: 25,
  });
  await page
    .getByRole('navigation', { name: 'Datasets', exact: true })
    .getByRole('button')
    .filter({ hasText: 'Synthetic retained rules' })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Synthetic retained rules', exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('searchbox', { name: 'Search this page', exact: true })).toHaveValue(
    'COMMENT-001',
  );
  await expect(detail).toContainText(readableComment);
  expect(queries).toHaveLength(1);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
});

for (const [key, heading, message] of [
  [
    'NO-MATCH',
    'No matching records',
    'No comments in this retained example cohort match this docket.',
  ],
  ['REFUSED', 'Lookup refused', 'The retained owner refused this exact request.'],
  ['UNKNOWN', 'Lookup outcome unknown', 'The owner has not established an outcome.'],
])
  test(`docket lookup keeps ${key} distinct from a known answer`, async ({ page, request }) => {
    const { queries } = await fixture(page, request);
    await page.goto('/');
    await findComments(page, key);
    await expect(page.getByText(heading, { exact: true })).toBeVisible();
    await expect(page.getByText(message, { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Inspect record 01', exact: true })).toHaveCount(
      0,
    );
    expect(queries[0].parameters).toEqual({ docket_id: key });
    if (key !== 'NO-MATCH')
      await expect(page.getByText('No matching records', { exact: true })).toHaveCount(0);
  });

test('a catalog search miss leads to an explicit record lookup using the searched identifier', async ({
  page,
  request,
}) => {
  const { comments, queries } = await fixture(page, request);
  await page.goto(`/?catalog=watershed&dataset=${encodeURIComponent(comments.id)}`);
  await page.getByRole('searchbox', { name: 'Search this catalog', exact: true }).fill('DEMO-42');
  await expect(page.getByText('No datasets match these filters.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Try record lookups', exact: true }).click();
  await page.getByRole('button', { name: 'use “DEMO-42” in this lookup', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Docket identifier', exact: true })).toHaveValue(
    'DEMO-42',
  );
  expect(queries).toHaveLength(0);
  await page.getByRole('button', { name: 'Run lookup', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'COMMENT-001', exact: true })).toBeVisible();
  expect(queries).toHaveLength(1);
});

test('record presentation escapes readable text, retains raw text, and opens only the exact mapped original', async ({
  page,
  request,
}) => {
  const { snapshot, evidenceRequests } = await fixture(page, request);
  await page.goto('/');
  const detail = await firstComment(page);
  await expect(detail.locator('.readable-record > p')).toHaveText(readableComment);
  await expect(detail.locator('img, script, .readable-record b')).toHaveCount(0);
  await detail.getByText('All fields, including original source text', { exact: true }).click();
  await expect(detail.getByText(rawComment, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as any).publisherInjected)).toBeUndefined();
  await detail
    .getByRole('button', { name: 'Inspect this comment’s original', exact: true })
    .click();
  await expect(
    detail
      .getByRole('status')
      .filter({ hasText: 'Original file matches its recorded fingerprint' }),
  ).toBeVisible();
  expect(evidenceRequests).toEqual([
    {
      catalogId: snapshot.id,
      catalogSha256: snapshot.identity.catalogSha256,
      record: originalRecord,
    },
  ]);
  await detail.getByText('View retained original', { exact: true }).click();
  await expect(detail.locator('.owner-evidence')).toContainText('COMMENT-001');
});

test('a related rule lookup uses the complete configured key and returns to the same comment', async ({
  page,
  request,
}) => {
  const { ruleBinding, queries } = await fixture(page, request);
  await page.goto('/');
  const detail = await firstComment(page);
  const trigger = detail.getByRole('button', { name: 'View the related rule', exact: true });
  await trigger.click();
  const related = page.getByRole('region', { name: 'Related record lookup', exact: true });
  await expect(related.getByRole('cell', { name: 'RULE-9', exact: true })).toBeVisible();
  expect(queries).toHaveLength(2);
  expect(queries[1]).toMatchObject({
    recipeId: ruleRecipe,
    parameters: { rule_id: 'RULE-9' },
    bindings: { rules: ruleBinding },
  });
  await related.getByRole('button', { name: 'Return to this record', exact: true }).click();
  await expect(related).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page.getByRole('searchbox', { name: 'Search this page', exact: true })).toHaveValue(
    'COMMENT-001',
  );
  await expect(detail).toContainText(readableComment);
  expect(queries).toHaveLength(2);
});

test('moving to the next record closes its related lookup without querying the new row implicitly', async ({ page, request }) => {
  const { queries } = await fixture(page, request);
  await page.goto('/');
  const detail = await firstComment(page);
  await detail.getByRole('button', { name: 'View the related rule', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Related record lookup' }).getByRole('cell', { name: 'RULE-9', exact: true })).toBeVisible();
  await detail.getByRole('button', { name: 'Next record', exact: true }).click();
  await expect(detail).toContainText('Second independently authored example comment.');
  await expect(page.getByRole('region', { name: 'Related record lookup' })).toHaveCount(0);
  expect(queries).toHaveLength(2);
});

for (const variant of [
  'missing-original',
  'ambiguous-original',
  'missing-related-key',
  'changed-version',
] as const)
  test(`row actions do not broaden the ${variant} target`, async ({ page, request }) => {
    const { evidenceRequests, queries } = await fixture(page, request, variant);
    await page.goto('/');
    const detail = await firstComment(page);
    if (variant === 'changed-version') {
      await expect(
        detail.getByRole('button', { name: 'Inspect this comment’s original', exact: true }),
      ).toHaveCount(0);
      await expect(
        detail.getByRole('button', { name: 'View the related rule', exact: true }),
      ).toHaveCount(0);
    } else if (variant === 'missing-related-key') {
      await expect(
        detail.getByRole('button', { name: 'View the related rule', exact: true }),
      ).toBeDisabled();
      await expect(detail).toContainText('lookup needs every configured key');
    } else {
      await expect(
        detail.getByRole('button', { name: 'Inspect this comment’s original', exact: true }),
      ).toBeDisabled();
      await expect(detail).toContainText(
        variant === 'ambiguous-original'
          ? 'More than one retained original matches'
          : 'No retained original matches',
      );
    }
    expect(evidenceRequests).toHaveLength(0);
    expect(queries).toHaveLength(1);
  });
