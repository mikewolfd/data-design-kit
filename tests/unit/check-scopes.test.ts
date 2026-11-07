import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Evidence } from '../../src/components/MetadataPanels';
import { spicyPairDirectory, spicyPairSnapshot } from '../helpers/spicy-pair';

const escaped = (text: string) =>
  renderToStaticMarkup(createElement('span', null, text)).slice(6, -7);

for (const audience of ['public', 'local'] as const) {
  test(
    `the pinned ${audience} Spicy pair shows all 24 exact scopes without invented labels`,
    { skip: !spicyPairDirectory && 'The pinned Spicy catalog pair is not supplied.' },
    async () => {
      const snapshot = await spicyPairSnapshot(audience);
      const before = JSON.stringify(snapshot);
      assert.equal(snapshot.catalog.checks.length, 24);
      assert.equal(snapshot.audience, audience);
      assert.equal(snapshot.capabilities.read, false);
      assert.equal(snapshot.capabilities.query, false);
      assert.ok(!snapshot.capabilities.evidence);
      let checked = 0;
      for (const version of snapshot.catalog.versions) {
        const checks = snapshot.catalog.checks.filter((row) => row.subject === version.id);
        if (!checks.length) continue;
        assert.equal(checks.length, 6);
        const dataset = snapshot.catalog.datasets.find((row) => row.alias === version.dataset)!;
        const html = renderToStaticMarkup(createElement(Evidence, { snapshot, dataset, version }));
        assert.match(html, /6 recorded; 6 passed; 0 failed; 0 unknown; 0 not run/);
        assert.doesNotMatch(html, /Check \d+ · title not supplied/);
        const section = html
          .split('<h2>Checks for this data version</h2>')[1]
          .split('</section>')[0];
        assert.deepEqual(
          [...section.matchAll(/<strong>(.*?)<\/strong>/gs)].map((match) => match[1]),
          checks.map((check) => escaped(check.scope)),
        );
        for (const check of checks) {
          assert.ok(html.includes(`<strong>${escaped(check.scope)}</strong>`));
          assert.ok(!html.includes(`<p>${escaped(check.scope)}</p>`));
          for (const value of [
            check.rule.id,
            check.rule.version,
            check.evaluator.id,
            check.evaluator.version,
            check.record!.uri,
            check.record!.sha256!,
          ]) {
            assert.ok(html.includes(escaped(value)), value);
          }
          assert.equal(check.reason, undefined);
          if (audience === 'public') assert.match(check.record!.uri, /^urn:ddk:sha256:/);
          checked++;
        }
        if (audience === 'public')
          assert.doesNotMatch(html, /file:\/\/|\/Users\/|Recorded processing acceptance/);
      }
      assert.equal(checked, 24);
      assert.equal(JSON.stringify(snapshot), before);
    },
  );
}
