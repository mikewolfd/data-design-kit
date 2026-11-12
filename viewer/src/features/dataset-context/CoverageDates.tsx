import type { ReactNode } from 'react';
import { Badge, Facts, RecordLink, Value } from '../../components/Primitives';
import type { CatalogVersion } from '../../domain/types';
import { datasetIntroduction, enumLabel } from '../../lib/content';
import { objectOf, textValue } from '../../lib/display';
import type { DateKind, PublisherRecord } from '../publisher-metadata';
import { contextScopes, type DatasetContextProps } from './scope';

const dateFormat = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeZone: 'UTC' });
const timeFormat = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'UTC',
});

export function RecordedDate({ value }: { value: string }) {
  const date = new Date(value);
  const calendar = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const formatted = Number.isNaN(date.getTime())
    ? value
    : calendar
      ? dateFormat.format(date)
      : `${timeFormat.format(date)} UTC`;
  return <time dateTime={value}>{formatted}</time>;
}

function CoverageDefinition({ coverage }: { coverage: NonNullable<PublisherRecord['coverage']> }) {
  const { period, geography, population, inclusion, exclusions } = coverage;
  const facts: [string, ReactNode][] = [];
  if (period)
    facts.push([
      'Period described',
      <>
        {period.start ? <RecordedDate value={period.start} /> : 'Start not supplied'}
        {' – '}
        {period.end ? <RecordedDate value={period.end} /> : 'End not supplied'}
      </>,
    ]);
  if (geography) facts.push(['Geography', geography]);
  if (population) facts.push(['Population', population]);
  if (inclusion) facts.push(['What is included', inclusion]);
  if (exclusions) facts.push(['Known exclusions', exclusions]);
  return facts.length ? <Facts items={facts} /> : null;
}

