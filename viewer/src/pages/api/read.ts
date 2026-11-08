import type { APIRoute } from 'astro';
import { access } from '../../server/registry';
import { body, json, withApi } from '../../server/http';
export const POST: APIRoute = ({ request }) =>
  withApi(async () => json(await access.read(await body(request))));
