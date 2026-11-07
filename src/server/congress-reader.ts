import { createReadStream } from 'node:fs';
import { readFile, realpath, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, isAbsolute, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { ExactObject, ExactValue } from '../domain/types';
import { validNumber } from '../domain/exact';
import type { OwnerAdapters } from './access';
import { fail, LIMITS, sha256, ViewerError } from './catalog-store';
import { bindCongressInput, loadCongressInputs } from './congress-registration';

const MODULE = 'apps/site/src/components/explorer/reader/archive.ts';
const TRANSPORT = 'apps/site/scripts/archive-server.mjs';
const SOURCE_LIMIT = 16 * 1024 * 1024;
const WORKING_LIMIT = 16 * 1024 * 1024;
type ModulePin = { path: string; sha256: string };
type OwnerConfig = { root: string; files: ModulePin[]; sourceRevision?: string };
type OwnerModule = {
  openArchive: (
    url: string,
    options: Record<string, unknown>,
  ) => Promise<{
    readRows: (name: string, options: Record<string, unknown>) => Promise<any>;
  }>;
  isArchiveDateValue: (value: unknown) => boolean;
  isArchiveTimestampValue: (value: unknown) => boolean;
};
type Origin = { pointerUrl: string; close: () => Promise<void> };
type TransportModule = {
  startArchiveServer: (options: { release: Readonly<Record<string, string>> }) => Promise<Origin>;
};

/** Optional fields in the owner's schema objects are absent, not data nulls. */
function presentSchemaFields(value: any): any {
  if (Array.isArray(value)) return value.map(presentSchemaFields);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, child]) => child !== undefined)
        .map(([name, child]) => [name, presentSchemaFields(child)]),
    );
  return value;
}

async function pinnedSource(
  path: string,
  expectedSha: string,
  signal?: AbortSignal,
): Promise<Buffer> {
  const hash = createHash('sha256');
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of createReadStream(path, { signal })) {
    size += chunk.length;
    if (size > SOURCE_LIMIT)
      fail('owner_module_budget', 'The owner module exceeds its read limit.', 413);
    hash.update(chunk);
    chunks.push(chunk as Buffer);
  }
  if (hash.digest('hex') !== expectedSha)
    fail('integrity_mismatch', 'The configured Congress owner source changed.', 409);
  return Buffer.concat(chunks, size);
}

/** Paths come only from an operator-pinned configuration, never catalog or HTTP input. */
async function checkedConfig(path: string, expectedSha: string): Promise<OwnerConfig> {
  if (!isAbsolute(path) || !/^[a-f0-9]{64}$/.test(expectedSha))
    fail(
      'invalid_registration',
      'The Congress owner configuration needs an absolute path and SHA-256.',
    );
  if ((await stat(path)).size > 128 * 1024)
    fail('owner_module_budget', 'The owner configuration exceeds its read limit.', 413);
  const bytes = await readFile(path);
  if (sha256(bytes) !== expectedSha)
    fail('integrity_mismatch', 'The Congress owner configuration changed.', 409);
  const config = JSON.parse(bytes.toString('utf8')) as OwnerConfig;
  if (
    !config ||
    !isAbsolute(config.root) ||
    !Array.isArray(config.files) ||
    config.files.length < 2 ||
    config.files.length > 64 ||
    new Set(config.files.map((entry) => entry.path)).size !== config.files.length ||
    config.files.some(
      (entry) =>
        typeof entry.path !== 'string' ||
        !/^[a-zA-Z0-9_./-]+$/.test(entry.path) ||
        isAbsolute(entry.path) ||
        entry.path.split('/').some((part) => !part || part === '.' || part === '..') ||
        !/^[a-f0-9]{64}$/.test(entry.sha256),
    ) ||
    ![MODULE, TRANSPORT, 'apps/site/package.json', 'apps/site/package-lock.json'].every((path) =>
      config.files.some((entry) => entry.path === path),
    )
  )
    fail('invalid_registration', 'The Congress owner source allowlist is invalid.');
  config.root = await realpath(config.root);
  return config;
}

