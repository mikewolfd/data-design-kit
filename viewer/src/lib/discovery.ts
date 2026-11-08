import type { CatalogDataset, CatalogSnapshot } from '../domain/types';
import { publisherMetadata } from '../features/publisher-metadata';
import { datasetIntroduction, datasetRecordAccess, formatLabel } from './content';
import { titleOf, versionsOf } from './display';

export const facetLabels = {
  topic: 'Topic',
  publisher: 'Declared source publisher',
  place: 'Geographic coverage',
  period: 'Data period',
  format: 'Format of listed resources',
  update: 'Declared update frequency',
} as const;
export type Facet = keyof typeof facetLabels;
export type FacetSelection = Partial<Record<Facet, string>>;
export const missingFacet = '__unknown__';
const distinct = (values: (string | undefined)[]) => [
  ...new Set(values.filter((value): value is string => Boolean(value))),
];
const facetValue = (value: string) => `value:${value}`;
export type DiscoveryItem = ReturnType<typeof discoveryItems>[number];

/** Index only disclosed dataset names and scoped facts; never field descriptions or other catalogs. */
export function discoveryItems(snapshot: CatalogSnapshot) {
  const metadata = publisherMetadata(snapshot);
  return snapshot.catalog.datasets.map((dataset) => {
    const supplied = metadata.datasets.get(dataset.id);
    const versions = versionsOf(snapshot, dataset);
    const versionIds = new Set(versions.map((version) => version.id));
    const scoped = [supplied, ...versions.map((version) => metadata.versions.get(version.id))];
    const period = scoped.flatMap((row) => {
      const range = row?.coverage?.period;
      return range
        ? [`${range.start ?? 'Start not supplied'} to ${range.end ?? 'End not supplied'}`]
        : [];
    });
    const facets: Record<Facet, string[]> = {
      topic: distinct([
        supplied?.subject,
        ...(supplied?.topics?.map((topic) => topic.label) ?? []),
      ]),
      publisher: distinct([
        ...(supplied?.publishers?.map((publisher) => publisher.name) ?? []),
        ...(supplied?.declaredPublishers?.map((publisher) => publisher.name) ?? []),
      ]),
      place: distinct(scoped.map((row) => row?.coverage?.geography)),
      period: distinct(period),
      format: distinct(
        snapshot.catalog.representations
          .filter((row) => versionIds.has(row.version))
          .map((row) => (row.mediaType ? formatLabel(row.mediaType, row.kind) : undefined)),
      ),
      update: distinct(scoped.map((row) => row?.updateFrequency)),
    };
    const introduction = datasetIntroduction(snapshot, dataset);
    const alternateNames = supplied?.alternateNames ?? [];
    const indexedNames = [
      dataset.id,
      dataset.alias,
      titleOf(dataset),
      ...alternateNames.map((name) => name.name),
    ];
    const searchable = [
      ...indexedNames,
      introduction.purpose,
      introduction.rowMeaning,
      supplied?.variantDescription,
    ]
      .filter(Boolean)
      .join(' ')
      .toLocaleLowerCase();
    return {
      dataset,
      introduction,
      facets,
      alternateNames,
      access: datasetRecordAccess(snapshot, dataset),
      sourceIds: distinct(versions.flatMap((version) => version.sources)),
      variant: supplied?.variantDescription,
      coverage: supplied?.coverageStatement,
      searchRank(query: string) {
        const normalized = query.trim().toLocaleLowerCase();
        if (!normalized) return 3;
        if ([dataset.id, dataset.alias].some((value) => value.toLocaleLowerCase() === normalized))
          return 0;
        if (indexedNames.some((value) => value.toLocaleLowerCase() === normalized)) return 1;
        return searchable.includes(normalized) ? 2 : -1;
      },
    };
  });
}

export function matchesFacets(item: DiscoveryItem, selected: FacetSelection, except?: Facet) {
  return (Object.keys(facetLabels) as Facet[]).every((facet) => {
    const selection = selected[facet];
    return (
      !selection ||
      facet === except ||
      (selection === missingFacet
        ? !item.facets[facet].length
        : item.facets[facet].some((value) => facetValue(value) === selection))
    );
  });
}

/** Counts are distinct datasets after other filters; one dataset can appear in several options. */
export function facetOptions(items: DiscoveryItem[], selected: FacetSelection, facet: Facet) {
  const counts = new Map<string, number>();
  let missing = 0;
  for (const item of items) {
    if (!matchesFacets(item, selected, facet)) continue;
    if (!item.facets[facet].length) missing++;
    for (const value of item.facets[facet]) counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  const active = selected[facet];
  if (active?.startsWith('value:') && !counts.has(active.slice(6))) counts.set(active.slice(6), 0);
  return [
    ...[...counts]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, count]) => ({ value: facetValue(label), label, count })),
    { value: missingFacet, label: 'Unknown or not supplied', count: missing },
  ];
}

export function datasetLabel(snapshot: CatalogSnapshot, dataset: CatalogDataset) {
  return (
    publisherMetadata(snapshot).datasets.get(dataset.id)?.variantDescription || titleOf(dataset)
  );
}
