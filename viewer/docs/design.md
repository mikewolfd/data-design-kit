# DDK viewer: tasks and information architecture

The viewer helps a reader decide whether an exact dataset is useful for a task, inspect its records when a supported reader exists, and carry its identity and limitations into the next step. These are task hypotheses, not findings from user research. Acceptance uses independent fixtures and task-based browser checks; research with actual users remains future work.

The visual direction is a calm, paper-colored workspace with a quiet green accent, readable tables, and a persistent dataset navigator. Content starts with catalog choice and search, then the selected dataset, version, and task. There is no marketing surface. Motion is limited to short focus/hover feedback and progress indication; reduced-motion preferences remove it.

| Reader task | Working surface | Evidence retained |
| --- | --- | --- |
| Find data for a purpose | Catalog choice, search, dataset list, purpose and product ports | Admitted catalog identity, definition revision, disclosed scope |
| Understand meaning and coverage | Overview and nested field definitions | Original paths, native types, root descriptions, identities, source scope |
| Inspect exact records | Version and representation choice, bounded pages, row details | Exact reference, source occurrence, filter, page cursor, typed values |
| Follow a connection | Relationship detail and destination dataset; explicit recipe form | Ordered keys, list traversal, null policy, release scope, actual versus contextual inputs |
| Assess suitability | Checks & sources | Required check outcomes, evidence level, version/rule/evaluator, unknown and not_run |
| Understand a change | Side-by-side version facts and available owner impact evidence | Exact base/candidate, metadata, requalification and computation distinguished |
| Inspect work and selection | History, source records, production definitions, release membership | Owner operation references, input coverage, observed outcome and publisher selections |
| Share or export | Exact-reference download, bounded page download, verified companions | Catalog digest, version/representation, query/filter context, explicit sample scope |

## System boundary

Standard DDK catalog, report, lock, and companion inventories go into a server-side allowlisted source adapter. It checks the pinned control bytes, preserves the admitted facts, and returns them to a reusable React workspace. Reader and query adapters are injected at the application composition root. A demonstration adapter performs only supported operations over small independently authored fixtures. Real application catalogs have discovery only until their owner supplies a qualified reader.

The viewer does not resolve authority by filename, timestamp, record count, or a digest alone. Publisher selection comes from explicit selection records. An explicit historical version may be inspected without asserting it is selected. Same-release recipes require complete exact membership. Contextual relationships never become query inputs.

The standard source remains the fact owner. There is no app metadata registry, no source-definition regeneration, no copied native runtime, no scheduler, and no selection mutation. Admitted incomplete evidence remains inspectable. Definition-check success, data access, data qualification, native acceptance, and publication remain separate facts.

## State and accessibility

Catalog, dataset, tab, and explicit version live in the URL. Bound data requests carry the catalog digest and exact representation. Switching context aborts pending work; late responses cannot replace a newer selection. Errors preserve the chosen task and parameters, with explicit retry. No row prefetch, browser persistence, full-dataset export, or automatic external fetching occurs.

Semantic headings, landmarks, tables, labels, native buttons/selects, a skip link, visible focus, keyboard-operable tabs, polite status announcements, a wrapping mobile layout, and reduced motion support form the baseline. Large/nested values expand on request. Null, missing, empty text, and empty lists have separate labels. Unknown types are displayed faithfully rather than coerced.

## Source-grounded decisions

SpicyGov's discovery, exact-version readers, provenance details, and explicit unavailable links supply useful task precedent. Its domain registries and legacy publication readers are not shared viewer dependencies. The two replacement readers show why release membership, field/list identities, public disclosures, and recipe input scopes matter.

The original bounded Commerce reader qualification remains DDK 0.1.0-dev.4, source `fb70ab825243235b4ecf77c5ebb8c636d0d06e2d`, wheel SHA-256 `7c4c6bb481316c95e13c5518089f90c71664ca7387c09eb1ae0f94219fe267b8`, with the separately pinned dev2 native executable. The later Commerce and SpicyRegs metadata captures use their recorded dev5 catalog builders. A metadata refresh or newer shared checkout does not expand the reader's native qualification. Exact current and historical identities are linked from the local handoff.

Official APIs checked on 2026-11-06: [Astro React integration](https://docs.astro.build/en/guides/integrations-guide/react/), [Astro Node adapter](https://docs.astro.build/en/guides/integrations-guide/node/), [server endpoints](https://docs.astro.build/en/guides/endpoints/), [React effect cleanup](https://react.dev/reference/react/useEffect), and [WAI tab keyboard behavior](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/). Astro 7.4.7 and a project-local Node 22.23.4 are pinned. The project-local runtime allows patched dependencies without changing host tools.
