import { createReadStream } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { exactObjectField, isObject, parseMetadata } from '../domain/exact';
import type { CatalogSnapshot, ExactBinding, ExactValue, RecordRef } from '../domain/types';
import { fail, sha256, type CatalogRegistration } from './catalog-store';
import { DEFAULT_DDK_SRC, DEFAULT_PYTHON } from './commerce-native';
import {
  createDocSpecCatalogOwner,
  encodeExactOwnerValue,
  type DocSpecCatalogOwner,
} from './docspec-owner';

const DIRECTORY = resolve(process.cwd(), 'fixtures/applications/congress-authored');
const CATALOG_SHA = 'e45c819098623a7edc352230ce839691e3d954d28bd0abac56bd12afd8d2a834';
const HANDOFF_SHA = 'b59c3cc000613cbc202906300d93f0619f5e9a948223de84462015145ba71e62';
const CAPTURE_SHA = '9e3c5957f4a4c5a3b0118a886a1e9c54e148e9d13029d5bb542ae2328ab81349';
export const congressRegistration: CatalogRegistration = {
  id: 'congress-authored',
  mode: 'application',
  exampleData: 'authored',
  navigationLabel: 'Congress archive — authored local example',
  navigationDescription:
    'Explore saved records from a small authored Congress example. This is synthetic example data.',
  directory: DIRECTORY,
  lockSha256: 'efed16b4e287e1eb585e01c0512c0109d638fba4fea5225b2365793f29bf7ba8',
};
export type CongressDataInput = Readonly<{
  name: string;
  path: string;
  sha256: string;
  size: number;
  rows: number;
  datasetId: string;
  datasetAlias: string;
  versionId: string;
  representationId: string;
}>;
export type CongressInputs = {
  /** Native release provenance only; the standard catalog declares no release membership. */
  releaseId: string;
  files: Readonly<Record<string, string>>;
  manifest: Record<string, any>;
  data: ReadonlyMap<string, CongressDataInput>;
  handoffRecord: RecordRef;
  originalManifestRecord: RecordRef;
};
type ReadOptions = { deadline?: number; signal?: AbortSignal };
function checkedSnapshot(snapshot: CatalogSnapshot) {
  if (
    snapshot.id !== congressRegistration.id ||
    snapshot.audience !== 'local' ||
    snapshot.catalog.audience !== 'local' ||
    snapshot.identity.catalogSha256 !== CATALOG_SHA ||
    snapshot.identity.lockSha256 !== congressRegistration.lockSha256 ||
    snapshot.catalog.releases.length ||
    snapshot.catalog.selections.length
  )
    fail(
      'binding_mismatch',
      'The Congress inputs require the pinned LOCAL source20 catalog with no release or selection claims.',
      409,
    );
}
/** Materialized dataset identities, not a declaration that every native mapping is qualified. */
export function congressSupportedDatasetIds(snapshot: CatalogSnapshot): readonly string[] {
  checkedSnapshot(snapshot);
  const aliases = new Set(snapshot.catalog.versions.map((row) => row.dataset));
  return Object.freeze(
    snapshot.catalog.datasets.filter((row) => aliases.has(row.alias)).map((row) => row.id),
  );
}
async function checkedJson(path: string, expectedSha: string, options: ReadOptions): Promise<any> {
  const deadline = options.deadline ?? Date.now() + 5000;
  if (options.signal?.aborted || Date.now() >= deadline)
    fail('deadline', 'The Congress metadata read was cancelled or timed out.', 408);
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
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
      if (count > 1024 * 1024)
        fail('evidence_budget', 'The Congress metadata exceeds its 1 MiB read budget.', 413);
      chunks.push(bytes);
    }
    const bytes = Buffer.concat(chunks, count);
    if (sha256(bytes) !== expectedSha)
      fail('integrity_mismatch', 'The pinned Congress metadata bytes changed.', 409);
    return parseMetadata(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}
