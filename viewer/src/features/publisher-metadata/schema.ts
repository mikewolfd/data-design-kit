import Ajv from 'ajv';
import type { CatalogDataset, ExactBinding, FieldPath } from '../../domain/types';

export const PUBLISHER_DISCOVERY = 'urn:ddk:publisher:discovery';

export type DatasetTarget = {
  kind: 'dataset';
  datasetId: string;
  definition: Pick<CatalogDataset['definition'], 'contractId' | 'version' | 'object'> & {
    sourceSha256: string;
  };
};
export type PublisherTarget =
  | DatasetTarget
  | { kind: 'version'; datasetId: string; versionId: string }
  | { kind: 'representation'; datasetId: string; versionId: string; representationId: string }
  | { kind: 'recipe'; recipeId: string };
export type PublisherLink = {
  label: string;
  purpose: string;
  target: PublisherTarget | { kind: 'external'; url: string };
};
export type PublisherEvidence = { label: string; sourceVersion?: string } & (
  { url: string; record?: never } | { url?: never; record: { uri: string; sha256: string } }
);
type Person = { name: string; url?: string };
type Coverage = {
  period?: { start?: string; end?: string };
  geography?: string;
  population?: string;
  inclusion?: string;
  exclusions?: string;
};
export type DateKind =
  | 'sourcePublished'
  | 'dataUpdated'
  | 'metadataUpdated'
  | 'retrieved'
  | 'nextExpectedUpdate'
  | 'coverageObserved';
export type PublisherPreparedView = {
  id: string;
  question: string;
  kind: 'valueCounts';
  field: FieldPath;
};
export type PublisherWorkflow = {
  id: string;
  title: string;
  summary: string;
  recipeId: string;
  bindings: Record<string, Omit<ExactBinding, 'releaseId'>>;
  defaults?: Record<string, string>;
  emptyMessage?: string;
};
export type PublisherRowAction = { id: string; label: string } & (
  | { kind: 'recipe'; workflowId: string; parameters: Record<string, string> }
  | {
      kind: 'original';
      fields: { uri: string; sha256: string; version: string };
      sourceReference: { scheme: string; uriPath: string[]; versionPath: string[] };
    }
);
export type PublisherRecord = {
  target: PublisherTarget;
  alternateNames?: { name: string; kind: 'former' | 'alternate' }[];
  variantDescription?: string;
  topics?: { id: string; label: string }[];
  coverage?: Coverage;
  dates?: { kind: DateKind; value: string }[];
  updateFrequency?: string;
  cautions?: { summary: string; details?: string; evidence?: PublisherEvidence[] }[];
  publishers?: Person[];
  terms?: { label: string; scope: 'data' | 'portalText' | 'derivedView'; url?: string }[];
  support?: { label: string; url: string }[];
  citation?: { text: string; originalIdentifier?: string };
  history?: {
    kind: 'correction' | 'renamedField' | 'coverage' | 'compatibility' | 'note';
    description: string;
    date?: string;
    evidence?: PublisherEvidence[];
  }[];
  resource?: {
    kind?: 'data' | 'documentation' | 'metadata' | 'notification';
    destination?: {
      kind: 'publisherPage' | 'documentation' | 'externalApi' | 'directFile' | 'notification';
      url: string;
    };
    purpose?: string;
    byteSize?: number;
    accessRequirements?: string;
    requestLimits?: string;
  };
  reuse?: PublisherLink[];
  preparedViews?: PublisherPreparedView[];
  rowActions?: PublisherRowAction[];
  readableFields?: string[];
  unknowns?: { fact: string; reason?: string }[];
};
export type PublisherGuide = {
  id: string;
  title: string;
  question: string;
  summary: string;
  author: Person;
  reviewedOn: string;
  reviewTrigger?: string;
  coverage?: Coverage;
  links: PublisherLink[];
  evidence: PublisherEvidence[];
};
type PublisherExtension = {
  schemaVersion: 1;
  records?: PublisherRecord[];
  guides?: PublisherGuide[];
  workflows?: PublisherWorkflow[];
};

