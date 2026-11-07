import { isObject } from '../../domain/exact';
import type {
  CatalogSnapshot,
  ExactBinding,
  QueryRequest,
  QueryResult,
  ReadRequest,
  ReadResult,
} from '../../domain/types';

export const VIEWER_READ_ROWS = 10;
export const VIEWER_QUERY_ROWS = 25;
const API_DEFAULT_ROWS = 25;
const API_MAX_ROWS = 100;

function sameBinding(left: ExactBinding, right?: ExactBinding | null) {
  return (
    isObject(right) &&
    left.datasetId === right.datasetId &&
    left.versionId === right.versionId &&
    left.representationId === right.representationId &&
    left.releaseId === right.releaseId
  );
}

function sameCatalog(snapshot: CatalogSnapshot, request: ReadRequest | QueryRequest) {
  return (
    request.catalogId === snapshot.id && request.catalogSha256 === snapshot.identity.catalogSha256
  );
}

export function sameReadRequest(left: ReadRequest, right: ReadRequest) {
  return (
    left.catalogId === right.catalogId &&
    left.catalogSha256 === right.catalogSha256 &&
    sameBinding(left, right) &&
    left.cursor === right.cursor &&
    left.limit === right.limit &&
    JSON.stringify(left.filter) === JSON.stringify(right.filter)
  );
}

function resultRowsMatch(result: ReadResult | QueryResult, limit: number) {
  if (result.status !== 'ok') return result.status === 'refused' || result.status === 'unknown';
  return (
    Array.isArray(result.rows) &&
    result.returned === result.rows.length &&
    result.returned <= limit &&
    (result.total === undefined ||
      (Number.isSafeInteger(result.total) && result.total >= result.returned)) &&
    Array.isArray(result.columns) &&
    result.columns.every((column) => typeof column === 'string')
  );
}

export function readResultMatches(
  snapshot: CatalogSnapshot,
  request: ReadRequest,
  result: ReadResult,
) {
  return (
    isObject(result) &&
    sameCatalog(snapshot, request) &&
    sameBinding(request, result.binding) &&
    resultRowsMatch(result, request.limit ?? API_DEFAULT_ROWS)
  );
}

export function queryResultMatches(
  snapshot: CatalogSnapshot,
  request: QueryRequest,
  result: QueryResult,
) {
  return (
    isObject(result) &&
    sameCatalog(snapshot, request) &&
    isObject(result.bindings) &&
    resultRowsMatch(result, request.limit ?? API_DEFAULT_ROWS) &&
    (result.execution === undefined ||
      (isObject(result.execution) && result.execution.recipeId === request.recipeId)) &&
    Object.keys(request.bindings).length === Object.keys(result.bindings).length &&
    Object.entries(request.bindings).every(([key, input]) => {
      const returned = result.bindings[key];
      const requested =
        request.releaseId === undefined ? input : { ...input, releaseId: request.releaseId };
      return returned !== undefined && sameBinding(requested, returned);
    })
  );
}

const pageScope =
  'Only the displayed page; all returned fields retained with visible column order recorded. Not a full dataset export';
const numericEncoding = '{$number: exact JSON number lexeme}';

export function pageExport(
  snapshot: CatalogSnapshot,
  request: ReadRequest,
  result: ReadResult,
  visibleColumns: string[] = result.columns,
) {
  if (!readResultMatches(snapshot, request, result) || result.status !== 'ok')
    throw new Error('Open the selected record page again before downloading.');
  return {
    format: 'ddk-viewer-page/1',
    scope: pageScope,
    numericEncoding,
    catalog: snapshot.identity,
    request,
    display: { columns: visibleColumns, order: 'original' },
    result,
  };
}

export function queryExport(snapshot: CatalogSnapshot, request: QueryRequest, result: QueryResult) {
  if (!queryResultMatches(snapshot, request, result) || result.status !== 'ok')
    throw new Error('Run this query again before downloading its result.');
  return {
    format: 'ddk-viewer-query/1',
    scope: `Up to ${request.limit ?? API_DEFAULT_ROWS} returned query rows; not the full dataset`,
    numericEncoding,
    catalog: snapshot.identity,
    request,
    result,
  };
}

function shellQuote(value: string) {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

export function localReadExample(snapshot: CatalogSnapshot, request: ReadRequest, origin: string) {
  if (
    snapshot.mode !== 'fixture' ||
    !snapshot.capabilities.read ||
    !sameCatalog(snapshot, request) ||
    request.cursor
  )
    return undefined;
  let url: URL;
  try {
    url = new URL(origin);
  } catch {
    return undefined;
  }
  if (
    url.origin !== origin ||
    !['http:', 'https:'].includes(url.protocol) ||
    !['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname)
  )
    return undefined;
  return {
    endpoint: `${url.origin}/api/read`,
    body: request,
    command: [
      `curl --fail-with-body --silent --show-error ${shellQuote(`${url.origin}/api/read`)}`,
      "  --header 'Content-Type: application/json'",
      `  --data-binary ${shellQuote(JSON.stringify(request))}`,
    ].join(' \\\n'),
    requirements: `Use this running local viewer with the same catalog copy. The fixture route uses no API key. The endpoint defaults to ${API_DEFAULT_ROWS} rows and accepts 1–${API_MAX_ROWS} rows per request. This example requests ${request.limit ?? API_DEFAULT_ROWS}. Requests are limited to 64 KiB and results to 256 KiB. Inspect the returned status and continuation.`,
  };
}

export function downloadReadme(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