export async function loadCongressInputs(
  snapshot: CatalogSnapshot,
  options: ReadOptions = {},
): Promise<CongressInputs> {
  checkedSnapshot(snapshot);
  // One absolute deadline covers all metadata reads. No payload files are read or copied here.
  options = { ...options, deadline: options.deadline ?? Date.now() + 5000 };
  const capture = await checkedJson(resolve(DIRECTORY, 'capture.json'), CAPTURE_SHA, options);
  const handoff = await checkedJson(resolve(DIRECTORY, 'handoff.json'), HANDOFF_SHA, options);
  const dataInventory = await checkedJson(
    resolve(DIRECTORY, 'data-files.json'),
    handoff.dataInventory.sha256,
    options,
  );
  const files = await checkedJson(
    resolve(DIRECTORY, 'original-files.json'),
    handoff.originalInputs.inventory.sha256,
    options,
  );
  // Check retained indexes against their original publisher records before using original paths.
  await checkedJson(
    handoff.originalInputs.inventory.path,
    handoff.originalInputs.inventory.sha256,
    options,
  );
  await checkedJson(fileURLToPath(capture.handoffRecord.uri), HANDOFF_SHA, options);
  const manifestPath = files['manifest.json'];
  if (pathToFileURL(manifestPath).href !== capture.originalManifestRecord.uri)
    fail('binding_mismatch', 'The original Congress manifest path changed.', 409);
  const manifest = await checkedJson(manifestPath, capture.originalManifestRecord.sha256, options);
  if (
    manifest.release_id !== handoff.originalReleaseId ||
    !Array.isArray(manifest.files) ||
    Object.keys(dataInventory).length !== 17
  )
    fail('binding_mismatch', 'The Congress publisher input inventory is incomplete.', 409);
  const data = new Map<string, CongressDataInput>();
  for (const [name, raw] of Object.entries(dataInventory)) {
    const row = raw as any;
    const dataset = snapshot.catalog.datasets.find((entry) => entry.alias === row.dataset);
    const matches = manifest.files.filter((entry: any) => entry.name === name);
    if (
      !dataset ||
      files[name] !== row.path ||
      matches.length !== 1 ||
      matches[0].sha256 !== row.sha256 ||
      matches[0].size !== row.size ||
      matches[0].rows !== row.rows ||
      !Number.isSafeInteger(row.size) ||
      row.size < 0 ||
      !Number.isSafeInteger(row.rows) ||
      row.rows < 0 ||
      data.has(dataset.id)
    )
      fail(
        'binding_mismatch',
        'The Congress file index differs from the original publisher manifest.',
        409,
      );
    const entry = Object.freeze({
      name,
      path: row.path,
      sha256: row.sha256,
      size: row.size,
      rows: row.rows,
      datasetId: dataset.id,
      datasetAlias: dataset.alias,
      versionId: row.version,
      representationId: row.representation,
    });
    data.set(dataset.id, entry);
  }
  const inputs: CongressInputs = {
    releaseId: handoff.originalReleaseId,
    files: Object.freeze(files),
    manifest,
    data,
    handoffRecord: Object.freeze(capture.handoffRecord),
    originalManifestRecord: Object.freeze(capture.originalManifestRecord),
  };
  for (const entry of data.values()) bindCongressInput(inputs, snapshot, entry);
  return inputs;
}
export function bindCongressInput(
  inputs: CongressInputs,
  snapshot: CatalogSnapshot,
  binding: ExactBinding,
): CongressDataInput {
  checkedSnapshot(snapshot);
  if (binding.releaseId !== undefined)
    fail(
      'release_mismatch',
      'This Congress catalog declares no standard release membership; its native release is provenance only.',
      409,
    );
  const entry = inputs.data.get(binding.datasetId);
  const dataset = snapshot.catalog.datasets.find((row) => row.id === binding.datasetId);
  const version = snapshot.catalog.versions.find((row) => row.id === binding.versionId);
  const representation = snapshot.catalog.representations.find(
    (row) => row.id === binding.representationId,
  );
  const value = version?.reference?.value;
  if (
    !entry ||
    !dataset ||
    entry.datasetAlias !== dataset.alias ||
    entry.versionId !== binding.versionId ||
    entry.representationId !== binding.representationId ||
    version?.dataset !== dataset.alias ||
    representation?.version !== version?.id ||
    version?.referenceDisclosure === 'withheld' ||
    version?.retention !== 'present' ||
    representation?.availability !== 'available' ||
    representation?.kind !== 'file' ||
    representation?.mediaType !== 'application/vnd.apache.parquet' ||
    version?.reference?.scheme !== 'urn:ddk:version:local-file-sha256' ||
    version?.reference?.authority !== 'urn:ddk:local-file' ||
    !isObject(value) ||
    exactObjectField(value, 'location') !== pathToFileURL(entry.path).href ||
    exactObjectField(value, 'sha256') !== entry.sha256 ||
    representation.location !== exactObjectField(value, 'location') ||
    inputs.files[entry.name] !== entry.path
  )
    fail(
      'binding_mismatch',
      'Dataset, version, representation and exact original file reference must match the Congress publisher facts.',
      409,
    );
  return entry;
}

