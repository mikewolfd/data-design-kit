import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async ({ request, url }, next) => {
  if (process.env.DDK_VIEWER_AUDIENCE === 'local') {
    const host = request.headers.get('host') ?? url.host;
    const origin = request.headers.get('origin');
    if (!/^(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?$/.test(host) ||
        !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
        (origin !== null && origin !== `${url.protocol}//${host}`))
      return new Response('This local viewer accepts same-origin loopback requests only.', { status: 403 });
  }
  const response = await next();
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('Content-Security-Policy', "frame-ancestors 'none'; base-uri 'none'; object-src 'none'");
  return response;
});
