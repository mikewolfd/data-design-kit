import type {
  CatalogDataset,
  CatalogRepresentation,
  CatalogSnapshot,
  CatalogVersion,
} from '../../domain/types';
import { enumLabel, formatLabel, isRecordResource } from '../../lib/content';
import { representationChoices } from '../../lib/choice-labels';
import { publisherMetadata, type PublisherLink } from '../publisher-metadata';
import { safeWebUrl, type PublisherRecord } from '../publisher-metadata/schema';
import { VIEWER_READ_ROWS } from './results';

const category = {
  data: 'Data resource',
  documentation: 'Supporting documentation',
  metadata: 'Metadata resource',
  notification: 'Notification service',
};
const destinationLabel = {
  publisherPage: 'Open publisher page',
  documentation: 'Open documentation',
  externalApi: 'Open programmatic access route',
  directFile: 'Open publisher file',
  notification: 'Open notification service',
};
const termsScope = { data: 'Data', portalText: 'Portal text', derivedView: 'Derived view' };
const readAccess = {
  available: `A reader is connected here. Up to ${VIEWER_READ_ROWS} records are requested per page. Opening records checks this exact resource.`,
  not_connected: 'This viewer has no record reader for this dataset.',
  not_records: 'This resource has no record-preview action here.',
  withheld: 'The exact reference is withheld.',
  unavailable: 'The catalog records this resource or its version as unavailable.',
  unknown: 'The catalog does not establish whether this resource can be opened here.',
};

type ResourceAccess = keyof typeof readAccess;

export function resourceRecordAccess(
  snapshot: CatalogSnapshot,
  dataset: CatalogDataset,
  version: CatalogVersion,
  representation: CatalogRepresentation,
): ResourceAccess {
  if (
    representation.version !== version.id ||
    ![dataset.alias, dataset.id].includes(version.dataset)
  )
    return 'unavailable';
  if (version.referenceDisclosure === 'withheld') return 'withheld';
  if (version.retention === 'missing' || representation.availability === 'unavailable')
    return 'unavailable';
  if (!isRecordResource(snapshot, representation)) return 'not_records';
  if (version.retention === 'unknown' || representation.availability === 'unknown')
    return 'unknown';
  if (
    !snapshot.capabilities.read ||
    snapshot.capabilities.readDatasetIds?.includes(dataset.id) === false
  )
    return 'not_connected';
  return 'available';
}

