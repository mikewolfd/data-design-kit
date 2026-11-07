import type { Catalog, CatalogDataset, CatalogSnapshot, CatalogVersion } from '../../domain/types';
import { publisherMetadata, type PublisherDatasetMetadata } from '../publisher-metadata';

export type DatasetContextProps = {
  snapshot: CatalogSnapshot;
  dataset: CatalogDataset;
  version?: CatalogVersion;
  representation?: Catalog['representations'][number];
  releaseId?: string;
};

export type MetadataScope = {
  kind: 'dataset' | 'version' | 'representation' | 'recipe';
  label: string;
  id: string;
  metadata?: PublisherDatasetMetadata;
};

export function contextScopes({ snapshot, dataset, version, representation }: DatasetContextProps) {
  const metadata = publisherMetadata(snapshot);
  const selectedVersion =
    version &&
    snapshot.catalog.versions.find(
      (candidate) =>
        candidate.id === version.id &&
        (candidate.dataset === dataset.alias || candidate.dataset === dataset.id),
    );
  const selectedResource =
    selectedVersion &&
    representation &&
    snapshot.catalog.representations.find(
      (candidate) => candidate.id === representation.id && candidate.version === selectedVersion.id,
    );
  const scopes: MetadataScope[] = [
    {
      kind: 'dataset',
      label: 'Dataset definition',
      id: dataset.id,
      metadata: metadata.datasets.get(dataset.id),
    },
  ];
  if (selectedVersion)
    scopes.push({
      kind: 'version',
      label: 'Selected data version',
      id: selectedVersion.id,
      metadata: metadata.versions.get(selectedVersion.id),
    });
  if (selectedResource)
    scopes.push({
      kind: 'representation',
      label: 'Selected resource',
      id: selectedResource.id,
      metadata: metadata.representations.get(selectedResource.id),
    });
  return { scopes, selectedVersion, selectedResource };
}
