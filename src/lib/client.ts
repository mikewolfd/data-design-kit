export class RequestError extends Error {
  constructor(
    public code: string,
    public technicalMessage: string,
    public status: number,
  ) {
    super(requestMessage(code, technicalMessage));
    this.name = 'RequestError';
  }
}

/** Keep the original diagnostic for inspection; recovery copy describes actual UI actions. */
export function requestMessage(code: string, original: string): string {
  switch (code) {
    case 'invalid_cursor':
    case 'cursor_mismatch':
      return 'This page link is no longer valid. Return to the first page to continue.';
    case 'result_budget':
    case 'column_budget':
    case 'browser_budget':
      return 'This result is too large to display here.';
    case 'native_quota':
      return /quota/i.test(original)
        ? 'This example has reached its request or storage limit. The request cannot run until the operator resolves the limit.'
        : 'This example cannot run until the operator checks its saved request records.';
    case 'integrity_mismatch':
      return 'The portal cannot confirm that the requested file matches its recorded fingerprint. The file was not opened.';
    case 'catalog_mismatch':
      return 'This request refers to a different catalog copy. Reopen the dataset from the catalog available here.';
    case 'native_busy':
      return 'Another request is still running, or its outcome is unknown. This example cannot start another request yet.';
    case 'native_page_refused':
      return 'This example supports only its complete three-record result. A separate page cannot be opened.';
    case 'evidence_budget':
    case 'file_budget':
      return 'This file is too large to display here.';
    default:
      return original;
  }
}

export async function readText(response: Response, maxBytes: number): Promise<string> {
  if (!response.body) throw new Error('The server returned no content. Retry this request.');
  const reader = response.body.getReader(),
    chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        throw new RequestError(
          'browser_budget',
          `Response exceeds the ${maxBytes}-byte browser limit.`,
          413,
        );
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const chunk of chunks) {
    all.set(chunk, at);
    at += chunk.length;
  }
  return new TextDecoder('utf-8', { fatal: true }).decode(all);
}
export async function request<T>(url: string, signal?: AbortSignal, body?: unknown): Promise<T> {
  const timeout = AbortSignal.timeout(15_000);
  const response = await fetch(url, {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    cache: 'no-store',
    ...(body === undefined
      ? {}
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }),
  });
  const parsed = JSON.parse(await readText(response, 16 * 1024 * 1024));
  if (!response.ok)
    throw new RequestError(
      parsed.error?.code ?? 'request_failed',
      parsed.error?.message ?? `The request could not be completed (${response.status}).`,
      response.status,
    );
  return parsed as T;
}
