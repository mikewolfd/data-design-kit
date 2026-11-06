import type { APIRoute } from 'astro';
import { store } from '../../../server/registry';
import { json, withApi } from '../../../server/http';
export const GET: APIRoute = () => withApi(async () => json(await store.list()));
