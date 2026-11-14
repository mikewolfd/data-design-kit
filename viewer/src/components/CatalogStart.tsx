import { useState } from 'react';
import type { CatalogSnapshot } from '../domain/types';
import { publisherMetadata } from '../features/publisher-metadata';
import { WorkflowQuery } from './WorkflowQuery';

export function CatalogStart({
  snapshot,
  active,
  search,
  onGuide,
}: {
  snapshot: CatalogSnapshot;
  active: boolean;
  search: string;
  onGuide: (id: string) => void;
}) {
  const metadata = publisherMetadata(snapshot);
  const [selected, setSelected] = useState(metadata.workflows[0]?.id);
  const [visited, setVisited] = useState([selected]);
  const [seeds, setSeeds] = useState<Record<string, string>>({});
  const [evicted, setEvicted] = useState(false);
  const workflow = metadata.workflows.find(({ id }) => id === selected);
  const recipe = snapshot.catalog.recipes.find(({ id }) => id === workflow?.recipeId);
  const names = Object.keys(recipe?.parameters.properties ?? {});
  return (
    <div className="catalog-start">
      <p className="eyebrow">Explore this collection</p>
      <h1>Start with a question</h1>
      <p className="dataset-subtitle">
        Look up records, read their source context, and keep the answer as you explore.
      </p>
      <p className="coverage-note">{snapshot.description}</p>
      {metadata.workflows.length > 1 && (
        <div className="workflow-choices" aria-label="Supported record lookups">
          {metadata.workflows.map((item) => (
            <button
              key={item.id}
              aria-pressed={selected === item.id}
              onClick={() => {
                setSelected(item.id);
                setVisited((previous) => {
                  const others = previous.filter((id) => id !== item.id);
                  if (others.length >= 6) setEvicted(true);
                  return [...others.slice(-5), item.id];
                });
              }}
            >
              {item.title}
            </button>
          ))}
        </div>
      )}
      {search.trim() && names.length === 1 && (
        <p className="lookup-search-help">
          Catalog search matches dataset descriptions. To search records for this identifier,{' '}
          <button onClick={() => setSeeds((previous) => ({ ...previous, [selected]: search }))}>
            use “{search}” in this lookup
          </button>
          .
        </p>
      )}
      {evicted && (
        <p className="muted" role="status">
          The six most recent lookups are kept in this session. Older lookups reopen with their
          starting values.
        </p>
      )}
      {visited.map((id) => {
        const item = metadata.workflows.find((candidate) => candidate.id === id);
        if (!item) return null;
        const inputNames = Object.keys(
          snapshot.catalog.recipes.find((candidate) => candidate.id === item.recipeId)?.parameters
            .properties ?? {},
        );
        const seed = seeds[id];
        return (
          <div key={id} hidden={id !== selected} inert={id !== selected}>
            <WorkflowQuery
              key={`${id}:${seed ?? ''}`}
              snapshot={snapshot}
              workflow={item}
              active={active && id === selected}
              initialParameters={
                seed && inputNames.length === 1 ? { [inputNames[0]]: seed } : undefined
              }
            />
          </div>
        );
      })}
      {!!metadata.guides.length && (
        <details className="catalog-guidance">
          <summary>About this collection and its limits</summary>
          {metadata.guides.map((guide) => (
            <article key={guide.id}>
              <h3>{guide.title}</h3>
              <p>{guide.summary}</p>
              <button onClick={() => onGuide(guide.id)}>Read the collection guide</button>
            </article>
          ))}
        </details>
      )}
    </div>
  );
}
