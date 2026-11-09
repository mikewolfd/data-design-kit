import type { APIRoute } from 'astro';
import { store } from '../../server/registry';
import { loadImpact } from '../../server/impact';
import { impactPins } from '../../server/impact-pin';
import { withApi, json } from '../../server/http';
export const GET: APIRoute = async ({ url }) =>
  withApi(async () =>
    json(
      await loadImpact(
        store,
        impactPins,
        url.searchParams.get('catalogId') || '',
        url.searchParams.get('catalogSha256') || '',
      ),
    ),
  );
