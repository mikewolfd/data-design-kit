import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createReadStream, existsSync } from 'node:fs';
import { readFile, realpath, stat } from 'node:fs/promises';
import { extname, isAbsolute, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  exactObjectEntries,
  exactObjectField,
  isExactNumber,
  isObject,
  parseExactData,
  parseMetadata,
  validNumber,
} from '../domain/exact';
import type {
  CatalogAudience,
  CatalogSnapshot,
  EvidenceResult,
  ExactBinding,
  ExactObject,
  ExactValue,
  QueryEngineProvenance,
  QueryResult,
  RecordRef,
} from '../domain/types';
import type { OwnerAdapters, OwnerEvidenceReader, OwnerQuery, OwnerReader } from './access';
import { fail, LIMITS, sha256, ViewerError, type CatalogRegistration } from './catalog-store';

export function resolveBridgeScriptPath(
  moduleUrl: string = import.meta.url,
  cwd: string = process.cwd(),
): string {
  const candidates = [
    fileURLToPath(new URL('../../scripts/docspec-owner-bridge.py', moduleUrl)),
    fileURLToPath(new URL('../../../scripts/docspec-owner-bridge.py', moduleUrl)),
    resolve(cwd, 'scripts/docspec-owner-bridge.py'),
  ];
  return candidates.find((candidate) => existsSync(candidate)) ?? candidates[0]!;
}

const BRIDGE_SCRIPT = resolveBridgeScriptPath();
const MAX_WORKER_STDOUT_LINE = 8 * 1024 * 1024;
const DEFAULT_VERIFY_DIGEST_MAX_BYTES = 256 * 1024 * 1024;
const FORBIDDEN_EVIDENCE_EXTENSIONS = new Set([
  '.parquet',
  '.arrow',
  '.ipc',
  '.feather',
  '.duckdb',
  '.sqlite',
  '.db',
]);

export interface PinnedParquetShard {
  path: string;
  sha256?: string;
  byteSize?: number;
  rowCount?: number;
  rowRange?: [number, number];
}

export interface DocSpecStartupReceipt {
  verifiedAt: string;
  catalogDirectory: string;
  lockSha256: string;
  pythonPath: string;
  pythonVersion: string;
  pyarrowVersion: string;
  permittedRoots: readonly string[];
  engine?: QueryEngineProvenance;
}

export interface EvidenceMapEntry {
  path: string;
  record: RecordRef;
  scope: string;
}

export interface DocSpecOwnerConfig {
  directory: string;
  lockSha256: string;
  pythonPath: string;
  ddkSrcPath?: string;
  docspecBinary?: string;
  docspecSha256?: string;
  docspecLimits?: Record<string, number>;
  docspecTimeoutSec?: number;
  fallbackEngine?: 'none' | 'duckdb';
  permittedRoots: readonly string[];
  maxConcurrent?: number;
  verifyDigestMaxBytes?: number;
  supportedDatasetIds?: readonly string[];
  supportedRecipeIds?: readonly string[];
  description?: string;
  enableReader?: boolean;
  enableQuery?: boolean;
  enableEvidence?: boolean;
  wrapQueryLimit?: boolean;
  retainReceiptsDir?: string;
  evidenceAllowlistOnly?: boolean;
  evidenceUriMap?: ReadonlyMap<string, EvidenceMapEntry>;
  resolveReadShards?: (input: {
    snapshot: CatalogSnapshot;
    binding: ExactBinding;
    deadline: number;
    signal: AbortSignal;
  }) => Promise<{
    shards: PinnedParquetShard[];
    extraDetails?: Record<string, unknown>;
  }>;
}

export interface DocSpecCatalogOwner extends OwnerAdapters {
  readonly startup: DocSpecStartupReceipt;
  close(): Promise<void>;
}

export interface OperatorCatalogOwnerEntry {
  id: string;
  catalogId?: string;
  pairedLocalCatalogId?: string;
  navigationLabel?: string;
  navigationDescription?: string;
  exampleData?: 'synthetic' | 'authored';
  directory: string;
  lockSha256: string;
  pairedLocalDirectory?: string;
  pairedLocalLockSha256?: string;
  pythonPath?: string;
  ddkSrcPath?: string;
  docspecBinary?: string;
  docspecSha256?: string;
  docspecLimits?: Record<string, number>;
  fallbackEngine?: 'none' | 'duckdb';
  permittedRoots?: string[];
  supportedDatasetIds?: string[];
  supportedRecipeIds?: string[];
  description?: string;
  enableEvidence?: boolean;
}

export interface TemporalValueGuards {
  isDateValue?: (value: unknown) => boolean;
  isTimestampValue?: (value: unknown) => boolean;
}

