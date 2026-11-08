import { useState } from 'react';
import { exactStringify } from '../../domain/exact';
import type { CatalogField, FieldPath } from '../../domain/types';
import { safeLink } from '../../lib/display';
import { declaredCodes } from './field-metadata';

export type DocumentedFieldValues = {
  path: FieldPath;
  domain: string;
  locator: string;
  sourceUrl: string;
  checked: boolean;
  values: { value: string; label?: string }[];
  observedAt?: string;
  observedOffList?: { value: string; reason: string }[];
  unobserved?: string[];
  caveat?: string;
};

const valueListLimit = 50;

function ValueList({
  title,
  entries,
}: {
  title: string;
  entries: { value: unknown; label?: string; description?: string }[];
}) {
  if (!entries.length) return null;
  return (
    <>
      <p>
        <strong>{title}</strong>
      </p>
      <ul>
        {entries.slice(0, valueListLimit).map(({ value, label, description }, index) => (
          <li key={index}>
            <code>{exactStringify(value, 0)}</code>
            {label && <> · {label}</>}
            {description && <p>{description}</p>}
          </li>
        ))}
      </ul>
      {entries.length > valueListLimit && (
        <p>First 50 values shown. See the source for the full list.</p>
      )}
    </>
  );
}

export function PublisherValues({ documentation }: { documentation: DocumentedFieldValues }) {
  const { sourceUrl, locator, domain, checked, observedAt, caveat, values } = documentation;
  const href = safeLink(sourceUrl);
  return (
    <div className="field-publisher-values">
      <ValueList title={`Publisher reference values for ${domain}`} entries={values} />
      <p>Other values may occur.</p>
      {caveat && <p>{caveat}</p>}
      <dl>
        <div>
          <dt>Source documentation</dt>
          <dd>{href ? <a href={href}>{sourceUrl}</a> : <code>{sourceUrl}</code>}</dd>
        </div>
        <div>
          <dt>Where to look</dt>
          <dd>{locator}</dd>
        </div>
        <div>
          <dt>Publisher marked as checked</dt>
          <dd>{checked ? 'Yes' : 'No'}</dd>
        </div>
        {observedAt && (
          <div>
            <dt>Observation date</dt>
            <dd>{observedAt}</dd>
          </div>
        )}
      </dl>
      <ValueList
        title="Observed outside this reference list"
        entries={(documentation.observedOffList ?? []).map(({ value, reason }) => ({
          value,
          description: reason,
        }))}
      />
      <ValueList
        title="Reference values the publisher marked as unobserved"
        entries={(documentation.unobserved ?? []).map((value) => ({ value }))}
      />
    </div>
  );
}

export function FieldValues({
  field,
  address,
  documentedValues,
}: {
  field: CatalogField;
  address: string;
  documentedValues: readonly DocumentedFieldValues[];
}) {
  const codes = declaredCodes(field);
  const examples = Array.isArray(field.examples) ? field.examples : [];
  const [open, setOpen] = useState(false);
  if (!codes.length && !examples.length && !documentedValues.length) return null;
  const title = documentedValues.length
    ? 'Publisher reference values'
    : 'Values documented for this field';
  return (
    <details className="field-values" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary aria-label={`${title} for ${address}`}>{title}</summary>
      {open && (
        <>
          <ValueList title="Allowed values in this definition" entries={codes} />
          <ValueList title="Examples of values" entries={examples.map((value) => ({ value }))} />
          {documentedValues.map((documentation, index) => (
            <PublisherValues key={index} documentation={documentation} />
          ))}
        </>
      )}
    </details>
  );
}
