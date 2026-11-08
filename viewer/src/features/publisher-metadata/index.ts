import type { CatalogDataset, CatalogField, CatalogSnapshot, FieldPath } from '../../domain/types';
import type { DocumentedFieldValues } from '../field-dictionary/FieldValues';
import {
  calendarDate,
  PUBLISHER_DISCOVERY,
  safeWebUrl,
  validatePublisherExtension,
  type PublisherEvidence,
  type PublisherGuide,
  type PublisherRecord,
  type PublisherTarget,
} from './schema';

export type {
  DateKind,
  PublisherEvidence,
  PublisherGuide,
  PublisherLink,
  PublisherPreparedView,
  PublisherRecord,
  PublisherTarget,
} from './schema';
export { PUBLISHER_DISCOVERY } from './schema';

const SPICY_DISCOVERY = 'urn:spicy-regs:discovery';
const CONGRESS_RELATIONS = 'urn:congressional-tech:archive:upstream-relations';
const ASSEMBLY = 'urn:ddk:catalog:assembly';
const SPICY_PROJECT = 'urn:spicy-regs:definitions';
const CONGRESS_PROJECT = 'urn:congressional-tech:archive:project';

type DeclaredPublisher = { id: string; name: string; url: string; note: string; kind: string };
export type PublisherDatasetMetadata = Partial<PublisherRecord> & {
  logicalName?: string;
  interpretation?: string;
  subject?: string;
  coverageStatement?: string;
  observationDate?: string;
  qualityNotes?: string;
  retainedInputReason?: {
    kind: string;
    assurance: string;
    fields?: string[];
    evidenceSha256?: string;
  };
  documentedValues?: DocumentedFieldValues[];
  declaredPublishers?: DeclaredPublisher[];
  intendedSourceFamilies?: string[];
  attributionMeaning?: string;
};
export type ContextualRelation = {
  id: string;
  family: string;
  table: string;
  rowMeaning: string;
  keyColumns: string[];
  joins: { field: string; table: string }[];
  limits: string;
};
type ExtensionRefusal = {
  extension: string;
  code: 'malformed' | 'unsupported_version';
  reason: string;
};
type PublisherMetadata = {
  datasets: ReadonlyMap<string, PublisherDatasetMetadata>;
  versions: ReadonlyMap<string, PublisherRecord>;
  representations: ReadonlyMap<string, PublisherRecord>;
  recipes: ReadonlyMap<string, PublisherRecord>;
  guides: readonly PublisherGuide[];
  contextualRelations: readonly ContextualRelation[];
  refusals: readonly ExtensionRefusal[];
};
const cache = new WeakMap<CatalogSnapshot, PublisherMetadata>();

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function text(value: unknown, max = 4096): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= max;
}
function optionalText(value: unknown, max?: number): value is string | undefined {
  return value === undefined || text(value, max);
}
function rows(value: unknown, max: number): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.length <= max && value.every(object);
}
function names(value: unknown, max = 100): value is string[] {
  return Array.isArray(value) && value.length <= max && value.every((entry) => text(entry, 256));
}

function fieldPaths(
  definition: CatalogField,
  requested: string,
  parents: FieldPath = [],
  prefix = '',
): FieldPath[] {
  const matches: FieldPath[] = [];
  for (const field of definition.properties ?? []) {
    const name = prefix ? `${prefix}.${field.name}` : field.name;
    const path: FieldPath = [...parents, { field: field.name }];
    if (name === requested) matches.push(path);
    if (requested.startsWith(`${name}.`)) {
      matches.push(...fieldPaths(field, requested, path, name));
    }
  }
  if (definition.items) {
    matches.push(...fieldPaths(definition.items, requested, [...parents, { each: true }], prefix));
  }
  return matches;
}

