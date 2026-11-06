import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import {
  compareExactNumbers,
  exactEqual,
  exactObjectEntries,
  exactObjectField,
  isEscapedObject,
  isExactNumber,
  isObject,
  parseExactData,
  validNumber,
} from '../domain/exact';
import type {
  CatalogSnapshot,
  ExactBinding,
  ExactObject,
  ExactValue,
  FieldPath,
  QueryRequest,
  QueryResult,
  ReadRequest,
  ReadResult,
  RecordRef,
} from '../domain/types';
import {
  CatalogStore,
  fail,
  LIMITS,
  sha256,
  ViewerError,
  type LoadedCatalog,
} from './catalog-store';

/** Native owners implement only these reads. No scheduler, selection or runtime SDK lives here. */
export interface OwnerReader {
  read(input: {
    snapshot: CatalogSnapshot;
    binding: ExactBinding;
    offset: number;
    limit: number;
    deadline: number;
    signal: AbortSignal;
  }): Promise<{
    rows: ExactObject[];
    rowPositions: number[];
    total?: number;
    hasMore?: boolean;
    consumed: ExactBinding;
    record?: RecordRef;
  }>;
}
export interface OwnerQuery {
  query(input: {
    snapshot: CatalogSnapshot;
    recipeId: string;
    bindings: Record<string, ExactBinding>;
    parameters: Record<string, ExactValue>;
    sql: Uint8Array;
    limit: number;
    deadline: number;
    signal: AbortSignal;
  }): Promise<QueryResult>;
}
const TRANSPORT = 'ddk-exact-json-v1' as const;
const empty = (
  binding: ExactBinding,
  status: 'refused' | 'unknown',
  reason: string,
): ReadResult => ({
  status,
  reason,
  binding,
  rows: [],
  columns: [],
  returned: 0,
  transport: TRANSPORT,
});
function text(value: unknown, label: string): asserts value is string {
  if (typeof value !== 'string' || !value || value.length > 2048)
    fail('invalid_request', `${label} must be a nonempty bounded string.`);
}
function pageLimit(value: unknown): number {
  if (value === undefined) return 25;
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < 1 ||
    value > LIMITS.pageRows
  )
    fail('page_budget', `Page size must be an integer from 1 to ${LIMITS.pageRows}.`);
  return value;
}
function checkedBinding(
  snapshot: CatalogSnapshot,
  value: ExactBinding,
): { refusal?: ReadResult; release?: ReadResult['release'] } {
  if (!isObject(value))
    fail('invalid_binding', 'An exact dataset, version and representation binding is required.');
  if (
    Object.keys(value).some(
      (key) => !['datasetId', 'versionId', 'representationId', 'releaseId'].includes(key),
    )
  )
    fail('invalid_binding', 'The exact binding contains an unsupported property.');
  for (const key of ['datasetId', 'versionId', 'representationId'] as const) text(value[key], key);
  const dataset = snapshot.catalog.datasets.find((row) => row.id === value.datasetId);
  if (!dataset)
    fail('binding_mismatch', 'The dataset identity is absent from the selected catalog.', 409);
  const version = snapshot.catalog.versions.find((row) => row.id === value.versionId);
  const representation = snapshot.catalog.representations.find(
    (row) => row.id === value.representationId,
  );
  if (
    !version ||
    version.dataset !== dataset.alias ||
    !representation ||
    representation.version !== version.id
  )
    fail(
      'binding_mismatch',
      'Dataset, version and representation do not identify the same catalog fact.',
      409,
    );
  if (version.referenceDisclosure === 'withheld')
    return {
      refusal: empty(
        value,
        'refused',
        'The exact version reference is withheld; no data reader may resolve it.',
      ),
    };
  if (version.retention === 'missing' || representation.availability === 'unavailable')
    return {
      refusal: empty(
        value,
        'refused',
        'The selected exact version or representation is unavailable.',
      ),
    };
  if (version.retention === 'unknown' || representation.availability === 'unknown')
    return {
      refusal: empty(
        value,
        'unknown',
        'The selected version retention or representation availability remains unknown.',
      ),
    };
  let release: ReadResult['release'];
  if (value.releaseId !== undefined) {
    text(value.releaseId, 'releaseId');
    const row = snapshot.catalog.releases.find((row) => row.id === value.releaseId);
    if (!row || row.membership !== 'complete' || !row.members.includes(version.id))
      fail(
        'release_mismatch',
        'The explicit version is not a member of the complete requested release.',
        409,
      );
    const selector = snapshot.catalog.currentSelection;
    release = {
      id: row.id,
      membership: row.membership,
      selected: Boolean(
        selector &&
        snapshot.catalog.selections.some(
          (selection) =>
            selection.authority === selector.authority &&
            selection.purpose === selector.purpose &&
            selection.release === row.id,
        ),
      ),
    };
  }
  return { release };
}
function fieldValues(value: unknown, path: FieldPath): unknown[] {
  let values = [value];
  for (const step of path)
    values = values.flatMap((item) =>
      'each' in step
        ? Array.isArray(item)
          ? item
          : []
        : isObject(item)
          ? [exactObjectField(item, step.field)]
          : [],
    );
  return values;
}
function checkedFilter(value: ReadRequest['filter']) {
  if (value === undefined) return;
  if (
    !isObject(value) ||
    !Array.isArray(value.path) ||
    value.path.length < 1 ||
    value.path.length > 12 ||
    value.path.some(
      (step) =>
        !isObject(step) ||
        Object.keys(step).length !== 1 ||
        !(
          ('field' in step &&
            typeof step.field === 'string' &&
            step.field.length > 0 &&
            step.field.length <= 256) ||
          ('each' in step && step.each === true)
        ),
    ) ||
    !Object.hasOwn(value, 'equals')
  )
    fail('invalid_filter', 'Use a bounded field path and one exact equality value.');
}
function rowColumns(rows: ExactObject[]): string[] {
  const columns = [...new Set(rows.flatMap((row) => exactObjectEntries(row).map(([key]) => key)))];
  if (columns.length > 256)
    fail('column_budget', 'The result exceeds the supported column budget.', 413);
  return columns;
}
function resultBudget<T>(result: T): T {
  if (Buffer.byteLength(JSON.stringify(result)) > LIMITS.resultBytes)
    fail(
      'result_budget',
      'The result exceeds the supported response byte budget. Request fewer rows.',
      413,
    );
  return result;
}
function sameBinding(actual: ExactBinding, expected: ExactBinding): boolean {
  return (
    isObject(actual) &&
    actual.datasetId === expected.datasetId &&
    actual.versionId === expected.versionId &&
    actual.representationId === expected.representationId &&
    actual.releaseId === expected.releaseId
  );
}
function validatePage(
  page: { rows: ExactObject[]; rowPositions?: number[]; total?: number; hasMore?: boolean },
  limit: number,
  offset = 0,
) {
  if (
    !Array.isArray(page.rows) ||
    page.rows.length > limit ||
    !Number.isSafeInteger(offset + page.rows.length) ||
    page.rows.some((row) => !isObject(row) || isExactNumber(row)) ||
    !Array.isArray(page.rowPositions) ||
    page.rows.length !== page.rowPositions.length ||
    page.rowPositions.some(
      (value, index, positions) =>
        !Number.isSafeInteger(value) || value < 0 || (index > 0 && value <= positions[index - 1]),
    ) ||
    (page.hasMore !== undefined && typeof page.hasMore !== 'boolean') ||
    (page.hasMore === true && page.rows.length === 0) ||
    (page.total !== undefined &&
      (!Number.isSafeInteger(page.total) ||
        page.total < offset + page.rows.length ||
        (page.rows.length === 0 && page.total > offset) ||
        (page.hasMore !== undefined && page.hasMore !== offset + page.rows.length < page.total)))
  )
    fail(
      'adapter_budget',
      'The owner reader returned an invalid, oversized or non-progressing page.',
      413,
    );
  rowColumns(page.rows);
  let nodes = 0;
  function visit(value: unknown, depth: number) {
    if (++nodes > 300_000 || depth > 48)
      fail('adapter_budget', 'The owner result exceeds the supported structure budget.', 413);
    if (isExactNumber(value) || value === null || typeof value === 'boolean') return;
    if (typeof value === 'string') {
      if (value.length > 1_000_000)
        fail('adapter_budget', 'An owner string exceeds the supported value budget.', 413);
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) visit(item, depth + 1);
      return;
    }
    if (isObject(value)) {
      if (('$number' in value || '$object' in value) && !isEscapedObject(value))
        fail(
          'adapter_transport',
          'The owner result contains an ambiguous reserved transport value.',
          409,
        );
      const entries = exactObjectEntries(value);
      if (new Set(entries.map(([key]) => key)).size !== entries.length)
        fail('adapter_transport', 'An escaped owner object contains duplicate keys.', 409);
      for (const [, item] of entries) visit(item, depth + 1);
      return;
    }
    fail('adapter_transport', 'Owner data numbers must use exact numeric transport tags.', 409);
  }
  for (const row of page.rows) visit(row, 0);
}

