# Viewer themes

The viewer can share one interface across catalogs while an operator supplies its branding and appearance. A theme changes text, colors, local font preferences and sidebar width. Catalog definitions and connected adapters continue to own data meaning, coverage, availability and query behavior.

Set `DDK_VIEWER_THEME_CONFIG` to an absolute path to a local JSON file before starting the viewer. The server reads that file once, on its first page request. Restart the server after changing it. With no file configured, the viewer uses its generic Data catalog branding and warm-paper palette.

```json
{
  "brand": {
    "name": "River records",
    "mark": "rr",
    "tagline": "Watershed observatory"
  },
  "colors": {
    "accent": "#a33e24",
    "accentHover": "#86331e",
    "ink": "#252722",
    "muted": "#62665b",
    "line": "#deded5",
    "paper": "#fdfcf9",
    "sidebar": "#f3f2ec",
    "surface": "#fffefb",
    "soft": "#f5f4ee",
    "selected": "#eae3d9"
  },
  "fonts": { "ui": "inter", "reading": "serif" },
  "layout": { "sidebarWidth": 264 }
}
```

Every section and field is optional. Omitted values use the defaults in `src/lib/theme.ts`. Colors must use six-digit hex values. `fonts.ui` accepts `system`, `inter` or `humanist`; these select local font stacks and never download a font. `fonts.reading` accepts `serif` or `ui`. The reading font applies to long text in record detail. Sidebar width must be an integer from 220 to 320 pixels; the layout adapts on narrow screens.

The brand name allows up to 64 characters, the mark up to eight, and the tagline up to 100. All are plain text. The file is limited to 16 KiB. Unknown keys, malformed values, URLs and raw CSS are refused where a color or font choice is expected. The default palette has checked normal-text contrast; verify contrast again when supplying custom colors. Themes do not accept scripts, remote assets, dataset identifiers or behavior switches.

The shared reading pane preserves every returned field, exact numeric values, list order and repeated occurrences. Previous and next controls move only within the returned page. The Query lab appears in the same viewer and requires a connected SQL adapter and explicit input versions. A successful result must match the submitted SQL fingerprint and input identities. Its export retains the original SQL and selected inputs. Empty, refused and unknown results remain distinct.

The captured-source inventory describes all source observations disclosed in the catalog. It does not infer links to a selected data version. An original-file inspector is offered only for the maintained `urn:ddk:version:local-file-sha256` reference with a file URI and SHA-256 digest; the connected evidence adapter still decides whether the exact file may be opened.
