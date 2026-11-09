import { createReadStream } from 'node:fs';
import { resolve } from 'node:path';
import { parseMetadata } from '../domain/exact';
import { fail, sha256, type CatalogStore } from './catalog-store';
export type ImpactRegistration = { catalogId: string; directory: string; bindingSha256: string };
async function readPinned(path: string, digest: string, deadline: number) {
  if (Date.now() >= deadline) fail('impact_timeout', 'The impact read exceeded its deadline.', 408);
  const chunks: Buffer[] = [];
  let size = 0;
  const stream = createReadStream(path, {
    highWaterMark: 32 * 1024,
    signal: AbortSignal.timeout(Math.max(1, deadline - Date.now())),
  });
  try {
    for await (const part of stream) {
      size += part.length;
      if (size > 1024 * 1024) fail('impact_budget', 'The impact artifact exceeds 1 MiB.', 413);
      chunks.push(part as Buffer);
    }
  } finally {
    stream.destroy();
  }
  const bytes = Buffer.concat(chunks);
  if (sha256(bytes) !== digest)
    fail('impact_mismatch', 'The owner impact artifact differs from its exact binding.', 409);
  return parseMetadata(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
}
export async function loadImpact(
  store: CatalogStore,
  registrations: readonly ImpactRegistration[],
  catalogId: string,
  catalogSha256: string,
) {
  const deadline = Date.now() + 5000;
  const { snapshot } = await store.load(catalogId, deadline);
  if (snapshot.identity.catalogSha256 !== catalogSha256)
    fail('snapshot_mismatch', 'The comparison request names another catalog snapshot.', 409);
  const registration = registrations.find((r) => r.catalogId === catalogId);
  if (!registration)
    return {
      available: false,
      reason: 'No owner impact report is registered for this exact catalog.',
    };
  const root = resolve(process.cwd(), registration.directory);
  const binding = await readPinned(
    resolve(root, 'binding.json'),
    registration.bindingSha256,
    deadline,
  );
  if (binding.candidateCatalogSha256 !== catalogSha256)
    fail('impact_mismatch', 'The impact report names a different candidate snapshot.', 409);
  const [base, report] = await Promise.all([
    readPinned(resolve(root, 'base.catalog.ddk.json'), binding.baseCatalogSha256, deadline),
    readPinned(resolve(root, 'impact.report.json'), binding.reportSha256, deadline),
  ]);
  if (
    base.audience !== snapshot.catalog.audience ||
    base.kind !== 'catalog' ||
    report.kind !== 'report'
  )
    fail('impact_scope', 'The comparison audience or document kinds do not match.', 409);
  return { available: true, binding, base, report };
}
