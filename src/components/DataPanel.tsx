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
import { downloadJson, jsonInput, releaseFor, shortId, titleOf } from '../lib/display';
import { Badge, Notice, Raw, Section, Value, BlankValuesHelp } from './Primitives';
import { EvidenceRecord } from './EvidenceRecord';
import { formatLabel, enumLabel } from '../lib/content';
import { exactObjectField } from '../domain/exact';

export function ResultTable({
  rows,
  columns,
  positions,
  caption = 'Records returned by this request',
}: {
  rows: ExactObject[];
  columns: string[];
  positions?: number[];
  caption?: string;
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
          <caption className="sr-only">{caption}</caption>
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
          <p className="muted">Each listed item is kept separately, including repeated values.</p>
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
  const [errorCode, setErrorCode] = useState('');
  const [errorDiagnostic, setErrorDiagnostic] = useState('');
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
    setErrorCode('');
    setResult(undefined);
    request<ReadResult>('/api/read', abort.signal, body)
      .then((data) => {
        if (!abort.signal.aborted) setResult(data);
      })
      .catch((e) => {
        if (!abort.signal.aborted) {
          setError(e.message);
          setErrorCode(e.code || '');
          setErrorDiagnostic(e.technicalMessage || e.message);
        }
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
    setErrorCode('');
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
      setErrorCode('export_too_large');
      setErrorDiagnostic((e as Error).message);
    }
  }
  const versions = snapshot.catalog.versions.filter(
    (item) => item.dataset === dataset.alias || item.dataset === dataset.id,
  );
  const cursorError = ['invalid_cursor', 'cursor_mismatch'].includes(errorCode);
  const quotaError = errorCode === 'native_quota';
  if (!version)
    return (
      <Section title="View records">
        <Notice
          title={
            versions.length
              ? 'Choose a data version to view records'
              : 'Records are not available in this portal'
          }
        >
          {versions.length
            ? 'Select a data version above to view its access details.'
            : 'You can explore the dataset description and fields. This catalog does not include a data version to open.'}
        </Notice>
      </Section>
    );
  return (
    <>
      <Section
        title="View records"
        aside={
          snapshot.mode === 'fixture' ? (
            <Badge status="unknown">Demonstration data</Badge>
          ) : snapshot.exampleData === 'authored' ? (
            <Badge status="unknown">Saved example data</Badge>
          ) : undefined
        }
      >
        {!readSupported ? (
          <Notice
            title={
              snapshot.capabilities.read
                ? 'Records for this dataset are not connected'
                : 'Viewing records is not connected'
            }
          >
            You can explore the dataset description and fields. This portal cannot open this
            dataset’s records.
            <Raw value={snapshot.capabilities} label="Reader connection details" />
          </Notice>
        ) : null}

        <div className="data-toolbar">
          <label className="stack-label">
            File, table or service
            <select
              value={representationId}
              onChange={(e) => {
                setRepresentation(e.target.value);
                setCursor(undefined);
                setHistory([]);
                setResult(undefined);
              }}
            >
              <option value="">Choose a file, table or service</option>
              {reps.map((r) => (
                <option key={r.id} value={r.id}>
                  {shortId(r.id)} · {enumLabel(r.availability)}
                </option>
              ))}
            </select>
          </label>
          {rep && (
            <span className="toolbar-note">
              {formatLabel(rep.mediaType, rep.kind)}
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
                    Clear filter
                  </button>
                )}
              </form>
            ) : (
              <p className="muted">Filtering records is not supported by this connection.</p>
            )}
            <div className="result-bar">
              <span role="status" aria-live="polite">
                {loading
                  ? 'Loading records…'
                  : result?.status === 'ok'
                    ? `${result.returned} ${result.returned === 1 ? 'record' : 'records'} on this page${result.total !== undefined ? ` · ${result.total} matching ${result.total === 1 ? 'record' : 'records'}` : ''}`
                    : result || error
                      ? 'Records were not loaded.'
                      : 'Ready to load records'}
              </span>
              <div>
                {loading ? (
                  <button
                    onClick={() => {
                      controller.current?.abort();
                      setLoading(false);
                      setErrorCode('');
                      setError(
                        'Stopped waiting. The source may still finish the request; this portal does not know its outcome. Your version and filter are preserved.',
                      );
                    }}
                  >
                    Stop waiting
                  </button>
                ) : null}
                {result?.status === 'ok' && (
                  <button onClick={exportPage}>Download this page (JSON) ↓</button>
                )}
              </div>
            </div>
            {result?.status === 'ok' && (
              <p className="muted">
                Download includes all returned fields for this page, including fields hidden in the
                table. It is not the full dataset. JSON is a structured data-file format.
              </p>
            )}
            {error && (
              <Notice
                title={
                  cursorError
                    ? 'This page link is no longer valid'
                    : errorCode === 'export_too_large'
                      ? 'This page could not be downloaded'
                      : 'Records could not be loaded'
                }
                kind="error"
                action={
                  cursorError ? (
                    <button
                      onClick={() => {
                        setHistory([]);
                        setCursor(undefined);
                        setRetry((v) => v + 1);
                      }}
                    >
                      Return to first page
                    </button>
                  ) : !quotaError &&
                    ![
                      'result_budget',
                      'column_budget',
                      'browser_budget',
                      'result_too_large',
                      'response_too_large',
                      'export_too_large',
                    ].includes(errorCode) &&
                    !error.startsWith('Stopped waiting') ? (
                    <button onClick={() => setRetry((v) => v + 1)}>Retry read</button>
                  ) : undefined
                }
              >
                {cursorError ? 'Return to the first page to continue.' : error}
                {snapshot.mode === 'fixture' &&
                  ['result_budget', 'column_budget', 'browser_budget', 'export_too_large'].includes(
                    errorCode,
                  ) && <p>You can change the filter above and try again.</p>}
                {errorCode && (
                  <Raw
                    value={{ code: errorCode, message: errorDiagnostic || error }}
                    label="Error details"
                  />
                )}
              </Notice>
            )}
            {result && result.status !== 'ok' && (
              <Notice
                title={
                  version.referenceDisclosure === 'withheld'
                    ? 'This version is withheld'
                    : result.status === 'unknown'
                      ? version.retention === 'unknown' || rep.availability === 'unknown'
                        ? 'Record availability is unknown'
                        : 'Request outcome is unknown'
                      : 'Records cannot be opened'
                }
              >
                {version.referenceDisclosure === 'withheld'
                  ? 'The catalog does not disclose the details needed to open its records.'
                  : result.status === 'unknown'
                    ? version.retention === 'unknown' || rep.availability === 'unknown'
                      ? 'The catalog does not confirm whether this version can be opened.'
                      : 'This request did not establish an outcome. The source may still finish; this portal does not know its result.'
                    : result.reason}
                {versions.length > 1 && <p>You can choose another listed version above.</p>}
                <Raw
                  value={{ status: result.status, reason: result.reason }}
                  label="Access details"
                />
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

                  <BlankValuesHelp />
                  <ResultTable
                    caption={`Records from ${titleOf(dataset)}, version ${shortId(version.id)} · this page only`}
                    rows={result.rows}
                    columns={visibleColumns ?? result.columns}
                    positions={result.rowPositions}
                  />
                </>
              ) : (
                <Notice
                  title={
                    filter ? 'No records match this filter' : 'This request returned no records'
                  }
                >
                  {filter
                    ? 'Try another value or clear the filter. This result applies to the selected version.'
                    : 'This result applies to the selected version and request.'}
                </Notice>
              ))}
            {result?.continuation === 'unknown' && (
              <Notice title="More records: unknown">
                The source did not report whether more records are available. This page does not
                establish the end of the dataset.
              </Notice>
            )}
            <div className="pagination">
              <span>
                {result?.rowOrder === 'query-result'
                  ? `${result.continuation === 'complete' ? 'All records in this saved result returned' : 'This page only'} · query result order`
                  : snapshot.mode === 'fixture'
                    ? '10 records per page · original order'
                    : '10 records per page · source-reported positions'}
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
          <Notice title="No file, table or service is listed">
            The exact version exists in the catalog, but no file, table, or service is offered for
            it.
          </Notice>
        )}
      </Section>
      <Section title="Technical read details">
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
