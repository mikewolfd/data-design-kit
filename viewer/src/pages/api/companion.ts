import type { APIRoute } from 'astro';
import { store } from '../../server/registry';
import { withApi } from '../../server/http';
export const GET: APIRoute = ({ url }) =>
  withApi(async () => {
    const path = url.searchParams.get('path') ?? '';
    const bytes = await store.companion(
      url.searchParams.get('catalogId') ?? '',
      url.searchParams.get('catalogSha256') ?? '',
      path,
    );
    return new Response(new Uint8Array(bytes), {
      headers: {
        'content-type': path.endsWith('.json')
          ? 'application/json; charset=utf-8'
          : 'text/plain; charset=utf-8',
        'cache-control': 'no-store',
        'x-content-type-options': 'nosniff',
      },
    });
  });
