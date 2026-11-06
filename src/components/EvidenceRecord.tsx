import { useEffect, useRef, useState } from 'react';
import type { CatalogSnapshot, EvidenceResult, RecordRef } from '../domain/types';
import { request } from '../lib/client';
import { Notice, Raw, RecordLink } from './Primitives';

/** Evidence content is loaded only through the selected owner's exact-record reader. */
export function EvidenceRecord({
  snapshot,
  record,
  label = 'Inspect owner evidence',
}: {
  snapshot: CatalogSnapshot;
  record?: RecordRef;
  label?: string;
}) {
  const [result, setResult] = useState<EvidenceResult>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController>(null);
  useEffect(() => {
    setResult(undefined);
    setError('');
    setLoading(false);
    return () => controller.current?.abort();
  }, [snapshot.identity.catalogSha256, record?.uri, record?.sha256]);
  async function inspect() {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setLoading(true);
    setError('');
    try {
      const value = await request<EvidenceResult>('/api/evidence', abort.signal, {
        catalogId: snapshot.id,
        catalogSha256: snapshot.identity.catalogSha256,
        record,
      });
      if (!abort.signal.aborted) setResult(value);
    } catch (e) {
      if (!abort.signal.aborted) setError((e as Error).message);
    } finally {
      if (!abort.signal.aborted) setLoading(false);
    }
  }
  return (
    <div className="owner-evidence">
      <RecordLink record={record} />
      {snapshot.capabilities.evidence && record?.sha256 && (
        <>
          <button className="text-button" disabled={loading} onClick={() => void inspect()}>
            {loading ? 'Reading verified evidence…' : result ? 'Reload owner evidence' : label}
          </button>
          {error && (
            <Notice title="Evidence could not be loaded" kind="error">
              {error}
            </Notice>
          )}
          {result && (
            <>
              <p role="status">Exact evidence verified. {result.scope}</p>
              <Raw value={result.document} label="Verified evidence document" />
            </>
          )}
        </>
      )}
    </div>
  );
}
