import { useState } from 'react';
import { Badge, Raw, RecordLink } from '../../components/Primitives';
import { exactStringify } from '../../domain/exact';
import { safeLink, versionsOf } from '../../lib/display';
import type { PublisherDatasetMetadata, PublisherRecord } from '../publisher-metadata';
import { contextScopes, type DatasetContextProps } from './scope';

function NamedLink({ label, url }: { label: string; url?: string }) {
  const href = url && safeLink(url);
  return href ? <a href={href}>{label}</a> : <>{label}</>;
}

function Publishers({ metadata }: { metadata?: PublisherDatasetMetadata }) {
  const {
    publishers = [],
    declaredPublishers = [],
    intendedSourceFamilies = [],
    attributionMeaning,
  } = metadata ?? {};
  return (
    <>
      {publishers.length > 0 && (
        <ul className="context-links">
          {publishers.map(({ name, url }, index) => (
            <li key={index}>
              <NamedLink label={name} url={url} />
            </li>
          ))}
        </ul>
      )}
      {declaredPublishers.length > 0 && (
        <>
          <p>Declared source publishers</p>
          <ul className="context-links">
            {declaredPublishers.map(({ id, name, url, note }) => (
              <li key={id}>
                <NamedLink label={name} url={url} />
                {note && <> · {note}</>}
              </li>
            ))}
          </ul>
        </>
      )}
      {intendedSourceFamilies.length > 0 && (
        <details>
          <summary>Intended source families</summary>
          <ul className="context-links">
            {intendedSourceFamilies.map((family, index) => (
              <li key={index}>{family}</li>
            ))}
          </ul>
        </details>
      )}
      {(declaredPublishers.length > 0 || intendedSourceFamilies.length > 0) &&
        attributionMeaning && <p className="muted">{attributionMeaning}</p>}
      {!publishers.length && !declaredPublishers.length && (
        <p className="muted">Source publisher attribution not supplied for this scope.</p>
      )}
    </>
  );
}

