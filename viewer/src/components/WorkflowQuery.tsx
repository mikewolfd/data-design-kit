import { useEffect, useId, useRef, useState } from 'react';
import type {
  CatalogSnapshot,
  ExactBinding,
  ExactObject,
  QueryRequest,
  QueryResult,
} from '../domain/types';
import { exactObjectField } from '../domain/exact';
import { request } from '../lib/client';
import { downloadJson, objectOf, words } from '../lib/display';
import { type PublisherWorkflow } from '../features/publisher-metadata';
import {
  recordMetadata,
  resolveRowAction,
  workflowResultBinding,
} from '../features/publisher-metadata/row-actions';
import { queryExport, queryResultMatches } from '../features/resource-details';
import { EvidenceRecord } from './EvidenceRecord';
import { Notice, Raw, Value } from './Primitives';
import { ResultTable } from './ResultTable';

/** A publisher's ready-to-run question, with exact inputs visible and ordinary query admission. */
export function WorkflowQuery({
  snapshot,
  workflow,
  initialParameters,
  autoRun = false,
  active = true,
  depth = 0,
}: {
  snapshot: CatalogSnapshot;
  workflow: PublisherWorkflow;
  initialParameters?: Record<string, string>;
  autoRun?: boolean;
  active?: boolean;
  depth?: number;
}) {
  const [parameters, setParameters] = useState({ ...workflow.defaults, ...initialParameters });
  const [received, setReceived] = useState<{ request: QueryRequest; result: QueryResult }>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController>(null);
  const completion = useRef<HTMLDivElement>(null);
  const id = useId();
  const recipe = snapshot.catalog.recipes.find(({ id }) => id === workflow.recipeId);
  const properties = objectOf(recipe?.parameters.properties);
  const required = Array.isArray(recipe?.parameters.required)
    ? (recipe.parameters.required as string[])
    : [];
  const supported =
    snapshot.capabilities.query &&
    (!snapshot.capabilities.queryRecipeIds ||
      snapshot.capabilities.queryRecipeIds.includes(workflow.recipeId));
  const binding = workflowResultBinding(snapshot, workflow);
  async function run() {
    if (!active || !supported || !recipe) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setReceived(undefined);
    setError('');
    setLoading(true);
    const body: QueryRequest = {
      catalogId: snapshot.id,
      catalogSha256: snapshot.identity.catalogSha256,
      recipeId: recipe.id,
      bindings: workflow.bindings,
      parameters,
      limit: 25,
    };
    try {
      const result = await request<QueryResult>('/api/query', abort.signal, body);
      if (!abort.signal.aborted) {
        if (!queryResultMatches(snapshot, body, result))
          throw new Error(
            'The response does not match this lookup and its exact data versions. Run the lookup again.',
          );
        setReceived({ request: body, result });
      }
    } catch (error) {
      if (!abort.signal.aborted)
        setError(error instanceof Error ? error.message : 'The lookup failed.');
    } finally {
      if (!abort.signal.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    if (autoRun) void run();
    return () => controller.current?.abort();
  }, []);
  useEffect(() => {
    if (!active && loading) {
      controller.current?.abort();
      setLoading(false);
      setError(
        'The viewer stopped waiting when you left this view. The native outcome may be unknown. Your lookup keys and exact inputs are preserved. Run it again to retry.',
      );
    }
  }, [active, loading]);
  useEffect(() => {
    if (received || error) completion.current?.focus({ preventScroll: false });
  }, [received, error]);
  const result = received?.result;
  return (
    <section className="workflow-query" aria-label={workflow.title}>
      <h2>{workflow.title}</h2>
      <p>{workflow.summary}</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void run();
        }}
      >
        <div className="workflow-parameters">
          {Object.entries(properties).map(([name, property]) => (
            <label className="stack-label" key={name} htmlFor={`${id}-${name}`}>
              {String(objectOf(property).title ?? words(name))}
              <input
                id={`${id}-${name}`}
                value={parameters[name] ?? ''}
                required={required.includes(name)}
                onChange={(event) => {
                  controller.current?.abort();
                  setLoading(false);
                  setReceived(undefined);
                  setError('');
                  setParameters((previous) => ({ ...previous, [name]: event.target.value }));
                }}
              />
            </label>
          ))}
          <button
            className="primary"
            type="submit"
            disabled={
              !active || !supported || loading || required.some((name) => !parameters[name]?.trim())
            }
          >
            {loading ? 'Looking up…' : 'Run lookup'}
          </button>
        </div>
      </form>
      <details className="workflow-inputs">
        <summary>Data versions used by this lookup</summary>
        <p>
          These are the publisher's explicit retained inputs for this task. Their use does not
          establish latest data or publisher-wide coverage.
        </p>
        <Raw value={workflow.bindings} label="Exact input identities" />
      </details>
      {!supported && (
        <Notice title="Lookup unavailable">
          This catalog's connected owner does not provide this query.
        </Notice>
      )}
      <div className="workflow-completion" ref={completion} tabIndex={-1} aria-live="polite">
        {loading && <p role="status">Reading the selected data versions…</p>}
        {error && <Notice title="Lookup could not complete">{error}</Notice>}
        {result && result.status !== 'ok' && (
          <Notice title={result.status === 'unknown' ? 'Lookup outcome unknown' : 'Lookup refused'}>
            {result.reason ?? 'The owner did not return an accepted result.'}
          </Notice>
        )}
        {result?.status === 'ok' && (
          <>
            <div className="section-heading">
              <h3>
                {result.rows.length} {result.rows.length === 1 ? 'record' : 'records'} returned
              </h3>
              <button
                onClick={() => {
                  try {
                    downloadJson(
                      'ddk-lookup-result.json',
                      queryExport(snapshot, received!.request, result),
                    );
                  } catch (error) {
                    setError((error as Error).message);
                  }
                }}
              >
                Download query and results (JSON) ↓
              </button>
            </div>
            {result.rows.length ? (
              <ResultTable
                rows={result.rows}
                columns={result.columns}
                renderRecord={
                  binding
                    ? (row) => (
                        <RecordPresentation
                          snapshot={snapshot}
                          binding={binding}
                          row={row}
                          active={active}
                          depth={depth}
                        />
                      )
                    : undefined
                }
              />
            ) : (
              <Notice title="No matching records">
                {workflow.emptyMessage ??
                  'This lookup completed with no matches in the selected data versions.'}
              </Notice>
            )}
            {result.hasMore && (
              <p className="muted">
                This is a bounded result. More matches may exist in the selected data versions.
              </p>
            )}
            {result.execution?.record && (
              <EvidenceRecord
                snapshot={snapshot}
                record={result.execution.record}
                label="Inspect native query receipt"
                active={active}
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}

export function RecordPresentation({
  snapshot,
  binding,
  row,
  active = true,
  depth = 0,
}: {
  snapshot: CatalogSnapshot;
  binding: ExactBinding;
  row: ExactObject;
  active?: boolean;
  depth?: number;
}) {
  const metadata = recordMetadata(snapshot, binding);
  const dataset = snapshot.catalog.datasets.find(({ id }) => id === binding.datasetId);
  const fields = dataset ? (snapshot.definitions[dataset.alias]?.properties ?? []) : [];
  const [opened, setOpened] = useState<string>();
  const closeButton = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    setOpened(undefined);
  }, [row]);
  const actions = (metadata?.rowActions ?? []).map((action) => ({
    action,
    result: resolveRowAction(snapshot, row, action),
  }));
  const selected = actions.find(({ action }) => action.id === opened);
  const readable =
    metadata?.readableFields?.flatMap((name) => {
      const value = exactObjectField(row, name);
      return typeof value === 'string' && value.length ? [{ name, value }] : [];
    }) ?? [];
  return (
    <>
      {!!actions.length && (
        <div className="record-actions" aria-label="Record actions">
          {actions.map(({ action, result }) => (
            <div key={action.id}>
              {result.kind === 'original' ? (
                <EvidenceRecord
                  snapshot={snapshot}
                  record={result.record}
                  label={action.label}
                  purpose="original"
                  compact
                  active={active}
                />
              ) : (
                <>
                  <button
                    disabled={result.kind === 'unavailable' || depth >= 4}
                    onClick={(event) => {
                      trigger.current = event.currentTarget;
                      setOpened(action.id);
                      setTimeout(() => closeButton.current?.focus(), 0);
                    }}
                  >
                    {action.label}
                  </button>
                  {result.kind === 'unavailable' && <p className="muted">{result.reason}</p>}
                  {depth >= 4 && result.kind === 'recipe' && (
                    <p className="muted">Close a related lookup before opening another.</p>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      )}
      {selected?.result.kind === 'recipe' && (
        <section className="related-lookup" aria-label="Related record lookup">
          <button
            ref={closeButton}
            onClick={() => {
              setOpened(undefined);
              trigger.current?.focus();
            }}
          >
            Return to this record
          </button>
          <WorkflowQuery
            key={`${opened}:${JSON.stringify(selected.result.parameters)}`}
            snapshot={snapshot}
            workflow={selected.result.workflow}
            initialParameters={selected.result.parameters}
            autoRun
            active={active}
            depth={depth + 1}
          />
        </section>
      )}
      {readable.map(({ name, value }) => (
        <section className="readable-record" key={name}>
          <h4>{fields.find((field) => field.name === name)?.businessName ?? words(name)}</h4>
          <p>{value}</p>
        </section>
      ))}
      {readable.length ? (
        <details className="record-original-fields">
          <summary>All fields, including original source text</summary>
          <Value value={row} full />
        </details>
      ) : (
        <Value value={row} full />
      )}
    </>
  );
}
