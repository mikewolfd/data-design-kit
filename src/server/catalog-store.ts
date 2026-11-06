import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { realpath } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { isObject, parseMetadata } from '../domain/exact';
import type {
  Catalog,
  CatalogField,
  CatalogLock,
  CatalogReport,
  CatalogSnapshot,
} from '../domain/types';

export const ASSEMBLY = 'urn:ddk:catalog:assembly';
export const OUTPUT_SET = 'urn:ddk:catalog:output-set';
export const LIMITS = Object.freeze({
  fileBytes: 8 * 1024 * 1024,
  retainedBytes: 32 * 1024 * 1024,
  files: 64,
  catalogs: 8,
  parsedCatalogs: 2,
  rows: 10_000,
  pageRows: 100,
  resultBytes: 256 * 1024,
  requestBytes: 64 * 1024,
  deadlineMs: 5000,
});
export class ViewerError extends Error {
  constructor(
    public code: string,
    message: string,
    public status = 400,
  ) {
    super(message);
  }
}
export function fail(code: string, message: string, status = 400): never {
  throw new ViewerError(code, message, status);
}
export const sha256 = (bytes: Uint8Array | string): string =>
  createHash('sha256').update(bytes).digest('hex');
const digest = (value: unknown): value is string =>
  typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export function relativePath(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !value ||
    /[\\%?#:\x00-\x1f]/.test(value) ||
    value.startsWith('/') ||
    value.split('/').some((part) => !part || part === '.' || part === '..')
  )
    fail('invalid_path', 'The requested file is not a safe catalog-relative companion.');
  return value;
}
export type CatalogRegistration = {
  id: string;
  directory: string;
  lockSha256: string;
  mode: 'fixture' | 'application';
  navigationLabel?: string;
};
export type LoadedCatalog = {
  snapshot: CatalogSnapshot;
  outputFiles: ReadonlyMap<string, { path: string; sha256: string; role: string }>;
  registration: CatalogRegistration;
};
function unique(values: unknown[], label: string) {
  if (
    values.some((value) => typeof value !== 'string' || !value) ||
    new Set(values).size !== values.length
  )
    fail('ambiguous_catalog', `The catalog contains invalid or duplicate ${label}.`, 409);
}
function freeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) freeze(child);
  }
  return value;
}
function validateStructure(raw: any, report: any, lock: any) {
  if (
    !isObject(raw) ||
    raw.kind !== 'catalog' ||
    raw.specVersion !== '0.1' ||
    !isObject(raw.project) ||
    raw.project.id !== lock.project ||
    typeof raw.project.version !== 'string' ||
    !['public', 'local'].includes(raw.audience)
  )
    fail('invalid_catalog', 'The catalog identity does not match the pinned lock.', 409);
  const arrays = [
    'sourceInventory',
    'adapters',
    'datasets',
    'products',
    'versions',
    'representations',
    'releases',
    'selections',
    'relationships',
    'identities',
    'sources',
    'checks',
    'files',
    'recipes',
    'runs',
    'productions',
  ];
  if (
    arrays.some(
      (key) =>
        !Array.isArray(raw[key]) ||
        raw[key].length > 20_000 ||
        raw[key].some((row: unknown) => !isObject(row)),
    )
  )
    fail('invalid_catalog', 'The catalog is missing supported inventory records.', 409);
  if (
    !isObject(report) ||
    report.kind !== 'report' ||
    report.specVersion !== '0.1' ||
    !['passed', 'failed', 'incomplete', 'error'].includes(report.decision) ||
    !Array.isArray(report.checks) ||
    report.checks.some(
      (row: any) =>
        !isObject(row) ||
        !['passed', 'failed', 'unknown', 'not_run'].includes(row.status) ||
        typeof row.required !== 'boolean' ||
        typeof row.applicable !== 'boolean',
    )
  )
    fail('invalid_report', 'The catalog report has an unsupported shape.', 409);
  if (
    report.decision === 'passed' &&
    report.checks.some((row: any) => row.required && row.applicable && row.status !== 'passed')
  )
    fail('invalid_report', 'A passing report contradicts an incomplete required check.', 409);
  for (const key of [
    'datasets',
    'versions',
    'representations',
    'releases',
    'relationships',
    'recipes',
    'sources',
    'runs',
  ])
    unique(
      raw[key].map((row: any) => row.id),
      key,
    );
  unique(
    raw.datasets.map((row: any) => row.alias),
    'dataset aliases',
  );
  unique(
    raw.files.map((row: any) => row.path),
    'companion paths',
  );
  const aliases = new Set(raw.datasets.map((row: any) => row.alias)),
    versionIds = new Set(raw.versions.map((row: any) => row.id));
  if (
    raw.versions.some(
      (row: any) =>
        !aliases.has(row.dataset) ||
        !['present', 'missing', 'unknown'].includes(row.retention) ||
        !Array.isArray(row.sources),
    ) ||
    raw.representations.some(
      (row: any) =>
        !versionIds.has(row.version) ||
        !['available', 'unavailable', 'unknown'].includes(row.availability),
    ) ||
    raw.releases.some(
      (row: any) =>
        !Array.isArray(row.members) ||
        new Set(row.members).size !== row.members.length ||
        row.members.some((id: string) => !versionIds.has(id)),
    )
  )
    fail('invalid_references', 'The catalog has unresolved version or release references.', 409);
  const definitions = raw.extensions?.[ASSEMBLY]?.datasetDefinitions ?? {};
  if (
    !isObject(definitions) ||
    raw.datasets.some(
      (row: any) =>
        !isObject(row.definition) ||
        (definitions[row.alias] !== undefined &&
          (!isObject(definitions[row.alias]) || typeof definitions[row.alias].name !== 'string')),
    )
  )
    fail('invalid_definitions', 'The admitted dataset definitions are invalid.', 409);
}

