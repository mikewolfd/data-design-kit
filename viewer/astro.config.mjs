import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import node from '@astrojs/node';
export default defineConfig({
  integrations: [react()],
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  devToolbar: { enabled: false },
  server: { host: '127.0.0.1', port: 4321 },
});