function documentedValues(value: unknown, definition?: CatalogField) {
  if (!object(value) || Object.keys(value).length > 32 || !definition)
    throw new Error('The documented code list has no matching disclosed definition.');
  return Object.entries(value).map(([key, entry]): DocumentedFieldValues => {
    const matches = fieldPaths(definition, key);
    if (
      matches.length !== 1 ||
      !object(entry) ||
      !text(entry.domain, 256) ||
      !text(entry.locator) ||
      !text(entry.source_url, 2048) ||
      !safeWebUrl(entry.source_url) ||
      typeof entry.checked !== 'boolean' ||
      !optionalText(entry.caveat) ||
      !optionalText(entry.observed_at, 40) ||
      (entry.unobserved !== undefined && !names(entry.unobserved, 1024)) ||
      !rows(entry.values, 1024) ||
      (entry.observed_off_list !== undefined && !rows(entry.observed_off_list, 1024))
    ) {
      throw new Error('A documented code list has an invalid field binding or source.');
    }
    const values = entry.values.map(({ value, label }) => {
      if (typeof value !== 'string' || value.length > 4096 || !optionalText(label))
        throw new Error('A documented code or label is malformed.');
      return { value, ...(label === undefined ? {} : { label }) };
    });
    const observedOffList = entry.observed_off_list?.map(({ value, reason }) => {
      if (typeof value !== 'string' || value.length > 4096 || !text(reason))
        throw new Error('An observed code or reason is malformed.');
      return { value, reason };
    });
    return {
      path: matches[0],
      domain: entry.domain,
      locator: entry.locator,
      sourceUrl: entry.source_url,
      checked: entry.checked,
      values,
      observedAt: entry.observed_at,
      observedOffList,
      unobserved: entry.unobserved,
      caveat: entry.caveat,
    };
  });
}
function inputReason(value: unknown): PublisherDatasetMetadata['retainedInputReason'] {
  if (!object(value)) throw new Error('A SpicyRegs retained-input note is malformed.');
  const { kind, assurance, fields, evidenceSha256 } = value;
  if (
    !text(kind, 256) ||
    !text(assurance) ||
    (fields !== undefined && !names(fields)) ||
    (evidenceSha256 !== undefined &&
      (typeof evidenceSha256 !== 'string' || !/^[0-9a-f]{64}$/.test(evidenceSha256)))
  ) {
    throw new Error('A SpicyRegs retained-input note is malformed.');
  }
  return { kind, assurance, fields, evidenceSha256 };
}
function spicyMetadata(value: Record<string, unknown>, snapshot: CatalogSnapshot) {
  if (
    !object(value.datasets) ||
    Object.keys(value.datasets).length > 1024 ||
    !rows(value.publishers, 256) ||
    !rows(value.sourceFamilies, 512) ||
    !rows(value.datasetAttribution, 1024) ||
    !text(value.attributionMeaning)
  ) {
    throw new Error('The SpicyRegs discovery inventories are malformed.');
  }
  const publishers = new Map<string, DeclaredPublisher>();
  for (const { id, name, url, note, kind } of value.publishers) {
    if (
      !text(id, 256) ||
      publishers.has(id) ||
      !text(name, 256) ||
      !text(url, 2048) ||
      !safeWebUrl(url) ||
      typeof note !== 'string' ||
      note.length > 4096 ||
      !text(kind, 256)
    ) {
      throw new Error('A declared SpicyRegs publisher is malformed.');
    }
    publishers.set(id, { id, name, url, note, kind });
  }
  const logicalNames = new Set(
    Object.values(value.datasets)
      .filter(object)
      .map((row) => row.logicalName),
  );
  const attribution = new Map<
    string,
    { declaredPublishers: DeclaredPublisher[]; intendedSourceFamilies: string[] }
  >();
  for (const { datasetName, publisherIds, inputFamilies } of value.datasetAttribution) {
    if (
      !text(datasetName, 256) ||
      !logicalNames.has(datasetName) ||
      attribution.has(datasetName) ||
      !names(publisherIds) ||
      publisherIds.some((id) => !publishers.has(id)) ||
      !names(inputFamilies)
    ) {
      throw new Error('A SpicyRegs attribution row has an invalid publisher or logical name.');
    }
    attribution.set(datasetName, {
      declaredPublishers: publisherIds.map((id) => publishers.get(id)!),
      intendedSourceFamilies: inputFamilies,
    });
  }
  const datasets = new Map(snapshot.catalog.datasets.map((row) => [row.alias, row]));
  const result = new Map<string, PublisherDatasetMetadata>();
  for (const [alias, entry] of Object.entries(value.datasets)) {
    const dataset = datasets.get(alias);
    if (
      !dataset ||
      !object(entry) ||
      !text(entry.logicalName, 256) ||
      !text(entry.interpretation, 256) ||
      !optionalText(entry.subject, 256) ||
      !optionalText(entry.coverageStatement) ||
      !optionalText(entry.qualityNotes) ||
      (entry.observationDate !== undefined &&
        (typeof entry.observationDate !== 'string' || !calendarDate(entry.observationDate)))
    ) {
      throw new Error('A SpicyRegs discovery row has an invalid dataset binding or description.');
    }
    const reason =
      entry.retainedInputReason === undefined ? undefined : inputReason(entry.retainedInputReason);
    result.set(dataset.id, {
      logicalName: entry.logicalName,
      interpretation: entry.interpretation,
      subject: entry.subject,
      coverageStatement: entry.coverageStatement,
      observationDate: entry.observationDate,
      qualityNotes: entry.qualityNotes,
      retainedInputReason: reason,
      ...attribution.get(entry.logicalName),
      attributionMeaning: value.attributionMeaning,
      ...(entry.documentedValues === undefined
        ? {}
        : {
            documentedValues: documentedValues(entry.documentedValues, snapshot.definitions[alias]),
          }),
    });
  }
  return result;
}
function congressMetadata(value: unknown): ContextualRelation[] {
  if (!rows(value, 100)) throw new Error('The Congress upstream relation inventory is malformed.');
  const ids = new Set<string>();
  return value.map(({ id, family, table, row_meaning, key_columns, joins, limits }) => {
    if (
      !text(id, 256) ||
      ids.has(id) ||
      !text(family, 256) ||
      !text(table, 256) ||
      !text(row_meaning) ||
      !names(key_columns) ||
      !rows(joins, 100) ||
      !text(limits)
    ) {
      throw new Error('A Congress upstream relation has invalid metadata.');
    }
    ids.add(id);
    const declaredJoins = joins.map(({ field, table: target }) => {
      if (!text(field, 256) || !text(target, 256))
        throw new Error('A declared upstream join is malformed.');
      return { field, table: target };
    });
    return {
      id,
      family,
      table,
      rowMeaning: row_meaning,
      keyColumns: key_columns,
      joins: declaredJoins,
      limits,
    };
  });
}
function extensionValues(snapshot: CatalogSnapshot, key: string): unknown[] {
  const assembly = snapshot.catalog.extensions?.[ASSEMBLY];
  if (!object(assembly) || !Array.isArray(assembly.projectExtensions)) return [];
  return assembly.projectExtensions.flatMap((row: unknown) => {
    if (
      !object(row) ||
      row.namespace !== '' ||
      !object(row.project) ||
      row.project.id !== snapshot.catalog.project.id ||
      row.project.version !== snapshot.catalog.project.version ||
      !object(row.extensions) ||
      !Object.hasOwn(row.extensions, key)
    )
      return [];
    return [row.extensions[key]];
  });
}
function exactDefinition(
  dataset: CatalogDataset,
  target: Extract<PublisherTarget, { kind: 'dataset' }>,
) {
  const expected = dataset.definition;
  const provided = target.definition;
  return (
    provided.contractId === expected.contractId &&
    provided.version === expected.version &&
    provided.object === expected.object &&
    provided.sourceSha256 === expected.source.sha256
  );
}
function targetKey(target: PublisherTarget) {
  switch (target.kind) {
    case 'dataset':
      return target.datasetId;
    case 'version':
      return target.versionId;
    case 'representation':
      return target.representationId;
    case 'recipe':
      return target.recipeId;
  }
}
function validateBindings(
  records: PublisherRecord[],
  guides: PublisherGuide[],
  snapshot: CatalogSnapshot,
) {
  const datasetById = new Map(snapshot.catalog.datasets.map((row) => [row.id, row]));
  const versionById = new Map(snapshot.catalog.versions.map((row) => [row.id, row]));
  const resourceById = new Map(snapshot.catalog.representations.map((row) => [row.id, row]));
  const recipeIds = new Set(snapshot.catalog.recipes.map((row) => row.id));
  const refs = new Set<string>();
  for (const ref of [
    ...snapshot.catalog.sourceInventory,
    ...snapshot.catalog.datasets.map(({ definition }) => definition.source),
    ...snapshot.catalog.products.map(({ definition }) => definition),
    ...snapshot.catalog.productions.map(({ definition }) => definition),
    ...[
      snapshot.catalog.versions,
      snapshot.catalog.sources,
      snapshot.catalog.representations,
      snapshot.catalog.releases,
      snapshot.catalog.selections,
      snapshot.catalog.runs,
      snapshot.catalog.checks,
    ].flatMap((records) => records.map(({ record }) => record)),
  ]) {
    if (ref?.sha256) refs.add(JSON.stringify([ref.uri, ref.sha256]));
  }
  function evidenceExists(evidence: PublisherEvidence[] = []) {
    return evidence.every(
      ({ record }) => !record || refs.has(JSON.stringify([record.uri, record.sha256])),
    );
  }
  function exists(target: PublisherTarget | { kind: 'external' }) {
    if (target.kind === 'external') return true;
    if (target.kind === 'recipe') return recipeIds.has(target.recipeId);
    const dataset = datasetById.get(target.datasetId);
    if (!dataset) return false;
    if (target.kind === 'dataset') return exactDefinition(dataset, target);
    if (![dataset.alias, dataset.id].includes(versionById.get(target.versionId)?.dataset ?? ''))
      return false;
    return (
      target.kind === 'version' ||
      resourceById.get(target.representationId)?.version === target.versionId
    );
  }
  function periodIsOrdered(coverage?: PublisherRecord['coverage']) {
    const period = coverage?.period;
    return !period?.start || !period?.end || period.start <= period.end;
  }
  function validPreparedViews(record: PublisherRecord) {
    if (record.preparedViews === undefined) return true;
    if (record.target.kind !== 'dataset') return false;
    const dataset = datasetById.get(record.target.datasetId);
    if (!dataset) return false;
    const definition = snapshot.definitions[dataset.alias];
    const scalarTypes = new Set([
      'string',
      'boolean',
      'integer',
      'number',
      'date',
      'timestamp',
      'time',
    ]);
    const virtualNames = new Set(
      snapshot.catalog.identities
        .filter((identity) => identity.dataset === dataset.alias)
        .flatMap((identity) => identity.fields)
        .flatMap(({ path, virtual }) =>
          virtual && path.length === 1 && 'field' in path[0] ? [path[0].field] : [],
        ),
    );
    const ids = new Set<string>();
    return record.preparedViews.every(({ id, field: [step] }) => {
      if (ids.has(id) || !step || !('field' in step) || virtualNames.has(step.field)) return false;
      ids.add(id);
      const fields = definition?.properties?.filter(({ name }) => name === step.field) ?? [];
      const [field] = fields;
      return (
        fields.length === 1 &&
        !field.items &&
        !field.properties &&
        scalarTypes.has(field.logicalType ?? '')
      );
    });
  }
  const seen = new Set<string>();
  for (const record of records) {
    const key = JSON.stringify([record.target.kind, targetKey(record.target)]);
    if (
      seen.has(key) ||
      !exists(record.target) ||
      record.reuse?.some(({ target }) => !exists(target)) ||
      !periodIsOrdered(record.coverage) ||
      !validPreparedViews(record) ||
      record.cautions?.some(({ evidence }) => !evidenceExists(evidence)) ||
      record.history?.some(({ evidence }) => !evidenceExists(evidence))
    )
      return false;
    seen.add(key);
    if (
      record.target.kind !== 'dataset' &&
      (record.alternateNames ||
        record.variantDescription ||
        record.topics ||
        record.updateFrequency)
    )
      return false;
    if (record.target.kind !== 'representation' && record.resource) return false;
    if (
      record.resource?.kind === 'notification' &&
      ['directFile', 'externalApi'].includes(record.resource.destination?.kind ?? '')
    )
      return false;
    if (record.dates && new Set(record.dates.map(({ kind }) => kind)).size !== record.dates.length)
      return false;
    if (record.topics && new Set(record.topics.map(({ id }) => id)).size !== record.topics.length)
      return false;
    if (
      record.unknowns &&
      new Set(record.unknowns.map(({ fact }) => fact)).size !== record.unknowns.length
    )
      return false;
  }
  const guideIds = new Set<string>();
  for (const guide of guides) {
    if (
      guideIds.has(guide.id) ||
      !periodIsOrdered(guide.coverage) ||
      guide.links.some(({ target }) => !exists(target)) ||
      guide.links.some(({ target }) => {
        if (target.kind !== 'recipe') return false;
        const recipe = snapshot.catalog.recipes.find((item) => item.id === target.recipeId);
        return (
          !recipe ||
          ![recipe.resultDataset, ...Object.values(recipe.inputs)].some((alias) =>
            snapshot.catalog.datasets.some(
              (dataset) => dataset.alias === alias || dataset.id === alias,
            ),
          )
        );
      }) ||
      !evidenceExists(guide.evidence)
    )
      return false;
    guideIds.add(guide.id);
  }
  return true;
}

