import type { APIRoute } from 'astro';
import { access } from '../../../server/registry';
import { json, withApi } from '../../../server/http';
export const GET: APIRoute = ({ params }) =>
  withApi(async () => {
    const { definitions: _derivedDefinitions, ...snapshot } = await access.snapshot(
      params.id ?? '',
    );
    return json(snapshot);
  });