async function checkSources(config: OwnerConfig, signal?: AbortSignal) {
  const sources = new Map<string, Buffer>();
  let total = 0;
  for (const entry of config.files) {
    signal?.throwIfAborted();
    const path = resolve(config.root, entry.path);
    if (!path.startsWith(config.root + sep) || (await realpath(path)) !== path)
      fail('integrity_mismatch', 'The configured Congress owner source changed.', 409);
    const bytes = await pinnedSource(path, entry.sha256, signal);
    total += bytes.length;
    if (total > SOURCE_LIMIT)
      fail('owner_module_budget', 'The owner source allowlist exceeds its total read limit.', 413);
    sources.set(path, bytes);
  }
  // Use the maintained TypeScript scanner to establish the relative source
  // imports before any owner module executes. Dependency versions remain owned
  // by the separately pinned package files, not a viewer package resolver.
  const { preProcessFile } = await import('typescript');
  const visited = new Set<string>();
  const visit = (path: string) => {
    if (visited.has(path)) return;
    visited.add(path);
    const bytes = sources.get(path);
    if (!bytes)
      fail(
        'owner_module_unpinned',
        'A Congress owner import is absent from the source allowlist.',
        409,
      );
    if (!/\.[cm]?[jt]s$/.test(path)) return;
    for (const imported of preProcessFile(bytes.toString('utf8'), true, true).importedFiles) {
      if (imported.fileName.startsWith('.')) visit(resolve(dirname(path), imported.fileName));
      else if (
        isAbsolute(imported.fileName) ||
        (/^[a-z][a-z0-9+.-]*:/i.test(imported.fileName) && !imported.fileName.startsWith('node:'))
      )
        fail(
          'owner_module_unpinned',
          'Congress owner source imports must stay within the relative source allowlist.',
          409,
        );
    }
  };
  visit(resolve(config.root, MODULE));
  visit(resolve(config.root, TRANSPORT));
  signal?.throwIfAborted();
}

/** Convert owned raw values, retaining the owner's temporal units and original schema. */
export function encodeCongressValue(
  value: unknown,
  owner: Pick<OwnerModule, 'isArchiveDateValue' | 'isArchiveTimestampValue'>,
): ExactValue {
  let nodes = 0;
  const visit = (item: any, depth: number): ExactValue => {
    if (++nodes > 300_000 || depth > 48)
      fail('adapter_budget', 'The Congress page exceeds the structure limit.', 413);
    if (item === null || typeof item === 'boolean' || typeof item === 'string') return item;
    if (typeof item === 'bigint' || typeof item === 'number') {
      const lexeme = typeof item === 'number' && Object.is(item, -0) ? '-0' : String(item);
      if (!validNumber(lexeme))
        fail(
          'owner_unsupported_type',
          'The Congress page contains a non-finite or unsupported number.',
          422,
        );
      return { $number: lexeme };
    }
    if (item instanceof Uint8Array)
      return { type: 'binary', encoding: 'base64', value: Buffer.from(item).toString('base64') };
    if (Array.isArray(item)) return item.map((child) => visit(child, depth + 1));
    if (item && typeof item === 'object') {
      // The maintained guards use a private marker. A source struct with these
      // same public fields remains an ordinary struct, never a guessed date.
      if (owner.isArchiveDateValue(item))
        return { type: 'date', days: visit(item.days, depth + 1) };
      if (owner.isArchiveTimestampValue(item))
        return { type: 'timestamp', unit: item.unit, value: visit(item.value, depth + 1) };
      const entries = Object.entries(item).map(
        ([key, child]) => [key, visit(child, depth + 1)] as [string, ExactValue],
      );
      return entries.some(([key]) => key === '$number' || key === '$object')
        ? { $object: entries }
        : Object.fromEntries(entries);
    }
    fail(
      'owner_unsupported_type',
      'The Congress page contains a value this viewer cannot preserve.',
      422,
    );
  };
  return visit(value, 0);
}

