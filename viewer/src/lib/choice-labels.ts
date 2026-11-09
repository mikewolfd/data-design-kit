import type {
  CatalogDataset,
  CatalogRepresentation,
  CatalogSnapshot,
  CatalogVersion,
} from '../domain/types';
import { formatLabel, enumLabel } from './content';
import { titleOf } from './display';
import { formatExactValue, isExactNumber } from '../domain/exact';

export type ChoiceLabel = { id: string; label: string };

function observedScope(version: CatalogVersion): string | undefined {
  if (version.referenceDisclosure === 'withheld' || version.coverage?.length !== 1) return;
  const { observed, unit, scope } = version.coverage[0];
  if (!(typeof observed === 'number' && Number.isFinite(observed)) && !isExactNumber(observed))
    return;
  return `${formatExactValue(observed)} ${unit} observed (${scope})`;
}

// The catalog has exact native references, but no human version-label field.
// Reference syntax alone cannot establish that a value is a meaningful label.
function distinguish(choices: ChoiceLabel[]): ChoiceLabel[] {
  const counts = new Map<string, number>();
  const seen = new Map<string, number>();
  for (const { label } of choices) counts.set(label, (counts.get(label) ?? 0) + 1);
  return choices.map(({ id, label }) => {
    const position = (seen.get(label) ?? 0) + 1;
    seen.set(label, position);
    // Choice numbers identify positions in this list, never version chronology.
    return { id, label: (counts.get(label) ?? 0) > 1 ? `${label} · Choice ${position}` : label };
  });
}

export function versionChoices(
  snapshot: CatalogSnapshot,
  dataset: CatalogDataset,
  versions: CatalogVersion[],
): ChoiceLabel[] {
  return distinguish(
    versions.map((version) => {
      const formats = [
        ...new Set(
          snapshot.catalog.representations
            .filter((row) => row.version === version.id)
            .map((row) => formatLabel(row.mediaType, row.kind)),
        ),
      ];
      return {
        id: version.id,
        label: [
          titleOf(dataset),
          'Version label not supplied',
          ...formats,
          observedScope(version),
          version.referenceDisclosure === 'withheld' ? 'Details withheld' : undefined,
        ]
          .filter(Boolean)
          .join(' · '),
      };
    }),
  );
}

export function representationChoices(
  dataset: CatalogDataset,
  representations: CatalogRepresentation[],
): ChoiceLabel[] {
  return distinguish(
    representations.map((row) => ({
      id: row.id,
      label: `${titleOf(dataset)} · ${formatLabel(row.mediaType, row.kind)} · ${
        row.availability === 'unknown' ? 'Availability unknown' : enumLabel(row.availability)
      }`,
    })),
  );
}
