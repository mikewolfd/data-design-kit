import { Notice, RecordLink } from '../../components/Primitives';
import type { CatalogRecipe, CatalogSnapshot } from '../../domain/types';
import { excerpt } from '../../lib/content';
import { safeLink } from '../../lib/display';
import {
  publisherMetadata,
  type PublisherEvidence,
  type PublisherRecord,
} from '../publisher-metadata';
import { RecordedDate } from './CoverageDates';
import { contextScopes, type DatasetContextProps, type MetadataScope } from './scope';

function EvidenceLinks({ records }: { records?: PublisherEvidence[] }) {
  if (!records?.length) return null;
  return (
    <ul className="context-links">
      {records.map((evidence, index) => {
        const href = 'url' in evidence && evidence.url ? safeLink(evidence.url) : undefined;
        return (
          <li key={index}>
            {href ? <a href={href}>{evidence.label}</a> : evidence.label}
            {evidence.sourceVersion && (
              <>
                {' '}
                · source version <code>{evidence.sourceVersion}</code>
              </>
            )}
            {'record' in evidence && evidence.record && <RecordLink record={evidence.record} />}
          </li>
        );
      })}
    </ul>
  );
}

export function PublisherMetadataNotice({ snapshot }: { snapshot: CatalogSnapshot }) {
  const { refusals } = publisherMetadata(snapshot);
  if (!refusals.length) return null;
  return (
    <Notice title="Some publisher metadata could not be shown" kind="warning">
      Standard catalog facts remain available.
      <details>
        <summary>See which publisher metadata was rejected</summary>
        <ul className="context-links">
          {refusals.map(({ extension, reason }) => (
            <li key={extension}>
              <code>{extension}</code> · {reason}
            </li>
          ))}
        </ul>
      </details>
    </Notice>
  );
}

export function Cautions(
  props: DatasetContextProps | { snapshot: CatalogSnapshot; recipe: Pick<CatalogRecipe, 'id'> },
) {
  const scopes: MetadataScope[] =
    'recipe' in props
      ? [
          {
            kind: 'recipe',
            label: 'This query',
            id: props.recipe.id,
            metadata: publisherMetadata(props.snapshot).recipes.get(props.recipe.id),
          },
        ]
      : contextScopes(props).scopes;

  return scopes.map(({ label, id, metadata }) => {
    const { cautions = [], qualityNotes, unknowns = [] } = metadata ?? {};
    if (!cautions.length && !qualityNotes && !unknowns.length) return null;
    return (
      <div className="context-cautions" key={id}>
        {cautions.map((caution, index) => (
          <Notice title={`Before using the data · ${label}`} kind="warning" key={index}>
            <p>{caution.summary}</p>
            {(caution.details || caution.evidence?.length) && (
              <details>
                <summary>Publisher’s explanation and evidence</summary>
                {caution.details && <p>{caution.details}</p>}
                <p>
                  Applies to <code>{id}</code>
                </p>
                <EvidenceLinks records={caution.evidence} />
              </details>
            )}
          </Notice>
        ))}
        {qualityNotes && (
          <Notice title={`Publisher data-quality note · ${label}`} kind="warning">
            <p>{excerpt(qualityNotes)}</p>
            <details>
              <summary>Full data-quality note and recorded scope</summary>
              <p>{qualityNotes}</p>
              <p>
                Applies to <code>{id}</code>
              </p>
            </details>
          </Notice>
        )}
        {unknowns.length > 0 && (
          <Notice title={`Open questions · ${label}`}>
            <ul className="context-links">
              {unknowns.map(({ fact, reason }) => (
                <li key={fact}>
                  <strong>{fact}</strong>
                  {reason && <> · {reason}</>}
                </li>
              ))}
            </ul>
          </Notice>
        )}
      </div>
    );
  });
}

const historyLabels: Record<NonNullable<PublisherRecord['history']>[number]['kind'], string> = {
  correction: 'Correction',
  renamedField: 'Field rename',
  coverage: 'Coverage change',
  compatibility: 'Compatibility note',
  note: 'Publisher note',
};

export function HistoryNotes(props: DatasetContextProps) {
  const { scopes } = contextScopes(props);
  const relevant = scopes.filter(({ metadata }) => metadata?.history?.length);
  if (!relevant.length) {
    return <p className="muted">Publisher change notes are not supplied for this selection.</p>;
  }
  return (
    <div className="dataset-context">
      {relevant.map(({ label, id, metadata }) => (
        <div className="context-scope" key={id}>
          <h3>{label}</h3>
          <ul className="context-links">
            {metadata?.history?.map(({ kind, description, date, evidence }, index) => (
              <li key={index}>
                <strong>{historyLabels[kind]}</strong>
                {date && (
                  <>
                    {' '}
                    · <RecordedDate value={date} />
                  </>
                )}
                <p>{description}</p>
                <details>
                  <summary>Recorded scope and original details</summary>
                  <p>
                    Applies to <code>{id}</code>
                  </p>
                  {date && (
                    <p>
                      Original date <code>{date}</code>
                    </p>
                  )}
                  <EvidenceLinks records={evidence} />
                </details>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
