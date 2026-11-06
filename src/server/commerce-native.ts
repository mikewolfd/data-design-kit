import { spawn } from 'node:child_process';
import { createReadStream } from 'node:fs';
import { lstat, mkdir, readdir, realpath, writeFile } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';
import { exactObjectEntries, isObject, parseExactData, parseMetadata } from '../domain/exact';
import type { EvidenceResult, ExactBinding, ExactObject, RecordRef } from '../domain/types';
import type { OwnerReader, OwnerQuery } from './access';
import { fail, sha256, ViewerError, type CatalogRegistration } from './catalog-store';

const CAPTURE_SHA = '884cf9dc7676187c17f7bd668151672a4c3d9d98edf5409c7fab18af287a0f72';
const CATALOG_SHA = 'c323123b5bfc65c23c2fd2710dcbf6c02fdd5ae1f0f351fc9ba30d31e958ae83';
const SQL_SHA = 'ca01fbd8506181c0f7a4766c61712613a32f8882007b2a941247b13703183670';
const DATA_SHA = 'ff0efd8f35eb3b64e23a2f195cbfd2c9989173020b4681ae783bc0f2301ba4c6';
const NATIVE_SHA = 'b89b43e2d2bf17f8d87ff1d9a779e06c3a024f2777e2327a8f048c6cb00a2532';
const VERSION =
  'urn:ddk:file-version:737bacee2ec6b3ada9d212f8206e4905647dc155ff71433646a645054d6a8e50';
const REPRESENTATION =
  'urn:ddk:representation:cb241944dad0e60e968aed2f1db0d5dfc3e1a364595a525dd8b4ef814bdc30d8';
const DATASET = 'urn:example:commerce:dataset:daily-revenue';
const RECIPE = 'urn:example:commerce:recipe:checked-revenue';
const RELEASE = 'urn:test:reference:release';
const PYTHON =
  '/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/relationship-profiles/distribution/qualified-01/env-full/bin/python';
const ROOT = resolve(process.cwd());
const CAPTURE = resolve(ROOT, 'fixtures/applications/commerce-native');
const WORK = resolve(ROOT, 'work/native-consumer');
export const commerceQuota = Object.freeze({
  attempts: 32,
  retainedBytes: 16 * 1024 * 1024,
  bridgeProcesses: 1,
  evidenceBytes: 1024 * 1024,
  outputBytes: 128 * 1024,
  cleanupGraceMs: 2000,
});
export const commerceRegistration: CatalogRegistration = {
  id: 'commerce-native',
  navigationLabel: 'Commerce · retained native result',
  mode: 'application',
  directory: CAPTURE,
  lockSha256: 'b36d8196f9eefa332f2580bcfd3684bbf7f94506fab0e2cc2064e4f23ef34c2d',
};
export const commerceScope = Object.freeze({
  datasetIds: [DATASET],
  recipeIds: [RECIPE],
  description:
    'A complete three-row read of one exact retained Parquet result through the qualified DDK and DocSpec bounded reader. Native query order; no paginated order guarantee, transformation, quality rerun or managed candidate acceptance.',
});
type EvidenceEntry = { path: string; record: RecordRef; scope: string };
const issued = new Map<string, EvidenceEntry>();
let original: Promise<Map<string, EvidenceEntry>> | undefined;
let originalDataPath: string | undefined;
let active = false,
  unsettled = false;
const evidenceKey = (record: RecordRef) => `${record.uri}\0${record.sha256 ?? ''}`;

