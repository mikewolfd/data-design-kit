import { useEffect, useState } from 'react';
import type { Catalog, CatalogDataset, CatalogSnapshot } from '../domain/types';
import { request } from '../lib/client';
import { downloadJson, objectOf, textValue, words } from '../lib/display';
import { Badge, Facts, Notice, Raw, Section } from './Primitives';

type ImpactResult = {
  available: boolean;
  reason?: string;
  binding?: Record<string, unknown>;
  base?: Catalog;
  report?: Record<string, unknown>;
};
export default function ImpactPanel({
  snapshot,
  dataset,
}: {
  snapshot: CatalogSnapshot;
  dataset: CatalogDataset;
}) {
  const [result, setResult] = useState<ImpactResult>();
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setError('');
    setResult(undefined);
    request<ImpactResult>(
      `/api/impact?${new URLSearchParams({ catalogId: snapshot.id, catalogSha256: snapshot.identity.catalogSha256 })}`,
      abort.signal,
    )
      .then((r) => {
        if (!abort.signal.aborted) setResult(r);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [snapshot.identity.catalogSha256, retry]);
  const metadata = objectOf(result?.report?.metadata);
  const changes = objectOf(metadata.catalogChanges),
    obligations = objectOf(metadata.catalogAffectedObligations);
  const old = result?.base?.datasets.find((d) => d.id === dataset.id);
  const oldAssembly = objectOf(result?.base?.extensions?.['urn:ddk:catalog:assembly']);
  const oldDefinitions = objectOf(oldAssembly.datasetDefinitions);
  const fields = (objectOf(oldDefinitions[old?.alias ?? '']).properties ?? []) as {
    name: string;
    description?: string;
  }[];
  const newFields = snapshot.definitions[dataset.alias]?.properties ?? [];
  return (
    <Section
      title="Publisher definition-change report"
      aside={
        result?.available ? (
          <Badge status="unknown">Definition analysis · example</Badge>
        ) : undefined
      }
    >
      <p>
        This publisher-supplied report compares fixed dataset definitions. It does not change when
        you choose data versions above.
      </p>
      {!result && !error && <p role="status">Opening the definition-change report…</p>}
      {error && (
        <Notice
          title="Definition-change report could not be loaded"
          kind="error"
          action={<button onClick={() => setRetry((n) => n + 1)}>Retry report</button>}
        >
          {error}
        </Notice>
      )}
      {result && !result.available && (
        <Notice title="No publisher definition-change report is supplied">
          {result.reason} A definition-change report must identify the exact catalog copies it
          compares.
        </Notice>
      )}
      {result?.available && (
        <>
          <p>{String(result.binding?.scope)}</p>
          <Facts
            items={[
              [
                'Base definition',
                old
                  ? `${old.definition.contractId} @ ${old.definition.version}`
                  : 'Outside the base scope',
              ],
              [
                'Candidate definition',
                `${dataset.definition.contractId} @ ${dataset.definition.version}`,
              ],
              ['Comparison checks', <Badge status={String(result.report?.decision)} />],
            ]}
          />
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Definition changes">
            <table className="compare-table">
              <thead>
                <tr>
                  <th scope="col">Description</th>
                  <th scope="col">Base</th>
                  <th scope="col">Candidate</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Title</th>
                  <td>{old?.title || old?.alias || 'Not supplied'}</td>
                  <td>{dataset.title || dataset.alias}</td>
                </tr>
                {newFields
                  .filter(
                    (f) => fields.find((x) => x.name === f.name)?.description !== f.description,
                  )
                  .map((f) => (
                    <tr key={f.name}>
                      <th scope="row">{f.name}</th>
                      <td>
                        {fields.find((x) => x.name === f.name)?.description || 'Not supplied'}
                      </td>
                      <td>{f.description || 'Not supplied'}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <h3 className="impact-title">Follow-up work identified by the report</h3>
          {Object.entries(changes).map(([key, value]) => {
            const change = objectOf(value);
            return (
              <div className="check-row" key={key}>
                <div>
                  <strong>{key}</strong>
                  <p>
                    {Array.isArray(change.obligations)
                      ? change.obligations.map((v) => words(String(v))).join(' · ')
                      : 'Not supplied'}
                  </p>
                  <span className="subline">Computation: {words(String(change.computation))}</span>
                </div>
              </div>
            );
          })}
          <h3 className="impact-title">Datasets and tools that may need updates</h3>
          {Object.entries(obligations).map(([key, value]) => (
            <div className="plain-list" key={key}>
              <div>
                <strong>{key}</strong>
                <span>
                  {Array.isArray(value)
                    ? value.map((v) => words(String(v))).join(' · ')
                    : textValue(value)}
                </span>
              </div>
            </div>
          ))}
          <Notice title="The report does not carry out these updates">
            The report records changes and follow-up work. It does not recalculate data, approve
            checks in the publishing system, or select a release.
          </Notice>
          <Raw value={metadata.runtimeReuse} label="Computation and qualification reuse evidence" />
          <Raw
            value={metadata.unresolvedCatalogScope}
            label="Unresolved consumer and evidence scope"
          />
          <Raw value={result.binding} label="Exact base, candidate, report, and DDK identities" />
          <Raw
            value={result.report}
            label="Full publisher-issued report, including original categories"
          />
          <p>
            The JSON file contains this report and its identifiers. It does not contain dataset
            records.
          </p>
          <button
            className="button secondary"
            onClick={() => downloadJson('ddk-bound-impact.json', result)}
          >
            Download definition-change report (JSON) ↓
          </button>
        </>
      )}
    </Section>
  );
}