function CoverageMeasurements({ coverage }: { coverage: CatalogVersion['coverage'] }) {
  if (!coverage?.length)
    return (
      <p className="muted">
        Coverage is unknown. No comparable observed and expected population has been supplied for
        this version.
      </p>
    );
  return coverage.map((measurement, index) => (
    <div className="evidence-row" key={index}>
      <div>
        <strong>{measurement.scope}</strong>
        {(measurement.kind || measurement.stage) && (
          <p className="muted">
            {[
              measurement.kind ? `Kind: ${enumLabel(measurement.kind)}` : undefined,
              measurement.stage ? `Stage: ${enumLabel(measurement.stage)}` : undefined,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        )}
        {measurement.bounds && (
          <p>
            Bounds on <code>{measurement.bounds.field}</code>:{' '}
            <Value value={measurement.bounds.min} /> to <Value value={measurement.bounds.max} />.
          </p>
        )}
        <p>
          {measurement.observed === undefined ? (
            'Observed count not recorded.'
          ) : (
            <>
              <Value value={measurement.observed} /> {measurement.unit} observed.
            </>
          )}
        </p>
        <p>
          {measurement.expected === undefined ? (
            'Expected population total not recorded in the catalog.'
          ) : (
            <>
              Expected population total <Value value={measurement.expected} /> {measurement.unit}.
            </>
          )}
        </p>
        {measurement.expected == null && !measurement.bounds && (
          <p>Completeness is unknown without an expected count.</p>
        )}
        <details>
          <summary>Coverage evidence for this scope</summary>
          <RecordLink record={measurement.record} />
        </details>
      </div>
      <Badge status={measurement.status}>
        {measurement.status === 'complete' && measurement.expected == null && !measurement.bounds
          ? 'Reported scope status: complete'
          : `Coverage: ${enumLabel(measurement.status)}`}
      </Badge>
    </div>
  ));
}

export function CoverageContext(props: DatasetContextProps) {
  const { scopes, selectedVersion } = contextScopes(props);
  const { snapshot, dataset } = props;
  const definitionNote = datasetIntroduction(snapshot, dataset).coverageNote;
  const customProperties = snapshot.definitions[dataset.alias]?.customProperties;
  const coverageDeclarations =
    snapshot.audience === 'local' &&
    snapshot.catalog.project.id === 'urn:congressional-tech:archive:project' &&
    Array.isArray(customProperties)
      ? customProperties.map(objectOf).filter(({ property }) => property === 'coverageLimits')
      : [];
  const limits = coverageDeclarations.length === 1 ? coverageDeclarations[0].value : undefined;
  const coverageLimits =
    Array.isArray(limits) &&
    limits.every((limit): limit is string => typeof limit === 'string' && limit.trim().length > 0)
      ? limits
      : [];
  return (
    <div className="dataset-context">
      {scopes.map(({ kind, label, id, metadata }) => {
        const coverage = metadata?.coverage;
        const suppliedCoverage = coverage && Object.keys(coverage).length > 0;
        return (
          <div className="context-scope" key={id}>
            <h3>{label}</h3>
            {metadata?.coverageStatement && <p>{metadata.coverageStatement}</p>}
            {suppliedCoverage && <CoverageDefinition coverage={coverage} />}
            {kind === 'dataset' && (
              <>
                {definitionNote && definitionNote !== metadata?.coverageStatement && (
                  <p>{definitionNote}</p>
                )}
                {coverageLimits.length > 0 && (
                  <ul className="context-links">
                    {coverageLimits.map((limit, index) => (
                      <li key={index}>{limit}</li>
                    ))}
                  </ul>
                )}
                {!metadata?.coverageStatement &&
                  !suppliedCoverage &&
                  !definitionNote &&
                  !coverageLimits.length && (
                    <p className="muted">Coverage description not supplied for this dataset.</p>
                  )}
              </>
            )}
            {kind === 'version' && selectedVersion && (
              <>
                <p>{selectedVersion.scope}</p>
                <CoverageMeasurements coverage={selectedVersion.coverage} />
              </>
            )}
            {kind === 'representation' && !suppliedCoverage && (
              <p className="muted">Coverage details not supplied for this resource.</p>
            )}
          </div>
        );
      })}
      {!selectedVersion && (
        <p className="muted">Version coverage is unknown. No data version is selected.</p>
      )}
    </div>
  );
}

const dateLabels: Record<DateKind, string> = {
  coverageObserved: 'Coverage observation date',
  sourcePublished: 'Source publication date',
  dataUpdated: 'Data update date',
  metadataUpdated: 'Metadata update date',
  retrieved: 'Source retrieval date',
  nextExpectedUpdate: 'Next expected data update',
};

export function DateContext(props: DatasetContextProps) {
  const { scopes, selectedVersion } = contextScopes(props);
  return (
    <div className="dataset-context">
      {scopes.map(({ kind: scopeKind, label, id, metadata }) => {
        const coreVersionDates: { kind: DateKind; value: string }[] =
          scopeKind === 'version' && selectedVersion?.dates
            ? [
                ...(selectedVersion.dates.publishedAt
                  ? [{ kind: 'sourcePublished' as const, value: selectedVersion.dates.publishedAt }]
                  : []),
                ...(selectedVersion.dates.sourceUpdatedAt
                  ? [{ kind: 'dataUpdated' as const, value: selectedVersion.dates.sourceUpdatedAt }]
                  : []),
                ...(selectedVersion.dates.retrievedAt
                  ? [{ kind: 'retrieved' as const, value: selectedVersion.dates.retrievedAt }]
                  : []),
              ]
            : [];
        const dates = [
          ...coreVersionDates,
          ...(metadata?.dates ?? []).filter(
            (entry) => !coreVersionDates.some((core) => core.kind === entry.kind),
          ),
        ];
        const observationDate = metadata?.observationDate;
        const coverageObserved = dates.some(({ kind }) => kind === 'coverageObserved');
        const facts: [string, ReactNode][] = [];
        for (const [kind, fact] of Object.entries(dateLabels)) {
          const value =
            dates.find((date) => date.kind === kind)?.value ??
            (kind === 'coverageObserved' ? observationDate : undefined);
          facts.push([fact, value ? <RecordedDate value={value} /> : 'Not supplied']);
        }
        if (observationDate && coverageObserved) {
          facts.unshift([
            'Coverage observation date from the publisher’s discovery notes',
            <RecordedDate value={observationDate} />,
          ]);
        }
        if (metadata?.updateFrequency)
          facts.push(['Publisher’s expected update schedule', metadata.updateFrequency]);
        if (scopeKind === 'dataset' && props.dataset.contract?.slaProperties?.length) {
          for (const sla of props.dataset.contract.slaProperties) {
            facts.push([`Declared SLA · ${sla.property}`, textValue(sla.value)]);
          }
        }
        return (
          <div className="context-scope" key={id}>
            <h3>{label}</h3>
            {facts.length ? (
              <Facts items={facts} />
            ) : (
              <p className="muted">Dates not supplied for this selection.</p>
            )}
            {(dates.length > 0 || observationDate) && (
              <details>
                <summary>Original dates and recorded scope</summary>
                <p>
                  <code>{id}</code>
                </p>
                <ul>
                  {dates.map(({ kind, value }) => (
                    <li key={kind}>
                      {dateLabels[kind]} <code>{value}</code>
                    </li>
                  ))}
                  {observationDate && (
                    <li>
                      Coverage observation date from the publisher’s discovery notes{' '}
                      <code>{observationDate}</code>
                    </li>
                  )}
                </ul>
              </details>
            )}
            {metadata?.updateFrequency && (
              <p className="muted">The schedule describes when the publisher expects updates.</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
