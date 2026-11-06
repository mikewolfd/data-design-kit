import { parseRequest } from '../domain/exact';
import { LIMITS, ViewerError, fail } from './catalog-store';

let active = 0;
const MAX_ACTIVE = 8;
export const json = (value: unknown, status = 200): Response =>
  new Response(JSON.stringify(value), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
    },
  });
export async function withApi(action: () => Promise<Response>): Promise<Response> {
  if (active >= MAX_ACTIVE)
    return json(
      { error: { code: 'server_busy', message: 'The bounded reader is busy. Retry shortly.' } },
      503,
    );
  active++;
  try {
    return await action();
  } catch (error) {
    if (error instanceof ViewerError)
      return json({ error: { code: error.code, message: error.message } }, error.status);
    if (error instanceof SyntaxError)
      return json(
        {
          error: {
            code: 'invalid_json',
            message:
              'The JSON is malformed, contains duplicate keys, or uses an unsupported value.',
          },
        },
        400,
      );
    return json(
      {
        error: { code: 'read_failed', message: 'The registered catalog could not be read safely.' },
      },
      409,
    );
  } finally {
    active--;
  }
}
export async function body(request: Request): Promise<any> {
  if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json'))
    fail('content_type', 'Send application/json.');
  const length = request.headers.get('content-length');
  if (length && (!/^\d+$/.test(length) || Number(length) > LIMITS.requestBytes))
    fail('request_budget', 'The request exceeds the supported byte budget.', 413);
  if (!request.body) fail('invalid_request', 'A JSON request body is required.');
  const reader = request.body.getReader(),
    chunks: Uint8Array[] = [];
  let size = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      void reader.cancel();
      reject(new ViewerError('deadline', 'The request body exceeded its deadline.', 408));
    }, LIMITS.deadlineMs);
  });
  try {
    for (;;) {
      const { value, done } = await Promise.race([reader.read(), timeout]);
      if (done) break;
      size += value.byteLength;
      if (size > LIMITS.requestBytes) {
        await reader.cancel();
        fail('request_budget', 'The request exceeds the supported byte budget.', 413);
      }
      chunks.push(value);
    }
    const joined = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      joined.set(chunk, offset);
      offset += chunk.length;
    }
    try {
      return parseRequest(new TextDecoder('utf-8', { fatal: true }).decode(joined));
    } catch {
      fail(
        'invalid_json',
        'The JSON is malformed, ambiguous or exceeds the supported value budget.',
      );
    }
  } finally {
    clearTimeout(timer);
    reader.releaseLock();
  }
}