async function readBounded(
  path: string,
  deadline: number,
  signal?: AbortSignal,
  cap = commerceQuota.evidenceBytes,
): Promise<Buffer> {
  if (signal?.aborted || Date.now() >= deadline)
    fail('deadline', 'The owner evidence deadline elapsed.', 408);
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
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
async function originalEvidence(): Promise<Map<string, EvidenceEntry>> {
  if (!original)
    original = (async () => {
      const bytes = await readBounded(resolve(CAPTURE, 'capture.json'), Date.now() + 5000);
      if (sha256(bytes) !== CAPTURE_SHA)
        fail('integrity_mismatch', 'The exact native catalog capture changed.', 409);
      const capture = parseMetadata(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
      originalDataPath = resolve(capture.sourceRoot, 'run/substrait-result.parquet');
      return new Map<string, EvidenceEntry>(
        capture.files.map((entry: any): [string, EvidenceEntry] => {
          const path = resolve(CAPTURE, entry.path);
          if (!path.startsWith(CAPTURE + sep))
            fail(
              'evidence_refused',
              'A retained evidence entry leaves its registered directory.',
              409,
            );
          const record = { uri: entry.uri, sha256: entry.sha256 };
          return [evidenceKey(record), { path, record, scope: entry.scope }];
        }),
      );
    })().catch((error) => {
      original = undefined;
      throw error;
    });
  return original!;
}
async function restoreIssued(deadline: number, signal?: AbortSignal) {
  let folders;
  try {
    folders = await readdir(WORK, { withFileTypes: true });
  } catch (error: any) {
    if (error.code === 'ENOENT') return;
    throw error;
  }
  if (folders.length > commerceQuota.attempts)
    fail('native_quota', 'The retained owner evidence exceeds its attempt quota.', 413);
  for (const folder of folders) {
    if (!folder.isDirectory() || !/^[a-f0-9-]{36}$/.test(folder.name)) continue;
    const attempt = resolve(WORK, folder.name);
    let requestBytes;
    try {
      requestBytes = await readBounded(resolve(attempt, 'viewer-request.json'), deadline, signal);
    } catch (error: any) {
      if (error.code === 'ENOENT') continue;
      throw error;
    }
    const request = parseMetadata(new TextDecoder('utf-8', { fatal: true }).decode(requestBytes));
    if (
      request.attempt !== attempt ||
      request.binding?.datasetId !== DATASET ||
      request.binding?.versionId !== VERSION ||
      request.binding?.representationId !== REPRESENTATION ||
      (request.binding?.releaseId !== undefined && request.binding.releaseId !== RELEASE) ||
      request.recipeId !== RECIPE ||
      !['read', 'query'].includes(request.operation) ||
      request.offset !== 0 ||
      !Number.isSafeInteger(request.limit) ||
      request.limit < 3 ||
      request.limit > 100 ||
      (request.catalogSha256 !== undefined && request.catalogSha256 !== CATALOG_SHA)
    )
      continue;
    let nativeEntry: EvidenceEntry | undefined;
    try {
      const resultBytes = await readBounded(
        resolve(attempt, 'bridge-result.json'),
        deadline,
        signal,
      );
      const result = parseMetadata(new TextDecoder('utf-8', { fatal: true }).decode(resultBytes));
      if (
        typeof result.evidence?.path === 'string' &&
        /^[a-f0-9]{64}$/.test(result.evidence.sha256)
      ) {
        const path = await realpath(result.evidence.path);
        if (path.startsWith(attempt + sep) && path.endsWith('/receipt.json')) {
          const bytes = await readBounded(path, deadline, signal);
          const receipt = parseMetadata(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
          if (
            sha256(bytes) === result.evidence.sha256 &&
            receipt.tool?.distributionSha256 === NATIVE_SHA &&
            receipt.inputs?.length === 1 &&
            receipt.inputs[0].sha256 === DATA_SHA &&
            receipt.inputs[0].path === originalDataPath &&
            receipt.inputs[0].name === 'daily_revenue' &&
            receipt.operation?.selection === 'not_requested' &&
            receipt.operation?.outputs?.length === 0
          ) {
            const record = { uri: pathToFileURL(path).href, sha256: result.evidence.sha256 };
            nativeEntry = { path, record, scope: 'new-consumer-read' };
          }
        }
      }
    } catch (error: any) {
      if (error.code !== 'ENOENT') throw error;
    }
    // Early retained attempts predate the explicit catalog digest field. Admit them only
    // when a native receipt independently binds the same full file/version request.
    if (request.catalogSha256 === undefined && !nativeEntry) continue;
    const path = resolve(attempt, 'viewer-request.json');
    const record = { uri: pathToFileURL(path).href, sha256: sha256(requestBytes) };
    issued.set(evidenceKey(record), { path, record, scope: 'viewer-read-attempt' });
    if (nativeEntry) issued.set(evidenceKey(nativeEntry.record), nativeEntry);
  }
}
/** Exact URI+digest lookup only. HTTP callers never select a filesystem path. */
export async function readCommerceEvidence(
  record: RecordRef,
  options: { deadline?: number; signal?: AbortSignal } = {},
): Promise<EvidenceResult> {
  if (!isObject(record) || typeof record.uri !== 'string' || typeof record.sha256 !== 'string')
    fail('evidence_refused', 'An exact registered evidence URI and digest are required.', 400);
  const deadline = options.deadline ?? Date.now() + 5000;
  const originals = await originalEvidence();
  if (!issued.has(evidenceKey(record)) && !originals.has(evidenceKey(record)))
    await restoreIssued(deadline, options.signal);
  const entry = issued.get(evidenceKey(record)) ?? originals.get(evidenceKey(record));
  if (!entry)
    fail(
      'evidence_refused',
      'This record is outside the exact native-consumer evidence allowlist.',
      404,
    );
  const path = await realpath(entry.path),
    root = issued.has(evidenceKey(record)) ? WORK : CAPTURE;
  if (!path.startsWith(root + sep))
    fail('evidence_refused', 'The registered evidence left its retained directory.', 409);
  const bytes = await readBounded(path, options.deadline ?? Date.now() + 5000, options.signal);
  if (sha256(bytes) !== record.sha256)
    fail('integrity_mismatch', 'The exact owner evidence bytes changed.', 409);
  return {
    record: entry.record,
    document: parseExactData(new TextDecoder('utf-8', { fatal: true }).decode(bytes)),
    scope: entry.scope,
  };
}
async function retainedUsage(directory: string): Promise<number> {
  let bytes = 0,
    entries = 0;
  async function scan(path: string) {
    for (const item of await readdir(path, { withFileTypes: true })) {
      if (++entries > 1024)
        fail('native_quota', 'The retained native-consumer evidence exceeds its file quota.', 413);
      const next = resolve(path, item.name),
        stat = await lstat(next);
      if (stat.isSymbolicLink())
        fail(
          'native_quota',
          'The viewer evidence directory contains an unsupported symbolic link.',
          409,
        );
      if (stat.isDirectory()) await scan(next);
      else bytes += stat.size;
      if (bytes > commerceQuota.retainedBytes)
        fail(
          'native_quota',
          'The retained native-consumer evidence exceeds its byte quota. Existing evidence remains intact.',
          413,
        );
    }
  }
  await scan(directory);
  return bytes;
}
function checkedBinding(binding: ExactBinding) {
  if (
    binding.datasetId !== DATASET ||
    binding.versionId !== VERSION ||
    binding.representationId !== REPRESENTATION ||
    (binding.releaseId !== undefined && binding.releaseId !== RELEASE)
  )
    fail(
      'native_scope_refused',
      'This native reader supports only the exact retained revenue dataset/version/representation.',
      409,
    );
}
async function nativeRead(input: {
  snapshot: { id: string; audience: string; identity: { catalogSha256: string } };
  binding: ExactBinding;
  limit: number;
  offset: number;
  deadline: number;
  signal: AbortSignal;
  operation: 'read' | 'query';
  onAttempt?: (record: RecordRef) => void;
}) {
  checkedBinding(input.binding);
  if (
    input.snapshot.id !== commerceRegistration.id ||
    input.snapshot.audience !== 'local' ||
    input.snapshot.identity.catalogSha256 !== CATALOG_SHA
  )
    fail(
      'native_scope_refused',
      'This adapter requires the exact retained local commerce catalog.',
      409,
    );
  if (input.offset !== 0 || input.limit < 3 || input.limit > 100)
    fail(
      'native_page_refused',
      'This native integration reads the complete three-row result. Use limit >= 3 and offset 0; its SQL has no stable pagination order.',
      400,
    );
  if (active || unsettled)
    fail('native_busy', 'A native reader is active or its completion remains unresolved.', 503);
  if (input.signal.aborted || Date.now() >= input.deadline)
    fail('deadline', 'The native read deadline elapsed before submission.', 408);
  active = true;
  try {
    await mkdir(WORK, { recursive: true });
    const folders = await readdir(WORK, { withFileTypes: true });
    if (folders.length >= commerceQuota.attempts)
      fail(
        'native_quota',
        'The finite native-consumer attempt quota is full. Retained successes and failures remain intact.',
        413,
      );
    await retainedUsage(WORK);
    const attempt = resolve(WORK, randomUUID());
    await mkdir(attempt);
    const request = {
      operation: input.operation,
      binding: input.binding,
      limit: input.limit,
      offset: input.offset,
      attempt,
      parameters: {},
      recipeId: RECIPE,
      catalogSha256: CATALOG_SHA,
      scope:
        'This is a pre-execution viewer request. Native submission and consumption are not established by this record.',
    };
    const requestBytes = JSON.stringify(request),
      requestPath = resolve(attempt, 'viewer-request.json');
    await writeFile(requestPath, requestBytes);
    const attemptRecord = { uri: pathToFileURL(requestPath).href, sha256: sha256(requestBytes) };
    issued.set(evidenceKey(attemptRecord), {
      path: requestPath,
      record: attemptRecord,
      scope: 'viewer-read-attempt',
    });
    input.onAttempt?.(attemptRecord);
    const output = await new Promise<Buffer>((resolveOutput, reject) => {
      const child = spawn(PYTHON, ['-B', resolve(ROOT, 'scripts/commerce-native-bridge.py')], {
        cwd: ROOT,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      const stdout: Buffer[] = [],
        stderr: Buffer[] = [];
      let count = 0,
        errorCount = 0,
        hardKilled = false;
      let grace: ReturnType<typeof setTimeout> | undefined;
      const requestCancellation = () => {
        child.kill('SIGTERM');
        if (!grace)
          grace = setTimeout(() => {
            hardKilled = true;
            unsettled = true;
            child.kill('SIGKILL');
          }, commerceQuota.cleanupGraceMs);
      };
      input.signal.addEventListener('abort', requestCancellation, { once: true });
      const deadline = setTimeout(requestCancellation, Math.max(1, input.deadline - Date.now()));
      child.stdout.on('data', (bytes: Buffer) => {
        count += bytes.length;
        if (count > commerceQuota.outputBytes) requestCancellation();
        else stdout.push(bytes);
      });
      child.stderr.on('data', (bytes: Buffer) => {
        errorCount += bytes.length;
        if (errorCount <= commerceQuota.outputBytes) stderr.push(bytes);
        else requestCancellation();
      });
      child.once('error', reject);
      child.once('close', async () => {
        clearTimeout(deadline);
        clearTimeout(grace);
        input.signal.removeEventListener('abort', requestCancellation);
        try {
          await writeFile(resolve(attempt, 'bridge-stderr.log'), Buffer.concat(stderr));
        } catch {
          reject(
            new ViewerError(
              'owner_deadline',
              `Viewer diagnostic retention failed; native attempt ${attemptRecord.uri} SHA-256 ${attemptRecord.sha256} remains retained.`,
              408,
            ),
          );
          return;
        }
        if (
          hardKilled ||
          count > commerceQuota.outputBytes ||
          errorCount > commerceQuota.outputBytes
        )
          reject(
            new ViewerError(
              'owner_deadline',
              `Native read outcome is unknown; attempt ${attemptRecord.uri} SHA-256 ${attemptRecord.sha256} remains retained.`,
              408,
            ),
          );
        else resolveOutput(Buffer.concat(stdout));
      });
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify(request));
    });
    const outputText = new TextDecoder('utf-8', { fatal: true }).decode(output);
    const answer = parseMetadata(outputText);
    let record: RecordRef | undefined;
    if (answer.evidence) {
      const path = await realpath(answer.evidence.path);
      if (!path.startsWith(attempt + sep) || !/^[a-f0-9]{64}$/.test(answer.evidence.sha256))
        fail('native_receipt_refused', 'The native receipt is outside its exact attempt.', 409);
      record = { uri: pathToFileURL(path).href, sha256: answer.evidence.sha256 };
      issued.set(evidenceKey(record), { path, record, scope: 'new-consumer-read' });
      await readCommerceEvidence(record, { deadline: Date.now() + 1000 });
    }
    if (answer.status !== 'succeeded' || !record) {
      const identity = answer.operation?.requestIdentity?.value;
      fail(
        answer.status === 'unknown' ? 'owner_deadline' : 'native_read_refused',
        `The native read did not establish a complete result. Attempt ${attemptRecord.uri} SHA-256 ${attemptRecord.sha256}${identity ? `; original native request ${identity}` : ''} remains retained.`,
        409,
      );
    }
    await retainedUsage(WORK);
    const exact = parseExactData(outputText) as any;
    if (
      !Array.isArray(exact.rows) ||
      exact.rows.length !== 3 ||
      answer.sqlSha256 !== SQL_SHA ||
      answer.binding?.inputs?.daily_revenue?.id !== VERSION ||
      answer.operation?.selection !== 'not_requested' ||
      answer.operation?.outputs?.length !== 0
    )
      fail(
        'native_receipt_refused',
        'The actual native result does not match this bounded read.',
        409,
      );
    return { rows: exact.rows as ExactObject[], record };
  } finally {
    active = false;
  }
}
export function createCommerceAdapter(): { reader: OwnerReader; query: OwnerQuery } {
  return {
    reader: {
      supportedDatasetIds: commerceScope.datasetIds,
      description: commerceScope.description,
      read: async (input) => {
        const result = await nativeRead({ ...input, operation: 'read' });
        return {
          ...result,
          rowPositions: [0, 1, 2],
          rowOrder: 'query-result',
          total: 3,
          hasMore: false,
          consumed: input.binding,
        };
      },
    },
    query: {
      supportedRecipeIds: commerceScope.recipeIds,
      description: commerceScope.description,
      query: async (input) => {
        if (
          input.recipeId !== RECIPE ||
          Object.keys(input.parameters).length ||
          Object.keys(input.bindings).length !== 1 ||
          !input.bindings.daily_revenue ||
          sha256(input.sql) !== SQL_SHA
        )
          fail(
            'native_scope_refused',
            'Only the exact registered parameter-free checked-revenue SQL is supported.',
            409,
          );
        const result = await nativeRead({
          snapshot: input.snapshot,
          binding: input.bindings.daily_revenue,
          offset: 0,
          limit: input.limit,
          deadline: input.deadline,
          signal: input.signal,
          onAttempt: input.onAttempt,
          operation: 'query',
        });
        return {
          status: 'ok',
          bindings: input.bindings,
          rows: result.rows,
          columns: [
            ...new Set(result.rows.flatMap((row) => exactObjectEntries(row).map(([key]) => key))),
          ],
          returned: 3,
          total: 3,
          hasMore: false,
          continuation: 'complete',
          rowPositions: [0, 1, 2],
          rowOrder: 'query-result',
          transport: 'ddk-exact-json-v1',
          execution: {
            kind: 'owner',
            recipeId: RECIPE,
            sqlSha256: SQL_SHA,
            inputs: ['daily_revenue'],
            contextualRelationships: [],
            record: result.record,
          },
        };
      },
    },
  };
}
