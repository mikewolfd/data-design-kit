import { useEffect, useId, useRef, useState } from 'react';
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
  safeLink,
  titleOf,
  words,
} from '../lib/display';
import { Badge, Facts, Notice, Raw, Section, BlankValuesHelp } from './Primitives';
import { enumLabel, formatLabel, isRecordResource } from '../lib/content';
import { ResultTable } from './DataPanel';
import { EvidenceRecord } from './EvidenceRecord';
import { exactEqual } from '../domain/exact';
import { Cautions } from '../features/dataset-context';
import { publisherMetadata } from '../features/publisher-metadata';
import {
  ResultContext,
  queryExport,
  queryResultMatches,
  resultCaption,
} from '../features/resource-details';

function RelationshipAssessment({
  snapshot,
  relationshipId,
  external,
}: {
  snapshot: CatalogSnapshot;
  relationshipId: string;
  external: boolean;
}) {
  const assembly = objectOf(snapshot.catalog.extensions?.['urn:ddk:catalog:assembly']);
  // Public disclosure and an explicit assessment scope take precedence over individual rows.
  const disclose =
    snapshot.audience === 'local' && !Object.hasOwn(assembly, 'relationshipAssessmentScope');
  const profile = objectOf(assembly.relationshipProfile);
  const identity = objectOf(profile.identity);
  const matches =
    disclose && Array.isArray(assembly.relationshipAssessments)
      ? assembly.relationshipAssessments
          .map(objectOf)
          .filter((row) => row.relationship === relationshipId)
      : [];
  const assessment = matches[0];
  const status = assessment?.status;
  const reason = assessment?.reason;
  const usable =
    matches.length === 1 &&
    profile.scope === 'declaration-support-only' &&
    typeof identity.id === 'string' &&
    !!identity.id &&
    typeof identity.version === 'string' &&
    !!identity.version &&
    assessment.scope === 'declaration-support-only' &&
    exactEqual(assessment.profile, profile.identity) &&
    (status === 'supported' || status === 'failed' || status === 'unknown') &&
    typeof reason === 'string' &&
    !!reason.trim() &&
    (assessment.externalExistence === undefined || assessment.externalExistence === 'not_assessed');
  const label = usable && typeof status === 'string' ? enumLabel(status) : 'Unknown';
  const explanation =
    usable && typeof reason === 'string'
      ? reason
      : matches.length > 1
        ? 'Multiple assessments identify this relationship; no single assessment is established.'
        : 'No usable matching-rule assessment is supplied for this relationship.';
  return (
    <>
      {disclose && (
        <div className="relationship-assessment muted">
          <p>Matching rule assessment: {label}</p>
          <p>{explanation}</p>
        </div>
      )}
      {external && (
        <p className="muted">
          {usable && assessment.externalExistence === 'not_assessed'
            ? 'Whether this external target exists has not been assessed.'
            : 'Whether this external target exists is unknown here.'}
        </p>
      )}
    </>
  );
}

