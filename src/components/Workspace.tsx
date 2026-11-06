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
import { Badge, Notice, Raw } from './Primitives';
import { Overview, Evidence, Activity, Compare } from './MetadataPanels';
import { DataPanel } from './DataPanel';
import { Connections } from './Connections';

const tabs = ['Overview', 'Data', 'Connections', 'Evidence', 'Activity', 'Compare'] as const;
type Tab = (typeof tabs)[number];
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
            'The shared link names a different catalog snapshot. The server has not supplied those exact bytes. Open this catalog explicitly to choose its configured snapshot.',
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
      const sourceText = snapshot.catalog.sources
        .filter((s) => sourceIds.includes(s.id))
        .map((s) => `${s.id} ${s.scope} ${s.outcome}`)
        .join(' ');
      const matches = [
        d.alias,
        d.id,
        d.title,
        d.rowMeaning,
        definition?.description,
        snapshot.catalog.project.id,
        sourceText,
      ]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase()
        .includes(search);
      const readable = snapshot.catalog.versions.some(
        (v) =>
          (v.dataset === d.id || v.dataset === d.alias) &&
          snapshot.catalog.representations.some(
            (r) => r.version === v.id && r.availability === 'available',
          ),
      );
      return (
        matches &&
        (!sourceFilter || sourceIds.includes(sourceFilter)) &&
        (availability === 'all' || (availability === 'available' ? readable : !readable))
      );
    }) ?? [];
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
    setAnnouncement('Exact reference downloaded.');
  }
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setAnnouncement('Dataset and version link copied.');
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
        <a className="brand" href="/" aria-label="Data workspace home">
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
          <span>Data workspace</span>
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
              {snapshot?.capabilities.description ||
                snapshot?.description ||
                'Standard catalogs, exact data, and evidence.'}
            </p>
            {snapshot && (
              <Badge status="unknown">
                {snapshot.mode === 'fixture' ? 'Demonstration catalog' : 'Application catalog'}
              </Badge>
            )}
          </div>
          <div className="discovery-tools">
            <label className="sr-only" htmlFor="dataset-search">
              Find a dataset
            </label>
            <div className="search-wrap">
              <span aria-hidden="true">⌕</span>
              <input
                id="dataset-search"
                ref={searchRef}
                type="search"
                placeholder="Find a dataset…"
                value={route.search}
                onChange={(e) => {
                  navigate({ search: e.target.value }, true);
                  setLimit(40);
                }}
              />
            </div>
            <label className="filter-label">
              Availability
              <select
                value={availability}
                onChange={(e) => {
                  setAvailability(e.target.value);
                  setLimit(40);
                }}
              >
                <option value="all">All datasets</option>
                <option value="available">Available representation</option>
                <option value="unavailable">No available representation</option>
              </select>
            </label>
            {!!snapshot?.catalog.sources.length && (
              <label className="filter-label source-filter">
                Source occurrence
                <select
                  value={sourceFilter}
                  onChange={(e) => {
                    setSourceFilter(e.target.value);
                    setLimit(40);
                  }}
                >
                  <option value="">All sources</option>
                  {snapshot.catalog.sources.map((s) => (
                    <option value={s.id} key={s.id}>
                      {shortId(s.id)} · {s.outcome}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {unavailable.length > 0 && (
            <div className="source-errors">
              <details>
                <summary>{unavailable.length} catalog source unavailable</summary>
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
                    {d.role || 'Dataset'} · {d.definition.version}
                  </small>
                </span>
                <span className="dataset-arrow" aria-hidden="true">
                  ›
                </span>
              </button>
            ))}
            {!datasets.length && !loading && (
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
                Show 40 more datasets
              </button>
            )}
          </nav>
          <footer className="sidebar-footer">
            <span className="mini-mark" aria-hidden="true">
              ◇
            </span>
            <div>
              <strong>Catalog & evidence</strong>
              <span>
                Exact references stay with
                <br />
                each dataset and result.
              </span>
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
              Loading the catalog and its evidence…
            </div>
          ) : error || exactLinkMismatch ? (
            <Notice
              title="Catalog could not be opened"
              kind="error"
              action={<button onClick={() => setRetry((v) => v + 1)}>Retry catalog</button>}
            >
              {error ||
                'The workspace link names different catalog bytes. Open the configured snapshot explicitly to continue.'}
              {route.digest && (
                <div>
                  <button
                    onClick={() => {
                      navigate({ digest: '', dataset: '', version: '' });
                      setRetry((v) => v + 1);
                    }}
                  >
                    Open the configured snapshot
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
                  <p className="eyebrow">{dataset.role || 'Dataset'}</p>
                  <h1 ref={titleRef} tabIndex={-1}>
                    {titleOf(dataset)}
                  </h1>
                  <p className="dataset-subtitle">
                    {snapshot.definitions[dataset.alias]?.description ||
                      dataset.rowMeaning ||
                      'Explore the admitted definition and available evidence.'}
                  </p>
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
                      <button onClick={copyLink}>Copy dataset & version link</button>
                      <button onClick={exactReference}>Download exact reference</button>
                      <p>Page data and query results export from their working views.</p>
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
                      {versions.length ? 'Choose an exact version' : 'No observed data versions'}
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
                  <span>Catalog snapshot</span>
                  <code title={snapshot.identity.catalogSha256}>
                    {snapshot.identity.catalogSha256.slice(0, 12)}
                  </code>
                  <span className="audience">{snapshot.audience}</span>
                </div>
              </div>
              {invalidVersion && (
                <Notice title="The linked version is unavailable" kind="error">
                  This exact version is not present in the configured catalog. Choose an available
                  version explicitly.
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
                    {tab}
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
                    : 'Admitted application definitions · owner evidence retained'}
                </span>
                <details>
                  <summary>Snapshot identity</summary>
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
                : 'This admitted catalog contains no datasets.'}
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