/** Encode raw JavaScript/owner values into lossless ddk-exact-json-v1 representation. */
export function encodeExactOwnerValue(
  value: unknown,
  guards: TemporalValueGuards = {},
): ExactValue {
  let nodes = 0;
  const visit = (item: any, depth: number): ExactValue => {
    if (++nodes > 300_000 || depth > 48)
      fail('adapter_budget', 'The owner page exceeds the structure limit.', 413);
    if (item === null || typeof item === 'boolean' || typeof item === 'string') return item;
    if (typeof item === 'bigint' || typeof item === 'number') {
      const lexeme = typeof item === 'number' && Object.is(item, -0) ? '-0' : String(item);
      if (!validNumber(lexeme))
        fail(
          'owner_unsupported_type',
          'The owner page contains a non-finite or unsupported number.',
          422,
        );
      return { $number: lexeme };
    }
    if (item instanceof Uint8Array)
      return { type: 'binary', encoding: 'base64', value: Buffer.from(item).toString('base64') };
    if (Array.isArray(item)) return item.map((child) => visit(child, depth + 1));
    if (item && typeof item === 'object') {
      if (guards.isDateValue?.(item))
        return { type: 'date', days: visit(item.days, depth + 1) };
      if (guards.isTimestampValue?.(item))
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
      'The owner page contains a value this viewer cannot preserve.',
      422,
    );
  };
  return visit(value, 0);
}

export const evidenceMapKey = (record: RecordRef): string =>
  `${record.uri}\0${record.sha256 ?? ''}`;

function isWithinRoots(resolvedPath: string, roots: readonly string[]): boolean {
  return roots.some((root) => resolvedPath === root || resolvedPath.startsWith(root + sep));
}

async function resolvePermittedFile(
  rawLocationOrPath: string,
  catalogDirectory: string,
  permittedRoots: readonly string[],
): Promise<string> {
  let candidate: string;
  if (rawLocationOrPath.startsWith('file://')) {
    let parsed: URL;
    try {
      parsed = new URL(rawLocationOrPath);
    } catch {
      fail('binding_mismatch', 'Invalid file:// location URI in catalog representation.', 409);
    }
    if (parsed.protocol !== 'file:' || (parsed.hostname && parsed.hostname !== 'localhost'))
      fail('binding_mismatch', 'Only local file:// representation locations are supported.', 409);
    candidate = fileURLToPath(parsed);
  } else if (isAbsolute(rawLocationOrPath)) {
    candidate = rawLocationOrPath;
  } else {
    candidate = resolve(catalogDirectory, rawLocationOrPath);
  }
  let real: string;
  try {
    real = await realpath(candidate);
  } catch {
    fail('evidence_refused', 'Referenced local file does not exist.', 404);
  }
  if (!isWithinRoots(real, permittedRoots))
    fail('evidence_refused', 'Referenced file is outside configured permittedRoots.', 409);
  const info = await stat(real);
  if (!info.isFile())
    fail('evidence_refused', 'Referenced path is not a regular file.', 409);
  return real;
}