function Recipe({
  recipe,
  snapshot,
  version,
  dataset,
}: {
  recipe: CatalogRecipe;
  snapshot: CatalogSnapshot;
  version?: CatalogVersion;
  dataset: CatalogDataset;
}) {
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [releaseId, setRelease] = useState('');
  const [bindingMode, setBindingMode] = useState<'release' | 'versions'>('release');
  const [versionsByInput, setVersionsByInput] = useState<Record<string, string>>({});
  const [representationsByInput, setRepresentationsByInput] = useState<Record<string, string>>({});
  const [result, setResult] = useState<QueryResult>();
  const [error, setError] = useState('');
  const [errorCode, setErrorCode] = useState('');
  const [errorDiagnostic, setErrorDiagnostic] = useState('');
  const parameterId = useId();
  const [loading, setLoading] = useState(false);
  const [sql, setSql] = useState<string>();
  const [sqlLoading, setSqlLoading] = useState(false);
  const [sqlError, setSqlError] = useState('');
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
    bindingProblem = 'This portal cannot resolve a required relationship for this query.';
  else if (bindingMode === 'release' && !release)
    bindingProblem = 'Choose a named release for the datasets used.';
  else if (bindingMode === 'release' && release?.membership !== 'complete')
    bindingProblem = 'This release does not list all required data versions.';
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
        (r) =>
          r.version === versions[0]?.id &&
          r.availability === 'available' &&
          isRecordResource(snapshot, r),
      );
      if (!dataset || versions.length !== 1 || !representations.length) {
        bindingProblem = `Input ${input} needs one data version and an available file, table or service in the selected group.`;
        break;
      }
      representationChoices.push({ input, choices: representations });
      const representation =
        representations.length === 1
          ? representations[0]
          : representations.find((r) => r.id === representationsByInput[input]);
      if (!representation) {
        bindingProblem = `Choose a file, table or service for ${input}.`;
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
    setErrorCode('');
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
      if (!abort.signal.aborted) {
        if (!queryResultMatches(snapshot, body, value))
          throw new Error(
            'The response does not match this query and its selected inputs. Run the query again to retry.',
          );
        setResult(value);
      }
    } catch (e) {
      if (!abort.signal.aborted) {
        setError((e as Error).message);
        setErrorCode((e as Error & { code?: string }).code || '');
        setErrorDiagnostic(
          (e as Error & { technicalMessage?: string }).technicalMessage || (e as Error).message,
        );
      }
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
    setSqlError('');
    try {
      const response = await fetch(
        `/api/companion?${new URLSearchParams({ catalogId: snapshot.id, catalogSha256: snapshot.identity.catalogSha256, path: recipe.sql })}`,
        { signal: abort.signal, cache: 'no-store' },
      );
      if (!response.ok)
        throw new Error('The SQL file could not be loaded. Close and reopen View SQL to retry.');
      const bytes = await readText(response, 1024 * 1024);
      if (!abort.signal.aborted) setSql(bytes);
    } catch (e) {
      if (!abort.signal.aborted) setSqlError((e as Error).message);
    } finally {
      if (!abort.signal.aborted) setSqlLoading(false);
    }
  }
  return (
    <article className="recipe" id={`recipe-${recipe.id}`}>
      <h3>{recipe.title || 'Query title not supplied'}</h3>
      {recipe.notes?.map((n, i) => (
        <p key={i}>{n}</p>
      ))}
      <Facts
        items={[
          [
            'Each result represents',
            recipe.resultGrain ||
              snapshot.catalog.datasets.find(
                (item) => item.alias === recipe.resultDataset || item.id === recipe.resultDataset,
              )?.rowMeaning ||
              'The publisher has not supplied what each result represents.',
          ],
          [
            'Datasets used',
            Object.entries(recipe.inputs).map(([name, alias]) => (
              <span className="subline" key={name}>
                <code>{name}</code> →{' '}
                {titleOf(
                  snapshot.catalog.datasets.find((d) => d.alias === alias || d.id === alias) ??
                    ({ id: alias, alias } as CatalogDataset),
                )}{' '}
                <code>{alias}</code>
              </span>
            )),
          ],
          [
            'Related matching rules',
            recipe.contextualRelationships?.length
              ? recipe.contextualRelationships.map(shortId).join(', ')
              : 'None declared',
          ],
        ]}
      />
      <Cautions snapshot={snapshot} recipe={recipe} />
      <p className="muted">
        Related matching rules provide context; they do not add datasets to this query.
      </p>
      {querySupported ? (
        <form onSubmit={run} className="recipe-form">
          <p>
            A release is a named group of data versions. Choose the release or individual versions
            to use; the portal keeps these choices explicit.
          </p>
          {requiresRelease && <p>This query requires all inputs to come from the same release.</p>}
          {!requiresRelease && (
            <label className="stack-label">
              Data versions to use
              <select
                value={bindingMode}
                onChange={(e) => {
                  controller.current?.abort();
                  setLoading(false);
                  setResult(undefined);
                  setBindingMode(e.target.value as 'release' | 'versions');
                }}
              >
                <option value="release">One named release</option>
                <option value="versions">Choose versions individually</option>
              </select>
            </label>
          )}
          {bindingMode === 'release' ? (
            <label className="stack-label">
              Named release
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
                    {shortId(r.id)} · {enumLabel(r.membership)}
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
                  <option value="">Choose a data version</option>
                  {snapshot.catalog.versions
                    .filter((v) => v.dataset === alias)
                    .map((v) => (
                      <option value={v.id} key={v.id}>
                        {shortId(v.id)} · {enumLabel(v.retention)}
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
                File, table or service for {input}
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
                  <option value="">Choose a file, table or service</option>
                  {choices.map((choice) => (
                    <option key={choice.id} value={choice.id}>
                      {shortId(choice.id)} · {formatLabel(choice.mediaType, choice.kind)}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          {order.map((name) => {
            const prop = objectOf(schema[name]);
            return (
              <div className="stack-label" key={name}>
                <label htmlFor={`${parameterId}-${name}`}>
                  {String(prop.title || words(name))}
                  {required.includes(name) ? ' (required)' : ''}
                </label>
                <input
                  id={`${parameterId}-${name}`}
                  aria-describedby={`${parameterId}-${name}-help`}
                  required={required.includes(name)}
                  value={parameters[name] ?? ''}
                  onChange={(e) => {
                    controller.current?.abort();
                    setLoading(false);
                    setParameters((p) => ({ ...p, [name]: e.target.value }));
                    setResult(undefined);
                  }}
                />
                <small id={`${parameterId}-${name}-help`}>
                  {String(prop.description || `Required format: ${prop.type || 'text'}`)}
                  {Array.isArray(prop.examples) && prop.examples.length
                    ? ` Example: ${String(prop.examples[0])}.`
                    : ''}
                </small>
                <details>
                  <summary>Technical parameter details</summary>
                  <code>{name}</code>
                  <span> · Type: {String(prop.type || 'string')}</span>
                </details>
              </div>
            );
          })}
          {bindingProblem && <p className="muted">{bindingProblem}</p>}
          <button className="button primary" disabled={loading || !!bindingProblem} type="submit">
            {loading ? 'Running query…' : 'Run query'}
            <span aria-hidden="true"> →</span>
          </button>
          <span className="muted">
            Up to 25 result rows ·{' '}
            {snapshot.mode === 'fixture' ? 'synthetic example data' : 'connected data source'}
          </span>
          {loading && (
            <button
              type="button"
              onClick={() => {
                controller.current?.abort();
                setLoading(false);
                setError(
                  'Stopped waiting. The source may still finish the request; this portal does not know its outcome. Parameters remain available.',
                );
              }}
            >
              Stop waiting
            </button>
          )}
        </form>
      ) : (
        <Notice title="Example query — cannot run here">
          You can inspect the SQL and its required data. This query is not connected to an execution
          service here.
          <Raw
            value={{ recipeId: recipe.id, capabilities: snapshot.capabilities }}
            label="Query connection details"
          />
        </Notice>
      )}
      <details
        className="sql-preview"
        onToggle={(e) => {
          if (e.currentTarget.open) void showSql();
        }}
      >
        <summary>View SQL</summary>
        <p>Structured Query Language (SQL) describes how this query uses the data.</p>
        <p>
          SQL engine: <code>{recipe.dialect}</code>
        </p>
        {sqlLoading ? (
          <p role="status">Loading SQL…</p>
        ) : (
          <pre>{sql ?? 'Close and reopen to retry loading the SQL file.'}</pre>
        )}
        {sqlError && (
          <Notice
            title="SQL could not be loaded"
            kind="error"
            action={<button onClick={() => void showSql()}>Retry loading SQL</button>}
          >
            {sqlError}
          </Notice>
        )}
      </details>
      <Raw value={recipe} label="Technical query details" />
      {error && (
        <Notice
          title={
            errorCode === 'export_too_large'
              ? 'Query result could not be downloaded'
              : 'Query needs attention'
          }
          kind="error"
        >
          {error}
          {errorCode && (
            <Raw
              value={{ code: errorCode, message: errorDiagnostic || error }}
              label="Error details"
            />
          )}
        </Notice>
      )}
      <div role="status" aria-live="polite">
        {result?.status === 'ok'
          ? `${result.returned} ${result.returned === 1 ? 'query result' : 'query results'}`
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
          {result.status === 'unknown'
            ? 'This request did not establish an outcome. The source may still finish; this portal does not know its result.'
            : result.reason}
          <Raw
            value={{ status: result.status, reason: result.reason }}
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
      {result?.status === 'ok' && (
        <>
          {queryRef.current && (
            <ResultContext
              kind="query"
              snapshot={snapshot}
              dataset={dataset}
              recipe={recipe}
              request={queryRef.current}
              result={result}
            />
          )}
          <div className="result-bar">
            <Badge status="unknown">
              {result.execution?.kind === 'fixture'
                ? 'Demonstration execution'
                : 'Connected source execution'}
            </Badge>
            <button
              onClick={() => {
                try {
                  if (!queryRef.current) throw new Error('Run the query again before downloading.');
                  downloadJson(
                    'ddk-query-result.json',
                    queryExport(snapshot, queryRef.current, result),
                  );
                } catch (e) {
                  setError((e as Error).message);
                  setErrorCode('export_too_large');
                  setErrorDiagnostic((e as Error).message);
                }
              }}
            >
              Download query and results (JSON) ↓
            </button>
          </div>
          <p className="muted">
            Download includes the query request, its data version choices, and up to 25 returned
            rows with all fields and exact numbers. JSON is a structured data-file format.
          </p>
          <BlankValuesHelp />
          {result.rows.length ? (
            <ResultTable
              rows={result.rows}
              columns={result.columns}
              caption={
                queryRef.current
                  ? resultCaption({
                      kind: 'query',
                      snapshot,
                      dataset,
                      recipe,
                      request: queryRef.current,
                      result,
                    })
                  : undefined
              }
            />
          ) : (
            <Notice title="No matching results">
              This query completed with no matches for the selected data versions and parameters.
            </Notice>
          )}
          <Raw value={result.execution} label="Technical execution record" />
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
  focusedRecipeId,
}: {
  snapshot: CatalogSnapshot;
  dataset: CatalogDataset;
  version?: CatalogVersion;
  onNavigate: (id: string, versionId?: string, releaseId?: string) => void;
  releaseId?: string;
  focusedRecipeId?: string;
}) {
  useEffect(() => {
    if (focusedRecipeId)
      document.getElementById(`recipe-${focusedRecipeId}`)?.scrollIntoView({ block: 'start' });
  }, [focusedRecipeId]);
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
      Object.values(r.inputs).includes(dataset.id) ||
      r.resultDataset === dataset.alias ||
      r.resultDataset === dataset.id,
  );
  const assembly = objectOf(snapshot.catalog.extensions?.['urn:ddk:catalog:assembly']);
  const assessmentScope = objectOf(assembly.relationshipAssessmentScope);
  return (
    <>
      <Section
        title="Related data"
        aside={<span className="muted">{relationships.length} declared</span>}
      >
        <p>
          These links describe how fields can connect datasets. Their declarations and matching-rule
          assessments do not establish which records match.
        </p>
        {Object.hasOwn(assembly, 'relationshipAssessmentScope') && (
          <Notice title="Matching rule assessment: Unknown">
            {assessmentScope.status === 'unknown' &&
            typeof assessmentScope.reason === 'string' &&
            assessmentScope.reason.trim()
              ? assessmentScope.reason
              : 'The catalog does not supply a usable assessment scope.'}
          </Notice>
        )}
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
              <article className="relationship" key={r.id} data-relationship-id={r.id}>
                <div className="relationship-route">
                  <span>{titleOf(dataset)}</span>
                  <span aria-hidden="true">{outgoing ? '→' : '←'}</span>
                  {target ? (
                    <button
                      onClick={() =>
                        onNavigate(target.id, boundTarget?.id, boundTarget ? releaseId : undefined)
                      }
                    >
                      {titleOf(target)} ·{' '}
                      {boundTarget ? 'version in the same release' : 'dataset description'} ↗
                    </button>
                  ) : r.target.external && safeLink(r.target.external) ? (
                    <a href={safeLink(r.target.external)} target="_blank" rel="noreferrer">
                      Open external source · {new URL(r.target.external).hostname}
                    </a>
                  ) : (
                    <code>{r.target.external || r.target.dataset}</code>
                  )}
                </div>
                <p>{r.meaning}</p>
                <p className="muted">
                  Declared requirement:{' '}
                  {r.resolution === 'required'
                    ? 'Matching records required'
                    : r.resolution === 'unresolved_allowed'
                      ? 'Unmatched records allowed'
                      : r.resolution === 'external'
                        ? 'External reference'
                        : 'Unknown'}
                </p>
                {!boundTarget && target && (
                  <p className="muted">
                    Opens the dataset description. This link does not open matching records.
                  </p>
                )}
                <details>
                  <summary>Matching rules</summary>
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
                      [
                        'Match & cardinality',
                        `${enumLabel(r.match)} · ${enumLabel(r.cardinality)}`,
                      ],
                      ['Scope & nulls', `${enumLabel(r.scope)} · nulls: ${enumLabel(r.nulls)}`],
                    ]}
                  />
                  {r.scopeDescription && <p>{r.scopeDescription}</p>}
                </details>
                <RelationshipAssessment
                  snapshot={snapshot}
                  relationshipId={r.id}
                  external={!!r.target.external}
                />
                <Raw value={r} label="Technical relationship details" />
              </article>
            );
          })
        ) : (
          <Notice title="No related datasets are listed">
            A matching field name alone does not establish a connection.
          </Notice>
        )}
      </Section>
      <Section
        title="Questions and queries"
        aside={
          <span className="muted">
            {recipes.length} documented {recipes.length === 1 ? 'query' : 'queries'} ·{' '}
            {
              recipes.filter(
                (r) =>
                  snapshot.capabilities.query &&
                  (!snapshot.capabilities.queryRecipeIds ||
                    snapshot.capabilities.queryRecipeIds.includes(r.id)),
              ).length
            }{' '}
            runnable here
          </span>
        }
      >
        {focusedRecipeId && !recipes.some((recipe) => recipe.id === focusedRecipeId) && (
          <Notice title="The linked query is not listed for this dataset">
            Choose one of the documented queries below or return to its guide.
          </Notice>
        )}
        {recipes.length ? (
          recipes.map((r) => (
            <Recipe
              key={`${r.id}:${version?.id}`}
              recipe={r}
              snapshot={snapshot}
              version={version}
              dataset={dataset}
            />
          ))
        ) : (
          <Notice title="No queries are listed">
            The publisher has not supplied a query for this dataset.
          </Notice>
        )}
      </Section>
      {!!publisherMetadata(snapshot).contextualRelations.length && (
        <Section title="Publisher’s upstream context">
          <p>
            These are publisher descriptions of upstream tables for this catalog. They do not
            establish local datasets, executable joins, or observed matches.
          </p>
          {publisherMetadata(snapshot).contextualRelations.map((relation) => (
            <details className="context-scope" key={relation.id}>
              <summary>
                {words(relation.table)} · {relation.family}
              </summary>
              <p>{relation.rowMeaning}</p>
              <p>{relation.limits}</p>
              <Raw value={relation} label="Exact upstream table declaration" />
            </details>
          ))}
        </Section>
      )}
    </>
  );
}
