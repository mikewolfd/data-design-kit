import type {
  CatalogSnapshot,
  CatalogDataset,
  CatalogVersion,
  FieldPath,
  ExactValue,
} from '../domain/types';
import { formatExactValue } from '../domain/exact';

export const textValue = (value: unknown): string => {
  if (value === undefined) return 'Not recorded';
  if (value === null) return 'null';
  if (typeof value === 'object') return formatExactValue(value);
  return String(value);
};
export const shortId = (id: string = '') => id.split(/[:/#]/).filter(Boolean).slice(-1)[0] || id;
export const words = (s: string = '') => s.replaceAll('_', ' ').replaceAll('-', ' ');
export const pathLabel = (path: FieldPath) =>
  path.map((p) => ('field' in p ? `[${JSON.stringify(p.field)}]` : '[each]')).join('');
export const titleOf = (dataset: CatalogDataset) => {
  const supplied = dataset.title || dataset.alias;
  // Formatting only: do not infer a subject, preferred variant, or missing definition.
  if (/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(supplied)) {
    const label = supplied.replaceAll('_', ' ');
    return label[0].toUpperCase() + label.slice(1);
  }
  return dataset.title || words(dataset.alias);
};
export const versionsOf = (snapshot: CatalogSnapshot, dataset: CatalogDataset) =>
  snapshot.catalog.versions.filter((v) => v.dataset === dataset.alias || v.dataset === dataset.id);
export function selectedVersion(
  snapshot: CatalogSnapshot,
  dataset: CatalogDataset,
): CatalogVersion | undefined {
  const { catalog } = snapshot;
  if (!catalog.currentSelection) return undefined;
  const versions = versionsOf(snapshot, dataset);
  const matches = catalog.selections
    .filter(
      (s) =>
        s.authority === catalog.currentSelection!.authority &&
        s.purpose === catalog.currentSelection!.purpose,
    )
    .map((selection) => ({
      selection,
      versions: versions.filter((v) =>
        catalog.releases.find((r) => r.id === selection.release)?.members.includes(v.id),
      ),
    }))
    .filter((match) => match.versions.length > 0);
  return matches.length === 1 && matches[0].versions.length === 1
    ? matches[0].versions[0]
    : undefined;
}
export function releaseFor(snapshot: CatalogSnapshot, versionId?: string) {
  const releases = snapshot.catalog.releases.filter((r) => r.members.includes(versionId ?? ''));
  return releases.length === 1 && releases[0].membership === 'complete' ? releases[0] : undefined;
}
export function objectOf(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
export function safeLink(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
export function downloadJson(name: string, data: unknown) {
  const bytes = JSON.stringify(data, null, 2);
  if (new TextEncoder().encode(bytes).length > 1024 * 1024)
    throw new Error('This page is too large to download here. The download limit is 1 MiB.');
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function jsonInput(value: string, kind = 'string'): ExactValue {
  if (kind === 'string') return value;
  if (kind === 'number' || kind === 'integer') {
    if (
      !(kind === 'integer' ? /^-?(0|[1-9]\d*)$/ : /^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?$/).test(
        value,
      )
    )
      throw new Error(`Enter a valid ${kind}.`);
    return { $number: value };
  }
  if (kind === 'boolean') {
    if (!['true', 'false'].includes(value)) throw new Error('Enter true or false.');
    return value === 'true';
  }
  if (kind === 'null') return null;
  throw new Error(`This portal does not support entering values of type ${kind}.`);
}
