import { useState, type ReactNode } from 'react';
import ImpactPanel from './ImpactPanel';
import { EvidenceRecord } from './EvidenceRecord';
import type { CatalogDataset, CatalogSnapshot, CatalogVersion } from '../domain/types';
import { Badge, FieldTree, Facts, Notice, Raw, RecordLink, Section } from './Primitives';
import { objectOf, safeLink, shortId, textValue, titleOf, versionsOf, words } from '../lib/display';
import { datasetIntroduction, enumLabel, recordAccess } from '../lib/content';
import { publisherMetadata } from '../features/publisher-metadata';
import { CapturedSources } from '../features/dataset-context/CapturedSources';
import {
  CoverageContext,
  DateContext,
  Cautions,
  ProvenanceContext,
  AttributionContext,
  HistoryNotes,
} from '../features/dataset-context';

type Context = { snapshot: CatalogSnapshot; dataset: CatalogDataset; version?: CatalogVersion };
export function Overview({
  snapshot,
  dataset,
  version,
  onViewData,
}: Context & { onViewData?: () => void }) {
  const definition = snapshot.definitions[dataset.alias];
  const introduction = datasetIntroduction(snapshot, dataset);
  const access = recordAccess(snapshot, dataset, version);
  const representations = snapshot.catalog.representations.filter((r) => r.version === version?.id);
  const fileAvailability = representations.some((r) => r.availability === 'available')
    ? 'available'
    : !representations.length || representations.some((r) => r.availability === 'unknown')
      ? 'unknown'
      : 'unavailable';
  const identities = snapshot.catalog.identities.filter(
    (i) => i.dataset === dataset.alias || i.dataset === dataset.id,
  );
  const products = snapshot.catalog.products.filter((p) =>
    p.ports.some((port) => port.dataset === dataset.alias || port.dataset === dataset.id),
  );
  const assembly = objectOf(snapshot.catalog.extensions?.['urn:ddk:catalog:assembly']);
  const coreTags = dataset.tags ?? dataset.contract?.tags ?? [];
  const coreContext = dataset.context ?? dataset.contract?.context;
  const canonicalUrls = dataset.contract?.canonicalUrls ?? [];
  return (
    <>
      <div className="overview-intro">
        <p className="eyebrow">What this dataset is for</p>
        <p>
          {introduction.purpose || 'The publisher has not supplied the purpose of this dataset.'}
        </p>
        {introduction.usage && (
          <>
            <p className="eyebrow">How to use this dataset</p>
            <p>{introduction.usage}</p>
          </>
        )}
        <p className="eyebrow">What one record represents</p>
        <p className="purpose">
          {introduction.rowMeaning || 'The publisher has not supplied what one record represents.'}
        </p>
        <Facts
          items={[
            ['View records here', access.label],
            ...(dataset.origin
              ? ([['Dataset origin', enumLabel(dataset.origin)]] as [string, ReactNode][])
              : []),
            ...(dataset.status
              ? ([['Dataset status', enumLabel(dataset.status)]] as [string, ReactNode][])
              : []),
            ...(dataset.model
              ? ([
                  [
                    'Model identity',
                    <>
                      <code>{dataset.model.id}</code> · {dataset.model.version}
                    </>,
                  ],
                ] as [string, ReactNode][])
              : []),
            ...(dataset.methodColumn
              ? ([['Method column', <code>{dataset.methodColumn}</code>]] as [string, ReactNode][])
              : []),
            ...(coreTags.length > 0
              ? ([['Tags', coreTags.join(', ')]] as [string, ReactNode][])
              : []),
            [
              'File availability',
              version ? (
                <Badge status={fileAvailability} />
              ) : versionsOf(snapshot, dataset).length ? (
                'Choose a data version to view file availability.'
              ) : (
                'No data versions listed.'
              ),
            ],
            [
              'Catalog report checks',
              <>
                <Badge status={snapshot.report.decision} />
                <span className="subline">
                  Applies to the recorded catalog check scope; see Checks & sources.
                </span>
              </>,
            ],
          ]}
        />
      </div>
      {(coreContext || canonicalUrls.length > 0) && (
        <Section title="Contract guidance & canonical references">
          {coreContext?.instructions && <p>{coreContext.instructions}</p>}
          {coreContext?.constraints && coreContext.constraints.length > 0 && (
            <ul>
              {coreContext.constraints.map((entry, idx) => (
                <li key={idx}>{entry.constraint}</li>
              ))}
            </ul>
          )}
          {canonicalUrls.length > 0 && (
            <ul>
              {canonicalUrls.map((url) => (
                <li key={url}>
                  {safeLink(url) ? (
                    <a href={safeLink(url)} target="_blank" rel="noreferrer">
                      {url}
                    </a>
                  ) : (
                    <code>{url}</code>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
      <Notice title="What you can do here">
        {access.detail} You can explore the field descriptions and recorded checks below.
        <div className="intro-actions">
          <a href="#field-dictionary">Explore field meanings</a>
          {onViewData && versionsOf(snapshot, dataset).length > 0 && (
            <button onClick={onViewData}>
              {access.state === 'available'
                ? 'View records and download options'
                : 'View access options'}
            </button>
          )}
        </div>
      </Notice>
      {products.length > 0 && (
        <Section title="Collections containing this dataset">
          <div className="plain-list">
            {products.map((p) => (
              <div key={p.id}>
                <strong>{words(p.alias)}</strong>
                <span>Version {p.version}</span>
                <code>{p.id}</code>
              </div>
            ))}
          </div>
        </Section>
      )}
      <Section title="Coverage">
        <CoverageContext snapshot={snapshot} dataset={dataset} version={version} />
      </Section>
      <Section title="Important limits">
        <Cautions snapshot={snapshot} dataset={dataset} version={version} />
      </Section>
      <Section title="Dates and update expectations">
        <DateContext snapshot={snapshot} dataset={dataset} version={version} />
      </Section>
      <div id="field-dictionary" tabIndex={-1}>
        <Section
          title="What each field means"
          aside={
            <span className="muted">
              {definition?.properties?.length ?? 0} top-level{' '}
              {definition?.properties?.length === 1 ? 'field' : 'fields'}
            </span>
          }
        >
          {assembly.disclosedDefinitionPaths !== undefined && (
            <Notice title="Some field definitions may be omitted from this public view">
              An omitted field is not evidence that the source has no such field.
            </Notice>
          )}
          {definition?.description && definition.description !== dataset.rowMeaning && (
            <details>
              <summary>Publisher’s technical dataset description</summary>
              <p>{definition.description}</p>
            </details>
          )}
          {definition?.properties?.length ? (
            <FieldTree
              fields={definition.properties}
              identities={identities}
              documentedValues={
                publisherMetadata(snapshot).datasets.get(dataset.id)?.documentedValues
              }
            />
          ) : (
            <p className="muted">
              No field definitions are disclosed. Dataset metadata may still be available.
            </p>
          )}
        </Section>
      </div>
      <Section title="Credit, reuse terms and help">
        <AttributionContext snapshot={snapshot} dataset={dataset} version={version} />
      </Section>
      <Section title="Identifiers & source records">
        <Facts
          items={[
            ['Dataset', <code>{dataset.id}</code>],
            [
              'Definition object and revision',
              <>
                <code>{dataset.definition.object}</code> · {dataset.definition.version}
              </>,
            ],
            ['Definition publisher', <code>{dataset.definition.contractId}</code>],
            ['Source definition', <RecordLink record={dataset.definition.source} />],
          ]}
        />
        {identities.map((i, n) => (
          <Raw key={n} value={i} label={`${words(i.kind)} identity · ${i.scope}`} />
        ))}
        <Raw value={definition || {}} label="View the original dataset definition" />
      </Section>
    </>
  );
}
export function Evidence({ snapshot, dataset, version }: Context) {
  const [all, setAll] = useState(false);
  const relevant = snapshot.report.checks.filter(
    (c) => c.subject === dataset.alias || c.subject === dataset.id || c.subject === version?.id,
  );
  const checks = all ? snapshot.report.checks : relevant;
  const required = snapshot.report.checks.filter(
    (c) => c.required && c.applicable && c.status !== 'passed',
  );
  const observed = snapshot.catalog.checks.filter((c) => c.subject === version?.id);
  return (
    <>
      <Section title="What has been checked">
        <p>
          Dataset: <strong>{titleOf(dataset)}</strong>.{' '}
          {version ? <>Selected version scope: {version.scope}.</> : 'No data version is selected.'}
        </p>
        <Notice
          title={
            required.length
              ? `Across this catalog, ${required.length} required check${required.length === 1 ? ' is' : 's are'} unresolved or failed`
              : 'Catalog checks describe their stated scope'
          }
          kind={required.length ? 'warning' : 'info'}
        >
          Each catalog report check applies only to its stated scope. Checks for a data version
          examine only the named data and rules. Passing checks do not establish overall data
          reliability.
        </Notice>
        <Facts
          items={[
            ['Catalog report checks', <Badge status={snapshot.report.decision} />],
            [
              'Checks for this data version',
              observed.length
                ? `${observed.length} recorded; ${observed.filter((c) => c.status === 'passed').length} passed; ${observed.filter((c) => c.status === 'failed').length} failed; ${observed.filter((c) => c.status === 'unknown').length} unknown; ${observed.filter((c) => c.status === 'not_run').length} not run`
                : 'Not supplied',
            ],
            ['Freshness', 'Unknown · no freshness policy assessed'],
          ]}
        />
      </Section>
      <Section title="Coverage and remaining unknowns">
        <CoverageContext snapshot={snapshot} dataset={dataset} version={version} />
      </Section>
      <Section title="Captured sources in this catalog">
        <CapturedSources snapshot={snapshot} />
      </Section>
      <Section title="Checks for this data version">
        <p>
          Passed means the named check passed. Failed means it reported a failure. Not run means it
          was not run. Unknown means the outcome is not established. Applicability is recorded
          separately.
        </p>
        {snapshot.capabilities.evidence &&
          [
            ...new Map(
              observed
                .filter((c) => c.record)
                .map((c) => [`${c.record!.uri}:${c.record!.sha256}`, c.record!]),
            ).values(),
          ].map((record) => (
            <EvidenceRecord
              key={`${record.uri}:${record.sha256}`}
              snapshot={snapshot}
              record={record}
              label="View saved check evidence"
            />
          ))}
        {observed.length ? (
          observed.map((c, i) => (
            <div className="evidence-row" key={i}>
              <div>
                <strong>{c.scope}</strong>
                <span className="subline">
                  Check subject: {titleOf(dataset)} · {version?.scope}
                </span>
                {c.reason && <p>{c.reason}</p>}
                <details>
                  <summary>Rule and evaluator details</summary>
                  <p>
                    Rule: <code>{c.rule.id}</code> · version {c.rule.version}
                  </p>
                  <p>
                    Evaluator: <code>{c.evaluator.id}</code> · version {c.evaluator.version}
                  </p>
                </details>
                <RecordLink record={c.record} />
              </div>
              <Badge status={c.status} />
            </div>
          ))
        ) : (
          <Notice title="No checks are recorded for this data version">
            {version
              ? 'The catalog links no check results to this version.'
              : 'No data version is selected.'}{' '}
            Missing results do not count as passes. Data quality remains unknown.
          </Notice>
        )}
      </Section>
      <Section
        title="Catalog check results"
        aside={
          <label className="check-label">
            <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
            Show all catalog checks
          </label>
        }
      >
        {checks.length ? (
          checks.slice(0, 80).map((c, i) => (
            <div className="check-row" key={`${c.id}:${i}`}>
              <div>
                <strong>
                  {'title' in c && typeof c.title === 'string'
                    ? c.title
                    : `Catalog check ${i + 1} · title not supplied`}
                </strong>
                <span className="subline">{words(c.group)}</span>
                <p>{c.reason || c.subject}</p>
                <span className="subline">
                  {c.evidence} evidence · {c.required ? 'Required' : 'Optional'} ·{' '}
                  {c.applicable ? 'Applicable' : 'Not applicable'}
                </span>
                <details>
                  <summary>Check details</summary>
                  <pre>{JSON.stringify(c, null, 2)}</pre>
                </details>
              </div>
              <Badge status={c.status} />
            </div>
          ))
        ) : (
          <p className="muted">
            No catalog checks are linked directly to this dataset. Choose “Show all catalog checks”
            to inspect the full report scope.
          </p>
        )}
        {checks.length > 80 && (
          <p>
            Showing 80 of {checks.length} checks. All results are retained in the catalog check
            report.
          </p>
        )}
      </Section>
      <Section title="Where this data comes from">
        <ProvenanceContext snapshot={snapshot} dataset={dataset} version={version} />
      </Section>
      <Section title="Technical check details">
        <p>Acceptance by the publishing system: not established here.</p>
        <p>
          This portal displays recorded publisher evidence. It does not make or refresh acceptance
          decisions.
        </p>
        <Raw value={snapshot.report.scope} label="Requested report scope" />
        <Raw value={snapshot.report.coverage} label="Check coverage" />
        <Raw value={snapshot.lock.tools} label="Recorded tool versions" />
        <Raw value={snapshot.catalog.extensions} label="Scoped definitions and extensions" />
      </Section>
    </>
  );
}
function RecordedProcessingEvidence({
  snapshot,
  run,
}: {
  snapshot: CatalogSnapshot;
  run: CatalogSnapshot['catalog']['runs'][number];
}) {
  // This maintained extension is local-only. Public checks keep their own disclosed scope.
  if (snapshot.audience !== 'local') return null;
  const rows = objectOf(
    snapshot.catalog.extensions?.['urn:ddk:catalog:assembly'],
  ).managedExecutions;
  if (!Array.isArray(rows)) return null;
  const matches = rows.map(objectOf).filter((row) => row.run === run.id);
  if (!matches.length) return null;
  const trace = matches[0];
  const record = objectOf(trace.record);
  const digest = (value: unknown): value is string =>
    typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const sameReceipt =
    matches.length === 1 &&
    typeof record.uri === 'string' &&
    !!record.uri &&
    record.uri === run.record?.uri &&
    digest(record.sha256) &&
    record.sha256 === run.record?.sha256;
  let status = 'Unknown · multiple summaries identify this processing event.';
  let identity: string | undefined;
  if (matches.length === 1) {
    if (!sameReceipt) {
      status = 'Unknown · the summary does not identify the same evidence file as this event.';
    } else if (trace.acceptedQualification === null) {
      status = 'No acceptance identity is attached to this record.';
    } else if (digest(trace.acceptedQualification)) {
      status = 'An acceptance identity is recorded for this event.';
      identity = trace.acceptedQualification;
    } else {
      status = 'Unknown · the summary supplies no valid acceptance identity.';
    }
  }
  const facts: [string, ReactNode][] = [['Recorded processing acceptance', status]];
  if (identity) facts.push(['Exact acceptance identity', <code>{identity}</code>]);
  return (
    <>
      <div className="recorded-acceptance">
        <Facts items={facts} />
        <p className="muted">
          An acceptance record covers only the processing system's named checks for that event. It
          does not establish that every record was verified, or that the result is currently
          accepted, selected or published.
        </p>
      </div>
      {sameReceipt && Object.hasOwn(trace, 'producerEvidence') && (
        <div className="recorded-producer-evidence">
          <p className="muted">
            This recorded metadata does not establish which code wrote earlier records or whether
            proof files are still available.
          </p>
          <Raw value={trace.producerEvidence} label="Recorded producer evidence for this event" />
        </div>
      )}
    </>
  );
}
export function Activity({ snapshot, dataset, version }: Context) {
  const { catalog } = snapshot;
  const runs = catalog.runs.filter(
    (r) => r.outputs.includes(version?.id || '') || r.inputs.includes(version?.id || ''),
  );
  const releases = catalog.releases.filter((r) => r.members.includes(version?.id || ''));
  const productions = catalog.productions.filter(
    (p) => p.inputs.includes(dataset.alias) || p.outputs.includes(dataset.alias),
  );
  return (
    <>
      <Section title="Publisher change notes">
        <HistoryNotes snapshot={snapshot} dataset={dataset} version={version} />
      </Section>
      <Section title="Dates and update expectations">
        <DateContext snapshot={snapshot} dataset={dataset} version={version} />
      </Section>
      <Section title="Recorded processing events">
        {runs.length ? (
          runs.map((r) => (
            <article className="run" key={r.id}>
              <div className="section-heading">
                <h3>{shortId(r.id)}</h3>
                <Badge status={r.outcome} />
              </div>
              <Facts
                items={[
                  ['Recorded at', readableTime(r.observedAt)],
                  ['Input coverage', r.inputCoverage.status],
                  ['Coverage scope', r.inputCoverage.scope],
                ]}
              />
              <Raw
                value={{ id: r.id, reference: r.reference, observedAt: r.observedAt }}
                label="Original operation identifiers and timestamp"
              />
              <Raw
                value={{ inputs: r.inputs, outputs: r.outputs }}
                label="Exact consumed inputs and outputs"
              />
              <RecordedProcessingEvidence snapshot={snapshot} run={r} />
              <EvidenceRecord
                snapshot={snapshot}
                record={r.record}
                label="View original processing record"
              />
            </article>
          ))
        ) : (
          <p className="muted">
            No processing events are recorded for this version. A processing plan does not show that
            processing took place.
          </p>
        )}
      </Section>
      <Section title="Release membership & publisher selections">
        {releases.length ? (
          releases.map((r) => (
            <article className="run" key={r.id}>
              <div className="section-heading">
                <h3>{shortId(r.id)}</h3>
                <Badge status={r.membership} />
              </div>
              <p>
                Release membership: {words(r.membership)}. {r.members.length} data{' '}
                {r.members.length === 1 ? 'version' : 'versions'} listed.
              </p>
              <Raw value={r.members} label="Inspect exact release membership" />
              {catalog.selections
                .filter((s) => s.release === r.id)
                .map((s, i) => (
                  <Facts
                    key={i}
                    items={[
                      ['Selection authority', <code>{s.authority}</code>],
                      ['Purpose', s.purpose],
                      [
                        'Selection recorded at',
                        <>
                          {readableTime(s.observedAt)}
                          <span className="subline">
                            Original: <code>{s.observedAt}</code>
                          </span>
                        </>,
                      ],
                      ['Publisher record', <RecordLink record={s.record} />],
                    ]}
                  />
                ))}
              {!catalog.selections.some((s) => s.release === r.id) && (
                <p>No publisher selection is recorded for this release.</p>
              )}
            </article>
          ))
        ) : (
          <p className="muted">
            No release membership is recorded for this version. No publisher selection is inferred.
          </p>
        )}
      </Section>
      <details className="raw">
        <summary>Integration status</summary>
        <Section title="Processing plans & saved results">
          {productions.map((p) => (
            <div key={p.alias}>
              <Raw value={p} label={`${p.alias} · ${p.kind ? `${p.kind} ` : ''}processing plan`} />
              {p.steps && p.steps.length > 0 && (
                <p className="muted">
                  Steps:{' '}
                  {p.steps.map((step, idx) => (
                    <span key={step.id}>
                      {idx > 0 ? ' → ' : ''}
                      <code>{step.id}</code> ({step.kind})
                    </span>
                  ))}
                </p>
              )}
            </div>
          ))}
          {catalog.files
            .filter((f) => /substrait|plan|lineage/.test(f.role + ' ' + f.path))
            .map((f) => (
              <p key={f.path}>
                <code>{f.path}</code> · {f.role}
              </p>
            ))}
          <Notice title="Recovery and managed-update details are not connected">
            {snapshot.capabilities.evidence && runs.some((r) => r.record?.sha256)
              ? 'Original processing records can be opened above. '
              : 'Original processing records cannot be opened here for this version. '}
            This portal does not provide update, publishing-system acceptance, or publication
            recovery actions. Those capabilities remain unassessed here.
          </Notice>
        </Section>
      </details>
    </>
  );
}
export function Compare({ snapshot, dataset, version }: Context) {
  const versions = versionsOf(snapshot, dataset);
  const [baseId, setBaseId] = useState(versions.find((v) => v.id !== version?.id)?.id || '');
  const base = versions.find((v) => v.id === baseId);
  return (
    <>
      <Section title="Compare versions">
        <p>
          Compare recorded facts for two data versions. This comparison does not assess what the
          differences mean for your use.
        </p>
        {versions.length >= 2 && (
          <label className="stack-label">
            Base version
            <select value={baseId} onChange={(e) => setBaseId(e.target.value)}>
              <option value="">Choose a base version</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {shortId(v.id)}
                </option>
              ))}
            </select>
          </label>
        )}
        {versions.length >= 2 && base && version && base.id !== version.id ? (
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Version comparison">
            <table className="compare-table">
              <thead>
                <tr>
                  <th scope="col">Recorded fact</th>
                  <th scope="col">Base · {shortId(base.id)}</th>
                  <th scope="col">Selected · {shortId(version.id)}</th>
                </tr>
              </thead>
              <tbody>
                {[
                  [
                    'Original version reference',
                    textValue(base.reference),
                    textValue(version.reference),
                  ],
                  [
                    'Saved version',
                    retentionLabel(base.retention),
                    retentionLabel(version.retention),
                  ],
                  ['Scope', base.scope, version.scope],
                  [
                    'Source captures',
                    base.sources.join(', ') || 'Unknown',
                    version.sources.join(', ') || 'Unknown',
                  ],
                  ['Coverage', coverageLabel(base), coverageLabel(version)],
                ].map(([label, left, right]) => (
                  <tr key={label}>
                    <th scope="row">{label}</th>
                    <td>{left}</td>
                    <td>{right}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Notice
            title={
              versions.length === 0
                ? 'No data versions are listed.'
                : versions.length === 1
                  ? 'Only one data version is listed.'
                  : base?.id === version?.id
                    ? 'Choose two different data versions.'
                    : 'Choose two data versions.'
            }
          >
            {versions.length < 2
              ? 'Two versions are needed for a comparison.'
              : 'Choose a data version above and a different base version here.'}
          </Notice>
        )}
        {base && version && base.id !== version.id && (
          <Raw value={{ base, selected: version }} label="Original version comparison records" />
        )}
      </Section>
      <ImpactPanel snapshot={snapshot} dataset={dataset} />
    </>
  );
}

function readableTime(value: string) {
  const time = new Date(value);
  return Number.isNaN(time.getTime())
    ? value
    : time.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) +
        ' UTC';
}
function retentionLabel(value: CatalogVersion['retention']) {
  return { present: 'Retained', missing: 'Not retained', unknown: 'Unknown' }[value];
}
function coverageLabel(version: CatalogVersion) {
  return version.coverage?.length
    ? version.coverage
        .map(
          (c) =>
            `${c.scope}: ${c.status}; ${c.observed === undefined ? 'observed count not recorded' : textValue(c.observed) + ' ' + c.unit + ' observed'}; ${c.expected === undefined ? 'expected population total not recorded' : textValue(c.expected) + ' ' + c.unit + ' expected'}`,
        )
        .join('; ')
    : 'Unknown — no coverage information recorded';
}
