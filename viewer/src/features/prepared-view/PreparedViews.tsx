import { useId } from 'react';
import { exactStringify } from '../../domain/exact';
import type {
  CatalogDataset,
  CatalogSnapshot,
  FieldPath,
  ReadRequest,
  ReadResult,
} from '../../domain/types';
import { preparedCounts } from './counts';

function pathLabel(path: FieldPath) {
  return path
    .map((step, index) => ('each' in step ? '[]' : `${index ? '.' : ''}${step.field}`))
    .join('');
}

function continuationText(continuation?: ReadResult['continuation']) {
  if (continuation === 'more') return 'More records are available for this request.';
  if (continuation === 'complete') return 'The reader reports this is the end of this request.';
  return 'The reader did not establish whether more records are available.';
}

export function PreparedViews({
  id,
  snapshot,
  dataset,
  request,
  result,
  onDownloadUnderlying,
}: {
  id?: string;
  snapshot: CatalogSnapshot;
  dataset: CatalogDataset;
  request: ReadRequest;
  result: ReadResult;
  onDownloadUnderlying?: () => void;
}) {
  const prefix = useId();
  const counts = preparedCounts(snapshot, dataset, request, result);
  if (!counts.length) return null;
  return (
    <div id={id} className="prepared-views" role="region" aria-label="Page summary" tabIndex={-1}>
      {counts.map(
        (
          { view, categories, fieldName, fieldLabel, excludedArrays, excludedObjects, returned },
          index,
        ) => {
          const heading = `${prefix}-${index}`;
          const excluded = excludedArrays + excludedObjects;
          return (
            <figure className="prepared-counts" key={view.id} aria-labelledby={heading}>
              <figcaption>
                <h3 id={heading}>{view.question}</h3>
                <p className="muted">Publisher-authored question · Viewer-generated counts</p>
                <p>
                  The calculation examines {returned} {returned === 1 ? 'record' : 'records'}{' '}
                  returned on this page. It reads <strong>{fieldLabel}</strong> once per record.
                  Absent fields, null, and empty text are counted separately. Arrays and objects are
                  excluded.
                </p>
                {excluded > 0 && (
                  <p>
                    Excluded {excluded} records with composite values ({excludedArrays} arrays and{' '}
                    {excludedObjects} objects).
                  </p>
                )}
                <p>
                  Time range for these returned records: not supplied by the read response. The
                  requested page gives no evidence that its values represent the full source
                  population.
                </p>
              </figcaption>
              {categories.length ? (
                <table className="prepared-counts-table">
                  <caption>Counts by value for {fieldLabel}</caption>
                  <thead>
                    <tr>
                      <th scope="col">Value</th>
                      <th scope="col">Returned records</th>
                    </tr>
                  </thead>
                  <tbody>
                    {categories.map(({ key, label, count }) => (
                      <tr key={key}>
                        <th scope="row">
                          <span>{label}</span>
                        </th>
                        <td>
                          <span className="prepared-counts-number">{count}</span>
                          <meter aria-hidden="true" min={0} max={returned} value={count} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p>
                  {returned
                    ? 'The returned records contain only excluded values.'
                    : 'This page contains no records.'}
                </p>
              )}
              <p className="muted">{continuationText(result.continuation)}</p>
              <details>
                <summary>Page and calculation details</summary>
                <dl>
                  <dt>Version</dt>
                  <dd>
                    <code>{request.versionId}</code>
                  </dd>
                  <dt>Resource</dt>
                  <dd>
                    <code>{request.representationId}</code>
                  </dd>
                  {request.releaseId && (
                    <>
                      <dt>Release</dt>
                      <dd>
                        <code>{request.releaseId}</code>
                      </dd>
                    </>
                  )}
                  <dt>Native field</dt>
                  <dd>
                    <code>{fieldName}</code>
                  </dd>
                  <dt>Filter</dt>
                  <dd>
                    {request.filter ? (
                      <code>
                        {pathLabel(request.filter.path)} ={' '}
                        {exactStringify(request.filter.equals, 0)}
                      </code>
                    ) : (
                      'No filter applied'
                    )}
                  </dd>
                  <dt>Returned page</dt>
                  <dd>{request.cursor ? 'Continuation page' : 'First page'}</dd>
                  <dt>Reader order</dt>
                  <dd>
                    {result.rowOrder === 'source-row'
                      ? 'Source row order'
                      : result.rowOrder === 'query-result'
                        ? 'Query result order'
                        : 'Ordering not supplied'}
                  </dd>
                  <dt>Grouping</dt>
                  <dd>
                    Values use their exact JSON spelling. Counts sort from largest to smallest. Ties
                    follow first appearance in the returned page.
                  </dd>
                </dl>
              </details>
              {onDownloadUnderlying && (
                <button type="button" onClick={onDownloadUnderlying}>
                  Download underlying page (JSON)
                </button>
              )}
            </figure>
          );
        },
      )}
    </div>
  );
}
