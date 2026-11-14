import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import type { ExactObject } from '../domain/types';
import { exactObjectEntries, exactObjectField, isExactNumber, isObject } from '../domain/exact';
import { Value } from './Primitives';

/** Search scalar values without changing exact numbers, source keys or nested occurrences. */
function searchableValues(value: unknown): string[] {
  if (isExactNumber(value)) return [value.$number.toLowerCase()];
  if (Array.isArray(value)) return value.flatMap(searchableValues);
  if (isObject(value))
    return exactObjectEntries(value).flatMap(([, item]) => searchableValues(item));
  return value === null || value === undefined ? [] : [String(value).toLowerCase()];
}

export function ResultTable({
  rows,
  columns,
  positions,
  caption = 'Records returned by this request',
  renderRecord,
}: {
  rows: ExactObject[];
  columns: string[];
  positions?: number[];
  caption?: string;
  renderRecord?: (row: ExactObject) => ReactNode;
}) {
  const searchId = useId();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<number | undefined>();
  const searchInput = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const searchable = useMemo(() => rows.map((row) => searchableValues(row)), [rows]);
  const query = search.trim().toLowerCase();
  const matching = rows
    .map((row, index) => ({ row, index }))
    .filter(({ index }) => !query || searchable[index].some((value) => value.includes(query)));
  const selectionOutsideSearch =
    selected !== undefined && !matching.some(({ index }) => index === selected);
  useEffect(() => {
    setSelected(undefined);
    setSearch('');
  }, [rows]);
  function inspect(index: number, button: HTMLButtonElement) {
    trigger.current = button;
    setSelected(selected === index ? undefined : index);
    setTimeout(() => heading.current?.focus(), 0);
  }
  return (
    <div className={`result-workspace${selected !== undefined ? ' has-selection' : ''}`}>
      <div className="result-table-tools">
        <div className="result-search">
          <label className="stack-label" htmlFor={searchId}>
            Search this page
            <input
              id={searchId}
              ref={searchInput}
              type="search"
              placeholder="Find text or exact values…"
              value={search}
              aria-describedby={`${searchId}-help ${searchId}-count`}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <span id={`${searchId}-count`} className="muted result-search-count" role="status">
            {matching.length} of {rows.length} records on this page
          </span>
          {search && (
            <button
              onClick={() => {
                setSearch('');
                searchInput.current?.focus();
              }}
            >
              Clear page search
            </button>
          )}
        </div>
        <p id={`${searchId}-help`} className="muted table-reading-help">
          Matches values in the returned page. Downloads keep every returned record. Select a record
          number to read every field; long values are shortened in this table.
        </p>
      </div>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Data records; scroll horizontally for more fields"
      >
        <table className="data-table">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">Record</th>
              {columns.map((c) => (
                <th key={c} scope="col">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matching.map(({ row, index: i }) => (
              <tr key={positions?.[i] ?? i} className={selected === i ? 'selected-row' : ''}>
                <td>
                  <button
                    className="row-button"
                    aria-label={`Inspect record ${String((positions?.[i] ?? i) + 1).padStart(2, '0')}`}
                    aria-expanded={selected === i}
                    onClick={(event) => inspect(i, event.currentTarget)}
                  >
                    {String((positions?.[i] ?? i) + 1).padStart(2, '0')}
                    <span aria-hidden="true">↗</span>
                  </button>
                </td>
                {columns.map((c) => (
                  <td key={c}>
                    <div className="cell-value">
                      <Value value={exactObjectField(row, c)} />
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!matching.length && <p className="muted">No records on this page match the search.</p>}
      </div>
      {selected !== undefined && rows[selected] && (
        <section className="record-inspector" aria-label="Record detail">
          <div className="section-heading">
            <h3 ref={heading} tabIndex={-1}>
              Record {(positions?.[selected] ?? selected) + 1}
            </h3>
            <button
              onClick={() => {
                setSelected(undefined);
                if (trigger.current?.isConnected) trigger.current.focus();
                else searchInput.current?.focus();
              }}
            >
              Close detail
            </button>
          </div>
          {selectionOutsideSearch && (
            <p className="muted">The selected record is outside these page search results.</p>
          )}
          <div className="record-navigation" role="group" aria-label="Browse returned records">
            <span className="muted">
              {selected + 1} of {rows.length} returned records
            </span>
            <div>
              <button
                aria-label="Previous record"
                disabled={selected === 0}
                onClick={() => setSelected(selected - 1)}
              >
                ←
              </button>
              <button
                aria-label="Next record"
                disabled={selected === rows.length - 1}
                onClick={() => setSelected(selected + 1)}
              >
                →
              </button>
            </div>
          </div>
          <p className="muted">Each listed item is kept separately, including repeated values.</p>
          <div key={selected}>
            {renderRecord ? renderRecord(rows[selected]) : <Value value={rows[selected]} full />}
          </div>
        </section>
      )}
    </div>
  );
}
