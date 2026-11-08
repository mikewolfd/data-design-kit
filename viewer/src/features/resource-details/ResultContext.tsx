import type {
  CatalogDataset,
  CatalogRecipe,
  CatalogSnapshot,
  QueryRequest,
  QueryResult,
  ReadRequest,
  ReadResult,
} from '../../domain/types';
import { exactStringify } from '../../domain/exact';
import { versionChoices } from '../../lib/choice-labels';
import { formatLabel } from '../../lib/content';
import { pathLabel, shortId, titleOf, versionsOf } from '../../lib/display';
import { publisherMetadata } from '../publisher-metadata';
import { downloadReadme, localReadExample, queryResultMatches, readResultMatches } from './results';

type Scope = { snapshot: CatalogSnapshot; dataset: CatalogDataset };
export type ResultContextProps = Scope &
  (
    | { kind: 'page'; request: ReadRequest; result: ReadResult; visibleColumns?: string[] }
    | { kind: 'query'; recipe: CatalogRecipe; request: QueryRequest; result: QueryResult }
  );

function describeFilter(request: ReadRequest) {
  const filter = request.filter;
  if (!filter) return 'All records in the selected resource';
  const field =
    filter.path.length === 1 && 'field' in filter.path[0]
      ? filter.path[0].field
      : pathLabel(filter.path);
  return `${field} = ${exactStringify(filter.equals, 0)}`;
}

function pagination(props: ResultContextProps) {
  const { result } = props;
  const state =
    result.continuation ??
    (result.hasMore === true ? 'more' : result.hasMore === false ? 'complete' : 'unknown');
  if (state === 'unknown') return 'Whether more matching records are available is unknown.';
  if (state === 'more')
    return props.kind === 'page'
      ? 'More matching records are available beyond this page.'
      : 'More matching records exist beyond this query result.';
  return 'This request reached the end of its matching result.';
}

function context(props: ResultContextProps) {
  const { snapshot, dataset, request, result } = props;
  if (result.status !== 'ok') return undefined;
  const datasetTitle = titleOf(dataset);
  const resultLabel = props.kind === 'page' ? 'Record page' : 'Query result';
  const count = `${result.returned} ${result.returned === 1 ? 'record' : 'records'}`;
  const limit = request.limit ?? 25;
  const matching =
    result.total === undefined
      ? undefined
      : `${result.total} matching ${result.total === 1 ? 'record' : 'records'} for this request`;
  const order =
    result.rowOrder === 'source-row'
      ? 'Source row order'
      : result.rowOrder === 'query-result'
        ? 'Query result order'
        : 'Row order not supplied';
  const example =
    snapshot.mode === 'fixture'
      ? 'Synthetic example'
      : snapshot.exampleData === 'authored'
        ? 'Authored example'
        : undefined;
  if (props.kind === 'page') {
    if (
      !readResultMatches(snapshot, props.request, props.result) ||
      props.request.datasetId !== dataset.id
    )
      return undefined;
    const versionId = props.request.versionId;
    const representationId = props.request.representationId;
    const selected = versionChoices(snapshot, dataset, versionsOf(snapshot, dataset)).find(
      (row) => row.id === versionId,
    )?.label;
    const version = selected?.startsWith(`${datasetTitle} · `)
      ? selected.slice(datasetTitle.length + 3)
      : (selected ?? shortId(versionId));
    const resource = snapshot.catalog.representations.find(
      (row) => row.id === representationId && row.version === versionId,
    );
    const purpose =
      publisherMetadata(snapshot).representations.get(representationId)?.resource?.purpose;
    const resourceLabel = purpose ?? formatLabel(resource?.mediaType, resource?.kind);
    return {
      datasetTitle,
      resultLabel,
      count,
      limit,
      matching,
      order,
      example,
      caption: `${datasetTitle} · ${version} · ${resourceLabel} · ${count} on this page`,
      selection: describeFilter(props.request),
      facts: [
        ['Version', version],
        ['Resource', resourceLabel],
        ['Position', props.request.cursor ? 'Page reached through a cursor' : 'First page'],
      ],
    };
  }
  if (
    !queryResultMatches(snapshot, props.request, props.result) ||
    props.recipe.id !== props.request.recipeId
  )
    return undefined;
  const title = props.recipe.title || 'Saved query';
  const parameters = Object.entries(props.request.parameters).map(
    ([name, value]) => `${name} = ${exactStringify(value, 0)}`,
  );
  const inputs = Object.entries(props.result.bindings).map(
    ([name, binding]) => `${name} · ${binding.versionId} · ${binding.representationId}`,
  );
  return {
    datasetTitle,
    resultLabel,
    count,
    limit,
    matching,
    order,
    example,
    caption: `${title} · ${count} returned`,
    selection: parameters.length ? parameters.join(' · ') : 'No parameter values submitted',
    facts: [
      ['Query', title],
      ['Input versions and resources', inputs.join('\n') || 'None'],
      ...(props.request.releaseId ? [['Release', props.request.releaseId]] : []),
    ],
  };
}

