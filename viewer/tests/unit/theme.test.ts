import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { parseViewerTheme, themeStyles } from '../../src/lib/theme';
import { loadViewerTheme } from '../../src/server/theme';
import { ViewerBrand } from '../../src/components/ViewerBrand';
import { Value } from '../../src/components/Primitives';

test('generic theme defaults and independent partial overrides need no catalog or external assets', () => {
  const defaults = parseViewerTheme();
  assert.equal(defaults.brand.name, 'Data catalog');
  assert.equal(defaults.brand.mark, 'ddk');
  const custom = parseViewerTheme({ brand: { name: 'River records', mark: 'rr' } });
  assert.equal(custom.brand.tagline, 'Data Design Kit');
  custom.colors.ink = '#000000';
  assert.equal(parseViewerTheme().colors.ink, '#252722');
  assert.match(themeStyles(defaults), /--accent: #a33e24/);
  assert.match(themeStyles(defaults), /--sidebar-width: 264px/);
  assert.doesNotMatch(themeStyles(defaults), /url\(|@import|https?:/);
  const other = parseViewerTheme({
    fonts: { ui: 'system', reading: 'ui' },
    layout: { sidebarWidth: 220 },
  });
  assert.match(themeStyles(other), /--sidebar-width: 220px/);
  assert.doesNotMatch(themeStyles(other), /Georgia/);
});

test('theme rejects CSS injection, unbounded layout, unknown keys and arbitrary font sources', () => {
  for (const config of [
    null,
    [],
    'paper',
    { colors: { accent: 'red; background: url(https://example.test)' } },
    { colors: { accent: '#000' } },
    { colors: { backgroundImage: 'url(https://example.test)' } },
    { fonts: { ui: 'url(https://example.test/font)' } },
    { fonts: { ui: '__proto__' } },
    { fonts: { reading: 'custom' } },
    { brand: { mark: 'unbounded mark' } },
    { brand: { name: 'a\nb' } },
    { brand: { name: '   ' } },
    { layout: { sidebarWidth: 219 } },
    { layout: { sidebarWidth: 321 } },
    { layout: { sidebarWidth: 240.5 } },
    { layout: { sidebarWidth: '264px' } },
    { datasetIds: ['domain-table'] },
    JSON.parse('{"__proto__":{"colors":{"accent":"red"}}}'),
  ])
    assert.throws(() => parseViewerTheme(config), /Invalid viewer theme/);
  const bypass = parseViewerTheme();
  bypass.colors.accent = 'red; display: none';
  assert.throws(() => themeStyles(bypass), /Invalid viewer theme/);
});

test('brand text and record prose stay text while exact values and duplicate occurrences remain visible', () => {
  const theme = parseViewerTheme({ brand: { name: '<script>catalog</script>', mark: '<b>' } });
  const brand = renderToStaticMarkup(createElement(ViewerBrand, { theme }));
  assert.match(brand, /&lt;script&gt;catalog&lt;\/script&gt;/);
  assert.doesNotMatch(brand, /<script>|<b>/);
  const prose = '<em>Publisher text</em>\n\n' + 'A retained sentence. '.repeat(12);
  const html = renderToStaticMarkup(
    createElement(Value, {
      value: {
        prose,
        amount: { $number: '9007199254740993' },
        repeated: ['same', 'same'],
        blank: null,
      },
      full: true,
    }),
  );
  assert.match(html, /class="prose-value"/);
  assert.match(html, /&lt;em&gt;Publisher text&lt;\/em&gt;\n\n/);
  assert.match(html, /9007199254740993/);
  assert.equal((html.match(/>same</g) ?? []).length, 2);
  assert.match(html, />null</);
});

test('default foregrounds meet normal-text contrast across configurable reading surfaces', () => {
  const colors = parseViewerTheme().colors;
  function luminance(hex: string) {
    const parts = [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16) / 255);
    const [r, g, b] = parts.map((channel) =>
      channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
    );
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  function contrast(foreground: string, background: string) {
    const pair = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
    return (pair[0] + 0.05) / (pair[1] + 0.05);
  }
  for (const background of [
    colors.paper,
    colors.sidebar,
    colors.surface,
    colors.soft,
    colors.selected,
  ])
    for (const foreground of [colors.ink, colors.muted, colors.accent])
      assert.ok(contrast(foreground, background) >= 4.5, `${foreground} on ${background}`);
  assert.ok(contrast('#ffffff', colors.accent) >= 4.5);
  assert.ok(contrast('#ffffff', colors.accentHover) >= 4.5);
});

test('operator theme reads only a bounded local JSON file and refuses malformed configuration', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'ddk-viewer-theme-'));
  const path = join(directory, 'theme.json');
  try {
    assert.equal((await loadViewerTheme()).brand.name, 'Data catalog');
    await assert.rejects(loadViewerTheme('theme.json'), /absolute file path/);
    await writeFile(path, JSON.stringify({ brand: { name: 'Test catalog' } }));
    assert.equal((await loadViewerTheme(path)).brand.name, 'Test catalog');
    await writeFile(path, '{malformed');
    await assert.rejects(loadViewerTheme(path), /valid JSON/);
    await writeFile(path, ' '.repeat(16_385));
    await assert.rejects(loadViewerTheme(path), /at most 16,384 bytes/);
    await writeFile(path, '{"colors":{"accent":"invalid"}}');
    await assert.rejects(loadViewerTheme(path), /#RRGGBB/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
