import { resolve } from 'node:path';
import { CatalogAccess, type OwnerAdapters, type OwnerEvidenceReader } from './access';
import { CatalogStore, fail, type CatalogRegistration } from './catalog-store';
import { fixturePins } from './fixture-pins';
import {
  commerceRegistration,
  createCommerceAdapter,
  readCommerceEvidence,
} from './commerce-native';
import {
  congressRegistration,
  congressSupportedDatasetIds,
  createCongressAdapter,
} from './congress-registration';
import { loadOperatorOwnerConfig } from './docspec-owner';

/** Operator-selected, read-only discovery inputs. No runtime paths arrive from HTTP. */
export const applicationRegistrations: readonly CatalogRegistration[] = [
  {
    id: 'spicy-regs',
    catalogId: 'urn:spicy-regs:definition-catalog',
    navigationLabel: 'SpicyRegs public catalog',
    navigationDescription:
      'Find descriptions of data about U.S. rules, legislation, courts, campaign finance and public spending. Records are not connected to this portal.',
    mode: 'application',
    directory: resolve(process.cwd(), 'fixtures/applications/spicy-regs'),
    lockSha256: '7d9073510323146c61a87d77d0caf4b47cf498538b0eb6da0832063756713d83',
  },
  {
    id: 'congress',
    catalogId: 'urn:congressional-tech:archive:catalog',
    navigationLabel: 'Congress archive public catalog',
    navigationDescription:
      'Explore descriptions of congressional hearings, documents, witnesses, bills and recordings. Records are not connected to this portal.',
    mode: 'application',
    directory: resolve(process.cwd(), 'fixtures/applications/congress'),
    lockSha256: '26967938b6e9e5bb067f8be52f798deb38ef2288449498b6cdde1373eddc7801',
  },
];

const audience = process.env.DDK_VIEWER_AUDIENCE === 'local' ? 'local' : 'public';
const builtinRegistrations = [
  ...applicationRegistrations,
  commerceRegistration,
  congressRegistration,
];

const operatorConfigPath = process.env.DDK_VIEWER_OWNER_CONFIG?.trim();
const operatorLoaded = operatorConfigPath
  ? await loadOperatorOwnerConfig(operatorConfigPath, audience)
  : { registrations: [], owners: new Map() };
const operatorIds = new Set(operatorLoaded.registrations.map((row) => row.id));

const selected = (process.env.DDK_VIEWER_APPLICATIONS ?? '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);

if (
  selected.some(
    (id) => !builtinRegistrations.some((row) => row.id === id) && !operatorIds.has(id),
  )
) {
  fail(
    'invalid_registration',
    'DDK_VIEWER_APPLICATIONS accepts spicy-regs, congress, commerce-native, congress-authored, or IDs from DDK_VIEWER_OWNER_CONFIG.',
  );
}

export const store = new CatalogStore(
  [
    ...(process.env.DDK_VIEWER_INCLUDE_EXAMPLES === '0' ? [] : fixturePins).map((row) => ({
      ...row,
      navigationLabel: row.id === 'watershed' ? 'Watershed observatory' : 'Public-service grants',
      directory: resolve(process.cwd(), 'fixtures', row.id),
      mode: 'fixture' as const,
    })),
    ...builtinRegistrations.filter(
      (row) => selected.includes(row.id) && !operatorIds.has(row.id),
    ),
    ...operatorLoaded.registrations,
  ],
  audience,
);

const adapters = new Map<string, OwnerAdapters>();
for (const [id, owner] of operatorLoaded.owners) {
  adapters.set(id, owner);
}

if (
  audience === 'local' &&
  selected.includes(commerceRegistration.id) &&
  !adapters.has(commerceRegistration.id)
) {
  const commerceEvidence: OwnerEvidenceReader = ({ record, deadline, signal }) =>
    readCommerceEvidence(record, { deadline, signal });
  const commerceOwner = await createCommerceAdapter();
  adapters.set(commerceRegistration.id, {
    ...commerceOwner,
    evidence: commerceEvidence,
  });
}

if (
  audience === 'local' &&
  selected.includes(congressRegistration.id) &&
  !adapters.has(congressRegistration.id)
) {
  const snapshot = await store.snapshot(congressRegistration.id);
  adapters.set(
    congressRegistration.id,
    await createCongressAdapter({
      snapshot,
      supportedDatasetIds: congressSupportedDatasetIds(snapshot),
    }),
  );
}

export const access = new CatalogAccess(store, adapters);