export function resultCaption(props: ResultContextProps) {
  return context(props)?.caption;
}

export function resultReadme(props: ResultContextProps, origin?: string) {
  const details = context(props);
  if (!details) return undefined;
  const example =
    props.kind === 'page' && origin
      ? localReadExample(props.snapshot, props.request, origin)
      : undefined;
  return [
    `${details.resultLabel} README`,
    '',
    details.caption,
    details.example,
    `Selection: ${details.selection}`,
    `Row bound: ${details.limit} requested. ${details.matching ?? 'Matching total not supplied.'}`,
    pagination(props),
    details.order,
    'Scope: Rows returned for this request only. Source population coverage is a separate assessment.',
    'Format: JSON. The download includes all returned fields, including hidden fields. Maximum download size: 1 MiB.',
    'Exact values: Keep $number strings and $object entry lists. Arrays retain their order and repeated values.',
    `Returned fields: ${props.result.columns.map((column) => JSON.stringify(column)).join(', ') || 'None'}`,
    '',
    `Catalog copy: ${props.snapshot.identity.catalogSha256}`,
    `Dataset: ${props.dataset.id}`,
    'Exact request:',
    JSON.stringify(props.request, null, 2),
    ...(example
      ? ['', 'Repeat this bounded fixture read:', example.requirements, example.command]
      : []),
    '',
  ]
    .filter((line) => line !== undefined)
    .join('\n');
}

export function ResultContext(props: ResultContextProps) {
  const details = context(props);
  if (!details) return null;
  const origin = typeof window === 'undefined' ? undefined : window.location.origin;
  const example =
    props.kind === 'page' && origin
      ? localReadExample(props.snapshot, props.request, origin)
      : undefined;
  return (
    <section className="result-context" aria-label={`${details.resultLabel} scope`}>
      <p>
        <strong>
          {details.resultLabel} · {details.count}
        </strong>{' '}
        · {details.datasetTitle}
        {details.example && ` · ${details.example}`}
      </p>
      <dl className="resource-facts">
        {details.facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        <div>
          <dt>{props.kind === 'page' ? 'Filter' : 'Parameters'}</dt>
          <dd>{details.selection}</dd>
        </div>
        <div>
          <dt>Row limit</dt>
          <dd>
            {details.limit} per request{details.matching && ` · ${details.matching}`}
          </dd>
        </div>
      </dl>
      <p>
        {details.order}. {pagination(props)} This preview describes the request's returned records.
      </p>
      <p>
        Download format is JSON, up to 1 MiB. It includes the selected request and all returned
        fields, including fields hidden in the table. The download contains only this{' '}
        {props.kind === 'page' ? 'page' : 'query result'}.
      </p>
      <details>
        <summary>Exact request, fields and reuse</summary>
        <p>
          Catalog copy <code>{props.snapshot.identity.catalogSha256}</code>
        </p>
        <p>
          Dataset <code>{props.dataset.id}</code>
        </p>
        <pre>{JSON.stringify(props.request, null, 2)}</pre>
        <p>
          Returned fields: {props.result.columns.length ? props.result.columns.join(', ') : 'None'}
        </p>
        {props.kind === 'page' && props.visibleColumns && (
          <p>
            Visible fields: {props.visibleColumns.length ? props.visibleColumns.join(', ') : 'None'}
          </p>
        )}
        <p>Keep exact number strings and repeated nested entries when using the downloaded file.</p>
        <button
          type="button"
          onClick={() => downloadReadme('ddk-result-readme.txt', resultReadme(props, origin)!)}
        >
          Download result README (text)
        </button>
        {example && (
          <>
            <h4>Repeat this bounded local read</h4>
            <p>
              Programmatic destination <code>{example.endpoint}</code>
            </p>
            <p>{example.requirements}</p>
            <pre>{example.command}</pre>
          </>
        )}
      </details>
    </section>
  );
}
