import { useState, type ReactNode } from 'react';
import type { CatalogField, RecordRef, FieldPath } from '../domain/types';
import { textValue, pathLabel, safeLink } from '../lib/display';
import { enumLabel } from '../lib/content';
import { exactObjectEntries, exactStringify, isExactNumber } from '../domain/exact';

export function Badge({ status, children }: { status: string; children?: ReactNode }) {
  return (
    <span
      className={`badge ${['failed', 'refused', 'error'].includes(status) ? 'bad' : status === 'passed' || status === 'available' || status === 'ok' ? 'good' : 'neutral'}`}
    >
      <span aria-hidden="true" className="status-dot" />
      {children ?? enumLabel(status)}
    </span>
  );
}
export function Notice({
  title,
  children,
  kind = 'info',
  action,
}: {
  title: string;
  children?: ReactNode;
  kind?: string;
  action?: ReactNode;
}) {
  return (
    <div className={`notice ${kind}`} role={kind === 'error' ? 'alert' : undefined}>
      <div>
        <strong>{title}</strong>
        {children && <div className="notice-copy">{children}</div>}
      </div>
      {action}
    </div>
  );
}
export function Section({
  title,
  children,
  aside,
}: {
  title: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="section">
      <div className="section-heading">
        <h2>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}
export function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="facts">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Raw({ value, label = 'View exact record' }: { value: unknown; label?: string }) {
  const [open, setOpen] = useState(false);
  const raw = open ? exactStringify(value) : '';
  return (
    <details className="raw" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>{label}</summary>
      {open && (
        <>
          <pre>{raw.slice(0, 131072)}</pre>
          {raw.length > 131072 && (
            <p className="muted">
              Preview limited to 131,072 characters. The full value is not shown here.
            </p>
          )}
        </>
      )}
    </details>
  );
}
export function RecordLink({ record }: { record?: RecordRef }) {
  if (!record) return <span className="muted">No evidence record supplied</span>;
  const href = safeLink(record.uri);
  return (
    <span className="record-link">
      {href ? (
        <a href={href} target="_blank" rel="noreferrer">
          {record.uri}
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      ) : (
        <code>{record.uri}</code>
      )}
      {record.sha256 && (
        <small>
          File fingerprint (SHA-256) <code>{record.sha256}</code>
        </small>
      )}
    </span>
  );
}
export function Value({
  value,
  full = false,
  depth = 0,
}: {
  value: unknown;
  full?: boolean;
  depth?: number;
}) {
  if (value === undefined) return <span className="value-empty">missing</span>;
  if (value === null) return <span className="value-empty">null</span>;
  if (value === '') return <span className="value-empty">empty text</span>;
  if (isExactNumber(value)) return <code className="exact-number">{value.$number}</code>;
  if (typeof value === 'object') {
    const arr = Array.isArray(value),
      entries = exactObjectEntries(value);
    if (!entries.length)
      return <span className="value-empty">{arr ? '[] · empty list' : '{} · empty object'}</span>;
    if (!full)
      return (
        <span className="structured-value">
          {entries.length}{' '}
          {arr
            ? entries.length === 1
              ? 'item'
              : 'items'
            : entries.length === 1
              ? 'field'
              : 'fields'}{' '}
          <span aria-hidden="true">↳</span>
        </span>
      );
    if (depth >= 8) return <pre>{textValue(value)}</pre>;
    return (
      <>
        <dl className="nested-values">
          {entries.slice(0, 50).map(([key, v]) => (
            <div key={key}>
              <dt>{arr ? `Occurrence [${key}]` : key}</dt>
              <dd>
                <Value value={v} full depth={depth + 1} />
              </dd>
            </div>
          ))}
        </dl>
        {entries.length > 50 && (
          <p>First 50 items displayed. Downloading the result retains the complete value.</p>
        )}
      </>
    );
  }
  return (
    <span className={typeof value === 'number' ? 'numeric' : undefined}>{textValue(value)}</span>
  );
}
function Field({
  field,
  path,
  depth = 0,
}: {
  field: CatalogField;
  path: FieldPath;
  depth?: number;
}) {
  const [open, setOpen] = useState(false);
  const children =
    field.properties ?? field.items?.properties ?? (field.items ? [field.items] : []);
  const nested = children.length > 0;
  const info = (
    <>
      <code>{field.name || '[element]'}</code>
      {field.businessName && field.businessName !== field.name && (
        <span className="field-type">{field.businessName}</span>
      )}
      <span className="field-description">{field.description || 'Description not supplied'}</span>
    </>
  );
  return (
    <li className="field">
      <div className="field-row">
        {nested ? (
          <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
            <summary>{info}</summary>
            {open &&
              depth < 10 &&
              (field.items && !field.items.properties ? (
                <ul className="field-list">
                  <Field field={field.items} path={[...path, { each: true }]} depth={depth + 1} />
                </ul>
              ) : (
                <FieldTree
                  fields={children}
                  path={field.items ? [...path, { each: true }] : path}
                  depth={depth + 1}
                />
              ))}
          </details>
        ) : (
          <div className="field-summary">{info}</div>
        )}
      </div>
      <details className="field-meta">
        <summary>Technical field details</summary>
        <span>Storage type: {field.physicalType || field.logicalType || 'Not disclosed'}</span>
        <span>
          {field.required ? 'Field is required. ' : ''}Whether null is allowed:{' '}
          {field.nullable === false ? 'No' : field.nullable === true ? 'Yes' : 'Not specified'}.
        </span>
        <code>{pathLabel(path)}</code>
      </details>
    </li>
  );
}
export function FieldTree({
  fields,
  path = [],
  depth = 0,
}: {
  fields: CatalogField[];
  path?: FieldPath;
  depth?: number;
}) {
  return (
    <ul className="field-list">
      {fields.slice(0, 100).map((field, i) => (
        <Field
          key={`${field.name}:${i}`}
          field={field}
          path={[...path, { field: field.name }]}
          depth={depth}
        />
      ))}
      {fields.length > 100 && (
        <li>First 100 fields displayed. See the catalog definition for all fields.</li>
      )}
    </ul>
  );
}

export function BlankValuesHelp() {
  return (
    <details className="blank-values-help">
      <summary>Why some values are blank</summary>
      <dl>
        <dt>missing</dt>
        <dd>The field is not present in this record.</dd>
        <dt>null</dt>
        <dd>The record supplies an explicit null value. Its reason is not inferred.</dd>
        <dt>empty text</dt>
        <dd>The record supplies a blank string.</dd>
        <dt>empty list</dt>
        <dd>The record supplies a list with no items.</dd>
        <dt>empty object</dt>
        <dd>The record supplies an object with no fields.</dd>
      </dl>
    </details>
  );
}