/** Only composition-root registrations can select directories and external lock pins. */
export class CatalogStore {
  readonly registrations: ReadonlyMap<string, CatalogRegistration>;
  private raw = new Map<string, Buffer>();
  private parsed = new Map<string, LoadedCatalog>();
  private pending = new Map<string, Promise<LoadedCatalog>>();
  private retainedRaw = 0;
  private parsedBytes = new Map<string, number>();
  private rawCatalogs = new Map<string, number>();
  private loadErrors = new Map<string, { id: string; code: string; reason: string }>();
  constructor(
    registrations: CatalogRegistration[],
    public readonly audience: 'public' | 'local' = 'public',
  ) {
    if (registrations.length > LIMITS.catalogs)
      fail('catalog_budget', 'Too many catalog registrations.');
    unique(
      registrations.map((row) => row.id),
      'registered catalog IDs',
    );
    if (
      registrations.some(
        (row) => !/^[a-z0-9][a-z0-9-]{0,63}$/.test(row.id) || !digest(row.lockSha256),
      )
    )
      fail(
        'invalid_registration',
        'A catalog registration needs a safe ID and exact external lock digest.',
      );
    this.registrations = new Map(registrations.map((row) => [row.id, Object.freeze({ ...row })]));
  }
  private evict(needed = 0, keepId?: string, addingParsed = false) {
    const overBudget = () =>
      this.retainedRaw + [...this.parsedBytes.values()].reduce((a, b) => a + b, 0) + needed >
      LIMITS.retainedBytes;
    while (
      overBudget() ||
      (addingParsed && this.parsed.size >= LIMITS.parsedCatalogs) ||
      (keepId && !this.rawCatalogs.has(keepId) && this.rawCatalogs.size >= LIMITS.parsedCatalogs)
    ) {
      const first = [...this.rawCatalogs.keys()].find(
        (id) => id !== keepId && !this.pending.has(id),
      );
      if (!first) break;
      this.parsed.delete(first);
      this.parsedBytes.delete(first);
      this.rawCatalogs.delete(first);
      for (const [key, bytes] of this.raw)
        if (key.startsWith(first + '\0')) {
          this.retainedRaw -= bytes.byteLength;
          this.raw.delete(key);
        }
    }
    if (
      this.retainedRaw + [...this.parsedBytes.values()].reduce((a, b) => a + b, 0) + needed >
      LIMITS.retainedBytes
    )
      fail('cache_budget', 'The registered catalog bytes exceed the retained process budget.', 413);
  }
  async readPinned(
    registration: CatalogRegistration,
    path: string,
    expected: string,
    deadline: number,
    cap = LIMITS.fileBytes,
  ): Promise<Buffer> {
    relativePath(path);
    if (!digest(expected)) fail('invalid_digest', 'A file inventory digest is invalid.', 409);
    const key = `${registration.id}\0${registration.directory}\0${path}\0${expected}`;
    const cached = this.raw.get(key);
    if (cached) {
      if (cached.byteLength > cap)
        fail('file_budget', 'A cached catalog file exceeds the caller byte budget.', 413);
      this.rawCatalogs.delete(registration.id);
      this.rawCatalogs.set(registration.id, Date.now());
      return Buffer.from(cached);
    }
    if (Date.now() >= deadline) fail('deadline', 'The catalog read exceeded its deadline.', 408);
    const root = await realpath(registration.directory);
    const target = await realpath(resolve(root, path));
    if (!target.startsWith(root + sep))
      fail('unsafe_file', 'A registered companion leaves its catalog directory.', 409);
    const chunks: Buffer[] = [];
    let size = 0;
    const stream = createReadStream(target, {
      highWaterMark: 64 * 1024,
      signal: AbortSignal.timeout(Math.max(1, deadline - Date.now())),
    });
    try {
      for await (const part of stream) {
        const chunk = part as Buffer;
        size += chunk.length;
        if (size > cap)
          fail('file_budget', 'A catalog file exceeds the supported byte budget.', 413);
        if (Date.now() >= deadline)
          fail('deadline', 'The catalog read exceeded its deadline.', 408);
        chunks.push(chunk);
      }
    } catch (error) {
      stream.destroy();
      throw error;
    }
    const bytes = Buffer.concat(chunks, size);
    if (sha256(bytes) !== expected)
      fail(
        'integrity_mismatch',
        'The pinned catalog or companion bytes do not match their exact digest.',
        409,
      );
    this.evict(size, registration.id);
    this.raw.set(key, bytes);
    this.retainedRaw += size;
    this.rawCatalogs.delete(registration.id);
    this.rawCatalogs.set(registration.id, Date.now());
    return Buffer.from(bytes);
  }
  async load(id: string, deadline = Date.now() + LIMITS.deadlineMs): Promise<LoadedCatalog> {
    const cached = this.parsed.get(id);
    if (cached) {
      this.parsed.delete(id);
      this.parsed.set(id, cached);
      return cached;
    }
    const pending = this.pending.get(id);
    if (pending) return pending;
    const registration = this.registrations.get(id);
    if (!registration) fail('unknown_catalog', 'This catalog is not registered.', 404);
    if (this.pending.size >= LIMITS.parsedCatalogs)
      fail('server_busy', 'Two catalog sets are already loading. Retry this request shortly.', 503);
    const promise = this.loadRegistered(registration, deadline);
    this.pending.set(id, promise);
    try {
      const result = await promise;
      this.loadErrors.delete(id);
      return result;
    } catch (error) {
      this.loadErrors.set(id, {
        id,
        code: error instanceof ViewerError ? error.code : 'catalog_unavailable',
        reason:
          error instanceof ViewerError
            ? error.message
            : 'This registered catalog is currently unavailable.',
      });
      throw error;
    } finally {
      this.pending.delete(id);
    }
  }
  private async loadRegistered(
    registration: CatalogRegistration,
    deadline: number,
  ): Promise<LoadedCatalog> {
    const lockBytes = await this.readPinned(
      registration,
      'catalog.lock.json',
      registration.lockSha256,
      deadline,
    );
    const lock = parseMetadata(new TextDecoder('utf-8', { fatal: true }).decode(lockBytes));
    if (
      !isObject(lock) ||
      lock.kind !== 'lock' ||
      lock.specVersion !== '0.1' ||
      !Array.isArray(lock.files) ||
      lock.files.length > LIMITS.files ||
      !isObject(lock.catalogOptions)
    )
      fail('invalid_lock', 'A supported standard catalog lock is required.', 409);
    if (this.audience === 'public' && lock.catalogOptions.audience !== 'public')
      fail(
        'audience_refused',
        'Public mode refuses internal catalog sets. An owner-produced public set is required.',
        403,
      );
    const output = lock.extensions?.[OUTPUT_SET];
    if (!Array.isArray(output) || output.length < 2 || output.length > LIMITS.files)
      fail(
        'invalid_inventory',
        'The standard output inventory is missing or exceeds its file budget.',
        409,
      );
    const companions = new Map<string, Buffer>(),
      outputRows = new Map<string, any>();
    for (const row of output) {
      if (!isObject(row) || !digest(row.sha256) || typeof row.role !== 'string')
        fail('invalid_inventory', 'The output inventory has an invalid entry.', 409);
      relativePath(row.path);
      if (outputRows.has(row.path) || row.path === 'catalog.lock.json')
        fail(
          'invalid_inventory',
          'The output inventory contains duplicate or circular entries.',
          409,
        );
      outputRows.set(row.path, row);
    }
    if (
      outputRows.get('catalog.ddk.json')?.role !== 'catalog' ||
      outputRows.get('catalog.report.json')?.role !== 'report'
    )
      fail('invalid_inventory', 'The standard catalog and report are required.', 409);
    // Definitions need only the standard catalog and report. SQL is read on demand.
    for (const path of ['catalog.ddk.json', 'catalog.report.json'])
      companions.set(
        path,
        await this.readPinned(registration, path, outputRows.get(path).sha256, deadline),
      );
    const catalog = parseMetadata(
      new TextDecoder('utf-8', { fatal: true }).decode(companions.get('catalog.ddk.json')!),
    );
    const report = parseMetadata(
      new TextDecoder('utf-8', { fatal: true }).decode(companions.get('catalog.report.json')!),
    );
    validateStructure(catalog, report, lock);
    if (
      catalog.audience !== lock.catalogOptions.audience ||
      (this.audience === 'public' && catalog.audience !== 'public')
    )
      fail('audience_refused', 'The catalog audience differs from its selected lock.', 403);
    if (
      catalog.files.length !== outputRows.size - 1 ||
      catalog.files.some(
        (row: any) =>
          row.path === 'catalog.ddk.json' ||
          row.sha256 !== outputRows.get(row.path)?.sha256 ||
          row.role !== outputRows.get(row.path)?.role,
      )
    )
      fail(
        'inventory_mismatch',
        'The catalog companion inventory differs from its pinned lock.',
        409,
      );
    for (const recipe of catalog.recipes)
      if (outputRows.get(recipe.sql)?.role !== 'recipe')
        fail('missing_recipe_companion', 'A recipe is missing its exact SQL companion.', 409);
    const inputDigests = new Map<string, string>();
    for (const row of lock.files) {
      if (
        !isObject(row) ||
        typeof row.path !== 'string' ||
        !row.path ||
        !digest(row.sha256) ||
        (inputDigests.has(row.path) && inputDigests.get(row.path) !== row.sha256)
      )
        fail(
          'ambiguous_catalog',
          'The lock has invalid or conflicting bytes for one input path.',
          409,
        );
      // Several schema objects can select the same exact source file. Preserve every record.
      inputDigests.set(row.path, row.sha256);
    }
    const marker = catalog.extensions?.['urn:ddk-viewer:fixture'];
    if (registration.mode === 'fixture' && (!isObject(marker) || marker.synthetic !== true))
      fail('invalid_fixture', 'The registered fixture has no explicit synthetic marker.', 409);
    const snapshot: CatalogSnapshot = freeze({
      id: registration.id,
      title: marker?.title ?? registration.navigationLabel ?? catalog.project.id,
      description:
        marker?.description ??
        'Read-only application catalog. Data access requires an injected, independently qualified owner adapter.',
      mode: registration.mode,
      audience: catalog.audience,
      catalog: catalog as Catalog,
      report: report as CatalogReport,
      lock: lock as CatalogLock,
      identity: {
        catalogSha256: outputRows.get('catalog.ddk.json').sha256,
        reportSha256: outputRows.get('catalog.report.json').sha256,
        lockSha256: registration.lockSha256,
      },
      capabilities: {
        read: registration.mode === 'fixture',
        query: registration.mode === 'fixture',
        ...(registration.mode === 'application'
          ? {
              reason:
                'Discovery only: no native reader or query adapter is registered for this application set.',
            }
          : {}),
      },
      definitions: (catalog.extensions?.[ASSEMBLY]?.datasetDefinitions ?? {}) as Record<
        string,
        CatalogField
      >,
    });
    // This counts retained wire bytes and serialized parsed metadata, not measured JS heap.
    const size = Buffer.byteLength(JSON.stringify(snapshot));
    this.evict(size, registration.id, true);
    const loaded = { snapshot, outputFiles: outputRows, registration };
    this.parsed.set(registration.id, loaded);
    this.parsedBytes.set(registration.id, size);
    return loaded;
  }
  async snapshot(id: string): Promise<CatalogSnapshot> {
    return (await this.load(id)).snapshot;
  }
  async list() {
    // Labels identify navigation targets only. Facts and admission come from the selected set.
    const catalogs = [...this.registrations.values()].map((row) => {
      const snapshot = this.parsed.get(row.id)?.snapshot;
      return {
        id: row.id,
        title: snapshot?.title ?? row.navigationLabel ?? row.id,
        description:
          snapshot?.description ??
          `Pinned ${row.mode} registration. Admission is checked when selected.`,
        mode: row.mode,
        audience: snapshot?.audience ?? this.audience,
        admission: snapshot ? ('admitted' as const) : ('not_loaded' as const),
      };
    });
    return { catalogs, unavailable: [...this.loadErrors.values()] };
  }
  async companion(id: string, catalogSha256: string, path: string) {
    const loaded = await this.load(id);
    if (loaded.snapshot.identity.catalogSha256 !== catalogSha256)
      fail('catalog_mismatch', 'The request does not match the exact selected catalog.', 409);
    relativePath(path);
    if (!loaded.snapshot.catalog.files.some((row) => row.path === path))
      fail('unknown_companion', 'This file is not a companion of the selected catalog.', 404);
    const selected = loaded.outputFiles.get(path)!;
    return this.readPinned(
      loaded.registration,
      path,
      selected.sha256,
      Date.now() + LIMITS.deadlineMs,
      1024 * 1024,
    );
  }
}
