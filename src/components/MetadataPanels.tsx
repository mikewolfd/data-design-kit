import { useState } from 'react';
import ImpactPanel from './ImpactPanel';
import type { CatalogDataset, CatalogSnapshot, CatalogVersion } from '../domain/types';
import { Badge, FieldTree, Facts, Notice, Raw, RecordLink, Section, Value } from './Primitives';
import { objectOf, shortId, textValue, versionsOf, words } from '../lib/display';

type Context = { snapshot: CatalogSnapshot; dataset: CatalogDataset; version?: CatalogVersion };
export function Overview({ snapshot, dataset, version }: Context) {
  const definition = snapshot.definitions[dataset.alias];
  const identities = snapshot.catalog.identities.filter(
    (i) => i.dataset === dataset.alias || i.dataset === dataset.id,
  );
  const products = snapshot.catalog.products.filter((p) =>
    p.ports.some((port) => port.dataset === dataset.alias || port.dataset === dataset.id),
  );
  const assembly = objectOf(snapshot.catalog.extensions?.['urn:ddk:catalog:assembly']);
  return (
    <>
      <div className="overview-intro">
        <p className="eyebrow">Purpose & scope</p>
        <p className="purpose">
          {dataset.rowMeaning ||
            definition?.description ||
            'A purpose description has not been supplied for this dataset.'}
        </p>
        <Facts
          items={[
            [
              'Definition',
              <>
                <code>{dataset.definition.object}</code>
                <span className="subline">Revision {dataset.definition.version}</span>
              </>,
            ],
            [
              'Data access',
              version ? (
                <Badge
                  status={
                    snapshot.catalog.representations.find((r) => r.version === version.id)
                      ?.availability || 'unknown'
                  }
                />
              ) : (
                'No observed version'
              ),
            ],
            [
              'Catalog checks',
              <>
                <Badge status={snapshot.report.decision} />
                <span className="subline">Within the requested check scope</span>
              </>,
            ],
          ]}
        />
      </div>
      {!version && (
        <Notice title="Definitions are available. Data access is not established.">
          This catalog does not identify a selected readable version. Definition checks do not
          establish data quality.
        </Notice>
      )}
      {products.length > 0 && (
        <Section title="Data products">
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
        {version?.coverage?.length ? (
          version.coverage.map((c, i) => (
            <div className="evidence-row" key={i}>
              <div>
                <strong>{c.scope}</strong>
                <p>
                  <Value value={c.observed} /> observed / <Value value={c.expected} /> expected ·{' '}
                  {c.unit}
                </p>
                <RecordLink record={c.record} />
              </div>
              <Badge status={c.status} />
            </div>
          ))
        ) : (
          <p className="muted">
            Coverage is unknown. No comparable observed and expected population has been supplied
            for this version.
          </p>
        )}
      </Section>
      <Section
        title="Field definitions"
        aside={<span className="muted">{definition?.properties?.length ?? 0} root fields</span>}
      >
        {assembly.disclosedDefinitionPaths !== undefined && (
          <Notice title="Definition disclosure is scoped">
            Fields omitted from the public view are unknown, not absent.
          </Notice>
        )}
        {definition?.description && definition.description !== dataset.rowMeaning && (
          <p>{definition.description}</p>
        )}
        {definition?.properties?.length ? (
          <FieldTree fields={definition.properties} />
        ) : (
          <p className="muted">
            No field definitions are disclosed. Root metadata may still be available.
          </p>
        )}
      </Section>
      <Section title="Identity & provenance">
        <Facts
          items={[
            ['Dataset', <code>{dataset.id}</code>],
            ['Definition owner', <code>{dataset.definition.contractId}</code>],
            ['Source definition', <RecordLink record={dataset.definition.source} />],
          ]}
        />
        {identities.map((i, n) => (
          <Raw key={n} value={i} label={`${words(i.kind)} identity · ${i.scope}`} />
        ))}
        <Raw value={definition || {}} label="Inspect the admitted definition" />
      </Section>
    </>
  );
}
export function Evidence({ snapshot, dataset, version }: Context) {
  const [all, setAll] = useState(false);
  const relevant = snapshot.report.checks.filter(
    (c) =>
      c.subject === dataset.alias ||
      c.subject === dataset.id ||
      c.subject === version?.id ||
      c.subject.includes(dataset.alias),
  );
  const checks = all ? snapshot.report.checks : relevant;
  const required = snapshot.report.checks.filter(
    (c) => c.required && c.applicable && c.status !== 'passed',
  );
  const observed = snapshot.catalog.checks.filter((c) => c.subject === version?.id);
  const sources = snapshot.catalog.sources.filter((s) => version?.sources.includes(s.id));
  return (
    <>
      <Section title="What the evidence establishes">
        <Notice
          title={
            required.length
              ? `${required.length} required check${required.length === 1 ? ' is' : 's are'} unresolved or failed`
              : 'Catalog checks describe their stated scope'
          }
          kind={required.length ? 'warning' : 'info'}
        >
          A declaration, available representation, or passing catalog report does not establish
          accepted native qualification.
        </Notice>
        <Facts
          items={[
            ['Catalog decision', <Badge status={snapshot.report.decision} />],
            [
              'Exact-version checks',
              observed.length ? `${observed.length} recorded` : 'Not supplied',
            ],
            ['Native acceptance', 'Not established by this viewer'],
            ['Freshness', 'Unknown · no freshness policy assessed'],
          ]}
        />
      </Section>
      <Section title="Version-bound quality">
        {observed.length ? (
          observed.map((c, i) => (
            <div className="evidence-row" key={i}>
              <div>
                <strong>{shortId(c.rule.id)}</strong>
                <p>{c.scope}</p>
                <p>{c.reason}</p>
                <span className="subline">
                  Rule {c.rule.version} · evaluator {c.evaluator.id} @ {c.evaluator.version}
                </span>
                <RecordLink record={c.record} />
              </div>
              <Badge status={c.status} />
            </div>
          ))
        ) : (
          <Notice title="Data qualification is unknown">
            No checks are bound to this exact version. Required missing checks cannot count as
            passes.
          </Notice>
        )}
      </Section>
      <Section
        title="Catalog check results"
        aside={
          <label className="check-label">
            <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
            All catalog checks
          </label>
        }
      >
        {checks.length ? (
          checks.slice(0, 80).map((c, i) => (
            <div className="check-row" key={`${c.id}:${i}`}>
              <div>
                <strong>{words(c.group)}</strong>
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
            No check results name this dataset. Choose “All catalog checks” to inspect the full
            report scope.
          </p>
        )}
        {checks.length > 80 && (
          <p>
            Showing 80 of {checks.length} checks. The verified report companion contains the
            complete set.
          </p>
        )}
      </Section>
      <Section title="Source occurrences">
        {sources.length ? (
          sources.map((s) => (
            <div className="evidence-row" key={s.id}>
              <div>
                <strong>{shortId(s.id)}</strong>
                <p>{s.scope}</p>
                <RecordLink record={s.record} />
                <Raw value={s} label="Source identity and retained evidence" />
              </div>
              <Badge status={s.outcome} />
            </div>
          ))
        ) : (
          <p className="muted">
            No source occurrences are linked to this version. Completeness remains unknown.
          </p>
        )}
      </Section>
      <Section title="Disclosure & checking scope">
        <Raw value={snapshot.report.scope} label="Requested report scope" />
        <Raw value={snapshot.report.coverage} label="Check coverage" />
        <Raw value={snapshot.lock.tools} label="Recorded tool versions" />
        <Raw value={snapshot.catalog.extensions} label="Scoped definitions and extensions" />
      </Section>
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
      <Section title="Observed runs">
        {runs.length ? (
          runs.map((r) => (
            <article className="run" key={r.id}>
              <div className="section-heading">
                <h3>{shortId(r.id)}</h3>
                <Badge status={r.outcome} />
              </div>
              <Facts
                items={[
                  ['Observed at', r.observedAt],
                  ['Operation identity', <code>{textValue(r.reference)}</code>],
                  ['Input coverage', r.inputCoverage.status],
                  ['Coverage scope', r.inputCoverage.scope],
                ]}
              />
              <Raw
                value={{ inputs: r.inputs, outputs: r.outputs }}
                label="Exact consumed inputs and outputs"
              />
              <RecordLink record={r.record} />
            </article>
          ))
        ) : (
          <p className="muted">
            No observed runs are associated with this version. A production definition is not
            execution evidence.
          </p>
        )}
      </Section>
      <Section title="Release membership & selections">
        {releases.length ? (
          releases.map((r) => (
            <article className="run" key={r.id}>
              <div className="section-heading">
                <h3>{shortId(r.id)}</h3>
                <Badge status={r.membership} />
              </div>
              <p>{r.members.length} exact member versions</p>
              <Raw value={r.members} label="Inspect exact release membership" />
              {catalog.selections
                .filter((s) => s.release === r.id)
                .map((s, i) => (
                  <Facts
                    key={i}
                    items={[
                      ['Selection authority', <code>{s.authority}</code>],
                      ['Purpose', s.purpose],
                      ['Observed selection', s.observedAt],
                      ['Owner record', <RecordLink record={s.record} />],
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
            No release membership is recorded for this version. It is not implicitly selected.
          </p>
        )}
      </Section>
      <Section title="Plans & retained results">
        {productions.map((p) => (
          <Raw key={p.alias} value={p} label={`${words(p.alias)} · declared production`} />
        ))}
        {catalog.files
          .filter((f) => /substrait|plan|lineage/.test(f.role + ' ' + f.path))
          .map((f) => (
            <p key={f.path}>
              <code>{f.path}</code> · {f.role}
            </p>
          ))}
        <Notice title="Native inspection is not connected">
          An owner adapter must supply exact operation, plan, protected-result, recovery, and
          selection receipts. This catalog alone does not prove recovery readiness.
        </Notice>
      </Section>
      <Section title="Runtime capabilities">
        <div className="plain-list">
          {[
            [
              'Managed Update & reconciliation',
              'Awaiting a qualified owner adapter for this application.',
            ],
            [
              'Complete candidate qualification',
              'Accepted-evidence mapping and exact multi-output membership remain shared-runtime requirements.',
            ],
            [
              'Publication recovery',
              'The publisher owns publication status and recovery. No operator actions are configured.',
            ],
          ].map(([name, reason]) => (
            <div key={name}>
              <strong>{name}</strong>
              <span>{reason}</span>
              <Badge status="unknown" />
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}
export function Compare({ snapshot, dataset, version }: Context) {
  const versions = versionsOf(snapshot, dataset);
  const [baseId, setBaseId] = useState(versions.find((v) => v.id !== version?.id)?.id || '');
  const base = versions.find((v) => v.id === baseId);
  return (
    <>
      <Section title="Compare exact versions">
        <p>
          Compare the recorded facts for two versions. Semantic impact requires the owner’s analysis
          of exact definition snapshots.
        </p>
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
        {base && version ? (
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
                    'Exact native reference',
                    textValue(base.reference),
                    textValue(version.reference),
                  ],
                  ['Retention', base.retention, version.retention],
                  ['Scope', base.scope, version.scope],
                  [
                    'Source occurrences',
                    base.sources.join(', ') || 'Unknown',
                    version.sources.join(', ') || 'Unknown',
                  ],
                  ['Coverage', textValue(base.coverage), textValue(version.coverage)],
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
          <Notice title="Choose two observed versions">
            This catalog may provide definitions without version history.
          </Notice>
        )}
      </Section>
      <ImpactPanel snapshot={snapshot} dataset={dataset} />
    </>
  );
}