export async function readBoundedBytes(
  path: string,
  deadline: number,
  signal?: AbortSignal,
  cap = LIMITS.fileBytes,
): Promise<Buffer> {
  if (signal?.aborted) throw signal.reason ?? new ViewerError('deadline', 'Cancelled.', 408);
  if (Date.now() >= deadline) fail('owner_deadline', 'The owner read deadline elapsed.', 408);
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, Math.max(1, deadline - Date.now()));
  const chunks: Buffer[] = [];
  let count = 0;
  try {
    for await (const part of createReadStream(path, {
      highWaterMark: 64 * 1024,
      signal: controller.signal,
    })) {
      const bytes = part as Buffer;
      count += bytes.length;
      if (count > cap)
        fail('evidence_budget', 'The selected owner evidence exceeds its byte budget.', 413);
      chunks.push(bytes);
    }
    return Buffer.concat(chunks, count);
  } catch (error: any) {
    if (signal?.aborted) throw signal.reason ?? new ViewerError('deadline', 'Cancelled.', 408);
    if (controller.signal.aborted || Date.now() >= deadline)
      fail('owner_deadline', 'The owner read deadline elapsed.', 408);
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

async function defaultResolveShards(
  snapshot: CatalogSnapshot,
  binding: ExactBinding,
  catalogDirectory: string,
  permittedRoots: readonly string[],
): Promise<PinnedParquetShard[]> {
  const dataset = snapshot.catalog.datasets.find((row) => row.id === binding.datasetId);
  const version = snapshot.catalog.versions.find((row) => row.id === binding.versionId);
  const representation = snapshot.catalog.representations.find(
    (row) => row.id === binding.representationId,
  );
  if (
    !dataset ||
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
    fail('native_scope_refused', 'Withheld version references cannot be resolved.', 409);
  if (version.retention !== 'present' || representation.availability !== 'available')
    fail('native_scope_refused', 'Selected version or representation is not available.', 409);
  if (representation.mediaType && representation.mediaType !== 'application/vnd.apache.parquet')
    fail('native_scope_refused', 'DocSpecCatalogOwner reads Parquet representations only.', 409);

  let refLocation: string | undefined;
  let refSha256: string | undefined;
  if (
    version.reference?.scheme === 'urn:ddk:version:local-file-sha256' &&
    isObject(version.reference.value)
  ) {
    const loc = exactObjectField(version.reference.value, 'location');
    const dig = exactObjectField(version.reference.value, 'sha256');
    if (typeof loc === 'string') refLocation = loc;
    if (typeof dig === 'string' && /^[a-f0-9]{64}$/.test(dig)) refSha256 = dig;
  }
  const lockEntry = snapshot.lock.files.find(
    (row) =>
      row.role === 'data' &&
      (row.identity === representation.id || row.identity === version.id),
  );

  if (representation.members && representation.members.length > 0) {
    let baseDir = catalogDirectory;
    if (representation.location) {
      if (representation.location.startsWith('file://')) {
        baseDir = fileURLToPath(new URL(representation.location));
      } else if (isAbsolute(representation.location)) {
        baseDir = representation.location;
      } else {
        baseDir = resolve(catalogDirectory, representation.location);
      }
    }
    const shards: PinnedParquetShard[] = [];
    for (const member of representation.members) {
      const resolvedPath = await resolvePermittedFile(member.path, baseDir, permittedRoots);
      shards.push({
        path: resolvedPath,
        sha256: member.sha256,
        ...(member.byteSize !== undefined ? { byteSize: member.byteSize } : {}),
        ...(member.rowCount !== undefined ? { rowCount: member.rowCount } : {}),
        ...(member.rowRange !== undefined ? { rowRange: member.rowRange } : {}),
      });
    }
    return shards;
  }

  const chosenLocation = representation.location ?? refLocation ?? lockEntry?.path;
  if (!chosenLocation)
    fail('native_scope_refused', 'Representation has no local Parquet file location.', 409);
  const resolvedSingle = await resolvePermittedFile(
    chosenLocation,
    catalogDirectory,
    permittedRoots,
  );
  if (refLocation) {
    const resolvedRef = await resolvePermittedFile(refLocation, catalogDirectory, permittedRoots);
    if (resolvedRef !== resolvedSingle)
      fail(
        'binding_mismatch',
        'Representation location disagrees with version.reference location.',
        409,
      );
  }
  const sha = refSha256 ?? lockEntry?.sha256;
  return [
    {
      path: resolvedSingle,
      ...(sha ? { sha256: sha } : {}),
      ...(representation.byteSize !== undefined ? { byteSize: representation.byteSize } : {}),
      ...(representation.rowCount !== undefined ? { rowCount: representation.rowCount } : {}),
    },
  ];
}

function decodeQueryParameters(
  parameters: Record<string, ExactValue>,
  schema: Record<string, unknown> | undefined,
): { pyParams: Record<string, unknown>; rawNumericParameters: Record<string, string> } {
  const pyParams: Record<string, unknown> = Object.create(null);
  const rawNumericParameters: Record<string, string> = Object.create(null);
  const props = isObject(schema) && isObject(schema.properties) ? schema.properties : {};
  for (const [key, raw] of Object.entries(parameters)) {
    const propSchema = isObject(props[key]) ? props[key] : undefined;
    const expectedType = propSchema?.type;
    if (isExactNumber(raw)) {
      rawNumericParameters[key] = raw.$number;
      const numeric = Number(raw.$number);
      if (!Number.isFinite(numeric))
        fail('invalid_parameters', `Numeric parameter ${key} exceeds finite bounds.`, 400);
      pyParams[key] =
        expectedType === 'integer' && /^-?(?:0|[1-9]\d*)$/.test(raw.$number)
          ? Number.isSafeInteger(numeric)
            ? numeric
            : Math.trunc(numeric)
          : numeric;
    } else if (typeof raw === 'number') {
      if (!Number.isFinite(raw))
        fail('invalid_parameters', `Parameter ${key} must be finite.`, 400);
      rawNumericParameters[key] = Object.is(raw, -0) ? '-0' : String(raw);
      pyParams[key] = raw;
    } else if (
      typeof raw === 'string' &&
      (expectedType === 'integer' || expectedType === 'number') &&
      validNumber(raw)
    ) {
      rawNumericParameters[key] = raw;
      pyParams[key] = Number(raw);
    } else {
      pyParams[key] = raw;
    }
  }
  return { pyParams, rawNumericParameters };
}

class PythonBridgeWorker {
  private child: ChildProcessWithoutNullStreams | null = null;
  private buffer = '';
  private nextId = 1;
  private pending = new Map<
    number,
    {
      resolve: (value: any) => void;
      reject: (error: Error) => void;
    }
  >();
  private queue: Promise<unknown> = Promise.resolve();
  private closed = false;

  constructor(
    private readonly pythonPath: string,
    private readonly initParams: Record<string, unknown>,
  ) {}

  private setReferenced(referenced: boolean) {
    if (!this.child) return;
    if (referenced) {
      this.child.ref();
      (this.child.stdout as any)?.ref?.();
      (this.child.stderr as any)?.ref?.();
      (this.child.stdin as any)?.ref?.();
    } else {
      this.child.unref();
      (this.child.stdout as any)?.unref?.();
      (this.child.stderr as any)?.unref?.();
      (this.child.stdin as any)?.unref?.();
    }
  }

  private killChild(reason: Error) {
    const proc = this.child;
    this.child = null;
    this.buffer = '';
    for (const [, waiter] of this.pending) {
      waiter.reject(reason);
    }
    this.pending.clear();
    if (proc && !proc.killed) {
      proc.kill('SIGTERM');
      const timer = setTimeout(() => {
        try {
          proc.kill('SIGKILL');
        } catch {}
      }, 500);
      timer.unref();
    }
  }

  private async ensureStarted(deadline: number, signal?: AbortSignal): Promise<any> {
    if (this.closed) fail('owner_unavailable', 'DocSpecCatalogOwner is closed.', 503);
    if (this.child) return undefined;

    const proc = spawn(this.pythonPath, ['-B', '-u', BRIDGE_SCRIPT], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.child = proc;

    let stderrTail = '';
    proc.stderr.on('data', (chunk: Buffer) => {
      stderrTail = (stderrTail + chunk.toString('utf8')).slice(-4096);
    });
    proc.stdout.on('data', (chunk: Buffer) => {
      this.buffer += chunk.toString('utf8');
      if (this.buffer.length > MAX_WORKER_STDOUT_LINE) {
        this.killChild(
          new ViewerError('adapter_budget', 'Owner worker response exceeded byte cap.', 413),
        );
        return;
      }
      let newlineIdx = this.buffer.indexOf('\n');
      while (newlineIdx !== -1) {
        const line = this.buffer.slice(0, newlineIdx);
        this.buffer = this.buffer.slice(newlineIdx + 1);
        newlineIdx = this.buffer.indexOf('\n');
        if (!line.trim()) continue;
        let parsed: any;
        try {
          parsed = JSON.parse(line);
        } catch {
          this.killChild(
            new ViewerError('adapter_transport', 'Malformed JSON from owner worker.', 502),
          );
          return;
        }
        const waiter = this.pending.get(parsed.id);
        if (!waiter) continue;
        this.pending.delete(parsed.id);
        if (parsed.ok) {
          waiter.resolve(parsed.result);
        } else {
          const err = parsed.error ?? {};
          waiter.reject(
            new ViewerError(
              typeof err.code === 'string' ? err.code : 'owner_unavailable',
              typeof err.message === 'string' ? err.message : 'Owner worker error.',
              typeof err.status === 'number' ? err.status : 409,
            ),
          );
        }
      }
    });
    proc.once('error', (err) => {
      this.killChild(
        new ViewerError('owner_unavailable', `Failed to start owner worker: ${err.message}`, 503),
      );
    });
    proc.once('close', (code) => {
      if (this.child === proc) {
        this.killChild(
          new ViewerError(
            'owner_unavailable',
            `Owner worker exited unexpectedly (code ${code})${stderrTail ? `: ${stderrTail.trim()}` : ''}`,
            503,
          ),
        );
      }
    });
    proc.stdin.on('error', () => {});

    const initResult = await this.sendRaw('init', this.initParams, deadline, signal);
    if (this.pending.size === 0) this.setReferenced(false);
    return initResult;
  }

  private sendRaw(
    method: string,
    params: Record<string, unknown>,
    deadline: number,
    signal?: AbortSignal,
  ): Promise<any> {
    if (signal?.aborted) {
      return Promise.reject(
        signal.reason ?? new ViewerError('owner_deadline', 'Owner request aborted.', 408),
      );
    }
    const remainingMs = deadline - Date.now();
    if (remainingMs <= 0) {
      return Promise.reject(
        new ViewerError('owner_deadline', 'The owner deadline elapsed before dispatch.', 408),
      );
    }
    const proc = this.child!;
    const id = this.nextId++;
    this.setReferenced(true);

    return new Promise((resolveCall, rejectCall) => {
      const onAbort = () => {
        cleanup();
        const reason =
          signal?.reason ??
          new ViewerError(
            'owner_deadline',
            'Owner request cancelled; worker recycled cleanly.',
            408,
          );
        this.killChild(
          reason instanceof Error ? reason : new ViewerError('owner_deadline', String(reason), 408),
        );
        rejectCall(reason);
      };
      const timer = setTimeout(() => {
        cleanup();
        const timeoutErr = new ViewerError(
          'owner_deadline',
          'The owner deadline elapsed; worker recycled cleanly.',
          408,
        );
        this.killChild(timeoutErr);
        rejectCall(timeoutErr);
      }, Math.max(1, remainingMs));

      const cleanup = () => {
        clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
      };

      this.pending.set(id, {
        resolve: (value) => {
          cleanup();
          if (this.pending.size === 0) this.setReferenced(false);
          resolveCall(value);
        },
        reject: (err) => {
          cleanup();
          if (this.pending.size === 0) this.setReferenced(false);
          rejectCall(err);
        },
      });

      signal?.addEventListener('abort', onAbort, { once: true });
      proc.stdin.write(JSON.stringify({ id, method, params }) + '\n');
    });
  }

  async init(deadline = Date.now() + 30_000): Promise<any> {
    return this.ensureStarted(deadline);
  }

  call(
    method: string,
    params: Record<string, unknown>,
    deadline: number,
    signal?: AbortSignal,
  ): Promise<any> {
    const run = async () => {
      await this.ensureStarted(deadline, signal);
      return this.sendRaw(method, params, deadline, signal);
    };
    const next = this.queue.then(run, run);
    this.queue = next.then(
      () => undefined,
      () => undefined,
    );
    return next;
  }

  async close(): Promise<void> {
    this.closed = true;
    const proc = this.child;
    this.child = null;
    for (const [, waiter] of this.pending) {
      waiter.reject(new ViewerError('owner_unavailable', 'Owner closed.', 503));
    }
    this.pending.clear();
    if (!proc) return;
    proc.ref();
    await new Promise<void>((resolveDone) => {
      const killTimer = setTimeout(() => {
        try {
          proc.kill('SIGKILL');
        } catch {}
        resolveDone();
      }, 500);
      proc.once('close', () => {
        clearTimeout(killTimer);
        resolveDone();
      });
      try {
        proc.stdin.end();
      } catch {
        proc.kill('SIGTERM');
      }
    });
  }
}

/**
 * Create a generic, startup-pinned DDK catalog owner adapter backed by PyArrow Parquet
 * row-group pagination and optional DocSpec checked recipe execution.
 */
export async function createDocSpecCatalogOwner(
  config: DocSpecOwnerConfig,
): Promise<DocSpecCatalogOwner> {
  if (!config || typeof config.directory !== 'string' || !isAbsolute(config.directory))
    fail('invalid_registration', 'DocSpecCatalogOwner directory must be an absolute path.');
  if (!/^[a-f0-9]{64}$/.test(config.lockSha256))
    fail('invalid_registration', 'DocSpecCatalogOwner requires a 64-hex lockSha256.');
  if (typeof config.pythonPath !== 'string' || !isAbsolute(config.pythonPath))
    fail('invalid_registration', 'DocSpecCatalogOwner pythonPath must be an absolute path.');
  if (!Array.isArray(config.permittedRoots) || config.permittedRoots.length === 0)
    fail('invalid_registration', 'DocSpecCatalogOwner requires non-empty permittedRoots.');
  if (config.docspecSha256 !== undefined && !/^[a-f0-9]{64}$/.test(config.docspecSha256))
    fail('invalid_registration', 'docspecSha256 must be a 64-hex SHA-256 digest.');

  let catalogDirectory: string;
  try {
    catalogDirectory = await realpath(config.directory);
  } catch {
    fail('invalid_registration', `Catalog directory does not exist: ${config.directory}`);
  }
  const pythonResolved = resolve(config.pythonPath);
  try {
    const pyStat = await stat(pythonResolved);
    if (!pyStat.isFile()) throw new Error('not a file');
  } catch {
    fail('owner_unavailable', `Configured Python interpreter not found: ${config.pythonPath}`, 503);
  }

  const permittedRoots: string[] = [];
  for (const rawRoot of config.permittedRoots) {
    if (typeof rawRoot !== 'string' || !isAbsolute(rawRoot))
      fail('invalid_registration', 'Every permittedRoot must be an absolute directory path.');
    let realRoot: string;
    try {
      realRoot = await realpath(rawRoot);
    } catch {
      fail('invalid_registration', `Permitted root does not exist: ${rawRoot}`);
    }
    const rootStat = await stat(realRoot);
    if (!rootStat.isDirectory())
      fail('invalid_registration', `Permitted root is not a directory: ${rawRoot}`);
    if (!permittedRoots.includes(realRoot)) permittedRoots.push(realRoot);
  }
  if (!isWithinRoots(catalogDirectory, permittedRoots)) {
    permittedRoots.push(catalogDirectory);
  }

  let retainReceiptsDirReal: string | undefined;
  if (config.retainReceiptsDir) {
    const absRetain = resolve(config.retainReceiptsDir);
    const { mkdir } = await import('node:fs/promises');
    await mkdir(absRetain, { recursive: true });
    retainReceiptsDirReal = await realpath(absRetain);
    if (!isWithinRoots(retainReceiptsDirReal, permittedRoots)) {
      permittedRoots.push(retainReceiptsDirReal);
    }
  }

  const catalogPath = resolve(catalogDirectory, 'catalog.ddk.json');
  const lockPath = resolve(catalogDirectory, 'catalog.lock.json');
  const lockBytes = await readBoundedBytes(lockPath, Date.now() + 5000, undefined, LIMITS.lockBytes);
  if (sha256(lockBytes) !== config.lockSha256)
    fail('integrity_mismatch', 'The catalog.lock.json digest differs from lockSha256.', 409);

  const worker = new PythonBridgeWorker(pythonResolved, {
    catalogPath,
    lockPath,
    expectedLockSha256: config.lockSha256,
    ...(config.ddkSrcPath ? { ddkSrcPath: resolve(config.ddkSrcPath) } : {}),
    ...(config.docspecBinary ? { docspecBinary: config.docspecBinary } : {}),
    ...(config.docspecSha256 ? { docspecSha256: config.docspecSha256 } : {}),
    ...(config.docspecLimits ? { docspecLimits: config.docspecLimits } : {}),
    ...(config.docspecTimeoutSec ? { docspecTimeoutSec: config.docspecTimeoutSec } : {}),
    fallbackEngine: config.fallbackEngine ?? 'none',
    permittedRoots,
    ...(retainReceiptsDirReal ? { retainReceiptsDir: retainReceiptsDirReal } : {}),
  });

  // Startup-once verification of Python + PyArrow + DDK + optional DocSpec binary SHA-256
  const initInfo = await worker.init(Date.now() + 30_000);
  const startup: DocSpecStartupReceipt = Object.freeze({
    verifiedAt: new Date().toISOString(),
    catalogDirectory,
    lockSha256: config.lockSha256,
    pythonPath: pythonResolved,
    pythonVersion: initInfo.pythonVersion,
    pyarrowVersion: initInfo.pyarrowVersion,
    permittedRoots: Object.freeze([...permittedRoots]),
    ...(initInfo.engine ? { engine: Object.freeze({ ...initInfo.engine }) } : {}),
  });

  const maxConcurrent = config.maxConcurrent ?? 4;
  const verifyDigestMaxBytes = config.verifyDigestMaxBytes ?? DEFAULT_VERIFY_DIGEST_MAX_BYTES;
  let activeCalls = 0;
  const dynamicEvidence = new Map<string, EvidenceMapEntry>();

  async function withConcurrency<T>(fn: () => Promise<T>): Promise<T> {
    if (activeCalls >= maxConcurrent)
      fail('owner_busy', 'Maximum concurrent DocSpecCatalogOwner requests reached.', 503);
    activeCalls++;
    try {
      return await fn();
    } finally {
      activeCalls--;
    }
  }

  function verifySnapshotIdentity(snapshot: CatalogSnapshot) {
    if (snapshot.audience !== 'local' || snapshot.catalog.audience !== 'local')
      fail('audience_refused', 'DocSpecCatalogOwner serves local catalog views only.', 403);
    if (snapshot.identity.lockSha256 !== config.lockSha256)
      fail('integrity_mismatch', 'Snapshot lockSha256 differs from startup-pinned owner.', 409);
  }

  const enableReader = config.enableReader ?? true;
  const enableQuery =
    config.enableQuery ?? Boolean(config.docspecBinary || config.fallbackEngine === 'duckdb');
  const enableEvidence = config.enableEvidence ?? true;

  const reader: OwnerReader | undefined = enableReader
    ? {
        ...(config.supportedDatasetIds ? { supportedDatasetIds: config.supportedDatasetIds } : {}),
        description:
          config.description ??
          'Read bounded Parquet slices from startup-verified local catalog representations.',
        async read({ snapshot, binding, offset, limit, deadline, signal }) {
          if (signal.aborted)
            throw signal.reason ?? new ViewerError('owner_deadline', 'Cancelled.', 408);
          if (Date.now() >= deadline)
            fail('owner_deadline', 'The owner read deadline elapsed.', 408);
          verifySnapshotIdentity(snapshot);
          if (
            config.supportedDatasetIds &&
            !config.supportedDatasetIds.includes(binding.datasetId)
          )
            fail('native_scope_refused', 'Dataset is outside configured owner scope.', 409);

          return withConcurrency(async () => {
            const resolved = config.resolveReadShards
              ? await config.resolveReadShards({ snapshot, binding, deadline, signal })
              : {
                  shards: await defaultResolveShards(
                    snapshot,
                    binding,
                    catalogDirectory,
                    permittedRoots,
                  ),
                };

            const page = await worker.call(
              'read_page',
              {
                shards: resolved.shards,
                offset,
                limit,
                verifyDigestMaxBytes,
              },
              deadline,
              signal,
            );

            const details = encodeExactOwnerValue({
              kind: 'owner-page',
              scope:
                'Response-bound Parquet slice metadata; not a managed candidate acceptance or publication claim.',
              consumed: binding,
              offset,
              totalRows: page.total,
              rowPositions: page.rowPositions,
              shardCount: resolved.shards.length,
              shards: resolved.shards.map((shard) => ({
                uri: pathToFileURL(shard.path).href,
                ...(shard.sha256 ? { sha256: shard.sha256 } : {}),
                ...(shard.byteSize !== undefined ? { byteSize: shard.byteSize } : {}),
                ...(shard.rowCount !== undefined ? { rowCount: shard.rowCount } : {}),
                ...(shard.rowRange ? { rowRange: shard.rowRange } : {}),
              })),
              schema: page.schema,
              ...(resolved.extraDetails ?? {}),
            }) as ExactObject;

            const rows = page.rows as ExactObject[];
            if (Buffer.byteLength(JSON.stringify({ rows, details })) > LIMITS.resultBytes)
              fail(
                'result_budget',
                'The page and read details exceed the viewer response byte budget.',
                413,
              );

            return {
              rows,
              rowPositions: page.rowPositions as number[],
              rowOrder: 'source-row',
              total: page.total as number,
              hasMore: page.hasMore as boolean,
              consumed: { ...binding },
              details,
            };
          });
        },
      }
    : undefined;

  const query: OwnerQuery | undefined = enableQuery
    ? {
        ...(config.supportedRecipeIds ? { supportedRecipeIds: config.supportedRecipeIds } : {}),
        description:
          config.description ??
          'Execute checked catalog SQL recipes through startup-pinned DocSpec runtime.',
        async query({ snapshot, recipeId, bindings, parameters, sql, limit, deadline, signal }) {
          if (signal.aborted)
            throw signal.reason ?? new ViewerError('owner_deadline', 'Cancelled.', 408);
          if (Date.now() >= deadline)
            fail('owner_deadline', 'The owner query deadline elapsed.', 408);
          verifySnapshotIdentity(snapshot);
          if (config.supportedRecipeIds && !config.supportedRecipeIds.includes(recipeId))
            fail('native_scope_refused', 'Recipe is outside configured owner scope.', 409);

          const recipe = snapshot.catalog.recipes.find((row) => row.id === recipeId);
          if (!recipe)
            fail('unknown_recipe', 'Recipe is absent from the selected catalog.', 404);
          const expectedCompanion = snapshot.catalog.files.find(
            (file) => file.role === 'recipe' && file.path === recipe.sql,
          );
          const actualSqlSha = sha256(sql);
          if (!expectedCompanion || expectedCompanion.sha256 !== actualSqlSha)
            fail(
              'native_scope_refused',
              'Supplied SQL bytes differ from the pinned catalog recipe companion.',
              409,
            );

          return withConcurrency(async () => {
            const inputNames = Object.keys(bindings).sort();
            const resolvedInputs: Record<
              string,
              { path: string; sha256?: string; versionId: string }
            > = Object.create(null);
            const versionsMap: Record<string, string> = Object.create(null);
            let sharedReleaseId: string | undefined;
            for (const name of inputNames) {
              const binding = bindings[name];
              if (binding.releaseId !== undefined) {
                if (sharedReleaseId !== undefined && sharedReleaseId !== binding.releaseId)
                  fail('release_mismatch', 'Conflicting releaseIds across recipe inputs.', 409);
                sharedReleaseId = binding.releaseId;
              }
              const shards = await defaultResolveShards(
                snapshot,
                binding,
                catalogDirectory,
                permittedRoots,
              );
              if (shards.length !== 1)
                fail(
                  'native_scope_refused',
                  `DocSpec recipe input ${name} requires a single Parquet file binding.`,
                  409,
                );
              resolvedInputs[name] = {
                path: shards[0].path,
                ...(shards[0].sha256 ? { sha256: shards[0].sha256 } : {}),
                versionId: binding.versionId,
              };
              versionsMap[name] = binding.versionId;
            }
            if (
              sharedReleaseId !== undefined &&
              Object.values(bindings).some((b) => b.releaseId !== sharedReleaseId)
            )
              fail(
                'release_mismatch',
                'Every recipe input must bind the same release when releaseId is supplied.',
                409,
              );

            const { pyParams, rawNumericParameters } = decodeQueryParameters(
              parameters,
              recipe.parameters,
            );

            const answer = await worker.call(
              'run_query',
              {
                recipeId,
                expectedSqlSha256: actualSqlSha,
                ...(sharedReleaseId !== undefined
                  ? { releaseId: sharedReleaseId }
                  : { versions: versionsMap }),
                inputs: resolvedInputs,
                parameters: pyParams,
                rawNumericParameters,
                limit,
                wrapLimit: config.wrapQueryLimit ?? true,
                verifyDigestMaxBytes,
              },
              deadline,
              signal,
            );

            let retainedRecord: RecordRef | undefined;
            if (answer.record?.path && answer.record?.sha256) {
              const recordUri = pathToFileURL(answer.record.path).href;
              retainedRecord = { uri: recordUri, sha256: answer.record.sha256 };
              dynamicEvidence.set(evidenceMapKey(retainedRecord), {
                path: answer.record.path,
                record: retainedRecord,
                scope: 'new-consumer-read',
              });
            }

            const rows = answer.rows as ExactObject[];
            const columns = [
              ...new Set(rows.flatMap((row) => exactObjectEntries(row).map(([key]) => key))),
            ];
            const consumedBindings: Record<string, ExactBinding> = {};
            for (const name of inputNames) {
              consumedBindings[name] = { ...bindings[name] };
            }
            const hasMore = Boolean(answer.hasMore);
            return {
              status: 'ok',
              bindings: consumedBindings,
              rows,
              columns,
              returned: rows.length,
              ...(typeof answer.total === 'number' ? { total: answer.total } : {}),
              hasMore,
              continuation: hasMore ? 'more' : 'complete',
              rowPositions: answer.rowPositions as number[],
              rowOrder: 'query-result',
              transport: 'ddk-exact-json-v1',
              execution: {
                kind: 'owner',
                recipeId,
                sqlSha256: answer.sqlSha256 as string,
                inputs: inputNames,
                contextualRelationships: recipe.contextualRelationships ?? [],
                ...(answer.engine ? { engine: answer.engine as QueryEngineProvenance } : {}),
                consumedBindings,
                ...(typeof answer.elapsedMs === 'number' ? { elapsedMs: answer.elapsedMs } : {}),
                ...(retainedRecord ? { record: retainedRecord } : {}),
              },
            } satisfies QueryResult;
          });
        },
      }
    : undefined;

  const evidence: OwnerEvidenceReader | undefined = enableEvidence
    ? async ({ record, deadline, signal }): Promise<EvidenceResult> => {
        if (!isObject(record) || typeof record.uri !== 'string' || typeof record.sha256 !== 'string')
          fail('evidence_refused', 'An exact evidence URI and SHA-256 digest are required.', 400);
        if (!/^[a-f0-9]{64}$/.test(record.sha256))
          fail('evidence_refused', 'Evidence SHA-256 must be a 64-character hex digest.', 400);

        const mapped =
          dynamicEvidence.get(evidenceMapKey(record)) ??
          config.evidenceUriMap?.get(evidenceMapKey(record));

        if (!mapped && config.evidenceAllowlistOnly) {
          fail(
            'evidence_refused',
            'This record is outside the configured evidence allowlist.',
            404,
          );
        }

        let targetPath: string;
        let scope = mapped?.scope ?? 'owner-evidence';
        if (mapped) {
          targetPath = await resolvePermittedFile(mapped.path, catalogDirectory, permittedRoots);
        } else {
          if (!record.uri.startsWith('file://'))
            fail('evidence_refused', 'Evidence URI must use file:// scheme.', 404);
          targetPath = await resolvePermittedFile(record.uri, catalogDirectory, permittedRoots);
        }

        const ext = extname(targetPath).toLowerCase();
        if (FORBIDDEN_EVIDENCE_EXTENSIONS.has(ext))
          fail('evidence_refused', 'Binary dataset payloads cannot be read via evidence API.', 409);

        const bytes = await readBoundedBytes(targetPath, deadline, signal, LIMITS.fileBytes);
        if (sha256(bytes) !== record.sha256)
          fail('integrity_mismatch', 'The evidence file bytes differ from record.sha256.', 409);

        let text: string;
        try {
          text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        } catch {
          fail('evidence_refused', 'Evidence file is not valid UTF-8 text or JSON.', 422);
        }

        const document =
          ext === '.txt' || ext === '.log' || ext === '.md'
            ? ({ text } as ExactObject)
            : parseExactData(text);

        return {
          record: { uri: record.uri, sha256: record.sha256 },
          document,
          scope,
        };
      }
    : undefined;

  return {
    startup,
    ...(reader ? { reader } : {}),
    ...(query ? { query } : {}),
    ...(evidence ? { evidence } : {}),
    close: () => worker.close(),
  };
}

/** Load an operator-supplied DDK_VIEWER_OWNER_CONFIG JSON file and resolve registrations + owners. */
export async function loadOperatorOwnerConfig(
  configPath: string,
  audience: CatalogAudience,
): Promise<{
  registrations: CatalogRegistration[];
  owners: Map<string, DocSpecCatalogOwner>;
}> {
  const resolvedConfigPath = resolve(configPath);
  const info = await stat(resolvedConfigPath).catch(() => null);
  if (!info || !info.isFile())
    fail('invalid_registration', `DDK_VIEWER_OWNER_CONFIG file not found: ${resolvedConfigPath}`);
  if (info.size > 1024 * 1024)
    fail('invalid_registration', 'DDK_VIEWER_OWNER_CONFIG exceeds 1 MiB.', 413);

  const rawText = await readFile(resolvedConfigPath, 'utf8');
  const parsed = parseMetadata(rawText);
  const rawEntries: unknown[] = Array.isArray(parsed)
    ? parsed
    : isObject(parsed) && Array.isArray(parsed.catalogs)
      ? parsed.catalogs
      : fail(
          'invalid_registration',
          'DDK_VIEWER_OWNER_CONFIG must be an array or { catalogs: [...] }.',
        );

  const registrations: CatalogRegistration[] = [];
  const owners = new Map<string, DocSpecCatalogOwner>();
  const seenIds = new Set<string>();

  for (const item of rawEntries) {
    if (!isObject(item) || typeof item.id !== 'string' || !item.id.trim())
      fail('invalid_registration', 'Each owner config entry requires a non-empty string id.');
    const entry = item as unknown as OperatorCatalogOwnerEntry;
    if (seenIds.has(entry.id))
      fail('invalid_registration', `Duplicate catalog id in owner config: ${entry.id}`);
    seenIds.add(entry.id);

    const usePairedLocal =
      audience === 'local' &&
      typeof entry.pairedLocalDirectory === 'string' &&
      typeof entry.pairedLocalLockSha256 === 'string';

    const selectedDir = resolve(
      usePairedLocal ? entry.pairedLocalDirectory! : entry.directory,
    );
    const selectedLockSha = usePairedLocal ? entry.pairedLocalLockSha256! : entry.lockSha256;

    if (!/^[a-f0-9]{64}$/.test(selectedLockSha))
      fail('invalid_registration', `Entry ${entry.id} requires a 64-hex lockSha256.`);

    const selectedCatalogId = usePairedLocal
      ? (entry.pairedLocalCatalogId ?? entry.catalogId)
      : entry.catalogId;

    registrations.push({
      id: entry.id,
      ...(selectedCatalogId ? { catalogId: selectedCatalogId } : {}),
      ...(entry.navigationLabel ? { navigationLabel: entry.navigationLabel } : {}),
      ...(entry.navigationDescription ? { navigationDescription: entry.navigationDescription } : {}),
      ...(entry.exampleData ? { exampleData: entry.exampleData } : {}),
      mode: 'application',
      directory: selectedDir,
      lockSha256: selectedLockSha,
    });

    if (audience === 'local' && entry.pythonPath && entry.permittedRoots?.length) {
      const owner = await createDocSpecCatalogOwner({
        directory: selectedDir,
        lockSha256: selectedLockSha,
        pythonPath: resolve(entry.pythonPath),
        ...(entry.ddkSrcPath ? { ddkSrcPath: resolve(entry.ddkSrcPath) } : {}),
        ...(entry.docspecBinary ? { docspecBinary: resolve(entry.docspecBinary) } : {}),
        ...(entry.docspecSha256 ? { docspecSha256: entry.docspecSha256 } : {}),
        ...(entry.docspecLimits ? { docspecLimits: entry.docspecLimits } : {}),
        fallbackEngine: entry.fallbackEngine ?? 'none',
        permittedRoots: entry.permittedRoots.map((r) => resolve(r)),
        ...(entry.supportedDatasetIds ? { supportedDatasetIds: entry.supportedDatasetIds } : {}),
        ...(entry.supportedRecipeIds ? { supportedRecipeIds: entry.supportedRecipeIds } : {}),
        ...(entry.description ? { description: entry.description } : {}),
        enableEvidence: entry.enableEvidence ?? true,
      });
      owners.set(entry.id, owner);
    }
  }

  return { registrations, owners };
}
