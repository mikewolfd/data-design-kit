import type { ViewerTheme } from '../lib/theme';

export function ViewerBrand({ theme }: { theme: ViewerTheme }) {
  return (
    <a className="brand" href="/" aria-label={`${theme.brand.name} home`}>
      <span className="brand-mark" aria-hidden="true">
        {theme.brand.mark}
      </span>
      <span className="brand-name">{theme.brand.name}</span>
    </a>
  );
}
