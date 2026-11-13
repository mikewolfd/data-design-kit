/** Presentation only. Catalog facts and adapter capabilities never come from a theme. */
export type ViewerTheme = {
  brand: { name: string; mark: string; tagline: string };
  colors: {
    accent: string;
    accentHover: string;
    ink: string;
    muted: string;
    line: string;
    paper: string;
    sidebar: string;
    surface: string;
    soft: string;
    selected: string;
  };
  fonts: { ui: 'system' | 'inter' | 'humanist'; reading: 'serif' | 'ui' };
  layout: { sidebarWidth: number };
};

const defaults: ViewerTheme = {
  brand: { name: 'Data catalog', mark: 'ddk', tagline: 'Data Design Kit' },
  colors: {
    accent: '#a33e24',
    accentHover: '#86331e',
    ink: '#252722',
    muted: '#62665b',
    line: '#deded5',
    paper: '#fdfcf9',
    sidebar: '#f3f2ec',
    surface: '#fffefb',
    soft: '#f5f4ee',
    selected: '#eae3d9',
  },
  fonts: { ui: 'inter', reading: 'serif' },
  layout: { sidebarWidth: 264 },
};

const uiFonts: Record<ViewerTheme['fonts']['ui'], string> = {
  system: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  inter: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  humanist: "Optima, Candara, 'Segoe UI', sans-serif",
};

function object(value: unknown, keys: readonly string[], path: string) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error(`Invalid viewer theme: ${path} must be an object.`);
  const result = value as Record<string, unknown>;
  for (const key of Object.keys(result))
    if (!keys.includes(key)) throw new Error(`Invalid viewer theme: unknown ${path} key ${key}.`);
  return result;
}

/** Accept bounded text, hex colors and known font choices, never arbitrary CSS or HTML. */
export function parseViewerTheme(input: unknown = {}): ViewerTheme {
  const source = object(input, ['brand', 'colors', 'fonts', 'layout'], 'configuration');
  const theme = structuredClone(defaults);
  if (source.brand !== undefined) {
    const brand = object(source.brand, ['name', 'mark', 'tagline'], 'brand');
    for (const key of ['name', 'mark', 'tagline'] as const) {
      const value = brand[key];
      if (value === undefined) continue;
      const limit = key === 'mark' ? 8 : key === 'name' ? 64 : 100;
      if (
        typeof value !== 'string' ||
        !value.trim() ||
        [...value.trim()].length > limit ||
        /[\u0000-\u001f\u007f]/.test(value)
      )
        throw new Error(`Invalid viewer theme: brand.${key} must be 1–${limit} characters.`);
      theme.brand[key] = value.trim();
    }
  }
  if (source.colors !== undefined) {
    const colors = object(source.colors, Object.keys(defaults.colors), 'colors');
    for (const key of Object.keys(colors) as (keyof ViewerTheme['colors'])[]) {
      const value = colors[key];
      if (typeof value !== 'string' || !/^#[0-9a-f]{6}$/i.test(value))
        throw new Error(`Invalid viewer theme: colors.${key} must use #RRGGBB.`);
      theme.colors[key] = value.toLowerCase();
    }
  }
  if (source.fonts !== undefined) {
    const fonts = object(source.fonts, ['ui', 'reading'], 'fonts');
    if (fonts.ui !== undefined) {
      if (typeof fonts.ui !== 'string' || !Object.hasOwn(uiFonts, fonts.ui))
        throw new Error('Invalid viewer theme: fonts.ui must be system, inter or humanist.');
      theme.fonts.ui = fonts.ui as ViewerTheme['fonts']['ui'];
    }
    if (fonts.reading !== undefined) {
      if (fonts.reading !== 'serif' && fonts.reading !== 'ui')
        throw new Error('Invalid viewer theme: fonts.reading must be serif or ui.');
      theme.fonts.reading = fonts.reading;
    }
  }
  if (source.layout !== undefined) {
    const layout = object(source.layout, ['sidebarWidth'], 'layout');
    if (layout.sidebarWidth !== undefined) {
      if (
        typeof layout.sidebarWidth !== 'number' ||
        !Number.isInteger(layout.sidebarWidth) ||
        layout.sidebarWidth < 220 ||
        layout.sidebarWidth > 320
      )
        throw new Error('Invalid viewer theme: layout.sidebarWidth must be 220–320 pixels.');
      theme.layout.sidebarWidth = layout.sidebarWidth;
    }
  }
  return theme;
}

/** Only validated, locally defined values enter this style attribute. */
export function themeStyles(theme: ViewerTheme): string {
  // Revalidate here so callers cannot bypass the CSS boundary with a type assertion.
  const valid = parseViewerTheme(theme);
  const values: Record<string, string> = {
    ...Object.fromEntries(
      Object.entries(valid.colors).map(([key, value]) => [
        `--${key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`,
        value,
      ]),
    ),
    '--font-ui': uiFonts[valid.fonts.ui],
    '--font-reading':
      valid.fonts.reading === 'serif'
        ? "Georgia, 'Times New Roman', serif"
        : uiFonts[valid.fonts.ui],
    '--sidebar-width': `${valid.layout.sidebarWidth}px`,
  };
  return Object.entries(values)
    .map(([key, value]) => `${key}: ${value}`)
    .join('; ');
}
