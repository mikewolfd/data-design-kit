import { useEffect, useRef, useState } from 'react';
import type {
  CatalogDataset,
  CatalogSnapshot,
  CatalogVersion,
  ReadResult,
  ExactObject,
  ReadRequest,
} from '../domain/types';
import { request } from '../lib/client';
import { downloadJson, jsonInput, releaseFor, shortId } from '../lib/display';
import { Badge, Notice, Raw, Section, Value } from './Primitives';
import { EvidenceRecord } from './EvidenceRecord';
import { exactObjectField } from '../domain/exact';

export function ResultTable({
  rows,
  columns,
  positions,
}: {
  rows: ExactObject[];
  columns: string[];
  positions?: number[];
}) {
  const [selected, setSelected] = useState<number | undefined>();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => setSelected(undefined), [rows]);
  function inspect(index: number) {
    setSelected(selected === index ? undefined : index);
    setTimeout(() => heading.current?.focus(), 0);
  }
  return (
    <>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Data records; scroll horizontally for more fields"
      >
        <table className="data-table">
          <caption className="sr-only">Bounded records for the exact selected version</caption>
          <thead>
            <tr>
              <th scope="col">Record</th>
              {columns.map((c) => (
                <th key={c} scope="col">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={positions?.[i] ?? i} className={selected === i ? 'selected-row' : ''}>
                <td>
                  <button
                    className="row-button"
                    aria-label={`Inspect record ${String((positions?.[i] ?? i) + 1).padStart(2, '0')}`}
                    aria-expanded={selected === i}
                    onClick={() => inspect(i)}
                  >
                    {String((positions?.[i] ?? i) + 1).padStart(2, '0')}
                    <span aria-hidden="true">↗</span>
                  </button>
                </td>
                {columns.map((c) => (
                  <td key={c}>
                    <Value value={exactObjectField(row, c)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected !== undefined && rows[selected] && (
        <section className="record-inspector" aria-label="Record detail">
          <div className="section-heading">
            <h3 ref={heading} tabIndex={-1}>
              Record {(positions?.[selected] ?? selected) + 1}
            </h3>
            <button
              onClick={() => {
                setSelected(undefined);
                document
                  .querySelector<HTMLButtonElement>(`.row-button[aria-expanded="true"]`)
                  ?.focus();
              }}
            >
              Close detail
            </button>
          </div>
          <p className="muted">
            List positions identify occurrences. Repeated values remain separate.
          </p>
          <Value value={rows[selected]} full />
        </section>
      )}
    </>
  );
}
export function DataPanel({
  snapshot,
  dataset,
  version,
  releaseId,
}: {
  snapshot: CatalogSnapshot;
  dataset: CatalogDataset;
  version?: CatalogVersion;
  releaseId?: string;
}) {
  const reps = snapshot.catalog.representations.filter((r) => r.version === version?.id);
  const [representationId, setRepresentation] = useState(reps.length === 1 ? reps[0].id : '');
  const [result, setResult] = useState<ReadResult>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState<string>();
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [retry, setRetry] = useState(0);
  const [filterField, setFilterField] = useState('');
  const [filterText, setFilterText] = useState('');
  const [filterKind, setFilterKind] = useState('string');
  const [filter, setFilter] = useState<ReadRequest['filter']>();
  const [visibleColumns, setColumns] = useState<string[]>();
  const controller = useRef<AbortController>(null);
  const currentRequest = useRef<ReadRequest>(null);
  const rep = reps.find((r) => r.id === representationId);
  const fields = snapshot.definitions[dataset.alias]?.properties ?? [];
  const readSupported =
    snapshot.capabilities.read &&
    (!snapshot.capabilities.readDatasetIds ||
      snapshot.capabilities.readDatasetIds.includes(dataset.id));
  useEffect(() => {
    if (!version || !rep || !readSupported) return;
    const abort = new AbortController();
    controller.current = abort;
    const body: ReadRequest = {
      catalogId: snapshot.id,
      catalogSha256: snapshot.identity.catalogSha256,
      datasetId: dataset.id,
      versionId: version.id,
      representationId: rep.id,
      releaseId: releaseId || releaseFor(snapshot, version.id)?.id,
      cursor,
      limit: 10,
      filter,
    };
    currentRequest.current = body;
    setLoading(true);
    setError('');
    setResult(undefined);
    request<ReadResult>('/api/read', abort.signal, body)
      .then((data) => {
        if (!abort.signal.aborted) setResult(data);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [
    snapshot.identity.catalogSha256,
    dataset.id,
    version?.id,
    rep?.id,
    releaseId,
    cursor,
    filter,
    retry,
    readSupported,
  ]);
  function applyFilter(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      setFilter(
        filterField
          ? { path: [{ field: filterField }], equals: jsonInput(filterText, filterKind) }
          : undefined,
      );
      setHistory([]);
      setCursor(undefined);
      setError('');
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function exportPage() {
    try {
      downloadJson('ddk-record-page.json', {
        format: 'ddk-viewer-page/1',
        scope:
          'Only the displayed page; all returned fields retained with visible column order recorded. Not a full dataset export',
        numericEncoding: '{$number: exact JSON number lexeme}',
        catalog: snapshot.identity,
        request: currentRequest.current,
        display: { columns: visibleColumns ?? result?.columns, order: 'original' },
        result,
      });
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (!version)
    return (
      <Section title="Explore records">
        <Notice title="Choose an exact data version">
          A definition alone cannot resolve record access. Select a recorded version above when one
          is available.
        </Notice>
      </Section>
    );
  return (
    <>
      <Section
        title="Explore records"
        aside={
          snapshot.mode === 'fixture' ? (
            <Badge status="unknown">Demonstration data</Badge>
          ) : undefined
        }
      >
        {!readSupported ? (
          <Notice
            title={
              snapshot.capabilities.read
                ? 'Dataset outside the connected reader scope'
                : 'No reader is connected'
            }
          >
            {snapshot.capabilities.read && snapshot.capabilities.description
              ? snapshot.capabilities.description
              : snapshot.capabilities.reason ||
                'The owner must provide a bounded reader for the exact native version, view, schema, and field identities.'}
          </Notice>
        ) : null}
        {readSupported && snapshot.capabilities.description && (
          <p className="muted">{snapshot.capabilities.description}</p>
        )}
        <div className="data-toolbar">
          <label className="stack-label">
            Representation
            <select
              value={representationId}
              onChange={(e) => {
                setRepresentation(e.target.value);
                setCursor(undefined);
                setHistory([]);
                setResult(undefined);
              }}
            >
              <option value="">Choose a representation</option>
              {reps.map((r) => (
                <option key={r.id} value={r.id}>
                  {shortId(r.id)} · {r.availability}
                </option>
              ))}
            </select>
          </label>
          {rep && (
            <span className="toolbar-note">
              {rep.mediaType || rep.kind}
              <br />
              <Badge status={rep.availability} />
            </span>
          )}
        </div>
        {readSupported && rep && (
          <>
            {snapshot.mode === 'fixture' ? (
              <form onSubmit={applyFilter} className="filter-form">
                <label>
                  Field
                  <select value={filterField} onChange={(e) => setFilterField(e.target.value)}>
                    <option value="">All records</option>
                    {fields
                      .filter((f) => !f.items && !f.properties)
                      .map((f) => (
                        <option value={f.name} key={f.name}>
                          {f.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Value type
                  <select
                    value={filterKind}
                    disabled={!filterField}
                    onChange={(e) => setFilterKind(e.target.value)}
                  >
                    {['string', 'integer', 'number', 'boolean', 'null'].map((t) => (
                      <option value={t} key={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Equals
                  <input
                    value={filterText}
                    disabled={!filterField || filterKind === 'null'}
                    onChange={(e) => setFilterText(e.target.value)}
                    placeholder="Exact value"
                  />
                </label>
                <button className="button secondary" type="submit">
                  Apply filter
                </button>
                {filter && (
                  <button
                    type="button"
                    onClick={() => {
                      setFilter(undefined);
                      setFilterField('');
                      setFilterText('');
                      setCursor(undefined);
                      setHistory([]);
                    }}
                  >
                    Clear
                  </button>
                )}
              </form>
            ) : (
              <p className="muted">Generic filters are not supported by this owner reader.</p>
            )}
            <div className="result-bar">
              <span role="status" aria-live="polite">
                {loading
                  ? 'Reading the exact version…'
                  : result
                    ? `${result.returned} records on this page${result.total !== undefined ? ` · ${result.total} matching records` : ''}`
                    : error
                      ? 'Read failed'
                      : 'Ready to read'}
              </span>
              <div>
                {loading ? (
                  <button
                    onClick={() => {
                      controller.current?.abort();
                      setLoading(false);
                      setError(
                        'Stopped waiting for this read. Owner work may still finish; its outcome is unknown here. Your version and filter are preserved.',
                      );
                    }}
                  >
                    Stop waiting
                  </button>
                ) : null}
                {result?.status === 'ok' && (
                  <button onClick={exportPage}>Export this page ↓</button>
                )}
              </div>
            </div>
            {error && (
              <Notice
                title="Records could not be loaded"
                kind="error"
                action={<button onClick={() => setRetry((v) => v + 1)}>Retry read</button>}
              >
                {error}
              </Notice>
            )}
            {result && result.status !== 'ok' && (
              <Notice title={result.status === 'refused' ? 'Access refused' : 'Access is unknown'}>
                {result.reason}
                <div className="notice-actions">
                  <button onClick={() => setRetry((v) => v + 1)}>Retry read</button>
                </div>
              </Notice>
            )}
            {result?.status === 'ok' &&
              (result.rows.length ? (
                <>
                  <details className="column-picker">
                    <summary>Visible fields ({(visibleColumns ?? result.columns).length})</summary>
                    <div>
                      {result.columns.map((c) => (
                        <label key={c}>
                          <input
                            type="checkbox"
                            checked={(visibleColumns ?? result.columns).includes(c)}
                            onChange={(e) =>
                              setColumns(
                                e.target.checked
                                  ? [...(visibleColumns ?? result.columns), c]
                                  : (visibleColumns ?? result.columns).filter((x) => x !== c),
                              )
                            }
                          />
                          {c}
                        </label>
                      ))}
                    </div>
                  </details>
                  <ResultTable
                    rows={result.rows}
                    columns={visibleColumns ?? result.columns}
                    positions={result.rowPositions}
                  />
                </>
              ) : (
                <Notice title="No matching records">
                  The reader completed this bounded request. An empty result does not establish
                  source completeness.
                </Notice>
              ))}
            {result?.continuation === 'unknown' && (
              <Notice title="Continuation is unknown">
                The owner did not report whether another page exists. These records are not evidence
                of the end of the dataset.
              </Notice>
            )}
            <div className="pagination">
              <span>
                {result?.rowOrder === 'query-result'
                  ? `${result.continuation === 'complete' ? 'Complete read' : 'Bounded page'} · native query result order`
                  : snapshot.mode === 'fixture'
                    ? '10 records per page · original order'
                    : '10 records per page · owner-reported positions'}
              </span>
              <div>
                <button
                  disabled={!history.length || loading}
                  onClick={() => {
                    setCursor(history[history.length - 1]);
                    setHistory((h) => h.slice(0, -1));
                  }}
                >
                  ← Previous
                </button>
                <button
                  disabled={!result?.nextCursor || loading}
                  onClick={() => {
                    setHistory((h) => [...h, cursor]);
                    setCursor(result!.nextCursor);
                  }}
                >
                  Next →
                </button>
              </div>
            </div>
          </>
        )}
        {!reps.length && (
          <Notice title="No representation is recorded">
            The exact version exists in the catalog, but no file, table, or service is offered for
            it.
          </Notice>
        )}
      </Section>
      <Section title="Exact read context">
        {result?.attempt && (
          <EvidenceRecord
            snapshot={snapshot}
            record={result.attempt}
            label="Inspect viewer read request"
          />
        )}
        {result?.readEvidence && (
          <>
            <Raw value={result.readEvidence} label="Read evidence and consumed version" />
            {result.readEvidence.kind === 'owner' && (
              <EvidenceRecord
                snapshot={snapshot}
                record={result.readEvidence.record}
                label="Inspect native read receipt"
              />
            )}
          </>
        )}
        <Raw
          value={{ catalogSha256: snapshot.identity.catalogSha256, version, representation: rep }}
          label="Version, representation, and source identities"
        />
        <p className="muted">
          Numbers retain their exact text. Null, missing, empty text, and empty lists remain
          distinct. The viewer makes no source completeness or quality claim from readable records.
        </p>
      </Section>
    </>
  );
}
