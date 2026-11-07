import { resolve } from 'node:path';
import { CatalogStore } from '../../src/server/catalog-store';

// Optional retained owner metadata. Pins identify the original 24-check pair;
// tests never select payload files or register a reader in the application.
export const spicyPairDirectory = process.env.DDK_VIEWER_SPICY_PAIR_DIRECTORY;
export const spicyPairPins = {
  public: '4f2b2ca60fe6a1bd1800632f4178add8e2dac583076d75b94ab13081a8fefdd3',
  local: '5b90add54870a67a29052ed5f2248b349bddd87c1634b2d9ca17ddffbcea87d8',
} as const;

export function spicyPairSnapshot(audience: 'public' | 'local') {
  if (!spicyPairDirectory) throw new Error('DDK_VIEWER_SPICY_PAIR_DIRECTORY is required.');
  const id = `spicy-pair-${audience}`;
  return new CatalogStore(
    [
      {
        id,
        directory: resolve(spicyPairDirectory, audience === 'local' ? 'private' : 'public'),
        lockSha256: spicyPairPins[audience],
        mode: 'application',
      },
    ],
    audience,
  ).snapshot(id);
}
