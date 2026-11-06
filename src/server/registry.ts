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
    mode: 'application',
    directory: resolve(process.cwd(), 'fixtures/applications/spicy-regs'),
    lockSha256: 'c7b5f8a50a4679822282fb2b04e621e0f1175a2afe33bf51fd08dbfb60f4021d',
  },
  {
    id: 'congress',
    navigationLabel: 'Congress archive public catalog',
    mode: 'application',
    directory: resolve(process.cwd(), 'fixtures/applications/congress'),
    lockSha256: 'f34c92d4e2f4460ca043aa73fdd11fd6b9b04cee127c5f872cee7829807686f2',
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
