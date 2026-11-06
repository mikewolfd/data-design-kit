# DDK viewer

A standalone React workspace, served by Astro, for exploring Data Design Kit catalogs. It reads the standard catalog, report, lock, and exact companion inventory. Definitions, availability, observed checks, native acceptance, and publisher selection remain separate.

## Run locally

```sh
npm ci
npm run dev
```

Open http://127.0.0.1:4321. npm scripts use the pinned project-local Node 22.23.4; no system Node change is required. Install dependencies with a working Node/npm installation. `npm run build` checks TypeScript and produces the Astro Node build. After stopping development with `npm exec -- astro dev stop`, `npm run preview` serves that build on the same local port.

The two default configurations are independently authored synthetic catalogs: watershed observations and public-service grants. Both include exact versions, scoped relationships, recipes, unknown/missing qualification, and unavailable evidence. Their data is labelled as demonstration data. They do not establish DDK assembly acceptance or native runtime qualification.

To include the read-only application catalogs captured for this task:

```sh
DDK_VIEWER_APPLICATIONS=spicy-regs,congress npm run dev
# or after building:
DDK_VIEWER_APPLICATIONS=spicy-regs,congress npm run preview
```

The allowlist in `src/server/registry.ts` pins each local directory and lock digest. Missing or changed sources refuse safely; no “latest” discovery or fallback data is used. These optional registrations use retained public metadata under `fixtures/applications/`. SpicyRegs is a public definition-only dev4 catalog. Its active source advanced from dev3 during implementation; the new dev4 controls were independently verified and captured before qualification. Congress is a public dev4 application metadata fixture with 24 datasets and 16 recipes; its tiny physical reader fixtures do not establish full native candidate quality. The viewer opens neither application's row files. Their live data/query capabilities remain unavailable until an explicit owner adapter is registered.

## What works

- Search dataset meaning and source context, filter availability, inspect product ports and nested definitions.
- Choose an exact version and representation, read bounded pages, filter exact scalar values, inspect ordered nested occurrences, and export the page with its request and visible-column context.
- Inspect ordered relationship keys, scope, null handling, external references, and navigate exact same-release endpoints when resolvable. Other links explicitly open definitions.
- Inspect and run only registered recipes; exact SQL, parameters, real inputs, explanatory relationships, release and result identity remain visible.
- Inspect report and exact-version checks without converting declared, unknown, or not_run outcomes into passes. Inspect source occurrences, coverage, runs, production definitions, release membership and publisher selections.
- Compare recorded versions and inspect a genuine `ddk.catalog_impact.compare_catalogs` report bound to exact base/candidate/report bytes. Metadata obligations, computation reuse, and qualification reuse stay distinct.
- Share a digest-bound workspace URL and export exact references, bounded pages, query results and impact evidence.

The shared runtime has no universal data-reader service in the qualified dev4 package. Native binary/timestamp decoding, managed actions, streaming quality, retained multi-output execution, complete candidate accepted-evidence mapping and publication recovery require their actual owners' qualified adapters. This app does not implement an execution engine, scheduler, recovery journal or selection authority.

## Reuse and integration

The React UI in `src/components/` consumes `CatalogSnapshot` and the bounded interfaces in `src/domain/types.ts`. Astro routes are thin transport adapters. `src/server/registry.ts` is the composition root; it chooses permitted sources and optional owner adapters. Domain code contains no congressional or regulatory table registries.

Read [the adapter guide](docs/adapters.md) before registering an owner. Actual producer definitions and standard output files remain authoritative. Adapter capability disclosure must match the concrete registered adapter. An available representation does not imply a configured reader, and a reader result does not establish data qualification.

Exact numeric transport uses `ddk-exact-json-v1`. Every data number is represented as `{"$number":"original JSON lexeme"}`; source objects containing reserved tag fields are escaped as `{"$object":[["field",value],...]}`. `src/domain/exact.ts` supplies lossless parsing, numeric comparison, rendering and reconstruction. Missing fields, `null`, empty text, empty lists, ordering and duplicate list occurrences remain distinct. Use `exactStringify` to reconstruct ordinary JSON with exact numeric tokens; native timestamps and binary values must retain owner-defined type interpretation.

The UI uses semantic HTML, manual-activation keyboard tabs, a skip link, live status messages, visible focus, local table scrolling and reduced motion. The task hypotheses and information architecture are in [docs/design.md](docs/design.md). No user research or screen-reader certification is claimed.

## Verification

```sh
npm test
npm run check
npm run build
npm run test:browser
```

The browser suite expects a running local preview and uses installed Google Chrome. It tests desktop and 390px/320px mobile layouts, keyboard interaction, exact values, pagination, filter retry, refusal, response races, historical relationships, impact, exports and automated accessibility. Enable the two application registrations to include their browser check; otherwise that one test is explicitly skipped.

Fixtures were checked against the schemas inside the qualified installed dev4 wheel. `fixtures/validation.json` records that limited shape check. They are authored format examples; schema validity is not executed quality or native acceptance. The impact fixture is generated by `scripts/build-impact.py` with the qualified Python environment named in the shared handoff. Rebuilding fixtures requires regenerating the impact receipt afterwards. No Python/native runtime is needed to run the application.

The final verification record and retained screenshots are in `outputs/`. Earlier failed browser runs remain in `work/` as scratch diagnosis; the final record states the tested revision and scope. Local commits and local preview do not imply publication or deployment.
