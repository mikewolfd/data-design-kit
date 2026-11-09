import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Catalog, CatalogField, FieldPath } from '../../src/domain/types';
import {
  FieldTree,
  type DocumentedFieldValues,
} from '../../src/features/field-dictionary/FieldTree';
import { PublisherValues } from '../../src/features/field-dictionary/FieldValues';
import { declaredCodes, fieldEntries } from '../../src/features/field-dictionary/field-metadata';

const render = (fields: CatalogField[], path?: FieldPath, identities?: Catalog['identities']) =>
  renderToStaticMarkup(createElement(FieldTree, { fields, path, identities }));

test('publisher label and description lead, with the native name and a path-specific copy action', () => {
  const html = render([
    {
      name: 'Complaint.Type[0]',
      businessName: 'Problem (formerly Complaint Type)',
      description: 'How the report was classified.',
      physicalName: 'STORED_TYPE',
    },
  ]);
  assert.match(
    html,
    /Problem \(formerly Complaint Type\).*Native field name <\/span><code>Complaint\.Type\[0\]<\/code>.*How the report was classified\./,
  );
  assert.match(html, /aria-label="Copy name for \[&quot;Complaint\.Type\[0\]&quot;\]"/);
  assert.match(html, /aria-label="Copy path for \[&quot;Complaint\.Type\[0\]&quot;\]"/);
  assert.match(html, /Physical name in the source<\/dt><dd><code>STORED_TYPE<\/code>/);
});

test('list steps describe the item itself and preserve named fields in schema order', () => {
  const tag = { name: 'TagSpec', logicalType: 'string' };
  const tags = { name: 'flags', items: tag };
  const matrix = { name: 'matrix', items: { name: 'inner list', items: { name: 'scalar' } } };
  const reading = { name: 'ReadingSpec', properties: [tags, matrix] };
  const readings = { name: 'readings', items: reading };
  const [entry] = fieldEntries([readings], []);
  const [item] = fieldEntries([], entry.path, reading);
  assert.deepEqual(item.path, [{ field: 'readings' }, { each: true }]);
  assert.equal(item.item, true);
  const [flagEntry, matrixEntry] = fieldEntries(reading.properties, item.path);
  const [flagItem] = fieldEntries([], flagEntry.path, tag);
  const [inner] = fieldEntries([], matrixEntry.path, matrix.items);
  assert.deepEqual(flagItem.path, [
    { field: 'readings' },
    { each: true },
    { field: 'flags' },
    { each: true },
  ]);
  assert.deepEqual(fieldEntries([], inner.path, matrix.items.items)[0].path, [
    { field: 'readings' },
    { each: true },
    { field: 'matrix' },
    { each: true },
    { each: true },
  ]);
  const html = render(reading.properties, item.path);
  assert.ok(html.indexOf('<code>flags</code>') < html.indexOf('<code>matrix</code>'));
  assert.match(html, /Copy name for \[&quot;readings&quot;\]\[each\]\[&quot;flags&quot;\]/);
  assert.match(html, /Copy name for \[&quot;readings&quot;\]\[each\]\[&quot;matrix&quot;\]/);
  assert.doesNotMatch(html, /ReadingSpec|TagSpec/);
});

test('unknown facts stay unknown while declared limits and nullability stay exact', () => {
  const html = render([
    {
      name: 'file_size_bytes',
      businessName: '  ',
      logicalType: 'number',
      required: false,
      logicalTypeOptions: { minimum: 0, exclusiveMaximum: { $number: '9007199254740993' } },
      unit: 'arbitrary-unit',
    },
    {
      name: '',
      description: 'This catalog explicitly defines the empty field name.',
      nullable: true,
    },
  ]);
  assert.match(html, /<strong class="field-label"><code>file_size_bytes<\/code><\/strong>/);
  assert.match(html, /Description not supplied/);
  assert.match(html, /Storage type<\/dt><dd>Not supplied<\/dd>/);
  assert.match(html, /Logical type<\/dt><dd><code>number<\/code><\/dd>/);
  assert.match(html, /Field marked required<\/dt><dd>No<\/dd>/);
  assert.match(html, /Null allowed<\/dt><dd>Not supplied<\/dd>/);
  assert.match(html, /Null allowed<\/dt><dd>Yes<\/dd>/);
  assert.match(html, /Minimum \(included\)<\/dt><dd><code>0<\/code>/);
  assert.match(html, /Upper bound \(excluded\)<\/dt><dd><code>9007199254740993<\/code>/);
  assert.match(html, /Copy name for \[&quot;&quot;\]/);
  assert.doesNotMatch(html, /arbitrary-unit/);
});

