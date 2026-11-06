import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: 'tests/browser',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  reporter: [['list'], ['json', { outputFile: 'work/browser-results.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:4321',
    channel: 'chrome',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
