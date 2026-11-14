import type { CatalogSnapshot, ExactBinding, ExactObject, RecordRef } from '../../domain/types';
import { exactObjectField, isObject } from '../../domain/exact';
import { originalSourceRecord } from '../dataset-context/CapturedSources';
import { publisherMetadata, type PublisherRowAction, type PublisherWorkflow } from './index';

type Resolution =
  | { kind: 'unavailable'; reason: string }
  | { kind: 'original'; record: RecordRef }
  | { kind: 'recipe'; workflow: PublisherWorkflow; parameters: Record<string, string> };

function pathValue(value: unknown, path: string[]): unknown {
  for (const name of path) value = isObject(value) ? exactObjectField(value, name) : undefined;
  return value;
}
export function recordMetadata(snapshot: CatalogSnapshot, binding: ExactBinding) {
  const dataset = snapshot.catalog.datasets.find(({ id }) => id === binding.datasetId);
  const version = snapshot.catalog.versions.find(({ id }) => id === binding.versionId);
  const resource = snapshot.catalog.representations.find(
    ({ id }) => id === binding.representationId,
  );
  if (
    !dataset ||
    !version ||
    ![dataset.id, dataset.alias].includes(version.dataset) ||
    resource?.version !== version.id
  )
    return undefined;
  return publisherMetadata(snapshot).versions.get(version.id);
}

/** A missing key or ambiguous original is a refusal, never a broader search or first-match choice. */
export function resolveRowAction(
  snapshot: CatalogSnapshot,
  row: ExactObject,
  action: PublisherRowAction,
): Resolution {
  const read = (field: string) => {
    const value = exactObjectField(row, field);
    return typeof value === 'string' && value.trim() ? value : undefined;
  };
  if (action.kind === 'recipe') {
    const workflow = publisherMetadata(snapshot).workflows.find(
      ({ id }) => id === action.workflowId,
    );
    if (!workflow)
      return { kind: 'unavailable', reason: 'The exact lookup is unavailable in this catalog.' };
    const parameters: Record<string, string> = {};
    for (const [name, field] of Object.entries(action.parameters)) {
      const value = read(field);
      if (value === undefined)
        return {
          kind: 'unavailable',
          reason: `This record has no ${field}; the lookup needs every configured key.`,
        };
      parameters[name] = value;
    }
    return { kind: 'recipe', workflow, parameters };
  }
  const uri = read(action.fields.uri),
    sha256 = read(action.fields.sha256),
    version = read(action.fields.version);
  if (!uri || !sha256 || !version)
    return {
      kind: 'unavailable',
      reason: 'The record is missing an original URI, digest, or source version.',
    };
  const matches = snapshot.catalog.sources.filter(
    (source) =>
      source.reference?.scheme === action.sourceReference.scheme &&
      pathValue(source.reference.value, action.sourceReference.uriPath) === uri &&
      pathValue(source.reference.value, action.sourceReference.versionPath) === version &&
      originalSourceRecord(source.content)?.sha256 === sha256,
  );
  if (matches.length !== 1)
    return {
      kind: 'unavailable',
      reason: matches.length
        ? 'More than one retained original matches these exact source keys. No original was selected.'
        : 'No retained original matches this URI, digest, and source version in this catalog.',
    };
  return { kind: 'original', record: originalSourceRecord(matches[0].content)! };
}

/** Only a result dataset that is itself an exact query input can use that version's row actions. */
export function workflowResultBinding(snapshot: CatalogSnapshot, workflow: PublisherWorkflow) {
  const recipe = snapshot.catalog.recipes.find(({ id }) => id === workflow.recipeId);
  const dataset = snapshot.catalog.datasets.find(
    (entry) => entry.id === recipe?.resultDataset || entry.alias === recipe?.resultDataset,
  );
  const matches = Object.values(workflow.bindings).filter(
    (binding) => binding.datasetId === dataset?.id,
  );
  return matches.length === 1 ? matches[0] : undefined;
}