test('declared codes preserve exact numeric lexemes and distinguish blank, null and other scalar values', () => {
  const field: CatalogField = {
    name: 'status_code',
    enum: [
      { value: '', label: 'Blank text' },
      { value: null, description: 'Explicit null' },
      { value: false },
      { value: 0 },
      { value: { $number: '12345678901234567890.00' }, label: 'A big exact code' },
      { label: 'Missing value' },
      { value: [] },
      'invalid unwrapped entry',
    ],
    examples: ['example-only'],
  };
  assert.deepEqual(
    declaredCodes(field).map(({ value }) => value),
    ['', null, false, 0, { $number: '12345678901234567890.00' }],
  );
  assert.deepEqual(declaredCodes({ name: 'status_code', examples: [null, ''] }), []);
  assert.match(render([field]), /Values documented for this field/);
  assert.match(
    render([{ name: 'status_code', examples: [null, ''] }]),
    /Values documented for this field/,
  );
  assert.doesNotMatch(render([{ name: 'status_code' }]), /Values documented for this field/);
});

test('identity scope matches a nonvirtual field by its entire path', () => {
  const prefix: FieldPath = [{ field: 'reports' }, { each: true }];
  const path = [...prefix, { field: 'record_id' }];
  const field = { name: 'record_id' };
  const identity = {
    dataset: 'fixture',
    kind: 'key',
    scope: 'Within this report series',
    meaning: 'The occurrence identifier declared by the publisher.',
    fields: [
      { path, virtual: false, physicalType: 'varchar' },
      { path: [...prefix, { field: 'record_sequence' }], virtual: false, physicalType: 'integer' },
    ],
  };
  assert.match(
    render([field], prefix, [identity]),
    /Part of an identifier.*Within this report series/,
  );
  assert.doesNotMatch(
    render([field], [{ field: 'other' }, { each: true }], [identity]),
    /Within this report series/,
  );
  const virtual = { ...identity, fields: [{ path, virtual: true, physicalType: 'varchar' }] };
  assert.doesNotMatch(render([field], prefix, [virtual]), /Within this report series/);
});

test('publisher reference values appear only on the matched nested field path', () => {
  const path: FieldPath = [{ field: 'related' }, { each: true }];
  const documentation: DocumentedFieldValues = {
    path: [...path, { field: 'type' }],
    domain: 'Related document types',
    locator: 'Related documents table',
    sourceUrl: 'https://publisher.example/reference#types',
    checked: true,
    values: [{ value: 'Amends' }],
  };
  const fields = [{ name: 'type' }, { name: 'related.type' }];
  const documentedValues = [documentation];
  const nested = renderToStaticMarkup(createElement(FieldTree, { fields, path, documentedValues }));
  assert.match(
    nested,
    /Publisher reference values for \[&quot;related&quot;\]\[each\]\[&quot;type&quot;\]/,
  );
  assert.equal(nested.match(/<details class="field-values"/g)?.length, 1);
  const root = renderToStaticMarkup(createElement(FieldTree, { fields, documentedValues }));
  assert.doesNotMatch(root, /Publisher reference values/);
});

test('publisher code references preserve scope, observed exceptions, and link safety', () => {
  const documentation: DocumentedFieldValues = {
    path: [{ field: 'code' }],
    domain: 'Related document types',
    locator: 'Related documents table',
    sourceUrl: 'https://publisher.example/reference#types',
    checked: true,
    values: [{ value: 'Amends', label: 'Amends a related document' }],
    observedAt: '2026-10-01',
    observedOffList: [{ value: 'Typo', reason: 'Retained spelling in source' }],
    unobserved: ['Supersedes'],
    caveat: 'This checked list describes the October sample.',
  };
  const html = renderToStaticMarkup(createElement(PublisherValues, { documentation }));
  assert.match(html, /Publisher reference values for Related document types/);
  assert.match(html, /&quot;Amends&quot;.*Amends a related document/);
  assert.match(html, /Other values may occur\./);
  assert.match(html, /This checked list describes the October sample\./);
  assert.match(html, /href="https:\/\/publisher\.example\/reference#types"/);
  assert.match(html, /Where to look<\/dt><dd>Related documents table/);
  assert.match(html, /Publisher marked as checked<\/dt><dd>Yes/);
  assert.match(html, /Observation date<\/dt><dd>2026-10-01/);
  assert.match(
    html,
    /Observed outside this reference list.*&quot;Typo&quot;.*Retained spelling in source/,
  );
  assert.match(html, /marked as unobserved.*&quot;Supersedes&quot;/);
  const unsafe = renderToStaticMarkup(
    createElement(PublisherValues, {
      documentation: { ...documentation, checked: false, sourceUrl: 'javascript:alert(1)' },
    }),
  );
  assert.doesNotMatch(unsafe, /href=/);
  assert.match(unsafe, /Publisher marked as checked<\/dt><dd>No/);
});

test('schema disclosure bounds identify where to find more fields', () => {
  const fields = Array.from({ length: 101 }, (_, index) => ({ name: `field_${index}` }));
  const html = render(fields);
  assert.match(html, /First 100 fields displayed/);
  assert.match(html, /field_99/);
  assert.doesNotMatch(html, /field_100/);
  const cutoff = renderToStaticMarkup(
    createElement(FieldTree, {
      fields: [{ name: 'parent', properties: [{ name: 'child' }] }],
      depth: 10,
    }),
  );
  assert.match(cutoff, /Deeper fields are listed in the catalog definition/);
  assert.doesNotMatch(cutoff, /child/);
});
