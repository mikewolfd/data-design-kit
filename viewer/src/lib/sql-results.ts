import type { CatalogSnapshot, QueryResult, SqlRequest } from '../domain/types';
import { queryResultMatches } from '../features/resource-details/results';

export const adHocSqlId = 'urn:ddk:ad-hoc-sql';

/** The transport's recipe-shaped execution record still binds the original SQL and all inputs. */
export function sqlResultMatches(
  snapshot: CatalogSnapshot,
  request: SqlRequest,
  result: QueryResult,
  sqlSha256: string,
) {
  return (
    queryResultMatches(snapshot, { ...request, recipeId: adHocSqlId, parameters: {} }, result) &&
    result.transport === 'ddk-exact-json-v1' &&
    (result.status !== 'ok' || result.execution?.sqlSha256 === sqlSha256)
  );
}

export function sqlResultExport(
  snapshot: CatalogSnapshot,
  request: SqlRequest,
  result: QueryResult,
  sqlSha256: string,
) {
  if (!sqlResultMatches(snapshot, request, result, sqlSha256) || result.status !== 'ok')
    throw new Error('Run this query again before downloading its result.');
  return {
    format: 'ddk-viewer-sql/1',
    scope: `Up to ${request.limit ?? 25} returned query rows; not the full dataset`,
    numericEncoding: '{$number: exact JSON number lexeme}',
    catalog: snapshot.identity,
    request,
    result,
  };
}

export function quotedSqlTable(alias: string): string {
  return `"${alias.replaceAll('"', '""')}"`;
}
