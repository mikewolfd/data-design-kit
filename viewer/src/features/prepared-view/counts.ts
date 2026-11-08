import { exactObjectField, exactStringify, isExactNumber, isObject } from '../../domain/exact';
import type {
  CatalogDataset,
  CatalogSnapshot,
  ExactBinding,
  ExactValue,
  ReadRequest,
  ReadResult,
} from '../../domain/types';
import { publisherMetadata, type PublisherPreparedView } from '../publisher-metadata';

type Category = { key: string; label: string; count: number };
type PreparedCounts = {
  view: PublisherPreparedView;
  fieldName: string;
  fieldLabel: string;
  categories: Category[];
  excludedArrays: number;
  excludedObjects: number;
  returned: number;
};

function matchesBinding(binding: ExactBinding, request: ReadRequest) {
  return (
    binding.datasetId === request.datasetId &&
    binding.versionId === request.versionId &&
    binding.representationId === request.representationId &&
    binding.releaseId === request.releaseId
  );
}
function boundPage(
  snapshot: CatalogSnapshot,
  dataset: CatalogDataset,
  request: ReadRequest,
  result: ReadResult,
) {
  if (
    result.status !== 'ok' ||
    result.transport !== 'ddk-exact-json-v1' ||
    result.rows.length !== result.returned ||
    !result.rows.every((row) => isObject(row) && !isExactNumber(row)) ||
    (request.limit !== undefined && result.returned > request.limit) ||
    request.catalogId !== snapshot.id ||
    request.catalogSha256 !== snapshot.identity.catalogSha256 ||
    request.datasetId !== dataset.id ||
    !snapshot.capabilities.read ||
    (snapshot.capabilities.readDatasetIds &&
      !snapshot.capabilities.readDatasetIds.includes(dataset.id)) ||
    !matchesBinding(result.binding, request) ||
    (result.readEvidence && !matchesBinding(result.readEvidence.consumed, request))
  )
    return false;

  const version = snapshot.catalog.versions.find(({ id }) => id === request.versionId);
  const representation = snapshot.catalog.representations.find(
    ({ id }) => id === request.representationId,
  );
  if (
    version?.dataset !== dataset.alias ||
    version.retention !== 'present' ||
    version.referenceDisclosure === 'withheld' ||
    representation?.version !== version.id ||
    representation.availability !== 'available'
  )
    return false;
  if (request.releaseId === undefined) return result.release === undefined;
  return (
    result.release?.id === request.releaseId &&
    snapshot.catalog.releases.some(
      (release) =>
        release.id === request.releaseId &&
        release.membership === 'complete' &&
        release.members.includes(version.id),
    )
  );
}
function category(value: ExactValue | undefined): { key: string; label: string } | undefined {
  if (value === undefined) return { key: 'missing', label: 'Field absent' };
  if (value === null) return { key: 'null', label: 'Null' };
  if (value === '') return { key: 'empty', label: 'Empty text' };
  if (typeof value === 'number' && !Number.isFinite(value)) return undefined;
  if (
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    typeof value === 'number' ||
    isExactNumber(value)
  ) {
    // JSON spelling preserves scalar type and exact number lexeme, including large integers.
    const spelling = exactStringify(value, 0);
    return { key: `value:${spelling}`, label: spelling };
  }
  return undefined;
}

/** Counts exact values for an admitted publisher question over one returned page. */
export function preparedCounts(
  snapshot: CatalogSnapshot,
  dataset: CatalogDataset,
  request: ReadRequest,
  result: ReadResult,
): PreparedCounts[] {
  if (!boundPage(snapshot, dataset, request, result)) return [];
  const views = publisherMetadata(snapshot).datasets.get(dataset.id)?.preparedViews ?? [];
  return views.flatMap((view) => {
    const [step] = view.field;
    if (!step || !('field' in step)) return [];
    const field = snapshot.definitions[dataset.alias]?.properties?.find(
      ({ name }) => name === step.field,
    );
    if (!field) return [];

    const categories = new Map<string, Category>();
    let excludedArrays = 0;
    let excludedObjects = 0;
    for (const row of result.rows) {
      const value = exactObjectField(row, step.field);
      const group = category(value);
      if (group) {
        const existing = categories.get(group.key);
        if (existing) existing.count += 1;
        else categories.set(group.key, { ...group, count: 1 });
      } else if (Array.isArray(value)) excludedArrays += 1;
      else if (isObject(value)) excludedObjects += 1;
      else return []; // A malformed transport scalar cannot participate in a reconciled view.
    }
    return [
      {
        view,
        fieldName: step.field,
        fieldLabel: field.businessName ?? step.field,
        categories: [...categories.values()].sort((left, right) => right.count - left.count),
        excludedArrays,
        excludedObjects,
        returned: result.returned,
      },
    ];
  });
}
