import { resolve } from 'node:path';
import { CatalogAccess, type OwnerAdapters, type OwnerEvidenceReader } from './access';
import { CatalogStore, fail, type CatalogRegistration } from './catalog-store';
import { fixturePins } from './fixture-pins';
import {
  commerceRegistration,
  createCommerceAdapter,
  readCommerceEvidence,
} from './commerce-native';
import { congressRegistration, congressSupportedDatasetIds } from './congress-registration';
import { createCongressAdapter } from './congress-reader';

/** Operator-selected, read-only discovery inputs. No runtime paths arrive from HTTP. */
export const applicationRegistrations: readonly CatalogRegistration[] = [
  {
    id: 'spicy-regs',
    navigationLabel: 'SpicyRegs public catalog',
    navigationDescription:
      'Find descriptions of data about U.S. rules, legislation, courts, campaign finance and public spending. Records are not connected to this portal.',
    mode: 'application',
    directory: resolve(process.cwd(), 'fixtures/applications/spicy-regs'),
    lockSha256: 'd2bae6877c2047e9d867a2b496f42a3057ae6cb36cc8a861c14c11d59533d7d2',
  },
  {
    id: 'congress',
    navigationLabel: 'Congress archive public catalog',
    navigationDescription:
      'Explore descriptions of congressional hearings, documents, witnesses, bills and recordings. Records are not connected to this portal.',
    mode: 'application',
    directory: resolve(process.cwd(), 'fixtures/applications/congress'),
    lockSha256: '26967938b6e9e5bb067f8be52f798deb38ef2288449498b6cdde1373eddc7801',
  },
];
const registrations = [...applicationRegistrations, commerceRegistration, congressRegistration];
const selected = (process.env.DDK_VIEWER_APPLICATIONS ?? '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);
if (selected.some((id) => !registrations.some((row) => row.id === id)))
  fail(
    'invalid_registration',
    'DDK_VIEWER_APPLICATIONS accepts spicy-regs, congress, commerce-native, and congress-authored.',
  );
export const store = new CatalogStore(
  [
    ...fixturePins.map((row) => ({
      ...row,
      navigationLabel: row.id === 'watershed' ? 'Watershed observatory' : 'Public-service grants',
      directory: resolve(process.cwd(), 'fixtures', row.id),
      mode: 'fixture' as const,
    })),
    ...registrations.filter((row) => selected.includes(row.id)),
  ],
  process.env.DDK_VIEWER_AUDIENCE === 'local' ? 'local' : 'public',
);
const commerceEvidence: OwnerEvidenceReader = ({ record, deadline, signal }) =>
  readCommerceEvidence(record, { deadline, signal });
const adapters = new Map<string, OwnerAdapters>();
if (selected.includes(commerceRegistration.id))
  adapters.set(commerceRegistration.id, {
    ...createCommerceAdapter(),
    evidence: commerceEvidence,
  });
const congressConfig = process.env.DDK_VIEWER_CONGRESS_OWNER_CONFIG;
const congressConfigSha = process.env.DDK_VIEWER_CONGRESS_OWNER_CONFIG_SHA256;
if (congressConfig || congressConfigSha) {
  if (!congressConfig || !congressConfigSha || !selected.includes(congressRegistration.id))
    fail(
      'invalid_registration',
      'Select congress-authored and supply both owner configuration path and SHA-256.',
    );
  const snapshot = await store.snapshot(congressRegistration.id);
  adapters.set(
    congressRegistration.id,
    await createCongressAdapter({
      configPath: congressConfig,
      configSha256: congressConfigSha,
      supportedDatasetIds: congressSupportedDatasetIds(snapshot),
    }),
  );
}
export const access = new CatalogAccess(store, adapters);
