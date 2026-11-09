import { isExactNumber } from '../../domain/exact';
import type { CatalogField, ExactNumber, FieldPath } from '../../domain/types';
import { objectOf } from '../../lib/display';

export const fieldLimit = 100;

export type FieldEntry = { field: CatalogField; path: FieldPath; item?: true };

export function fieldEntries(fields: CatalogField[], path: FieldPath, item?: CatalogField) {
  const entries: FieldEntry[] = fields.slice(0, fieldLimit).map((field) => ({
    field,
    path: [...path, { field: field.name }],
  }));
  if (item) entries.push({ field: item, path: [...path, { each: true }], item: true });
  return entries;
}

export function suppliedText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

type Code = string | number | boolean | null | ExactNumber;

function isCode(value: unknown): value is Code {
  return (
    value === null || typeof value === 'string' || typeof value === 'boolean' || isNumber(value)
  );
}

function isNumber(value: unknown): value is number | ExactNumber {
  return (typeof value === 'number' && Number.isFinite(value)) || isExactNumber(value);
}

export function declaredCodes(field: CatalogField) {
  if (!Array.isArray(field.enum)) return [];
  return field.enum.flatMap((entry: unknown) => {
    const { value, label, description } = objectOf(entry);
    return isCode(value)
      ? [{ value, label: suppliedText(label), description: suppliedText(description) }]
      : [];
  });
}

const bounds = [
  ['minimum', 'Minimum (included)'],
  ['exclusiveMinimum', 'Lower bound (excluded)'],
  ['maximum', 'Maximum (included)'],
  ['exclusiveMaximum', 'Upper bound (excluded)'],
] as const;
const numericLimits = [...bounds, ['multipleOf', 'Multiple of']] as const;
const limitsByType: Readonly<Record<string, readonly (readonly [string, string])[]>> = {
  integer: numericLimits,
  number: numericLimits,
  date: bounds,
  time: bounds,
  timestamp: bounds,
  string: [
    ['minLength', 'Minimum text length'],
    ['maxLength', 'Maximum text length'],
  ],
  array: [
    ['minItems', 'Minimum list length'],
    ['maxItems', 'Maximum list length'],
  ],
  object: [
    ['minProperties', 'Minimum field count'],
    ['maxProperties', 'Maximum field count'],
  ],
};

export function declaredLimits(field: CatalogField) {
  const options = objectOf(field.logicalTypeOptions);
  const type = field.logicalType ?? '';
  if (!Object.hasOwn(limitsByType, type)) return [];
  const temporal = type === 'date' || type === 'time' || type === 'timestamp';
  return limitsByType[type].flatMap(([key, label]) => {
    const value = options[key];
    const supplied = temporal ? suppliedText(value) : isNumber(value) ? value : undefined;
    return supplied === undefined ? [] : [{ label, value: supplied }];
  });
}
