import { useEffect, useId, useRef, useState, type SyntheticEvent } from 'react';
import type { CatalogSnapshot, ExactBinding, QueryResult, SqlRequest } from '../domain/types';
import { request } from '../lib/client';
import { downloadJson, titleOf, versionsOf } from '../lib/display';
import { representationChoices, versionChoices } from '../lib/choice-labels';
import { quotedSqlTable, sqlResultExport, sqlResultMatches } from '../lib/sql-results';
import { BlankValuesHelp, Notice, Raw } from './Primitives';
import { ResultTable } from './DataPanel';
import { EvidenceRecord } from './EvidenceRecord';

type Selection = { versionId: string; representationId: string };

export function QueryLab({
  snapshot,
  initialBinding,
  active = true,
}: {
  snapshot: CatalogSnapshot;
  initialBinding?: ExactBinding;
  active?: boolean;
}) {
  const [sql, setSql] = useState('');
  const [limit, setLimit] = useState(25);
  const [selections, setSelections] = useState<Record<string, Selection>>(() =>
    initialBinding ? { [initialBinding.datasetId]: initialBinding } : {},
  );
  const [tablePickerOpen, setTablePickerOpen] = useState(!initialBinding?.representationId);
  const [tableSearch, setTableSearch] = useState('');
  const [message, setMessage] = useState('');
  const [undo, setUndo] = useState<{
    sql: string;
    limit: number;
    selections: Record<string, Selection>;
  }>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [received, setReceived] = useState<{
    request: SqlRequest;
    result: QueryResult;
    sqlSha256: string;
  }>();
  const controller = useRef<AbortController>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const outcome = useRef<HTMLDivElement>(null);
  const editorId = useId();
  const activeRef = useRef(active);
  activeRef.current = active;
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!active && loading) {
      controller.current?.abort();
      setLoading(false);
      setMessage(
        'Stopped waiting for the query when you left this view. Its native outcome may be unknown; your draft is retained.',
      );
    }
  }, [active, loading]);
  useEffect(() => {
    if (activeRef.current && (received || error)) outcome.current?.focus();
  }, [received, error]);
  const tables = snapshot.catalog.datasets.filter(
    (dataset) => versionsOf(snapshot, dataset).length,
  );
  const bindings: Record<string, ExactBinding> = {};
  for (const dataset of tables) {
    const selection = selections[dataset.id];
    if (selection?.versionId && selection.representationId)
      bindings[dataset.alias] = { datasetId: dataset.id, ...selection };
  }
  const current: SqlRequest = {
    catalogId: snapshot.id,
    catalogSha256: snapshot.identity.catalogSha256,
    sql,
    bindings,
    limit,
  };
  const visibleTables = tables.filter((dataset) =>
    `${titleOf(dataset)} ${dataset.alias}`.toLowerCase().includes(tableSearch.toLowerCase()),
  );
  const incomplete = Object.values(selections).some(
    (item) => item.versionId && !item.representationId,
  );
  const result =
    received && JSON.stringify(received.request) === JSON.stringify(current)
      ? received.result
      : undefined;

  function edit() {
    setError('');
    setReceived(undefined);
    setMessage('');
  }
  function insertTable(alias: string) {
    const input = editor.current;
    const start = input?.selectionStart ?? sql.length;
    const end = input?.selectionEnd ?? start;
    const name = quotedSqlTable(alias);
    setUndo({ sql, limit, selections });
    edit();
    setSql(sql.slice(0, start) + name + sql.slice(end));
    setMessage(`Inserted ${alias}. Choose its exact data version if it is not included yet.`);
    requestAnimationFrame(() => {
      input?.focus();
      input?.setSelectionRange(start + name.length, start + name.length);
    });
  }
  function startQuery(datasetId: string, alias: string) {
    setUndo({ sql, limit, selections });
    edit();
    setSql(`SELECT *\nFROM ${quotedSqlTable(alias)}\nLIMIT 25`);
    setLimit(25);
    const selected =
      selections[datasetId] ||
      (initialBinding?.datasetId === datasetId ? initialBinding : undefined);
    setSelections(selected ? { [datasetId]: selected } : {});
    setMessage(
      selected?.versionId && selected.representationId
        ? `Started a new query for ${alias} using your selected version. You can undo this replacement.`
        : `Started a new query for ${alias}. Choose ${selected?.versionId ? 'a resource' : 'a data version'} before running it. You can undo this replacement.`,
    );
    if (!selected?.versionId || !selected.representationId) setTablePickerOpen(true);
    editor.current?.focus();
  }
  async function run(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !active ||
      !snapshot.capabilities.sql ||
      !sql.trim() ||
      !Object.keys(bindings).length ||
      incomplete ||
      loading
    )
      return;
    const abort = new AbortController();
    controller.current?.abort();
    controller.current = abort;
    setLoading(true);
    setTablePickerOpen(false);
    setMessage('');
    setError('');
    setReceived(undefined);
    try {
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(sql));
      const sqlSha256 = [...new Uint8Array(digest)]
        .map((byte) => byte.toString(16).padStart(2, '0'))
        .join('');
      const value = await request<QueryResult>('/api/sql', abort.signal, current);
      if (abort.signal.aborted || !activeRef.current || controller.current !== abort) return;
      if (!sqlResultMatches(snapshot, current, value, sqlSha256))
        throw new Error(
          'The response does not match the submitted SQL and selected inputs. Run the query again to retry.',
        );
      setReceived({ request: current, result: value, sqlSha256 });
    } catch (cause) {
      if (!abort.signal.aborted && activeRef.current && controller.current === abort)
        setError((cause as Error).message);
    } finally {
      if (!abort.signal.aborted && controller.current === abort) setLoading(false);
    }
  }

  if (!snapshot.capabilities.sql)
    return (
      <Notice title="Query lab is not connected">
        This catalog has no adapter for custom SQL. Publisher-authored queries remain under Related
        data.
      </Notice>
    );

  return (
    <section className="query-lab" aria-label="Query lab">
      <div className="section-heading">
        <h2>Query lab</h2>
        <span className="muted">Read-only · up to 100 rows</span>
      </div>
      <p className="muted">
        Choose a data version for each table you need, then query those exact inputs.
      </p>
      <div className="query-workspace">
        <div className="query-main">
          <form onSubmit={run} className="query-editor">
            <label htmlFor={editorId}>SQL query</label>
            <textarea
              id={editorId}
              ref={editor}
              value={sql}
              placeholder={'SELECT *\nFROM "table_name"\nLIMIT 25'}
              maxLength={32768}
              spellCheck={false}
              aria-describedby={`${editorId}-help`}
              disabled={loading}
              onChange={(event) => {
                edit();
                setSql(event.target.value);
              }}
            />
            <div className="query-actions">
              <button
                className="button primary"
                type="submit"
                disabled={loading || !sql.trim() || !Object.keys(bindings).length || incomplete}
              >
                {loading ? 'Running query…' : 'Run SQL query'} <span aria-hidden="true">↗</span>
              </button>
              <label className="query-limit">
                Row limit
                <input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={limit}
                  disabled={loading}
                  onChange={(event) => {
                    edit();
                    setLimit(event.currentTarget.valueAsNumber);
                  }}
                />
              </label>
            </div>
            <p id={`${editorId}-help`} className="muted">
              Empty results are valid. A refusal or an unknown outcome stays visible. Choosing a
              table here does not establish source completeness.
            </p>
            <p className="muted">
              {Object.keys(bindings).length} tables selected
              {incomplete ? ' · Choose a resource for every included version.' : '.'}
              {!!Object.keys(bindings).length && ` ${Object.keys(bindings).join(', ')}`}
            </p>
            {undo && (
              <button
                type="button"
                disabled={loading}
                onClick={() => {
                  edit();
                  setSql(undo.sql);
                  setLimit(undo.limit);
                  setSelections(undo.selections);
                  setUndo(undefined);
                  setMessage('Previous query and input choices restored.');
                }}
              >
                Undo query edit
              </button>
            )}
            {message && <p role="status">{message}</p>}
          </form>
          <div ref={outcome} className="query-outcome" tabIndex={-1} aria-label="Query outcome">
            {error && (
              <Notice title="Query needs attention" kind="error">
                {error}
              </Notice>
            )}
            <div role="status" aria-live="polite">
              {loading
                ? 'Running the submitted query…'
                : result?.status === 'ok'
                  ? `${result.returned} query results`
                  : ''}
            </div>
            {result && result.status !== 'ok' && (
              <Notice
                title={
                  result.status === 'unknown'
                    ? 'Query request outcome is unknown'
                    : 'Query results were not loaded'
                }
              >
                {result.reason ||
                  (result.status === 'unknown'
                    ? 'The request did not establish an outcome.'
                    : 'The connected reader refused this request.')}
                <Raw
                  value={{ status: result.status, reason: result.reason, attempt: result.attempt }}
                  label="Query outcome details"
                />
              </Notice>
            )}
            {result?.attempt && (
              <EvidenceRecord
                snapshot={snapshot}
                record={result.attempt}
                label="Inspect viewer query request"
              />
            )}
            {result?.status === 'ok' && received && (
              <section className="query-results" aria-label="SQL query results">
                <div className="result-bar">
                  <span>Results for the selected inputs</span>
                  <button
                    onClick={() => {
                      try {
                        downloadJson(
                          'ddk-sql-result.json',
                          sqlResultExport(snapshot, received.request, result, received.sqlSha256),
                        );
                      } catch (cause) {
                        setError((cause as Error).message);
                      }
                    }}
                  >
                    Download SQL and results (JSON) ↓
                  </button>
                </div>
                <BlankValuesHelp />
                {result.rows.length ? (
                  <ResultTable
                    rows={result.rows}
                    columns={result.columns}
                    caption="Results of the submitted SQL against the selected exact inputs"
                  />
                ) : (
                  <Notice title="No matching results">
                    This query completed with no matches for the selected inputs.
                  </Notice>
                )}
                <Raw
                  value={{
                    catalog: snapshot.identity,
                    request: received.request,
                    execution: result.execution,
                  }}
                  label="SQL, input versions and execution evidence"
                />
                {result.execution?.kind === 'owner' && result.execution.record && (
                  <EvidenceRecord
                    snapshot={snapshot}
                    record={result.execution.record}
                    label="Inspect native SQL query receipt"
                  />
                )}
              </section>
            )}
          </div>
        </div>
        <aside className="query-tables" aria-label="Query tables">
          <details
            open={tablePickerOpen}
            onToggle={(event) => setTablePickerOpen(event.currentTarget.open)}
          >
            <summary>Choose tables · {Object.keys(bindings).length} selected</summary>
            <label className="stack-label">
              Find a table
              <input
                type="search"
                value={tableSearch}
                onChange={(event) => setTableSearch(event.target.value)}
              />
            </label>
            <div className="query-table-list">
              {tables.length ? (
                visibleTables.map((dataset) => {
                  const versions = versionsOf(snapshot, dataset);
                  const selection = selections[dataset.id];
                  const representations = snapshot.catalog.representations.filter(
                    (item) => item.version === selection?.versionId,
                  );
                  return (
                    <div className="query-table" key={dataset.id}>
                      <h3>{titleOf(dataset)}</h3>
                      <code>{dataset.alias}</code>
                      <label>
                        Data version for {dataset.alias}
                        <select
                          value={selection?.versionId ?? ''}
                          disabled={loading}
                          onChange={(event) => {
                            edit();
                            const versionId = event.target.value;
                            const resources = snapshot.catalog.representations.filter(
                              (item) => item.version === versionId,
                            );
                            setSelections((old) => ({
                              ...old,
                              [dataset.id]: {
                                versionId,
                                representationId: resources.length === 1 ? resources[0].id : '',
                              },
                            }));
                          }}
                        >
                          <option value="">Not included</option>
                          {versionChoices(snapshot, dataset, versions).map((option) => (
                            <option value={option.id} key={option.id}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      {selection?.versionId && (
                        <label>
                          Resource for {dataset.alias}
                          <select
                            value={selection.representationId}
                            disabled={loading}
                            onChange={(event) => {
                              edit();
                              setSelections((old) => ({
                                ...old,
                                [dataset.id]: {
                                  ...selection,
                                  representationId: event.target.value,
                                },
                              }));
                            }}
                          >
                            <option value="">Choose a resource</option>
                            {representationChoices(dataset, representations).map((option) => (
                              <option value={option.id} key={option.id}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                      <button
                        type="button"
                        className="text-button"
                        disabled={loading}
                        onClick={() => insertTable(dataset.alias)}
                      >
                        Insert table name
                      </button>
                      <button
                        type="button"
                        className="text-button"
                        disabled={loading}
                        onClick={() => startQuery(dataset.id, dataset.alias)}
                      >
                        {sql.trim() ? 'Replace with new query' : 'Start query'}
                      </button>
                      <details>
                        <summary>Fields and exact choices</summary>
                        <p className="muted">
                          Fields:{' '}
                          {(snapshot.definitions[dataset.alias]?.properties ?? [])
                            .map((field) => field.name)
                            .join(', ') || 'Not supplied'}
                        </p>
                        <Raw
                          value={{
                            datasetId: dataset.id,
                            versionId: selection?.versionId || null,
                            representationId: selection?.representationId || null,
                          }}
                          label="Exact input identifiers"
                        />
                      </details>
                    </div>
                  );
                })
              ) : (
                <p className="muted">No data versions are listed in this catalog.</p>
              )}
              {!visibleTables.length && <p className="muted">No tables match this search.</p>}
            </div>
          </details>
        </aside>
      </div>
    </section>
  );
}
