import { useState } from 'react';
import { formatExactValue } from '../../domain/exact';
import type { Catalog, CatalogField, FieldPath } from '../../domain/types';
import { pathLabel } from '../../lib/display';
import {
  declaredLimits,
  fieldEntries,
  fieldLimit,
  suppliedText,
  type FieldEntry,
} from './field-metadata';
import { FieldValues, type DocumentedFieldValues } from './FieldValues';

export type { DocumentedFieldValues } from './FieldValues';

type Identities = Catalog['identities'];
type FieldTreeProps = {
  fields: CatalogField[];
  path?: FieldPath;
  depth?: number;
  identities?: Identities;
  documentedValues?: readonly DocumentedFieldValues[];
};

const fieldDepthLimit = 10;
const suppliedBoolean = (value: unknown) =>
  value === true ? 'Yes' : value === false ? 'No' : 'Not supplied';

function Field({
  field,
  path,
  item,
  depth,
  identities,
  documentedValues,
}: FieldEntry & Pick<Required<FieldTreeProps>, 'depth' | 'identities' | 'documentedValues'>) {
  const [open, setOpen] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const name = typeof field.name === 'string' ? field.name : undefined;
  const displayName = name === '' ? '""' : name;
  const humanName = suppliedText(field.businessName);
  const description = suppliedText(field.description);
  const physicalName = suppliedText(field.physicalName);
  const physicalType = suppliedText(field.physicalType);
  const logicalType = suppliedText(field.logicalType);
  const address = pathLabel(path);
  const limits = declaredLimits(field);
  const hasChildren = Boolean(field.items || field.properties?.length);
  const itemObject = item && !field.items && Boolean(field.properties?.length);
  const declaredIdentities = identities.filter((identity) =>
    identity.fields.some((part) => !part.virtual && pathLabel(part.path) === address),
  );
  async function copy(value: string, label: 'name' | 'path') {
    try {
      await navigator.clipboard.writeText(value);
      setAnnouncement(`Copied field ${label}.`);
    } catch {
      setAnnouncement(`Clipboard access is unavailable. Select and copy the ${label} shown here.`);
    }
  }

  const children = (open || itemObject) && depth < fieldDepthLimit && (
    <FieldList
      fields={field.properties ?? []}
      item={field.items}
      path={path}
      depth={depth + 1}
      identities={identities}
      documentedValues={documentedValues}
    />
  );

  return (
    <li className="field">
      <div className="field-summary">
        <div className="field-heading">
          <strong className="field-label">
            {humanName ?? (item ? 'List item' : <code>{displayName}</code>)}
          </strong>
          {displayName !== undefined && (humanName || item) && (
            <span className="field-native">
              <span className="sr-only">
                {item ? 'Item definition name ' : 'Native field name '}
              </span>
              <code>{displayName}</code>
            </span>
          )}
        </div>
        <p className="field-description">{description ?? 'Description not supplied'}</p>
      </div>
      {declaredIdentities.length > 0 && (
        <dl className="field-identities">
          {declaredIdentities.map((identity, index) => (
            <div key={index}>
              <dt>{identity.fields.length > 1 ? 'Part of an identifier' : 'Identifier scope'}</dt>
              <dd>
                {identity.scope}
                {identity.meaning && <> · {identity.meaning}</>}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <FieldValues
        field={field}
        address={address}
        documentedValues={documentedValues.filter((record) => pathLabel(record.path) === address)}
      />
      <details className="field-meta">
        <summary aria-label={`Technical field details for ${address}`}>
          Technical field details
        </summary>
        <dl>
          {name !== undefined && (
            <div>
              <dt>Native name</dt>
              <dd>
                <code>{displayName}</code>
                <button
                  type="button"
                  className="field-copy"
                  aria-label={`Copy name for ${address}`}
                  onClick={() => void copy(name, 'name')}
                >
                  Copy name
                </button>
              </dd>
            </div>
          )}
          <div>
            <dt>Field path</dt>
            <dd>
              <code>{address}</code>
              <button
                type="button"
                className="field-copy"
                aria-label={`Copy path for ${address}`}
                onClick={() => void copy(address, 'path')}
              >
                Copy path
              </button>
            </dd>
          </div>
          <div>
            <dt>Storage type</dt>
            <dd>{physicalType ? <code>{physicalType}</code> : 'Not supplied'}</dd>
          </div>
          <div>
            <dt>Logical type</dt>
            <dd>{logicalType ? <code>{logicalType}</code> : 'Not supplied'}</dd>
          </div>
          {physicalName && (
            <div>
              <dt>Physical name in the source</dt>
              <dd>
                <code>{physicalName}</code>
              </dd>
            </div>
          )}
          <div>
            <dt>Field marked required</dt>
            <dd>{suppliedBoolean(field.required)}</dd>
          </div>
          <div>
            <dt>Null allowed</dt>
            <dd>{suppliedBoolean(field.nullable)}</dd>
          </div>
          {limits.map(({ label, value }) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                <code>{formatExactValue(value)}</code>
              </dd>
            </div>
          ))}
        </dl>
      </details>
      <div className="field-copy-status" role="status">
        {announcement}
      </div>
      {hasChildren && (
        <div className="field-row">
          {depth >= fieldDepthLimit ? (
            <p className="field-limit">Deeper fields are listed in the catalog definition.</p>
          ) : itemObject ? (
            children
          ) : (
            <details onToggle={(event) => setOpen(event.currentTarget.open)}>
              <summary>
                {displayName === undefined ? (
                  'Items in this list'
                ) : (
                  <>
                    Nested fields in <code>{displayName}</code>
                  </>
                )}
              </summary>
              {children}
            </details>
          )}
        </div>
      )}
    </li>
  );
}

function FieldList({
  fields,
  path,
  item,
  depth,
  identities,
  documentedValues,
}: Required<FieldTreeProps> & { item?: CatalogField }) {
  return (
    <ul className="field-list">
      {fieldEntries(fields, path, item).map((entry, index) => (
        <Field
          key={`${entry.field.name}:${index}`}
          {...entry}
          depth={depth}
          identities={identities}
          documentedValues={documentedValues}
        />
      ))}
      {fields.length > fieldLimit && (
        <li>First 100 fields displayed. See the catalog definition for all fields.</li>
      )}
    </ul>
  );
}

export function FieldTree({
  fields,
  path = [],
  depth = 0,
  identities = [],
  documentedValues = [],
}: FieldTreeProps) {
  return (
    <FieldList
      fields={fields}
      path={path}
      depth={depth}
      identities={identities}
      documentedValues={documentedValues}
    />
  );
}