export async function createCongressAdapter(options: {
  configPath: string;
  configSha256: string;
  supportedDatasetIds: readonly string[];
}): Promise<OwnerAdapters> {
  const config = await checkedConfig(options.configPath, options.configSha256);
  await checkSources(config);
  // Runtime imports keep synthetic and catalog-only builds independent of an
  // external Congress checkout. This local source adapter requires installed tsx.
  let modules: Promise<{ owner: OwnerModule; transport: TransportModule }> | undefined;
  const load = () =>
    (modules ??= (async () => {
      const { tsImport } = await import('tsx/esm/api');
      const owner = (await tsImport(
        pathToFileURL(resolve(config.root, MODULE)).href,
        import.meta.url,
      )) as OwnerModule;
      const transport = (await import(
        /* @vite-ignore */ pathToFileURL(resolve(config.root, TRANSPORT)).href
      )) as TransportModule;
      if (
        typeof owner.openArchive !== 'function' ||
        typeof owner.isArchiveDateValue !== 'function' ||
        typeof owner.isArchiveTimestampValue !== 'function' ||
        typeof transport.startArchiveServer !== 'function'
      )
        fail(
          'owner_unavailable',
          'The configured Congress owner does not expose the maintained raw-row interface.',
          503,
        );
      return { owner, transport };
    })());
  return {
    reader: {
      supportedDatasetIds: options.supportedDatasetIds,
      description:
        'Read saved authored example records through the Congress archive reader. Queries and generic filters are not connected. Original date and timestamp units are retained.',
      async read({ snapshot, binding, offset, limit, deadline, signal }) {
        signal.throwIfAborted();
        if (Date.now() >= deadline) fail('owner_deadline', 'The Congress read timed out.', 408);
        const inputs = await loadCongressInputs(snapshot, { deadline, signal });
        const input = bindCongressInput(inputs, snapshot, binding);
        if (
          inputs.manifest.files.reduce((sum: number, file: any) => sum + file.size, 0) >
          SOURCE_LIMIT
        )
          fail(
            'adapter_budget',
            'This local Congress transport exceeds its verified-release size limit.',
            413,
          );
        await checkSources(config, signal);
        const { owner, transport } = await load();
        let origin: Origin | undefined;
        try {
          origin = await transport.startArchiveServer({ release: inputs.files });
          signal.throwIfAborted();
          const reader = await owner.openArchive(origin.pointerUrl, {
            releaseId: inputs.releaseId,
            mode: 'rows',
            signal,
            heapBytes: 32 * 1024 * 1024,
            cacheBytes: 8 * 1024 * 1024,
            indexBytes: 4 * 1024 * 1024,
          });
          const page = await reader.readRows(input.name, {
            offset,
            limit,
            maxBytes: WORKING_LIMIT,
            signal,
          });
          const expectedEnd = Math.min(offset + limit, input.rows);
          const expectedLength = Math.max(0, expectedEnd - offset);
          const descriptor = inputs.manifest.files.find((file: any) => file.name === input.name);
          const sourceStart = descriptor.row_range?.[0] ?? 0;
          if (
            page.releaseId !== inputs.releaseId ||
            page.file?.name !== input.name ||
            page.file.sha256 !== input.sha256 ||
            page.file.size !== input.size ||
            page.file.rows !== input.rows ||
            page.totalRows !== input.rows ||
            page.offset !== offset ||
            page.file.rowRange?.[0] !== sourceStart ||
            page.file.rowRange?.[1] !== sourceStart + input.rows ||
            page.nextOffset !== (expectedEnd < input.rows ? expectedEnd : null) ||
            !Array.isArray(page.schema) ||
            !Array.isArray(page.rows) ||
            page.rows.length !== expectedLength ||
            !Array.isArray(page.rowPositions) ||
            page.rowPositions.length !== expectedLength ||
            page.rowPositions.some(
              (position: any, index: number) =>
                position.fileRow !== offset + index ||
                position.row !== sourceStart + offset + index,
            )
          )
            fail(
              'adapter_binding',
              'The Congress reader returned a different file, release or row range.',
              409,
            );
          const rows = page.rows.map((row: unknown) =>
            encodeCongressValue(row, owner),
          ) as ExactObject[];
          const details = encodeCongressValue(
            {
              kind: 'owner-page',
              scope:
                'Response-bound read evidence, not a persisted receipt or a publication claim.',
              consumed: binding,
              releaseId: page.releaseId,
              file: page.file,
              offset: page.offset,
              totalRows: page.totalRows,
              nextOffset: page.nextOffset,
              rowPositions: page.rowPositions,
              schema: presentSchemaFields(page.schema),
              originalManifest: inputs.originalManifestRecord,
              localCatalogHandoff: inputs.handoffRecord,
              ownerModule: {
                configuration: {
                  uri: pathToFileURL(options.configPath).href,
                  sha256: options.configSha256,
                },
                entry: MODULE,
                transport: TRANSPORT,
                files: config.files,
                ...(config.sourceRevision ? { sourceRevision: config.sourceRevision } : {}),
              },
              valueEncoding: {
                numbers: 'ddk-exact-json-v1 numeric tags; original bigint values stay exact.',
                temporal:
                  'Owner-marked date and timestamp fields retain their original units; the physical schema records UTC semantics.',
                binary:
                  'Actual binary cells use a type/encoding/value object with base64 bytes. The physical schema distinguishes cells from source structs.',
                sourceObjects: 'Source keys named $number or $object use escaped entry lists.',
              },
            },
            owner,
          ) as ExactObject;
          if (Buffer.byteLength(JSON.stringify({ rows, details })) > LIMITS.resultBytes)
            fail(
              'adapter_budget',
              'The Congress page and read details exceed the viewer result limit.',
              413,
            );
          signal.throwIfAborted();
          return {
            rows,
            rowPositions: page.rowPositions.map((position: any) => position.row),
            rowOrder: 'source-row',
            total: input.rows,
            hasMore: page.nextOffset !== null,
            consumed: { ...binding },
            details,
          };
        } catch (error) {
          signal.throwIfAborted();
          if (error instanceof ViewerError) throw error;
          const code = (error as any)?.code;
          const status = code === 'BUDGET_EXCEEDED' ? 413 : code === 'UNAVAILABLE' ? 404 : 422;
          if (
            [
              'INVALID_PAGE',
              'UNAVAILABLE',
              'UNSUPPORTED_TYPE',
              'SCHEMA_MISMATCH',
              'BUDGET_EXCEEDED',
            ].includes(code)
          )
            fail(`owner_${code.toLowerCase()}`, (error as Error).message, status);
          throw error;
        } finally {
          await origin?.close();
        }
      },
    },
  };
}
