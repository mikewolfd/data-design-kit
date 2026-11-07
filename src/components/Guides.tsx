import type { CatalogSnapshot } from '../domain/types';
import { publisherMetadata, type PublisherLink } from '../features/publisher-metadata';
import { Notice, RecordLink, Section } from './Primitives';

export function guideHref(snapshot: CatalogSnapshot, target: PublisherLink['target']): string {
  if (target.kind === 'external') return target.url;
  const query = new URLSearchParams({
    catalog: snapshot.id,
    snapshot: snapshot.identity.catalogSha256,
  });
  if (target.kind === 'recipe') {
    const recipe = snapshot.catalog.recipes.find((item) => item.id === target.recipeId)!;
    const dataset = [recipe.resultDataset, ...Object.values(recipe.inputs)]
      .map((alias) =>
        snapshot.catalog.datasets.find((item) => item.id === alias || item.alias === alias),
      )
      .find(Boolean);
    if (dataset) query.set('dataset', dataset.id);
    query.set('tab', 'Connections');
    query.set('recipe', recipe.id);
  } else {
    query.set('dataset', target.datasetId);
    if (target.kind !== 'dataset') query.set('version', target.versionId);
    if (target.kind === 'representation') {
      query.set('resource', target.representationId);
      query.set('tab', 'Data');
    } else query.set('tab', 'Overview');
  }
  return `?${query}`;
}

export function Guides({ snapshot, guideId }: { snapshot: CatalogSnapshot; guideId?: string }) {
  const guides = publisherMetadata(snapshot).guides;
  useEffect(() => {
    if (guideId) document.getElementById(`guide-title-${guideId}`)?.focus();
  }, [guideId]);
  return (
    <Section title="Guides for using this catalog">
      <p>
        Publisher-authored guidance connects a question to the relevant datasets. A guide is
        explanatory content; opening it does not read or join records.
      </p>
      {!guides.length && (
        <Notice title="No publisher guide is supplied for this catalog">
          Explore the dataset descriptions, fields and Related data to see the information available
          here.
        </Notice>
      )}
      {guideId && !guides.some((guide) => guide.id === guideId) && (
        <Notice title="The linked guide is not supplied in this catalog copy">
          Choose an available guide or return to the dataset descriptions.
        </Notice>
      )}
      {guides.map((guide) => (
        <article className="catalog-guide" id={guide.id} key={guide.id}>
          <p className="eyebrow">
            Publisher guidance
            {snapshot.mode === 'fixture' || snapshot.exampleData ? ' · Example data' : ''}
          </p>
          <h3 id={`guide-title-${guide.id}`} tabIndex={-1}>
            {guide.title}
          </h3>
          <p>
            <strong>{guide.question}</strong>
          </p>
          <p>{guide.summary}</p>
          <p className="muted">
            Written by{' '}
            {guide.author.url ? (
              <a href={guide.author.url} target="_blank" rel="noreferrer">
                {guide.author.name} (external)
              </a>
            ) : (
              guide.author.name
            )}{' '}
            · Reviewed {guide.reviewedOn}
          </p>
          <p className="muted">
            <strong>When to review this guide: </strong>
            {guide.reviewTrigger || 'The publisher has not supplied a review trigger.'}
          </p>
          {guide.coverage && (
            <dl className="guide-scope">
              {Object.entries(guide.coverage).map(([key, value]) => (
                <div key={key}>
                  <dt>{key === 'period' ? 'Data period' : key}</dt>
                  <dd>
                    {typeof value === 'string'
                      ? value
                      : `${value.start ?? 'Start not supplied'} to ${value.end ?? 'End not supplied'}`}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          <ol className="guide-links">
            {guide.links.map((link, index) => (
              <li key={index}>
                <a
                  href={guideHref(snapshot, link.target)}
                  {...(link.target.kind === 'external'
                    ? { target: '_blank', rel: 'noreferrer' }
                    : {})}
                >
                  {link.label}
                  {link.target.kind === 'external' ? ' (external)' : ''}
                </a>
                <p>{link.purpose}</p>
                <span className="muted">
                  {link.target.kind === 'external'
                    ? `Destination: ${new URL(link.target.url).hostname}`
                    : link.target.kind === 'recipe'
                      ? 'Opens saved query details; execution requires its listed inputs.'
                      : link.target.kind === 'representation'
                        ? 'Opens the resource’s access options. Choose Open records to request a bounded page.'
                        : 'Opens the dataset description.'}
                </span>
              </li>
            ))}
          </ol>
          <details>
            <summary>Sources for this guide</summary>
            {guide.evidence.map((evidence, index) => (
              <p key={index}>
                {evidence.url ? (
                  <a href={evidence.url} target="_blank" rel="noreferrer">
                    {evidence.label} (external)
                  </a>
                ) : (
                  <>
                    {evidence.label}: <RecordLink record={evidence.record} />
                  </>
                )}
                {evidence.sourceVersion && <> · Source version: {evidence.sourceVersion}</>}
              </p>
            ))}
            <code>{guide.id}</code>
          </details>
        </article>
      ))}
    </Section>
  );
}
import { useEffect } from 'react';
