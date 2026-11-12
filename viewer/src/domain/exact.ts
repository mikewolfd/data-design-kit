import { isLosslessNumber, LosslessNumber, parse, stringify } from 'lossless-json';
import type { EscapedObject, ExactNumber, ExactValue } from './types';

const JSON_NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;
const FORBIDDEN = new Set(['__proto__', 'prototype', 'constructor']);
export const isObject = (value: unknown): value is Record<string, any> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
export const isExactNumber = (value: unknown): value is ExactNumber =>
  isObject(value) &&
  Object.keys(value).length === 1 &&
  typeof value.$number === 'string' &&
  validNumber(value.$number);
export const isEscapedObject = (value: unknown): value is EscapedObject =>
  isObject(value) &&
  Object.keys(value).length === 1 &&
  Array.isArray(value.$object) &&
  value.$object.every(
    (entry: unknown) => Array.isArray(entry) && entry.length === 2 && typeof entry[0] === 'string',
  );
export const exactObjectEntries = (value: Record<string, any>): [string, any][] =>
  isEscapedObject(value) ? value.$object : Object.entries(value);
export const exactObjectField = (value: Record<string, any>, name: string): any =>
  isEscapedObject(value)
    ? value.$object.find((entry) => entry[0] === name)?.[1]
    : Object.hasOwn(value, name)
      ? value[name]
      : undefined;
export function validNumber(value: string): boolean {
  if (value.length > 1024 || !JSON_NUMBER.test(value)) return false;
  const exponent = value.match(/[eE]([+-]?\d+)$/)?.[1];
  return !exponent || (exponent.length < 6 && Math.abs(Number(exponent)) <= 1000);
}

/** Numeric lexemes remain exact. Literal source tag objects use an escaped entry list. */
function parseSafe(text: string, mode: 'data' | 'metadata' | 'request'): any {
  const parsed = parse(text, null, {
    onDuplicateKey: ({ key }) => {
      throw new Error(`Duplicate JSON key: ${key}`);
    },
  });
  const maxNodes = mode === 'metadata' ? 2_000_000 : 300_000;
  const maxString = mode === 'metadata' ? 4_000_000 : 1_000_000;
  let nodes = 0;
  const visit = (value: any, depth: number): any => {
    if (++nodes > maxNodes || depth > 48)
      throw new Error('JSON structure exceeds the supported budget.');
    if (isLosslessNumber(value)) {
      if (!validNumber(value.value))
        throw new Error('Numeric value exceeds the exact-value budget.');
      if (
        mode !== 'data' &&
        /^-?(?:0|[1-9]\d*)$/.test(value.value) &&
        Number.isSafeInteger(Number(value.value))
      )
        return Number(value.value);
      return { $number: value.value };
    }
    if (typeof value === 'string' && value.length > maxString)
      throw new Error('JSON string exceeds the supported budget.');
    if (Array.isArray(value)) return value.map((item) => visit(item, depth + 1));
    if (isObject(value)) {
      const keys = Object.keys(value);
      if (mode === 'request' && keys.some((key) => FORBIDDEN.has(key)))
        throw new Error('Unsafe JSON object key.');
      if (mode === 'request' && '$number' in value) {
        if (!isExactNumber(value)) throw new Error('Invalid exact number transport value.');
        return { $number: value.$number };
      }
      if (mode !== 'request' && keys.some((key) => key === '$number' || key === '$object'))
        return { $object: keys.map((key) => [key, visit(value[key], depth + 1)]) };
      const result = Object.create(null);
      for (const key of keys) result[key] = visit(value[key], depth + 1);
      return result;
    }
    return value;
  };
  return visit(parsed, 0);
}
export const parseExactData = (text: string): ExactValue => parseSafe(text, 'data');
export const parseMetadata = (text: string): any => parseSafe(text, 'metadata');
export const parseRequest = (text: string): any => parseSafe(text, 'request');

export function exactStringify(value: unknown, space: number | string = 2): string {
  const decode = (item: any): any => {
    if (isExactNumber(item)) return new LosslessNumber(item.$number);
    if (Array.isArray(item)) return item.map(decode);
    if (isObject(item))
      return Object.fromEntries(
        exactObjectEntries(item).map(([key, child]) => [key, decode(child)]),
      );
    return item;
  };
  return stringify(decode(value), null, space) ?? 'null';
}
export function formatExactValue(value: unknown): string {
  if (isExactNumber(value)) return value.$number;
  if (typeof value === 'string') return value;
  if (value === undefined) return '(missing)';
  return exactStringify(value, 0);
}

function parts(value: string): [bigint, number] {
  if (!validNumber(value)) throw new Error('Invalid exact numeric value.');
  const [mantissa, exponent = '0'] = value.toLowerCase().split('e');
  const fraction = mantissa.split('.')[1]?.length ?? 0;
  return [BigInt(mantissa.replace('.', '')), Number(exponent) - fraction];
}
/** Decimal comparison uses integer arithmetic; values never pass through a float. */
export function compareExactNumbers(left: string, right: string): -1 | 0 | 1 {
  const [a, ae] = parts(left),
    [b, be] = parts(right),
    base = Math.min(ae, be);
  const x = a * 10n ** BigInt(ae - base),
    y = b * 10n ** BigInt(be - base);
  return x < y ? -1 : x > y ? 1 : 0;
}
export function exactEqual(left: unknown, right: unknown): boolean {
  if (isExactNumber(left) && isExactNumber(right))
    return compareExactNumbers(left.$number, right.$number) === 0;
  if (typeof left !== typeof right || left === null || right === null) return left === right;
  if (Array.isArray(left) && Array.isArray(right))
    return (
      left.length === right.length && left.every((item, index) => exactEqual(item, right[index]))
    );
  if (isObject(left) && isObject(right)) {
    const a = Object.keys(left).sort(),
      b = Object.keys(right).sort();
    return (
      a.length === b.length &&
      a.every((key, index) => key === b[index] && exactEqual(left[key], right[key]))
    );
  }
  return left === right;
}