export class FixtureReader implements OwnerReader {
  constructor(private store: CatalogStore) {}
  async all(
    loaded: LoadedCatalog,
    binding: ExactBinding,
    deadline: number,
  ): Promise<ExactObject[]> {
    if (loaded.registration.mode !== 'fixture')
      fail('reader_refused', 'The fixture reader cannot read application data.', 403);
    const matches = loaded.snapshot.lock.files.filter(
      (row) => row.role === 'data' && row.identity === binding.representationId,
    );
    if (matches.length !== 1)
      fail(
        'reader_refused',
        'No single pinned fixture data file is registered for this representation.',
        409,
      );
    const file = matches[0];
    const bytes = await this.store.readPinned(
      loaded.registration,
      file.path,
      file.sha256,
      deadline,
      1024 * 1024,
    );
    const rows = parseExactData(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (
      !Array.isArray(rows) ||
      rows.length > LIMITS.rows ||
      rows.some((row) => !isObject(row) || isExactNumber(row))
    )
      fail('row_budget', 'The fixture must be a bounded array of JSON objects.', 413);
    if (Date.now() >= deadline) fail('deadline', 'The fixture parse exceeded its deadline.', 408);
    return rows as ExactObject[];
  }
  async read(input: {
    snapshot: CatalogSnapshot;
    binding: ExactBinding;
    offset: number;
    limit: number;
    deadline: number;
    signal?: AbortSignal;
  }) {
    const rows = await this.all(
      await this.store.load(input.snapshot.id, input.deadline),
      input.binding,
      input.deadline,
    );
    const file = input.snapshot.lock.files.find(
      (row) => row.role === 'data' && row.identity === input.binding.representationId,
    )!;
    return {
      rows: rows.slice(input.offset, input.offset + input.limit),
      rowPositions: rows
        .slice(input.offset, input.offset + input.limit)
        .map((_, index) => input.offset + index),
      total: rows.length,
      consumed: input.binding,
      record: { uri: `urn:sha256:${file.sha256}`, sha256: file.sha256 },
    };
  }
}

const FIXTURE_RECIPES = Object.freeze({
  'urn:ddk-viewer:fixture:watershed:recipe:minimum': {
    catalog: 'watershed',
    input: 'observations',
    parameter: 'minimum_concentration',
    field: 'concentration',
    sql: 'SELECT * FROM records WHERE concentration >= $minimum_concentration;\n',
  },
  'urn:ddk-viewer:fixture:grants:recipe:minimum': {
    catalog: 'grants',
    input: 'awards',
    parameter: 'minimum_amount',
    field: 'amount',
    sql: 'SELECT * FROM records WHERE amount >= $minimum_amount;\n',
  },
});

/** Requests bind exact catalog bytes. Opaque cursors also bind the filter and page size. */
export class CatalogAccess {
  private cursorKey = randomBytes(32);
  private fixture: FixtureReader;
  private activeOwners = 0;
  private deadlineMs: number;
  constructor(
    private store: CatalogStore,
    private adapters: ReadonlyMap<string, { reader?: OwnerReader; query?: OwnerQuery }> = new Map(),
    options: { deadlineMs?: number } = {},
  ) {
    this.fixture = new FixtureReader(store);
    this.deadlineMs = options.deadlineMs ?? LIMITS.deadlineMs;
    if (
      !Number.isSafeInteger(this.deadlineMs) ||
      this.deadlineMs < 1 ||
      this.deadlineMs > LIMITS.deadlineMs
    )
      fail('invalid_deadline', 'The read deadline must stay within the viewer budget.');
  }
  private capabilities(snapshot: CatalogSnapshot): CatalogSnapshot {
    if (snapshot.mode === 'fixture') return snapshot;
    const owner = this.adapters.get(snapshot.id);
    return {
      ...snapshot,
      capabilities: {
        read: Boolean(owner?.reader),
        query: Boolean(owner?.query),
        ...(!owner?.reader && !owner?.query
          ? {
              reason:
                'Discovery only: no owner reader or query adapter is registered for this application set.',
            }
          : {}),
      },
    };
  }
  /** The same explicit adapter registry controls both UI capabilities and API access. */
  async snapshot(id: string): Promise<CatalogSnapshot> {
    return this.capabilities(await this.store.snapshot(id));
  }
  /** A timed-out owner still holds its concurrency slot until its promise settles. */
  private async callOwner<T>(
    run: (signal: AbortSignal) => Promise<T>,
    deadline: number,
  ): Promise<T> {
    if (this.activeOwners >= 2)
      fail(
        'owner_busy',
        'Two owner reads remain unsettled. Retry after the owner reports completion.',
        503,
      );
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    this.activeOwners++;
    const running = Promise.resolve()
      .then(() => run(controller.signal))
      .finally(() => {
        this.activeOwners--;
      });
    const expired = new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => {
          controller.abort();
          reject(
            new ViewerError(
              'owner_deadline',
              'The owner read deadline elapsed. Cancellation was requested; completion remains unknown.',
              408,
            ),
          );
        },
        Math.max(1, deadline - Date.now()),
      );
    });
    try {
      return await Promise.race([running, expired]);
    } finally {
      clearTimeout(timer);
    }
  }
  private async selected(id: string, catalogSha256: string, deadline: number) {
    text(id, 'catalogId');
    text(catalogSha256, 'catalogSha256');
    const loaded = await this.store.load(id, deadline);
    if (loaded.snapshot.identity.catalogSha256 !== catalogSha256)
      fail('catalog_mismatch', 'The request does not match the exact selected catalog bytes.', 409);
    return { ...loaded, snapshot: this.capabilities(loaded.snapshot) };
  }
  private cursor(scope: string, offset: number): string {
    const payload = Buffer.from(JSON.stringify({ scope, offset })).toString('base64url');
    return `${payload}.${createHmac('sha256', this.cursorKey).update(payload).digest('base64url')}`;
  }
  private offset(cursor: unknown, scope: string): number {
    if (cursor === undefined) return 0;
    if (
      typeof cursor !== 'string' ||
      cursor.length > 1024 ||
      !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(cursor)
    )
      fail('invalid_cursor', 'The page cursor is invalid.');
    const [payload, signature] = cursor.split('.'),
      expected = createHmac('sha256', this.cursorKey).update(payload).digest();
    const received = Buffer.from(signature, 'base64url');
    if (received.length !== expected.length || !timingSafeEqual(received, expected))
      fail('invalid_cursor', 'The page cursor is invalid or belongs to another server process.');
    const decoded = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    if (decoded.scope !== scope || !Number.isSafeInteger(decoded.offset) || decoded.offset < 0)
      fail(
        'cursor_mismatch',
        'The page cursor does not match this exact binding, filter and page size.',
        409,
      );
    return decoded.offset;
  }
  async read(request: ReadRequest): Promise<ReadResult> {
    const deadline = Date.now() + this.deadlineMs;
    if (!isObject(request)) fail('invalid_request', 'A read request object is required.');
    const loaded = await this.selected(request.catalogId, request.catalogSha256, deadline),
      snapshot = loaded.snapshot;
    const binding: ExactBinding = {
      datasetId: request.datasetId,
      versionId: request.versionId,
      representationId: request.representationId,
      ...(request.releaseId !== undefined ? { releaseId: request.releaseId } : {}),
    };
    const checked = checkedBinding(snapshot, binding);
    if (checked.refusal) return checked.refusal;
    const limit = pageLimit(request.limit);
    checkedFilter(request.filter);
    const scope = sha256(
      JSON.stringify({
        catalogSha256: request.catalogSha256,
        binding,
        filter: request.filter,
        limit,
      }),
    );
    const offset = this.offset(request.cursor, scope);
    const reader =
      loaded.registration.mode === 'fixture'
        ? this.fixture
        : this.adapters.get(snapshot.id)?.reader;
    if (!reader)
      return empty(
        binding,
        'refused',
        'No qualified owner reader is registered for this application catalog.',
      );
    let page: {
      rows: ExactObject[];
      rowPositions: number[];
      total?: number;
      hasMore?: boolean;
      consumed: ExactBinding;
      record?: RecordRef;
    };
    if (request.filter && reader === this.fixture) {
      const rows = await this.fixture.all(loaded, binding, deadline);
      const matches = rows
        .map((row, index) => ({ row, index }))
        .filter((item) =>
          fieldValues(item.row, request.filter!.path).some((value) =>
            exactEqual(value, request.filter!.equals),
          ),
        );
      const selected = matches.slice(offset, offset + limit);
      const file = snapshot.lock.files.find(
        (row) => row.role === 'data' && row.identity === binding.representationId,
      )!;
      page = {
        rows: selected.map((item) => item.row),
        rowPositions: selected.map((item) => item.index),
        total: matches.length,
        consumed: binding,
        record: { uri: `urn:sha256:${file.sha256}`, sha256: file.sha256 },
      };
    } else {
      if (request.filter)
        return empty(
          binding,
          'refused',
          'This owner adapter has not declared support for generic filters.',
        );
      if (reader === this.fixture)
        page = await this.fixture.read({ snapshot, binding, offset, limit, deadline });
      else {
        try {
          page = await this.callOwner(
            (signal) => reader.read({ snapshot, binding, offset, limit, deadline, signal }),
            deadline,
          );
        } catch (error) {
          if (error instanceof ViewerError && ['owner_deadline', 'owner_busy'].includes(error.code))
            return empty(binding, 'unknown', error.message);
          throw error;
        }
      }
    }
    validatePage(page, limit, offset);
    if (!sameBinding(page.consumed, binding))
      fail(
        'adapter_binding',
        'The owner receipt does not identify the exact requested input.',
        409,
      );
    const continuation =
      page.total !== undefined
        ? offset + page.rows.length < page.total
          ? 'more'
          : 'complete'
        : page.hasMore !== undefined
          ? page.hasMore
            ? 'more'
            : 'complete'
          : 'unknown';
    return resultBudget({
      status: 'ok',
      binding,
      rows: page.rows,
      rowPositions: page.rowPositions,
      columns: rowColumns(page.rows),
      returned: page.rows.length,
      ...(page.total !== undefined ? { total: page.total } : {}),
      ...(continuation !== 'unknown' ? { hasMore: continuation === 'more' } : {}),
      continuation,
      ...(continuation === 'more'
        ? { nextCursor: this.cursor(scope, offset + page.rows.length) }
        : {}),
      transport: TRANSPORT,
      readEvidence: {
        kind: reader === this.fixture ? 'fixture' : 'owner',
        consumed: page.consumed,
        ...(page.record ? { record: page.record } : {}),
      },
      ...(checked.release ? { release: checked.release } : {}),
    });
  }
  async query(request: QueryRequest): Promise<QueryResult> {
    const deadline = Date.now() + this.deadlineMs;
    if (!isObject(request) || !isObject(request.bindings) || !isObject(request.parameters))
      fail('invalid_request', 'Recipe bindings and exact parameters are required.');
    text(request.recipeId, 'recipeId');
    const loaded = await this.selected(request.catalogId, request.catalogSha256, deadline),
      { snapshot } = loaded;
    const recipe = snapshot.catalog.recipes.find((row) => row.id === request.recipeId);
    if (!recipe) fail('unknown_recipe', 'This recipe is absent from the selected catalog.', 404);
    const names = Object.keys(recipe.inputs).sort(),
      bound = Object.keys(request.bindings).sort();
    if (names.length !== bound.length || names.some((name, index) => name !== bound[index]))
      fail(
        'recipe_inputs',
        'Bind exactly the recipe execution inputs. Context relationships do not add inputs.',
        409,
      );
    const bindings: Record<string, ExactBinding> = Object.create(null);
    for (const name of names) {
      const supplied = request.bindings[name];
      if (
        request.releaseId !== undefined &&
        supplied.releaseId !== undefined &&
        request.releaseId !== supplied.releaseId
      )
        fail(
          'release_mismatch',
          'The input release differs from the requested query release.',
          409,
        );
      const binding =
        request.releaseId !== undefined ? { ...supplied, releaseId: request.releaseId } : supplied;
      const result = checkedBinding(snapshot, binding);
      if (result.refusal) return { ...result.refusal, bindings: request.bindings };
      const dataset = snapshot.catalog.datasets.find((row) => row.id === binding.datasetId)!;
      if (dataset.alias !== recipe.inputs[name])
        fail('recipe_inputs', 'A recipe input is bound to a different logical dataset.', 409);
      bindings[name] = binding;
    }
    const requiredRelationships = snapshot.catalog.relationships.filter((row) =>
      recipe.relationships.includes(row.id),
    );
    if (requiredRelationships.length !== recipe.relationships.length)
      fail('recipe_relationships', 'A required recipe relationship is absent.', 409);
    if (
      requiredRelationships.some(
        (row) => !['same_release', 'version_pair'].includes(row.scope) || 'external' in row.target,
      )
    )
      return {
        status: 'unknown',
        reason:
          'The recipe requires a relationship scope that the pinned DDK resolver cannot bind. A project-specific scope resolver is required.',
        bindings,
        rows: [],
        columns: [],
        returned: 0,
        transport: TRANSPORT,
      };
    if (requiredRelationships.some((row) => row.scope === 'same_release')) {
      const releaseId = request.releaseId;
      text(releaseId, 'releaseId');
      const release = snapshot.catalog.releases.find((row) => row.id === releaseId);
      if (
        !release ||
        release.membership !== 'complete' ||
        Object.values(bindings).some((binding) => !release.members.includes(binding.versionId))
      )
        fail(
          'release_mismatch',
          'Same-release recipe inputs must belong to one explicit complete release.',
          409,
        );
    }
    const limit = pageLimit(request.limit);
    const sql = await this.store.companion(snapshot.id, request.catalogSha256, recipe.sql);
    const native = this.adapters.get(snapshot.id)?.query;
    if (loaded.registration.mode !== 'fixture') {
      if (!native)
        return {
          status: 'refused',
          reason: 'No qualified owner query adapter is registered for this application catalog.',
          bindings,
          rows: [],
          columns: [],
          returned: 0,
          transport: TRANSPORT,
        };
      let result: QueryResult;
      try {
        result = await this.callOwner(
          (signal) =>
            native.query({
              snapshot,
              recipeId: recipe.id,
              bindings,
              parameters: request.parameters,
              sql,
              limit,
              deadline,
              signal,
            }),
          deadline,
        );
      } catch (error) {
        if (error instanceof ViewerError && ['owner_deadline', 'owner_busy'].includes(error.code))
          return {
            status: 'unknown',
            reason: error.message,
            bindings,
            rows: [],
            columns: [],
            returned: 0,
            transport: TRANSPORT,
          };
        throw error;
      }
      if (
        !isObject(result) ||
        !['ok', 'unknown', 'refused'].includes(result.status) ||
        result.transport !== TRANSPORT ||
        !isObject(result.bindings) ||
        Object.keys(result.bindings).length !== names.length ||
        names.some((name) => !sameBinding(result.bindings[name], bindings[name]))
      )
        fail(
          'adapter_binding',
          'The owner query receipt differs from its exact requested inputs.',
          409,
        );
      validatePage(
        {
          ...result,
          rowPositions:
            result.rowPositions ??
            (result.status !== 'ok' && result.rows.length === 0 ? [] : undefined),
        },
        limit,
      );
      if (
        result.returned !== result.rows.length ||
        (result.status !== 'ok' && result.rows.length !== 0) ||
        (result.status === 'ok' &&
          (!result.execution ||
            result.execution.kind !== 'owner' ||
            result.execution.recipeId !== recipe.id ||
            result.execution.sqlSha256 !== sha256(sql)))
      )
        fail('adapter_receipt', 'The owner query result has an invalid execution receipt.', 409);
      return resultBudget({ ...result, columns: rowColumns(result.rows) });
    }
    const registered = FIXTURE_RECIPES[recipe.id as keyof typeof FIXTURE_RECIPES];
    if (
      !registered ||
      registered.catalog !== snapshot.id ||
      recipe.sql !== `recipes/${registered.input}-minimum.sql` ||
      sql.toString('utf8') !== registered.sql ||
      names.length !== 1 ||
      names[0] !== 'records' ||
      recipe.inputs.records !== registered.input
    )
      fail(
        'unregistered_recipe',
        'The fixture evaluator refuses an unregistered or changed recipe companion.',
        409,
      );
    const parameters = Object.keys(request.parameters);
    if (parameters.length !== 1 || parameters[0] !== registered.parameter)
      fail('invalid_parameters', 'Supply exactly the declared recipe parameter.');
    const raw = request.parameters[registered.parameter];
    const minimum = isExactNumber(raw)
      ? raw.$number
      : typeof raw === 'string' && validNumber(raw)
        ? raw
        : undefined;
    if (minimum === undefined)
      fail(
        'invalid_parameters',
        'Enter the recipe number as an exact numeric string or $number value.',
      );
    const rows = await this.fixture.all(loaded, bindings.records, deadline);
    const matches = rows
      .map((row, index) => ({ row, index }))
      .filter((item) => {
        const value = exactObjectField(item.row, registered.field);
        return isExactNumber(value) && compareExactNumbers(value.$number, minimum) >= 0;
      });
    const selected = matches.slice(0, limit);
    return resultBudget({
      status: 'ok',
      bindings,
      rows: selected.map((item) => item.row),
      rowPositions: selected.map((item) => item.index),
      columns: rowColumns(selected.map((item) => item.row)),
      returned: selected.length,
      total: matches.length,
      transport: TRANSPORT,
      execution: {
        kind: 'fixture',
        recipeId: recipe.id,
        sqlSha256: sha256(sql),
        inputs: names,
        contextualRelationships: recipe.contextualRelationships ?? [],
      },
    });
  }
}
