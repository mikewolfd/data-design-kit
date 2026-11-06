import { useEffect, useRef, useState } from 'react';
import type {
  CatalogDataset,
  CatalogSnapshot,
  CatalogVersion,
  CatalogRecipe,
  QueryRequest,
  QueryResult,
  ExactBinding,
  ExactValue,
} from '../domain/types';
import { request, readText } from '../lib/client';
import {
  downloadJson,
  jsonInput,
  objectOf,
  pathLabel,
  shortId,
  titleOf,
  words,
} from '../lib/display';
import { Badge, Facts, Notice, Raw, Section } from './Primitives';
import { ResultTable } from './DataPanel';
import { EvidenceRecord } from './EvidenceRecord';

function Recipe({
  recipe,
  snapshot,
  version,
}: {
  recipe: CatalogRecipe;
  snapshot: CatalogSnapshot;
  version?: CatalogVersion;
}) {
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [releaseId, setRelease] = useState('');
  const [bindingMode, setBindingMode] = useState<'release' | 'versions'>('release');
  const [versionsByInput, setVersionsByInput] = useState<Record<string, string>>({});
  const [representationsByInput, setRepresentationsByInput] = useState<Record<string, string>>({});
  const [result, setResult] = useState<QueryResult>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [sql, setSql] = useState<string>();
  const [sqlLoading, setSqlLoading] = useState(false);
  const controller = useRef<AbortController>(null);
  const sqlController = useRef<AbortController>(null);
  const queryRef = useRef<QueryRequest>(null);
  const querySupported =
    snapshot.capabilities.query &&
    (!snapshot.capabilities.queryRecipeIds ||
      snapshot.capabilities.queryRecipeIds.includes(recipe.id));
  const schema = objectOf(recipe.parameters.properties);
  const order = recipe.parameterOrder ?? Object.keys(schema);
  const required = Array.isArray(recipe.parameters.required)
    ? (recipe.parameters.required as string[])
    : [];
  const releases = snapshot.catalog.releases.filter(
    (r) => !version || r.members.includes(version.id),
  );
  useEffect(
    () => () => {
      controller.current?.abort();
      sqlController.current?.abort();
    },
    [],
  );
  const bindings: Record<string, ExactBinding> = {};
  const representationChoices: {
    input: string;
    choices: CatalogSnapshot['catalog']['representations'];
  }[] = [];
  const relationships = snapshot.catalog.relationships.filter((r) =>
    recipe.relationships.includes(r.id),
  );
  const requiresRelease = relationships.some((r) => r.scope === 'same_release');
  const unsupportedRelationship = relationships.some(
    (r) => r.scope === 'declared' || r.scope === 'external' || !!r.target.external,
  );
  let bindingProblem = '';
  const release = snapshot.catalog.releases.find((r) => r.id === releaseId);
  if (unsupportedRelationship)
    bindingProblem =
      'A required relationship has no supported exact resolver in the selected DDK profile.';
  else if (bindingMode === 'release' && !release)
    bindingProblem = 'Choose an explicit release for the recipe inputs.';
  else if (bindingMode === 'release' && release?.membership !== 'complete')
    bindingProblem = 'This release does not establish complete input membership.';
  else
    for (const [input, alias] of Object.entries(recipe.inputs)) {
      const dataset = snapshot.catalog.datasets.find((d) => d.alias === alias || d.id === alias);
      const versions = snapshot.catalog.versions.filter(
        (v) =>
          v.dataset === alias &&
          (bindingMode === 'release'
            ? release?.members.includes(v.id)
            : v.id === versionsByInput[input]),
      );
      const representations = snapshot.catalog.representations.filter(
        (r) => r.version === versions[0]?.id && r.availability === 'available',
      );
      if (!dataset || versions.length !== 1 || !representations.length) {
        bindingProblem = `Input ${input} needs one exact version and an available representation in this release.`;
        break;
      }
      representationChoices.push({ input, choices: representations });
      const representation =
        representations.length === 1
          ? representations[0]
          : representations.find((r) => r.id === representationsByInput[input]);
      if (!representation) {
        bindingProblem = `Choose an exact representation for ${input}.`;
        continue;
      }
      bindings[input] = {
        datasetId: dataset.id,
        versionId: versions[0].id,
        representationId: representation.id,
        ...(bindingMode === 'release' ? { releaseId } : {}),
      };
    }
  async function run(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setError('');
    setResult(undefined);
    if (bindingProblem) {
      setError(bindingProblem);
      return;
    }
    const values: Record<string, ExactValue> = {};
    try {
      for (const name of order) {
        if (parameters[name] === undefined && !required.includes(name)) continue;
        values[name] = jsonInput(
          parameters[name] ?? '',
          String(objectOf(schema[name]).type ?? 'string'),
        );
      }
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setLoading(true);
    const body: QueryRequest = {
      catalogId: snapshot.id,
      catalogSha256: snapshot.identity.catalogSha256,
      recipeId: recipe.id,
      bindings,
      parameters: values,
      ...(bindingMode === 'release' ? { releaseId } : {}),
      limit: 25,
    };
    queryRef.current = body;
    try {
      const value = await request<QueryResult>('/api/query', abort.signal, body);
      if (!abort.signal.aborted) setResult(value);
    } catch (e) {
      if (!abort.signal.aborted) setError((e as Error).message);
    } finally {
      if (!abort.signal.aborted) setLoading(false);
    }
  }
  async function showSql() {
    if (sql !== undefined) return;
    sqlController.current?.abort();
    const abort = new AbortController();
    sqlController.current = abort;
    setSqlLoading(true);
    setError('');
    try {
      const response = await fetch(
        `/api/companion?${new URLSearchParams({ catalogId: snapshot.id, catalogSha256: snapshot.identity.catalogSha256, path: recipe.sql })}`,
        { signal: abort.signal, cache: 'no-store' },
      );
      if (!response.ok) throw new Error('The admitted SQL companion could not be read.');
      const bytes = await readText(response, 1024 * 1024);
      if (!abort.signal.aborted) setSql(bytes);
    } catch (e) {
      if (!abort.signal.aborted) setError((e as Error).message);
    } finally {
      if (!abort.signal.aborted) setSqlLoading(false);
    }
  }
  return (
    <article className="recipe">
      <h3>{recipe.title || shortId(recipe.id)}</h3>
      {recipe.notes?.map((n, i) => (
        <p key={i}>{n}</p>
      ))}
      <Facts
        items={[
          ['Dialect', recipe.dialect],
          ['Result meaning', recipe.resultGrain || recipe.resultDataset || 'Not declared'],
          [
            'Actual inputs',
            Object.entries(recipe.inputs).map(([name, alias]) => (
              <span className="subline" key={name}>
                <code>{name}</code> → {alias}
              </span>
            )),
          ],
          [
            'Explanatory links',
            recipe.contextualRelationships?.length
              ? recipe.contextualRelationships.map(shortId).join(', ')
              : 'None declared',
          ],
        ]}
      />
      <p className="muted">Explanatory links do not add datasets to this query’s inputs.</p>
      <details
        className="sql-preview"
        onToggle={(e) => {
          if (e.currentTarget.open) void showSql();
        }}
      >
        <summary>Inspect the exact SQL companion</summary>
        {sqlLoading ? (
          <p role="status">Reading verified SQL…</p>
        ) : (
          <pre>{sql ?? 'Open again to retry the companion read.'}</pre>
        )}
      </details>
      {querySupported ? (
        <form onSubmit={run} className="recipe-form">
          {!requiresRelease && (
            <label className="stack-label">
              Input binding
              <select
                value={bindingMode}
                onChange={(e) => {
                  controller.current?.abort();
                  setLoading(false);
                  setResult(undefined);
                  setBindingMode(e.target.value as 'release' | 'versions');
                }}
              >
                <option value="release">One exact release</option>
                <option value="versions">Explicit exact versions</option>
              </select>
            </label>
          )}
          {bindingMode === 'release' ? (
            <label className="stack-label">
              Exact release
              <select
                value={releaseId}
                onChange={(e) => {
                  controller.current?.abort();
                  setLoading(false);
                  setRelease(e.target.value);
                  setRepresentationsByInput({});
                  setResult(undefined);
                }}
              >
                <option value="">Choose a release</option>
                {releases.map((r) => (
                  <option value={r.id} key={r.id}>
                    {shortId(r.id)} · {r.membership}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            Object.entries(recipe.inputs).map(([input, alias]) => (
              <label className="stack-label" key={input}>
                Version for {input}
                <select
                  value={versionsByInput[input] ?? ''}
                  onChange={(e) => {
                    controller.current?.abort();
                    setLoading(false);
                    setResult(undefined);
                    setVersionsByInput((previous) => ({ ...previous, [input]: e.target.value }));
                    setRepresentationsByInput((previous) => ({ ...previous, [input]: '' }));
                  }}
                >
                  <option value="">Choose an exact version</option>
                  {snapshot.catalog.versions
                    .filter((v) => v.dataset === alias)
                    .map((v) => (
                      <option value={v.id} key={v.id}>
                        {shortId(v.id)} · {v.retention}
                      </option>
                    ))}
                </select>
              </label>
            ))
          )}
          {representationChoices
            .filter((item) => item.choices.length > 1)
            .map(({ input, choices }) => (
              <label className="stack-label" key={input}>
                Representation for {input}
                <select
                  value={representationsByInput[input] ?? ''}
                  onChange={(e) => {
                    controller.current?.abort();
                    setLoading(false);
                    setResult(undefined);
                    setRepresentationsByInput((previous) => ({
                      ...previous,
                      [input]: e.target.value,
                    }));
                  }}
                >
                  <option value="">Choose an exact representation</option>
                  {choices.map((choice) => (
                    <option key={choice.id} value={choice.id}>
                      {shortId(choice.id)} · {choice.mediaType || choice.kind}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          {order.map((name) => {
            const prop = objectOf(schema[name]);
            return (
              <label className="stack-label" key={name}>
                {String(prop.title || name)}
                {required.includes(name) ? ' (required)' : ''}
                <input
                  required={required.includes(name)}
                  value={parameters[name] ?? ''}
                  onChange={(e) => {
                    controller.current?.abort();
                    setLoading(false);
                    setParameters((p) => ({ ...p, [name]: e.target.value }));
                    setResult(undefined);
                  }}
                  placeholder={String(prop.description || prop.type || 'Value')}
                />
                <small>{String(prop.description || `Type: ${prop.type || 'string'}`)}</small>
              </label>
            );
          })}
          {bindingProblem && <p className="muted">{bindingProblem}</p>}
          <button className="button primary" disabled={loading || !!bindingProblem} type="submit">
            {loading ? 'Running bounded query…' : 'Run query'}
            <span aria-hidden="true"> →</span>
          </button>
          <span className="muted">
            Up to 25 result rows · {snapshot.mode === 'fixture' ? 'fixture reader' : 'owner reader'}
          </span>
          {loading && (
            <button
              type="button"
              onClick={() => {
                controller.current?.abort();
                setLoading(false);
                setError(
                  'Stopped waiting for this query. Owner work may still finish; its outcome is unknown here. Parameters remain available.',
                );
              }}
            >
              Stop waiting
            </button>
          )}
        </form>
      ) : (
        <Notice
          title={
            snapshot.capabilities.query
              ? 'Recipe outside the connected query scope'
              : 'Query execution is not connected'
          }
        >
          {snapshot.capabilities.query
            ? snapshot.capabilities.description ||
              'The registered owner does not support this recipe.'
            : 'This recipe is documentation until an owner supplies a checked, exact-binding query adapter.'}
        </Notice>
      )}
      {error && (
        <Notice title="Query needs attention" kind="error">
          {error}
        </Notice>
      )}
      <div role="status" aria-live="polite">
        {result?.status === 'ok' ? `${result.returned} query results` : ''}
      </div>
      {result && result.status !== 'ok' && (
        <Notice title={`Query ${result.status}`}>{result.reason}</Notice>
      )}
      {result?.attempt && (
        <EvidenceRecord
          snapshot={snapshot}
          record={result.attempt}
          label="Inspect viewer query request"
        />
      )}
      {result?.status === 'ok' && (
        <>
          <div className="result-bar">
            <Badge status="unknown">
              {result.execution?.kind === 'fixture' ? 'Demonstration execution' : 'Owner execution'}
            </Badge>
            <button
              onClick={() =>
                downloadJson('ddk-query-result.json', {
                  format: 'ddk-viewer-query/1',
                  scope: 'Bounded query result',
                  catalog: snapshot.identity,
                  request: queryRef.current,
                  result,
                })
              }
            >
              Export query & result ↓
            </button>
          </div>
          {result.rows.length ? (
            <ResultTable rows={result.rows} columns={result.columns} />
          ) : (
            <Notice title="No matching results">
              The supported query completed with no matches.
            </Notice>
          )}
          <Raw value={result.execution} label="Reader-issued execution record" />
          {result.execution?.kind === 'owner' && (
            <EvidenceRecord
              snapshot={snapshot}
              record={result.execution.record}
              label="Inspect native query receipt"
            />
          )}
        </>
      )}
    </article>
  );
}
export function Connections({
  snapshot,
  dataset,
  version,
  onNavigate,
  releaseId,
}: {
  snapshot: CatalogSnapshot;
  dataset: CatalogDataset;
  version?: CatalogVersion;
  onNavigate: (id: string, versionId?: string, releaseId?: string) => void;
  releaseId?: string;
}) {
  const relationships = snapshot.catalog.relationships.filter(
    (r) =>
      r.source.dataset === dataset.alias ||
      r.source.dataset === dataset.id ||
      r.target.dataset === dataset.alias ||
      r.target.dataset === dataset.id,
  );
  const recipes = snapshot.catalog.recipes.filter(
    (r) =>
      Object.values(r.inputs).includes(dataset.alias) ||
      Object.values(r.inputs).includes(dataset.id),
  );
  return (
    <>
      <Section
        title="Connections"
        aside={<span className="muted">{relationships.length} declared</span>}
      >
        <p>
          Relationships describe meaning and matching rules. Their presence does not prove that
          records match.
        </p>
        {relationships.length ? (
          relationships.map((r) => {
            const outgoing = r.source.dataset === dataset.alias || r.source.dataset === dataset.id;
            const otherAlias = outgoing ? r.target.dataset : r.source.dataset;
            const target = snapshot.catalog.datasets.find(
              (d) => d.alias === otherAlias || d.id === otherAlias,
            );
            const release = snapshot.catalog.releases.find((item) => item.id === releaseId);
            const targetVersions = snapshot.catalog.versions.filter(
              (v) =>
                (v.dataset === target?.alias || v.dataset === target?.id) &&
                release?.members.includes(v.id),
            );
            const boundTarget =
              r.scope === 'same_release' &&
              release?.membership === 'complete' &&
              targetVersions.length === 1
                ? targetVersions[0]
                : undefined;
            return (
              <article className="relationship" key={r.id}>
                <div className="relationship-route">
                  <span>{outgoing ? words(r.source.dataset) : words(r.target.dataset || '')}</span>
                  <span aria-hidden="true">{outgoing ? '→' : '←'}</span>
                  {target ? (
                    <button
                      onClick={() =>
                        onNavigate(target.id, boundTarget?.id, boundTarget ? releaseId : undefined)
                      }
                    >
                      {titleOf(target)} · {boundTarget ? 'same release' : 'definition'} ↗
                    </button>
                  ) : (
                    <code>{r.target.external || r.target.dataset}</code>
                  )}
                </div>
                <p>{r.meaning}</p>
                {!boundTarget && target && (
                  <p className="muted">
                    Opens the dataset definition. No exact record relationship is resolved.
                  </p>
                )}
                <Facts
                  items={[
                    [
                      'Source keys',
                      r.source.paths.map((p, i) => (
                        <code className="subline" key={i}>
                          {pathLabel(p)}
                        </code>
                      )),
                    ],
                    [
                      'Target keys',
                      r.target.paths?.map((p, i) => (
                        <code className="subline" key={i}>
                          {pathLabel(p)}
                        </code>
                      )) || 'External target',
                    ],
                    ['Match & cardinality', `${r.match} · ${r.cardinality}`],
                    ['Scope & nulls', `${r.scope} · nulls: ${r.nulls}`],
                  ]}
                />
                {r.scopeDescription && <p>{r.scopeDescription}</p>}
                <span className="muted">
                  Observed matches: unknown
                  {r.target.external ? ' · external existence not assessed' : ''}
                </span>
                <Raw value={r} label="Full scoped relationship declaration" />
              </article>
            );
          })
        ) : (
          <Notice title="No relationships are disclosed">
            A matching field name alone does not establish a connection.
          </Notice>
        )}
      </Section>
      <Section
        title="Queries"
        aside={<span className="muted">{recipes.length} available recipes</span>}
      >
        {recipes.length ? (
          recipes.map((r) => (
            <Recipe
              key={`${r.id}:${version?.id}`}
              recipe={r}
              snapshot={snapshot}
              version={version}
            />
          ))
        ) : (
          <Notice title="No query recipes are disclosed">
            The owner can provide parameterized SQL with exact input bindings and companion bytes.
          </Notice>
        )}
      </Section>
    </>
  );
}
