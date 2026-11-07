import { test, expect } from '@playwright/test';
import { resolve } from 'node:path';
import { CatalogStore } from '../../src/server/catalog-store';
import { fixturePins } from '../../src/server/fixture-pins';
import { spicyPairDirectory, spicyPairSnapshot } from '../helpers/spicy-pair';

for (const [name, viewport] of [
  ['desktop', { width: 1440, height: 1000 }],
  ['mobile', { width: 390, height: 844 }],
] as const) {
  test(`supplied check scopes and reasons remain readable on ${name}`, async ({
    page,
  }, testInfo) => {
    const pin = fixturePins.find((row) => row.id === 'watershed')!;
    const snapshots = [
      ...(spicyPairDirectory
        ? [await spicyPairSnapshot('public'), await spicyPairSnapshot('local')]
        : []),
      await new CatalogStore([
        { ...pin, directory: resolve('fixtures/watershed'), mode: 'fixture' },
      ]).snapshot(pin.id),
      await new CatalogStore(
        [
          {
            id: 'commerce-check-metadata',
            directory: resolve('fixtures/applications/commerce-native'),
            lockSha256: 'efd61cc7f5de0fec81fec7f4750805030e21dbfa6d6ffeb7393dc56bc4504f82',
            mode: 'application',
            exampleData: 'synthetic',
          },
        ],
        'local',
      ).snapshot('commerce-check-metadata'),
    ];
    const operations: string[] = [],
      errors: string[] = [];
    page.on('request', (request) => {
      if (/\/api\/(read|query|evidence)(?:\?|$)/.test(request.url()))
        operations.push(request.url());
    });
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route(/\/api\/(read|query|evidence)(?:\?|$)/, (route) => route.abort());
    await page.route('**/api/catalogs', (route) => route.fulfill({ json: { catalogs: [] } }));
    await page.route('**/api/catalogs/*', (route) => {
      const id = new URL(route.request().url()).pathname.split('/').at(-1);
      const snapshot = snapshots.find((row) => row.id === id);
      return route.fulfill({ status: snapshot ? 200 : 404, json: snapshot ?? {} });
    });
    await page.setViewportSize(viewport);
    for (const snapshot of snapshots) {
      let checked = 0;
      const versions = snapshot.catalog.versions.filter((version) =>
        snapshot.catalog.checks.some((check) => check.subject === version.id),
      );
      for (const version of versions) {
        const checks = snapshot.catalog.checks.filter((check) => check.subject === version.id);
        await page.goto(
          `/?${new URLSearchParams({
            catalog: snapshot.id,
            dataset: version.dataset,
            version: version.id,
            snapshot: snapshot.identity.catalogSha256,
            tab: 'Evidence',
          })}`,
        );
        const section = page.locator('section.section').filter({
          has: page.getByRole('heading', { name: 'Checks for this data version', exact: true }),
        });
        const cards = section.locator('.evidence-row');
        await expect(cards).toHaveCount(checks.length);
        expect(await cards.locator('strong').allTextContents()).toEqual(
          checks.map((check) => check.scope),
        );
        await expect(section).not.toContainText('title not supplied');
        for (const [index, check] of checks.entries()) {
          const card = cards.nth(index);
          const reason = card.locator(':scope > div > p');
          if (check.reason) await expect(reason).toHaveText(check.reason);
          else await expect(reason).toHaveCount(0);
          await expect(card.locator('.badge')).toHaveText(
            check.status === 'not_run'
              ? 'Not run'
              : check.status[0].toUpperCase() + check.status.slice(1),
          );
          const summary = card.getByText('Rule and evaluator details', { exact: true });
          await summary.focus();
          await summary.press('Enter');
          await expect(card.locator('details')).toHaveAttribute('open', '');
          for (const value of [
            check.rule.id,
            check.rule.version,
            check.evaluator.id,
            check.evaluator.version,
          ])
            await expect(card.locator('details')).toContainText(value);
          if (check.record) {
            await expect(card.locator('.record-link')).toContainText(check.record.uri);
            if (check.record.sha256)
              await expect(card.locator('.record-link')).toContainText(check.record.sha256);
          }
          checked++;
        }
        if (snapshot.id === 'spicy-pair-public') {
          await expect(section).not.toContainText('file:///');
          expect(snapshot.catalog.runs).toEqual([]);
          expect(
            (snapshot.catalog.extensions?.['urn:ddk:catalog:assembly'] as Record<string, unknown>)
              ?.managedExecutions,
          ).toBeUndefined();
          const longest = checks.reduce(
            (best, check, i) => (check.scope.length > checks[best].scope.length ? i : best),
            0,
          );
          if (version === versions[0])
            await cards
              .nth(longest)
              .screenshot({ path: testInfo.outputPath(`long-scope-${name}.png`) });
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
      }
      if (snapshot.id.startsWith('spicy-pair-')) expect(checked).toBe(24);
      else expect(checked).toBeGreaterThan(0);
    }
    expect(operations).toEqual([]);
    expect(errors).toEqual([]);
  });
}
