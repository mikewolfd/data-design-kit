import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isObject, parseExactData, parseMetadata } from '../domain/exact';
import type { ExactObject, QueryResult } from '../domain/types';
import type { OwnerEvidenceReader, OwnerQuery, OwnerSql } from './access';
import { fail, LIMITS, sha256, ViewerError } from './catalog-store';

/** Operator-only placement for the installed DDK Python composition API. */
export interface LocalSqlConfig {
  python: string;
  pythonPath?: string[];
  evidenceDirectory: string;
  maxInputBytes?: number;
  maxMembers?: number;
}
interface CatalogConfig {
  directory: string;
  lockSha256: string;
  docspecBinary: string;
  docspecSha256: string;
  docspecLimits: Record<string, number>;
  permittedRoots: readonly string[];
}

export async function createLocalCatalogSql(config: LocalSqlConfig, catalog: CatalogConfig): Promise<{
  sql: OwnerSql;
  query: OwnerQuery;
  evidence: OwnerEvidenceReader;
}> {
  for (const value of [config.python, config.evidenceDirectory, ...(config.pythonPath ?? [])])
    if (typeof value !== 'string' || !isAbsolute(value))
      fail('invalid_registration', 'Local SQL placement requires absolute operator paths.');
  // Preserve the operator's venv path: dereferencing its executable symlink
  // before spawning would silently select the system Python environment.
  const python = config.python;
  if (!(await stat(await realpath(python))).isFile()) fail('invalid_registration', 'The selected Python executable is unavailable.');
  const maxInputBytes = config.maxInputBytes ?? 16 * 1024 * 1024;
  const maxMembers = config.maxMembers ?? 128;
  if (!Number.isSafeInteger(maxInputBytes) || maxInputBytes < 1 || maxInputBytes > 16 * 1024 * 1024 ||
      !Number.isSafeInteger(maxMembers) || maxMembers < 1 || maxMembers > 128)
    fail('invalid_registration', 'Local SQL input limits exceed the supported allocation.');
  await mkdir(config.evidenceDirectory, { recursive: true });
  const evidenceDirectory = await realpath(config.evidenceDirectory);
  const records = new Map<string, { path: string; sha256: string }>();
  let active = 0;

  const query: OwnerSql['query'] = async input => {
    if (input.snapshot.identity.lockSha256 !== catalog.lockSha256)
      fail('catalog_mismatch', 'The query adapter is bound to a different catalog lock.', 409);
    if (active >= 2) fail('owner_busy', 'Both local query allocations are in use.', 503);
    if (input.signal.aborted || Date.now() >= input.deadline)
      fail('owner_deadline', 'The local query deadline elapsed.', 408);
    active++;
    const started = Date.now();
    try {
      const directory = await mkdtemp(join(evidenceDirectory, 'query-'));
      const bindings = Object.fromEntries(Object.entries(input.bindings).map(([name, binding]) => [name, binding.versionId]));
      const request = { bindings, sql: Buffer.from(input.sql).toString('utf8'), limit: input.limit };
      const requestBytes = JSON.stringify(request);
      const requestPath = join(directory, 'viewer-request.json');
      await writeFile(requestPath, requestBytes, { flag: 'wx' });
      const attempt = { uri: pathToFileURL(requestPath).href, sha256: sha256(requestBytes) };
      records.set(attempt.uri, { path: requestPath, sha256: attempt.sha256 });
      input.onAttempt?.(attempt);
      const configPath = join(directory, 'worker-config.json');
      await writeFile(configPath, JSON.stringify({ ...catalog, maxInputBytes, maxMembers,
        attemptDirectory: directory, timeoutSeconds: Math.max(0.05, (input.deadline - Date.now()) / 1000) }), { flag: 'wx' });
      const output = await new Promise<string>((resolve, reject) => {
        const child = spawn(python, ['-m', 'ddk.catalog_query_worker', '--config', configPath], {
          detached: true, stdio: ['pipe', 'pipe', 'pipe'],
          env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1',
            ...(config.pythonPath ? { PYTHONPATH: config.pythonPath.join(':') } : {}) },
        });
        const chunks: Buffer[] = [], diagnostics: Buffer[] = [];
        let bytes = 0, failure: ViewerError | undefined;
        const stop = (error: ViewerError) => {
          failure ??= error;
          if (child.pid) {
            try { process.kill(-child.pid, 'SIGKILL'); } catch (cause: any) {
              if (cause.code !== 'ESRCH') child.kill('SIGKILL');
            }
          }
        };
        const abort = () => stop(new ViewerError('native_read_unknown', 'The query wait ended; retained request evidence identifies the attempt.', 409));
        const timer = setTimeout(abort, Math.max(1, input.deadline - Date.now()));
        input.signal.addEventListener('abort', abort, { once: true });
        if (input.signal.aborted) abort();
        child.stdout.on('data', (chunk: Buffer) => {
          bytes += chunk.length;
          if (bytes > 4 * 1024 * 1024) stop(new ViewerError('native_read_unknown', 'The local query exceeded its output allocation.', 413));
          else chunks.push(chunk);
        });
        child.stderr.on('data', (chunk: Buffer) => {
          bytes += chunk.length;
          if (bytes > 4 * 1024 * 1024) stop(new ViewerError('native_read_unknown', 'The local query exceeded its diagnostic allocation.', 413));
          else diagnostics.push(chunk);
        });
        child.on('error', () => { failure ??= new ViewerError('native_read_unknown', 'The local query process could not complete.', 409); });
        child.stdin.on('error', () => {});
        child.on('close', async code => {
          clearTimeout(timer);
          input.signal.removeEventListener('abort', abort);
          try {
            await Promise.all([
              writeFile(join(directory, 'worker-stdout.json'), Buffer.concat(chunks), { flag: 'wx' }),
              writeFile(join(directory, 'worker-stderr.log'), Buffer.concat(diagnostics), { flag: 'wx' }),
            ]);
          } catch {
            failure ??= new ViewerError('native_read_unknown', 'The local query diagnostic record could not be retained.', 409);
          }
          if (failure) reject(failure);
          else if (code !== 0) reject(new ViewerError('native_read_unknown', 'The local query process ended without a complete answer.', 409));
          else resolve(Buffer.concat(chunks).toString('utf8'));
        });
        child.stdin.end(requestBytes);
      });
      const result = parseMetadata(output);
      if (!isObject(result) || !['ok', 'refused', 'unknown'].includes(result.status))
        fail('adapter_receipt', 'The local query response is incomplete.', 409);
      const base: QueryResult = { status: result.status, bindings: input.bindings,
        rows: [], columns: [], returned: 0, rowPositions: [], transport: 'ddk-exact-json-v1',
        ...(result.reason ? { reason: result.reason } : {}) };
      if (result.record) {
        // The bridge may retain only its own fixed answer file, never a path
        // supplied by the request or returned by the execution engine.
        const answerPath = join(directory, 'answer.json');
        const uri = pathToFileURL(answerPath).href;
        if (result.record.uri !== uri || !/^[a-f0-9]{64}$/.test(result.record.sha256))
          fail('adapter_receipt', 'The local query evidence reference is invalid.', 409);
        records.set(uri, { path: answerPath, sha256: result.record.sha256 });
      }
      if (result.status !== 'ok') return { ...base, attempt };
      if (result.sqlSha256 !== sha256(input.sql) || !isObject(result.bindings) ||
          Object.keys(result.bindings).length !== Object.keys(bindings).length ||
          Object.entries(bindings).some(([name, version]) => result.bindings[name] !== version))
        fail('adapter_receipt', 'The local query consumed different SQL or versions.', 409);
      const rows = parseExactData(result.rowsJson);
      if (!Array.isArray(rows) || rows.some(row => !isObject(row)) || rows.length > input.limit ||
          !Array.isArray(result.columns) || result.columns.some((name: unknown) => typeof name !== 'string'))
        fail('adapter_receipt', 'The local query returned invalid rows.', 409);
      return { ...base, rows: rows as ExactObject[], columns: result.columns, returned: rows.length,
        total: rows.length, continuation: 'complete', hasMore: false,
        rowPositions: rows.map((_, index) => index), rowOrder: 'query-result',
        execution: { kind: 'owner', recipeId: 'urn:ddk:ad-hoc-sql', sqlSha256: result.sqlSha256,
          inputs: Object.keys(bindings), contextualRelationships: [], record: result.record,
          consumedBindings: input.bindings, elapsedMs: Date.now() - started,
          engine: { id: 'docspec', version: '0.1.0', binarySha256: catalog.docspecSha256 } } };
    } finally { active--; }
  };
  return {
    sql: { query },
    query: { query: async input => {
      if (Object.keys(input.parameters).length)
        return { status: 'refused', reason: 'This local SQL adapter requires parameter-free SQL.',
          bindings: input.bindings, rows: [], columns: [], returned: 0, transport: 'ddk-exact-json-v1' };
      const result = await query(input);
      return { ...result, ...(result.execution ? { execution: { ...result.execution, recipeId: input.recipeId } } : {}) };
    } },
    evidence: async ({ record }) => {
      const selected = records.get(record.uri);
      if (!selected || selected.sha256 !== record.sha256)
        fail('evidence_refused', 'The record is not a retained local query attempt.', 409);
      if ((await stat(selected.path)).size > LIMITS.fileBytes)
        fail('evidence_budget', 'The retained query evidence exceeds the display allowance.', 413);
      const bytes = await readFile(selected.path);
      if (sha256(bytes) !== selected.sha256) fail('integrity_mismatch', 'The query evidence changed.', 409);
      return { record, document: parseExactData(bytes.toString('utf8')), scope: 'Retained local query attempt; no managed selection.' };
    },
  };
}
