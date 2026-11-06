import { useEffect, useRef, useState } from 'react';
import type { CatalogSnapshot, CatalogSummary } from '../domain/types';
import { request } from '../lib/client';
import {
  downloadJson,
  selectedVersion,
  shortId,
  titleOf,
  versionsOf,
  releaseFor,
} from '../lib/display';
import { datasetRecordAccess, enumLabel } from '../lib/content';
import { Badge, Notice, Raw } from './Primitives';
import { Overview, Evidence, Activity, Compare } from './MetadataPanels';
import { DataPanel } from './DataPanel';
import { Connections } from './Connections';

const tabs = ['Overview', 'Data', 'Connections', 'Evidence', 'Activity', 'Compare'] as const;
type Tab = (typeof tabs)[number];
const tabLabels: Record<Tab, string> = {
  Overview: 'Overview',
  Data: 'View data',
  Connections: 'Related data',
  Evidence: 'Checks & sources',
  Activity: 'History',
  Compare: 'Compare versions',
};
type Route = {
  catalog: string;
  dataset: string;
  version: string;
  tab: Tab;
  digest: string;
  search: string;
  release: string;
};
function routeFromUrl(): Route {
  const q = new URLSearchParams(window.location.search),
    tab = q.get('tab');
  return {
    catalog: q.get('catalog') || '',
    dataset: q.get('dataset') || '',
    version: q.get('version') || '',
    tab: tabs.includes(tab as Tab) ? (tab as Tab) : 'Overview',
    digest: q.get('snapshot') || '',
    search: q.get('q') || '',
    release: q.get('release') || '',
  };
}
export default function Workspace() {
  const [route, setRoute] = useState<Route>(routeFromUrl);
  const [catalogs, setCatalogs] = useState<CatalogSummary[]>([]);
  const [snapshot, setSnapshot] = useState<CatalogSnapshot>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [sourceFilter, setSourceFilter] = useState('');
  const [announcement, setAnnouncement] = useState('');
  const [availability, setAvailability] = useState('all');
  const [limit, setLimit] = useState(40);
  const [unavailable, setUnavailable] = useState<{ id: string; reason: string }[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [catalogError, setCatalogError] = useState('');
  const titleRef = useRef<HTMLHeadingElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  function navigate(change: Partial<Route>, replace = false) {
    setRoute((old) => {
      const next = { ...old, ...change };
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries({
        catalog: next.catalog,
        dataset: next.dataset,
        version: next.version,
        tab: next.tab,
        snapshot: next.digest,
        q: next.search,
        release: next.release,
      })) {
        if (v) q.set(k, v);
      }
      window.history[replace ? 'replaceState' : 'pushState']({}, '', `?${q}`);
      return next;
    });
  }
  useEffect(() => {
    const listener = () => {
      setRoute(routeFromUrl());
      setExportOpen(false);
    };
    window.addEventListener('popstate', listener);
    return () => window.removeEventListener('popstate', listener);
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    request<{ catalogs: CatalogSummary[]; unavailable?: { id: string; reason: string }[] }>(
      '/api/catalogs',
      abort.signal,
    )
      .then((r) => {
        setCatalogs(r.catalogs);
        setUnavailable(r.unavailable ?? []);
        setCatalogError('');
        if (!route.catalog && r.catalogs[0]) navigate({ catalog: r.catalogs[0].id }, true);
      })
      .catch((e) => {
        if (!abort.signal.aborted) {
          setCatalogError(e.message);
          setLoading(false);
        }
      });
    return () => abort.abort();
  }, [retry]);
  useEffect(() => {
    if (!route.catalog) return;
    const abort = new AbortController();
    setLoading(true);
    setError('');
    setSnapshot(undefined);
    setExportOpen(false);
    setAvailability('all');
    setSourceFilter('');
    setLimit(40);
    request<CatalogSnapshot>(`/api/catalogs/${encodeURIComponent(route.catalog)}`, abort.signal)
      .then((s) => {
        if (abort.signal.aborted) return;
        if (route.digest && route.digest !== s.identity.catalogSha256)
          throw new Error(
            'This link refers to a different catalog copy. Opening the available copy may show different data.',
          );
        s.definitions =
          (
            s.catalog.extensions?.['urn:ddk:catalog:assembly'] as
              { datasetDefinitions?: CatalogSnapshot['definitions'] } | undefined
          )?.datasetDefinitions ?? {};
        setSnapshot(s);
        if (!route.digest) navigate({ digest: s.identity.catalogSha256 }, true);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [route.catalog, retry]);
  const dataset =
    snapshot?.catalog.datasets.find((d) => d.id === route.dataset || d.alias === route.dataset) ??
    (!route.dataset ? snapshot?.catalog.datasets[0] : undefined);
  const versions = snapshot && dataset ? versionsOf(snapshot, dataset) : [];
  const version =
    versions.find((v) => v.id === route.version) ||
    (!route.version && snapshot && dataset ? selectedVersion(snapshot, dataset) : undefined);
  const exactLinkMismatch =
    !!snapshot && !!route.digest && route.digest !== snapshot.identity.catalogSha256;
  const boundRelease =
    route.release || (snapshot ? releaseFor(snapshot, version?.id)?.id : undefined);
  const invalidVersion = !!route.version && !version;
  const search = route.search.toLocaleLowerCase();
  const datasets =
    snapshot?.catalog.datasets.filter((d) => {
      const definition = snapshot.definitions[d.alias];
      const sourceIds = snapshot.catalog.versions
        .filter((v) => v.dataset === d.alias || v.dataset === d.id)
        .flatMap((v) => v.sources);
      const matches = [d.alias, d.id, d.title, d.rowMeaning, definition?.description]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase()
        .includes(search);
      const recordState = datasetRecordAccess(snapshot, d).state;
      return (
        matches &&
        (!sourceFilter || sourceIds.includes(sourceFilter)) &&
        (availability === 'all' ||
          (availability === 'available'
            ? recordState === 'available'
            : availability === 'unknown'
              ? recordState === 'unknown'
              : recordState !== 'available' && recordState !== 'unknown'))
      );
    }) ?? [];
  const titleCounts = new Map<string, number>();
  for (const item of snapshot?.catalog.datasets ?? []) {
    const title = titleOf(item);
    titleCounts.set(title, (titleCounts.get(title) ?? 0) + 1);
  }
  const description =
    snapshot && dataset ? snapshot.definitions[dataset.alias]?.description : undefined;
  const coverageStart = description?.indexOf('Coverage limits:') ?? -1;
  const nullabilityStart = description?.indexOf('Nullability basis:') ?? -1;
  const technicalDescription =
    coverageStart >= 0 && nullabilityStart > coverageStart;
  const coverageNote =
    technicalDescription && description
      ? description
          .slice(coverageStart + 'Coverage limits:'.length, nullabilityStart)
          .trim()
      : undefined;
  const summary =
    technicalDescription
      ? description?.slice(0, coverageStart).trim() || undefined
      : description !== dataset?.rowMeaning ? description : undefined;
  const exampleDataset =
    !!snapshot?.exampleData ||
    snapshot?.mode === 'fixture' ||
    (['Future reader fixture', 'Future reader example (fixture)'].includes(dataset?.title ?? '') &&
      dataset?.rowMeaning === 'One future fixture row');
  useEffect(() => {
    document.title =
      dataset && snapshot
        ? `${titleOf(dataset)} · ${snapshot.title} · DDK`
        : snapshot
          ? `${snapshot.title} · DDK`
          : 'Data catalog · DDK';
  }, [dataset, snapshot]);
  function chooseDataset(id: string, versionId?: string, releaseId?: string) {
    navigate({ dataset: id, version: versionId || '', release: releaseId || '', tab: 'Overview' });
    setExportOpen(false);
    setTimeout(() => titleRef.current?.focus(), 0);
  }
  function switchTab(tab: Tab) {
    navigate({ tab });
    setExportOpen(false);
  }
  function exactReference() {
    if (!snapshot || !dataset) return;
    downloadJson('ddk-exact-reference.json', {
      format: 'ddk-viewer-reference/1',
      catalogId: snapshot.catalog.id,
      catalogIdentity: snapshot.identity,
      audience: snapshot.audience,
      datasetId: dataset.id,
      definition: dataset.definition,
      version: version ?? null,
      release: boundRelease ?? null,
      selection: snapshot.catalog.selections,
      qualification: {
        catalogDecision: snapshot.report.decision,
        versionChecks: snapshot.catalog.checks.filter((c) => c.subject === version?.id),
        nativeAcceptance: 'not established',
      },
      link: window.location.href,
    });
    setAnnouncement('Dataset reference downloaded.');
  }
  async function copyLink() {
    try {
      const link = new URL(window.location.href);
      if (dataset) link.searchParams.set('dataset', dataset.id);
      if (version) link.searchParams.set('version', version.id);
      else link.searchParams.delete('version');
      await navigator.clipboard.writeText(link.href);
      setAnnouncement(version ? 'Dataset and version link copied.' : 'Dataset link copied.');
    } catch {
      setAnnouncement('Clipboard access is unavailable. Copy the address from your browser.');
    }
  }
  return (
    <>
      <a className="skip-link" href="#workspace">
        Skip to dataset
      </a>
      <header className="app-header">
        <a className="brand" href="/" aria-label="Data catalog home">
          <span className="brand-mark">
            <svg aria-hidden="true" width="35" height="28" viewBox="0 0 40 28">
              <path
                d="M11 3v20H7a6 6 0 1 1 4-10M25 3v20h-4a6 6 0 1 1 4-10M31 3v20m0-7 7-7m-7 7 7 7"
                fill="none"
                stroke="currentColor"
                strokeWidth="3.5"
              />
            </svg>
          </span>
          <span>Data catalog</span>
        </a>
        <div className="header-context">
          <span className="header-dot" aria-hidden="true" />
          <span>Local preview</span>
          <span className="header-divider" />
          <span>Data Design Kit</span>
        </div>
      </header>
      <div className="app-layout">
        <aside className="sidebar" aria-label="Dataset discovery">
          <div className="sidebar-top">
            <p className="eyebrow">Explore data</p>
            <label className="eyebrow" htmlFor="catalog-choice">
              Catalog
            </label>
            <select
              id="catalog-choice"
              value={route.catalog}
              onChange={(e) =>
                navigate({
                  catalog: e.target.value,
                  dataset: '',
                  version: '',
                  digest: '',
                  release: '',
                  search: '',
                  tab: 'Overview',
                })
              }
            >
              {catalogs.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
            <p className="catalog-description">
              {snapshot?.description ||
                'Find datasets, understand what they contain, and see how you can use them.'}{' '}
              A dataset is a collection of related records.
            </p>
            {snapshot && (
              <details>
                <summary>About this catalog</summary>
                <p>{snapshot.description}</p>
                {snapshot.capabilities.description && <p>{snapshot.capabilities.description}</p>}
              </details>
            )}
            {snapshot && (
              <Badge status="unknown">
                {snapshot.mode === 'fixture'
                  ? 'Example catalog · synthetic records'
                  : snapshot.exampleData === 'authored'
                    ? 'Example catalog'
                    : 'Application catalog'}
              </Badge>
            )}
          </div>
          <div className="discovery-tools">
            <label className="sr-only" htmlFor="dataset-search">
              Search this catalog
            </label>
            <div className="search-wrap">
              <span aria-hidden="true">⌕</span>
              <input
                id="dataset-search"
                ref={searchRef}
                type="search"
                placeholder="Search this catalog…"
                aria-describedby="dataset-search-help"
                value={route.search}
                onChange={(e) => {
                  navigate({ search: e.target.value }, true);
                  setLimit(40);
                }}
              />
            </div>
            <p id="dataset-search-help" className="muted">
              Search dataset titles, descriptions and identifiers.
            </p>
            <label className="filter-label">
              Can I view records here?
              <select
                value={availability}
                onChange={(e) => {
                  setAvailability(e.target.value);
                  setLimit(40);
                }}
              >
                <option value="all">All datasets</option>
                <option value="available">Records connected here</option>
                <option value="unavailable">Records not available here</option>
                <option value="unknown">Record availability unknown</option>
              </select>
            </label>
            {!!snapshot?.catalog.sources.length && (
              <label className="filter-label source-filter">
                Source capture
                <select
                  value={sourceFilter}
                  aria-describedby="source-capture-help"
                  onChange={(e) => {
                    setSourceFilter(e.target.value);
                    setLimit(40);
                  }}
                >
                  <option value="">All source captures</option>
                  {snapshot.catalog.sources.map((s) => (
                    <option value={s.id} key={s.id}>
                      {s.scope || s.id} · {enumLabel(s.outcome)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {!!snapshot?.catalog.sources.length && (
              <details className="source-capture-help">
                <summary>About source captures</summary>
                <p id="source-capture-help" className="muted">
                  A source capture is a recorded retrieval or observation of a source. The
                  publisher’s recorded scope labels each capture; exact identifiers are in Checks &
                  sources.
                </p>
              </details>
            )}
          </div>
          {unavailable.length > 0 && (
            <div className="source-errors">
              <details>
                <summary>
                  {unavailable.length} catalog {unavailable.length === 1 ? 'source' : 'sources'}{' '}
                  unavailable
                </summary>
                {unavailable.map((c) => (
                  <p key={c.id}>
                    {c.id}: {c.reason}
                  </p>
                ))}
                <button onClick={() => setRetry((v) => v + 1)}>Retry sources</button>
              </details>
            </div>
          )}
          <div className="nav-label">
            <span>Datasets</span>
            <span aria-live="polite">{datasets.length}</span>
          </div>
          <nav className="dataset-nav" aria-label="Datasets">
            {(error || catalogError) && (
              <div className="nav-empty">
                <p>Dataset list could not be loaded.</p>
              </div>
            )}
            {datasets.slice(0, limit).map((d) => (
              <button
                key={d.id}
                className={d.id === dataset?.id ? 'active' : ''}
                aria-current={d.id === dataset?.id ? 'page' : undefined}
                onClick={() => chooseDataset(d.id)}
              >
                <span className="dataset-symbol" aria-hidden="true">
                  ▤
                </span>
                <span>
                  <strong>{titleOf(d)}</strong>
                  <small>
                    {(titleCounts.get(titleOf(d)) ?? 0) > 1
                      ? d.alias
                      : enumLabel(d.role || 'Dataset')}{' '}
                    · {d.definition.version}
                  </small>
                </span>
                <span className="dataset-arrow" aria-hidden="true">
                  ›
                </span>
              </button>
            ))}
            {!datasets.length && !loading && !error && !catalogError && !!snapshot && (
              <div className="nav-empty">
                <p>No datasets match these filters.</p>
                <button
                  onClick={() => {
                    navigate({ search: '' }, true);
                    setAvailability('all');
                    setSourceFilter('');
                  }}
                >
                  Clear filters
                </button>
              </div>
            )}
            {datasets.length > limit && (
              <button className="load-more" onClick={() => setLimit((n) => n + 40)}>
                Show {Math.min(40, datasets.length - limit)} more{' '}
                {datasets.length - limit === 1 ? 'dataset' : 'datasets'}
              </button>
            )}
          </nav>
          <footer className="sidebar-footer">
            <span className="mini-mark" aria-hidden="true">
              ◇
            </span>
            <div>
              <strong>Catalog & evidence</strong>
              <span>References stay with each dataset and result.</span>
            </div>
          </footer>
        </aside>
        <main id="workspace" tabIndex={-1} className="workspace">
          {catalogError && (
            <Notice
              title="Catalog list unavailable"
              kind="error"
              action={<button onClick={() => setRetry((v) => v + 1)}>Retry</button>}
            >
              {catalogError}
            </Notice>
          )}
          {loading ? (
            <div className="loading-state" role="status">
              <span className="loading-line" />
              Opening the catalog…
            </div>
          ) : error || exactLinkMismatch ? (
            <Notice
              title="Catalog could not be opened"
              kind="error"
              action={<button onClick={() => setRetry((v) => v + 1)}>Retry catalog</button>}
            >
              {error ||
                'This link refers to a different catalog copy. Opening the available copy may show different data.'}
              {route.digest && (
                <div>
                  <button
                    onClick={() => {
                      navigate({ digest: '', dataset: '', version: '' });
                      setRetry((v) => v + 1);
                    }}
                  >
                    Open the catalog available here
                  </button>
                </div>
              )}
            </Notice>
          ) : snapshot && dataset ? (
            <>
              <div className="breadcrumb">
                <span>{snapshot.title}</span>
                <span aria-hidden="true">/</span>
                <span>Datasets</span>
              </div>
              <div className="dataset-heading">
                <div>
                  <p className="eyebrow" title={dataset.role}>
                    {enumLabel(dataset.role || 'Dataset')}
                  </p>
                  <h1 ref={titleRef} tabIndex={-1}>
                    {titleOf(dataset)}
                  </h1>
                  {summary && <p className="dataset-subtitle">{summary}</p>}
                  {exampleDataset && (
                    <Badge status="unknown">
                      {snapshot.mode === 'fixture'
                        ? 'Example dataset · synthetic records'
                        : snapshot.exampleData === 'authored'
                          ? 'Example dataset · saved example records'
                          : 'Example dataset · not live archive data'}
                    </Badge>
                  )}
                  {coverageNote && (
                    <p className="dataset-subtitle">
                      <strong>Coverage and important limits: </strong>
                      {coverageNote}
                    </p>
                  )}
                  {technicalDescription && (
                    <details>
                      <summary>Technical definition notes</summary>
                      <p className="dataset-subtitle">{description}</p>
                    </details>
                  )}
                  <details>
                    <summary>Dataset identifiers</summary>
                    <p>
                      Definition alias: <code>{dataset.alias}</code>
                    </p>
                    {dataset.title && dataset.title !== titleOf(dataset) && (
                      <p>
                        Supplied title: <code>{dataset.title}</code>
                      </p>
                    )}
                    <p>
                      Dataset identifier: <code>{dataset.id}</code>
                    </p>
                    <p>
                      Role: <code>{dataset.role ?? 'Not recorded'}</code>
                    </p>
                  </details>
                </div>
                <div className="share-control">
                  <button
                    className="button secondary"
                    onClick={() => setExportOpen((v) => !v)}
                    aria-expanded={exportOpen}
                  >
                    Share & export <span aria-hidden="true">↗</span>
                  </button>
                  {exportOpen && (
                    <div className="share-panel">
                      <button onClick={copyLink}>
                        {version ? 'Copy link to this dataset and version' : 'Copy dataset link'}
                      </button>
                      <button onClick={exactReference}>Download dataset reference (JSON)</button>
                      <p>
                        Includes identifiers for the catalog
                        {version ? ' and selected version' : ' and dataset'}. It does not contain
                        data records. JSON is a structured data-file format.
                      </p>
                      <p>Download records and query results from their views.</p>
                    </div>
                  )}
                </div>
              </div>
              <div className="context-bar">
                <label htmlFor="version-choice">
                  Data version
                  <select
                    id="version-choice"
                    value={version?.id || ''}
                    onChange={(e) => navigate({ version: e.target.value, release: '' })}
                  >
                    <option value="">
                      {versions.length ? 'Choose a data version' : 'No data versions listed'}
                    </option>
                    {versions.map((v) => (
                      <option value={v.id} key={v.id}>
                        {shortId(v.id)}
                        {selectedVersion(snapshot, dataset)?.id === v.id
                          ? ' · publisher selected'
                          : ''}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="snapshot-context">
                  <span>Catalog copy</span>
                  <code title={snapshot.identity.catalogSha256}>
                    {snapshot.identity.catalogSha256.slice(0, 12)}
                  </code>
                  <span className="audience">{snapshot.audience}</span>
                </div>
              </div>
              {invalidVersion && (
                <Notice title="The linked version is unavailable" kind="error">
                  This version is not listed in this catalog.{' '}
                  {versions.length
                    ? 'Choose a listed version.'
                    : 'No data versions are listed here.'}
                </Notice>
              )}
              <div className="tablist" role="tablist" aria-label="Dataset views">
                {tabs.map((tab, i) => (
                  <button
                    id={`tab-${tab}`}
                    role="tab"
                    aria-selected={route.tab === tab}
                    aria-controls={`panel-${tab}`}
                    tabIndex={route.tab === tab ? 0 : -1}
                    key={tab}
                    onClick={() => switchTab(tab)}
                    onKeyDown={(e) => {
                      let n = i;
                      if (e.key === 'ArrowRight') n = (i + 1) % tabs.length;
                      else if (e.key === 'ArrowLeft') n = (i + tabs.length - 1) % tabs.length;
                      else if (e.key === 'Home') n = 0;
                      else if (e.key === 'End') n = tabs.length - 1;
                      else return;
                      e.preventDefault();
                      document.getElementById(`tab-${tabs[n]}`)?.focus();
                    }}
                  >
                    {tabLabels[tab]}
                    {tab === 'Data' && version && (
                      <span className="tab-indicator" aria-hidden="true" />
                    )}
                  </button>
                ))}
              </div>
              <div
                role="tabpanel"
                tabIndex={0}
                aria-labelledby={`tab-${route.tab}`}
                id={`panel-${route.tab}`}
                className="tab-content"
                key={`${snapshot.identity.catalogSha256}:${dataset.id}:${version?.id}:${route.tab}`}
              >
                {route.tab === 'Overview' && (
                  <Overview snapshot={snapshot} dataset={dataset} version={version} />
                )}
                {route.tab === 'Data' && (
                  <DataPanel
                    snapshot={snapshot}
                    dataset={dataset}
                    version={version}
                    releaseId={boundRelease}
                  />
                )}
                {route.tab === 'Connections' && (
                  <Connections
                    snapshot={snapshot}
                    dataset={dataset}
                    version={version}
                    releaseId={boundRelease}
                    onNavigate={chooseDataset}
                  />
                )}
                {route.tab === 'Evidence' && (
                  <Evidence snapshot={snapshot} dataset={dataset} version={version} />
                )}
                {route.tab === 'Activity' && (
                  <Activity snapshot={snapshot} dataset={dataset} version={version} />
                )}
                {route.tab === 'Compare' && (
                  <Compare snapshot={snapshot} dataset={dataset} version={version} />
                )}
              </div>
              <footer className="workspace-footer">
                <span>
                  {snapshot.mode === 'fixture'
                    ? 'Synthetic examples · no production data'
                    : 'Application field definitions and recorded evidence'}
                </span>
                <details>
                  <summary>Catalog copy identifiers</summary>
                  <Raw
                    value={{
                      identity: snapshot.identity,
                      project: snapshot.catalog.project,
                      tools: snapshot.lock.tools,
                    }}
                    label="Exact catalog and tool identities"
                  />
                </details>
              </footer>
            </>
          ) : snapshot ? (
            <Notice title="Dataset unavailable">
              {route.dataset
                ? 'The dataset in this link is not disclosed by this catalog. Choose a dataset from the list.'
                : 'This catalog contains no datasets.'}
            </Notice>
          ) : null}
        </main>
      </div>
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
    </>
  );
}
