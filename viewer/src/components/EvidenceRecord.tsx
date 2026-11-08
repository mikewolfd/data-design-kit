import { useEffect, useRef, useState } from 'react';
import type { CatalogSnapshot, EvidenceResult, RecordRef } from '../domain/types';
import { request } from '../lib/client';
import { Notice, Raw, RecordLink } from './Primitives';

/** Evidence content is loaded only through the selected owner's exact-record reader. */
export function EvidenceRecord({
  snapshot,
  record,
  label = 'View publisher evidence',
}: {
  snapshot: CatalogSnapshot;
  record?: RecordRef;
  label?: string;
}) {
  const [result, setResult] = useState<EvidenceResult>();
  const [error, setError] = useState('');
  const [errorDetails, setErrorDetails] = useState<unknown>();
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
    setResult(undefined);
    setErrorDetails(undefined);
    try {
      const value = await request<EvidenceResult>('/api/evidence', abort.signal, {
        catalogId: snapshot.id,
        catalogSha256: snapshot.identity.catalogSha256,
        record,
      });
      if (!abort.signal.aborted) setResult(value);
    } catch (e) {
      if (!abort.signal.aborted) {
        const failure = e as Error & { code?: string; technicalMessage?: string };
        setError(failure.message);
        setErrorDetails({
          code: failure.code,
          message: failure.technicalMessage ?? failure.message,
        });
      }
    } finally {
      if (!abort.signal.aborted) setLoading(false);
    }
  }
  return (
    <div className="owner-evidence">
      <RecordLink record={record} />
      {record && (!snapshot.capabilities.evidence || !record.sha256) && (
        <p className="muted">
          {!snapshot.capabilities.evidence
            ? 'This portal cannot open the evidence file. Its recorded reference is shown above.'
            : 'This record has no file fingerprint, so this portal cannot verify and open its evidence file.'}
        </p>
      )}
      {snapshot.capabilities.evidence && record?.sha256 && (
        <>
          <button className="text-button" disabled={loading} onClick={() => void inspect()}>
            {loading ? 'Opening evidence file…' : result ? 'Reload publisher evidence' : label}
          </button>
          {error && (
            <Notice title="Evidence could not be loaded" kind="error">
              {error}
              <Raw value={errorDetails} label="Error details" />
            </Notice>
          )}
          {result && (
            <>
              <p role="status">
                Evidence file matches its recorded fingerprint. This confirms the file’s identity;
                its contents describe what was checked. {result.scope}
              </p>
              <Raw value={result.document} label="View evidence document" />
            </>
          )}
        </>
      )}
    </div>
  );
}