function ExternalLink({ url, children }: { url: string; children: string }) {
  if (!safeWebUrl(url)) return null;
  return (
    <a href={url} target="_blank" rel="noreferrer">
      {children} · {new URL(url).hostname}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

function ReuseLinks({ links }: { links?: readonly PublisherLink[] }) {
  const external = links?.filter((entry) => entry.target.kind === 'external') ?? [];
  return external.length > 0 ? (
    <ul className="resource-reuse-links">
      {external.map(
        ({ label, purpose, target }, index) =>
          target.kind === 'external' && (
            <li key={`${target.url}:${index}`}>
              <ExternalLink url={target.url}>{label}</ExternalLink>
              <p>{purpose}</p>
            </li>
          ),
      )}
    </ul>
  ) : null;
}

function Scope({ metadata }: { metadata?: PublisherRecord }) {
  const coverage = metadata?.coverage;
  if (!coverage || !Object.values(coverage).some(Boolean)) return 'Resource scope not supplied';
  const period = coverage.period;
  return (
    <>
      {period?.start && period.end ? (
        <p>
          {period.start} to {period.end}
        </p>
      ) : period?.start ? (
        <p>From {period.start}</p>
      ) : (
        period?.end && <p>Through {period.end}</p>
      )}
      {coverage.geography && <p>{coverage.geography}</p>}
      {coverage.population && <p>{coverage.population}</p>}
      {coverage.inclusion && <p>{coverage.inclusion}</p>}
      {coverage.exclusions && <p>{coverage.exclusions}</p>}
    </>
  );
}

export function ResourceDetails({
  snapshot,
  dataset,
  version,
  selectedRepresentationId,
  onSelectRepresentation,
}: {
  snapshot: CatalogSnapshot;
  dataset: CatalogDataset;
  version?: CatalogVersion;
  selectedRepresentationId?: string;
  onSelectRepresentation?: (id: string) => void;
}) {
  const publisher = publisherMetadata(snapshot);
  const representations =
    version && [dataset.alias, dataset.id].includes(version.dataset)
      ? snapshot.catalog.representations.filter((row) => row.version === version.id)
      : [];
  const choices = representationChoices(dataset, representations);
  if (!version || representations.length === 0) {
    const hasVersions = snapshot.catalog.versions.some((row) =>
      [dataset.alias, dataset.id].includes(row.dataset),
    );
    return (
      <section className="resource-details">
        <h3>Files, tables and services</h3>
        <p>
          {version
            ? 'The catalog lists no resource for this version.'
            : hasVersions
              ? 'Choose a listed data version to see its resources.'
              : 'This catalog provides dataset and field descriptions. It lists no data versions or resources for this dataset.'}
        </p>
        {!version && <ReuseLinks links={publisher.datasets.get(dataset.id)?.reuse} />}
      </section>
    );
  }
  return (
    <section className="resource-details">
      <h3>Files, tables and services</h3>
      {representations.map((representation, index) => {
        const metadata = publisher.representations.get(representation.id);
        const resource = metadata?.resource;
        const access = resourceRecordAccess(snapshot, dataset, version, representation);
        const destination = resource?.destination;
        const suppliedDestination =
          access !== 'withheld' &&
          (destination?.kind !== 'directFile' || representation.availability === 'available')
            ? destination
            : undefined;
        const listed =
          !destination &&
          access !== 'withheld' &&
          representation.availability === 'available' &&
          representation.location &&
          safeWebUrl(representation.location)
            ? representation.location
            : undefined;
        const update = metadata?.dates?.find((date) => date.kind === 'dataUpdated');
        const selected =
          selectedRepresentationId === representation.id ||
          (!selectedRepresentationId && representations.length === 1);
        return (
          <details key={representation.id} open={selected || undefined}>
            <summary>
              {choices[index].label}
              {selected && ' · Selected'}
            </summary>
            <p>{resource?.kind ? category[resource.kind] : enumLabel(representation.kind)}</p>
            <dl className="resource-facts">
              <div>
                <dt>Purpose</dt>
                <dd>{resource?.purpose ?? 'Purpose not supplied'}</dd>
              </div>
              <div>
                <dt>Format</dt>
                <dd>{formatLabel(representation.mediaType, representation.kind)}</dd>
              </div>
              <div>
                <dt>Scope and period</dt>
                <dd>
                  <Scope metadata={metadata} />
                </dd>
              </div>
              <div>
                <dt>Size</dt>
                <dd>
                  {resource?.byteSize === undefined
                    ? 'Size not supplied'
                    : `${resource.byteSize.toLocaleString('en-US')} bytes`}
                </dd>
              </div>
              <div>
                <dt>Data updated</dt>
                <dd>
                  {update ? (
                    <time dateTime={update.value}>{update.value}</time>
                  ) : (
                    'Update date not supplied'
                  )}
                </dd>
              </div>
              <div>
                <dt>Catalog availability</dt>
                <dd>{enumLabel(representation.availability)}</dd>
              </div>
              <div>
                <dt>Record access here</dt>
                <dd>{readAccess[access]}</dd>
              </div>
              <div>
                <dt>Access requirements</dt>
                <dd>{resource?.accessRequirements ?? 'Resource requirements not supplied'}</dd>
              </div>
              {resource?.requestLimits && (
                <div>
                  <dt>Resource request limits</dt>
                  <dd>{resource.requestLimits}</dd>
                </div>
              )}
              <div>
                <dt>Reuse terms</dt>
                <dd>
                  {metadata?.terms?.length ? (
                    <ul>
                      {metadata.terms.map((term, termIndex) => (
                        <li key={termIndex}>
                          {termsScope[term.scope]} ·{' '}
                          {term.url ? (
                            <ExternalLink url={term.url}>{term.label}</ExternalLink>
                          ) : (
                            term.label
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    'Resource reuse terms not supplied'
                  )}
                </dd>
              </div>
              <div>
                <dt>Access destination</dt>
                <dd>
                  {suppliedDestination ? (
                    <ExternalLink url={suppliedDestination.url}>
                      {destinationLabel[suppliedDestination.kind]}
                    </ExternalLink>
                  ) : listed ? (
                    <ExternalLink url={listed}>Open listed resource</ExternalLink>
                  ) : access === 'available' ? (
                    'Connected reader in this viewer'
                  ) : access === 'withheld' ? (
                    'Withheld'
                  ) : (
                    'External destination not supplied'
                  )}
                </dd>
              </div>
              <div>
                <dt>Resource identifier</dt>
                <dd>
                  <code>{representation.id}</code>
                </dd>
              </div>
            </dl>
            {access !== 'withheld' &&
              (metadata?.reuse?.some(({ target }) => target.kind === 'external') ? (
                <ReuseLinks links={metadata.reuse} />
              ) : (
                <p className="muted">Resource guide or metadata companion not supplied.</p>
              ))}
            {metadata?.unknowns?.length ? (
              <ul>
                {metadata.unknowns.map(({ fact, reason }, item) => (
                  <li key={item}>
                    {fact}
                    {reason ? ` · ${reason}` : ''}
                  </li>
                ))}
              </ul>
            ) : null}
            {onSelectRepresentation && !selected && access === 'available' && (
              <button type="button" onClick={() => onSelectRepresentation(representation.id)}>
                Select this resource
              </button>
            )}
          </details>
        );
      })}
    </section>
  );
}
