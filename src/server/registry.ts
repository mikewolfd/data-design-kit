import { resolve } from 'node:path';
import { CatalogAccess, type OwnerEvidenceReader } from './access';
import { CatalogStore, fail, type CatalogRegistration } from './catalog-store';
import { fixturePins } from './fixture-pins';
import {
  commerceRegistration,
  createCommerceAdapter,
  readCommerceEvidence,
} from './commerce-native';

/** Operator-selected, read-only discovery inputs. No runtime paths arrive from HTTP. */
export const applicationRegistrations: readonly CatalogRegistration[] = [
  {
    id: 'spicy-regs',
    navigationLabel: 'SpicyRegs public catalog',
    navigationDescription:
      'Find descriptions of data about U.S. rules, legislation, courts, campaign finance and public spending. Records are not connected to this portal.',
    mode: 'application',
    directory: resolve(process.cwd(), 'fixtures/applications/spicy-regs'),
    lockSha256: 'd7cac836f87f4194894fd78fca11ce137ab859c08e1c90fe104ad7657817776d',
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
const registrations = [...applicationRegistrations, commerceRegistration];
const selected = (process.env.DDK_VIEWER_APPLICATIONS ?? '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);
if (selected.some((id) => !registrations.some((row) => row.id === id)))
  fail(
    'invalid_registration',
    'DDK_VIEWER_APPLICATIONS accepts spicy-regs, congress, and commerce-native.',
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
export const access = new CatalogAccess(
  store,
  new Map(
    selected.includes(commerceRegistration.id)
      ? [
          [
            commerceRegistration.id,
            {
              ...createCommerceAdapter(),
              evidence: commerceEvidence,
            },
          ],
        ]
      : [],
  ),
);
