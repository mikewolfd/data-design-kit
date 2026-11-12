import { readdir, realpath } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isObject, parseExactData, parseMetadata } from '../domain/exact';
import type { EvidenceResult, RecordRef } from '../domain/types';
import { fail, sha256, type CatalogRegistration } from './catalog-store';
import {
  createDocSpecCatalogOwner,
  DEFAULT_DOCSPEC_BINARY,
  DEFAULT_DOCSPEC_SHA256,
  evidenceMapKey,
  readBoundedBytes,
  type DocSpecCatalogOwner,
  type EvidenceMapEntry,
} from './docspec-owner';

export { DEFAULT_DOCSPEC_BINARY, DEFAULT_DOCSPEC_SHA256 };

const CAPTURE_SHA = '2b2dfa95deccf0c8240926bcb568d8e396bfdc6128034f6a704df7a7c1510834';
const DATASET = 'urn:example:commerce:dataset:daily-revenue';
const RECIPE = 'urn:example:commerce:recipe:checked-revenue';

const ROOT = resolve(process.cwd());
const CAPTURE = resolve(ROOT, 'fixtures/applications/commerce-native');
const WORK = resolve(ROOT, 'work/native-consumer');

export const commerceRegistration: CatalogRegistration = {
  id: 'commerce-native',
  navigationLabel: 'Commerce example — saved daily revenue result',
  navigationDescription:
    'Explore a saved three-record result from the commerce example. Daily revenue is the only dataset you can view here.',
  mode: 'application',
  exampleData: 'authored',
  directory: CAPTURE,
  lockSha256: 'efd61cc7f5de0fec81fec7f4750805030e21dbfa6d6ffeb7393dc56bc4504f82',
};

export const commerceScope = Object.freeze({
  datasetIds: [DATASET],
  recipeIds: [RECIPE],
  description:
    'View records in the saved daily revenue result and run the checked-revenue recipe through startup-pinned DocSpecCatalogOwner.',
});

type CaptureMetadata = {
  sourceRoot: string;
  entries: Map<string, EvidenceMapEntry>;
};

let captureCache: Promise<CaptureMetadata> | undefined;

async function loadCommerceCapture(): Promise<CaptureMetadata> {
  if (!captureCache) {
    captureCache = (async () => {
      const bytes = await readBoundedBytes(
        resolve(CAPTURE, 'capture.json'),
        Date.now() + 5000,
        undefined,
        1024 * 1024,
      );
      if (sha256(bytes) !== CAPTURE_SHA)
        fail('integrity_mismatch', 'The exact native catalog capture changed.', 409);
      const capture = parseMetadata(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
      const entries = new Map<string, EvidenceMapEntry>();
      for (const item of capture.files) {
        const path = resolve(CAPTURE, item.path);
        if (!path.startsWith(CAPTURE + sep))
          fail(
            'evidence_refused',
            'A retained evidence entry leaves its registered directory.',
            409,
          );
        const record: RecordRef = { uri: item.uri, sha256: item.sha256 };
        entries.set(evidenceMapKey(record), { path, record, scope: item.scope });
      }
      return { sourceRoot: resolve(capture.sourceRoot), entries };
    })().catch((error) => {
      captureCache = undefined;
      throw error;
    });
  }
  return captureCache;
}

async function scanHistoricalWorkEvidence(
  record: RecordRef,
  deadline: number,
  signal?: AbortSignal,
): Promise<EvidenceMapEntry | undefined> {
  let folders;
  try {
    folders = await readdir(WORK, { withFileTypes: true });
  } catch (error: any) {
    if (error?.code === 'ENOENT') return undefined;
    throw error;
  }
  for (const folder of folders) {
    if (!folder.isDirectory()) continue;
    const base = resolve(WORK, folder.name);
    for (const rel of ['viewer-request.json', 'runtime/receipt.json', 'receipt.json']) {
      const candidate = resolve(base, rel);
      try {
        const real = await realpath(candidate);
        if (!real.startsWith(WORK + sep)) continue;
        if (pathToFileURL(real).href !== record.uri) continue;
        const bytes = await readBoundedBytes(real, deadline, signal, 4 * 1024 * 1024);
        if (sha256(bytes) === record.sha256) {
          return {
            path: real,
            record: { uri: record.uri, sha256: record.sha256 },
            scope: rel === 'viewer-request.json' ? 'viewer-read-attempt' : 'new-consumer-read',
          };
        }
      } catch {
        continue;
      }
    }
  }
  return undefined;
}

/** Exact URI + digest lookup for retained commerce capture and replay evidence. */
export async function readCommerceEvidence(
  record: RecordRef,
  options: { deadline?: number; signal?: AbortSignal } = {},
): Promise<EvidenceResult> {
  if (!isObject(record) || typeof record.uri !== 'string' || typeof record.sha256 !== 'string')
    fail('evidence_refused', 'An exact registered evidence URI and digest are required.', 400);
  if (!/^[a-f0-9]{64}$/.test(record.sha256))
    fail('evidence_refused', 'An exact registered evidence URI and digest are required.', 400);
  const deadline = options.deadline ?? Date.now() + 5000;
  const capture = await loadCommerceCapture();
  const entry =
    capture.entries.get(evidenceMapKey(record)) ??
    (await scanHistoricalWorkEvidence(record, deadline, options.signal));
  if (!entry)
    fail(
      'evidence_refused',
      'This record is outside the exact native-consumer evidence allowlist.',
      404,
    );
  const real = await realpath(entry.path);
  if (!real.startsWith(CAPTURE + sep) && !real.startsWith(WORK + sep))
    fail('evidence_refused', 'The registered evidence left its retained directory.', 409);
  const bytes = await readBoundedBytes(real, deadline, options.signal, 4 * 1024 * 1024);
  if (sha256(bytes) !== record.sha256)
    fail('integrity_mismatch', 'The exact owner evidence bytes changed.', 409);
  return {
    record: entry.record,
    document: parseExactData(new TextDecoder('utf-8', { fatal: true }).decode(bytes)),
    scope: entry.scope,
  };
}

/** Thin configuration wrapper around startup-pinned DocSpecCatalogOwner for commerce-native. */
export async function createCommerceAdapter(options?: {
  docspecBinary?: string;
  docspecSha256?: string;
  retainReceiptsDir?: string;
}): Promise<DocSpecCatalogOwner> {
  const capture = await loadCommerceCapture();
  return createDocSpecCatalogOwner({
    directory: CAPTURE,
    lockSha256: commerceRegistration.lockSha256,
    docspecBinary:
      options?.docspecBinary ?? process.env.DDK_VIEWER_DOCSPEC_BINARY ?? DEFAULT_DOCSPEC_BINARY,
    docspecSha256:
      options?.docspecSha256 ?? process.env.DDK_VIEWER_DOCSPEC_SHA256 ?? DEFAULT_DOCSPEC_SHA256,
    permittedRoots: [CAPTURE, capture.sourceRoot],
    supportedDatasetIds: commerceScope.datasetIds,
    supportedRecipeIds: commerceScope.recipeIds,
    description: commerceScope.description,
    evidenceAllowlistOnly: true,
    evidenceUriMap: capture.entries,
    ...(options?.retainReceiptsDir ? { retainReceiptsDir: options.retainReceiptsDir } : {}),
  });
}
