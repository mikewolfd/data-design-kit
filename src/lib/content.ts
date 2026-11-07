import type {
  CatalogDataset,
  CatalogRepresentation,
  CatalogSnapshot,
  CatalogVersion,
} from '../domain/types';
import { publisherMetadata } from '../features/publisher-metadata';
import { versionsOf, words } from './display';

/** Keep publisher prose intact while separating its explicitly labelled limits. */
export function datasetIntroduction(snapshot: CatalogSnapshot, dataset: CatalogDataset) {
  const description = snapshot.definitions[dataset.alias]?.description;
  const coverageStart = description?.indexOf('Coverage limits:') ?? -1;
  const nullabilityStart = description?.indexOf('Nullability basis:') ?? -1;
  const technicalDescription = coverageStart >= 0 && nullabilityStart > coverageStart;
  const coverageNote =
    technicalDescription && description
      ? description.slice(coverageStart + 'Coverage limits:'.length, nullabilityStart).trim()
      : undefined;
  const describedPurpose = technicalDescription
    ? description?.slice(0, coverageStart).trim() || undefined
    : description;
  const purposeMarker = '\n\nDefinition purpose:';
  const purposeOffset = describedPurpose?.indexOf(purposeMarker) ?? -1;
  const purpose =
    purposeOffset >= 0 ? describedPurpose!.slice(purposeOffset + 2).trim() : describedPurpose;
  return {
    description,
    technicalDescription,
    coverageNote,
    purpose,
    summary: purpose !== dataset.rowMeaning ? purpose : undefined,
    rowMeaning:
      dataset.rowMeaning ||
      (typeof snapshot.definitions[dataset.alias]?.dataGranularityDescription === 'string'
        ? (snapshot.definitions[dataset.alias].dataGranularityDescription as string)
        : undefined),
  };
}

/** A visibly abbreviated excerpt is a navigation aid, not new publisher copy. */
export function excerpt(value: string | undefined, limit = 220): string | undefined {
  if (!value) return undefined;
  const text = value.replace(/\s+/g, ' ').trim();
  if (text.length <= limit) return text;
  const end = text.lastIndexOf(' ', limit);
  return `${text.slice(0, end > limit / 2 ? end : limit)}…`;
}

export type RecordAccess = {
  state:
    | 'available'
    | 'not_connected'
    | 'unknown'
    | 'unavailable'
    | 'withheld'
    | 'choose_version'
    | 'no_versions';
  label: string;
  detail: string;
};

/** Explicit resource purpose wins; absent richer metadata does not imply a notification service. */
export function isRecordResource(snapshot: CatalogSnapshot, representation: CatalogRepresentation) {
  const resource = publisherMetadata(snapshot).representations.get(representation.id)?.resource;
  return (
    (!resource?.kind || resource.kind === 'data') && resource?.destination?.kind !== 'notification'
  );
}

/** Describes a possible read, not the outcome of a request that has not run. */
export function recordAccess(
  snapshot: CatalogSnapshot,
  dataset: CatalogDataset,
  version?: CatalogVersion,
): RecordAccess {
  if (!versionsOf(snapshot, dataset).length)
    return {
      state: 'no_versions',
      label: 'No data versions listed',
      detail:
        'You can explore the dataset description and fields. This catalog does not include a data version to open.',
    };
  if (version?.referenceDisclosure === 'withheld')
    return {
      state: 'withheld',
      label: 'Withheld',
      detail: 'The catalog does not disclose the details needed to open this version’s records.',
    };
  if (
    !snapshot.capabilities.read ||
    (snapshot.capabilities.readDatasetIds !== undefined &&
      !snapshot.capabilities.readDatasetIds.includes(dataset.id))
  )
    return {
      state: 'not_connected',
      label: 'Not connected',
      detail:
        'You can explore this dataset’s description and fields. Reading its records is not connected to this portal.',
    };
  if (!version)
    return {
      state: 'choose_version',
      label: 'Choose a data version',
      detail: 'Choose a data version to view its access details.',
    };
  const listed = snapshot.catalog.representations.filter((row) => row.version === version.id);
  const files = listed.filter((row) => isRecordResource(snapshot, row));
  if (listed.length && !files.length)
    return {
      state: 'not_connected',
      label: 'Supporting resources only',
      detail:
        'The listed resources supply documentation, metadata or notifications. No record resource is offered for this version.',
    };
  if (
    version.retention === 'missing' ||
    (files.length > 0 && files.every((row) => row.availability === 'unavailable'))
  )
    return {
      state: 'unavailable',
      label: 'Unavailable',
      detail:
        'The catalog records this version or all of its files, tables and services as unavailable.',
    };
  if (
    version.retention === 'unknown' ||
    !files.length ||
    !files.some((row) => row.availability === 'available')
  )
    return {
      state: 'unknown',
      label: 'Unknown',
      detail: 'The catalog does not confirm whether this version can be opened.',
    };
  return {
    state: 'available',
    label: 'Available',
    detail:
      'A reader is connected for this dataset and the catalog lists an available file, table or service. Opening the records checks access for the request.',
  };
}

/** Any readable version qualifies for discovery; this never selects a version. */
export function datasetRecordAccess(
  snapshot: CatalogSnapshot,
  dataset: CatalogDataset,
): RecordAccess {
  const versions = versionsOf(snapshot, dataset);
  if (!versions.length) return recordAccess(snapshot, dataset);
  const states = versions.map((version) => recordAccess(snapshot, dataset, version));
  return (
    states.find((row) => row.state === 'available') ??
    states.find((row) => row.state === 'unknown') ??
    states.find((row) => row.state === 'not_connected') ??
    states.find((row) => row.state === 'unavailable') ??
    states[0]
  );
}

const enumLabels: Readonly<Record<string, string>> = {
  source_record: 'Source records',
  derived_record: 'Derived records',
  lookup: 'Reference data',
  many_to_one: 'Many records can match one',
  one_to_many: 'One record can match many',
  one_to_one: 'One record can match one',
  many_to_many: 'Many records can match many',
  same_release: 'Same release',
  dataset_version: 'Within one data version',
  unresolved_allowed: 'Unmatched records allowed',
  not_run: 'Not run',
  equal: 'Equal values',
};
export function enumLabel(value = ''): string {
  const label = enumLabels[value] ?? words(value);
  return label ? label[0].toUpperCase() + label.slice(1) : 'Not recorded';
}

export function formatLabel(mediaType?: string, kind?: string): string {
  const labels: Readonly<Record<string, string>> = {
    'application/json': 'JSON file',
    'application/x-ndjson': 'Line-separated JSON file',
    'application/vnd.apache.parquet': 'Parquet file',
    'application/x-parquet': 'Parquet file',
    'text/csv': 'CSV file',
    'text/tab-separated-values': 'Tab-separated text file',
  };
  const label =
    (mediaType && labels[mediaType]) ||
    mediaType ||
    (kind ? enumLabel(kind) : 'Format not recorded');
  return kind === 'service' || kind === 'table' ? label.replace(/ file$/, '') : label;
}