export function ProvenanceContext(props: DatasetContextProps) {
  const { dataset, snapshot } = props;
  const { scopes, selectedVersion } = contextScopes(props);
  const datasetMetadata = scopes[0].metadata;
  const sources = snapshot.catalog.sources.filter(({ id }) =>
    selectedVersion?.sources.includes(id),
  );
  const producers = snapshot.catalog.productions.filter(
    ({ outputs }) => outputs.includes(dataset.alias) || outputs.includes(dataset.id),
  );
  const runs = selectedVersion
    ? snapshot.catalog.runs.filter(({ outputs }) => outputs.includes(selectedVersion.id))
    : [];
  const reason = datasetMetadata?.retainedInputReason;
  return (
    <div className="dataset-context">
      {snapshot.exampleData === 'synthetic' && <p>This catalog contains synthetic example data.</p>}
      {snapshot.exampleData === 'authored' && <p>This catalog contains authored example data.</p>}
      {snapshot.mode === 'fixture' && !snapshot.exampleData && (
        <p>This is an example catalog with fixture records.</p>
      )}
      <div className="context-scope">
        <h3>Definition and declared sources</h3>
        <Publishers metadata={datasetMetadata} />
        {reason && (
          <>
            <p>{reason.assurance}</p>
            <Raw value={reason} label="Publisher’s retained-input declaration" />
          </>
        )}
        <details>
          <summary>Exact dataset definition reference</summary>
          <p>
            <code>{dataset.definition.object}</code> · revision{' '}
            <code>{dataset.definition.version}</code>
          </p>
          <p>
            Definition identifier <code>{dataset.definition.contractId}</code>
          </p>
          <RecordLink record={dataset.definition.source} />
        </details>
      </div>
      <div className="context-scope">
        <h3>Recorded source observations for this version</h3>
        {selectedVersion && (
          <details>
            <summary>Exact selected data version</summary>
            <p>
              <code>{selectedVersion.id}</code>
            </p>
            <RecordLink record={selectedVersion.record} />
            {selectedVersion.referenceDisclosure === 'withheld' ? (
              <p>The original version reference is withheld.</p>
            ) : (
              <Raw value={selectedVersion.reference} label="Original version reference" />
            )}
          </details>
        )}
        {sources.length > 0 ? (
          <ul className="context-links">
            {sources.map((source) => (
              <li key={source.id}>
                <p>{source.scope}</p>
                <Badge status={source.outcome} />
                <details>
                  <summary>Exact source and capture references</summary>
                  <p>
                    <code>{source.id}</code>
                  </p>
                  <RecordLink record={source.record} />
                  <Raw
                    value={{ reference: source.reference, content: source.content }}
                    label="Original source references"
                  />
                </details>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            {selectedVersion
              ? 'No source observations are linked to this version. Source coverage remains unknown.'
              : versionsOf(snapshot, dataset).length
                ? 'Choose a data version to identify its recorded source observations.'
                : 'This catalog lists no data versions for this dataset. Source observations remain unknown.'}
          </p>
        )}
      </div>
      <div className="context-scope">
        <h3>How the data was processed</h3>
        {producers.length > 0 && (
          <details>
            <summary>Declared processing plans</summary>
            <p>These plans identify intended inputs and outputs.</p>
            {producers.map((production) => (
              <Raw key={production.identity.id} value={production} label={production.alias} />
            ))}
          </details>
        )}
        {runs.length > 0 ? (
          <ul className="context-links">
            {runs.map((run) => (
              <li key={run.id}>
                <Badge status={run.outcome} />
                <p>
                  Recorded input coverage <Badge status={run.inputCoverage.status} /> ·{' '}
                  {run.inputCoverage.scope}
                </p>
                <details>
                  <summary>Processing record and exact input references</summary>
                  <p>
                    <code>{run.id}</code>
                  </p>
                  <RecordLink record={run.record} />
                  <Raw
                    value={{ reference: run.reference, inputs: run.inputs, outputs: run.outputs }}
                    label="Original operation references"
                  />
                </details>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            How records were processed remains unknown. No processing events are linked to this
            selection.
          </p>
        )}
      </div>
    </div>
  );
}

function CopyText({ label, value }: { label: string; value: string }) {
  const [status, setStatus] = useState('');
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setStatus('Copied.');
    } catch {
      setStatus('Clipboard access is unavailable. Select and copy the text shown here.');
    }
  }
  return (
    <div>
      <button className="context-copy" type="button" onClick={() => void copy()}>
        {label}
      </button>
      <span className="context-copy-status" role="status">
        {status}
      </span>
    </div>
  );
}

const termLabels: Record<NonNullable<PublisherRecord['terms']>[number]['scope'], string> = {
  data: 'Data reuse terms',
  portalText: 'Portal text reuse terms',
  derivedView: 'Derived view reuse terms',
};

export function citationWithReference(
  { text, originalIdentifier }: NonNullable<PublisherRecord['citation']>,
  versionReference?: string,
) {
  const parts = [text];
  if (originalIdentifier) parts.push(`Original publisher identifier\n${originalIdentifier}`);
  if (versionReference)
    parts.push(`Exact selected-version reference from the viewer\n${versionReference}`);
  return parts.join('\n\n');
}

export function AttributionContext(props: DatasetContextProps) {
  const { snapshot, dataset, releaseId } = props;
  const { scopes, selectedVersion, selectedResource } = contextScopes(props);
  const release =
    selectedVersion &&
    snapshot.catalog.releases.find(
      (candidate) => candidate.id === releaseId && candidate.members.includes(selectedVersion.id),
    );
  const selectedScope = scopes[scopes.length - 1];
  const originalIdentifier =
    selectedScope.kind !== 'dataset' && selectedScope.metadata?.citation?.originalIdentifier;
  const versionReference =
    selectedVersion &&
    exactStringify({
      catalogId: snapshot.catalog.id,
      catalogSha256: snapshot.identity.catalogSha256,
      datasetId: dataset.id,
      versionId: selectedVersion.id,
      ...(selectedVersion.referenceDisclosure === 'withheld'
        ? { referenceDisclosure: 'withheld' }
        : { originalVersionReference: selectedVersion.reference }),
      ...(selectedResource ? { representationId: selectedResource.id } : {}),
      ...(release ? { releaseId: release.id } : {}),
      ...(originalIdentifier ? { originalCitationIdentifier: originalIdentifier } : {}),
    });
  return (
    <div className="dataset-context">
      {scopes.map(({ label, id, metadata }) => (
        <div className="context-scope" key={id}>
          <h3>{label}</h3>
          <Publishers metadata={metadata} />
          {!metadata?.terms?.some(({ scope }) => scope === 'data') && (
            <p className="muted">Data reuse terms not supplied for this scope.</p>
          )}
          {metadata?.terms?.map(({ scope, label: name, url }, index) => (
            <p key={index}>
              <strong>{termLabels[scope]}</strong> <NamedLink label={name} url={url} />
            </p>
          ))}
          {metadata?.support?.length ? (
            <>
              <p>Publisher’s help links</p>
              <ul className="context-links">
                {metadata.support.map(({ label: name, url }, index) => (
                  <li key={index}>
                    {url.startsWith('mailto:') ? (
                      <a href={url}>{name}</a>
                    ) : (
                      <NamedLink label={name} url={url} />
                    )}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="muted">A support route is not supplied for this scope.</p>
          )}
          {metadata?.citation ? (
            <>
              <p className="context-citation">{metadata.citation.text}</p>
              {metadata.citation.originalIdentifier && (
                <p>
                  Original identifier <code>{metadata.citation.originalIdentifier}</code>
                </p>
              )}
              <CopyText
                label={`Copy publisher citation for ${label.toLowerCase()}${versionReference ? ' with selected reference' : ''}`}
                value={citationWithReference(metadata.citation, versionReference)}
              />
            </>
          ) : (
            <p className="muted">Publisher citation not supplied for this scope.</p>
          )}
        </div>
      ))}
      <details>
        <summary>Recorded source definition</summary>
        <RecordLink record={dataset.definition.source} />
      </details>
      {selectedResource && (
        <details>
          <summary>Recorded source for the selected resource</summary>
          <RecordLink record={selectedResource.record} />
        </details>
      )}
      {versionReference && (
        <details>
          <summary>Exact reference for the selected data version</summary>
          {selectedVersion?.referenceDisclosure === 'withheld' && (
            <p>The original version reference is withheld.</p>
          )}
          {releaseId && !release && <p>Release membership for this version was not confirmed.</p>}
          <pre>{versionReference}</pre>
          <CopyText label="Copy exact selected-version reference" value={versionReference} />
        </details>
      )}
    </div>
  );
}