export function encodeCongressValue(
  value: unknown,
  owner: {
    isArchiveDateValue: (value: unknown) => boolean;
    isArchiveTimestampValue: (value: unknown) => boolean;
  },
): ExactValue {
  return encodeExactOwnerValue(value, {
    isDateValue: owner.isArchiveDateValue,
    isTimestampValue: owner.isArchiveTimestampValue,
  });
}

/** Thin configuration wrapper around startup-pinned DocSpecCatalogOwner for congress-authored. */
export async function createCongressAdapter(options: {
  snapshot: CatalogSnapshot;
  pythonPath?: string;
  ddkSrcPath?: string;
  docspecBinary?: string;
  docspecSha256?: string;
  supportedDatasetIds?: readonly string[];
}): Promise<DocSpecCatalogOwner> {
  const inputs = await loadCongressInputs(options.snapshot);
  const dataDirs = [...new Set([...inputs.data.values()].map((item) => dirname(item.path)))];
  const manifestDir = dirname(fileURLToPath(inputs.originalManifestRecord.uri));
  return createDocSpecCatalogOwner({
    directory: DIRECTORY,
    lockSha256: congressRegistration.lockSha256,
    pythonPath: options.pythonPath ?? process.env.DDK_VIEWER_PYTHON ?? DEFAULT_PYTHON,
    ddkSrcPath: options.ddkSrcPath ?? process.env.DDK_VIEWER_DDK_SRC ?? DEFAULT_DDK_SRC,
    ...(options.docspecBinary ? { docspecBinary: options.docspecBinary } : {}),
    ...(options.docspecSha256 ? { docspecSha256: options.docspecSha256 } : {}),
    permittedRoots: [DIRECTORY, manifestDir, ...dataDirs],
    supportedDatasetIds:
      options.supportedDatasetIds ?? congressSupportedDatasetIds(options.snapshot),
    description:
      'Read saved authored Congress Parquet records through startup-pinned DocSpecCatalogOwner.',
    resolveReadShards: async ({ snapshot, binding }) => {
      const entry = bindCongressInput(inputs, snapshot, binding);
      return {
        shards: [
          {
            path: entry.path,
            sha256: entry.sha256,
            byteSize: entry.size,
            rowCount: entry.rows,
          },
        ],
        extraDetails: {
          releaseId: inputs.releaseId,
          file: {
            name: entry.name,
            sha256: entry.sha256,
            size: entry.size,
            rows: entry.rows,
          },
          originalManifest: inputs.originalManifestRecord,
          localCatalogHandoff: inputs.handoffRecord,
          ownerModule: {
            entry: 'docspec-owner-bridge.py',
            configuration: { sha256: congressRegistration.lockSha256 },
          },
        },
      };
    },
  });
}
