import { useState } from 'react';
import type { CatalogSnapshot, ExactReference, RecordRef } from '../../domain/types';
import { exactObjectField, isObject } from '../../domain/exact';
import { Badge, Raw } from '../../components/Primitives';
import { EvidenceRecord } from '../../components/EvidenceRecord';

/** Decode only the maintained native file reference; its owner still authorizes every read. */
export function originalSourceRecord(reference?: ExactReference): RecordRef | undefined {
  if (reference?.scheme !== 'urn:ddk:version:local-file-sha256' || !isObject(reference.value))
    return undefined;
  const location = exactObjectField(reference.value, 'location');
  const sha256 = exactObjectField(reference.value, 'sha256');
  if (typeof location !== 'string' || typeof sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(sha256))
    return undefined;
  try {
    if (new URL(location).protocol !== 'file:') return undefined;
  } catch {
    return undefined;
  }
  return { uri: location, sha256 };
}

export function CapturedSources({ snapshot }: { snapshot: CatalogSnapshot }) {
  const [limit, setLimit] = useState(50);
  const sources = snapshot.catalog.sources;
  return (
    <div className="captured-sources">
      <p>
        {sources.length} recorded source {sources.length === 1 ? 'observation' : 'observations'} in
        this catalog. This inventory does not establish publisher-wide completeness or a link to the
        selected data version.
      </p>
      {sources.length ? (
        <>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Captured source inventory"
          >
            <table className="data-table source-inventory">
              <caption className="sr-only">Captured sources in this catalog</caption>
              <thead>
                <tr>
                  <th scope="col">Recorded scope</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Retained original</th>
                </tr>
              </thead>
              <tbody>
                {sources.slice(0, limit).map((source) => {
                  const original = originalSourceRecord(source.content);
                  return (
                    <tr key={source.id}>
                      <td>
                        <span>{source.scope || 'Scope not supplied'}</span>
                        <Raw
                          value={{
                            id: source.id,
                            reference: source.reference,
                            content: source.content,
                            record: source.record,
                          }}
                          label="Source and capture references"
                        />
                      </td>
                      <td>
                        <Badge status={source.outcome} />
                      </td>
                      <td>
                        {original ? (
                          <EvidenceRecord
                            snapshot={snapshot}
                            record={original}
                            label="Inspect retained original"
                            purpose="original"
                          />
                        ) : (
                          <span className="muted">
                            No supported digest-pinned original file is supplied.
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {sources.length > limit && (
            <button onClick={() => setLimit((previous) => previous + 50)}>
              Show {Math.min(50, sources.length - limit)} more source observations
            </button>
          )}
        </>
      ) : (
        <p className="muted">
          No source observations are recorded. Source coverage remains unknown.
        </p>
      )}
    </div>
  );
}