/** Read supported publisher facts from the already admitted, immutable catalog snapshot. */
export function publisherMetadata(snapshot: CatalogSnapshot): PublisherMetadata {
  const cached = cache.get(snapshot);
  if (cached) return cached;
  const datasets = new Map<string, PublisherDatasetMetadata>();
  const versions = new Map<string, PublisherRecord>();
  const representations = new Map<string, PublisherRecord>();
  const recipes = new Map<string, PublisherRecord>();
  const refusals: ExtensionRefusal[] = [];
  let guides: PublisherGuide[] = [];
  let contextualRelations: ContextualRelation[] = [];
  function consume(key: string, versioned: boolean, read: (value: unknown) => void) {
    const values = extensionValues(snapshot, key);
    if (!values.length) return;
    try {
      if (values.length !== 1)
        throw new Error('More than one declaration claims the selected project.');
      const value = values[0];
      if (
        versioned &&
        object(value) &&
        Number.isSafeInteger(value.schemaVersion) &&
        value.schemaVersion !== 1
      ) {
        refusals.push({
          extension: key,
          code: 'unsupported_version',
          reason: 'This publisher metadata version is not supported.',
        });
        return;
      }
      read(value);
    } catch (error) {
      refusals.push({
        extension: key,
        code: 'malformed',
        reason: error instanceof Error ? error.message : 'Publisher metadata could not be read.',
      });
    }
  }
  if (snapshot.catalog.project.id === SPICY_PROJECT) {
    consume(SPICY_DISCOVERY, true, (value) => {
      if (!object(value) || value.schemaVersion !== 1)
        throw new Error('The SpicyRegs discovery version is missing.');
      for (const [id, entry] of spicyMetadata(value, snapshot)) datasets.set(id, entry);
    });
  }
  if (snapshot.catalog.project.id === CONGRESS_PROJECT) {
    consume(CONGRESS_RELATIONS, false, (value) => {
      contextualRelations = congressMetadata(value);
    });
  }
  consume(PUBLISHER_DISCOVERY, true, (value) => {
    if (
      !object(value) ||
      new TextEncoder().encode(JSON.stringify(value)).length > 512 * 1024 ||
      !validatePublisherExtension(value)
    )
      throw new Error('Publisher metadata has an invalid field, date, link, or size.');
    const records = value.records ?? [];
    const suppliedGuides = value.guides ?? [];
    if (!validateBindings(records, suppliedGuides, snapshot))
      throw new Error(
        'Publisher metadata contains a duplicate or mismatched target, or an invalid scope.',
      );
    for (const record of records) {
      const id = targetKey(record.target);
      switch (record.target.kind) {
        case 'dataset':
          datasets.set(id, { ...datasets.get(id), ...record });
          break;
        case 'version':
          versions.set(id, record);
          break;
        case 'representation':
          representations.set(id, record);
          break;
        case 'recipe':
          recipes.set(id, record);
          break;
      }
    }
    guides = suppliedGuides;
  });
  const result = {
    datasets,
    versions,
    representations,
    recipes,
    guides,
    contextualRelations,
    refusals,
  };
  cache.set(snapshot, result);
  return result;
}
