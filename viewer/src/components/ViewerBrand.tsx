import type { ViewerTheme } from '../lib/theme';

export function ViewerBrand({ theme, onHome }: { theme: ViewerTheme; onHome?: () => void }) {
  return (
    <a
      className="brand"
      href="/"
      aria-label={`${theme.brand.mark} ${theme.brand.name} home`}
      onClick={(event) => {
        if (
          onHome &&
          !event.metaKey &&
          !event.ctrlKey &&
          !event.shiftKey &&
          !event.altKey &&
          event.button === 0
        ) {
          event.preventDefault();
          onHome();
        }
      }}
    >
      <span className="brand-mark" aria-hidden="true">
        {theme.brand.mark}
      </span>{' '}
      <span className="brand-name">{theme.brand.name}</span>
    </a>
  );
}
