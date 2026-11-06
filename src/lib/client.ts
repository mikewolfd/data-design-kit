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
        throw new Error('This response exceeds the browser byte limit.');
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
    throw new Error(
      parsed.error?.message ?? `Request failed (${response.status}). Retry this request.`,
    );
  return parsed as T;
}