const ajv = new Ajv({ allErrors: false });
export function safeWebUrl(value: string) {
  if (!/^https?:\/\//i.test(value) || /[\\\s\u0000-\u001f\u007f]/.test(value)) return false;
  try {
    const url = new URL(value);
    return Boolean(url.hostname) && !url.username && !url.password;
  } catch {
    return false;
  }
}
function safeSupportUrl(value: string) {
  return (
    safeWebUrl(value) ||
    (/^mailto:[A-Z0-9.!#$%&'*+\/=?^_\x60{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i.test(value) &&
      !/[%?&#]/.test(value))
  );
}
export function calendarDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(value);
  return Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}
function suppliedDate(value: string) {
  if (calendarDate(value)) return true;
  return (
    /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,9})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(
      value,
    ) &&
    calendarDate(value.slice(0, 10)) &&
    Number.isFinite(Date.parse(value))
  );
}
ajv.addFormat('web-url', safeWebUrl);
ajv.addFormat('support-url', safeSupportUrl);
ajv.addFormat('calendar-date', calendarDate);
ajv.addFormat('supplied-date', suppliedDate);
const text = (maxLength: number) => ({ type: 'string', minLength: 1, maxLength, pattern: '\\S' });
const short = text(256);
const detail = text(4096);
const identity = text(2048);
const url = { ...identity, format: 'web-url' };
const date = { ...text(40), format: 'supplied-date' };
const calendar = { ...text(10), format: 'calendar-date' };
const list = (items: object, maxItems = 20) => ({ type: 'array', items, maxItems });
const object = (properties: Record<string, object>, required: string[] = []) => ({
  type: 'object',
  properties,
  required,
  additionalProperties: false,
});
const choice = (...values: string[]) => ({ type: 'string', enum: values });
const versionProps = { datasetId: identity, versionId: identity };
const target = {
  oneOf: [
    object(
      {
        kind: choice('dataset'),
        datasetId: identity,
        definition: object(
          {
            contractId: identity,
            version: short,
            object: identity,
            sourceSha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
          },
          ['contractId', 'version', 'object', 'sourceSha256'],
        ),
      },
      ['kind', 'datasetId', 'definition'],
    ),
    object({ kind: choice('version'), ...versionProps }, ['kind', 'datasetId', 'versionId']),
    object(
      {
        kind: choice('representation'),
        ...versionProps,
        representationId: identity,
      },
      ['kind', 'datasetId', 'versionId', 'representationId'],
    ),
    object({ kind: choice('recipe'), recipeId: identity }, ['kind', 'recipeId']),
  ],
};
const link = object(
  {
    label: short,
    purpose: detail,
    target: {
      oneOf: [...target.oneOf, object({ kind: choice('external'), url }, ['kind', 'url'])],
    },
  },
  ['label', 'purpose', 'target'],
);
const evidence = list({
  oneOf: [
    object({ label: short, url, sourceVersion: short }, ['label', 'url']),
    object(
      {
        label: short,
        record: object(
          {
            uri: identity,
            sha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
          },
          ['uri', 'sha256'],
        ),
        sourceVersion: short,
      },
      ['label', 'record'],
    ),
  ],
});
const person = object({ name: short, url }, ['name']);
const coverage = object({
  period: { ...object({ start: calendar, end: calendar }), minProperties: 1 },
  geography: detail,
  population: detail,
  inclusion: detail,
  exclusions: detail,
});
const namedFields = {
  type: 'object',
  additionalProperties: short,
  maxProperties: 16,
  minProperties: 1,
};
const path = { ...list(short, 8), minItems: 1 };
const rowAction = {
  oneOf: [
    object(
      {
        id: short,
        label: short,
        kind: choice('recipe'),
        workflowId: short,
        parameters: namedFields,
      },
      ['id', 'label', 'kind', 'workflowId', 'parameters'],
    ),
    object(
      {
        id: short,
        label: short,
        kind: choice('original'),
        fields: object({ uri: short, sha256: short, version: short }, ['uri', 'sha256', 'version']),
        sourceReference: object({ scheme: identity, uriPath: path, versionPath: path }, [
          'scheme',
          'uriPath',
          'versionPath',
        ]),
      },
      ['id', 'label', 'kind', 'fields', 'sourceReference'],
    ),
  ],
};
const workflow = object(
  {
    id: short,
    title: short,
    summary: detail,
    recipeId: identity,
    bindings: {
      type: 'object',
      minProperties: 1,
      maxProperties: 16,
      additionalProperties: object({ ...versionProps, representationId: identity }, [
        'datasetId',
        'versionId',
        'representationId',
      ]),
    },
    defaults: {
      type: 'object',
      maxProperties: 16,
      additionalProperties: { type: 'string', maxLength: 4096 },
    },
    emptyMessage: detail,
  },
  ['id', 'title', 'summary', 'recipeId', 'bindings'],
);
const record = object(
  {
    target,
    alternateNames: list(
      object({ name: short, kind: choice('former', 'alternate') }, ['name', 'kind']),
    ),
    variantDescription: detail,
    topics: list(object({ id: short, label: short }, ['id', 'label'])),
    coverage,
    dates: list(
      object(
        {
          kind: choice(
            'sourcePublished',
            'dataUpdated',
            'metadataUpdated',
            'retrieved',
            'nextExpectedUpdate',
            'coverageObserved',
          ),
          value: date,
        },
        ['kind', 'value'],
      ),
      6,
    ),
    updateFrequency: short,
    cautions: list(object({ summary: short, details: detail, evidence }, ['summary'])),
    publishers: list(person),
    terms: list(
      object({ label: short, scope: choice('data', 'portalText', 'derivedView'), url }, [
        'label',
        'scope',
      ]),
    ),
    support: list(
      object({ label: short, url: { ...identity, format: 'support-url' } }, ['label', 'url']),
    ),
    citation: object({ text: detail, originalIdentifier: identity }, ['text']),
    history: list(
      object(
        {
          kind: choice('correction', 'renamedField', 'coverage', 'compatibility', 'note'),
          description: detail,
          date,
          evidence,
        },
        ['kind', 'description'],
      ),
    ),
    resource: {
      ...object({
        kind: choice('data', 'documentation', 'metadata', 'notification'),
        destination: object(
          {
            kind: choice(
              'publisherPage',
              'documentation',
              'externalApi',
              'directFile',
              'notification',
            ),
            url,
          },
          ['kind', 'url'],
        ),
        purpose: detail,
        byteSize: { type: 'integer', minimum: 0, maximum: Number.MAX_SAFE_INTEGER },
        accessRequirements: detail,
        requestLimits: detail,
      }),
      minProperties: 1,
    },
    reuse: list(link),
    rowActions: list(rowAction, 8),
    readableFields: { ...list(short, 8), uniqueItems: true },
    preparedViews: list(
      object(
        {
          id: short,
          question: detail,
          kind: choice('valueCounts'),
          field: { ...list(object({ field: short }, ['field']), 1), minItems: 1 },
        },
        ['id', 'question', 'kind', 'field'],
      ),
      5,
    ),
    unknowns: list(object({ fact: short, reason: detail }, ['fact'])),
  },
  ['target'],
);
const guide = object(
  {
    id: short,
    title: short,
    question: detail,
    summary: detail,
    author: person,
    reviewedOn: calendar,
    reviewTrigger: detail,
    coverage,
    links: { ...list(link), minItems: 1 },
    evidence: { ...evidence, minItems: 1 },
  },
  ['id', 'title', 'question', 'summary', 'author', 'reviewedOn', 'links', 'evidence'],
);

export const validatePublisherExtension = ajv.compile<PublisherExtension>(
  object(
    {
      schemaVersion: { type: 'integer', const: 1 },
      records: list(record, 1024),
      guides: list(guide, 32),
      workflows: list(workflow, 16),
    },
    ['schemaVersion'],
  ),
);
